"""
Unit tests for scripts/rotate_secret.py (the unified CI-plane rotation engine).

All external I/O (requests, filesystem) is mocked; real NaCl crypto is used for the
encryption round-trips so the seal/open is actually verified.
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from nacl import encoding
from nacl.public import PrivateKey, SealedBox

import rotate_secret as rs
from rotate_secret import (
    _encrypt_secret,
    _get_env_public_key,
    _github_headers,
    _list_vercel_env_vars,
    _parse_filter,
    _refuse_if_terraform_managed,
    _select_secrets,
    _vercel_headers,
    cmd_check,
    cmd_generate,
    cmd_paste,
    create_vercel_token,
    delete_vercel_token,
    list_vercel_tokens,
    update_github_env_secret,
    upsert_vercel_env_var,
)

ALL = frozenset()


# ── fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def nacl_keypair():
    private = PrivateKey.generate()
    pub_b64 = private.public_key.encode(encoding.Base64Encoder).decode()
    return private, pub_b64


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _past(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.fixture
def sample_registry():
    return {
        "secrets": [
            {
                "name": "GH_PACKAGES_PAT",
                "kind": "paste",
                "per_env": False,
                "value_staging_secret": "SECRET_VALUE_NEW",
                "check": {"expiry": _future(60), "warn_days_before_expiry": 14},
                "github_env_secrets": [
                    {"repo": "Needless2Say/kriegerdataforge", "environment": "prod", "secret_name": "GH_PACKAGES_PAT"},
                    {"repo": "Needless2Say/fitness-app-backend", "environment": "dev", "secret_name": "GH_PACKAGES_PAT"},
                ],
                "vercel_env_vars": [
                    {"project_id": "prj_real_1", "project_name": "kdf-prod", "environment": "prod", "env_key": "GH_PACKAGES_PAT"},
                    {"project_id": "TODO_x", "project_name": "kdf-dev", "environment": "dev", "env_key": "GH_PACKAGES_PAT"},
                ],
            },
            {
                "name": "VERCEL_TOKEN",
                "kind": "generate",
                "generator": "vercel_token",
                "per_env": True,
                "github_env_secrets": [
                    {"app": "auth-backend", "repo": "Needless2Say/kriegerdataforge", "environment": "prod", "secret_name": "VERCEL_TOKEN", "vercel_token_name": "kdf-auth-backend-prod"},
                    {"app": "fitness-frontend", "repo": "Needless2Say/fitness-app-frontend", "environment": "dev", "secret_name": "VERCEL_TOKEN", "vercel_token_name": "kdf-fitness-frontend-dev"},
                ],
            },
            {
                "name": "VERCEL_SHARED",
                "kind": "generate",
                "generator": "vercel_token",
                "shared": True,
                "vercel_token_name": "kdf-deploy-shared",
                "github_env_secrets": [
                    {"app": "a", "repo": "Needless2Say/r1", "environment": "prod", "secret_name": "VERCEL_TOKEN"},
                    {"app": "a", "repo": "Needless2Say/r1", "environment": "dev", "secret_name": "VERCEL_TOKEN"},
                    {"app": "b", "repo": "Needless2Say/r2", "environment": "prod", "secret_name": "VERCEL_TOKEN"},
                ],
            },
            {
                "name": "CI_HMAC",
                "kind": "generate",
                "generator": "random_urlsafe",
                "per_env": True,
                "github_env_secrets": [
                    {"repo": "Needless2Say/a", "environment": "prod", "secret_name": "CI_HMAC"},
                    {"repo": "Needless2Say/b", "environment": "prod", "secret_name": "CI_HMAC"},
                    {"repo": "Needless2Say/a", "environment": "dev", "secret_name": "CI_HMAC"},
                ],
            },
            {
                "name": "DB_DATABASE_URL",
                "kind": "paste",
                "terraform_managed": True,
                "github_env_secrets": [],
            },
        ]
    }


@pytest.fixture
def mock_registry_file(sample_registry):
    mock_path = MagicMock(spec=Path)
    mock_path.is_file.return_value = True
    mock_path.read_text.return_value = json.dumps(sample_registry)
    with patch.object(rs, "REGISTRY_FILE", mock_path):
        yield mock_path


# ── helpers: headers / crypto / api primitives (parity with the retired scripts) ──


class TestHeaders:
    def test_github_bearer_and_version(self):
        h = _github_headers("ghp_x")
        assert h["Authorization"] == "Bearer ghp_x"
        assert h["X-GitHub-Api-Version"] == "2022-11-28"
        assert "application/vnd.github+json" in h["Accept"]

    def test_vercel_bearer(self):
        h = _vercel_headers("v")
        assert h["Authorization"] == "Bearer v"
        assert h["Content-Type"] == "application/json"


class TestEncrypt:
    def test_round_trip(self, nacl_keypair):
        private, pub = nacl_keypair
        enc = _encrypt_secret(pub, "s3cr3t")
        assert SealedBox(private).decrypt(base64.b64decode(enc)).decode() == "s3cr3t"

    def test_nondeterministic(self, nacl_keypair):
        _, pub = nacl_keypair
        assert _encrypt_secret(pub, "x") != _encrypt_secret(pub, "x")


class TestGetEnvPublicKey:
    def test_returns_key(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v=="}
        with patch("requests.get", return_value=r):
            assert _get_env_public_key("gh", "o", "rp", "prod") == ("k", "v==")

    def test_url_has_owner_repo_env(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v"}
        with patch("requests.get", return_value=r) as g:
            _get_env_public_key("gh", "Own", "Rep", "stg")
        url = g.call_args[0][0]
        assert "Own" in url and "Rep" in url and "stg" in url


class TestUpdateGitHubEnvSecret:
    def test_puts_encrypted_value(self, nacl_keypair):
        private, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "kid", "key": pub}
        with patch("requests.get", return_value=gr), patch("requests.put") as put:
            update_github_env_secret("gh", "o/r", "prod", "S", "val")
        body = put.call_args[1]["json"]
        assert body["key_id"] == "kid"
        assert SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"])).decode() == "val"

    def test_raises_on_put_failure(self, nacl_keypair):
        _, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "k", "key": pub}
        pr = MagicMock(); pr.raise_for_status.side_effect = Exception("HTTP 422")
        with patch("requests.get", return_value=gr), patch("requests.put", return_value=pr):
            with pytest.raises(Exception, match="HTTP 422"):
                update_github_env_secret("gh", "o/r", "prod", "S", "v")


class TestVercelTokenApi:
    def test_create_returns_id_and_bearer(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch("requests.post", return_value=r) as p:
            assert create_vercel_token("m", "n") == ("tid", "bv")
        assert p.call_args[1]["json"]["name"] == "n"
        assert "expiresAt" in p.call_args[1]["json"]

    def test_list_returns_tokens(self):
        r = MagicMock(); r.json.return_value = {"tokens": [{"id": "1", "name": "a"}]}
        with patch("requests.get", return_value=r):
            assert list_vercel_tokens("m") == [{"id": "1", "name": "a"}]

    def test_delete_hits_token_id(self):
        with patch("requests.delete", return_value=MagicMock()) as d:
            delete_vercel_token("m", "tok_9")
        assert "tok_9" in d.call_args[0][0]


class TestUpsertVercelEnvVar:
    def test_post_when_absent(self):
        lr = MagicMock(); lr.json.return_value = {"envs": []}
        with patch("requests.get", return_value=lr), patch("requests.post", return_value=MagicMock()) as post, patch("requests.patch") as pat:
            upsert_vercel_env_var("m", "prj", "K", "v")
        assert post.call_args[1]["json"]["key"] == "K"
        assert set(post.call_args[1]["json"]["target"]) == {"production", "preview", "development"}
        pat.assert_not_called()

    def test_patch_existing_only_matching_key(self):
        lr = MagicMock(); lr.json.return_value = {"envs": [
            {"id": "e1", "key": "K", "target": ["production"]},
            {"id": "e2", "key": "OTHER", "target": ["production"]},
        ]}
        with patch("requests.get", return_value=lr), patch("requests.patch", return_value=MagicMock()) as pat, patch("requests.post") as post:
            upsert_vercel_env_var("m", "prj", "K", "v")
        assert pat.call_count == 1 and "e1" in pat.call_args[0][0]
        post.assert_not_called()

    def test_list_returns_empty_when_absent(self):
        r = MagicMock(); r.json.return_value = {}
        with patch("requests.get", return_value=r):
            assert _list_vercel_env_vars("m", "prj") == []


# ── parse_filter / select / guards ────────────────────────────────────────────


class TestParseFilter:
    def test_all_and_empty_match_all(self):
        assert _parse_filter("all") == ALL and _parse_filter("") == ALL and _parse_filter("ALL") == ALL

    def test_comma_lowercased_trimmed(self):
        assert _parse_filter("Foo, BAR,") == frozenset({"foo", "bar"})


class TestSelectSecrets:
    def test_empty_selects_all(self, sample_registry):
        assert len(_select_secrets(sample_registry, ALL)) == 5

    def test_named_subset(self, sample_registry):
        got = _select_secrets(sample_registry, frozenset({"vercel_token"}))
        assert [e["name"] for e in got] == ["VERCEL_TOKEN"]

    def test_unknown_exits(self, sample_registry):
        with pytest.raises(SystemExit, match="unknown secret"):
            _select_secrets(sample_registry, frozenset({"nope"}))


class TestTerraformGuard:
    def test_refuses_tf_managed(self):
        with pytest.raises(SystemExit, match="Terraform-managed"):
            _refuse_if_terraform_managed({"name": "DB", "terraform_managed": True})

    def test_allows_normal(self):
        _refuse_if_terraform_managed({"name": "X"})  # no raise


# ── check mode ──────────────────────────────────────────────────────────────────


class TestCheck:
    def _e(self, expiry, warn=14):
        return {"name": "S", "check": {"expiry": expiry, "warn_days_before_expiry": warn}}

    def test_ok_far_future(self):
        assert cmd_check([self._e(_future(60))]) == 0

    def test_warn_within_threshold(self):
        assert cmd_check([self._e(_future(7), warn=14)]) == 1

    def test_expired(self):
        assert cmd_check([self._e(_past(1))]) == 1

    def test_todo_expiry(self):
        assert cmd_check([self._e("TODO")]) == 1

    def test_invalid_date(self):
        assert cmd_check([self._e("01/01/2030")]) == 1

    def test_no_check_block_is_ok(self):
        assert cmd_check([{"name": "S"}]) == 0

    def test_aggregate_rc_any_bad(self):
        assert cmd_check([self._e(_future(60)), self._e(_past(1))]) == 1

    def test_emits_needs_rotation_line_with_only_unhealthy(self, capsys):
        cmd_check([
            {"name": "A", "check": {"expiry": _past(1)}},
            {"name": "B", "check": {"expiry": _future(60)}},
            {"name": "C", "kind": "manual", "check": {"expiry": "TODO_set"}},
        ])
        out = capsys.readouterr().out
        assert "NEEDS_ROTATION: A,C" in out  # B (healthy) excluded; manual TODO flagged

    def test_emits_empty_needs_line_when_all_healthy(self, capsys):
        rc = cmd_check([{"name": "X", "check": {"expiry": _future(60)}}, {"name": "Y"}])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NEEDS_ROTATION: \n" in out


class TestRealRegistry:
    """The actual scripts/secret_registry.json must parse and run an offline check."""

    def test_loads_with_monitored_tokens_and_checks_offline(self):
        reg = rs._load_registry()  # reads the real REGISTRY_FILE
        entries = _select_secrets(reg, ALL)
        names = {e["name"] for e in entries}
        assert {"GH_PACKAGES_PAT", "VERCEL_TOKEN", "CICD_PAT", "CICD_REGISTRY_PAT", "VERCEL_MASTER_TOKEN"} <= names
        assert "KDF_APP_PRIVATE_KEY" in names  # the GitHub App private key is monitored too
        assert "VERCEL_API_TOKEN" in names  # terraform mgmt token, split out from the shared deploy token
        vercel = next(e for e in entries if e["name"] == "VERCEL_TOKEN")
        assert vercel.get("shared") is True and vercel.get("vercel_token_name") == "kdf-deploy-shared"
        # the manual tokens carry a check block (monitored) and no engine targets
        for name in ("CICD_PAT", "CICD_REGISTRY_PAT", "VERCEL_MASTER_TOKEN", "KDF_APP_PRIVATE_KEY"):
            e = next(x for x in entries if x["name"] == name)
            assert e.get("kind") == "manual" and "check" in e
            assert not e.get("github_env_secrets") and not e.get("vercel_env_vars")
        assert cmd_check(entries) in (0, 1)


# ── generate: vercel_token ──────────────────────────────────────────────────────


class TestGenerateVercelToken:
    def _entry(self, sample_registry):
        return [e for e in sample_registry["secrets"] if e["name"] == "VERCEL_TOKEN"]

    def test_creates_per_target_and_writes(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token"):
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "master")
        assert rc == 0
        assert create.call_count == 2
        assert upd.call_count == 2

    def test_app_filter(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), frozenset({"auth-backend"}), ALL, "gh", "m")
        assert create.call_count == 1
        assert create.call_args[0][1] == "kdf-auth-backend-prod"

    def test_env_filter(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), ALL, frozenset({"dev"}), "gh", "m")
        assert create.call_count == 1
        assert create.call_args[0][1] == "kdf-fitness-frontend-dev"

    def test_deletes_old_when_id_differs(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-auth-backend-prod", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "v")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token") as dele:
            cmd_generate(self._entry(sample_registry), frozenset({"auth-backend"}), ALL, "gh", "m")
        dele.assert_called_once_with("m", "old")

    def test_partial_failure_returns_1(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", side_effect=Exception("boom")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            assert cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m") == 1

    def test_missing_master_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match="VERCEL_MASTER_TOKEN"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "")

    def test_missing_gh_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match="GH_TOKEN"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "", "m")


# ── generate: vercel_token (shared) ──────────────────────────────────────────────


class TestGenerateSharedVercelToken:
    def _entry(self, sample_registry):
        return [e for e in sample_registry["secrets"] if e["name"] == "VERCEL_SHARED"]

    def test_mints_once_and_fans_out_same_value(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "shared-val")) as create, \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "master")
        assert rc == 0
        assert create.call_count == 1                       # ONE token minted...
        assert create.call_args[0][1] == "kdf-deploy-shared"
        assert upd.call_count == 3                          # ...written to all 3 targets...
        assert {c[0][4] for c in upd.call_args_list} == {"shared-val"}  # ...with the SAME value
        dele.assert_not_called()                            # no prior token to delete

    def test_ignores_app_and_env_filters(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "v")) as create, \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), frozenset({"a"}), frozenset({"dev"}), "gh", "m")
        assert create.call_count == 1
        assert upd.call_count == 3                          # all targets, despite the filters

    def test_deletes_old_shared_token_when_all_writes_succeed(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "v")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 0
        dele.assert_called_once_with("m", "old")

    def test_keeps_old_token_when_a_write_fails(self, sample_registry):
        # middle write fails -> old token must NOT be deleted, so both stay valid (no dead repo)
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "v")), \
             patch.object(rs, "update_github_env_secret", side_effect=[None, Exception("boom"), None]), \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1
        dele.assert_not_called()

    def test_mint_failure_writes_nothing(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", side_effect=Exception("mint boom")), \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1
        upd.assert_not_called()
        dele.assert_not_called()

    def test_delete_failure_is_soft_error_not_a_crash(self, sample_registry):
        # all writes succeed, then the cleanup DELETE raises -> must return 1 (soft error), NOT crash,
        # and every target must still have been written (the new token is already live).
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "v")), \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token", side_effect=Exception("delete boom")) as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1                      # soft error, surfaced via _summary — not a traceback
        assert upd.call_count == 3          # every target still written
        dele.assert_called_once_with("m", "old")  # cleanup was attempted

    def test_reaps_all_duplicate_old_tokens(self, sample_registry):
        # two pre-existing tokens share the name -> BOTH must be deleted (a name->id map would miss one)
        with patch.object(rs, "list_vercel_tokens", return_value=[
                 {"name": "kdf-deploy-shared", "id": "old1"},
                 {"name": "kdf-deploy-shared", "id": "old2"},
                 {"name": "unrelated", "id": "keep"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "v")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 0
        deleted = {c[0][1] for c in dele.call_args_list}
        assert deleted == {"old1", "old2"}  # both duplicates reaped, unrelated token untouched

    def test_missing_entry_token_name_errors_without_minting(self):
        entry = [{
            "name": "BAD_SHARED", "kind": "generate", "generator": "vercel_token", "shared": True,
            "github_env_secrets": [{"repo": "Needless2Say/x", "environment": "prod", "secret_name": "VERCEL_TOKEN"}],
        }]  # no entry-level vercel_token_name
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token") as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            rc = cmd_generate(entry, ALL, ALL, "gh", "m")
        assert rc == 1                       # clean error, not a KeyError traceback
        create.assert_not_called()           # bailed before minting any token


# ── generate: random_urlsafe (per-env) ──────────────────────────────────────────


class TestGenerateRandom:
    def _entry(self, sample_registry):
        return [e for e in sample_registry["secrets"] if e["name"] == "CI_HMAC"]

    def test_per_env_values_distinct_across_envs_shared_within(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as upd:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "")
        assert rc == 0 and upd.call_count == 3
        # call args: (gh, repo, environment, secret_name, value)
        by_env = {}
        for c in upd.call_args_list:
            by_env.setdefault(c[0][2], set()).add(c[0][4])
        assert len(by_env["prod"]) == 1  # two prod targets share one value
        assert len(by_env["dev"]) == 1
        assert by_env["prod"] != by_env["dev"]  # distinct per environment

    def test_env_filter_limits_targets(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as upd:
            cmd_generate(self._entry(sample_registry), ALL, frozenset({"dev"}), "gh", "")
        assert upd.call_count == 1

    def test_terraform_managed_entry_refused(self, sample_registry):
        tf = [e for e in sample_registry["secrets"] if e["name"] == "DB_DATABASE_URL"]
        with pytest.raises(SystemExit, match="Terraform-managed"):
            cmd_generate(tf, ALL, ALL, "gh", "m")


# ── paste mode ──────────────────────────────────────────────────────────────────


class TestPaste:
    def _entry(self, sample_registry):
        return next(e for e in sample_registry["secrets"] if e["name"] == "GH_PACKAGES_PAT")

    def test_fans_to_gh_and_real_vercel_skips_todo(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc:
            rc = cmd_paste(self._entry(sample_registry), ALL, "gh", "master", "the-value")
        assert rc == 0
        assert gh.call_count == 2
        # only the real Vercel project (prj_real_1) is written; TODO_x skipped
        vc.assert_called_once()
        assert vc.call_args[0][1] == "prj_real_1"
        assert vc.call_args[0][3] == "the-value"

    def test_env_filter_narrows_gh_targets(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var"):
            cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "gh", "master", "v")
        assert gh.call_count == 1
        assert gh.call_args[0][1] == "Needless2Say/kriegerdataforge"

    def test_missing_value_exits(self, sample_registry):
        with pytest.raises(SystemExit, match="STAGED_SECRET_VALUE"):
            cmd_paste(self._entry(sample_registry), ALL, "gh", "m", "")

    def test_missing_gh_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match="GH_TOKEN"):
            cmd_paste(self._entry(sample_registry), ALL, "", "m", "v")

    def test_vercel_skipped_without_master(self, sample_registry):
        with patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "upsert_vercel_env_var") as vc:
            cmd_paste(self._entry(sample_registry), ALL, "gh", "", "v")
        vc.assert_not_called()

    def test_partial_gh_failure_returns_1_but_attempts_all(self, sample_registry):
        n = [0]

        def flaky(*a, **k):
            n[0] += 1
            if n[0] == 1:
                raise Exception("fail one")

        with patch.object(rs, "update_github_env_secret", side_effect=flaky), \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry(sample_registry), ALL, "gh", "", "v")
        assert rc == 1 and n[0] == 2

    def test_terraform_managed_refused(self, sample_registry):
        tf = next(e for e in sample_registry["secrets"] if e["name"] == "DB_DATABASE_URL")
        with pytest.raises(SystemExit, match="Terraform-managed"):
            cmd_paste(tf, ALL, "gh", "m", "v")


# ── CLI + main dispatch ─────────────────────────────────────────────────────────


class TestCli:
    def test_requires_mode(self):
        with pytest.raises(SystemExit):
            rs.parse_cli_args([])

    def test_defaults(self):
        a = rs.parse_cli_args(["--mode", "check"])
        assert a.secrets == "all" and a.apps == "all" and a.envs == "all"


class TestMain:
    def test_check_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "check"])
        with patch.object(rs, "cmd_check", return_value=0) as c:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and c.called

    def test_generate_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "generate", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        with patch.object(rs, "cmd_generate", return_value=0) as g:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and g.called

    def test_paste_requires_single_secret(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "paste", "--secrets", "all"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        with pytest.raises(SystemExit, match="exactly one secret"):
            rs.main()

    def test_paste_single_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "paste", "--secrets", "GH_PACKAGES_PAT"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("STAGED_SECRET_VALUE", "v")
        with patch.object(rs, "cmd_paste", return_value=0) as p:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and p.called

    def test_missing_registry_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "check"])
        mp = MagicMock(spec=Path); mp.is_file.return_value = False
        with patch.object(rs, "REGISTRY_FILE", mp):
            with pytest.raises(SystemExit):
                rs.main()
