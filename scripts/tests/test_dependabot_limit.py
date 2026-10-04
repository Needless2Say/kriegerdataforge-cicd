"""
Tests for the Dependabot limits the kit sync writes into a repo's own .github/dependabot.yml (cicd D-047).

Dependabot's version update pull requests cannot install the private packages and ran every repo's CI on each rebase,
about 800 billed minutes a week in four repos. The sync sets `open-pull-requests-limit: 0` on every `updates:` entry,
so Dependabot keeps raising alerts and opens no version update pull request. It replaces another value, adds a missing
one, keeps comments, order and line endings, writes nothing on a second run, and never creates the file.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import distribute_kit as dk
import pytest

PAGE = "\n".join([
    "# Dependabot configuration",
    "version: 2",
    "",
    "updates:",
    "  # Keep the Actions pins fresh",
    "  - package-ecosystem: \"github-actions\"",
    "    directory: \"/\"",
    "    schedule:",
    "      interval: \"weekly\"",
    "",
    "  - package-ecosystem: \"npm\"",
    "    directory: \"/\"",
    "    schedule:",
    "      interval: \"weekly\"",
    "    open-pull-requests-limit: 10  # bounded on purpose",
    "    groups:",
    "      dev-dependencies:",
    "        patterns:",
    "          - \"*\"",
    "    ignore:",
    "      - dependency-name: \"eslint\"",
    "        versions: [\">=10\"]",
    "",
    "  - package-ecosystem: \"docker\"",
    "    directory: \"/\"",
    "    schedule:",
    "      interval: \"weekly\"",
    "",
])

ONE_REPO = {"files": ["skills.md"], "repos": [{"repo": "Needless2Say/repo-a", "branch": "main"}]}


def _limits(page: str) -> list[str]:
    """
    The value of every `open-pull-requests-limit` line, in order.
    """
    return re.findall(r"^\s*(?:-\s+)?open-pull-requests-limit:\s*([^#\s]*)", page, flags = re.MULTILINE)


def _entries(page: str) -> int:
    return len(re.findall(r"^  - package-ecosystem:", page, flags = re.MULTILINE))

# ======================================================================================================================
# The patch
# ======================================================================================================================

def test_every_entry_ends_with_a_limit_of_zero():
    done = dk.limit_dependabot_prs(PAGE)
    assert _limits(done) == ["0", "0", "0"]
    assert _entries(done) == 3


def test_the_control_an_unpatched_page_is_not_at_zero_everywhere():
    """
    The page as it is fails the assertion above, so that test fails without the patch.
    """
    assert _limits(PAGE) != ["0"] * _entries(PAGE)


def test_a_different_limit_is_replaced_and_its_comment_kept():
    done = dk.limit_dependabot_prs(PAGE)
    assert "    open-pull-requests-limit: 0  # bounded on purpose" in done
    assert "open-pull-requests-limit: 10" not in done


def test_a_missing_limit_is_added_after_the_entrys_last_line_at_its_key_indent():
    lines   = dk.limit_dependabot_prs(PAGE).split("\n")
    actions = lines.index("      interval: \"weekly\"")
    assert lines[actions + 1] == "    open-pull-requests-limit: 0"
    assert lines[-2] == "    open-pull-requests-limit: 0"  # the docker entry, the last line of the page before its end


def test_nested_groups_and_ignore_lists_are_left_as_they_were():
    done = dk.limit_dependabot_prs(PAGE)
    for line in (
        "      dev-dependencies:",
        "          - \"*\"",
        "      - dependency-name: \"eslint\"",
        "        versions: [\">=10\"]",
    ):
        assert line in done
    assert done.count("open-pull-requests-limit") == 3


def test_comments_and_order_survive():
    done = dk.limit_dependabot_prs(PAGE)
    assert done.startswith("# Dependabot configuration\nversion: 2\n\nupdates:\n  # Keep the Actions pins fresh\n")
    order = [match for match in re.findall(r"package-ecosystem: \"(\w[\w-]*)\"", done)]
    assert order == ["github-actions", "npm", "docker"]


def test_crlf_lines_stay_crlf():
    crlf = PAGE.replace("\n", "\r\n")
    done = dk.limit_dependabot_prs(crlf)
    assert "\n" not in done.replace("\r\n", "")
    assert _limits(done) == ["0", "0", "0"]


def test_a_second_run_changes_nothing():
    done = dk.limit_dependabot_prs(PAGE)
    assert dk.limit_dependabot_prs(done) == done


@pytest.mark.parametrize("page", [
    "version: 2\n",
    "version: 2\nupdates: []\n",
    "# no config here\n",
], ids = ["no-updates", "flow-list", "comment-only"])
def test_a_page_without_an_updates_block_list_comes_back_unchanged(page):
    assert dk.limit_dependabot_prs(page) == page


def test_items_at_column_zero_and_a_key_on_the_dash_line():
    page = "version: 2\nupdates:\n- open-pull-requests-limit: 5\n  package-ecosystem: pip\n- package-ecosystem: npm\n"
    done = dk.limit_dependabot_prs(page)
    assert done == (
        "version: 2\nupdates:\n- open-pull-requests-limit: 0\n  package-ecosystem: pip\n"
        "- package-ecosystem: npm\n  open-pull-requests-limit: 0\n"
    )


def test_a_quoted_or_empty_limit_becomes_zero():
    page = "updates:\n  - package-ecosystem: pip\n    open-pull-requests-limit: \"3\"\n"
    assert _limits(dk.limit_dependabot_prs(page)) == ["0"]
    page = "updates:\n  - package-ecosystem: pip\n    open-pull-requests-limit:\n"
    # a space after the colon, or YAML reads `key:0` as one plain string
    assert dk.limit_dependabot_prs(page) == "updates:\n  - package-ecosystem: pip\n    open-pull-requests-limit: 0\n"


def test_a_page_without_a_final_newline_gets_its_line_after_one():
    page = "updates:\n  - package-ecosystem: pip\n    directory: /"
    assert dk.limit_dependabot_prs(page) == "updates:\n  - package-ecosystem: pip\n    directory: /\n" \
        "    open-pull-requests-limit: 0\n"

# ======================================================================================================================
# The sync writes the page only where it exists
# ======================================================================================================================

def _reader(files: dict[str, str]):
    def read(_token, _repo, _branch, path):
        return (files[path], "sha") if path in files else (None, None)


    return read


def test_dependabot_due_is_false_for_a_repo_without_the_file():
    with patch.object(dk, "_get_remote_file", side_effect = _reader({})):
        assert dk.dependabot_due("tok", "o/r", "main") is False


def test_dependabot_due_is_true_until_the_page_is_at_zero():
    with patch.object(dk, "_get_remote_file", side_effect = _reader({dk.DEPENDABOT_FILE: PAGE})):
        assert dk.dependabot_due("tok", "o/r", "main") is True
    done = dk.limit_dependabot_prs(PAGE)
    with patch.object(dk, "_get_remote_file", side_effect = _reader({dk.DEPENDABOT_FILE: done})):
        assert dk.dependabot_due("tok", "o/r", "main") is False


def _distribute(files: dict[str, str]):
    patches = [
        patch.object(dk, "compute_drift", return_value = []),
        patch.object(dk, "agents_line_missing", return_value = False),
        patch.object(dk, "_get_remote_file", side_effect = _reader(files)),
        patch.object(dk, "_get_branch_sha", return_value = "basesha"),
        patch.object(dk, "_create_branch"),
        patch.object(dk, "_open_pr_url", return_value = None),
        patch.object(dk, "_put_file"),
        patch.object(dk, "_create_pr", return_value = "https://pr"),
    ]
    started = [p.start() for p in patches]
    try:
        rc = dk.cmd_distribute(ONE_REPO, "tok", None)
    finally:
        for p in patches:
            p.stop()
    return rc, started[6], started[7]


def test_the_sync_writes_the_limits_and_says_why_in_the_pull_request():
    rc, put_file, create_pr = _distribute({dk.DEPENDABOT_FILE: PAGE})
    assert rc == 0
    put_file.assert_called_once()
    path, content = put_file.call_args.args[3], put_file.call_args.args[4]
    assert path == dk.DEPENDABOT_FILE
    assert _limits(content) == ["0", "0", "0"]
    body = create_pr.call_args.args[5]
    assert dk.DEPENDABOT_LABEL in body
    assert "Security update pull requests are a repo setting" in body


def test_a_repo_without_the_file_gets_none_and_no_pull_request():
    rc, put_file, create_pr = _distribute({})
    assert rc == 0
    put_file.assert_not_called()
    create_pr.assert_not_called()
