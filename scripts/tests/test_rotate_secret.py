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
import rotate_secret as rs
from nacl import encoding
from nacl.public import PrivateKey, SealedBox
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

# a fake token the live expiry tests hand around, which no output may ever carry (D-049)
TOKEN = "github_pat_FAKE_LIVE_TOKEN_VALUE_0123456789"

# the time the recorded expiry tests stamp, the secrets fence's step 6
NOW = datetime(2026, 11, 6, 12, 0, tzinfo = timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────────
@pytest.fixture
def nacl_keypair():
    private = PrivateKey.generate()
    pub_b64 = private.public_key.encode(encoding.Base64Encoder).decode()
    return private, pub_b64


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days = days)).strftime("%Y-%m-%d")


def _past(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days = days)).strftime("%Y-%m-%d")


@pytest.fixture
def sample_registry():
    return {
        "secrets": [
            {
                "name": "GH_PACKAGES_PAT",
                "kind": "paste",
                "per_env": False,
                "staging": [
                    {"slot": "GH_PACKAGES_PAT_PROD_NEW", "environment": "prod"},
                    {"slot": "GH_PACKAGES_PAT_DEV_NEW", "environment": "dev"},
                ],
                "check": {"expiry": _future(60), "warn_days_before_expiry": 14},
                "github_env_secrets": [
                    {"repo": "Needless2Say/kriegerdataforge", "environment": "prod", "secret_name": "GH_PACKAGES_PAT"},
                    {"repo": "Needless2Say/fitness-app-backend", "environment": "dev", "secret_name": "GH_PACKAGES_PAT"},
                ],
                "vercel_env_vars": [
                    {"project_id": "prj_real_1", "project_name": "kdf-prod", "environment": "prod", "env_key": "GH_PACKAGES_PAT"},
                    {
                        "project_id": "TODO_x",
                        "project_name": "kdf-dev",
                        "environment": "dev",
                        "env_key": "GH_PACKAGES_PAT",
                        "inactive": True,
                    },
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
    mock_path                        = MagicMock(spec = Path)
    mock_path.is_file.return_value   = True
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
        with patch.object(rs._SESSION, "get", return_value = r):
            assert _get_env_public_key("gh", "o", "rp", "prod") == ("k", "v==")


    def test_url_has_owner_repo_env(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v"}
        with patch.object(rs._SESSION, "get", return_value = r) as g:
            _get_env_public_key("gh", "Own", "Rep", "stg")
        url = g.call_args[0][0]
        assert "Own" in url and "Rep" in url and "stg" in url


class TestUpdateGitHubEnvSecret:
    def test_puts_encrypted_value(self, nacl_keypair):
        private, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "kid", "key": pub}
        with patch.object(rs._SESSION, "get", return_value = gr), patch.object(rs._SESSION, "put") as put:
            update_github_env_secret("gh", "o/r", "prod", "S", "val")
        body = put.call_args[1]["json"]
        assert body["key_id"] == "kid"
        assert SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"])).decode() == "val"


    def test_raises_on_put_failure(self, nacl_keypair):
        _, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "k", "key": pub}
        pr = MagicMock(); pr.raise_for_status.side_effect = Exception("HTTP 422")
        with patch.object(rs._SESSION, "get", return_value = gr), patch.object(rs._SESSION, "put", return_value = pr):
            with pytest.raises(Exception, match = "HTTP 422"):
                update_github_env_secret("gh", "o/r", "prod", "S", "v")


class TestGetRepoPublicKey:
    def test_returns_key(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v=="}
        with patch.object(rs._SESSION, "get", return_value = r):
            assert _get_repo_public_key("gh", "o", "rp") == ("k", "v==")


    def test_url_is_repo_level_actions_not_environment(self):
        r = MagicMock(); r.json.return_value = {"key_id": "k", "key": "v"}
        with patch.object(rs._SESSION, "get", return_value = r) as g:
            _get_repo_public_key("gh", "Own", "Rep")
        url = g.call_args[0][0]
        assert "Own/Rep/actions/secrets/public-key" in url
        assert "environments" not in url  # repository-level, NOT an environment box


class TestUpdateGitHubRepoSecret:
    def test_puts_encrypted_value_to_repo_actions(self, nacl_keypair):
        private, pub = nacl_keypair
        gr = MagicMock(); gr.json.return_value = {"key_id": "kid", "key": pub}
        with patch.object(rs._SESSION, "get", return_value = gr), patch.object(rs._SESSION, "put") as put:
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
        with patch.object(rs._SESSION, "get", return_value = gr), patch.object(rs._SESSION, "put", return_value = pr):
            with pytest.raises(Exception, match = "HTTP 422"):
                update_github_repo_secret("gh", "o/r", "S", "v")


class TestDeleteGitHubEnvSecret:
    def test_deletes_env_secret_at_correct_url(self):
        r = MagicMock(); r.status_code = 204
        with patch.object(rs._SESSION, "delete", return_value = r) as d:
            delete_github_env_secret("gh", "o/r", "prod", "S")
        assert "o/r/environments/prod/secrets/S" in d.call_args[0][0]


    def test_404_already_gone_is_tolerated(self):
        r = MagicMock(); r.status_code = 404
        r.raise_for_status.side_effect = Exception("must not be raised on 404")
        with patch.object(rs._SESSION, "delete", return_value = r):
            delete_github_env_secret("gh", "o/r", "prod", "S")  # idempotent no-op, no raise


    def test_other_status_raises(self):
        r = MagicMock(); r.status_code = 403
        r.raise_for_status.side_effect = Exception("HTTP 403")
        with patch.object(rs._SESSION, "delete", return_value = r):
            with pytest.raises(Exception, match = "HTTP 403"):
                delete_github_env_secret("gh", "o/r", "prod", "S")


class TestVercelTokenApi:
    def test_create_returns_id_and_bearer(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch.object(rs._SESSION, "post", return_value = r) as p:
            assert create_vercel_token("m", "n") == ("tid", "bv")
        assert p.call_args[1]["json"]["name"] == "n"
        assert "expiresAt" in p.call_args[1]["json"]


    def test_list_returns_tokens(self):
        r = MagicMock(); r.json.return_value = {"tokens": [{"id": "1", "name": "a"}]}
        with patch.object(rs._SESSION, "get", return_value = r):
            assert list_vercel_tokens("m") == [{"id": "1", "name": "a"}]


    def test_delete_hits_token_id(self):
        with patch.object(rs._SESSION, "delete", return_value = MagicMock()) as d:
            delete_vercel_token("m", "tok_9")
        assert "tok_9" in d.call_args[0][0]


    def test_create_scopes_to_team_when_team_id_set(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch.object(rs._SESSION, "post", return_value = r) as p:
            create_vercel_token("m", "n", "team_abc")
        assert p.call_args[1]["params"] == {"teamId": "team_abc"}  # team-scoped


    def test_create_omits_team_param_when_no_team_id(self):
        r = MagicMock(); r.json.return_value = {"token": {"id": "tid"}, "bearerToken": "bv"}
        with patch.object(rs._SESSION, "post", return_value = r) as p:
            create_vercel_token("m", "n")
        assert p.call_args[1]["params"] is None


    def test_create_403_raises_master_scope_error(self):
        r = MagicMock(); r.status_code = 403
        with patch.object(rs._SESSION, "post", return_value = r):
            with pytest.raises(rs.VercelMasterScopeError, match = "FULL ACCOUNT"):
                create_vercel_token("m", "n", "team_x")


    def test_list_403_raises_master_scope_error(self):
        r = MagicMock(); r.status_code = 403
        with patch.object(rs._SESSION, "get", return_value = r):
            with pytest.raises(rs.VercelMasterScopeError, match = "FULL ACCOUNT"):
                list_vercel_tokens("m")


class TestUpsertVercelEnvVar:
    def test_post_when_absent(self):
        lr = MagicMock(); lr.json.return_value = {"envs": []}
        with patch.object(
            rs._SESSION,
            "get",
            return_value = lr,
        ), patch.object(
            rs._SESSION,
            "post",
            return_value = MagicMock(),
        ) as post, patch.object(rs._SESSION, "patch") as pat:
            upsert_vercel_env_var("m", "prj", "K", "v")
        assert post.call_args[1]["json"]["key"] == "K"
        assert set(post.call_args[1]["json"]["target"]) == {"production", "preview", "development"}
        pat.assert_not_called()


    def test_patch_existing_only_matching_key(self):
        lr = MagicMock(); lr.json.return_value = {"envs": [
            {"id": "e1", "key": "K", "target": ["production"]},
            {"id": "e2", "key": "OTHER", "target": ["production"]},
        ]}
        with patch.object(
            rs._SESSION,
            "get",
            return_value = lr,
        ), patch.object(
            rs._SESSION,
            "patch",
            return_value = MagicMock(),
        ) as pat, patch.object(rs._SESSION, "post") as post:
            upsert_vercel_env_var("m", "prj", "K", "v")
        assert pat.call_count == 1 and "e1" in pat.call_args[0][0]
        post.assert_not_called()


    def test_list_returns_empty_when_absent(self):
        r = MagicMock(); r.json.return_value = {}
        with patch.object(rs._SESSION, "get", return_value = r):
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
        with pytest.raises(SystemExit, match = "unknown secret"):
            _select_secrets(sample_registry, frozenset({"nope"}))


class TestTerraformGuard:
    def test_refuses_tf_managed(self):
        with pytest.raises(SystemExit, match = "Terraform-managed"):
            _refuse_if_terraform_managed({"name": "DB", "terraform_managed": True})


    def test_allows_normal(self):
        _refuse_if_terraform_managed({"name": "X"})  # no raise


# ── check mode ──────────────────────────────────────────────────────────────────
class TestCheck:
    def _e(self, expiry, warn = 14):
        return {"name": "S", "check": {"expiry": expiry, "warn_days_before_expiry": warn}}


    def test_ok_far_future(self):
        assert cmd_check([self._e(_future(60))]) == 0


    def test_warn_within_threshold(self):
        assert cmd_check([self._e(_future(7), warn = 14)]) == 1


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
        rc  = cmd_check([{"name": "X", "check": {"expiry": _future(60)}}, {"name": "Y"}])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NEEDS_ROTATION: \n" in out


class TestRealRegistry:
    """
    The actual scripts/secret_registry.json must parse and run an offline check.
    """
    def test_loads_with_monitored_tokens_and_checks_offline(self):
        reg     = rs._load_registry()  # reads the real REGISTRY_FILE
        entries = _select_secrets(reg, ALL)
        names   = {e["name"] for e in entries}
        assert {"GH_PACKAGES_PAT", "VERCEL_DEPLOYMENT_TOKEN", "CICD_PAT", "VERCEL_MASTER_TOKEN"} <= names
        assert "KDF_APP_PRIVATE_KEY" in names  # the GitHub App private key is monitored too
        # GH_PACKAGES_PAT must fan out to the repository-level CI secret in every backend
        # that installs the SDK in CI (a job with no `environment:` can't read env secrets).
        gh_pat       = next(e for e in entries if e["name"] == "GH_PACKAGES_PAT")
        repo_targets = {t["repo"] for t in gh_pat.get("github_repo_secrets", [])}
        assert {
            "Needless2Say/kriegerdataforge",
            "Needless2Say/fitness-app-backend",
            "Needless2Say/tiffanys-space-backend",
            "Needless2Say/kriegerdataforge-template-fastapi",  # scaffold repo also installs the SDK in CI
        } <= repo_targets
        assert not gh_pat.get("github_env_secrets")  # repo-level only now
        # the former env copies were already reaped in the one-time migration -> no retired targets
        assert not gh_pat.get("retired_github_env_secrets")
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
        assert vercel.get("check", {}).get("recorded")  # its expiry is the fact the ops run records, read live
        # the manual tokens carry a check block (monitored) and no engine targets
        for name in ("CICD_PAT", "VERCEL_MASTER_TOKEN", "KDF_APP_PRIVATE_KEY"):
            e = next(x for x in entries if x["name"] == name)
            assert e.get("kind") == "manual" and "check" in e
            assert not e.get("github_env_secrets") and not e.get("vercel_env_vars")
        assert cmd_check(entries) in (0, 1)


# ── the recorded expiry facts (the secrets fence) ────────────────────────────────
class TestRecordedExpiry:
    """
    Once CICD_PAT and the master token live in ops, the weekly monitor holds neither, so the ops run reads each one
    live and records its expiry as a cicd repository variable, nothing secret, and the monitor reads that fact alone,
    never the registry's hand kept date.
    """
    def _entries(self):
        return [
            {
                "name": "CICD_PAT",
                "kind": "manual",
                "check": {"expiry": "2026-07-30", "live": "github", "recorded": True},
            },
            {
                "name": "VERCEL_MASTER_TOKEN",
                "kind": "manual",
                "check": {"expiry": "2026-07-30", "live": "vercel-current", "recorded": True},
            },
            {"name": "GH_PACKAGES_PAT", "kind": "paste", "check": {"expiry": "2026-07-30", "live": "github"}},
        ]


    def test_record_writes_each_recorded_tokens_date_status_and_time(self, capsys):
        answers = {"CICD_PAT": ("2026-12-01", "ok"), "VERCEL_MASTER_TOKEN": (None, "rejected")}
        with patch.object(rs, "live_expiry", side_effect = lambda entry, environ = None: answers[entry["name"]]), \
             patch.object(rs, "set_repo_variable") as setter:
            rc = rs.cmd_record_expiry(self._entries(), "gh", "Needless2Say/kriegerdataforge-cicd", now = NOW)
        assert rc == 0
        assert setter.call_args_list == [
            (("gh", "Needless2Say/kriegerdataforge-cicd", "EXPIRY_CICD_PAT",
              "expires=2026-12-01 status=ok recorded=2026-11-06T12:00:00Z"),),
            (("gh", "Needless2Say/kriegerdataforge-cicd", "EXPIRY_VERCEL_MASTER_TOKEN",
              "expires=none status=rejected recorded=2026-11-06T12:00:00Z"),),
        ]
        assert "GH_PACKAGES_PAT" not in capsys.readouterr().out.split("Recording")[1].split("\n")[0]


    def test_a_failed_write_fails_the_run(self):
        with patch.object(rs, "live_expiry", return_value = ("2026-12-01", "ok")), \
             patch.object(rs, "set_repo_variable", side_effect = RuntimeError("403")):
            assert rs.cmd_record_expiry(self._entries(), "gh", "Needless2Say/kriegerdataforge-cicd", now = NOW) == 1


    @pytest.mark.parametrize(("token", "repo"), [("", "Needless2Say/kriegerdataforge-cicd"), ("gh", "")])
    def test_record_needs_a_token_and_the_repo(self, token, repo):
        with pytest.raises(SystemExit):
            rs.cmd_record_expiry(self._entries(), token, repo, now = NOW)


    def _recorded(self, monkeypatch, value):
        entry = self._entries()[0]
        if value is None:
            monkeypatch.delenv("EXPIRY_CICD_PAT", raising = False)
        else:
            monkeypatch.setenv("EXPIRY_CICD_PAT", value)
        with patch.object(rs, "live_expiry", side_effect = AssertionError("a recorded token is never read live")):
            return rs._check_one(entry, live = True)


    def test_a_recorded_token_reads_its_fact_and_never_the_registrys_date(self, monkeypatch, capsys):
        outcome, drift = self._recorded(monkeypatch, f"expires={_future(60)} status=ok recorded=2026-11-06T12:00:00Z")
        assert outcome == 0 and drift is None
        assert "recorded 2026-11-06T12:00:00Z" in capsys.readouterr().out


    def test_a_token_its_provider_gives_no_expiry_is_healthy(self, monkeypatch, capsys):
        assert self._recorded(monkeypatch, "expires=none status=no-expiry recorded=2026-11-06T12:00:00Z")[0] == 0
        assert "no expiry" in capsys.readouterr().out


    def test_a_missing_fact_is_said_plainly_and_needs_a_look(self, monkeypatch, capsys):
        assert self._recorded(monkeypatch, None)[0] == 1
        out = capsys.readouterr().out
        assert "no recorded expiry" in out and "2026-07-30" not in out


    @pytest.mark.parametrize(("value", "said"), [
        ("expires=none status=rejected recorded=2026-11-06T12:00:00Z", "REJECTED"),
        ("expires=none status=error recorded=2026-11-06T12:00:00Z", "the read said error"),
        ("expires=none status=no-token recorded=2026-11-06T12:00:00Z", "the read said no-token"),
        (f"expires={_past(3)} status=ok recorded=2026-11-06T12:00:00Z", "EXPIRED"),
        (f"expires={_future(5)} status=ok recorded=2026-11-06T12:00:00Z", "WARNING"),
        ("garbage", "cannot read"),
        # Codex's read of step 6, each a fact that once read as healthy
        ("expires=2099-01-01 status=error recorded=invalid", "cannot read"),
        ("expires=garbage status=no-expiry recorded=invalid", "cannot read"),
        ("expires=none status=rejected recorded=2026-11-06T12:00:00Z status=ok", "cannot read"),
        (f"expires={_future(60)} status=ok recorded=not-a-time", "cannot read"),
        (f"expires={_future(60)} status=ok recorded=2026-11-06T12:00:00Z extra=1", "cannot read"),
        ("expires=none status=ok recorded=2026-11-06T12:00:00Z", "cannot read"),
        (f"expires={_future(60)} status=rejected recorded=2026-11-06T12:00:00Z", "cannot read"),
        (f"expires={_future(60)} status=fine recorded=2026-11-06T12:00:00Z", "cannot read"),
    ])
    def test_a_recorded_fact_that_is_not_healthy_needs_a_look(self, monkeypatch, capsys, value, said):
        assert self._recorded(monkeypatch, value)[0] == 1
        assert said in capsys.readouterr().out


    def test_set_repo_variable_updates_then_creates(self, monkeypatch):
        calls   = []
        session = MagicMock()


        def answer(status):
            resp             = MagicMock()
            resp.status_code = status
            resp.ok          = status < 400
            return resp


        session.patch.side_effect = lambda url, **kw: calls.append(("PATCH", url, kw["json"])) or answer(404)
        session.post.side_effect  = lambda url, **kw: calls.append(("POST", url, kw["json"])) or answer(201)
        monkeypatch.setattr(rs, "_SESSION", session)
        rs.set_repo_variable("gh", "Needless2Say/kriegerdataforge-cicd", "EXPIRY_X", "expires=none")
        assert [call[0] for call in calls] == ["PATCH", "POST"]
        assert calls[1][2] == {"name": "EXPIRY_X", "value": "expires=none"}


    def test_prove_master_mints_a_throwaway_token_and_deletes_it(self, capsys):
        with patch.object(rs, "create_vercel_token", return_value = ("tok_1", "the-secret-value")) as mint, \
             patch.object(rs, "delete_vercel_token") as delete:
            assert rs.cmd_prove_master("master", "team_x") == 0
        assert mint.call_args[0][0] == "master" and mint.call_args[0][2] == "team_x"
        delete.assert_called_once_with("master", "tok_1")
        assert "the-secret-value" not in capsys.readouterr().out


    def test_prove_master_fails_when_the_master_cannot_mint(self):
        with patch.object(rs, "create_vercel_token", side_effect = RuntimeError("403")), \
             patch.object(rs, "delete_vercel_token") as delete:
            assert rs.cmd_prove_master("master", "team_x") == 1
        delete.assert_not_called()


    def test_the_real_registry_records_every_token_the_monitor_cannot_read(self):
        # the packages and npm tokens since D-099, recorded when the staged run distributes them
        entries  = json.loads(rs.REGISTRY_FILE.read_text(encoding = "utf-8"))["secrets"]
        recorded = sorted(entry["name"] for entry in entries if (entry.get("check") or {}).get("recorded"))
        assert recorded == [
            "CICD_PAT",
            "GH_NPM_TOKEN",
            "GH_PACKAGES_PAT",
            "VERCEL_DEPLOYMENT_TOKEN",
            "VERCEL_MASTER_TOKEN",
        ]


# ── generate: vercel_token ──────────────────────────────────────────────────────
class TestGenerateVercelToken:
    def _entry(self, sample_registry):
        return [e for e in sample_registry["secrets"] if e["name"] == "VERCEL_TOKEN"]


    def test_creates_per_target_and_writes(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token"):
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "master")
        assert rc == 0
        assert create.call_count == 2
        assert upd.call_count == 2


    def test_app_filter(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), frozenset({"auth-backend"}), ALL, "gh", "m")
        assert create.call_count == 1
        assert create.call_args[0][1] == "kdf-auth-backend-prod"


    def test_env_filter(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "nval")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), ALL, frozenset({"dev"}), "gh", "m")
        assert create.call_count == 1
        assert create.call_args[0][1] == "kdf-fitness-frontend-dev"


    def test_deletes_old_when_id_differs(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-auth-backend-prod", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "v")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token") as dele:
            cmd_generate(self._entry(sample_registry), frozenset({"auth-backend"}), ALL, "gh", "m")
        dele.assert_called_once_with("m", "old")


    def test_partial_failure_returns_1(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", side_effect = Exception("boom")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            assert cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m") == 1


    def test_missing_master_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match = "VERCEL_MASTER_TOKEN"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "")


    def test_missing_gh_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match = "GH_TOKEN"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "", "m")


# ── generate: vercel_token (shared) ──────────────────────────────────────────────
class TestGenerateSharedVercelToken:
    def _entry(self, sample_registry):
        return [e for e in sample_registry["secrets"] if e["name"] == "VERCEL_SHARED"]


    def test_mints_once_and_fans_out_same_value(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "shared-val")) as create, \
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
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "v")) as create, \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), frozenset({"a"}), frozenset({"dev"}), "gh", "m")
        assert create.call_count == 1
        assert upd.call_count == 3                          # all targets, despite the filters


    def test_deletes_old_shared_token_when_all_writes_succeed(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "v")), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 0
        dele.assert_called_once_with("m", "old")


    def test_keeps_old_token_when_a_write_fails(self, sample_registry):
        # middle write fails -> old token must NOT be deleted, so both stay valid (no dead repo)
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "v")), \
             patch.object(rs, "update_github_env_secret", side_effect = [None, Exception("boom"), None]), \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1
        dele.assert_not_called()


    def test_master_scope_error_exits_cleanly(self, sample_registry):
        # a non-Full-Account master 403s on /v3/user/tokens -> clean SystemExit, not a traceback
        with patch.object(rs, "list_vercel_tokens", side_effect = rs.VercelMasterScopeError("needs FULL ACCOUNT")):
            with pytest.raises(SystemExit, match = "FULL ACCOUNT"):
                cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m", "team_z")


    def test_mint_failure_writes_nothing(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", side_effect = Exception("mint boom")), \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token") as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1
        upd.assert_not_called()
        dele.assert_not_called()


    def test_delete_failure_is_soft_error_not_a_crash(self, sample_registry):
        # all writes succeed, then the cleanup DELETE raises -> must return 1 (soft error), NOT crash,
        # and every target must still have been written (the new token is already live).
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy-shared", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "v")), \
             patch.object(rs, "update_github_env_secret") as upd, \
             patch.object(rs, "delete_vercel_token", side_effect = Exception("delete boom")) as dele:
            rc = cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m")
        assert rc == 1                      # soft error, surfaced via _summary — not a traceback
        assert upd.call_count == 3          # every target still written
        dele.assert_called_once_with("m", "old")  # cleanup was attempted


    def test_reaps_all_duplicate_old_tokens(self, sample_registry):
        # two pre-existing tokens share the name -> BOTH must be deleted (a name->id map would miss one)
        with patch.object(
            rs,
            "list_vercel_tokens",
            return_value = [
                {"name": "kdf-deploy-shared", "id": "old1"},
                {"name": "kdf-deploy-shared", "id": "old2"},
                {"name": "unrelated", "id": "keep"},
            ],
        ), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "v")), \
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
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token") as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            rc = cmd_generate(entry, ALL, ALL, "gh", "m")
        assert rc == 1                       # clean error, not a KeyError traceback
        create.assert_not_called()           # bailed before minting any token


    def test_forwards_team_id_to_create(self, sample_registry):
        with patch.object(rs, "list_vercel_tokens", return_value = []), \
             patch.object(rs, "create_vercel_token", return_value = ("nid", "v")) as create, \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "delete_vercel_token"):
            cmd_generate(self._entry(sample_registry), ALL, ALL, "gh", "m", "team_z")
        # every mint is scoped to the team (3rd positional arg of create_vercel_token)
        assert all(c[0][2] == "team_z" for c in create.call_args_list)


