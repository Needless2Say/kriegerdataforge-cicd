"""
Tests for the tickets tool's file form, its config, check and fmt (tools/claude-code/kdf_tickets/).

Each test makes a repo's worktree under its temp folder with git init and an origin, writes its config and tickets,
and reads what check, fmt or the form say. The package is imported by its name from tools/claude-code with bytecode
off, and the shipped form is also run as kdf-tickets.sh runs it, the package's folder named to this interpreter with
-I and -B. PyYAML, in the test environment alone, reads every file the form writes and every fixture to the same value
the tool reads. Every owner, repo and ticket here is synthetic. The characters YAML misreads are made with chr, since
kdf-fmt's format writes a string's \\u escapes as the characters themselves, which would stand in the source unseen.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOLS    = Path(__file__).resolve().parents[2] / "tools" / "claude-code"
PACKAGE  = TOOLS / "kdf_tickets"
LAUNCHER = TOOLS / "kdf-tickets.sh"
BASH     = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
# a stand in for cicd's venv interpreter, it logs each call and runs this interpreter, or plays one that cannot start
STAND_IN       = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log}"
{body}
"""
FIXTURES       = Path(__file__).resolve().parent / "fixtures" / "tickets"
GIT            = shutil.which("git")
OWNER          = "example-owner"
REPO           = "sample-app"
ORIGIN         = f"https://github.com/{OWNER}/{REPO}.git"
LINE_SEPARATOR = chr(0x2028)
PARAGRAPH      = chr(0x2029)
NEXT_LINE      = chr(0x85)
BYTE_ORDER     = chr(0xFEFF)
E_ACUTE        = chr(0xE9)
# each body class of design 5.2 and the form it is written in
BODIES = {
    "a block": ("The lead.\n\n  An indented line.\n\tA tab first.\nA line with trailing spaces  \n", "block"),
    "a first line of spaces": ("   three spaces first\nthen more\n", "block"),
    "a blank first line": ("\nthe second line\n", "block"),
    "an empty body": ("", "json"),
    "no final line break": ("no line break at the end", "json"),
    "several final line breaks": ("two at the end\n\n", "json"),
    "a lone line break": ("\n", "json"),
    "a line of white space alone": ("first\n   \nlast\n", "json"),
    "a line of a tab alone": ("first\n\t\nlast\n", "json"),
    "a carriage return alone": ("first\rsecond\n", "json"),
    "a Unicode line separator": (f"first{LINE_SEPARATOR}second\n", "json"),
    "a Unicode paragraph separator": (f"first{PARAGRAPH}second\n", "json"),
    "a control character": ("a bell \x07 here\n", "json"),
    "a C1 control character": (f"a next line {NEXT_LINE} here\n", "json"),
    "a byte order mark": (f"{BYTE_ORDER}a mark\n", "json"),
}

sys.path.insert(0, str(TOOLS))
written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    from kdf_tickets import check as checking
    from kdf_tickets import common, form
    from kdf_tickets.config import load_config, load_registry
finally:
    sys.dont_write_bytecode = written

pytestmark = pytest.mark.skipif(GIT is None, reason = "git is needed to make a worktree with an origin")


# the helpers

# ======================================================================================================================

def _git(path: Path, *args: str) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run([GIT, "-C", str(path), *args], check = True, capture_output = True, env = environment)


def _registry(folder: Path, keys: tuple[str, ...] = ("apps", "hosted")) -> Path:
    boards = [{"key": key, "title": f"Board {key}", "existing_node_id": f"PVT_{key}", "repos": []} for key in keys]
    path   = folder / "registry.json"
    path.write_text(json.dumps({"boards": boards}), encoding = "utf-8")
    return path


def _config(**changes) -> dict:
    config = {
        "format": 1,
        "owner": OWNER,
        "repo": REPO,
        "about": {REPO: {"board": "apps"}, "public-app": {"board": "hosted"}},
        "leave_out_labels": ["ops", "ai-triaged", "local-only"],
        "backup_age_days": 7,
        "read_only": False,
    }
    config.update(changes)
    return config


