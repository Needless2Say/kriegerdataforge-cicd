"""
Unit tests for scripts/rotate_gh_pat.py.

All external I/O (requests, filesystem) is mocked; real NaCl crypto is used
for encryption round-trip tests.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from nacl import encoding
from nacl.public import PrivateKey, SealedBox

import rotate_gh_pat as rgh
from rotate_gh_pat import (
    _encrypt_secret,
    _get_env_public_key,
    _github_headers,
    _list_vercel_env_vars,
    _load_registry,
    _vercel_headers,
    cmd_check,
    cmd_distribute,
    update_github_env_secret,
    upsert_vercel_env_var,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def nacl_keypair():
    private = PrivateKey.generate()
    pub_b64 = private.public_key.encode(encoding.Base64Encoder).decode()
    return private, pub_b64


def _future_date(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _past_date(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


@pytest.fixture
def sample_registry():
    return {
        "pat_name": "kdf-packages-read",
        "pat_expiry": _future_date(60),
        "warn_days_before_expiry": 14,
        "github_env_secrets": [
            {
                "repo": "Needless2Say/kriegerdataforge",
                "environment": "prod",
                "secret_name": "GH_PACKAGES_PAT",
            },
            {
                "repo": "Needless2Say/fitness-app-backend",
                "environment": "dev",
                "secret_name": "GH_PACKAGES_PAT",
            },
        ],
        "vercel_env_vars": [
            {
                "project_id": "prj_real_123",
                "project_name": "kriegerdataforge-prod",
                "env_key": "GH_PACKAGES_PAT",
            },
            {
                "project_id": "TODO_fill_in_later",
                "project_name": "fitness-app-backend-prod",
                "env_key": "GH_PACKAGES_PAT",
            },
        ],
    }


@pytest.fixture
def mock_registry_file(sample_registry):
    mock_path = MagicMock(spec=Path)
    mock_path.is_file.return_value = True
    mock_path.read_text.return_value = json.dumps(sample_registry)
    with patch.object(rgh, "REGISTRY_FILE", mock_path):
        yield mock_path


# ── _vercel_headers ────────────────────────────────────────────────────────────


class TestVercelHeaders:
    def test_bearer_format(self):
        assert _vercel_headers("tok")["Authorization"] == "Bearer tok"

    def test_content_type(self):
        assert _vercel_headers("tok")["Content-Type"] == "application/json"


# ── _github_headers ────────────────────────────────────────────────────────────


class TestGitHubHeaders:
    def test_bearer_format(self):
        assert _github_headers("gh_tok")["Authorization"] == "Bearer gh_tok"

    def test_accept_header(self):
        assert "vnd.github+json" in _github_headers("t")["Accept"]

    def test_api_version(self):
        assert _github_headers("t")["X-GitHub-Api-Version"] == "2022-11-28"


# ── _encrypt_secret ────────────────────────────────────────────────────────────


class TestEncryptSecret:
    def test_round_trip(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        enc = _encrypt_secret(pub_b64, "my-pat-value")
        dec = SealedBox(private).decrypt(base64.b64decode(enc)).decode()
        assert dec == "my-pat-value"

    def test_empty_string_round_trip(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        enc = _encrypt_secret(pub_b64, "")
        dec = SealedBox(private).decrypt(base64.b64decode(enc)).decode()
        assert dec == ""

    def test_output_is_valid_base64(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        assert len(base64.b64decode(_encrypt_secret(pub_b64, "x"))) > 0

    def test_different_plaintexts_differ(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        assert _encrypt_secret(pub_b64, "a") != _encrypt_secret(pub_b64, "b")


# ── _get_env_public_key ────────────────────────────────────────────────────────


class TestGetEnvPublicKey:
    def test_returns_key_id_and_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key_id": "kid_7", "key": "b64key=="}
        with patch("requests.get", return_value=mock_resp):
            key_id, key = _get_env_public_key("gh", "o", "r", "prod")
        assert key_id == "kid_7"
        assert key == "b64key=="

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 404")
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(Exception):
                _get_env_public_key("tok", "o", "r", "env")


# ── update_github_env_secret ───────────────────────────────────────────────────


class TestUpdateGitHubEnvSecret:
    def test_encrypted_value_decrypts_correctly(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        mock_get = MagicMock()
        mock_get.json.return_value = {"key_id": "kid", "key": pub_b64}

        # Use `as mock_put` to capture the callable mock, not a pre-created return value.
        with patch("requests.get", return_value=mock_get), \
             patch("requests.put") as mock_put:
            update_github_env_secret("gh", "o/r", "prod", "SECRET", "pat_value")

        body = mock_put.call_args[1]["json"]
        dec = SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"])).decode()
        assert dec == "pat_value"

    def test_raises_on_put_failure(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        mock_get = MagicMock()
        mock_get.json.return_value = {"key_id": "k", "key": pub_b64}
        mock_put = MagicMock()
        mock_put.raise_for_status.side_effect = Exception("HTTP 422")

        with patch("requests.get", return_value=mock_get), \
             patch("requests.put", return_value=mock_put):
            with pytest.raises(Exception, match="HTTP 422"):
                update_github_env_secret("gh", "o/r", "prod", "S", "v")


# ── _list_vercel_env_vars ──────────────────────────────────────────────────────


class TestListVercelEnvVars:
    def test_returns_envs_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"envs": [{"id": "e1", "key": "FOO"}]}
        with patch("requests.get", return_value=mock_resp):
            result = _list_vercel_env_vars("master", "prj_123")
        assert result == [{"id": "e1", "key": "FOO"}]

    def test_returns_empty_list_when_key_absent(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        with patch("requests.get", return_value=mock_resp):
            assert _list_vercel_env_vars("master", "prj_123") == []

    def test_url_contains_project_id(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"envs": []}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            _list_vercel_env_vars("master", "prj_abc")
        assert "prj_abc" in mock_get.call_args[0][0]

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 403")
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 403"):
                _list_vercel_env_vars("bad", "prj")


# ── upsert_vercel_env_var ──────────────────────────────────────────────────────


class TestUpsertVercelEnvVar:
    def test_posts_when_no_existing_entries(self):
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": []}
        mock_post_resp = MagicMock()

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.post", return_value=mock_post_resp) as mock_post, \
             patch("requests.patch") as mock_patch:
            upsert_vercel_env_var("master", "prj_123", "GH_PACKAGES_PAT", "new_value")

        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert body["key"] == "GH_PACKAGES_PAT"
        assert body["value"] == "new_value"
        assert set(body["target"]) == {"production", "preview", "development"}
        mock_patch.assert_not_called()

    def test_patches_single_existing_entry(self):
        existing_entry = {"id": "env_id_1", "key": "GH_PACKAGES_PAT", "target": ["production"]}
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": [existing_entry]}
        mock_patch_resp = MagicMock()

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.patch", return_value=mock_patch_resp) as mock_patch, \
             patch("requests.post") as mock_post:
            upsert_vercel_env_var("master", "prj_123", "GH_PACKAGES_PAT", "new_value")

        mock_patch.assert_called_once()
        url = mock_patch.call_args[0][0]
        assert "env_id_1" in url
        body = mock_patch.call_args[1]["json"]
        assert body["value"] == "new_value"
        assert body["target"] == ["production"]
        mock_post.assert_not_called()

    def test_patches_multiple_existing_entries(self):
        entries = [
            {"id": "e1", "key": "GH_PACKAGES_PAT", "target": ["production"]},
            {"id": "e2", "key": "GH_PACKAGES_PAT", "target": ["preview"]},
            {"id": "e3", "key": "GH_PACKAGES_PAT", "target": ["development"]},
        ]
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": entries}
        mock_patch_resp = MagicMock()

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.patch", return_value=mock_patch_resp) as mock_patch, \
             patch("requests.post") as mock_post:
            upsert_vercel_env_var("master", "prj_123", "GH_PACKAGES_PAT", "val")

        assert mock_patch.call_count == 3
        patched_ids = {c[0][0].split("/")[-1] for c in mock_patch.call_args_list}
        assert patched_ids == {"e1", "e2", "e3"}
        mock_post.assert_not_called()

    def test_only_matches_entries_with_correct_key(self):
        entries = [
            {"id": "e1", "key": "GH_PACKAGES_PAT", "target": ["production"]},
            {"id": "e2", "key": "OTHER_VAR", "target": ["production"]},
        ]
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": entries}
        mock_patch_resp = MagicMock()

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.patch", return_value=mock_patch_resp) as mock_patch, \
             patch("requests.post"):
            upsert_vercel_env_var("master", "prj_123", "GH_PACKAGES_PAT", "val")

        assert mock_patch.call_count == 1
        assert "e1" in mock_patch.call_args[0][0]

    def test_raises_on_patch_failure(self):
        entries = [{"id": "e1", "key": "GH_PACKAGES_PAT", "target": ["production"]}]
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": entries}
        mock_patch_resp = MagicMock()
        mock_patch_resp.raise_for_status.side_effect = Exception("HTTP 400")

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.patch", return_value=mock_patch_resp):
            with pytest.raises(Exception, match="HTTP 400"):
                upsert_vercel_env_var("master", "prj", "GH_PACKAGES_PAT", "v")

    def test_raises_on_post_failure(self):
        mock_list_resp = MagicMock()
        mock_list_resp.json.return_value = {"envs": []}
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.side_effect = Exception("HTTP 409")

        with patch("requests.get", return_value=mock_list_resp), \
             patch("requests.post", return_value=mock_post_resp):
            with pytest.raises(Exception, match="HTTP 409"):
                upsert_vercel_env_var("master", "prj", "GH_PACKAGES_PAT", "v")


# ── _load_registry ─────────────────────────────────────────────────────────────


class TestLoadRegistry:
    def test_loads_valid_registry(self, tmp_path):
        reg = {"pat_name": "test", "pat_expiry": "2099-01-01"}
        reg_file = tmp_path / "gh_pat_registry.json"
        reg_file.write_text(json.dumps(reg), encoding="utf-8")
        with patch.object(rgh, "REGISTRY_FILE", reg_file):
            result = _load_registry()
        assert result["pat_name"] == "test"

    def test_exits_when_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch.object(rgh, "REGISTRY_FILE", missing):
            with pytest.raises(SystemExit):
                _load_registry()


# ── cmd_check ──────────────────────────────────────────────────────────────────


class TestCmdCheck:
    def _reg(self, expiry: str, warn: int = 14) -> dict:
        return {"pat_expiry": expiry, "warn_days_before_expiry": warn}

    def test_ok_when_plenty_of_time_left(self):
        assert cmd_check(self._reg(_future_date(60))) == 0

    def test_ok_exactly_one_day_beyond_warn_threshold(self):
        # warn=14 → need days_remaining > 14. Use +16 to stay safe across the
        # midnight boundary: cmd_check parses the date string to 00:00 UTC, so
        # (date+16days 00:00 - now HH:MM).days is always >= 15 regardless of time of day.
        assert cmd_check(self._reg(_future_date(16), warn=14)) == 0

    def test_warns_at_warn_days_boundary(self):
        # warn=14, days_remaining=14 → 14 <= 14 → warn
        assert cmd_check(self._reg(_future_date(14), warn=14)) == 1

    def test_warns_within_warn_days(self):
        assert cmd_check(self._reg(_future_date(7), warn=14)) == 1

    def test_warns_on_expiry_day(self):
        # days_remaining=0 → 0 <= 14
        assert cmd_check(self._reg(_future_date(0), warn=14)) == 1

    def test_warns_when_expired(self):
        assert cmd_check(self._reg(_past_date(1), warn=14)) == 1

    def test_warns_when_long_expired(self):
        assert cmd_check(self._reg(_past_date(90), warn=14)) == 1

    def test_exits_when_expiry_is_todo(self):
        assert cmd_check(self._reg("TODO_fill_in")) == 1

    def test_exits_when_expiry_is_empty(self):
        assert cmd_check({"pat_expiry": "", "warn_days_before_expiry": 14}) == 1

    def test_exits_when_expiry_key_missing(self):
        assert cmd_check({"warn_days_before_expiry": 14}) == 1

    def test_exits_on_invalid_date_format(self):
        assert cmd_check(self._reg("01/01/2030")) == 1

    def test_uses_default_warn_days_when_key_missing(self):
        # No warn_days_before_expiry key → defaults to 14
        reg = {"pat_expiry": _future_date(7)}
        assert cmd_check(reg) == 1

    def test_custom_warn_days(self):
        reg = {"pat_expiry": _future_date(30), "warn_days_before_expiry": 7}
        assert cmd_check(reg) == 0  # 30 > 7 → OK

    def test_expired_message_mentions_expired(self, capsys):
        cmd_check(self._reg(_past_date(3)))
        assert "EXPIRED" in capsys.readouterr().out

    def test_warning_message_mentions_warning(self, capsys):
        cmd_check(self._reg(_future_date(5), warn=14))
        assert "WARNING" in capsys.readouterr().out

    def test_ok_message_confirms_valid(self, capsys):
        cmd_check(self._reg(_future_date(60)))
        assert "OK" in capsys.readouterr().out


# ── cmd_distribute ─────────────────────────────────────────────────────────────


class TestCmdDistribute:
    def test_missing_pat_new_exits(self, monkeypatch, sample_registry):
        monkeypatch.delenv("GH_PACKAGES_PAT_NEW", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        with pytest.raises(SystemExit) as exc:
            cmd_distribute(sample_registry)
        assert "GH_PACKAGES_PAT_NEW" in str(exc.value)

    def test_missing_gh_token_exits(self, monkeypatch, sample_registry):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new_token")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            cmd_distribute(sample_registry)
        assert "GH_TOKEN" in str(exc.value)

    def test_missing_vercel_token_skips_vercel_but_continues(
        self, monkeypatch, sample_registry
    ):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)

        with patch.object(rgh, "update_github_env_secret") as mock_gh, \
             patch.object(rgh, "upsert_vercel_env_var") as mock_vercel:
            result = cmd_distribute(sample_registry)

        assert result == 0
        assert mock_gh.call_count == 2
        mock_vercel.assert_not_called()

    def test_missing_vercel_token_prints_warning(self, monkeypatch, sample_registry, capsys):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)

        with patch.object(rgh, "update_github_env_secret"):
            cmd_distribute(sample_registry)

        assert "VERCEL_MASTER_TOKEN" in capsys.readouterr().out

    def test_pushes_to_all_github_env_secrets(self, monkeypatch, sample_registry):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new_value")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)

        with patch.object(rgh, "update_github_env_secret") as mock_gh:
            cmd_distribute(sample_registry)

        assert mock_gh.call_count == 2
        calls = [c[0] for c in mock_gh.call_args_list]
        repos = {c[1] for c in calls}
        assert "Needless2Say/kriegerdataforge" in repos
        assert "Needless2Say/fitness-app-backend" in repos
        # verify correct PAT value is pushed (c[4] = secret_value, c[3] = secret_name)
        for c in calls:
            assert c[4] == "ghp_new_value"

    def test_skips_vercel_entries_with_todo_project_id(self, monkeypatch, sample_registry, capsys):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "v_master")

        with patch.object(rgh, "update_github_env_secret"), \
             patch.object(rgh, "upsert_vercel_env_var") as mock_vercel:
            cmd_distribute(sample_registry)

        # Only the real project (prj_real_123) should be upserted
        assert mock_vercel.call_count == 1
        assert mock_vercel.call_args[0][1] == "prj_real_123"
        # skipped project name mentioned in output (project_id is not printed, project_name is)
        assert "fill in project_id" in capsys.readouterr().out

    def test_updates_real_vercel_projects(self, monkeypatch, sample_registry):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "v_master")

        with patch.object(rgh, "update_github_env_secret"), \
             patch.object(rgh, "upsert_vercel_env_var") as mock_vercel:
            cmd_distribute(sample_registry)

        mock_vercel.assert_called_once_with("v_master", "prj_real_123", "GH_PACKAGES_PAT", "ghp_new")

    def test_github_failure_is_collected_and_returns_1(self, monkeypatch, sample_registry):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)

        with patch.object(rgh, "update_github_env_secret", side_effect=Exception("API down")):
            result = cmd_distribute(sample_registry)

        assert result == 1

    def test_vercel_failure_is_collected_and_returns_1(self, monkeypatch, sample_registry):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "v_master")

        with patch.object(rgh, "update_github_env_secret"), \
             patch.object(rgh, "upsert_vercel_env_var", side_effect=Exception("Vercel error")):
            result = cmd_distribute(sample_registry)

        assert result == 1

    def test_all_succeed_returns_0_and_prints_followup(
        self, monkeypatch, sample_registry, capsys
    ):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "v_master")

        with patch.object(rgh, "update_github_env_secret"), \
             patch.object(rgh, "upsert_vercel_env_var"):
            result = cmd_distribute(sample_registry)

        assert result == 0
        out = capsys.readouterr().out
        assert "pat_expiry" in out
        assert "GH_PACKAGES_PAT_NEW" in out

    def test_partial_github_failure_still_pushes_remaining_targets(
        self, monkeypatch, sample_registry
    ):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)

        call_count = [0]

        def flaky_gh(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("first call failed")

        with patch.object(rgh, "update_github_env_secret", side_effect=flaky_gh):
            result = cmd_distribute(sample_registry)

        assert result == 1
        assert call_count[0] == 2  # both targets were attempted

    def test_all_vercel_todo_skipped_returns_0_if_github_ok(
        self, monkeypatch, sample_registry
    ):
        monkeypatch.setenv("GH_PACKAGES_PAT_NEW", "ghp_new")
        monkeypatch.setenv("GH_TOKEN", "gh_tok")
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "v_master")

        # Make all Vercel project IDs TODO
        registry_all_todo = dict(sample_registry)
        registry_all_todo["vercel_env_vars"] = [
            {"project_id": "TODO_1", "project_name": "app1", "env_key": "GH_PACKAGES_PAT"},
        ]

        with patch.object(rgh, "update_github_env_secret"), \
             patch.object(rgh, "upsert_vercel_env_var") as mock_vercel:
            result = cmd_distribute(registry_all_todo)

        assert result == 0
        mock_vercel.assert_not_called()


# ── parse_cli_args ─────────────────────────────────────────────────────────────


class TestParseCLIArgs:
    def test_check_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "check"])
        assert rgh.parse_cli_args().mode == "check"

    def test_distribute_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "distribute"])
        assert rgh.parse_cli_args().mode == "distribute"

    def test_invalid_mode_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "invalid"])
        with pytest.raises(SystemExit):
            rgh.parse_cli_args()

    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script"])
        with pytest.raises(SystemExit):
            rgh.parse_cli_args()


# ── main ───────────────────────────────────────────────────────────────────────


class TestMain:
    def test_check_mode_passes(self, monkeypatch, mock_registry_file, sample_registry):
        monkeypatch.setattr(sys, "argv", ["script", "check"])
        # sample_registry has expiry 60 days out → should exit 0
        with patch.object(rgh, "cmd_check", return_value=0) as mock_check:
            with pytest.raises(SystemExit) as exc:
                rgh.main()
        assert exc.value.code == 0

    def test_check_mode_fails_when_expiring(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "check"])
        with patch.object(rgh, "cmd_check", return_value=1):
            with pytest.raises(SystemExit) as exc:
                rgh.main()
        assert exc.value.code == 1

    def test_distribute_mode_success(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "distribute"])
        with patch.object(rgh, "cmd_distribute", return_value=0):
            with pytest.raises(SystemExit) as exc:
                rgh.main()
        assert exc.value.code == 0

    def test_distribute_mode_failure(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "distribute"])
        with patch.object(rgh, "cmd_distribute", return_value=1):
            with pytest.raises(SystemExit) as exc:
                rgh.main()
        assert exc.value.code == 1