# ── generate: shared vercel_token → repo-level + retired-env reaping ─────────────
class TestGenerateSharedRepoLevel:
    """
    The shared VERCEL_DEPLOYMENT_TOKEN writes REPOSITORY secrets and reaps its retired
    per-environment copies; the old Vercel token is revoked only once the new value is live
    everywhere AND every env shadow is gone.
    """
    def _entry(self):
        return {
            "name": "VERCEL_DEPLOYMENT_TOKEN",
            "kind": "generate",
            "generator": "vercel_token",
            "shared": True,
            "vercel_token_name": "kdf-deploy",
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
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "val")), \
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
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "val")), \
             patch.object(rs, "update_github_repo_secret", side_effect = [None, Exception("boom")]), \
             patch.object(rs, "delete_github_env_secret") as dele_env, \
             patch.object(rs, "delete_vercel_token") as reap:
            rc = cmd_generate([self._entry()], ALL, ALL, "gh", "m")
        assert rc == 1
        dele_env.assert_not_called()  # a write failed -> don't remove the env fallback
        reap.assert_not_called()      # ...and keep the previous token valid


    def test_shadow_delete_failure_keeps_old_token(self):
        with patch.object(rs, "list_vercel_tokens", return_value = [{"name": "kdf-deploy", "id": "old"}]), \
             patch.object(rs, "create_vercel_token", return_value = ("new", "val")), \
             patch.object(rs, "update_github_repo_secret"), \
             patch.object(rs, "delete_github_env_secret", side_effect = [None, Exception("no perm")]), \
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
        with pytest.raises(SystemExit, match = "Terraform-managed"):
            cmd_generate(tf, ALL, ALL, "gh", "m")