def _worktree(tmp_path: Path, config: dict | None = None, origin: str = ORIGIN) -> Path:
    root = tmp_path / "worktree"
    (root / "docs" / "tickets").mkdir(parents = True)
    _git(root, "init", "-q")
    _git(root, "remote", "add", "origin", origin)
    _write_config(root, config or _config())
    return root


def _write_config(root: Path, config: dict) -> None:
    (root / "docs" / "tickets" / "config.json").write_text(json.dumps(config, indent = 2), encoding = "utf-8")


def _ticket(ident: str = "first-ticket", **changes) -> form.Ticket:
    ticket = form.Ticket(id = ident, title = "A first ticket", about = REPO, body = "The lead.\n")
    for name, value in changes.items():
        setattr(ticket, name, value)
    return ticket


def _pulled(ident: str = "first-ticket", number: int = 1, board: dict | None = None, **changes) -> form.Ticket:
    board         = board if board is not None else {
        "status": "Backlog",
        "priority": "P2",
        "type": "Feature",
        "severity": None,
        "after": None,
    }
    ticket        = _ticket(ident, **changes)
    ticket.issue  = {
        "repo": REPO,
        "number": number,
        "node": f"I_node{number}",
        "url": f"https://github.com/{OWNER}/{REPO}/issues/{number}",
    }
    ticket.board  = board
    ticket.synced = form.synced_from(ticket, comments = None)
    return ticket


def _write(root: Path, ticket: form.Ticket, name: str | None = None) -> Path:
    path = root / "docs" / "tickets" / f"{name or ticket.id}.yaml"
    path.write_bytes(form.dump(ticket).encode("utf-8"))
    return path


def _problems(root: Path, registry: Path) -> list[str]:
    return checking.check(root, registry)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", str(PACKAGE), *args],
        capture_output = True,
        text = True,
        encoding = "utf-8",
        check = False,
    )


# the canonical form

# ======================================================================================================================

@pytest.mark.parametrize("label", sorted(BODIES))
def test_every_body_class_round_trips_through_the_tool_and_pyyaml(label: str) -> None:
    body, shape = BODIES[label]
    text = form.dump(_ticket(body = body))
    line = next(line for line in text.split("\n") if line.startswith("body: "))
    assert line == "body: |2" if shape == "block" else line.startswith('body: "')
    assert form.load(text).body == body
    assert yaml.safe_load(text)["body"] == body
    assert form.dump(form.load(text)) == text


def test_the_body_is_the_last_key_and_every_other_line_is_one_json_value() -> None:
    text  = form.dump(_pulled(body = "line one\nline two\n"))
    lines = text.split("\n")
    keys  = [line.partition(":")[0] for line in lines if line and not line.startswith("  ")]
    assert keys == list(form.ORDER)
    for line in lines[: len(form.ORDER) - 1]:
        json.loads(line.partition(": ")[2])


def test_carriage_return_and_line_feed_pairs_read_as_line_feeds_and_trailing_spaces_stay() -> None:
    text = form.dump(_ticket(body = "kept  \nsecond\n")).replace("\n", "\r\n")
    assert form.load(text).body == "kept  \nsecond\n"


def test_a_title_with_characters_yaml_reads_as_a_break_is_written_escaped_and_reads_back() -> None:
    title = f"odd {LINE_SEPARATOR} {NEXT_LINE} \x7f {BYTE_ORDER} and caf{E_ACUTE}"
    text  = form.dump(_ticket(title = title))
    assert LINE_SEPARATOR not in text and NEXT_LINE not in text and BYTE_ORDER not in text
    assert f"caf{E_ACUTE}" in text
    assert form.load(text).title == title
    assert yaml.safe_load(text)["title"] == title


