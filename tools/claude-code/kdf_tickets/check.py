"""
check and fmt, the offline commands. check reads every file of a worktree's docs/tickets/ against the canonical form,
the fields' rules, the ids, the parents, each issue's identity and the config, and lists every problem. fmt rewrites
the ticket files into the canonical form and changes no value.
"""

from __future__ import annotations

# standard imports
from pathlib import Path

# third party imports
from kdf_tickets import form
from kdf_tickets.common import Refusal, repo_name, slug, text_digest
from kdf_tickets.config import REGISTRY, Config, load_config

# module constants
KINDS  = ("feature", "bug", "chore", "owner", "next-change")
STATES = ("open", "closed")
# the reasons GitHub gives a closed issue, duplicate among them, and none for one closed before reasons were kept
CLOSED_REASONS = ("completed", "not_planned", "duplicate", None)
TITLE_LIMIT    = 110
COMMENTS       = ".comments.md"
BOARD_LABEL    = "board:"


def folder(root: Path) -> Path:
    """
    Name a worktree's tickets folder.

    Args:
        root: the worktree

    Returns:
        Path: its docs/tickets/
    """
    return root / "docs" / "tickets"


def writable(root: Path, name: str) -> Path:
    """
    Name a file the tool may write, inside the worktree's docs/tickets/ alone, through no link.

    Args:
        root: the worktree
        name: the file's name in the folder

    Returns:
        Path: the file's path

    Raises:
        Refusal: for a folder or a file that is a link, or a path that resolves outside the folder
    """
    base = folder(root)
    path = base / name
    if base.is_symlink() or (root / "docs").is_symlink() or path.is_symlink():
        raise Refusal(f"{path} or a folder above it is a link, so the tool writes nothing through it")
    if path.resolve().parent != base.resolve() or not base.resolve().is_relative_to(root.resolve()):
        raise Refusal(f"{path} resolves outside the worktree's docs/tickets/, so the tool writes nothing there")
    return path


def read_tickets(root: Path) -> tuple[dict[str, tuple[form.Ticket, str]], dict[str, str], list[str]]:
    """
    Read every file of a worktree's tickets folder, the tickets, the comments files and what the folder should not hold.

    Args:
        root: the worktree

    Returns:
        tuple: each ticket and its text by file name, each comments file's text by its ticket's file stem, and the
            problems met reading, a file the reader cannot take or one that is no ticket's
    """
    tickets:  dict[str, tuple[form.Ticket, str]] = {}
    comments: dict[str, str] = {}
    problems: list[str] = []
    for path in sorted(folder(root).iterdir()):
        name = path.name
        if path.is_symlink():
            problems.append(f"{name}: a link, which the folder never holds, since a write through it would leave it")
            continue
        if name == "config.json":
            continue
        if path.is_file() and name.endswith(COMMENTS):
            comments[name[: -len(COMMENTS)]] = path.read_bytes().decode("utf-8", "replace")
            continue
        if not (path.is_file() and name.endswith(".yaml")):
            problems.append(f"{name}: not a ticket file, the folder holds config.json, <id>.yaml and <id>{COMMENTS}")
            continue
        try:
            text = path.read_bytes().decode("utf-8")
            tickets[name] = (form.load(text), text)
        except (UnicodeDecodeError, form.FormError) as error:
            problems.append(f"{name}: cannot be read, {error}")
    return tickets, comments, problems