# ── paste mode ──────────────────────────────────────────────────────────────────
class TestPaste:
    def _entry(self, sample_registry):
        return next(e for e in sample_registry["secrets"] if e["name"] == "GH_PACKAGES_PAT")


    def test_fans_to_the_named_environments_gh_and_real_vercel(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc:
            rc = cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "gh", "master", "the-value")
        assert rc == 0
        assert gh.call_count == 1
        vc.assert_called_once()
        assert vc.call_args[0][1] == "prj_real_1"
        assert vc.call_args[0][3] == "the-value"


    def test_an_inactive_vercel_project_is_named_unwritten_and_never_counted_as_written(self, sample_registry, capsys):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc:
            rc = cmd_paste(self._entry(sample_registry), frozenset({"dev"}), "gh", "master", "the-value")
        assert rc == 0 and gh.call_count == 1
        vc.assert_not_called()
        out = capsys.readouterr().out
        assert "1 inactive target(s) left unwritten" in out and "kdf-dev" in out
        assert "All active targets updated successfully." in out
        assert "All targets updated successfully." not in out


    def test_an_active_vercel_project_with_no_id_stops_the_paste_before_any_write(self, sample_registry):
        # a target left on the old value while the run said every target was written (D-099, the Round Table's L1)
        entry = self._entry(sample_registry)
        entry["vercel_env_vars"][1].pop("inactive")
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc, \
             pytest.raises(SystemExit, match = "no project id"):
            cmd_paste(entry, frozenset({"dev"}), "gh", "master", "the-value")
        gh.assert_not_called()
        vc.assert_not_called()


    @pytest.mark.parametrize("kind", ["generate", "manual", "distribute"])
    def test_an_entry_not_of_kind_paste_is_refused_before_any_write(self, sample_registry, kind):
        # a generated token, a credential made in ops or an App key never takes a pasted value (D-099, L4)
        entry = dict(self._entry(sample_registry), kind = kind)
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "update_github_repo_secret") as repo, \
             pytest.raises(SystemExit, match = "only a 'paste' entry"):
            cmd_paste(entry, frozenset({"prod"}), "gh", "master", "the-value")
        gh.assert_not_called()
        repo.assert_not_called()


    def test_an_entry_held_in_repository_secrets_alone_refuses_an_environment(self):
        # an environment would narrow its Vercel copies alone and leave the rotation half done (D-099, L2)
        entry = {
            "name": "GLOBAL_PAT",
            "kind": "paste",
            "github_repo_secrets": [{"repo": "Needless2Say/a", "secret_name": "GLOBAL_PAT"}],
            "vercel_env_vars": [{"project_id": "prj_1", "project_name": "p", "environment": "dev", "env_key": "X"}],
        }
        with patch.object(rs, "update_github_repo_secret") as repo, \
             pytest.raises(SystemExit, match = "lives in no environment"):
            cmd_paste(entry, frozenset({"dev"}), "gh", "master", "the-value")
        repo.assert_not_called()


    @pytest.mark.parametrize("envs", [ALL, frozenset({"dev", "prod"})])
    def test_an_entry_with_environment_targets_is_pasted_to_one_named_environment_never_both(
        self,
        sample_registry,
        envs,
    ):
        # a value meant for one environment written to both would put DEV's value in PROD (the secrets fence)
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "update_github_repo_secret") as repo, \
             patch.object(rs, "upsert_vercel_env_var") as vc, \
             pytest.raises(SystemExit, match = "exactly one"):
            cmd_paste(self._entry(sample_registry), envs, "gh", "master", "the-value")
        gh.assert_not_called()
        repo.assert_not_called()
        vc.assert_not_called()


    def test_an_environment_with_no_target_there_is_refused(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             pytest.raises(SystemExit, match = "no target in environment 'staging'"):
            cmd_paste(self._entry(sample_registry), frozenset({"staging"}), "gh", "master", "the-value")
        gh.assert_not_called()


    @pytest.mark.parametrize(("name", "environment", "secret_name"), [
        ("KDF_HUB_URL_DEV", "dev", "KDF_HUB_URL"),
        ("KDF_HUB_URL_PROD", "prod", "KDF_HUB_URL"),
        ("KDF_HUB_CRON_SECRET_DEV", "dev", "KDF_HUB_CRON_SECRET"),
        ("KDF_HUB_CRON_SECRET_PROD", "prod", "KDF_HUB_CRON_SECRET"),
        ("REPORTS_CRON_SECRET_FITNESS_APP", "dev", "REPORTS_CRON_SECRET_FITNESS_APP"),
        ("REPORTS_CRON_SECRET_FITNESS_APP", "prod", "REPORTS_CRON_SECRET_FITNESS_APP"),
    ])
    def test_each_real_cron_copy_is_pasted_to_its_one_cicd_environment(self, name, environment, secret_name):
        entry = next(
            e for e in json.loads(rs.REGISTRY_FILE.read_text(encoding = "utf-8"))["secrets"] if e["name"] == name
        )
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "update_github_repo_secret") as repo:
            assert cmd_paste(entry, frozenset({environment}), "gh", "", "the-value") == 0
        gh.assert_called_once_with("gh", "Needless2Say/kriegerdataforge-cicd", environment, secret_name, "the-value")
        repo.assert_not_called()


    def test_env_filter_narrows_gh_targets(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var"):
            cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "gh", "master", "v")
        assert gh.call_count == 1
        assert gh.call_args[0][1] == "Needless2Say/kriegerdataforge"


    def _entry_with_repo_secrets(self):
        # mirrors the real GH_PACKAGES_PAT shape: env secrets (deploy) + repo secrets (CI)
        return {
            "name": "GH_PACKAGES_PAT",
            "kind": "paste",
            "per_env": False,
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
            rc = cmd_paste(self._entry_with_repo_secrets(), frozenset({"dev"}), "gh", "", "the-value")
        assert rc == 0
        assert env.call_count == 1  # the named environment's secret (deploy) written
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
             patch.object(rs, "update_github_repo_secret", side_effect = flaky) as repo, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_repo_secrets(), frozenset({"prod"}), "gh", "", "v")
        assert rc == 1  # a failed repo-secret write is a hard error, not swallowed
        assert repo.call_count == 2  # both attempted despite the first failing


    def _entry_with_retired(self):
        # one global PAT: repo-level only, with stale env copies to reap
        return {
            "name": "GH_PACKAGES_PAT",
            "kind": "paste",
            "per_env": False,
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
        with patch.object(rs, "update_github_repo_secret", side_effect = Exception("boom")), \
             patch.object(rs, "delete_github_env_secret") as dele, \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(self._entry_with_retired(), ALL, "gh", "", "v")
        assert rc == 1
        dele.assert_not_called()  # repo write failed -> leave the env copy as a working fallback


    def test_missing_value_exits(self, sample_registry):
        with pytest.raises(SystemExit, match = "no staged value"):
            cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "gh", "m", "")


    def test_missing_gh_token_exits(self, sample_registry):
        with pytest.raises(SystemExit, match = "GH_TOKEN"):
            cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "", "m", "v")


    def test_vercel_targets_without_the_master_stop_the_paste_before_any_write(self, sample_registry):
        with patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc, \
             pytest.raises(SystemExit, match = "VERCEL_MASTER_TOKEN"):
            cmd_paste(self._entry(sample_registry), frozenset({"prod"}), "gh", "", "v")
        gh.assert_not_called()
        vc.assert_not_called()


    def test_partial_gh_failure_returns_1_but_attempts_all(self, sample_registry):
        n = [0]


        def flaky(*a, **k):
            n[0] += 1
            if n[0] == 1:
                raise Exception("fail one")


        entry = {
            "name": "TWO_REPOS",
            "kind": "paste",
            "github_env_secrets": [
                {"repo": "Needless2Say/a", "environment": "prod", "secret_name": "TWO_REPOS"},
                {"repo": "Needless2Say/b", "environment": "prod", "secret_name": "TWO_REPOS"},
            ],
        }
        with patch.object(rs, "update_github_env_secret", side_effect = flaky), \
             patch.object(rs, "upsert_vercel_env_var"):
            rc = cmd_paste(entry, frozenset({"prod"}), "gh", "", "v")
        assert rc == 1 and n[0] == 2


    def test_terraform_managed_refused(self, sample_registry):
        tf = next(e for e in sample_registry["secrets"] if e["name"] == "DB_DATABASE_URL")
        with pytest.raises(SystemExit, match = "Terraform-managed"):
            cmd_paste(tf, ALL, "gh", "m", "v")


