"""
Tests for the ecosystem context line the kit sync writes into a repo's own AGENTS.md (cicd D-046).

The line points every agent at the owner's private context repo beside the repo. distribute_kit.py inserts it into
the AGENTS.md of the sync pull request it already opens, only when the page lacks it, and never touches another line.
The version check lets a kit sync branch carry AGENTS.md, so those pull requests do not fail its strict +1 gate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import distribute_kit as dk
import pytest
from common import check_version as cv

LINE = "".join(line + "\n" for line in dk.ECOSYSTEM_LINES)

POINTER_PAGE = "\n".join([
    "# repo-a, Agent Guide",
    "",
    "> **This is the canonical agent guide for this repo.** Read this first.",
    "",
    "> **Know your role before you act, whatever model or tool you are.**",
    "> [`docs/agent/AGENT_ROLES.md`](docs/agent/AGENT_ROLES.md) says what each role may do.",
    "",
    "## Vision & purpose",
    "",
    "Text that mentions a > quote and `docs/agent/AGENT_ROLES.md` again.",
    "",
])

ONE_QUOTE_PAGE = "\n".join([
    "# repo-b, Agent Guide",
    "",
    "> **This is the canonical agent guide for this repo.**",
    ">",
    "> **Know your role.** [`docs/agent/AGENT_ROLES.md`](docs/agent/AGENT_ROLES.md) says what each role may do.",
    "## Vision",
    "",
])

NO_POINTER_PAGE = "# repo-c, Agent Guide\n\nAn older page without the role pointer.\n\n## Commands\n"

NO_HEADING_PAGE = "An agent guide with no heading at all.\n"


def _removed(text: str) -> str:
    """
    The page with the inserted paragraph and its blank lines taken out again, to show nothing else changed.
    """
    lf = text.replace("\r\n", "\n")
    return lf.replace("\n" + LINE + "\n", "\n", 1).replace("\n" + LINE, "\n", 1).replace(LINE + "\n", "", 1)

# ======================================================================================================================
# Where the line goes, and what stays
# ======================================================================================================================

def test_the_line_goes_right_after_the_role_pointer_blockquote():
    out = dk.insert_ecosystem_line(POINTER_PAGE)
    assert dk.ECOSYSTEM_PATH in out
    lines = out.split("\n")
    first = lines.index(dk.ECOSYSTEM_LINES[0])
    assert lines[first - 1] == ""
    assert lines[first - 2].startswith("> [`docs/agent/AGENT_ROLES.md`]")
    assert lines[first + len(dk.ECOSYSTEM_LINES)] == ""
    assert lines[first + len(dk.ECOSYSTEM_LINES) + 1] == "## Vision & purpose"
    assert _removed(out) == POINTER_PAGE


def test_a_pointer_quote_followed_by_a_heading_gets_a_blank_line_on_both_sides():
    out = dk.insert_ecosystem_line(ONE_QUOTE_PAGE)
    assert out == ONE_QUOTE_PAGE.replace("may do.\n## Vision", "may do.\n\n" + LINE + "\n## Vision")


def test_a_page_without_the_role_pointer_gets_the_line_after_its_first_heading():
    out = dk.insert_ecosystem_line(NO_POINTER_PAGE)
    assert out.startswith("# repo-c, Agent Guide\n\n" + LINE + "\nAn older page")
    assert _removed(out) == NO_POINTER_PAGE


def test_a_page_with_no_heading_gets_the_line_at_the_top():
    out = dk.insert_ecosystem_line(NO_HEADING_PAGE)
    assert out == LINE + "\n" + NO_HEADING_PAGE


def test_a_page_that_has_the_line_comes_back_unchanged():
    page = POINTER_PAGE.replace("## Vision", "See `../kriegerdataforge-context/AGENTS.md` too.\n\n## Vision")
    assert dk.insert_ecosystem_line(page) is page


@pytest.mark.parametrize("page", [POINTER_PAGE, ONE_QUOTE_PAGE, NO_POINTER_PAGE, NO_HEADING_PAGE])
def test_a_second_run_changes_nothing(page):
    once = dk.insert_ecosystem_line(page)
    assert dk.insert_ecosystem_line(once) == once


@pytest.mark.parametrize("page", [POINTER_PAGE, ONE_QUOTE_PAGE, NO_POINTER_PAGE, NO_HEADING_PAGE])
def test_a_crlf_page_stays_crlf_and_gets_the_same_insert(page):
    out = dk.insert_ecosystem_line(page.replace("\n", "\r\n"))
    assert dk.ECOSYSTEM_PATH in out
    assert "\n" not in out.replace("\r\n", "")
    assert out == dk.insert_ecosystem_line(page).replace("\n", "\r\n")


def test_a_page_whose_quote_ends_the_file_without_a_newline_gets_one():
    page = "# repo-d\n\n> Know your role, [`docs/agent/AGENT_ROLES.md`](docs/agent/AGENT_ROLES.md)."
    out  = dk.insert_ecosystem_line(page)
    assert out == page + "\n\n" + LINE


def test_the_line_keeps_the_house_width_and_names_a_path_only():
    assert all(len(line) <= 120 for line in dk.ECOSYSTEM_LINES)
    assert dk.ECOSYSTEM_PATH in dk.ECOSYSTEM_LINES[0]


def test_cicds_own_agents_page_carries_the_line_where_the_sync_would_put_it():
    page = (dk.REPO_ROOT / "AGENTS.md").read_bytes().decode("utf-8")
    assert dk.ECOSYSTEM_PATH in page
    lf = page.replace("\r\n", "\n")
    assert dk.insert_ecosystem_line(_removed(lf)) == lf

# ======================================================================================================================
# check and distribute
# ======================================================================================================================

def _reader(pages: dict[str, str | None]):
    return lambda _token, _repo, _branch, path: (pages.get(path), "blobsha")


@pytest.mark.parametrize(
    ("agents", "missing"),
    [(POINTER_PAGE, True), (dk.insert_ecosystem_line(POINTER_PAGE), False), (None, False)],
)
def test_a_missing_line_is_found_and_a_missing_page_is_left_to_the_gap_report(agents, missing):
    with patch.object(dk, "_get_remote_file", side_effect = _reader({"AGENTS.md": agents})):
        assert dk.agents_line_missing("tok", "o/r", "main") is missing


@pytest.fixture
def one_repo():
    return {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}


@pytest.fixture
def gaps_none():
    with patch.object(dk, "compute_gaps", return_value = []):
        yield


def test_check_lists_a_repo_whose_agents_page_lacks_the_line(one_repo, gaps_none, capsys):
    with (
        patch.object(dk, "compute_drift", return_value = []),
        patch.object(dk, "_get_remote_file", side_effect = _reader({"AGENTS.md": POINTER_PAGE})),
    ):
        assert dk.cmd_check(one_repo, "tok", None) == 1
    assert "repo-a: DRIFT (1): AGENTS.md (the ecosystem context line)" in capsys.readouterr().out


def _distribute(one_repo, insert = None):
    """
    Run distribute for one repo whose kit files are in sync and whose AGENTS.md lacks the line, and return the writes.
    """
    patches = [
        patch.object(dk, "compute_drift", return_value = []),
        patch.object(dk, "_get_remote_file", side_effect = _reader({"AGENTS.md": POINTER_PAGE.replace("\n", "\r\n")})),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_open_pr_url", return_value = None),
        patch.object(dk, "_put_file"),
        patch.object(dk, "_create_pr", return_value = "https://pr"),
    ]
    if insert is not None:
        patches.append(patch.object(dk, "insert_ecosystem_line", side_effect = insert))
    started = [p.start() for p in patches]
    try:
        rc = dk.cmd_distribute(one_repo, "tok", None)
    finally:
        for p in patches:
            p.stop()
    put_file, create_pr = started[5], started[6]
    return rc, put_file, create_pr


def test_distribute_writes_the_line_into_the_sync_pull_request(one_repo):
    rc, put_file, create_pr = _distribute(one_repo)
    assert rc == 0
    put_file.assert_called_once()
    path, content = put_file.call_args.args[3], put_file.call_args.args[4]
    assert path == "AGENTS.md"
    assert dk.ECOSYSTEM_PATH in content
    assert "\n" not in content.replace("\r\n", "")
    assert "AGENTS.md (the ecosystem context line)" in create_pr.call_args.args[5]


def test_the_control_a_sync_that_skips_the_insert_writes_no_line(one_repo):
    """
    The same run with the insert replaced by one that returns the page as it is. Nothing is written, so the test
    above fails without the insert.
    """
    rc, put_file, _create_pr = _distribute(one_repo, insert = lambda page: page)
    assert rc == 0
    put_file.assert_not_called()


def test_a_rerun_over_a_branch_that_has_the_line_writes_nothing(one_repo):
    done = dk.insert_ecosystem_line(POINTER_PAGE)
    with (
        patch.object(dk, "compute_drift", return_value = []),
        patch.object(dk, "agents_line_missing", return_value = True),
        patch.object(dk, "_get_remote_file", side_effect = _reader({"AGENTS.md": done})),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_open_pr_url", return_value = "https://github.com/Needless2Say/repo-a/pull/9"),
        patch.object(dk, "_put_file") as put_file,
    ):
        assert dk.cmd_distribute(one_repo, "tok", None) == 0
    put_file.assert_not_called()

# ======================================================================================================================
# The version check lets a kit sync branch carry AGENTS.md, and no other branch
# ======================================================================================================================

@pytest.mark.parametrize(
    ("head", "exempt"),
    [("chore/kit-sync-v1.14.0", True), ("feature/agents-page", False), ("chore/scripts-sync-1.5.0", False)],
)
def test_agents_md_skips_the_version_check_on_a_kit_sync_branch_alone(tmp_path: Path, head: str, exempt: bool):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": head}),
        patch.object(cv, "_changed_files", return_value = ["skills.md", "AGENTS.md"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is exempt


def test_a_kit_sync_branch_that_changes_code_still_needs_a_bump(tmp_path: Path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": "chore/kit-sync-v1.14.0"}),
        patch.object(cv, "_changed_files", return_value = ["AGENTS.md", "src/app.py"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False
