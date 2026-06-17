"""
Unit tests for scripts/check_deployer.py.

The registry is provided in-memory (or via a tmp file) — no real filesystem
registry or network access is required.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

import check_deployer as cd
from check_deployer import (
    _load_registry,
    _resolve,
    is_authorized,
    main,
    parse_cli_args,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def sample_registry():
    return {
        "deployers": {
            "Needless2Say/fitness-app-frontend": {
                "dev": ["Needless2Say", "Ascensionn"],
                "prod": ["Needless2Say"],
            },
            "Needless2Say/kriegerdataforge": {
                "dev": ["Needless2Say"],
                "prod": ["Needless2Say"],
            },
            "Needless2Say/arthurs-portfolio": {
                "github-pages": ["Needless2Say"],
            },
        }
    }


# ── is_authorized ──────────────────────────────────────────────────────────────


class TestIsAuthorized:
    def test_owner_allowed_on_prod(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "prod", "Needless2Say")
        assert ok is True

    def test_collaborator_allowed_on_dev(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/fitness-app-frontend", "dev", "Ascensionn")
        assert ok is True

    def test_collaborator_denied_on_prod(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "Needless2Say/fitness-app-frontend", "prod", "Ascensionn")
        assert ok is False
        assert "NOT an approved deployer" in reason

    def test_matching_is_case_insensitive(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/fitness-app-frontend", "dev", "ASCENSIONN")
        assert ok is True

    def test_actor_surrounding_whitespace_ignored(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "dev", "  Needless2Say  ")
        assert ok is True

    def test_unknown_repo_denied_fail_closed(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "Needless2Say/not-registered", "dev", "Needless2Say")
        assert ok is False
        assert "not in the deployer registry" in reason

    def test_unknown_environment_denied_fail_closed(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "staging", "Needless2Say")
        assert ok is False
        assert "not configured" in reason

    def test_unknown_environment_message_lists_known_envs(self, sample_registry):
        _, reason = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "staging", "Needless2Say")
        assert "dev" in reason and "prod" in reason

    def test_unknown_actor_denied(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "dev", "randomperson")
        assert ok is False
        assert "randomperson" in reason

    def test_github_pages_environment(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/arthurs-portfolio", "github-pages", "Needless2Say")
        assert ok is True

    def test_empty_actor_denied(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "Needless2Say/kriegerdataforge", "dev", "")
        assert ok is False

    def test_empty_deployers_registry_denies(self):
        ok, reason = is_authorized({"deployers": {}}, "Needless2Say/kriegerdataforge", "dev", "Needless2Say")
        assert ok is False
        assert "not in the deployer registry" in reason


# ── _resolve ───────────────────────────────────────────────────────────────────


class TestResolve:
    def test_cli_value_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_REPO", "from-env")
        assert _resolve("from-cli", "DEPLOY_REPO") == "from-cli"

    def test_falls_back_to_first_env(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_ACTOR", raising=False)
        monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "tactor")
        assert _resolve(None, "DEPLOY_ACTOR", "GITHUB_TRIGGERING_ACTOR", "GITHUB_ACTOR") == "tactor"

    def test_skips_empty_env_values(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ACTOR", "")
        monkeypatch.setenv("GITHUB_ACTOR", "fallback")
        assert _resolve(None, "DEPLOY_ACTOR", "GITHUB_ACTOR") == "fallback"

    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPO", raising=False)
        assert _resolve(None, "DEPLOY_REPO") == ""

    def test_empty_string_cli_value_is_kept(self, monkeypatch):
        # An explicit "" (not None) means the caller passed a flag — keep it.
        monkeypatch.setenv("DEPLOY_REPO", "env-value")
        assert _resolve("", "DEPLOY_REPO") == ""


# ── _load_registry ─────────────────────────────────────────────────────────────


class TestLoadRegistry:
    def test_loads_valid_registry(self, tmp_path):
        reg = {"deployers": {"a/b": {"dev": ["x"]}}}
        reg_file = tmp_path / "deployer_registry.json"
        reg_file.write_text(json.dumps(reg), encoding="utf-8")
        with patch.object(cd, "REGISTRY_FILE", reg_file):
            assert _load_registry()["deployers"]["a/b"]["dev"] == ["x"]

    def test_exits_when_file_missing(self, tmp_path):
        with patch.object(cd, "REGISTRY_FILE", tmp_path / "nope.json"):
            with pytest.raises(SystemExit):
                _load_registry()

    def test_real_registry_file_is_valid_json_and_well_formed(self):
        """The committed registry parses and every entry maps env -> list[str]."""
        registry = _load_registry()
        assert isinstance(registry.get("deployers"), dict)
        assert registry["deployers"], "registry must list at least one repo"
        for repo, envs in registry["deployers"].items():
            assert "/" in repo, f"repo key '{repo}' should be owner/repo"
            assert isinstance(envs, dict) and envs, f"{repo} must map environments to deployers"
            for env, users in envs.items():
                assert isinstance(users, list) and users, f"{repo}[{env}] must be a non-empty list"
                assert all(isinstance(u, str) and u.strip() for u in users)

    def test_real_registry_seeded_expectations(self):
        """Guards the seeded policy: owner everywhere, Ascensionn on the two fitness repos' dev only."""
        deployers = _load_registry()["deployers"]
        for repo, envs in deployers.items():
            for env, users in envs.items():
                assert "Needless2Say" in users, f"owner missing from {repo}[{env}]"
        for repo in ("Needless2Say/fitness-app-frontend", "Needless2Say/fitness-app-backend"):
            assert "Ascensionn" in deployers[repo]["dev"]
            assert "Ascensionn" not in deployers[repo]["prod"]