# ── paste-staged, the staging slots' run (D-099) ─────────────────────────────────
class TestPasteStaged:
    """
    The staged slots' run, each slot checked before any write, deleted once written, kept when it failed.
    """
    CICD  = "Needless2Say/kriegerdataforge-cicd"
    FRESH = "2026-11-06T09:00:00Z"
    STALE = "2026-10-29T11:59:00Z"
    VALUE = "the-staged-value-never-printed"


    def _run(self, registry, slots, environ, updated_at = FRESH, facts = "facts", master = "master"):
        with patch.object(rs, "github_env_secret_updated_at", return_value = updated_at) as age, \
             patch.object(rs, "update_github_env_secret") as gh, \
             patch.object(rs, "upsert_vercel_env_var") as vc, \
             patch.object(rs, "delete_github_env_secret") as dele:
            rc = rs.cmd_paste_staged(registry, slots, "gh", facts, master, self.CICD, environ, NOW)
        return rc, age, gh, vc, dele


    def test_a_ready_slot_is_written_to_its_one_environment_and_then_deleted(self, sample_registry):
        rc, age, gh, vc, dele = self._run(
            sample_registry,
            ["GH_PACKAGES_PAT_PROD_NEW"],
            {"GH_PACKAGES_PAT_PROD_NEW": self.VALUE},
        )
        assert rc == 0
        age.assert_called_once_with("gh", self.CICD, "ops", "GH_PACKAGES_PAT_PROD_NEW")
        # the prod target alone, never dev, and the prod Vercel copy
        assert [c.args[2] for c in gh.call_args_list] == ["prod"]
        assert vc.call_args.args[1] == "prj_real_1" and vc.call_args.args[3] == self.VALUE
        dele.assert_called_once_with("gh", self.CICD, "ops", "GH_PACKAGES_PAT_PROD_NEW")


    def test_an_unknown_slot_is_refused(self, sample_registry):
        with pytest.raises(SystemExit, match = "no staging slot named SECRET_VALUE_NEW"):
            rs.cmd_paste_staged(sample_registry, ["SECRET_VALUE_NEW"], "gh", "f", "m", self.CICD, {}, NOW)


    def test_no_slot_named_is_refused(self, sample_registry):
        with pytest.raises(SystemExit, match = "name the slots"):
            rs.cmd_paste_staged(sample_registry, [], "gh", "f", "m", self.CICD, {}, NOW)


    @pytest.mark.parametrize(
        ("environ", "updated_at", "why"),
        [
            ({}, FRESH, "not set in this run"),
            ({"GH_PACKAGES_PAT_PROD_NEW": VALUE}, None, "not set in ops"),
            ({"GH_PACKAGES_PAT_PROD_NEW": VALUE}, STALE, "more than 7"),
        ],
        ids = ["unset in the run", "unset in ops", "set more than a week ago"],
    )
    def test_a_slot_not_ready_stops_the_run_before_anything_is_written(
        self,
        sample_registry,
        capsys,
        environ,
        updated_at,
        why,
    ):
        # a slot left from an earlier rotation is never pasted again (D-099, the Round Table's L3)
        environ = dict(environ, GH_PACKAGES_PAT_DEV_NEW = self.VALUE)
        rc, _age, gh, vc, dele = self._run(
            sample_registry,
            ["GH_PACKAGES_PAT_DEV_NEW", "GH_PACKAGES_PAT_PROD_NEW"],
            environ,
            updated_at,
        )
        assert rc == 1
        gh.assert_not_called()
        vc.assert_not_called()
        dele.assert_not_called()
        out = capsys.readouterr().out
        assert why in out and "Nothing written" in out


    def test_an_unresolved_target_stops_the_run_before_anything_is_written(self, sample_registry, capsys):
        sample_registry["secrets"][0]["vercel_env_vars"][1].pop("inactive")
        rc, _age, gh, _vc, dele = self._run(
            sample_registry,
            ["GH_PACKAGES_PAT_DEV_NEW"],
            {"GH_PACKAGES_PAT_DEV_NEW": self.VALUE},
        )
        assert rc == 1
        gh.assert_not_called()
        dele.assert_not_called()
        assert "no project id" in capsys.readouterr().out


    def test_a_failed_slot_is_kept_for_a_retry_and_the_others_go_on(self, sample_registry, capsys):
        def update(_token, _repo, environment, _name, _value):
            if environment == "dev":
                raise RuntimeError("HTTP 502")


        environ = {"GH_PACKAGES_PAT_DEV_NEW": self.VALUE, "GH_PACKAGES_PAT_PROD_NEW": self.VALUE}
        with patch.object(rs, "github_env_secret_updated_at", return_value = self.FRESH), \
             patch.object(rs, "update_github_env_secret", side_effect = update), \
             patch.object(rs, "upsert_vercel_env_var"), \
             patch.object(rs, "delete_github_env_secret") as dele:
            rc = rs.cmd_paste_staged(
                sample_registry,
                ["GH_PACKAGES_PAT_DEV_NEW", "GH_PACKAGES_PAT_PROD_NEW"],
                "gh",
                "f",
                "m",
                self.CICD,
                environ,
                NOW,
            )
        assert rc == 1
        dele.assert_called_once_with("gh", self.CICD, "ops", "GH_PACKAGES_PAT_PROD_NEW")
        out = capsys.readouterr().out
        assert "GH_PACKAGES_PAT_DEV_NEW: FAILED, the slot is kept for a retry" in out
        assert "GH_PACKAGES_PAT_PROD_NEW: written, the slot deleted" in out


    def test_a_slot_that_could_not_be_deleted_fails_the_run_and_says_so(self, sample_registry, capsys):
        with patch.object(rs, "github_env_secret_updated_at", return_value = self.FRESH), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "upsert_vercel_env_var"), \
             patch.object(rs, "delete_github_env_secret", side_effect = RuntimeError("HTTP 403")):
            rc = rs.cmd_paste_staged(
                sample_registry,
                ["GH_PACKAGES_PAT_PROD_NEW"],
                "gh",
                "f",
                "m",
                self.CICD,
                {"GH_PACKAGES_PAT_PROD_NEW": self.VALUE},
                NOW,
            )
        assert rc == 1
        assert "written, the slot NOT deleted, RuntimeError, delete it by hand" in capsys.readouterr().out


    EXPIRING = {"github-authentication-token-expiration": "2026-12-09 12:00:00 UTC"}


    @pytest.mark.parametrize(
        ("facts", "read", "write_fails", "fact"),
        [
            ("facts", (200, EXPIRING), False, "expires=2026-12-09 status=ok recorded=2026-11-06T12:00:00Z"),
            ("facts", (200, None), False, "expires=none status=no-expiry recorded=2026-11-06T12:00:00Z"),
            ("", (200, EXPIRING), False, None),
            ("facts", (503, None), False, None),
            ("facts", (200, {"github-authentication-token-expiration": "soon"}), False, None),
            ("facts", RuntimeError("timed out"), False, None),
            ("facts", (401, None), False, None),
            ("facts", (200, EXPIRING), True, None),
        ],
        ids = [
            "read and written",
            "no expiry read whole",
            "no facts token",
            "the read answered 503",
            "the header unreadable",
            "the read timed out",
            "the token rejected",
            "the write failed",
        ],
    )
    def test_a_slot_is_deleted_only_once_its_tokens_expiry_was_read_and_recorded(
        self,
        sample_registry,
        capsys,
        facts,
        read,
        write_fails,
        fact,
    ):
        # the slot holds the one copy the run can read again, the npm token's above all, so it stays until its expiry
        # was read live and its fact written, through the real recorder with only GitHub mocked (Codex's reads of
        # D-099, M1)
        sample_registry["secrets"][0]["check"] = {"live": "github", "recorded": True}
        get = {"side_effect": read} if isinstance(read, Exception) else {"return_value": _resp(*read)}
        with patch.object(rs, "github_env_secret_updated_at", return_value = self.FRESH), \
             patch.object(rs, "update_github_env_secret"), \
             patch.object(rs, "upsert_vercel_env_var"), \
             patch.object(rs._SESSION, "get", **get), \
             patch.object(rs, "set_repo_variable", side_effect = RuntimeError("422") if write_fails else None) as put, \
             patch.object(rs, "delete_github_env_secret") as dele:
            rc = rs.cmd_paste_staged(
                sample_registry,
                ["GH_PACKAGES_PAT_PROD_NEW"],
                "gh",
                facts,
                "m",
                self.CICD,
                {"GH_PACKAGES_PAT_PROD_NEW": self.VALUE},
                NOW,
            )
        out = capsys.readouterr().out
        assert self.VALUE not in out
        if fact:
            assert rc == 0
            put.assert_called_once_with("facts", self.CICD, "EXPIRY_GH_PACKAGES_PAT", fact)
            dele.assert_called_once()
        else:
            assert rc == 1
            dele.assert_not_called()
            assert "its expiry NOT recorded, the slot is kept" in out


    @pytest.mark.parametrize(
        "project_id",
        ["", "   ", None, 7, "TODO_x"],
        ids = ["empty", "blank", "null", "a number", "TODO"],
    )
    def test_a_target_with_no_real_project_id_stops_the_run_before_anything_is_written(
        self,
        sample_registry,
        project_id,
    ):
        # Codex's read of D-099, M2, an empty or null id once got past the preflight that caught TODO alone
        target = sample_registry["secrets"][0]["vercel_env_vars"][1]
        target.pop("inactive")
        target["project_id"] = project_id
        rc, _age, gh, vc, dele = self._run(
            sample_registry,
            ["GH_PACKAGES_PAT_DEV_NEW"],
            {"GH_PACKAGES_PAT_DEV_NEW": self.VALUE},
        )
        assert rc == 1
        gh.assert_not_called()
        vc.assert_not_called()
        dele.assert_not_called()


    def test_no_value_is_ever_printed(self, sample_registry, capsys):
        self._run(sample_registry, ["GH_PACKAGES_PAT_PROD_NEW"], {"GH_PACKAGES_PAT_PROD_NEW": self.VALUE})
        printed = capsys.readouterr()
        assert self.VALUE not in printed.out + printed.err


    @pytest.mark.parametrize(
        ("updated_at", "refused"),
        [("2026-11-06T12:00:00Z", False), ("2026-10-30T12:00:00Z", False), ("2026-10-30T11:59:59Z", True)],
    )
    def test_a_slot_older_than_a_week_is_refused(self, updated_at, refused):
        assert (rs._staged_age_refusal(updated_at, NOW) is not None) == refused


