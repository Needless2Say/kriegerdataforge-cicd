"""
The read commands that reach GitHub or read the ticket files whole, plan, pull, find, prompt and ages.

Each command that reaches GitHub reads the repo's visibility first and refuses a repo GitHub calls public before any
other read (design 5.3), then makes every read before it writes anything, so a failed read leaves the files as they
were (5.5). pull writes inside the worktree's docs/tickets/ alone, and nothing here writes an issue or a board.
"""

from __future__ import annotations

# standard imports
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# third party imports
from kdf_tickets import form, sync
from kdf_tickets.check import COMMENTS, folder, read_tickets
from kdf_tickets.common import CLEAN, CONFLICT, FOUND, Refusal, git, slug
from kdf_tickets.config import REGISTRY, Config, load_config, parse_config
from kdf_tickets.github import Reader

# module constants
MODES          = ("only", "adopt", "backup")
DAY            = 86400
PROMPT_HEADING = "**Its design prompt.**"
PROMPT_BLOCK   = re.compile(r"```text\n(.*?)\n```", re.DOTALL)
PLAN_LINK      = re.compile(r"[\w./-]*docs/features/[\w.-]+/IMPLEMENTATION_PLAN\.md")


def current_files(root: Path) -> dict[str, sync.Current]:
    """
    Read a worktree's ticket files for a reconciliation, refusing a folder a reader cannot take.

    Args:
        root: the worktree

    Returns:
        dict[str, sync.Current]: each ticket by its stem

    Raises:
        Refusal: for a file that does not read, before anything reaches GitHub
    """
    tickets, comments, problems = read_tickets(root)
    if problems:
        raise Refusal(f"the tickets folder has files that do not read, {problems[0]}. Run check")
    current = {}
    for name, (ticket, text) in tickets.items():
        stem = name[: -len(".yaml")]
        current[stem] = sync.Current(ticket = ticket, text = text, comments = comments.get(stem))
    return current


def board_keys(config: Config, current: dict[str, sync.Current]) -> set[str]:
    """
    Name the boards a config's tickets sit on, every repo it keeps tickets about.

    Args:
        config: the repo's config
        current: its ticket files

    Returns:
        set[str]: the board keys
    """
    return set(config.about.values())


def reconcile(
    config: Config,
    current: dict[str, sync.Current],
    reader: Reader,
    adopt: bool,
    adopted: dict[int, str] | None = None,
    take: set[str] | None = None,
) -> sync.Result:
    """
    Read GitHub for a config, its visibility first, and reconcile the files with it.

    Args:
        config: the repo's config
        current: its ticket files
        reader: GitHub's reads
        adopt: whether an unmarked issue no file holds is adopted
        adopted: the adoption map
        take: the stems whose conflicts take GitHub's values

    Returns:
        sync.Result: the reconciliation

    Raises:
        Refusal: for a repo GitHub calls public, before any other read
    """
    if not reader.private(config.owner, config.repo):
        raise Refusal(
            f"{config.owner}/{config.repo} is public. A public repo keeps no tickets, they are held privately",
        )
    remote = sync.read_remote(reader, config, board_keys(config, current))
    return sync.reconcile(config, current, remote, adopt, adopted, take)


def plan(root: Path, reader: Reader, registry: Path = REGISTRY) -> tuple[int, list[str]]:
    """
    The dry run, each difference by field and side, the conflicts, the drafts and the issues off their boards.

    Args:
        root: the worktree
        reader: GitHub's reads
        registry: the boards' registry

    Returns:
        tuple[int, list[str]]: 0 in step, 1 with differences, 2 with a conflict, and the lines to print
    """
    config = load_config(root, registry)
    result = reconcile(config, current_files(root), reader, adopt = False)
    lines  = result.notes + result.refusals + result.differences + result.conflicts
    if result.conflicts:
        code = CONFLICT
    elif result.differences or result.refusals:
        code = FOUND
    else:
        code = CLEAN
    lines.append({CLEAN: "plan: in step", FOUND: "plan: differences", CONFLICT: "plan: a conflict"}[code])
    return code, lines