# ── parse_cli_args ─────────────────────────────────────────────────────────────


class TestParseCLIArgs:
    def test_defaults_are_none(self):
        args = parse_cli_args([])
        assert args.repo is None and args.actor is None and args.environment is None

    def test_parses_all_flags(self):
        args = parse_cli_args(["--repo", "o/r", "--actor", "me", "--environment", "dev"])
        assert (args.repo, args.actor, args.environment) == ("o/r", "me", "dev")


# ── main ───────────────────────────────────────────────────────────────────────


class TestMain:
    def _patch_registry(self, registry):
        return patch.object(cd, "_load_registry", return_value=registry)

    def test_returns_0_for_approved_actor(self, sample_registry):
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "Needless2Say/kriegerdataforge", "--actor", "Needless2Say", "--environment", "prod"])
        assert rc == 0

    def test_returns_1_for_unapproved_actor(self, sample_registry):
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "Needless2Say/fitness-app-frontend", "--actor", "Ascensionn", "--environment", "prod"])
        assert rc == 1

    def test_returns_1_for_unknown_repo(self, sample_registry):
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "Needless2Say/ghost", "--actor", "Needless2Say", "--environment", "dev"])
        assert rc == 1

    def test_returns_1_when_required_input_missing(self, sample_registry, monkeypatch):
        # No env fallbacks available, and environment flag omitted.
        for var in ("DEPLOY_REPO", "GITHUB_REPOSITORY", "DEPLOY_ACTOR", "GITHUB_TRIGGERING_ACTOR",
                    "GITHUB_ACTOR", "DEPLOY_ENVIRONMENT"):
            monkeypatch.delenv(var, raising=False)
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "Needless2Say/kriegerdataforge", "--actor", "Needless2Say"])
        assert rc == 1

    def test_reads_values_from_environment(self, sample_registry, monkeypatch):
        monkeypatch.setenv("DEPLOY_REPO", "Needless2Say/kriegerdataforge")
        monkeypatch.setenv("DEPLOY_ACTOR", "Needless2Say")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "dev")
        with self._patch_registry(sample_registry):
            rc = main([])
        assert rc == 0

    def test_triggering_actor_preferred_over_github_actor(self, sample_registry, monkeypatch):
        # github.triggering_actor (approved) should win over GITHUB_ACTOR (not approved).
        monkeypatch.setenv("DEPLOY_REPO", "Needless2Say/fitness-app-frontend")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "dev")
        monkeypatch.delenv("DEPLOY_ACTOR", raising=False)
        monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "Ascensionn")
        monkeypatch.setenv("GITHUB_ACTOR", "someone-else")
        with self._patch_registry(sample_registry):
            rc = main([])
        assert rc == 0

    def test_denied_message_printed(self, sample_registry, capsys):
        with self._patch_registry(sample_registry):
            main(["--repo", "Needless2Say/ghost", "--actor", "x", "--environment", "dev"])
        assert "DENIED:" in capsys.readouterr().out

    def test_approved_message_printed(self, sample_registry, capsys):
        with self._patch_registry(sample_registry):
            main(["--repo", "Needless2Say/kriegerdataforge", "--actor", "Needless2Say", "--environment", "dev"])
        assert "OK:" in capsys.readouterr().out

    def test_writes_step_summary_when_env_set(self, sample_registry, monkeypatch, tmp_path):
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        with self._patch_registry(sample_registry):
            main(["--repo", "Needless2Say/kriegerdataforge", "--actor", "Needless2Say", "--environment", "dev"])
        assert "Deployer authorization" in summary.read_text(encoding="utf-8")


# ── module entry guard ──────────────────────────────────────────────────────────


class TestEntryGuard:
    def test_main_callable_with_argv(self, sample_registry, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["check_deployer.py"])
        monkeypatch.setenv("DEPLOY_REPO", "Needless2Say/kriegerdataforge")
        monkeypatch.setenv("DEPLOY_ACTOR", "Needless2Say")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "prod")
        with patch.object(cd, "_load_registry", return_value=sample_registry):
            assert main() == 0
