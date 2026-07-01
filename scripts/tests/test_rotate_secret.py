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
    _get_repo_public_key,
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
    delete_github_env_secret,
    delete_vercel_token,
    list_vercel_tokens,
    update_github_env_secret,
    update_github_repo_secret,
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


class TestGetRepoPublicKey:
    def test_returns_key(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v=="}
        with patch("requests.get", return_value=r):
            assert _get_repo_public_key("gh", "o", "rp") == ("k", "v==")

    def test_url_is_repo_level_actions_not_environment(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v"}
        with patch("requests.get", return_value=r) as g:
            _get_repo_public_key("gh", "Own", "Rep")
        url = g.call_args[0][0]
        assert "Own/Rep/actions/secrets/public-key" in url
        assert "environments" not in url  # repository-level, NOT an environment box


class TestUpdateGitHubRepoSecret:
    def test_puts_encrypted_value_to_repo_actions(self, nacl_keypair):
        private, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "kid", "key": pub}
        with patch("requests.get", return_value=gr), patch("requests.put") as put:
            update_github_repo_secret("gh", "o/r", "S", "val")
        url = put.call_args[0][0]
        assert "o/r/actions/secrets/S" in url
        assert "environments" not in url  # repo-level store, not env
        body = put.call_args[1]["json"]
        assert body["key_id"] == "kid"
        assert SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"])).decode() == "val"

    def test_raises_on_put_failure(self, nacl_keypair):
        _, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "k", "key": pub}
        pr = MagicMock(); pr.raise_for_status.side_effect = Exception("HTTP 422")
        with patch("requests.get", return_value=gr), patch("requests.put", return_value=pr):
            with pytest.raises(Exception, match="HTTP 422"):
                update_github_repo_secret("gh", "o/r", "S", "v")