# ── the real registry's slots (D-099) ────────────────────────────────────────────
class TestRealSlots:
    """
    The real registry's slots, one for each place a paste entry lives, named for it.
    """
    def _registry(self):
        return json.loads(rs.REGISTRY_FILE.read_text(encoding = "utf-8"))


    def test_every_paste_entry_has_a_slot_for_each_place_it_lives_and_no_other_kind_has_one(self):
        for entry in self._registry()["secrets"]:
            slots = entry.get("staging", [])
            if entry["kind"] != "paste":
                assert not slots, entry["name"]
                continue
            held = sorted({target["environment"] for target in entry.get("github_env_secrets", [])})
            assert sorted(slot.get("environment", "") for slot in slots) == (held or [""]), entry["name"]


    def test_each_slot_is_named_for_its_entry_and_its_environment(self):
        for slot, (entry, environment) in rs.staging_slots(self._registry()).items():
            # an entry already named for its environment, KDF_HUB_URL_DEV, takes no second suffix
            named_for_it = not environment or entry["name"].endswith(environment.upper())
            expected     = f"{entry['name']}_NEW" if named_for_it else f"{entry['name']}_{environment.upper()}_NEW"
            assert slot == expected


    def test_no_entry_keeps_the_retired_shared_slot(self):
        text = rs.REGISTRY_FILE.read_text(encoding = "utf-8")
        assert "SECRET_VALUE_NEW" not in text and "value_staging_secret" not in text


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
        with patch.object(rs, "cmd_check", return_value = 0) as c:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and c.called


    def test_record_expiry_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "record-expiry", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("GITHUB_REPOSITORY", "Needless2Say/kriegerdataforge-cicd")
        with patch.object(rs, "cmd_record_expiry", return_value = 0) as r:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and r.called
        assert r.call_args[0][1:3] == ("gh", "Needless2Say/kriegerdataforge-cicd")


    def test_prove_master_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "prove-master"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team_x")
        with patch.object(rs, "cmd_prove_master", return_value = 0) as p:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and p.call_args[0] == ("m", "team_x")


    def test_generate_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "generate", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        monkeypatch.setenv("VERCEL_TEAM_ID", "team_x")
        with patch.object(rs, "cmd_generate", return_value = 0) as g:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and g.called
        assert g.call_args[0][5] == "team_x"  # team_id forwarded to cmd_generate


    def test_generate_requires_team_id(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "generate", "--secrets", "VERCEL_TOKEN"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "m")
        monkeypatch.delenv("VERCEL_TEAM_ID", raising = False)
        with pytest.raises(SystemExit, match = "VERCEL_TEAM_ID"):
            rs.main()


    def test_paste_requires_single_secret(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "paste", "--secrets", "all"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        with pytest.raises(SystemExit, match = "exactly one secret"):
            rs.main()


    def test_paste_single_dispatch(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "paste", "--secrets", "GH_PACKAGES_PAT"])
        monkeypatch.setenv("GH_TOKEN", "gh")
        monkeypatch.setenv("STAGED_SECRET_VALUE", "v")
        with patch.object(rs, "cmd_paste", return_value = 0) as p:
            with pytest.raises(SystemExit) as e:
                rs.main()
        assert e.value.code == 0 and p.called


    def test_missing_registry_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["x", "--mode", "check"])
        mp = MagicMock(spec = Path); mp.is_file.return_value = False
        with patch.object(rs, "REGISTRY_FILE", mp):
            with pytest.raises(SystemExit):
                rs.main()


