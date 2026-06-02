"""
Unit tests for scripts/rotate_vercel_tokens.py.

All external I/O (requests, filesystem) is mocked; real NaCl crypto is used
for the encryption tests so the round-trip is actually verified.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from nacl import encoding
from nacl.public import PrivateKey, SealedBox

import rotate_vercel_tokens as rvt
from rotate_vercel_tokens import (
    TOKEN_EXPIRY_DAYS,
    _encrypt_secret,
    _get_env_public_key,
    _github_headers,
    _parse_filter,
    _vercel_headers,
    create_vercel_token,
    delete_vercel_token,
    list_vercel_tokens,
    update_github_env_secret,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def nacl_keypair():
    """Real NaCl keypair for encryption round-trip tests."""
    private = PrivateKey.generate()
    pub_b64 = private.public_key.encode(encoding.Base64Encoder).decode()
    return private, pub_b64


@pytest.fixture
def sample_registry():
    return {
        "tokens": [
            {
                "app": "auth-backend",
                "vercel_token_name": "kdf-auth-backend-prod",
                "repo": "Needless2Say/kriegerdataforge",
                "environment": "prod",
                "secret_name": "VERCEL_TOKEN",
            },
            {
                "app": "fitness-frontend",
                "vercel_token_name": "kdf-fitness-frontend-dev",
                "repo": "Needless2Say/fitness-app-frontend",
                "environment": "dev",
                "secret_name": "VERCEL_TOKEN",
            },
        ]
    }


@pytest.fixture
def mock_registry_file(sample_registry):
    """Patch rvt.REGISTRY_FILE so main() reads sample_registry without disk I/O."""
    mock_path = MagicMock(spec=Path)
    mock_path.is_file.return_value = True
    mock_path.read_text.return_value = json.dumps(sample_registry)
    with patch.object(rvt, "REGISTRY_FILE", mock_path):
        yield mock_path


# ── _vercel_headers ────────────────────────────────────────────────────────────


class TestVercelHeaders:
    def test_bearer_format(self):
        h = _vercel_headers("mytoken")
        assert h["Authorization"] == "Bearer mytoken"

    def test_content_type(self):
        assert _vercel_headers("t")["Content-Type"] == "application/json"

    def test_returns_exact_two_keys(self):
        assert set(_vercel_headers("t").keys()) == {"Authorization", "Content-Type"}


# ── _github_headers ────────────────────────────────────────────────────────────


class TestGitHubHeaders:
    def test_bearer_format(self):
        h = _github_headers("ghp_abc")
        assert h["Authorization"] == "Bearer ghp_abc"

    def test_accept_header_contains_github_json(self):
        assert "application/vnd.github+json" in _github_headers("t")["Accept"]

    def test_api_version_header(self):
        assert _github_headers("t")["X-GitHub-Api-Version"] == "2022-11-28"


# ── _parse_filter ──────────────────────────────────────────────────────────────


class TestParseFilter:
    def test_empty_string_matches_all(self):
        assert _parse_filter("") == frozenset()

    def test_all_keyword_matches_all(self):
        assert _parse_filter("all") == frozenset()

    def test_all_case_insensitive(self):
        assert _parse_filter("ALL") == frozenset()
        assert _parse_filter("  All  ") == frozenset()

    def test_single_value_returned_as_set(self):
        assert _parse_filter("auth-backend") == frozenset({"auth-backend"})

    def test_multiple_comma_separated_values(self):
        assert _parse_filter("foo,bar") == frozenset({"foo", "bar"})

    def test_whitespace_stripped_from_parts(self):
        assert _parse_filter("foo, bar") == frozenset({"foo", "bar"})

    def test_trailing_comma_ignored(self):
        assert _parse_filter("foo,bar,") == frozenset({"foo", "bar"})

    def test_consecutive_commas_ignored(self):
        assert _parse_filter("foo,,bar") == frozenset({"foo", "bar"})

    def test_values_are_lowercased(self):
        assert _parse_filter("Foo,BAR") == frozenset({"foo", "bar"})

    def test_returns_frozenset(self):
        assert isinstance(_parse_filter("x"), frozenset)


# ── _encrypt_secret ────────────────────────────────────────────────────────────


class TestEncryptSecret:
    def test_round_trip_decrypts_correctly(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        encrypted_b64 = _encrypt_secret(pub_b64, "super-secret")
        decrypted = SealedBox(private).decrypt(base64.b64decode(encrypted_b64)).decode()
        assert decrypted == "super-secret"

    def test_empty_string_round_trip(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        encrypted_b64 = _encrypt_secret(pub_b64, "")
        decrypted = SealedBox(private).decrypt(base64.b64decode(encrypted_b64)).decode()
        assert decrypted == ""

    def test_different_plaintexts_produce_different_ciphertext(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        assert _encrypt_secret(pub_b64, "a") != _encrypt_secret(pub_b64, "b")

    def test_same_plaintext_produces_different_ciphertext_each_time(self, nacl_keypair):
        # SealedBox uses ephemeral keys so identical plaintexts differ
        _, pub_b64 = nacl_keypair
        assert _encrypt_secret(pub_b64, "x") != _encrypt_secret(pub_b64, "x")

    def test_output_is_valid_base64(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        encrypted = _encrypt_secret(pub_b64, "test")
        decoded = base64.b64decode(encrypted)
        assert len(decoded) > 0


# ── create_vercel_token ────────────────────────────────────────────────────────


class TestCreateVercelToken:
    def test_returns_id_and_bearer_token(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "token": {"id": "tok_xyz"},
            "bearerToken": "bearer_abc",
        }
        with patch("requests.post", return_value=mock_resp) as mock_post:
            token_id, bearer = create_vercel_token("master", "my-token")

        assert token_id == "tok_xyz"
        assert bearer == "bearer_abc"

    def test_request_includes_token_name(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": {"id": "id"}, "bearerToken": "val"}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            create_vercel_token("master", "kdf-auth-backend-prod")
        body = mock_post.call_args[1]["json"]
        assert body["name"] == "kdf-auth-backend-prod"

    def test_request_includes_expiry(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": {"id": "id"}, "bearerToken": "val"}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            create_vercel_token("master", "tok")
        body = mock_post.call_args[1]["json"]
        assert "expiresAt" in body
        # should be roughly TOKEN_EXPIRY_DAYS * 86400 * 1000 ms from now
        from datetime import datetime, timezone
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        assert body["expiresAt"] > now_ms

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 403")
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 403"):
                create_vercel_token("bad", "name")


# ── list_vercel_tokens ─────────────────────────────────────────────────────────


class TestListVercelTokens:
    def test_returns_tokens_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"tokens": [{"id": "t1", "name": "tok1"}]}
        with patch("requests.get", return_value=mock_resp):
            result = list_vercel_tokens("master")
        assert result == [{"id": "t1", "name": "tok1"}]

    def test_returns_empty_list_when_key_absent(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        with patch("requests.get", return_value=mock_resp):
            assert list_vercel_tokens("master") == []

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 401")
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 401"):
                list_vercel_tokens("bad")


# ── delete_vercel_token ────────────────────────────────────────────────────────


class TestDeleteVercelToken:
    def test_calls_delete_endpoint_with_token_id(self):
        mock_resp = MagicMock()
        with patch("requests.delete", return_value=mock_resp) as mock_del:
            delete_vercel_token("master", "tok_old_123")
        url = mock_del.call_args[0][0]
        assert "tok_old_123" in url

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 404")
        with patch("requests.delete", return_value=mock_resp):
            with pytest.raises(Exception, match="HTTP 404"):
                delete_vercel_token("master", "bad_id")


# ── _get_env_public_key ────────────────────────────────────────────────────────


class TestGetEnvPublicKey:
    def test_returns_key_id_and_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key_id": "kid_99", "key": "b64key=="}
        with patch("requests.get", return_value=mock_resp):
            key_id, key = _get_env_public_key("gh", "owner", "repo", "prod")
        assert key_id == "kid_99"
        assert key == "b64key=="

    def test_url_contains_owner_repo_and_environment(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key_id": "k", "key": "v"}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            _get_env_public_key("gh", "MyOwner", "MyRepo", "staging")
        url = mock_get.call_args[0][0]
        assert "MyOwner" in url
        assert "MyRepo" in url
        assert "staging" in url

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 404")
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(Exception):
                _get_env_public_key("tok", "o", "r", "env")


# ── update_github_env_secret ───────────────────────────────────────────────────


class TestUpdateGitHubEnvSecret:
    def test_calls_put_with_correct_key_id_and_encrypted_value(self, nacl_keypair):
        private, pub_b64 = nacl_keypair
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"key_id": "kid_1", "key": pub_b64}
        mock_put_resp = MagicMock()

        with patch("requests.get", return_value=mock_get_resp), \
             patch("requests.put", return_value=mock_put_resp) as mock_put:
            update_github_env_secret("gh", "owner/repo", "prod", "MY_SECRET", "the_value")

        body = mock_put.call_args[1]["json"]
        assert body["key_id"] == "kid_1"
        decrypted = SealedBox(private).decrypt(base64.b64decode(body["encrypted_value"])).decode()
        assert decrypted == "the_value"

    def test_url_contains_owner_repo_environment_and_secret_name(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"key_id": "k", "key": pub_b64}
        mock_put_resp = MagicMock()

        with patch("requests.get", return_value=mock_get_resp), \
             patch("requests.put", return_value=mock_put_resp) as mock_put:
            update_github_env_secret("gh", "Acme/my-repo", "staging", "DEPLOY_TOKEN", "v")

        url = mock_put.call_args[0][0]
        assert "Acme" in url
        assert "my-repo" in url
        assert "staging" in url
        assert "DEPLOY_TOKEN" in url

    def test_raises_when_put_fails(self, nacl_keypair):
        _, pub_b64 = nacl_keypair
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"key_id": "k", "key": pub_b64}
        mock_put_resp = MagicMock()
        mock_put_resp.raise_for_status.side_effect = Exception("HTTP 422")

        with patch("requests.get", return_value=mock_get_resp), \
             patch("requests.put", return_value=mock_put_resp):
            with pytest.raises(Exception, match="HTTP 422"):
                update_github_env_secret("gh", "o/r", "prod", "S", "v")


# ── parse_cli_args ─────────────────────────────────────────────────────────────


class TestParseCLIArgs:
    def test_defaults_to_all(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script"])
        args = rvt.parse_cli_args()
        assert args.apps == "all"
        assert args.envs == "all"

    def test_apps_arg(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend"])
        assert rvt.parse_cli_args().apps == "auth-backend"

    def test_envs_arg(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "--envs", "prod"])
        assert rvt.parse_cli_args().envs == "prod"

    def test_both_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "infra", "--envs", "dev"])
        args = rvt.parse_cli_args()
        assert args.apps == "infra"
        assert args.envs == "dev"

    def test_comma_separated_apps(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend,infra"])
        assert rvt.parse_cli_args().apps == "auth-backend,infra"


# ── main ───────────────────────────────────────────────────────────────────────


class TestMain:
    def test_missing_vercel_master_token_exits(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.delenv("VERCEL_MASTER_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            rvt.main()
        assert "VERCEL_MASTER_TOKEN" in str(exc.value)

    def test_missing_gh_token_exits(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            rvt.main()
        assert "GH_TOKEN" in str(exc.value)

    def test_missing_registry_file_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.setenv("GH_TOKEN", "gh")
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = False
        with patch.object(rvt, "REGISTRY_FILE", mock_path):
            with pytest.raises(SystemExit):
                rvt.main()

    def test_empty_registry_no_candidates_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.setenv("GH_TOKEN", "gh")
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.read_text.return_value = json.dumps({"tokens": []})
        with patch.object(rvt, "REGISTRY_FILE", mock_path):
            with pytest.raises(SystemExit) as exc:
                rvt.main()
        assert "no registry entries matched" in str(exc.value)

    def test_apps_filter_no_match_shows_filter_in_error(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "ghost-app"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.setenv("GH_TOKEN", "gh")
        with pytest.raises(SystemExit) as exc:
            rvt.main()
        assert "apps=ghost-app" in str(exc.value)

    def test_envs_filter_no_match_shows_filter_in_error(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--envs", "staging"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.setenv("GH_TOKEN", "gh")
        with pytest.raises(SystemExit) as exc:
            rvt.main()
        assert "envs=staging" in str(exc.value)

    def test_both_filters_no_match_shows_both_in_error(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "ghost", "--envs", "staging"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "tok")
        monkeypatch.setenv("GH_TOKEN", "gh")
        with pytest.raises(SystemExit) as exc:
            rvt.main()
        msg = str(exc.value)
        assert "apps=ghost" in msg
        assert "envs=staging" in msg

    def test_all_succeed_exits_zero(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", return_value=("nid", "nval")), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token"):
            rvt.main()  # should not raise

    def test_old_token_deleted_when_id_differs(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend", "--envs", "prod"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[
                {"name": "kdf-auth-backend-prod", "id": "old_id"}
             ]), \
             patch.object(rvt, "create_vercel_token", return_value=("new_id", "new_val")), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token") as mock_del:
            rvt.main()

        mock_del.assert_called_once_with("master", "old_id")

    def test_old_token_not_deleted_when_same_id(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend", "--envs", "prod"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[
                {"name": "kdf-auth-backend-prod", "id": "same_id"}
             ]), \
             patch.object(rvt, "create_vercel_token", return_value=("same_id", "new_val")), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token") as mock_del:
            rvt.main()

        mock_del.assert_not_called()

    def test_old_token_not_deleted_when_absent_from_existing(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend", "--envs", "prod"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", return_value=("nid", "nval")), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token") as mock_del:
            rvt.main()

        mock_del.assert_not_called()

    def test_partial_failure_exits_with_code_1(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", side_effect=Exception("API error")), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token"):
            with pytest.raises(SystemExit) as exc:
                rvt.main()
        assert exc.value.code == 1

    def test_filter_by_app_only_rotates_matching_entries(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--apps", "auth-backend"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", return_value=("nid", "nval")) as mock_create, \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token"):
            rvt.main()

        assert mock_create.call_count == 1
        assert mock_create.call_args[0][1] == "kdf-auth-backend-prod"

    def test_filter_by_env_only_rotates_matching_entries(self, monkeypatch, mock_registry_file):
        monkeypatch.setattr(sys, "argv", ["script", "--envs", "dev"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", return_value=("nid", "nval")) as mock_create, \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token"):
            rvt.main()

        assert mock_create.call_count == 1
        assert mock_create.call_args[0][1] == "kdf-fitness-frontend-dev"

    def test_second_failure_after_first_success_still_reports_all_errors(
        self, monkeypatch, mock_registry_file
    ):
        monkeypatch.setattr(sys, "argv", ["script"])
        monkeypatch.setenv("VERCEL_MASTER_TOKEN", "master")
        monkeypatch.setenv("GH_TOKEN", "gh")

        call_count = 0

        def flaky_create(master, name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("nid1", "nval1")
            raise Exception("second entry failed")

        with patch.object(rvt, "list_vercel_tokens", return_value=[]), \
             patch.object(rvt, "create_vercel_token", side_effect=flaky_create), \
             patch.object(rvt, "update_github_env_secret"), \
             patch.object(rvt, "delete_vercel_token"):
            with pytest.raises(SystemExit) as exc:
                rvt.main()

        assert exc.value.code == 1