def test_the_board_after_is_read_and_written() -> None:
    board  = {"status": "In Progress", "priority": "P1", "type": "Bug", "severity": "High", "after": "sample-app/zero"}
    text   = form.dump(_pulled(board = board))
    loaded = form.load(text)
    assert loaded.board["after"] == "sample-app/zero"
    assert yaml.safe_load(text)["board"] == board


def test_labels_and_assignees_are_written_sorted() -> None:
    text = form.dump(_ticket(labels = ["zeta", "alpha"], assignees = ["b-user", "a-user"]))
    assert 'labels: ["alpha", "zeta"]' in text
    assert 'assignees: ["a-user", "b-user"]' in text


def test_a_json_value_the_standard_library_would_take_loosely_is_refused() -> None:
    text = form.dump(_ticket()).replace('kind: "feature"', "kind: NaN")
    with pytest.raises(form.FormError):
        form.load(text)
    doubled = form.dump(_pulled()).replace('"repo": "sample-app",', '"repo": "sample-app", "repo": "other",')
    with pytest.raises(form.FormError):
        form.load(doubled)


def test_the_source_holds_no_character_it_cannot_show() -> None:
    for path in (*PACKAGE.glob("*.py"), Path(__file__)):
        text = path.read_text(encoding = "utf-8")
        assert form.UNSAFE.search(text) is None, path.name


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.yaml")), ids = lambda path: path.name)
def test_pyyaml_reads_every_fixture_to_the_value_the_tool_reads(path: Path) -> None:
    text   = path.read_text(encoding = "utf-8")
    ticket = form.load(text)
    assert form.dump(ticket) == text.replace("\r\n", "\n")
    assert yaml.safe_load(text) == form.as_dict(ticket)


def test_the_fixtures_folder_holds_tickets() -> None:
    assert len(list(FIXTURES.rglob("*.yaml"))) >= 3


# check

# ======================================================================================================================

def test_a_clean_worktree_checks_clean(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _pulled("first-ticket", 1, labels = ["bug"]))
    _write(root, _pulled("second-ticket", 2, parent = "first-ticket"))
    _write(root, _ticket("hosted-one", about = "public-app", labels = ["board:hosted"]))
    assert _problems(root, registry) == []


def test_a_file_not_in_canonical_form_is_refused_and_fmt_rewrites_it(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    path     = _write(root, _ticket(labels = ["zeta", "alpha"]))
    path.write_text(path.read_text(encoding = "utf-8").replace('["alpha", "zeta"]', '["zeta","alpha"]'), "utf-8")
    assert any("canonical form" in problem for problem in _problems(root, registry))
    assert checking.fmt(root) == (["first-ticket.yaml"], [])
    assert _problems(root, registry) == []


def test_a_comment_line_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    path     = _write(root, _ticket())
    path.write_text("# a note\n" + path.read_text(encoding = "utf-8"), encoding = "utf-8")
    assert any("canonical form" in problem for problem in _problems(root, registry))


def test_a_board_edited_by_hand_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    path     = _write(root, _pulled())
    path.write_text(path.read_text(encoding = "utf-8").replace('"P2"', '"P0"'), encoding = "utf-8")
    problems = _problems(root, registry)
    assert any("board" in problem and "pull" in problem for problem in problems)


def test_a_comments_file_edited_by_hand_is_refused(tmp_path: Path) -> None:
    root          = _worktree(tmp_path)
    registry      = _registry(tmp_path)
    comments      = "<!-- kdf-comment node=IC_1 author=someone at=2026-01-01T00:00:00Z -->\nA comment.\n"
    ticket        = _pulled()
    ticket.synced = form.synced_from(ticket, comments = comments)
    _write(root, ticket)
    side = root / "docs" / "tickets" / "first-ticket.comments.md"
    side.write_text(comments, encoding = "utf-8")
    assert _problems(root, registry) == []
    side.write_text(comments + "An edit.\n", encoding = "utf-8")
    assert any("comments" in problem for problem in _problems(root, registry))
    side.unlink()
    assert any("comments" in problem for problem in _problems(root, registry))


def test_a_comments_file_without_its_ticket_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    (root / "docs" / "tickets" / "lonely.comments.md").write_text("x\n", encoding = "utf-8")
    assert any("lonely.comments.md" in problem for problem in _problems(root, registry))


def test_an_id_that_is_not_its_file_name_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("first-ticket"), name = "another-name")
    assert any("file's name" in problem for problem in _problems(root, registry))