def check(root: Path, registry: Path = REGISTRY) -> list[str]:
    """
    Check a worktree's tickets offline.

    Args:
        root: the worktree
        registry: the boards' registry

    Returns:
        list[str]: every problem, each leading with its file's name, empty when the folder is clean

    Raises:
        Refusal: for a config that cannot be used, before any ticket is read
    """
    config = load_config(root, registry)
    tickets, comments, problems = read_tickets(root)
    ids:    dict[str, list[str]]    = {}
    issues: dict[str, list[str]] = {}
    for name, (ticket, _) in tickets.items():
        ids.setdefault(ticket.id, []).append(name)
    for name, (ticket, text) in sorted(tickets.items()):
        stem = name[: -len(".yaml")]
        problems.extend(f"{name}: {problem}" for problem in ticket_problems(stem, ticket, text, config, ids, comments))
        if ticket.issue is not None:
            for key in (f"{ticket.issue['repo']}#{ticket.issue['number']}", ticket.issue["node"]):
                issues.setdefault(key, []).append(name)
    for ident, names in sorted(ids.items()):
        if len(names) > 1:
            problems.append(f"{', '.join(names)}: a duplicate id {ident}")
    named = set()
    for key, names in sorted(issues.items()):
        if len(names) > 1 and tuple(names) not in named:
            named.add(tuple(names))
            problems.append(f"{', '.join(names)}: two files naming one issue, {key}. Settle which ticket it is")
    for stem in sorted(set(comments) - {name[: -len(".yaml")] for name in tickets}):
        problems.append(f"{stem}{COMMENTS}: a comments file with no ticket beside it")
    return problems


def ticket_problems(
    stem: str,
    ticket: form.Ticket,
    text: str,
    config: Config,
    ids: dict[str, list[str]],
    comments: dict[str, str],
) -> list[str]:
    """
    Check one ticket's form and fields.

    Args:
        stem: its file's name without .yaml
        ticket: the ticket read
        text: its file's text
        config: the repo's config
        ids: every id read, by the files holding it
        comments: each comments file's text by its ticket's file stem

    Returns:
        list[str]: its problems
    """
    problems = []
    if form.dump(ticket) != text.replace("\r\n", "\n"):
        problems.append("not in the canonical form. Run fmt")
    if not slug(stem):
        problems.append("the file's name is not a slug, [a-z0-9][a-z0-9-]* of at most 64")
    if not slug(ticket.id):
        problems.append(f"id {ticket.id!r} is not a slug, [a-z0-9][a-z0-9-]* of at most 64")
    elif ticket.id != stem:
        problems.append(f"id {ticket.id} is not the file's name")
    if not ticket.title.strip():
        problems.append("the title is empty")
    elif ticket.issue is None and len(ticket.title) > TITLE_LIMIT:
        problems.append(f"a new ticket's title runs past {TITLE_LIMIT} characters")
    if ticket.about not in config.about:
        problems.append(f"about {ticket.about!r} is not a repo the config names")
    problems.extend(f"also names {repo!r}, not a repo name" for repo in ticket.also if not repo_name(repo))
    if ticket.kind not in KINDS:
        problems.append(f"kind {ticket.kind!r} is not one of {', '.join(KINDS)}")
    problems.extend(state_problems(ticket))
    problems.extend(label_problems(ticket, config))
    problems.extend(parent_problems(ticket, config, ids))
    problems.extend(issue_problems(ticket, config))
    problems.extend(after_problems(ticket, config, ids))
    problems.extend(base_problems(stem, ticket, comments))
    return problems


def after_problems(ticket: form.Ticket, config: Config, ids: dict[str, list[str]]) -> list[str]:
    """
    Check the board block's after, the nearest earlier card the config backs up on that board, <repo>/<id> with the
    config's own repo and an id a file here holds, never the ticket itself. A fork or a cycle stands, since pull --only
    writes a moved card's after without its neighbours'.

    Args:
        ticket: the ticket
        config: the repo's config
        ids: every id read

    Returns:
        list[str]: its problems
    """
    after = (ticket.board or {}).get("after")
    if after is None:
        return []
    repo, _, ident = after.partition("/")
    if repo != config.repo or ident not in ids or ident == ticket.id:
        return [f"board.after {after!r} is not {config.repo}/<the id of another ticket here>"]
    return []


def state_problems(ticket: form.Ticket) -> list[str]:
    """
    Check state and reason as one unit, open with no reason, closed with one of GitHub's.

    Args:
        ticket: the ticket

    Returns:
        list[str]: its problems
    """
    if ticket.state not in STATES:
        return [f"state {ticket.state!r} is not open or closed"]
    if ticket.state == "open" and ticket.reason is not None:
        return [f"an open ticket has the reason {ticket.reason!r}, which only a closed one has"]
    if ticket.state == "closed" and ticket.reason not in CLOSED_REASONS:
        return [f"reason {ticket.reason!r} is not completed, not_planned or duplicate"]
    return []