class TestDeleteGitHubEnvSecret:
    def test_deletes_env_secret_at_correct_url(self):
        r = MagicMock(); r.status_code = 204
        with patch("requests.delete", return_value=r) as d:
            delete_github_env_secret("gh", "o/r", "prod", "S")
        assert "o/r/environments/prod/secrets/S" in d.call_args[0][0]

    def test_404_already_gone_is_tolerated(self):
        r = MagicMock(); r.status_code = 404
        r.raise_for_status.side_effect = Exception("must not be raised on 404")
        with patch("requests.delete", return_value=r):
            delete_github_env_secret("gh", "o/r", "prod", "S")  # idempotent no-op, no raise

    def test_other_status_raises(self):
        r = MagicMock(); r.status_code = 403
        r.raise_for_status.side_effect = Exception("HTTP 403")
        with patch("requests.delete", return_value=r):
            with pytest.raises(Exception, match="HTTP 403"):
                delete_github_env_secret("gh", "o/r", "prod", "S")


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

    def test_create_scopes_to_team_when_team_id_set(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch("requests.post", return_value=r) as p:
            create_vercel_token("m", "n", "team_abc")
        assert p.call_args[1]["params"] == {"teamId": "team_abc"}  # team-scoped

    def test_create_omits_team_param_when_no_team_id(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch("requests.post", return_value=r) as p:
            create_vercel_token("m", "n")
        assert p.call_args[1]["params"] is None

    def test_create_403_raises_master_scope_error(self):
        r = MagicMock(); r.status_code = 403
        with patch("requests.post", return_value=r):
            with pytest.raises(rs.VercelMasterScopeError, match="FULL ACCOUNT"):
                create_vercel_token("m", "n", "team_x")

    def test_list_403_raises_master_scope_error(self):
        r = MagicMock(); r.status_code = 403
        with patch("requests.get", return_value=r):
            with pytest.raises(rs.VercelMasterScopeError, match="FULL ACCOUNT"):
                list_vercel_tokens("m")


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
        assert {"GH_PACKAGES_PAT", "VERCEL_DEPLOYMENT_TOKEN", "CICD_PAT", "VERCEL_MASTER_TOKEN"} <= names
        assert "KDF_APP_PRIVATE_KEY" in names  # the GitHub App private key is monitored too
        # GH_PACKAGES_PAT must fan out to the repository-level CI secret in every backend
        # that installs the SDK in CI (a job with no `environment:` can't read env secrets).
        gh_pat = next(e for e in entries if e["name"] == "GH_PACKAGES_PAT")
        repo_targets = {t["repo"] for t in gh_pat.get("github_repo_secrets", [])}
        assert {
            "Needless2Say/kriegerdataforge",
            "Needless2Say/fitness-app-backend",
            "Needless2Say/tiffanys-space-backend",
            "Needless2Say/kriegerdataforge-template-fastapi",  # scaffold repo also installs the SDK in CI
        } <= repo_targets
        assert not gh_pat.get("github_env_secrets")  # repo-level only now
        assert len(gh_pat.get("retired_github_env_secrets", [])) == 6  # old prod/dev copies, reaped
        # consolidated 2026-06-30: the VERCEL_TOKEN + VERCEL_API_TOKEN split collapsed into one
        # account-scoped token, and the dormant CICD_REGISTRY_PAT entry was removed.
        assert not ({"VERCEL_TOKEN", "VERCEL_API_TOKEN", "CICD_REGISTRY_PAT"} & names)
        vercel = next(e for e in entries if e["name"] == "VERCEL_DEPLOYMENT_TOKEN")
        assert vercel.get("shared") is True and vercel.get("vercel_token_name") == "VERCEL_DEPLOYMENT_TOKEN"
        # one global token -> stored ONLY at repository level (no env copies); the former prod/dev
        # env secrets are listed for deletion so they can't shadow the repo value.
        assert not vercel.get("github_env_secrets")
        assert len(vercel["github_repo_secrets"]) == 7  # one repo secret per repo (6 apps + terraform)
        assert len(vercel["retired_github_env_secrets"]) == 14  # old prod/dev env copies, reaped on rotation
        assert vercel.get("check", {}).get("expiry")  # auto-maintained expiry is tracked (record-expiry bot)
        # the manual tokens carry a check block (monitored) and no engine targets
        for name in ("CICD_PAT", "VERCEL_MASTER_TOKEN", "KDF_APP_PRIVATE_KEY"):
            e = next(x for x in entries if x["name"] == name)
            assert e.get("kind") == "manual" and "check" in e
            assert not e.get("github_env_secrets") and not e.get("vercel_env_vars")
        assert cmd_check(entries) in (0, 1)


# ── record-expiry ───────────────────────────────────────────────────────────────


class TestRecordExpiry:
    def test_set_registry_expiry_is_scoped(self):
        # Two secrets share the SAME expiry; updating one must not bleed into the other.
        text = (
            '{ "secrets": [\n'
            '  { "name": "A", "check": { "expiry": "2026-07-30" } },\n'
            '  { "name": "B", "check": { "expiry": "2026-07-30" } }\n'
            "] }"
        )
        new, old = rs.set_registry_expiry(text, "B", "2026-09-15")
        assert old == "2026-07-30"
        got = {s["name"]: s["check"]["expiry"] for s in json.loads(new)["secrets"]}
        assert got == {"A": "2026-07-30", "B": "2026-09-15"}

    def test_set_registry_expiry_absent_secret_is_noop(self):
        text = '{ "secrets": [ { "name": "A", "check": { "expiry": "2026-07-30" } } ] }'
        new, old = rs.set_registry_expiry(text, "ZZZ", "2026-09-15")
        assert old is None and new == text

    def _write_reg(self, tmp_path, monkeypatch):
        # All three share 2026-07-30, but only the vercel_token-with-check entry may be touched.
        text = (
            "{\n"
            '  "secrets": [\n'
            '    { "name": "GH_PACKAGES_PAT", "kind": "paste", "check": { "expiry": "2026-07-30", "warn_days_before_expiry": 7 } },\n'
            '    { "name": "VERCEL_DEPLOYMENT_TOKEN", "kind": "generate", "generator": "vercel_token", "shared": true, "check": { "expiry": "2026-07-30", "warn_days_before_expiry": 10 } },\n'
            '    { "name": "CICD_PAT", "kind": "manual", "check": { "expiry": "2026-07-30", "warn_days_before_expiry": 14 } }\n'
            "  ]\n}"
        )
        f = tmp_path / "reg.json"
        f.write_text(text, encoding="utf-8")
        monkeypatch.setattr(rs, "REGISTRY_FILE", f)
        return f

    def test_stamps_only_vercel_token_with_check(self, tmp_path, monkeypatch, capsys):
        f = self._write_reg(tmp_path, monkeypatch)
        entries = json.loads(f.read_text())["secrets"]
        rc = rs.cmd_record_expiry(entries, today=datetime(2026, 6, 30, tzinfo=timezone.utc))
        assert rc == 0
        assert "REGISTRY_UPDATED: true" in capsys.readouterr().out
        got = {s["name"]: s["check"]["expiry"] for s in json.loads(f.read_text())["secrets"]}
        assert got["VERCEL_DEPLOYMENT_TOKEN"] == "2026-08-14"  # 2026-06-30 + 45d
        assert got["GH_PACKAGES_PAT"] == "2026-07-30"  # paste (no generator) -> skipped
        assert got["CICD_PAT"] == "2026-07-30"  # manual -> skipped

    def test_noop_when_expiry_already_current(self, tmp_path, monkeypatch, capsys):
        f = self._write_reg(tmp_path, monkeypatch)
        entries = json.loads(f.read_text())["secrets"]
        before = f.read_text()
        # 2026-06-15 + 45d == 2026-07-30, the value already in the registry → no write.
        rc = rs.cmd_record_expiry(entries, today=datetime(2026, 6, 15, tzinfo=timezone.utc))
        assert rc == 0
        assert "REGISTRY_UPDATED: false" in capsys.readouterr().out
        assert f.read_text() == before


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

    def test_master_scope_error_exits_cleanly(self, sample_registry):
        # a non-Full-Account master 403s on /v3/user/tokens -> clean SystemExit, not a traceback
        with patch.object(rs, "list_vercel_tokens", side_effect=rs.VercelMasterScopeError("needs FULL ACCOUNT")):
            with pytest.raises(SystemExit, match="FULL ACCOUNT"):
                cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m", "team_z")

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

    def test_forwards_team_id_to_create(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value=[]), \
             patch.object(rs, "create_vercel_token", return_value=("nid", "v")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m", "team_z")
        # every mint is scoped to the team (3rd positional arg of create_vercel_token)
        assert all(c[0][2] == "team_z" for c in create.call_args_list)


# ── generate: shared vercel_token → repo-level + retired-env reaping ─────────────


class TestGenerateSharedRepoLevel:
    """The shared VERCEL_DEPLOYMENT_TOKEN writes REPOSITORY secrets and reaps its retired
    per-environment copies; the old Vercel token is revoked only once the new value is live
    everywhere AND every env shadow is gone."""

    def _entry(self):
        return {
            "name": "VERCEL_DEPLOYMENT_TOKEN", "kind": "generate", "generator": "vercel_token",
            "shared": True, "vercel_token_name": "kdf-deploy",
            "github_repo_secrets": [
                {"repo": "Needless2Say/a", "secret_name": "VERCEL_DEPLOYMENT_TOKEN"},
                {"repo": "Needless2Say/b", "secret_name": "VERCEL_DEPLOYMENT_TOKEN"},
            ],
            "retired_github_env_secrets": [
                {"repo": "Needless2Say/a", "environment": "prod", "secret_name": "VERCEL_DEPLOYMENT_TOKEN"},
                {"repo": "Needless2Say/a", "environment": "dev", "secret_name": "VERCEL_DEPLOYMENT_TOKEN"},
            ],
        }

    def test_writes_repo_secrets_reaps_shadows_then_revokes_old(self):
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "val")), \
             patch.object(rs, "update_github_env_secret") as env, \
             patch.object(rs, "update_github_repo_secret") as repo, \
             patch.object(rs, "delete_github_env_secret") as dele_env, \
             patch.object(rs, "delete_vercel_token") as reap:
            rc = cmd_generate([self._entry()], ALL, ALL, "gh", "m")
        assert rc == 0
        env.assert_not_called()               # no env-secret writes — repo-level only
        assert repo.call_count == 2            # written to both repo secrets, SAME value
        assert {c[0][3] for c in repo.call_args_list} == {"val"}  # (gh, repo, secret_name, value)
        assert dele_env.call_count == 2        # both retired env shadows deleted
        reap.assert_called_once_with("m", "old")  # old token revoked (writes ok + shadows gone)

    def test_repo_write_failure_keeps_old_token_and_skips_shadow_delete(self):
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "val")), \
             patch.object(rs, "update_github_repo_secret", side_effect=[None, Exception("boom")]), \
             patch.object(rs, "delete_github_env_secret") as dele_env, \
             patch.object(rs, "delete_vercel_token") as reap:
            rc = cmd_generate([self._entry()], ALL, ALL, "gh", "m")
        assert rc == 1
        dele_env.assert_not_called()  # a write failed -> don't remove the env fallback
        reap.assert_not_called()      # ...and keep the previous token valid

    def test_shadow_delete_failure_keeps_old_token(self):
        with patch.object(rs, "list_vercel_tokens", return_value=[{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value=("new", "val")), \
             patch.object(rs, "update_github_repo_secret"), \
             patch.object(rs, "delete_github_env_secret", side_effect=[None, Exception("no perm")]), \
             patch.object(rs, "delete_vercel_token") as reap:
            rc = cmd_generate([self._entry()], ALL, ALL, "gh", "m")
        assert rc == 1              # soft error surfaced
        reap.assert_not_called()    # a lingering env shadow -> old token must stay valid


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

    def _entry_with_repo_secrets(self):
        # mirrors the real GH_PACKAGES_PAT shape: env secrets (deploy) + repo secrets (CI)
        return {
            "name": "GH_PACKAGES_PAT", "kind": "paste", "per_env": False,
            "github_env_secrets": [
                {"repo": "Needless2Say/a", "environment": "prod", "secret_name": "GH_PACKAGES_PAT"},
                {"repo": "Needless2Say/a", "environment": "dev", "secret_name": "GH_PACKAGES_PAT"},
            ],
            "github_repo_secrets": [
                {"repo": "Needless2Say/a", "secret_name": "GH_PACKAGES_PAT"},
                {"repo": "Needless2Say/b", "secret_name": "GH_PACKAGES_PAT"},
            ],
        }

    def test_also_fans_to_repo_level_ci_secrets(self):
        with patch.object(rs, "update_github_env_secret") as env, \
             patch.object(rs, "update_github_repo_secret") as repo, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_repo_secrets(), ALL, "gh", "", "the-value")
        assert rc == 0
        assert env.call_count == 2  # both environment secrets (deploy) still written
        assert repo.call_count == 2  # BOTH repository-level CI secrets written
        # signature: update_github_repo_secret(gh_token, owner_repo, secret_name, value)
        assert {c[0][1] for c in repo.call_args_list} == {"Needless2Say/a", "Needless2Say/b"}
        assert all(c[0][3] == "the-value" for c in repo.call_args_list)

    def test_repo_secrets_ignore_env_filter(self):
        # a repo secret is a single global value CI reads regardless of environment,
        # so an --envs filter must NOT drop it (only env secrets are narrowed)
        with patch.object(rs, "update_github_env_secret") as env, \
             patch.object(rs, "update_github_repo_secret") as repo, \
             patch.object(rs, "upsert_vercel_env_var"):
            cmd_paste(self._entry_with_repo_secrets(), frozenset({"prod"}), "gh", "", "v")
        assert env.call_count == 1  # env secrets narrowed to prod
        assert repo.call_count == 2  # repo secrets always written

    def test_repo_secret_failure_surfaces_rc_1_but_attempts_all(self):
        n = [0]

        def flaky(*a, **k):
            n[0] += 1
            if n[0] == 1:
                raise Exception("repo write boom")

        with patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "update_github_repo_secret", side_effect=flaky) as repo, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_repo_secrets(), ALL, "gh", "", "v")
        assert rc == 1  # a failed repo-secret write is a hard error, not swallowed
        assert repo.call_count == 2  # both attempted despite the first failing

    def _entry_with_retired(self):
        # one global PAT: repo-level only, with stale env copies to reap
        return {
            "name": "GH_PACKAGES_PAT", "kind": "paste", "per_env": False,
            "github_repo_secrets": [
                {"repo": "Needless2Say/a", "secret_name": "GH_PACKAGES_PAT"},
            ],
            "retired_github_env_secrets": [
                {"repo": "Needless2Say/a", "environment": "prod", "secret_name": "GH_PACKAGES_PAT"},
                {"repo": "Needless2Say/a", "environment": "dev", "secret_name": "GH_PACKAGES_PAT"},
            ],
        }

    def test_paste_reaps_retired_env_shadows_after_repo_write(self):
        with patch.object(rs, "update_github_repo_secret") as repo, \
             patch.object(rs, "delete_github_env_secret") as dele, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_retired(), ALL, "gh", "", "v")
        assert rc == 0
        assert repo.call_count == 1
        assert dele.call_count == 2  # both stale env copies deleted so they can't shadow the repo value

    def test_paste_keeps_env_shadow_when_repo_write_fails(self):
        with patch.object(rs, "update_github_repo_secret", side_effect=Exception("boom")), \
             patch.object(rs, "delete_github_env_secret") as dele, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_retired(), ALL, "gh", "", "v")
        assert rc == 1
        dele.assert_not_called()  # repo write failed -> leave the env copy as a working fallback

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

    def test_record_expiry_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "record-expiry", "--secrets", "VERCEL_TOKEN"])
        with patch.object(rs, "cmd_record_expiry", return_value=0) as r:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and r.called

    def test_generate_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "generate", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team_x")
        with patch.object(rs, "cmd_generate", return_value=0) as g:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and g.called
        assert g.call_args[0][5] == "team_x"  # team_id forwarded to cmd_generate

    def test_generate_requires_team_id(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "generate", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        monkeypatch.delenv("VERCEL_TEAM_ID", raising=False)
        with pytest.raises(SystemExit, match="VERCEL_TEAM_ID"):
            rs.main()

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
