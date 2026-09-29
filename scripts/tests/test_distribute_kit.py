"""
Unit tests for scripts/distribute_kit.py.

All network I/O (requests) is mocked; the drift/diff logic is tested directly.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import distribute_kit as dk
import pytest

# the real check, kept before the autouse fixture below replaces it in every test
REAL_COMPUTE_GAPS = dk.compute_gaps


# ── Fixtures ────────────────────────────────────────────────────────────────────
@pytest.fixture
def registry():
    return {
        "files": ["skills.md", "WORKFLOW.md", "docs/agent/DEFINITION_OF_DONE.md"],
        "repos": [
            {"repo": "Needless2Say/repo-a", "branch": "main"},
            {"repo": "Needless2Say/repo-b", "branch": "main"},
        ],
    }


@pytest.fixture(autouse = True)
def no_open_pr():
    """
    No sync pull request is open unless a test says so, and no test reaches GitHub for it.
    """
    with patch.object(dk, "_open_pr_url", return_value = None) as open_pr:
        yield open_pr


@pytest.fixture(autouse = True)
def no_gaps():
    """
    Every repo's own files meet the standard unless a test says so, and no check test reaches GitHub for them.
    """
    with patch.object(dk, "compute_gaps", return_value = []) as gaps:
        yield gaps


# ── Pure helpers ─────────────────────────────────────────────────────────────────
def test_normalize_ignores_crlf():
    assert dk._normalize("a\r\nb\r\n") == "a\nb\n"
    assert dk._normalize("a\r\nb") == dk._normalize("a\nb")


def test_select_files_all(registry):
    assert dk._select_files(registry, None) == registry["files"]


def test_select_files_only_filters(registry):
    assert dk._select_files(registry, "skills.md") == ["skills.md"]


def test_select_files_only_no_match_exits(registry):
    with pytest.raises(SystemExit):
        dk._select_files(registry, "does-not-exist.md")


def test_select_repos_all(registry):
    assert dk._select_repos(registry, None) == registry["repos"]
    assert dk._select_repos(registry, "") == registry["repos"]
    assert dk._select_repos(registry, "  ,  ") == registry["repos"]


def test_select_repos_filters_subset(registry):
    sel = dk._select_repos(registry, "repo-a")
    assert [e["repo"] for e in sel] == ["Needless2Say/repo-a"]


def test_select_repos_multiple_tokens(registry):
    sel = dk._select_repos(registry, "repo-a, repo-b")
    assert [e["repo"] for e in sel] == ["Needless2Say/repo-a", "Needless2Say/repo-b"]


def test_select_repos_is_exact_not_substring(registry):
    # "repo" is a substring of both but an exact match of neither -> no match (exits).
    with pytest.raises(SystemExit):
        dk._select_repos(registry, "repo")
    # a partial like "repo-" must not fan out to repo-a/repo-b either.
    with pytest.raises(SystemExit):
        dk._select_repos(registry, "repo-")


def test_select_repos_full_owner_repo(registry):
    sel = dk._select_repos(registry, "Needless2Say/repo-b")
    assert [e["repo"] for e in sel] == ["Needless2Say/repo-b"]


def test_select_repos_case_insensitive(registry):
    assert len(dk._select_repos(registry, "REPO-A")) == 1


def test_select_repos_no_match_exits(registry):
    with pytest.raises(SystemExit):
        dk._select_repos(registry, "nonexistent")


# ── Contents API helper ──────────────────────────────────────────────────────────
def test_get_remote_file_404_returns_none():
    resp = MagicMock(status_code = 404)
    with patch.object(dk._SESSION, "get", return_value = resp):
        assert dk._get_remote_file("tok", "o/r", "main", "a.md") == (None, None)


def test_get_remote_file_decodes_content():
    resp                   = MagicMock(status_code = 200)
    resp.json.return_value = {"content": base64.b64encode(b"hello").decode(), "sha": "abc"}
    resp.raise_for_status  = MagicMock()
    with patch.object(dk._SESSION, "get", return_value = resp):
        content, sha = dk._get_remote_file("tok", "o/r", "main", "a.md")
    assert content == "hello"
    assert sha == "abc"


# ── HTTP retry hardening ─────────────────────────────────────────────────────────
def test_session_retries_transient_failures():
    """
    Regression guard: the shared session must retry transient GitHub failures.

    A fan-out check/distribute across every kit repo routinely hits a 502/503/429 or a
    DNS/connection blip; without retries a single hiccup aborts a whole repo (the
    2026-07 distribute check errored on two 502s + one DNS failure). The retry must
    stay wired, cover the transient status codes + connection errors, and NOT retry
    POST on a server response (no duplicate branches/PRs).
    """
    retry = dk._SESSION.get_adapter("https://api.github.com").max_retries
    assert retry.total and retry.total >= 3
    assert retry.connect and retry.connect >= 1  # DNS / connection blips
    for code in (429, 500, 502, 503, 504):
        assert code in retry.status_forcelist
    assert retry.backoff_factor > 0  # exponential backoff, not a hot loop
    # Idempotent methods retry; POST (branch/PR create) is excluded from status retry.
    assert "GET" in retry.allowed_methods
    assert "PUT" in retry.allowed_methods
    assert "POST" not in retry.allowed_methods
    # 404 (missing = drift) and 422 (ref exists, handled) must NOT be retried.
    assert 404 not in retry.status_forcelist
    assert 422 not in retry.status_forcelist


# ── Drift detection ──────────────────────────────────────────────────────────────
def test_compute_drift_detects_diff_and_missing():
    files = ["a.md", "b.md", "c.md"]


    def fake_remote(_token, _repo, _branch, path):
        if path == "a.md":
            return ("local-a.md", "sha")   # in sync
        if path == "b.md":
            return ("DIFFERENT", "sha")     # content drift
        return (None, None)                 # missing -> drift


    with (
        patch.object(dk, "_read_local", side_effect = lambda rel: f"local-{rel}"),
        patch.object(dk, "_get_remote_file", side_effect = fake_remote),
    ):
        drift = dk.compute_drift("tok", "o/r", "main", files)
    assert drift == ["b.md", "c.md"]


def test_compute_drift_normalizes_line_endings():
    with (
        patch.object(dk, "_read_local", return_value = "x\ny\n"),
        patch.object(dk, "_get_remote_file", return_value = ("x\r\ny\r\n", "sha")),
    ):
        assert dk.compute_drift("tok", "o/r", "main", ["a.md"]) == []


# ── check mode ───────────────────────────────────────────────────────────────────
def test_cmd_check_returns_0_when_in_sync(registry):
    with patch.object(dk, "compute_drift", return_value = []):
        assert dk.cmd_check(registry, "tok", None) == 0


def test_cmd_check_returns_1_on_drift(registry):
    with patch.object(dk, "compute_drift", side_effect = [["skills.md"], []]):
        assert dk.cmd_check(registry, "tok", None) == 1


def test_cmd_check_returns_1_on_error(registry):
    with patch.object(dk, "compute_drift", side_effect = RuntimeError("boom")):
        assert dk.cmd_check(registry, "tok", None) == 1


def test_cmd_check_respects_repos_filter(registry):
    """
    With --repos, only the selected repos are checked.
    """
    checked: list[str] = []


    def fake_drift(_token, repo, _branch, _files):
        checked.append(repo)
        return []


    with patch.object(dk, "compute_drift", side_effect = fake_drift):
        rc = dk.cmd_check(registry, "tok", None, "repo-b")
    assert rc == 0
    assert checked == ["Needless2Say/repo-b"]


# ── distribute mode ──────────────────────────────────────────────────────────────
def test_cmd_distribute_opens_pr_for_drifted_repo():
    reg = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    with (
        patch.object(dk, "compute_drift", return_value = ["skills.md"]),
        patch.object(dk, "_read_local", return_value = "content"),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch") as create_branch,
        patch.object(dk, "_get_remote_file", return_value = ("old", "blobsha")),
        patch.object(dk, "_put_file") as put_file,
        patch.object(dk, "_create_pr", return_value = "https://pr") as create_pr,
    ):
        rc = dk.cmd_distribute(reg, "tok", None)
    assert rc == 0
    create_branch.assert_called_once()
    put_file.assert_called_once()
    create_pr.assert_called_once()


def test_cmd_distribute_skips_in_sync_repo():
    reg = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    with (
        patch.object(dk, "compute_drift", return_value = []),
        patch.object(dk, "_create_pr") as create_pr,
    ):
        rc = dk.cmd_distribute(reg, "tok", None)
    assert rc == 0
    create_pr.assert_not_called()


def test_cmd_distribute_reports_failure_rc():
    reg = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    with (
        patch.object(dk, "compute_drift", return_value = ["skills.md"]),
        patch.object(dk, "_read_local", return_value = "content"),
        patch.object(dk, "_get_branch_sha", side_effect = RuntimeError("api down")),
    ):
        rc = dk.cmd_distribute(reg, "tok", None)
    assert rc == 1


def test_cmd_distribute_rerun_updates_the_open_pr_and_opens_no_second_one(no_open_pr, capsys):
    """
    A second run over the same sync branch brings the branch up to date and does not ask GitHub for the PR again.
    """
    reg                     = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    no_open_pr.return_value = "https://github.com/Needless2Say/repo-a/pull/7"
    with (
        patch.object(dk, "compute_drift", return_value = ["skills.md"]),
        patch.object(dk, "_read_local", return_value = "new"),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_get_remote_file", return_value = ("old", "blobsha")),
        patch.object(dk, "_put_file") as put_file,
        patch.object(dk, "_create_pr") as create_pr,
    ):
        rc = dk.cmd_distribute(reg, "tok", None)
    assert rc == 0
    put_file.assert_called_once()
    create_pr.assert_not_called()
    out = capsys.readouterr().out
    assert "PR already open — https://github.com/Needless2Say/repo-a/pull/7" in out
    assert "1 PR(s) were already open" in out


def test_cmd_distribute_skips_a_file_the_sync_branch_already_carries():
    """
    A file whose sync branch copy already matches the kit is not written again, so a re-run adds no commits.
    """
    reg = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}
    with (
        patch.object(dk, "compute_drift", return_value = ["skills.md"]),
        patch.object(dk, "_read_local", return_value = "same\r\n"),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_get_remote_file", return_value = ("same\n", "blobsha")),
        patch.object(dk, "_put_file") as put_file,
        patch.object(dk, "_create_pr", return_value = "https://pr") as create_pr,
    ):
        rc = dk.cmd_distribute(reg, "tok", None)
    assert rc == 0
    put_file.assert_not_called()
    create_pr.assert_called_once()


# ── version-marker consistency ───────────────────────────────────────────────────
def test_assert_version_consistency_passes_when_match():
    marker                        = MagicMock()
    marker.is_file.return_value   = True
    marker.read_text.return_value = "v1.2.0\n"
    with (
        patch.object(dk, "VENDORED_VERSION_FILE", marker),
        patch.object(dk, "_kit_version", return_value = "v1.2.0"),
    ):
        dk._assert_version_consistency()  # no SystemExit


def test_assert_version_consistency_exits_on_mismatch():
    marker                        = MagicMock()
    marker.is_file.return_value   = True
    marker.read_text.return_value = "v1.1.0"
    with (
        patch.object(dk, "VENDORED_VERSION_FILE", marker),
        patch.object(dk, "_kit_version", return_value = "v1.2.0"),
        pytest.raises(SystemExit),
    ):
        dk._assert_version_consistency()


def test_assert_version_consistency_noop_when_marker_absent():
    marker                      = MagicMock()
    marker.is_file.return_value = False
    with (
        patch.object(dk, "VENDORED_VERSION_FILE", marker),
        patch.object(dk, "_kit_version", return_value = "v1.2.0"),
    ):
        dk._assert_version_consistency()  # returns early, no error


# ---------------------------------------------------------------------------
# REAL-FILE consistency guards (2026-07-14 review, finding C1/C10). The mocked
# tests above prove the check LOGIC; these prove the ACTUAL on-disk markers +
# registry are self-consistent — the gap that let kit/KIT_VERSION lag the
# vendored marker slip through a kit-version bump PR.
# ---------------------------------------------------------------------------
def test_real_kit_version_markers_match():
    """
    kit/KIT_VERSION (canonical) == kit/common/docs/agent/KIT_VERSION (vendored)
    == the root docs/agent/KIT_VERSION hand-copy. A bump must touch all three.
    """
    canonical = dk.KIT_VERSION_FILE.read_text(encoding = "utf-8").strip()
    vendored  = dk.VENDORED_VERSION_FILE.read_text(encoding = "utf-8").strip()
    root_copy = (dk.REPO_ROOT / "docs" / "agent" / "KIT_VERSION").read_text(encoding = "utf-8").strip()
    assert canonical == vendored, (
        f"kit/KIT_VERSION ({canonical}) != vendored marker ({vendored}) — "
        "distribute_kit._assert_version_consistency() would hard-exit; bump both."
    )
    assert canonical == root_copy, (f"kit/KIT_VERSION ({canonical}) != root docs/agent/KIT_VERSION ({root_copy}).")


def test_cicd_keeps_its_own_kit_copies_current():
    """
    cicd is the source and never a sync target, so its root copies of the kit files change in the same pull request as
    kit/common. Every agent working in cicd reads the root copies, and they had fallen versions behind by 2026-09-29.
    """
    def text(path):
        return path.read_bytes().replace(b"\r\n", b"\n")


    drifted = [name for name in dk._load_registry()["files"] if text(dk.REPO_ROOT / name) != text(dk.KIT_DIR / name)]
    assert not drifted, f"cicd's own copies differ from kit/common, copy these over: {drifted}"


def test_real_kit_registry_files_all_exist_under_kit_common():
    """
    Every kit_registry.json files[] entry must resolve under kit/common/ — a
    stale/typo'd path would silently drop a file from the synced set.
    """
    registry = dk._load_registry()
    files: list[str] = registry.get("files", [])
    assert files, "kit_registry.json files[] is empty"
    missing = [f for f in files if not (dk.KIT_DIR / f).is_file()]
    assert not missing, f"kit_registry files[] paths absent under kit/common/: {missing}"


# ── gaps in a repo's own files ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("gitignore", "ignored"),
    [
        (".env*\n!.env.example\n", True),
        ("**/.env.*\n", True),
        ("/.env.kdf\n", True),
        ("# .env*\n.env.local\n.env.github\n", False),
        (".env*\n!.env.kdf\n", False),
        (".env*\n!.env.*.example\n", True),
        (".env/\n", False),
    ],
)
def test_ignores_reads_a_root_gitignore_as_git_does(gitignore: str, ignored: bool):
    """
    The last matching line wins, a negation re-includes, a comment and a directory rule never match a file.
    """
    assert dk._ignores(gitignore, ".env.kdf") is ignored


def test_a_repo_that_meets_the_standard_has_no_gaps():
    files = {
        "AGENTS.md": "Know your role, [`docs/agent/AGENT_ROLES.md`](docs/agent/AGENT_ROLES.md)",
        ".env.kdf.example": "GH_PACKAGES_PAT=\n",
        ".gitignore": ".env*\n!.env.local.example\n!.env.kdf.example\n",
    }
    with patch.object(dk, "_get_remote_file", side_effect = lambda _t, _r, _b, path: (files.get(path), "sha")):
        assert REAL_COMPUTE_GAPS("tok", "o/r", "main") == []


def test_a_repo_without_the_pointer_the_example_or_the_ignore_reports_each_gap():
    files = {"AGENTS.md": "# a guide without the pointer\n", ".gitignore": ".env.local\n"}
    with patch.object(dk, "_get_remote_file", side_effect = lambda _t, _r, _b, path: (files.get(path), "sha")):
        gaps = REAL_COMPUTE_GAPS("tok", "o/r", "main")
    assert len(gaps) == 3
    assert any("AGENT_ROLES.md" in gap for gap in gaps)
    assert any(".env.kdf.example" in gap for gap in gaps)
    assert any("does not ignore .env.kdf" in gap for gap in gaps)


def test_cmd_check_returns_1_on_a_gap_and_says_distribute_opens_none(registry, no_gaps, capsys):
    no_gaps.side_effect = [["no .env.kdf.example, the env standard of ADR D-030"], []]
    with patch.object(dk, "compute_drift", return_value = []):
        assert dk.cmd_check(registry, "tok", None) == 1
    out = capsys.readouterr().out
    assert "GAPS (1)" in out
    assert "distribute opens none" in out