@pytest.mark.parametrize("ident", ["../escape", "/absolute", "back\\slash", "has.dot", "Upper", "-lead", "x" * 65, ""])
def test_an_id_failing_the_slug_pattern_is_refused(tmp_path: Path, ident: str) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket(ident), name = "safe-name")
    assert any("slug" in problem for problem in _problems(root, registry))


@pytest.mark.parametrize("name", ["has.dot", "Upper", "-lead"])
def test_a_file_name_failing_the_slug_pattern_is_refused(tmp_path: Path, name: str) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket(name), name = name)
    assert any("slug" in problem for problem in _problems(root, registry))


def test_a_duplicate_id_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("first-ticket"))
    _write(root, _ticket("first-ticket"), name = "copy-ticket")
    assert any("duplicate id" in problem for problem in _problems(root, registry))


def test_two_files_naming_one_issue_are_refused_naming_both(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _pulled("first-ticket", 4))
    _write(root, _pulled("second-ticket", 4))
    problems = [problem for problem in _problems(root, registry) if "one issue" in problem]
    assert problems and "first-ticket" in problems[0] and "second-ticket" in problems[0]


def test_a_missing_parent_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket(parent = "not-here"))
    assert any("parent" in problem for problem in _problems(root, registry))


def test_a_parent_in_another_repo_is_taken_by_its_form(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket(parent = "other-repo/some-ticket"))
    assert _problems(root, registry) == []
    _write(root, _ticket(parent = "other-repo/../x"))
    assert any("parent" in problem for problem in _problems(root, registry))


def test_an_issue_in_another_repo_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    ticket   = _pulled()
    ticket.issue["repo"] = "other-repo"
    ticket.issue["url"] = f"https://github.com/{OWNER}/other-repo/issues/1"
    _write(root, ticket)
    assert any("issue.repo" in problem for problem in _problems(root, registry))


def test_an_issue_url_that_disagrees_with_its_number_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    ticket   = _pulled()
    ticket.issue["url"] = f"https://github.com/{OWNER}/{REPO}/issues/99"
    _write(root, ticket)
    assert any("issue.url" in problem for problem in _problems(root, registry))


def test_an_about_the_config_does_not_name_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket(about = "unknown-repo"))
    assert any("about" in problem for problem in _problems(root, registry))


def test_a_board_label_must_match_its_about_board(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("hosted-one", about = "public-app", labels = ["board:apps"]))
    assert any("board:" in problem for problem in _problems(root, registry))
    _write(root, _ticket("hosted-one", about = "public-app", labels = ["board:hosted", "board:apps"]))
    assert any("board:" in problem for problem in _problems(root, registry))


def test_a_hosted_ticket_without_a_board_label_is_taken(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("moved-one", about = "public-app"))
    assert _problems(root, registry) == []


def test_an_unknown_kind_and_a_state_out_of_its_unit_are_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("bad-kind", kind = "epic"))
    _write(root, _ticket("open-reason", reason = "completed"))
    _write(root, _ticket("closed-odd", state = "closed", reason = "maybe"))
    problems = _problems(root, registry)
    assert any("bad-kind" in problem and "kind" in problem for problem in problems)
    assert any("open-reason" in problem and "reason" in problem for problem in problems)
    assert any("closed-odd" in problem and "reason" in problem for problem in problems)