def label_problems(ticket: form.Ticket, config: Config) -> list[str]:
    """
    Check the labels, none empty, and a board: label, where one is carried, the one its about's board names.

    Args:
        ticket: the ticket
        config: the repo's config

    Returns:
        list[str]: its problems
    """
    problems = ["a label is empty"] if any(not label.strip() for label in ticket.labels) else []
    boards   = [label for label in ticket.labels if label.startswith(BOARD_LABEL)]
    expected = config.about.get(ticket.about)
    if len(boards) > 1:
        problems.append(f"more than one board: label, {', '.join(boards)}")
    elif boards and expected is not None and boards[0] != f"{BOARD_LABEL}{expected}":
        problems.append(f"the label {boards[0]} is not board:{expected}, the board the config gives {ticket.about}")
    return problems


def parent_problems(ticket: form.Ticket, config: Config, ids: dict[str, list[str]]) -> list[str]:
    """
    Check the parent, an id in this repo or <repo>/<id> in another, and one here that a file holds.

    Args:
        ticket: the ticket
        config: the repo's config
        ids: every id read

    Returns:
        list[str]: its problems
    """
    if ticket.parent is None:
        return []
    repo, _, ident = ticket.parent.rpartition("/")
    if (repo and not repo_name(repo)) or not slug(ident) or ticket.parent.count("/") > 1:
        return [f"parent {ticket.parent!r} is not <id> or <repo>/<id>"]
    if repo in ("", config.repo) and ident not in ids:
        return [f"parent {ticket.parent} is a ticket no file here holds"]
    if repo in ("", config.repo) and ident == ticket.id:
        return ["a ticket is its own parent"]
    return []


def issue_problems(ticket: form.Ticket, config: Config) -> list[str]:
    """
    Check the issue's identity against the config, its repo the config's and its URL its number's.

    Args:
        ticket: the ticket
        config: the repo's config

    Returns:
        list[str]: its problems
    """
    issue = ticket.issue
    if issue is None:
        return []
    if issue["repo"] != config.repo:
        return [f"issue.repo {issue['repo']} is not {config.repo}, the repo the config names"]
    url = f"https://github.com/{config.owner}/{config.repo}/issues/{issue['number']}"
    if issue["number"] < 1 or issue["url"].lower() != url.lower():
        return [f"issue.url {issue['url']} is not {url}"]
    if not issue["node"]:
        return ["issue.node is empty"]
    return []


def base_problems(stem: str, ticket: form.Ticket, comments: dict[str, str]) -> list[str]:
    """
    Check the files only pull writes, the board block and the comments file, against their bases in synced.

    Args:
        stem: the ticket's file stem
        ticket: the ticket
        comments: each comments file's text by its ticket's file stem

    Returns:
        list[str]: its problems
    """
    side = comments.get(stem)
    if ticket.synced is None:
        problems = []
        if ticket.board is not None:
            problems.append("a board block with no synced bases. Only pull writes board")
        if side is not None:
            problems.append(f"a {COMMENTS} file with no synced bases. Only pull writes comments")
        return problems
    problems = []
    if ticket.synced["board"] != form.board_digest(ticket.board):
        problems.append("board differs from its base, an edit by hand. Only pull writes board, run pull --only")
    expected = None if side is None else text_digest(side)
    if ticket.synced["comments"] != expected:
        problems.append(f"the {COMMENTS} file differs from its base. A comment is written on GitHub, run pull --only")
    return problems


def fmt(root: Path) -> tuple[list[str], list[str]]:
    """
    Rewrite every ticket file a worktree holds into the canonical form, changing no value.

    Args:
        root: the worktree

    Returns:
        tuple[list[str], list[str]]: the files rewritten, and the problems met, a file the reader cannot take among them
    """
    tickets, _, problems = read_tickets(root)
    written = []
    for name, (ticket, text) in sorted(tickets.items()):
        canonical = form.dump(ticket)
        if canonical != text:
            writable(root, name).write_bytes(canonical.encode("utf-8"))
            written.append(name)
    return written, problems
