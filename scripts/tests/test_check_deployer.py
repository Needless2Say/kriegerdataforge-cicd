"""
Unit tests for scripts/check_deployer.py.

The registry is provided in-memory (or via a tmp file) — no real filesystem
registry or network access is required.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import check_deployer as cd
import pytest
from check_deployer import (
    _load_registry,
    _resolve,
    is_authorized,
    main,
    parse_cli_args,
)

# a scratch bot for the bot's rule, its numeric id, its login and the one caller its grant names
BOT_ID    = "100000001"
BOT_LOGIN = "kdf-dispatcher[bot]"
CALLER    = "NeedlessAlloy/kriegerdataforge/.github/workflows/cd.yml@refs/heads/main"


# ── Shared fixtures ────────────────────────────────────────────────────────────
@pytest.fixture(autouse = True)
def _the_runner_names_the_owner_as_the_starter(monkeypatch):
    # the runner sets GITHUB_ACTOR, who started the run, in every job. a test that is about the starter sets its own
    monkeypatch.setenv("GITHUB_ACTOR", "NeedlessAlloy")
    monkeypatch.delenv("DEPLOY_STARTED_BY", raising = False)


@pytest.fixture
def sample_registry():
    return {
        "deployers": {
            "NeedlessAlloy/fitness-app-frontend": {
                "dev": ["NeedlessAlloy", "Ascensionn"],
                "prod": ["NeedlessAlloy"],
            },
            "NeedlessAlloy/kriegerdataforge": {
                "dev": ["NeedlessAlloy"],
                "prod": ["NeedlessAlloy"],
            },
            "NeedlessAlloy/arthurs-portfolio": {
                "github-pages": ["NeedlessAlloy"],
            },
        }
    }


# ── is_authorized ──────────────────────────────────────────────────────────────
class TestIsAuthorized:
    def test_owner_allowed_on_prod(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "prod", "NeedlessAlloy")
        assert ok is True


    def test_collaborator_allowed_on_dev(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/fitness-app-frontend", "dev", "Ascensionn")
        assert ok is True


    def test_collaborator_denied_on_prod(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "NeedlessAlloy/fitness-app-frontend", "prod", "Ascensionn")
        assert ok is False
        assert "NOT an approved deployer" in reason


    def test_matching_is_case_insensitive(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/fitness-app-frontend", "dev", "ASCENSIONN")
        assert ok is True


    def test_actor_surrounding_whitespace_ignored(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "dev", "  NeedlessAlloy  ")
        assert ok is True


    def test_unknown_repo_denied_fail_closed(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "NeedlessAlloy/not-registered", "dev", "NeedlessAlloy")
        assert ok is False
        assert "not in the deployer registry" in reason


    def test_unknown_environment_denied_fail_closed(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "staging", "NeedlessAlloy")
        assert ok is False
        assert "not configured" in reason


    def test_unknown_environment_message_lists_known_envs(self, sample_registry):
        _, reason = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "staging", "NeedlessAlloy")
        assert "dev" in reason and "prod" in reason


    def test_unknown_actor_denied(self, sample_registry):
        ok, reason = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "dev", "randomperson")
        assert ok is False
        assert "randomperson" in reason


    def test_github_pages_environment(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/arthurs-portfolio", "github-pages", "NeedlessAlloy")
        assert ok is True


    def test_empty_actor_denied(self, sample_registry):
        ok, _ = is_authorized(sample_registry, "NeedlessAlloy/kriegerdataforge", "dev", "")
        assert ok is False


    def test_empty_deployers_registry_denies(self):
        ok, reason = is_authorized({"deployers": {}}, "NeedlessAlloy/kriegerdataforge", "dev", "NeedlessAlloy")
        assert ok is False
        assert "not in the deployer registry" in reason


# ── _resolve ───────────────────────────────────────────────────────────────────
class TestResolve:
    def test_cli_value_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_REPO", "from-env")
        assert _resolve("from-cli", "DEPLOY_REPO") == "from-cli"


    def test_falls_back_to_first_env(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_ACTOR", raising = False)
        monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "tactor")
        assert _resolve(None, "DEPLOY_ACTOR", "GITHUB_TRIGGERING_ACTOR", "GITHUB_ACTOR") == "tactor"


    def test_skips_empty_env_values(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ACTOR", "")
        monkeypatch.setenv("GITHUB_ACTOR", "fallback")
        assert _resolve(None, "DEPLOY_ACTOR", "GITHUB_ACTOR") == "fallback"


    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_REPO", raising = False)
        assert _resolve(None, "DEPLOY_REPO") == ""


    def test_empty_string_cli_value_is_kept(self, monkeypatch):
        # An explicit "" (not None) means the caller passed a flag — keep it.
        monkeypatch.setenv("DEPLOY_REPO", "env-value")
        assert _resolve("", "DEPLOY_REPO") == ""


# ── _load_registry ─────────────────────────────────────────────────────────────
class TestLoadRegistry:
    def test_loads_valid_registry(self, tmp_path):
        reg      = {"deployers": {"a/b": {"dev": ["x"]}}}
        reg_file = tmp_path / "deployer_registry.json"
        reg_file.write_text(json.dumps(reg), encoding = "utf-8")
        with patch.object(cd, "REGISTRY_FILE", reg_file):
            assert _load_registry()["deployers"]["a/b"]["dev"] == ["x"]


    def test_exits_when_file_missing(self, tmp_path):
        with patch.object(cd, "REGISTRY_FILE", tmp_path / "nope.json"):
            with pytest.raises(SystemExit):
                _load_registry()


    def test_real_registry_file_is_valid_json_and_well_formed(self):
        """
        The committed registry parses and every entry maps env -> list[str].
        """
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
        """
        Guards the seeded policy: the owner everywhere and no one else.
        """
        deployers = _load_registry()["deployers"]
        for repo, envs in deployers.items():
            for env, users in envs.items():
                assert users == ["NeedlessAlloy"], f"{repo}[{env}] lists {users}"


# ── parse_cli_args ─────────────────────────────────────────────────────────────
class TestParseCLIArgs:
    def test_defaults_are_none(self):
        args = parse_cli_args([])
        assert args.repo is None and args.actor is None and args.environment is None


    def test_parses_all_flags(self):
        args = parse_cli_args(["--repo", "o/r", "--actor", "me", "--environment", "dev"])
        assert (args.repo, args.actor, args.environment) == ("o/r", "me", "dev")


# ── the real registry ─────────────────────────────────────────────────────────
class TestTheRealRegistry:
    """
    The registry this repo ships, read as the gate reads it.
    """
    @pytest.mark.parametrize("repo", ["NeedlessAlloy/fitness-app-backend", "NeedlessAlloy/fitness-app-frontend"])
    def test_a_login_no_longer_listed_is_refused_on_dev(self, repo):
        ok, _ = is_authorized(_load_registry(), repo, "dev", "Ascensionn")
        assert ok is False


    def test_the_comment_names_both_users_the_check_reads(self):
        comment = _load_registry()["_comment"]
        assert "github.actor" in comment and "github.triggering_actor" in comment


# ── main ───────────────────────────────────────────────────────────────────────
class TestMain:
    def _patch_registry(self, registry):
        return patch.object(cd, "_load_registry", return_value = registry)


    def test_returns_0_for_approved_actor(self, sample_registry):
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--environment", "prod"])
        assert rc == 0


    def test_returns_1_for_unapproved_actor(self, sample_registry):
        with self._patch_registry(sample_registry):
            repo = "NeedlessAlloy/fitness-app-frontend"
            rc   = main(["--repo", repo, "--actor", "Ascensionn", "--environment", "prod"])
        assert rc == 1


    def test_returns_1_for_unknown_repo(self, sample_registry):
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "NeedlessAlloy/ghost", "--actor", "NeedlessAlloy", "--environment", "dev"])
        assert rc == 1


    def test_returns_1_when_required_input_missing(self, sample_registry, monkeypatch):
        # No env fallbacks available, and environment flag omitted.
        for var in (
            "DEPLOY_REPO",
            "GITHUB_REPOSITORY",
            "DEPLOY_ACTOR",
            "GITHUB_TRIGGERING_ACTOR",
            "GITHUB_ACTOR",
            "DEPLOY_ENVIRONMENT",
        ):
            monkeypatch.delenv(var, raising = False)
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy"])
        assert rc == 1


    def test_reads_values_from_environment(self, sample_registry, monkeypatch):
        monkeypatch.setenv("DEPLOY_REPO", "NeedlessAlloy/kriegerdataforge")
        monkeypatch.setenv("DEPLOY_ACTOR", "NeedlessAlloy")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "dev")
        with self._patch_registry(sample_registry):
            rc = main([])
        assert rc == 0


    def test_an_approved_rerun_of_a_run_another_started_is_denied(self, sample_registry, monkeypatch):
        # a rerun keeps github.actor, who started the run, and sets the triggering actor to whoever reran it, so an
        # approved deployer's rerun of a deploy a stranger started stays denied
        monkeypatch.setenv("DEPLOY_REPO", "NeedlessAlloy/fitness-app-frontend")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "dev")
        monkeypatch.delenv("DEPLOY_ACTOR", raising = False)
        monkeypatch.delenv("DEPLOY_STARTED_BY", raising = False)
        monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "Ascensionn")
        monkeypatch.setenv("GITHUB_ACTOR", "someone-else")
        with self._patch_registry(sample_registry):
            rc = main([])
        assert rc == 1


    def test_the_bot_that_started_a_run_is_denied_when_the_owner_reruns_it(self, sample_registry, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")
        monkeypatch.delenv("DEPLOY_STARTED_BY", raising = False)
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--environment", "prod"])
        assert rc == 1


    def test_the_flag_for_who_started_the_run_wins_over_the_runner(self, sample_registry, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")
        with self._patch_registry(sample_registry):
            rc = main([
                "--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--started-by", "needlessalloy",
                "--environment", "prod",
            ])
        assert rc == 0


    def test_a_run_whose_starter_is_unknown_is_denied(self, sample_registry, monkeypatch, capsys):
        for var in ("DEPLOY_STARTED_BY", "GITHUB_ACTOR"):
            monkeypatch.delenv(var, raising = False)
        with self._patch_registry(sample_registry):
            rc = main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--environment", "prod"])
        assert rc == 1
        assert "started_by" in capsys.readouterr().out


    def test_denied_message_printed(self, sample_registry, capsys):
        with self._patch_registry(sample_registry):
            main(["--repo", "NeedlessAlloy/ghost", "--actor", "x", "--environment", "dev"])
        assert "DENIED:" in capsys.readouterr().out


    def test_approved_message_printed(self, sample_registry, capsys):
        with self._patch_registry(sample_registry):
            main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--environment", "dev"])
        assert "OK:" in capsys.readouterr().out


    def test_writes_step_summary_when_env_set(self, sample_registry, monkeypatch, tmp_path):
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        with self._patch_registry(sample_registry):
            main(["--repo", "NeedlessAlloy/kriegerdataforge", "--actor", "NeedlessAlloy", "--environment", "dev"])
        assert "Deployer authorization" in summary.read_text(encoding = "utf-8")


# ── the bot's rule ─────────────────────────────────────────────────────────────
@pytest.fixture
def bot_registry(sample_registry):
    registry = dict(sample_registry)
    registry["automation"] = {
        "bots": {
            BOT_ID: {
                "NeedlessAlloy/kriegerdataforge": {
                    "prod": {"workflow": ".github/workflows/cd.yml", "ref": "refs/heads/main"},
                },
            },
        },
    }
    return registry


def _bot_run(**overrides: str) -> list[str]:
    """
    The flags of a run the bot started and dispatched, its first attempt, from the deploy job, each one overridable.
    """
    flags = {
        "repo": "NeedlessAlloy/kriegerdataforge",
        "environment": "prod",
        "actor": BOT_LOGIN,
        "started-by": BOT_LOGIN,
        "actor-id": BOT_ID,
        "profile": "redeploy",
        "event": "workflow_dispatch",
        "workflow-ref": CALLER,
        "run-attempt": "1",
    }
    flags.update({key.replace("_", "-"): value for key, value in overrides.items()})
    argv: list[str] = []
    for key, value in flags.items():
        argv += [f"--{key}", value]
    return argv


class TestTheBotRule:
    """
    The dispatcher's bot, named by its numeric id alone, admitted only on the deploy profile of its first attempt.
    """
    def _run(self, registry, argv, monkeypatch, tmp_path):
        output = tmp_path / "output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        with patch.object(cd, "_load_registry", return_value = registry):
            rc = main(argv)
        return rc, output.read_text(encoding = "utf-8") if output.exists() else ""


    def test_the_bot_is_admitted_on_the_deploy_profile_of_its_first_dispatch(self, bot_registry, monkeypatch, tmp_path):
        rc, output = self._run(bot_registry, _bot_run(), monkeypatch, tmp_path)
        assert rc == 0
        assert "path=bot" in output


    @pytest.mark.parametrize("overrides", [
        {"profile": ""},
        {"profile": "terraform"},
        {"run_attempt": "2"},
        {"event": "schedule"},
        {"event": "push"},
        {"workflow_ref": "NeedlessAlloy/kriegerdataforge/.github/workflows/other.yml@refs/heads/main"},
        {"workflow_ref": "NeedlessAlloy/kriegerdataforge/.github/workflows/cd.yml@refs/heads/feature"},
        {"workflow_ref": "NeedlessAlloy/kriegerdataforge/.github/workflows/cd.yml@refs/tags/v1.0.0"},
        {"environment": "dev"},
        {"repo": "NeedlessAlloy/fitness-app-frontend"},
        {"actor": "NeedlessAlloy"},
    ], ids = [
        "no-profile", "another-profile", "a-rerun", "a-schedule", "a-push", "another-caller", "another-branch",
        "a-tag", "an-environment-not-granted", "a-repo-not-granted", "the-owner-reran-it",
    ])
    def test_the_bot_off_its_profile_is_refused_by_both_rules(self, bot_registry, overrides, monkeypatch, tmp_path):
        # a run the bot started never falls back to the logins, so off its profile it is refused whole
        rc, output = self._run(bot_registry, _bot_run(**overrides), monkeypatch, tmp_path)
        assert rc == 1
        assert "path=" not in output


    def test_an_id_no_bot_entry_names_takes_the_human_rule_by_login(self, bot_registry, monkeypatch, tmp_path):
        rc, output = self._run(bot_registry, _bot_run(actor_id = "100000002"), monkeypatch, tmp_path)
        assert rc == 1
        assert "path=" not in output


    def test_the_owners_run_takes_the_human_rule_and_says_so(self, bot_registry, monkeypatch, tmp_path):
        argv = _bot_run(actor = "NeedlessAlloy", started_by = "NeedlessAlloy", actor_id = "200000002", profile = "")
        rc, output = self._run(bot_registry, argv, monkeypatch, tmp_path)
        assert rc == 0
        assert "path=human" in output


    def test_the_owners_rerun_is_the_human_rule_as_before(self, bot_registry, monkeypatch, tmp_path):
        owner = "NeedlessAlloy"
        argv  = _bot_run(actor = owner, started_by = owner, actor_id = "200000002", run_attempt = "3")
        rc, output = self._run(bot_registry, argv, monkeypatch, tmp_path)
        assert rc == 0
        assert "path=human" in output


    def test_the_bots_login_alone_never_admits_it(self, bot_registry, monkeypatch, tmp_path):
        # a login is not an identity the registry trusts for a bot, so a run whose id is no bot's is the human rule's
        bot_registry["deployers"]["NeedlessAlloy/kriegerdataforge"]["prod"].append(BOT_LOGIN)
        rc, output = self._run(bot_registry, _bot_run(actor_id = "200000002"), monkeypatch, tmp_path)
        assert rc == 0
        assert "path=human" in output


    def test_the_actor_id_falls_back_to_the_runners_own(self, bot_registry, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_ACTOR_ID", BOT_ID)
        argv  = _bot_run()
        index = argv.index("--actor-id")
        del argv[index:index + 2]
        rc, output = self._run(bot_registry, argv, monkeypatch, tmp_path)
        assert rc == 0
        assert "path=bot" in output


    def test_a_registry_with_no_automation_section_admits_no_bot(self, sample_registry, monkeypatch, tmp_path):
        rc, _ = self._run(sample_registry, _bot_run(), monkeypatch, tmp_path)
        assert rc == 1


    def test_the_real_registry_names_its_bots_by_number_with_exact_callers(self):
        bots = _load_registry()["automation"]["bots"]
        assert isinstance(bots, dict)
        for bot_id, grants in bots.items():
            assert bot_id.isdigit(), f"a bot is named by its numeric user id, not {bot_id!r}"
            for repo, environments in grants.items():
                assert "/" in repo
                for environment, caller in environments.items():
                    assert environment in ("dev", "prod")
                    assert caller["workflow"].startswith(".github/workflows/")
                    assert caller["ref"] == "refs/heads/main"


    def test_the_real_registry_comment_names_the_bots_id_and_its_first_attempt(self):
        comment = _load_registry()["automation"]["_comment"]
        assert "GITHUB_ACTOR_ID" in comment and "first attempt" in comment


# ── module entry guard ──────────────────────────────────────────────────────────
class TestEntryGuard:
    def test_main_callable_with_argv(self, sample_registry, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["check_deployer.py"])
        monkeypatch.setenv("DEPLOY_REPO", "NeedlessAlloy/kriegerdataforge")
        monkeypatch.setenv("DEPLOY_ACTOR", "NeedlessAlloy")
        monkeypatch.setenv("DEPLOY_ENVIRONMENT", "prod")
        with patch.object(cd, "_load_registry", return_value = sample_registry):
            assert main() == 0