def test_a_new_tickets_title_past_110_is_refused_and_a_pulled_one_kept(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket("long-new", title = "t" * 111))
    _write(root, _pulled("long-pulled", 3, title = "t" * 140))
    problems = _problems(root, registry)
    assert any("long-new" in problem for problem in problems)
    assert not any("long-pulled" in problem for problem in problems)


def test_a_stray_file_in_the_folder_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    (root / "docs" / "tickets" / "notes.yml").write_text("x: 1\n", encoding = "utf-8")
    assert any("notes.yml" in problem for problem in _problems(root, registry))


# the config

# ======================================================================================================================

def test_a_config_whose_repo_differs_from_the_origin_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path, origin = f"git@github.com:{OWNER}/copied-template.git")
    registry = _registry(tmp_path)
    with pytest.raises(common.Refusal, match = "origin"):
        load_config(root, registry)


def test_an_origin_in_ssh_or_https_form_matches_its_config(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    for index, origin in enumerate((f"git@github.com:{OWNER}/{REPO}.git", f"https://github.com/{OWNER}/{REPO}")):
        root = _worktree(tmp_path / str(index), origin = origin)
        assert load_config(root, registry).repo == REPO


def test_a_board_key_the_registry_lacks_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path, _config(about = {REPO: {"board": "nowhere"}}))
    registry = _registry(tmp_path)
    with pytest.raises(common.Refusal, match = "nowhere"):
        load_config(root, registry)


def test_a_board_with_no_pinned_node_is_read_and_refused_only_when_a_config_names_it(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    boards   = [
        {"key": "apps", "title": "Board apps", "existing_node_id": "PVT_apps", "repos": []},
        {"key": "new", "title": "Board new", "existing_node_id": None, "repos": []},
    ]
    registry.write_text(json.dumps({"boards": boards}), encoding = "utf-8")
    assert load_config(_worktree(tmp_path / "a", _config(about = {REPO: {"board": "apps"}})), registry).repo == REPO
    with pytest.raises(common.Refusal, match = "does not yet pin"):
        load_config(_worktree(tmp_path / "b", _config(about = {REPO: {"board": "new"}})), registry)


def test_cicds_own_registry_reads() -> None:
    boards = load_registry()
    assert {"fitness", "platform", "business", "personal", "cicd"} <= set(boards)
    assert boards["business"].node and not boards["cicd"].node


def test_an_unknown_format_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path, _config(format = 2))
    registry = _registry(tmp_path)
    with pytest.raises(common.Refusal, match = "format"):
        load_config(root, registry)


