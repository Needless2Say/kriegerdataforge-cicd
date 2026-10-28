"""
Tests for the tickets tool's GitHub side, the reader, the merge of design 5.5 and the read commands, plan, pull,
find, prompt and ages (tools/claude-code/kdf_tickets/).

GitHub is the stand in of tickets_fakes.py. Each test builds the repos, issues and boards it needs, and reads which
reads were made and in what order. No test reaches GitHub. Every owner, repo, issue and board here is synthetic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.tickets_fakes import BOARD, GIT, HOSTER, OWNER, REPO, TOOLS, FakeGitHub, card
from tests.tickets_fakes import git as _git
from tests.tickets_fakes import plan as _plan
from tests.tickets_fakes import pull as _pull
from tests.tickets_fakes import registry as _registry
from tests.tickets_fakes import rewrite as _rewrite
from tests.tickets_fakes import setup as _setup
from tests.tickets_fakes import tickets as _tickets
from tests.tickets_fakes import worktree as _worktree

# a feature's body with its design prompt, as the template writes one
PROMPTED = """The lead.

**Its design prompt.**

```text
You are `sample-design`, an Opus design session. You design ticket sample-app#1.
Your STATUS.md section is "Sample".
```
"""

written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    from kdf_tickets import commands, form
    from kdf_tickets.common import CLEAN, CONFLICT, FOUND, Refusal, text_digest
    from kdf_tickets.github import Reader
finally:
    sys.dont_write_bytecode = written

pytestmark = pytest.mark.skipif(GIT is None, reason = "git is needed to make a worktree with an origin")


# the merge, design 5.5

# ======================================================================================================================

def test_adoption_then_a_quiet_plan_is_in_step(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    code, _ = _pull(root, registry, reader, mode = "adopt")
    assert code == CLEAN
    assert sorted(_tickets(root)) == ["ticket-number-1", "ticket-number-2"]
    assert _plan(root, registry, reader)[0] == CLEAN


def test_each_row_of_the_merge_table(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 4)
    _pull(root, registry, reader, mode = "adopt")
    # row 2, the file changed and GitHub did not, the file's value to push
    _rewrite(root, "ticket-number-1", title = "A title the session changed")
    # row 3, GitHub changed and the file did not, GitHub's value to pull
    github.repos[REPO]["issues"][1]["title"] = "A title the owner changed"
    # row 4, both changed apart, a conflict
    _rewrite(root, "ticket-number-3", title = "the file's title")
    github.repos[REPO]["issues"][2]["title"] = "GitHub's title"
    # row 1, both changed alike, in step
    _rewrite(root, "ticket-number-4", title = "the same title")
    github.repos[REPO]["issues"][3]["title"] = "the same title"
    code, lines = _plan(root, registry, reader)
    assert code == CONFLICT
    text = "\n".join(lines)
    assert "ticket-number-1: title, the file's to push" in text
    assert "ticket-number-2: title, GitHub's to pull" in text
    assert "ticket-number-3: title, a conflict" in text
    assert "ticket-number-4" not in text
    _pull(root, registry, reader, mode = "backup")
    tickets = _tickets(root)
    assert tickets["ticket-number-1"].title == "A title the session changed"
    assert tickets["ticket-number-2"].title == "A title the owner changed"
    assert tickets["ticket-number-4"].synced["title"] == text_digest("the same title")


def test_a_conflict_leaves_its_field_and_base_alone_until_take(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    base = _tickets(root)["ticket-number-1"].synced["title"]
    _rewrite(root, "ticket-number-1", title = "the file's title")
    github.repos[REPO]["issues"][0]["title"] = "GitHub's title"
    _pull(root, registry, reader, mode = "backup")
    ticket = _tickets(root)["ticket-number-1"]
    assert ticket.title == "the file's title" and ticket.synced["title"] == base
    _pull(root, registry, reader, mode = "only", only = ["ticket-number-1"], take = True)
    ticket = _tickets(root)["ticket-number-1"]
    assert ticket.title == "GitHub's title" and ticket.synced["title"] == text_digest("GitHub's title")


def test_labels_merge_by_item_on_both_sides(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["labels"] = ["kept", "dropped-on-github", "dropped-in-file"]
    _pull(root, registry, reader, mode = "adopt")
    _rewrite(root, "ticket-number-1", labels = ["kept", "dropped-on-github", "added-in-file"])
    github.repos[REPO]["issues"][0]["labels"] = ["kept", "dropped-in-file", "added-on-github"]
    code, lines = _plan(root, registry, reader)
    assert code == FOUND
    _pull(root, registry, reader, mode = "backup")
    ticket = _tickets(root)["ticket-number-1"]
    # each side's own change taken, an add on one side never meeting a remove of the same label against one base
    assert ticket.labels == ["added-in-file", "added-on-github", "kept"]
    assert ticket.synced["labels"] == ["added-on-github", "dropped-in-file", "kept"]
    assert any("labels, the file's to push" in line for line in _plan(root, registry, reader)[1])


def test_an_issue_reopened_comes_in_open_with_no_reason(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0].update(state = "CLOSED", stateReason = "COMPLETED")
    _pull(root, registry, reader, mode = "adopt")
    assert (
        _tickets(root)["ticket-number-1"].state,
        _tickets(root)["ticket-number-1"].reason,
    ) == ("closed", "completed")
    github.repos[REPO]["issues"][0].update(state = "OPEN", stateReason = "REOPENED")
    _pull(root, registry, reader, mode = "backup")
    ticket = _tickets(root)["ticket-number-1"]
    assert (ticket.state, ticket.reason) == ("open", None)


def test_the_marker_is_left_out_of_the_body_and_its_hash(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["body"] = "The lead.\n\n<!-- kdf-ticket: chosen-id -->"
    _pull(root, registry, reader, mode = "adopt")
    ticket = _tickets(root)["chosen-id"]
    assert "kdf-ticket" not in ticket.body
    assert ticket.synced["body"] == text_digest(ticket.body)


def test_a_marker_failing_the_slug_pattern_is_refused_and_listed(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["body"] = "x\n<!-- kdf-ticket: ../escape -->"
    code, lines = _pull(root, registry, reader, mode = "adopt")
    assert code == FOUND
    assert any("#1" in line and "slug" in line for line in lines)
    assert not any(path.name.startswith(".") for path in (root / "docs").rglob("*"))


def test_a_label_starting_with_a_leave_out_entry_is_skipped(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 3)
    github.repos[REPO]["issues"][0]["labels"] = ["ops:ecosystem-watch"]
    github.repos[REPO]["issues"][1]["labels"] = ["local-only"]
    _pull(root, registry, reader, mode = "adopt")
    assert sorted(_tickets(root)) == ["ticket-number-3"]
    assert _plan(root, registry, reader)[0] == CLEAN


def test_comments_are_backed_up_beside_the_ticket(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["comments"] = [
        {
            "id": "IC_1",
            "author": {"login": "someone"},
            "createdAt": "2026-07-13T00:00:00Z",
            "updatedAt": None,
            "body": "First.\r\nSecond line.",
        },
        {"id": "IC_2", "author": None, "createdAt": "2026-07-14T00:00:00Z", "updatedAt": None, "body": "Gone user."},
    ]
    _pull(root, registry, reader, mode = "adopt")
    side = (root / "docs" / "tickets" / "ticket-number-1.comments.md").read_text(encoding = "utf-8")
    assert "<!-- kdf-comment node=IC_1 author=someone at=2026-07-13T00:00:00Z -->\nFirst.\nSecond line.\n" in side
    assert "author=ghost" in side
    assert _tickets(root)["ticket-number-1"].synced["comments"] == text_digest(side)


# the fences

# ======================================================================================================================

def test_a_public_repo_is_refused_before_any_other_call(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["private"] = False
    with pytest.raises(Refusal, match = "public"):
        _pull(root, registry, reader, mode = "adopt")
    with pytest.raises(Refusal, match = "public"):
        _plan(root, registry, reader)
    assert set(github.operations()) == {"Visibility"}
    assert list((root / "docs" / "tickets").glob("*.yaml")) == []


def test_a_pull_whose_first_board_read_fails_refuses_and_writes_nothing(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    before = {path.name: path.read_bytes() for path in (root / "docs" / "tickets").iterdir()}
    github.failing_boards.add(BOARD)
    github.repos[REPO]["issues"][0]["title"] = "changed on GitHub"
    with pytest.raises(Refusal, match = "read:project"):
        _pull(root, registry, reader, mode = "backup")
    assert {path.name: path.read_bytes() for path in (root / "docs" / "tickets").iterdir()} == before


def test_a_plain_pull_is_refused(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    with pytest.raises(Refusal, match = "--only, --adopt or --backup"):
        _pull(root, registry, reader, mode = None)


def test_adopt_is_refused_once_the_repo_holds_tickets(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    with pytest.raises(Refusal, match = "--backup"):
        _pull(root, registry, reader, mode = "adopt")


def test_an_issue_gone_from_github_keeps_its_file_and_is_reported(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    github.repos[REPO]["issues"].pop(0)
    code, lines = _plan(root, registry, reader)
    assert code == FOUND and any("ticket-number-1" in line and "gone" in line for line in lines)
    _pull(root, registry, reader, mode = "backup")
    assert "ticket-number-1" in _tickets(root)


# the modes

# ======================================================================================================================

def test_adoption_names_each_issue_by_its_title_made_unique(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 0)
    for number, title in ((1, "Fix the Login Page!"), (2, "Fix the login page"), (3, "Été"), (4, "???")):
        github.issue(REPO, number, title = title, boards = [BOARD])
    github.board(BOARD, 18, "Board apps", [card(REPO, number) for number in (1, 2, 3, 4)])
    _pull(root, registry, reader, mode = "adopt")
    tickets = _tickets(root)
    assert sorted(tickets) == ["ete", "fix-the-login-page", "fix-the-login-page-2", "issue-4"]
    assert tickets["fix-the-login-page-2"].issue["number"] == 2
    assert check_clean(root, registry)


def check_clean(root: Path, registry: Path) -> bool:
    from kdf_tickets import check as checking

    return checking.check(root, registry) == []


def test_backup_adopts_a_new_issue_and_only_touches_its_named_tickets_alone(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 3)
    _pull(root, registry, reader, mode = "adopt")
    github.repos[REPO]["issues"][0]["title"] = "first changed"
    github.repos[REPO]["issues"][1]["title"] = "second changed"
    github.issue(REPO, 4, title = "A new one", boards = [BOARD])
    github.boards[BOARD]["cards"].append(card(REPO, 4))
    code, _ = _pull(root, registry, reader, mode = "only", only = ["ticket-number-1"])
    tickets = _tickets(root)
    assert tickets["ticket-number-1"].title == "first changed"
    assert tickets["ticket-number-2"].title == "Ticket number 2"
    assert "a-new-one" not in tickets
    _pull(root, registry, reader, mode = "backup")
    tickets = _tickets(root)
    assert tickets["ticket-number-2"].title == "second changed" and "a-new-one" in tickets


def test_only_refuses_an_id_no_file_holds(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    with pytest.raises(Refusal, match = "not-here"):
        _pull(root, registry, reader, mode = "only", only = ["not-here"])


def _hoster(tmp_path: Path) -> tuple[FakeGitHub, Path, Path, Reader]:
    github = FakeGitHub()
    github.repo(HOSTER)
    github.issue(HOSTER, 1, title = "Moved from the public app", boards = ["PVT_hosted"])
    github.issue(HOSTER, 2, title = "Labelled for its board", labels = ["board:hosted"], boards = ["PVT_hosted"])
    github.issue(HOSTER, 3, title = "Neither moved nor labelled", boards = ["PVT_hosted"])
    github.board("PVT_hosted", 30, "Board hosted", [card(HOSTER, number) for number in (1, 2, 3)])
    root = _worktree(tmp_path, repo = HOSTER, about = {"public-app": {"board": "hosted"}})
    return github, root, _registry(tmp_path), Reader(run = github.run, sleep = lambda seconds: None)


def test_a_config_hosts_another_repos_tickets_by_its_data(tmp_path: Path) -> None:
    github, root, registry, reader = _hoster(tmp_path)
    moved = tmp_path / "moved.tsv"
    old   = f"https://github.com/{OWNER}/public-app/issues/40"
    moved.write_text(f"public-app#40\thttps://github.com/{OWNER}/{HOSTER}/issues/1\t{old}\n", encoding = "utf-8")
    code, lines = _pull(root, registry, reader, mode = "adopt", adoption_map = moved)
    tickets = _tickets(root)
    assert tickets["moved-from-the-public-app"].about == "public-app"
    assert tickets["labelled-for-its-board"].about == "public-app"
    # an unmarked issue in a repo hosting others' tickets, with no board: label and not in the map, is refused
    assert "neither-moved-nor-labelled" not in tickets
    assert code == FOUND and any("#3" in line and "board:" in line for line in lines)
    assert all(ticket.issue["repo"] == HOSTER for ticket in tickets.values())


def test_a_map_naming_another_repos_issue_is_refused(tmp_path: Path) -> None:
    github, root, registry, reader = _hoster(tmp_path)
    moved = tmp_path / "moved.tsv"
    moved.write_text(f"public-app#40\thttps://github.com/{OWNER}/elsewhere/issues/1\tx\n", encoding = "utf-8")
    with pytest.raises(Refusal, match = "map"):
        _pull(root, registry, reader, mode = "adopt", adoption_map = moved)


def test_the_board_is_read_by_the_registrys_pinned_node_and_its_number_from_github(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    assert ("Board", {"id": BOARD, "after": None}) in github.calls
    code, lines = _plan(root, registry, reader)
    assert any("Board apps, number 18" in line for line in lines)


def test_board_fields_and_after_are_read_from_the_cards_in_order(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 3)
    github.boards[BOARD]["cards"] = [
        card(REPO, 2, "In Progress", priority = "P1"),
        card(REPO, 0, kind = "DRAFT_ISSUE"),
        card(REPO, 1),
        card(REPO, 3),
    ]
    _pull(root, registry, reader, mode = "adopt")
    tickets = _tickets(root)
    assert tickets["ticket-number-2"].board == {
        "status": "In Progress",
        "priority": "P1",
        "type": None,
        "severity": None,
        "after": None,
    }
    # a draft above is skipped, the card following the nearest ticket above it
    assert tickets["ticket-number-1"].board["after"] == f"{REPO}/ticket-number-2"
    assert tickets["ticket-number-3"].board["after"] == f"{REPO}/ticket-number-1"


def test_a_draft_and_an_issue_off_its_board_are_differences(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 2)
    github.boards[BOARD]["cards"] = [card(REPO, 1), card(REPO, 9, kind = "DRAFT_ISSUE")]
    github.repos[REPO]["issues"][1]["boards"] = []
    _pull(root, registry, reader, mode = "adopt")
    assert _tickets(root)["ticket-number-2"].board is None
    code, lines = _plan(root, registry, reader)
    assert code == FOUND
    assert any("draft" in line for line in lines)
    assert any("ticket-number-2" in line and "off its board" in line for line in lines)


def test_an_item_on_another_board_is_a_difference(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["boards"] = [BOARD, "PVT_hosted"]
    _pull(root, registry, reader, mode = "adopt")
    code, lines = _plan(root, registry, reader)
    assert code == FOUND and any("ticket-number-1" in line and "Board hosted" in line for line in lines)


def test_an_item_on_a_closed_board_is_passed_over(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["boards"] = [BOARD, "PVT_closed_old"]
    github.closed_boards.add("PVT_closed_old")
    _pull(root, registry, reader, mode = "adopt")
    # a closed board is never backed up (design section 3), so an item on one is no difference
    assert _plan(root, registry, reader)[0] == CLEAN


def test_a_closed_board_of_the_configs_own_is_refused(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    github.closed_boards.add(BOARD)
    with pytest.raises(Refusal, match = "closed"):
        _plan(root, registry, reader)


def test_a_card_moved_on_the_board_comes_in_by_pull(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    github.boards[BOARD]["cards"][0] = card(REPO, 1, "Done", priority = "P0")
    code, lines = _plan(root, registry, reader)
    assert code == FOUND and any("ticket-number-1: board, GitHub's to pull" in line for line in lines)
    _pull(root, registry, reader, mode = "backup")
    assert _tickets(root)["ticket-number-1"].board["status"] == "Done"
    assert check_clean(root, registry)


# another repo on the board

# ======================================================================================================================

def test_after_passes_over_every_card_this_config_does_not_back_up_on_its_board(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 3)
    github.repos[REPO]["issues"][1]["labels"] = ["local-only"]
    github.boards[BOARD]["cards"] = [
        card(REPO, 1),
        card("sibling", 7),
        card(REPO, 0, kind = "DRAFT_ISSUE"),
        card("sibling", 8, kind = "PULL_REQUEST"),
        card(REPO, 2),
        card(REPO, 3),
    ]
    _pull(root, registry, reader, mode = "adopt")
    tickets = _tickets(root)
    assert tickets["ticket-number-1"].board["after"] is None
    assert tickets["ticket-number-3"].board["after"] == f"{REPO}/ticket-number-1"
    assert check_clean(root, registry)


def test_a_hosting_repo_names_its_own_tickets_and_passes_over_one_bound_to_another_board(tmp_path: Path) -> None:
    github, _, registry, reader = _hoster(tmp_path)
    github.repos[HOSTER]["issues"][1]["labels"] = ["board:apps"]
    github.repos[HOSTER]["issues"][1]["boards"] = ["PVT_hosted", BOARD]
    github.issue(HOSTER, 4, title = "Fourth", labels = ["board:hosted"], boards = ["PVT_hosted"])
    github.boards["PVT_hosted"]["cards"] = [card(HOSTER, number) for number in (2, 4)]
    github.board(BOARD, 18, "Board apps", [card(HOSTER, 2)])
    root = _worktree(
        tmp_path,
        repo = HOSTER,
        about = {"public-app": {"board": "hosted"}, "apps-app": {"board": "apps"}},
        name = "two-boards",
    )
    _pull(root, registry, reader, mode = "adopt")
    tickets = _tickets(root)
    assert tickets["labelled-for-its-board"].about == "apps-app"
    # #2 is backed up on apps, so its card on hosted is passed over, and the ticket's own block is its card on apps
    assert tickets["fourth"].board["after"] is None
    assert tickets["labelled-for-its-board"].board["after"] is None
    assert any("labelled-for-its-board: also on Board hosted" in line for line in _plan(root, registry, reader)[1])


def test_another_repos_card_moving_changes_no_file(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 2)
    github.boards[BOARD]["cards"] = [card(REPO, 1), card("sibling", 7), card(REPO, 2)]
    _pull(root, registry, reader, mode = "adopt")
    github.boards[BOARD]["cards"] = [card("sibling", 7), card(REPO, 1), card(REPO, 2)]
    assert _plan(root, registry, reader)[0] == CLEAN


def test_an_own_drag_changes_at_most_three_files(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 5)
    _pull(root, registry, reader, mode = "adopt")
    cards = github.boards[BOARD]["cards"]
    github.boards[BOARD]["cards"] = [cards[0], cards[2], cards[3], cards[1], cards[4]]
    _, lines = _pull(root, registry, reader, mode = "backup")
    written = sorted(line for line in lines if line.startswith("wrote "))
    assert written == ["wrote ticket-number-2.yaml", "wrote ticket-number-3.yaml", "wrote ticket-number-5.yaml"]
    assert _tickets(root)["ticket-number-2"].board["after"] == f"{REPO}/ticket-number-4"


def test_ages_dates_a_place_alone_by_the_last_backup_on_main(tmp_path: Path) -> None:
    github, _, registry, reader = _setup(tmp_path, issues = 3)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _clone(workspace, github, registry, reader, REPO)
    now   = 1785000000.0
    cards = github.boards[BOARD]["cards"]
    github.boards[BOARD]["cards"] = [cards[1], cards[0], cards[2]]
    code, lines = commands.ages(workspace, reader, registry, clock = lambda: now)
    # the cards' own times are 2026-07-12, the backup merged on 2026-07-15, the bound the age takes
    assert code == FOUND and any(f"{REPO}  10 days" in line for line in lines)


# the reader

# ======================================================================================================================

def test_a_rate_limit_reply_is_waited_out(tmp_path: Path) -> None:
    github, root, registry, _ = _setup(tmp_path)
    waits: list[float] = []
    reader              = Reader(run = github.run, sleep = waits.append)
    github.rate_limited = 2
    code, _ = _pull(root, registry, reader, mode = "adopt")
    assert code == CLEAN and waits == [7.0, 7.0]


def test_issues_page_a_hundred_at_a_time(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 150)
    _pull(root, registry, reader, mode = "adopt")
    assert len(_tickets(root)) == 150
    assert github.operations().count("Issues") == 2


# find, prompt and ages

# ======================================================================================================================

def test_find_by_label_and_kind_from_the_files_alone(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path, issues = 3)
    github.repos[REPO]["issues"][0]["labels"] = ["next-change"]
    github.repos[REPO]["issues"][2].update(state = "CLOSED", stateReason = "COMPLETED", labels = ["next-change"])
    _pull(root, registry, reader, mode = "adopt")
    _rewrite(root, "ticket-number-2", kind = "bug")
    calls = len(github.calls)
    assert [line.split()[0] for line in commands.find(root, label = "next-change")] == ["ticket-number-1"]
    assert [line.split()[0] for line in commands.find(root, kind = "bug")] == ["ticket-number-2"]
    assert len(commands.find(root, label = "next-change", state = "all")) == 2
    assert len(github.calls) == calls


def test_prompt_gives_a_features_design_prompt_and_an_in_progress_tickets_plan(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["body"] = PROMPTED
    github.repos[
        REPO
    ]["issues"][1]["body"] = "Built by [the plan](docs/features/2026-01-01-x/IMPLEMENTATION_PLAN.md).\n"
    github.boards[BOARD]["cards"][1] = card(REPO, 2, "In Progress")
    _pull(root, registry, reader, mode = "adopt")
    assert commands.prompt(root, "ticket-number-1").startswith("You are `sample-design`")
    assert "docs/features/2026-01-01-x/IMPLEMENTATION_PLAN.md" in commands.prompt(root, "ticket-number-2")
    _rewrite(root, "ticket-number-2", body = "No plan named.\n")
    with pytest.raises(Refusal):
        commands.prompt(root, "ticket-number-2")


def _clone(tmp_path: Path, github: FakeGitHub, registry: Path, reader: Reader, name: str) -> Path:
    root = _worktree(tmp_path, name = name)
    _pull(root, registry, reader, mode = "adopt")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "adopt")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def test_ages_gives_the_oldest_unpulled_change_and_zero_for_a_quiet_repo(tmp_path: Path) -> None:
    github, _, registry, reader = _setup(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _clone(workspace, github, registry, reader, REPO)
    now = 1785000000.0
    code, lines = commands.ages(workspace, reader, registry, clock = lambda: now)
    assert code == CLEAN and any(REPO in line and " 0 days" in line for line in lines)
    github.repos[REPO]["issues"][0].update(title = "changed", updatedAt = "2026-07-12T10:00:00Z")
    github.repos[REPO]["issues"][1].update(title = "changed too", updatedAt = "2026-07-20T10:00:00Z")
    code, lines = commands.ages(workspace, reader, registry, clock = lambda: now)
    oldest = int((now - 1783850400) // 86400)
    assert code == FOUND and any(f" {oldest} days" in line and "past" in line for line in lines)


def test_ages_reads_mains_files_and_not_the_working_tree(tmp_path: Path) -> None:
    github, _, registry, reader = _setup(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = _clone(workspace, github, registry, reader, REPO)
    for path in (root / "docs" / "tickets").glob("*.yaml"):
        path.unlink()
    code, lines = commands.ages(workspace, reader, registry, clock = lambda: 1785000000.0)
    assert code == CLEAN


# the shipped form

# ======================================================================================================================

def _run(*args: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PATH": ""}
    return subprocess.run(
        [sys.executable, "-I", "-B", str(TOOLS / "kdf_tickets"), *args],
        capture_output = True,
        text = True,
        encoding = "utf-8",
        env = environment,
        check = False,
    )


def test_the_shipped_pull_refuses_no_mode_and_two_modes_before_any_read(tmp_path: Path) -> None:
    root = _worktree(tmp_path)
    # with no gh on the path, a read would fail, so a refusal here was made before any read
    plain = _run("pull", "--root", str(root))
    assert plain.returncode == 3 and "--only, --adopt or --backup" in plain.stderr
    both = _run("pull", "--root", str(root), "--adopt", "--backup")
    assert both.returncode == 3
    assert _run("pull", "--root", str(root), "--backup", "--map", str(tmp_path)).returncode == 3


def test_the_shipped_find_and_prompt_read_the_files_alone(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    github.repos[REPO]["issues"][0]["body"] = PROMPTED
    _pull(root, registry, reader, mode = "adopt")
    found = _run("find", "--root", str(root))
    assert found.returncode == 0 and "ticket-number-1  sample-app#1" in found.stdout
    prompted = _run("prompt", "ticket-number-1", "--root", str(root))
    assert prompted.returncode == 0 and prompted.stdout.startswith("You are `sample-design`")


# plan's exits

# ======================================================================================================================

def test_plan_exits_zero_one_and_two(tmp_path: Path) -> None:
    github, root, registry, reader = _setup(tmp_path)
    _pull(root, registry, reader, mode = "adopt")
    assert _plan(root, registry, reader)[0] == CLEAN
    github.repos[REPO]["issues"][0]["title"] = "moved on"
    assert _plan(root, registry, reader)[0] == FOUND
    _rewrite(root, "ticket-number-1", title = "and here")
    assert _plan(root, registry, reader)[0] == CONFLICT
