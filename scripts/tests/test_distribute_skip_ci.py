"""
Tests for cicd D-047, a Distribute that runs no CI when every change is already tested.

A sync pull request ran the repo's whole CI, 10 to 24 billed minutes in each of 17 private repos per Distribute. Now a
sync whose every changed path is on an exact allowlist, the kit's copies, the AGENTS.md pointer, the Dependabot limits
and the version scripts, carries `[skip ci]` in every commit, so GitHub starts no pull_request workflow. Any other
change, a patch of a repo's own Makefile or the mutation engine, leaves the marker off and CI runs. The kit and the
scripts can also travel in one pull request per repo, and the version check lets that combined branch through.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import common.repo_sync as rs
import distribute_all as da
import distribute_kit as dk
import distribute_scripts as ds
import pytest
from common import check_version as cv

SCRIPTS          = Path(__file__).resolve().parents[1]
KIT_REGISTRY     = json.loads((SCRIPTS / "kit_registry.json").read_text(encoding = "utf-8"))
SCRIPTS_REGISTRY = json.loads((SCRIPTS / "scripts_registry.json").read_text(encoding = "utf-8"))
HUB              = {"repo": "Needless2Say/kriegerdataforge", "branch": "main"}
TEMPLATE         = {"repo": "Needless2Say/kriegerdataforge-template-nextjs", "branch": "main"}
VERSION_SCRIPTS  = {
    "scripts/kdf_scripts/check_version.py",
    "scripts/kdf_scripts/bump_version.py",
    "scripts/kdf_scripts/version_targets.py",
}
NOT_ELIGIBLE     = [
    "scripts/kdf_scripts/mutation_runner.py",   # tested in cicd, never against a repo's own tables
    "Makefile",                                  # the scripts sync's patch of the repo's own file
    "requirements-dev.in",
    "kdf-fmt.toml",
    "ruff.toml",
    "pyproject.toml",
    "scripts/check_version.py",                  # a delete of a superseded copy
    "docs/README.md",                            # a directory is never on the list, only exact paths
    "docs/agent/NOT_A_KIT_FILE.md",
    ".github/workflows/ci.yml",
]
ENGINE           = {"src": "scripts/common/mutation_runner.py", "dest": "scripts/kdf_scripts/mutation_runner.py"}
CHECK = {"src": "scripts/common/check_version.py", "dest": "scripts/kdf_scripts/check_version.py", "pretested": True}


def _always(_changed, _pretested) -> bool:
    """
    The control, an eligibility rule that says yes to anything.
    """
    return True

# ======================================================================================================================
# The allowlists are exact paths
# ======================================================================================================================

def test_the_kit_allowlist_is_the_registry_files_and_the_two_patched_pages():
    allow = dk.pretested_paths(KIT_REGISTRY["files"])
    assert allow == {*KIT_REGISTRY["files"], "AGENTS.md", ".github/dependabot.yml"}


def test_the_scripts_allowlist_is_the_three_version_scripts_and_never_the_engine():
    assert ds.pretested_dests(SCRIPTS_REGISTRY, HUB) == VERSION_SCRIPTS
    assert ds.pretested_dests(SCRIPTS_REGISTRY, TEMPLATE) == VERSION_SCRIPTS


def test_a_file_entry_without_the_flag_never_skips():
    registry = {"files": [{"src": "scripts/common/new.py", "dest": "scripts/kdf_scripts/new.py"}]}
    assert ds.pretested_dests(registry, HUB) == set()


@pytest.mark.parametrize("path", sorted({*KIT_REGISTRY["files"], "AGENTS.md", ".github/dependabot.yml"}))
def test_each_kit_path_is_eligible_alone(path):
    assert rs.skip_ci_eligible([path], dk.pretested_paths(KIT_REGISTRY["files"])) is True


@pytest.mark.parametrize("path", sorted(VERSION_SCRIPTS))
def test_each_version_script_is_eligible_alone(path):
    assert rs.skip_ci_eligible([path], ds.pretested_dests(SCRIPTS_REGISTRY, HUB)) is True


@pytest.mark.parametrize("path", NOT_ELIGIBLE)
def test_a_change_off_the_list_lets_ci_run_even_beside_eligible_ones(path):
    allow = dk.pretested_paths(KIT_REGISTRY["files"]) | ds.pretested_dests(SCRIPTS_REGISTRY, HUB)
    assert rs.skip_ci_eligible(["skills.md", "scripts/kdf_scripts/check_version.py", path], allow) is False
    assert _always(["skills.md", path], allow) is True, "the control says yes, so the line above depends on the rule"


def test_an_empty_change_set_never_skips():
    assert rs.skip_ci_eligible([], {"skills.md"}) is False


def test_the_marker_is_what_github_reads():
    assert rs.SKIP_CI_MARKER == "[skip ci]"
    assert rs.with_skip_ci("chore: sync", True) == "chore: sync [skip ci]"
    assert rs.with_skip_ci("chore: sync", False) == "chore: sync"

# ======================================================================================================================
# The engine marks every commit of an eligible sync, so the PR's HEAD carries it
# ======================================================================================================================

def _file_item(dest: str) -> rs.SyncItem:
    return rs.SyncItem(dest = dest, desired = lambda _remote, d = dest: f"new {d}")


def _engine_run(items, pretested, eligible = None):
    patches = [
        patch.object(rs, "_get_remote_file", return_value = (None, None)),
        patch.object(rs, "_get_branch_sha", return_value = "base"),
        patch.object(rs, "_create_branch"),
        patch.object(rs, "_open_pr_url", return_value = None),
        patch.object(rs, "_put_file"),
        patch.object(rs, "_create_pr", return_value = "https://pr"),
    ]
    if eligible is not None:
        patches.append(patch.object(rs, "skip_ci_eligible", side_effect = eligible))
    started = [p.start() for p in patches]
    try:
        rc = rs.run_distribute(
            "tok",
            [{"repo": "o/repo-a", "branch": "main"}],
            items,
            sync_branch = "chore/scripts-sync-9",
            pr_title = "sync",
            pr_body_fn = lambda drift: "body",
            commit_msg_fn = lambda item: f"sync {item.dest}",
            pretested = pretested,
        )
    finally:
        for p in patches:
            p.stop()
    put_file, create_pr = started[4], started[5]
    messages = [call.args[6] for call in put_file.call_args_list]
    return rc, messages, create_pr.call_args.args[5]


def test_an_eligible_sync_marks_every_commit_and_says_so_in_the_body():
    rc, messages, body = _engine_run(
        [_file_item("scripts/kdf_scripts/check_version.py"), _file_item("scripts/kdf_scripts/bump_version.py")],
        VERSION_SCRIPTS,
    )
    assert rc == 0
    assert len(messages) == 2 and all(message.endswith(" [skip ci]") for message in messages)
    assert messages[-1].endswith(" [skip ci]"), "the last commit is the PR's HEAD, the one GitHub reads"
    assert "**CI skipped**" in body


def test_an_ineligible_sync_marks_no_commit_and_names_what_ci_runs_for():
    rc, messages, body = _engine_run(
        [_file_item("scripts/kdf_scripts/check_version.py"), _file_item("Makefile")],
        VERSION_SCRIPTS,
    )
    assert rc == 0
    assert messages and not any("[skip ci]" in message for message in messages)
    assert "**CI runs**" in body and "Makefile" in body


def test_the_control_an_always_yes_rule_marks_the_ineligible_sync():
    """
    The same ineligible run under a rule that says yes to anything carries the marker, so the test above fails
    without the rule.
    """
    _rc, messages, _body = _engine_run(
        [_file_item("scripts/kdf_scripts/check_version.py"), _file_item("Makefile")],
        VERSION_SCRIPTS,
        eligible = _always,
    )
    assert all(message.endswith(" [skip ci]") for message in messages)


def test_without_an_allowlist_the_engine_marks_nothing_and_adds_no_note():
    _rc, messages, body = _engine_run([_file_item("scripts/kdf_scripts/check_version.py")], None)
    assert not any("[skip ci]" in message for message in messages)
    assert body == "body"

# ======================================================================================================================
# The kit sync is always eligible, its every change is a kit copy or one of the two patched pages
# ======================================================================================================================

def test_the_kit_sync_marks_every_commit(monkeypatch):
    registry = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    pages    = {"AGENTS.md": "# repo-a\n\n> [`docs/agent/AGENT_ROLES.md`](docs/agent/AGENT_ROLES.md)\n"}
    with (
        patch.object(dk, "compute_drift", return_value = ["skills.md"]),
        patch.object(dk, "agents_line_missing", return_value = True),
        patch.object(dk, "dependabot_due", return_value = False),
        patch.object(dk, "_get_remote_file", side_effect = lambda _t, _r, _b, path: (pages.get(path), "sha")),
        patch.object(dk, "_read_local", return_value = "kit text"),
        patch.object(dk, "_get_branch_sha", return_value = "base"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_open_pr_url", return_value = None),
        patch.object(dk, "_put_file") as put_file,
        patch.object(dk, "_create_pr", return_value = "https://pr") as create_pr,
    ):
        assert dk.cmd_distribute(registry, "tok", None) == 0
    messages = [call.args[6] for call in put_file.call_args_list]
    assert len(messages) == 2 and all(message.endswith(" [skip ci]") for message in messages)
    assert "**CI skipped**" in create_pr.call_args.args[5]

# ======================================================================================================================
# The kit and the scripts in one pull request per repo
# ======================================================================================================================

def test_merged_entries_keep_one_entry_per_repo_and_flag_each_registry():
    kit     = {"repos": [{"repo": "o/a", "branch": "main"}, {"repo": "o/kit-only", "branch": "main"}]}
    scripts = {"repos": [{"repo": "o/a", "branch": "main", "ruff_config": "ruff.toml"}, {"repo": "o/scripts-only"}]}
    entries = {entry["repo"]: entry for entry in da.merged_entries(kit, scripts)}
    assert set(entries) == {"o/a", "o/kit-only", "o/scripts-only"}
    assert entries["o/a"]["_kit"] and entries["o/a"]["_scripts"] and entries["o/a"]["ruff_config"] == "ruff.toml"
    assert entries["o/kit-only"].get("_scripts") is None and entries["o/scripts-only"].get("_kit") is None


def test_the_real_registries_name_the_same_repos():
    kit     = {entry["repo"] for entry in KIT_REGISTRY["repos"]}
    scripts = {entry["repo"] for entry in SCRIPTS_REGISTRY["repos"]}
    assert kit == scripts


def _combined_run(monkeypatch, scripts_files, eligible = None):
    """
    Run distribute_all.py's distribute for one repo whose kit file and scripts are all missing, and return the
    commit messages, the PR calls and the exit code.
    """
    kit_registry     = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    scripts_registry = {"files": scripts_files, "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    monkeypatch.setattr(sys, "argv", ["distribute_all.py", "distribute"])
    monkeypatch.setenv("GH_TOKEN", "tok")
    patches = [
        patch.object(dk, "_load_registry", return_value = kit_registry),
        patch.object(ds, "_load_registry", return_value = scripts_registry),
        patch.object(dk, "_assert_version_consistency"),
        patch.object(dk, "_kit_version", return_value = "v9.0.0"),
        patch.object(ds, "_scripts_version", return_value = "9.9.9"),
        patch.object(dk, "agents_line_missing", return_value = False),
        patch.object(dk, "dependabot_due", return_value = False),
        patch.object(rs, "_get_remote_file", return_value = (None, None)),
        patch.object(rs, "_get_branch_sha", return_value = "base"),
        patch.object(rs, "_create_branch"),
        patch.object(rs, "_open_pr_url", return_value = None),
        patch.object(rs, "_put_file"),
        patch.object(rs, "_create_pr", return_value = "https://pr"),
    ]
    if eligible is not None:
        patches.append(patch.object(rs, "skip_ci_eligible", side_effect = eligible))
    started = [p.start() for p in patches]
    try:
        with pytest.raises(SystemExit) as exited:
            da.main()
    finally:
        for p in patches:
            p.stop()
    put_file, create_pr = started[11], started[12]
    return exited.value.code, put_file, create_pr


def test_one_pull_request_carries_the_kit_and_the_scripts_and_skips_ci(monkeypatch):
    code, put_file, create_pr = _combined_run(monkeypatch, [CHECK])
    assert code == 0
    create_pr.assert_called_once()
    assert create_pr.call_args.args[2] == "chore/ecosystem-sync-kit-v9.0.0-scripts-9.9.9"
    assert {call.args[3] for call in put_file.call_args_list} == {"skills.md", "scripts/kdf_scripts/check_version.py"}
    assert all(call.args[6].endswith(" [skip ci]") for call in put_file.call_args_list)
    assert "**CI skipped**" in create_pr.call_args.args[5]


def test_the_combined_pull_request_runs_ci_when_it_carries_the_engine(monkeypatch):
    code, put_file, create_pr = _combined_run(monkeypatch, [CHECK, ENGINE])
    assert code == 0
    create_pr.assert_called_once()
    assert not any("[skip ci]" in call.args[6] for call in put_file.call_args_list)
    assert "scripts/kdf_scripts/mutation_runner.py" in create_pr.call_args.args[5]


def test_the_control_an_always_yes_rule_skips_the_engine_too(monkeypatch):
    _code, put_file, _create_pr = _combined_run(monkeypatch, [CHECK, ENGINE], eligible = _always)
    assert all(call.args[6].endswith(" [skip ci]") for call in put_file.call_args_list)

# ======================================================================================================================
# The version check lets the combined branch carry what either sync may, and no other branch
# ======================================================================================================================

@pytest.mark.parametrize(("head", "changed", "exempt"), [
    ("chore/ecosystem-sync-kit-v1.15.0-scripts-1.5.2", ["skills.md", "AGENTS.md", "Makefile"], True),
    ("chore/ecosystem-sync-kit-v1.15.0-scripts-1.5.2", [".github/dependabot.yml", "requirements-dev.in"], True),
    ("chore/kit-sync-v1.15.0", ["skills.md", ".github/dependabot.yml"], True),
    ("chore/kit-sync-v1.15.0", ["skills.md", "Makefile"], False),
    ("chore/scripts-sync-1.5.2", [".github/dependabot.yml"], False),
    ("feature/dependabot", [".github/dependabot.yml"], False),
    ("chore/ecosystem-sync-kit-v1.15.0-scripts-1.5.2", ["src/app.py"], False),
], ids = ["combined-kit-and-make", "combined-dependabot-reqs", "kit-dependabot", "kit-make", "scripts-dependabot",
          "feature", "combined-code"])
def test_the_version_check_lets_each_sync_branch_carry_its_own_files(tmp_path: Path, head, changed, exempt):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": head}),
        patch.object(cv, "_changed_files", return_value = changed),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is exempt