def test_an_unknown_config_key_and_a_wrong_type_are_refused(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root     = _worktree(tmp_path / "a", _config(extra = True))
    with pytest.raises(common.Refusal, match = "extra"):
        load_config(root, registry)
    root = _worktree(tmp_path / "b", _config(read_only = "no"))
    with pytest.raises(common.Refusal, match = "read_only"):
        load_config(root, registry)


def test_a_worktree_without_a_config_is_refused(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    (root / "docs" / "tickets" / "config.json").unlink()
    with pytest.raises(common.Refusal, match = "config.json"):
        load_config(root, registry)


# the shipped form

# ======================================================================================================================

def test_the_package_runs_isolated_and_check_exits_by_its_findings(tmp_path: Path) -> None:
    root     = _worktree(tmp_path)
    registry = _registry(tmp_path)
    _write(root, _ticket())
    clean = _run("check", "--root", str(root), "--registry", str(registry))
    assert clean.returncode == 0, clean.stderr
    _write(root, _ticket("bad-kind", kind = "epic"))
    found = _run("check", "--root", str(root), "--registry", str(registry))
    assert found.returncode == 1
    assert "bad-kind" in found.stdout
    assert not (PACKAGE / "__pycache__").exists() or not any((PACKAGE / "__pycache__").iterdir())


def test_the_arguments_are_strict(tmp_path: Path) -> None:
    root = _worktree(tmp_path)
    assert _run("chec", "--root", str(root)).returncode == common.REFUSED
    assert _run("check", "--ro", str(root)).returncode == common.REFUSED
    assert _run("check", f"@{root}").returncode == common.REFUSED
    helped = _run("--help")
    assert helped.returncode == 0 and "check" in helped.stdout


def test_a_reviewer_is_refused_before_help(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-I", "-B", str(PACKAGE), "--help"],
        capture_output = True,
        text = True,
        env = {**os.environ, "KDF_ROLE": "reviewer"},
        check = False,
    )
    assert done.returncode == common.REFUSED
    assert "reviewer" in done.stderr


# the launcher, against a stand in interpreter, since GitHub's test job makes no repo .venv

# ======================================================================================================================

def _layout(tmp_path: Path, interpreter: str | None) -> tuple[Path, Path]:
    """
    A checkout holding the launcher and the package, with a stand in at .venv/bin/python that runs or fails, or none.
    """
    tools = tmp_path / "cicd" / "tools" / "claude-code"
    tools.mkdir(parents = True)
    shutil.copy2(LAUNCHER, tools / LAUNCHER.name)
    shutil.copytree(PACKAGE, tools / PACKAGE.name, ignore = shutil.ignore_patterns("__pycache__"))
    log = tmp_path / "interpreter.log"
    if interpreter is not None:
        body  = f'exec "{Path(sys.executable).as_posix()}" "$@"' if interpreter == "runs" else "exit 1"
        stand = tmp_path / "cicd" / ".venv" / "bin" / "python"
        stand.parent.mkdir(parents = True)
        stand.write_text(STAND_IN.format(log = log.as_posix(), body = body), encoding = "utf-8", newline = "\n")
        stand.chmod(0o755)
    return tools / LAUNCHER.name, log


def _launch(launcher: Path, *args: str, role: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key != "KDF_ROLE"}
    if role is not None:
        environment["KDF_ROLE"] = role
    return subprocess.run([str(BASH), str(launcher), *args], capture_output = True, text = True, env = environment)


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the launcher needs bash")
def test_the_launcher_refuses_a_reviewer_before_help_and_before_the_interpreter(tmp_path: Path) -> None:
    launcher, log = _layout(tmp_path, "runs")
    for args in (("--help",), ("check", "--root", str(tmp_path))):
        done = _launch(launcher, *args, role = "reviewer")
        assert done.returncode == 3 and done.stdout == "", args
        assert "reviewer role never runs the tickets tool" in done.stderr
    assert not log.exists()


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the launcher needs bash")
def test_the_launcher_exits_four_naming_make_venv_with_no_usable_interpreter(tmp_path: Path) -> None:
    for interpreter in (None, "fails"):
        launcher, _ = _layout(tmp_path / str(interpreter), interpreter)
        done = _launch(launcher, "--help")
        assert done.returncode == 4 and done.stdout == "", interpreter
        assert "make venv" in done.stderr


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the launcher needs bash")
def test_the_launcher_runs_the_package_isolated_with_no_bytecode_and_every_argument(tmp_path: Path) -> None:
    launcher, log = _layout(tmp_path, "runs")
    done = _launch(launcher, "--help")
    assert done.returncode == 0 and "pull runs in one of three modes" in done.stdout, done.stderr
    for name in ("check", "fmt", "plan", "pull", "find", "prompt", "scan", "ages"):
        assert name in done.stdout
    root = _worktree(tmp_path / "repo")
    done = _launch(launcher, "find", "--root", str(root))
    assert done.returncode == 0, done.stderr
    last = log.read_text(encoding = "utf-8").splitlines()[-1]
    assert last.startswith("-I -B ") and last.split()[2].endswith("kdf_tickets")
    assert last.endswith(f"find --root {root}")
    assert not list(launcher.parent.rglob("__pycache__"))