def pull(
    root: Path,
    reader: Reader,
    registry: Path = REGISTRY,
    mode: str | None = None,
    only: list[str] | None = None,
    take: bool = False,
    adoption_map: Path | None = None,
) -> tuple[int, list[str]]:
    """
    Bring GitHub into the files, by its mode, every read made before anything is written.

    Args:
        root: the worktree
        reader: GitHub's reads
        registry: the boards' registry
        mode: only, the named tickets alone, adopt, a repo's first pull, or backup, every ticket
        only: the ids for only
        take: settle the named tickets' conflicts with GitHub's values, with only
        adoption_map: a map of moved issues to the repos they came from, with adopt

    Returns:
        tuple[int, list[str]]: 0 written clean, 1 with issues refused, 2 with a conflict left, and the lines to print

    Raises:
        Refusal: for a pull with no mode, an id no file holds, an adopt once tickets exist, or a failed read
    """
    if mode not in MODES:
        raise Refusal("pull runs with --only, --adopt or --backup, never guessed from the branch")
    config  = load_config(root, registry)
    current = current_files(root)
    if mode == "adopt" and current:
        raise Refusal("the repo already holds tickets, so its pulls run with --backup or --only")
    if mode != "adopt" and adoption_map is not None:
        raise Refusal("an adoption map goes with --adopt alone")
    if mode != "only" and (only or take):
        raise Refusal("--take and the ids go with --only alone")
    named = set(only or [])
    for ident in sorted(named):
        if not slug(ident) or ident not in current:
            raise Refusal(f"{ident!r} is no ticket this repo's files hold")
    adopted = sync.read_map(adoption_map, config) if adoption_map is not None else {}
    result  = reconcile(
        config,
        current,
        reader,
        adopt = mode != "only",
        adopted = adopted,
        take = named if take else set(),
    )
    lines   = []
    for stem, entry in sorted(result.entries.items()):
        if (mode == "only" and stem not in named) or not entry.changed:
            continue
        write_entry(root, entry)
        lines.append(f"wrote {stem}.yaml")
    conflicts = [line for line in result.conflicts if mode != "only" or line.split(":")[0] in named]
    lines    += result.refusals + conflicts
    code = CONFLICT if conflicts else FOUND if result.refusals else CLEAN
    lines.append(f"pull: {len([line for line in lines if line.startswith('wrote ')])} files written")
    return code, lines


def write_entry(root: Path, entry: sync.Entry) -> None:
    """
    Write one ticket and its comments file, inside the worktree's docs/tickets/ alone.

    Args:
        root: the worktree
        entry: the ticket as the pull writes it

    Raises:
        Refusal: for a stem the slug pattern refuses, so no file is written outside the folder
    """
    if not slug(entry.stem):
        raise Refusal(f"{entry.stem!r} is not a slug, so no file is written for it")
    target = folder(root)
    (target / f"{entry.stem}.yaml").write_bytes(form.dump(entry.ticket).encode("utf-8"))
    side = target / f"{entry.stem}{COMMENTS}"
    if entry.comments is None:
        side.unlink(missing_ok = True)
    else:
        side.write_bytes(entry.comments.encode("utf-8"))


def find(
    root: Path,
    about: str | None = None,
    label: str | None = None,
    kind: str | None = None,
    state: str = "open",
) -> list[str]:
    """
    List tickets from the files alone, by about, label and kind.

    Args:
        root: the worktree
        about: the repo a ticket is about
        label: a label it carries
        kind: its kind
        state: open, closed or all

    Returns:
        list[str]: one line per ticket, its id, its issue and its title
    """
    tickets, _, _ = read_tickets(root)
    lines = []
    for name, (ticket, _) in sorted(tickets.items()):
        if state != "all" and ticket.state != state:
            continue
        if (
            about and ticket.about != about
        ) or (label and label not in ticket.labels) or (kind and ticket.kind != kind):
            continue
        where = f"{ticket.issue['repo']}#{ticket.issue['number']}" if ticket.issue else "not pushed"
        lines.append(f"{ticket.id}  {where}  {ticket.title}")
    return lines