# ── live expiry (D-049) ─────────────────────────────────────────────────────────
def _resp(status: int = 200, headers: dict | None = None, body: dict | None = None) -> MagicMock:
    resp                   = MagicMock()
    resp.status_code       = status
    resp.ok                = 200 <= status < 300
    resp.headers           = headers or {}
    resp.json.return_value = body or {}
    return resp


def _ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(hour = 12, tzinfo = timezone.utc).timestamp() * 1000)


class TestLiveExpiry:
    """
    Each check.live token's real expiry, read from GitHub or Vercel with the token itself, drift against the registry,
    and no value ever printed (D-049).
    """
    @pytest.mark.parametrize(
        ("raw", "want"),
        [
            ("2026-11-02 12:00:00 UTC", "2026-11-02"),
            ("2026-11-02 23:30:00 -0500", "2026-11-03"),
            ("2026-11-02 01:00:00 +0200", "2026-11-01"),
            ("next tuesday", None),
            ("", None),
        ],
    )
    def test_parse_github_expiry_reads_both_shapes_in_utc(self, raw, want):
        assert rs.parse_github_expiry(raw) == want


    def test_github_reads_the_expiry_header_with_the_token_itself(self):
        with patch.object(
            rs._SESSION,
            "get",
            return_value = _resp( headers = {"github-authentication-token-expiration": "2026-11-02 12:00:00 UTC"}),
        ) as get:
            got = rs.live_expiry({"name": "CICD_PAT", "check": {"live": "github"}}, {"CICD_PAT": TOKEN})
        assert got == ("2026-11-02", "ok")
        assert get.call_args.args[0] == f"{rs.GITHUB_API}/rate_limit"
        assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"


    @pytest.mark.parametrize(
        ("resp", "want"),
        [
            (_resp(401), (None, "rejected")),
            (_resp(200), (None, "no expiry")),
            (_resp(500), (None, "error, HTTP 500")),
            (_resp(200, {"github-authentication-token-expiration": "soon"}),
             (None, "error, an expiry header it cannot read")),
        ],
    )
    def test_github_answers_that_carry_no_date(self, resp, want):
        with patch.object(rs._SESSION, "get", return_value = resp):
            assert rs.live_expiry({"name": "CICD_PAT", "check": {"live": "github"}}, {"CICD_PAT": TOKEN}) == want


    def test_vercel_current_reads_the_tokens_own_metadata(self):
        body = {"token": {"id": "t1", "name": "master", "expiresAt": _ms("2026-12-01")}}
        with patch.object(rs._SESSION, "get", return_value = _resp(body = body)) as get:
            got = rs.live_expiry(
                {"name": "VERCEL_MASTER_TOKEN", "check": {"live": "vercel-current"}},
                {"VERCEL_MASTER_TOKEN": TOKEN},
            )
        assert got == ("2026-12-01", "ok")
        assert get.call_args.args[0] == f"{rs.VERCEL_API}/v5/user/tokens/current"
        with patch.object(rs._SESSION, "get", return_value = _resp(403)):
            assert rs.live_expiry(
                {"name": "VERCEL_MASTER_TOKEN", "check": {"live": "vercel-current"}},
                {"VERCEL_MASTER_TOKEN": TOKEN},
            ) == (None, "rejected")
        with patch.object(rs._SESSION, "get", return_value = _resp(body = {"token": {"id": "t1"}})):
            assert rs.live_expiry(
                {"name": "VERCEL_MASTER_TOKEN", "check": {"live": "vercel-current"}},
                {"VERCEL_MASTER_TOKEN": TOKEN},
            ) == (None, "no expiry")


    def test_vercel_named_takes_the_earliest_of_its_name_through_the_master_token(self):
        """
        After a rotation that kept the old token, a repo may still hold the one that expires first.
        """
        entry = {
            "name": "VERCEL_DEPLOYMENT_TOKEN",
            "vercel_token_name": "VERCEL_DEPLOYMENT_TOKEN",
            "check": {"live": "vercel-named"},
        }
        body  = {"tokens": [
            {"name": "VERCEL_DEPLOYMENT_TOKEN", "expiresAt": _ms("2026-10-20")},
            {"name": "VERCEL_DEPLOYMENT_TOKEN", "expiresAt": _ms("2026-11-18")},
            {"name": "something else", "expiresAt": _ms("2027-01-01")},
        ]}
        with patch.object(rs._SESSION, "get", return_value = _resp(body = body)) as get:
            got = rs.live_expiry(entry, {"VERCEL_MASTER_TOKEN": TOKEN, "VERCEL_DEPLOYMENT_TOKEN": "unused"})
        assert got == (
            "2026-10-20",
            "ok, 2 Vercel tokens are named VERCEL_DEPLOYMENT_TOKEN, the earliest expiry is used",
        )
        assert get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        single = {"tokens": [{"name": "VERCEL_DEPLOYMENT_TOKEN", "expiresAt": _ms("2026-11-18")}]}
        with patch.object(rs._SESSION, "get", return_value = _resp(body = single)):
            assert rs.live_expiry(entry, {"VERCEL_MASTER_TOKEN": TOKEN}) == ("2026-11-18", "ok")
        with patch.object(rs._SESSION, "get", return_value = _resp(body = {"tokens": []})):
            assert rs.live_expiry(entry, {"VERCEL_MASTER_TOKEN": TOKEN}) == (
                None,
                "error, no Vercel token named VERCEL_DEPLOYMENT_TOKEN",
            )
        with patch.object(rs._SESSION, "get", return_value = _resp(401)):
            assert "refused VERCEL_MASTER_TOKEN" in rs.live_expiry(entry, {"VERCEL_MASTER_TOKEN": TOKEN})[1]


    def test_nothing_is_called_without_a_live_source_or_a_token(self):
        with patch.object(rs._SESSION, "get") as get:
            assert rs.live_expiry({"name": "X", "check": {"expiry": "2030-01-01"}}, {}) == (None, "not checked live")
            assert rs.live_expiry({"name": "X", "check": {"live": "github"}}, {}) == (None, "no token in this run")
            assert rs.live_expiry({"name": "X", "check": {"live": "gitlab"}}, {"X": TOKEN}) == (
                None,
                "error, unknown live source gitlab",
            )
        assert not get.called


    def test_an_answer_of_an_unexpected_shape_is_reported_never_raised(self):
        """
        A body that is a list, not an object, raised AttributeError past the check before the review of D-049.
        """
        resp                   = _resp()
        resp.json.return_value = ["not", "an", "object"]
        with patch.object(rs._SESSION, "get", return_value = resp):
            got = rs.live_expiry(
                {"name": "VERCEL_MASTER_TOKEN", "check": {"live": "vercel-current"}},
                {"VERCEL_MASTER_TOKEN": TOKEN},
            )
        assert got == (None, "error, AttributeError")


    def test_two_tokens_of_one_name_are_noted_in_the_check(self, monkeypatch, capsys):
        note = "ok, 2 Vercel tokens are named VERCEL_DEPLOYMENT_TOKEN, the earliest expiry is used"
        monkeypatch.setattr(rs, "live_expiry", lambda entry, environ = None: (_future(90), note))
        day = _future(90)
        assert cmd_check(
            [{"name": "VERCEL_DEPLOYMENT_TOKEN", "check": {"expiry": day, "live": "vercel-named"}}],
            live = True,
        ) == 0
        assert "NOTE — 2 Vercel tokens are named VERCEL_DEPLOYMENT_TOKEN" in capsys.readouterr().out


    def test_a_failed_call_names_its_type_alone(self):
        with patch.object(rs._SESSION, "get", side_effect = rs.requests.ConnectionError(f"boom {TOKEN}")):
            got = rs.live_expiry({"name": "CICD_PAT", "check": {"live": "github"}}, {"CICD_PAT": TOKEN})
        assert got == (None, "error, ConnectionError")


    def _live(self, monkeypatch, expiry: str, live_answer: tuple[str | None, str]) -> list[dict]:
        monkeypatch.setattr(rs, "live_expiry", lambda entry, environ = None: live_answer)
        return [{"name": "CICD_PAT", "check": {"expiry": expiry, "warn_days_before_expiry": 14, "live": "github"}}]


    def test_a_registry_date_that_disagrees_is_drift_and_the_live_date_rules(self, monkeypatch, capsys):
        entries = self._live(monkeypatch, _past(60), (_future(90), "ok"))
        assert cmd_check(entries, live = True) == 1
        out = capsys.readouterr().out
        assert f"DRIFT — the registry says {_past(60)}, GitHub says {_future(90)}" in out
        assert f"REGISTRY_DRIFT: CICD_PAT={_future(90)}" in out
        assert "NEEDS_ROTATION: \n" in out


    def test_a_live_date_past_its_warning_needs_rotation(self, monkeypatch, capsys):
        entries = self._live(monkeypatch, _future(300), (_future(3), "ok"))
        assert cmd_check(entries, live = True) == 1
        out = capsys.readouterr().out
        assert "WARNING — expires in" in out
        assert "NEEDS_ROTATION: CICD_PAT" in out


    def test_a_rejected_token_needs_rotation_whatever_the_registry_says(self, monkeypatch, capsys):
        entries = self._live(monkeypatch, _future(300), (None, "rejected"))
        assert cmd_check(entries, live = True) == 1
        out = capsys.readouterr().out
        assert "CICD_PAT: REJECTED by GitHub, it is expired or revoked. Rotate now." in out
        assert "NEEDS_ROTATION: CICD_PAT" in out


    def test_a_live_check_that_cannot_answer_falls_back_to_the_registry(self, monkeypatch, capsys):
        entries = self._live(monkeypatch, _future(90), (None, "no token in this run"))
        assert cmd_check(entries, live = True) == 0
        out = capsys.readouterr().out
        assert "live check no token in this run, so the registry's date is used." in out
        assert "REGISTRY_DRIFT: \n" in out


    def test_a_matching_date_and_no_expiry_are_healthy(self, monkeypatch, capsys):
        day     = _future(90)
        entries = self._live(monkeypatch, day, (day, "ok"))
        assert cmd_check(entries, live = True) == 0
        entries = self._live(monkeypatch, _past(5), (None, "no expiry"))
        assert cmd_check(entries, live = True) == 0
        assert "GitHub reports no expiry on it" in capsys.readouterr().out


    def test_without_live_the_registry_alone_is_read(self, monkeypatch, capsys):
        monkeypatch.setattr(rs, "live_expiry", lambda *a, **k: pytest.fail("live read without --live"))
        entries = [{"name": "CICD_PAT", "check": {"expiry": _future(90), "live": "github"}}]
        assert cmd_check(entries) == 0


    def test_no_token_value_is_ever_printed(self, capsys):
        answers = [
            _resp(headers = {"github-authentication-token-expiration": "2020-01-01 00:00:00 UTC"}),
            _resp(401),
            _resp(500, body = {"message": TOKEN}),
        ]
        for resp in answers:
            with patch.object(rs._SESSION, "get", return_value = resp):
                cmd_check([{"name": "CICD_PAT", "check": {"expiry": "2030-01-01", "live": "github"}}], live = True)
        printed = capsys.readouterr()
        assert TOKEN not in printed.out + printed.err


    def test_the_real_registry_reads_five_tokens_live(self):
        registry = json.loads(rs.REGISTRY_FILE.read_text(encoding = "utf-8"))
        live     = {e["name"]: e["check"]["live"] for e in registry["secrets"] if (e.get("check") or {}).get("live")}
        assert live == {
            "GH_PACKAGES_PAT": "github",
            "GH_NPM_TOKEN": "github",
            "VERCEL_DEPLOYMENT_TOKEN": "vercel-named",
            "CICD_PAT": "github",
            "VERCEL_MASTER_TOKEN": "vercel-current",
        }
        assert set(live.values()) <= set(rs.LIVE_SOURCES)


    def test_parse_cli_takes_live(self):
        assert rs.parse_cli_args(["--mode", "check", "--live"]).live is True
        assert rs.parse_cli_args(["--mode", "check"]).live is False
