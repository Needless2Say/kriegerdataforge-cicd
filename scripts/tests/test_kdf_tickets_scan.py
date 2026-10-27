"""
Tests for the tickets tool's sensitivity scan, design 5.11, its patterns, the owner's private words, the allowance
bound to its text, and pull holding a flagged issue back (tools/claude-code/kdf_tickets/scan.py).

Every text here is synthetic, the card number a published test number and the IBAN the standard's own example.
GitHub is the stand in of tickets_fakes.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tests.tickets_fakes import GIT, REPO, card, setup, tickets
from tests.tickets_fakes import pull as run_pull

# each pattern class, a synthetic text it hits and the name the scan gives it
HITS  = {
    "a money amount": "the quote came to $1,250.00 in the end",
    "a money amount in words": "about 300 USD a month",
    "a card number": "paid with 4111 1111 1111 1111 yesterday",
    "an account number": "send it to GB82 WEST 1234 5698 7654 32 please",
    "an account by its label": "the account number: 12345678 on file",
    "an email address": "write to someone@private-mail.test about it",
    "a phone number": "call (555) 123-4567 after noon",
    "a street address": "the office at 221 Baker Street moved",
    "the word invoice": "the invoice is overdue",
    "the word salary": "a salary review",
    "the word lawsuit": "the lawsuit was settled",
    "the word diagnosis": "a diagnosis came back",
    "the word tax": "the tax form",
    "a contract beside an amount": "the contract is worth $5,000",
    "a contract with a party": "a contract with Acme for the year",
}
NAMES = {
    "a money amount in words": "a money amount",
    "an account by its label": "an account number",
    "a contract beside an amount": "the word contract",
    "a contract with a party": "the word contract",
}
# texts an engineering ticket holds that the scan must not flag
CLEAN_TEXTS = (
    "a syntax error in the parser",
    "keep the API contract stable across versions",
    "the contract tests pass",
    "echo $1 in the script",
    "bump to 1.12.3 and pin sha 3f2a9b1c",
    "the date 2026-10-27 and the port 5432",
    "mail noreply@github.com or someone@example.com",
    "the 404 page and the 500 page",
    "taxonomy of the syntax tree",
)
# a comment added on GitHub after an allowance
NEW_COMMENT = {
    "id": "IC_9",
    "author": {"login": "someone"},
    "createdAt": "2026-07-13T00:00:00Z",
    "updatedAt": None,
    "body": "a new comment",
}

written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    from kdf_tickets import commands, scan
    from kdf_tickets.common import CLEAN, FOUND, Refusal
finally:
    sys.dont_write_bytecode = written

pytestmark = pytest.mark.skipif(GIT is None, reason = "git is needed to make a worktree with an origin")


# the patterns

# ======================================================================================================================

@pytest.mark.parametrize("label", sorted(HITS))
@pytest.mark.parametrize("place", ["title", "body", "comment 1"])
def test_each_pattern_class_hits_a_title_a_body_and_a_comment(label: str, place: str) -> None:
    text  = HITS[label]
    parts = {"title": "A title", "body": "A body.\n", "comment 1": "A comment."}
    parts[place] = text
    hit  = scan.scan_issue(7, "a-ticket", parts["title"], parts["body"], [parts["comment 1"]])
    name = NAMES.get(label, label)
    assert hit is not None and place in hit.counts and hit.counts[place][name] >= 1
    assert text not in hit.line()


@pytest.mark.parametrize("text", CLEAN_TEXTS)
def test_engineering_text_does_not_hit(text: str) -> None:
    assert scan.count(text) == {}


def test_a_card_number_failing_its_check_and_an_iban_failing_its_check_do_not_hit() -> None:
    assert scan.count("order 4111 1111 1111 1112 shipped") == {}
    assert scan.count("ref GB82 WEST 1234 5698 7654 33 closed") == {}


def test_a_private_word_is_printed_as_a_private_word_and_never_itself(tmp_path: Path) -> None:
    words = tmp_path / "private-words.txt"
    words.write_text("# the owner's words\nZephyrine\n", encoding = "utf-8")
    pattern = scan.private_words(words)
    hit     = scan.scan_issue(3, "a-ticket", "about zephyrine's plan", "x\n", [], pattern)
    assert hit is not None and hit.counts["title"][scan.PRIVATE] == 1
    assert "zephyrine" not in hit.line().lower()


def test_a_missing_private_words_list_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal):
        scan.private_words(tmp_path / "missing.txt")


# the allowance and the command

# ======================================================================================================================

def _flagged(tmp_path: Path):
    github, root, registry, reader = setup(tmp_path, issues = 2)
    github.repos[REPO]["issues"][0]["body"] = "the invoice is attached\n"
    return github, root, registry, reader


def test_scan_lists_a_flagged_issue_by_its_id_and_pattern(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    code, lines = commands.scan_command(root, reader, registry)
    assert code == FOUND
    assert any(line.startswith("#1 ticket-number-1: body, the word invoice (1)") for line in lines)
    assert not any("attached" in line for line in lines)


def test_an_allowance_binds_to_its_text_and_asks_again_once_it_changes(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    code, _ = commands.scan_command(root, reader, registry, allow = ["ticket-number-1"])
    assert code == CLEAN
    config = json.loads((root / "docs" / "tickets" / "config.json").read_text(encoding = "utf-8"))
    assert config["allow"]["ticket-number-1"]["policy"] == scan.POLICY
    assert commands.scan_command(root, reader, registry)[0] == CLEAN
    for change in ("title", "body", "comment"):
        github.repos[REPO]["issues"][0].update(body = "the invoice is attached\n", comments = [])
        commands.scan_command(root, reader, registry, allow = ["ticket-number-1"])
        if change == "title":
            github.repos[REPO]["issues"][0]["title"] = "Ticket number 1, renamed"
        elif change == "body":
            github.repos[REPO]["issues"][0]["body"] = "the invoice is attached, and more\n"
        else:
            github.repos[REPO]["issues"][0]["comments"] = [NEW_COMMENT]
        assert commands.scan_command(root, reader, registry)[0] == FOUND, change
        github.repos[REPO]["issues"][0]["title"] = "Ticket number 1"


def test_allowing_an_id_the_scan_does_not_flag_is_refused(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    with pytest.raises(Refusal, match = "ticket-number-2"):
        commands.scan_command(root, reader, registry, allow = ["ticket-number-2"])


def test_scan_refuses_a_public_repo_before_any_other_read(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    github.repos[REPO]["private"] = False
    with pytest.raises(Refusal, match = "public"):
        commands.scan_command(root, reader, registry)
    assert github.operations() == ["Visibility"]


# pull

# ======================================================================================================================

def test_pull_writes_no_file_for_a_flagged_issue_until_it_is_allowed(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    code, lines = run_pull(root, registry, reader, mode = "adopt")
    assert code == FOUND
    assert sorted(tickets(root)) == ["ticket-number-2"]
    assert any("#1 ticket-number-1" in line and "Held by the scan" in line for line in lines)
    commands.scan_command(root, reader, registry, allow = ["ticket-number-1"])
    code, _ = run_pull(root, registry, reader, mode = "backup")
    assert code == CLEAN and sorted(tickets(root)) == ["ticket-number-1", "ticket-number-2"]


def test_pull_scans_a_changed_text_and_holds_its_change(tmp_path: Path) -> None:
    github, root, registry, reader = setup(tmp_path, issues = 1)
    run_pull(root, registry, reader, mode = "adopt")
    github.repos[REPO]["issues"][0]["body"] = "now with a salary figure\n"
    code, lines = run_pull(root, registry, reader, mode = "backup")
    assert code == FOUND and any("Held by the scan" in line for line in lines)
    assert "salary" not in tickets(root)["ticket-number-1"].body


def test_pull_does_not_scan_an_unchanged_text_again(tmp_path: Path) -> None:
    github, root, registry, reader = _flagged(tmp_path)
    commands.scan_command(root, reader, registry, allow = ["ticket-number-1"])
    run_pull(root, registry, reader, mode = "adopt")
    config = root / "docs" / "tickets" / "config.json"
    data   = json.loads(config.read_text(encoding = "utf-8"))
    data.pop("allow")
    config.write_text(json.dumps(data), encoding = "utf-8")
    github.boards["PVT_apps"]["cards"][0] = card(REPO, 1, "Done")
    code, lines = run_pull(root, registry, reader, mode = "backup")
    # a board move alone changes no text, so the text allowed before is not held again
    assert code == CLEAN and tickets(root)["ticket-number-1"].board["status"] == "Done"