def prompt(root: Path, ident: str) -> str:
    """
    Give a ticket's design prompt, or for one In Progress the plan whose last section is its build's prompt.

    Args:
        root: the worktree
        ident: the ticket's id

    Returns:
        str: the prompt, or where the build's prompt is

    Raises:
        Refusal: for an id no file holds, or a ticket whose body holds neither
    """
    path = folder(root) / f"{ident}.yaml"
    if not slug(ident) or not path.is_file():
        raise Refusal(f"{ident!r} is no ticket this repo's files hold")
    ticket = form.load(path.read_text(encoding = "utf-8"))
    if (ticket.board or {}).get("status") == "In Progress":
        link = PLAN_LINK.search(ticket.body)
        if link is None:
            raise Refusal(
                f"{ident} is In Progress and its body links no plan, docs/features/<folder>/" "IMPLEMENTATION_PLAN.md",
            )
        return f"{ident} is In Progress. Its build's prompt is the last section of {link.group()}"
    _, heading, rest = ticket.body.partition(PROMPT_HEADING)
    block = PROMPT_BLOCK.search(rest) if heading else None
    if block is None:
        raise Refusal(f"{ident}'s body holds no ```text block under {PROMPT_HEADING}")
    return block.group(1)


def main_files(clone: Path) -> tuple[str | None, dict[str, sync.Current]]:
    """
    Read a clone's tickets config and files at origin/main, never its working tree.

    Args:
        clone: the clone

    Returns:
        tuple: the config's text, None for a clone that keeps no tickets at its main, and each ticket by its stem
    """
    shown = git(clone, "show", "origin/main:docs/tickets/config.json")
    if shown.returncode != 0:
        return None, {}
    listed  = git(clone, "ls-tree", "--name-only", "origin/main", "docs/tickets/")
    names   = [line.rpartition("/")[2] for line in listed.stdout.splitlines()]
    texts   = {name: git(clone, "show", f"origin/main:docs/tickets/{name}").stdout for name in names}
    current = {}
    for name, text in texts.items():
        if name.endswith(".yaml"):
            stem = name[: -len(".yaml")]
            current[
                stem
            ] = sync.Current(ticket = form.load(text), text = text, comments = texts.get(f"{stem}{COMMENTS}"))
    return shown.stdout, current


def seconds(stamp: str) -> float:
    """
    Read one of GitHub's times as seconds since the epoch.

    Args:
        stamp: the time, such as 2026-07-12T10:00:00Z

    Returns:
        float: its seconds
    """
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def ages(
    workspace: Path,
    reader: Reader,
    registry: Path = REGISTRY,
    clock: Callable[[], float] = time.time,
) -> tuple[int, list[str]]:
    """
    List every clone under a folder with tickets, and the age of the oldest change on GitHub not yet in its main.

    Args:
        workspace: the folder whose clones are read
        reader: GitHub's reads
        registry: the boards' registry
        clock: the time now

    Returns:
        tuple[int, list[str]]: 1 when a repo is past its limit or cannot be read, else 0, and a line per repo
    """
    code, lines, now = CLEAN, [], clock()
    for clone in sorted(path for path in workspace.iterdir() if (path / ".git").exists()):
        text, current = main_files(clone)
        if text is None:
            continue
        try:
            config = parse_config(text, f"{clone.name}'s config.json at origin/main", registry)
            result = reconcile(config, current, reader, adopt = False)
        except (Refusal, form.FormError) as error:
            lines.append(f"{clone.name}  cannot be read, {error}")
            code = FOUND
            continue
        backup = git(clone, "log", "-1", "--format=%cI", "origin/main", "--", "docs/tickets/").stdout.strip()
        dated  = [seconds(backup if stamp == sync.ORDER else stamp) for stamp in result.stamps if stamp and (
            stamp != sync.ORDER or backup)]
        oldest = min(dated, default = now)
        days   = int(max(now - oldest, 0) // DAY)
        line   = f"{config.repo}  {days} days"
        if days > config.backup_age_days:
            line += f", past its limit of {config.backup_age_days} days. A backup pull is due"
            code = FOUND
        lines.append(line)
    return code, lines
