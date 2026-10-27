"""
The reconciliation plan, pull and ages share, GitHub's issues and boards set beside a repo's ticket files.

Each issue is matched to its file by its node id, then by the marker in its body. An unmarked issue no file holds is
adopted by a pull that adopts, its id a slug of its title made unique and its about from the adoption map, its board:
label, or the repo itself (design 5.4). Each matched ticket's issue fields are merged (design 5.5), its board block is
read whole from its card on its config's board, after naming the nearest earlier card this config backs up on that
board as <repo>/<id>, the config's own repo, every other card passed over, the owner's choice of 2026-10-27 (Round
Table 68), and its comments are set beside it. Every difference is kept with the GitHub time of the change it
carries, which ages reads. Nothing here writes a file or reaches GitHub, the reads being given to it whole.
"""

from __future__ import annotations

# standard imports
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# third party imports
from kdf_tickets import form, merge
from kdf_tickets.common import Refusal, slug, text_digest
from kdf_tickets.config import Config
from kdf_tickets.github import Board, Issue, Reader

# module constants
MARKER      = re.compile(r"\n*<!-- kdf-ticket: ([^\s>]*) -->\s*\Z")
BOARD_LABEL = "board:"
UNKNOWN     = object()
# the stamp of a difference in a card's place alone, which no GitHub time dates, since a drag leaves the cards whose
# after changes unmoved on GitHub, so ages dates it by the last backup merged on main, a bound that can only warn early
ORDER     = "order"
ISSUE_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/issues/([0-9]+)")
# an adopted issue's kind, from a label first, then its board Type, then feature
KIND_LABELS  = {
    "bug": "bug",
    "type:bug": "bug",
    "feature": "feature",
    "enhancement": "feature",
    "chore": "chore",
    "next-change": "next-change",
}
KIND_TYPES   = {
    "Bug": "bug",
    "Feature": "feature",
    "Feedback": "feature",
    "Chore": "chore",
    "Docs": "chore",
    "Infra": "chore",
}
COMMENT_HEAD = "<!-- kdf-comment node={node} author={author} at={at} -->"


@dataclass
class Remote:
    """
    What GitHub holds for one repo's config, its issues and the boards its tickets sit on by key.
    """
    issues: list[Issue]
    boards: dict[str, Board]


@dataclass
class Current:
    """
    One ticket file as it stands, its text and its comments file's text.
    """
    ticket:   form.Ticket
    text:     str
    comments: str | None


@dataclass
class Entry:
    """
    One ticket as a pull would write it, and whether that changes its files.
    """
    stem:     str
    ticket:   form.Ticket
    comments: str | None
    changed:  bool
    new:      bool = False


@dataclass
class Result:
    """
    The reconciliation, the tickets a pull would write, the differences and conflicts plan lists, the issues refused,
    lines that are notes alone, and the GitHub time of each change not yet in the files.
    """
    entries:     dict[str, Entry] = field(default_factory = dict)
    differences: list[str] = field(default_factory = list)
    conflicts:   list[str] = field(default_factory = list)
    refusals:    list[str] = field(default_factory = list)
    notes:       list[str] = field(default_factory = list)
    stamps:      list[str] = field(default_factory = list)


def split_marker(body: str) -> tuple[str | None, str]:
    """
    Take the hidden marker line off the end of an issue's body.

    Args:
        body: the body as GitHub holds it

    Returns:
        tuple[str | None, str]: the marker's id, None when the body has none, and the body without it
    """
    match = MARKER.search(body)
    if match is None:
        return None, body
    return match.group(1), body[: match.start()]


def slugify(title: str, number: int, taken: set[str]) -> str:
    """
    Make an adopted issue's id from its title, made unique by its number when the slug is taken.

    Args:
        title: the issue's title
        number: its number
        taken: the ids already held

    Returns:
        str: an id the slug pattern takes, not in taken

    Raises:
        Refusal: when even the numbered forms are taken
    """
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    base  = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:64].rstrip("-") or f"issue-{number}"
    for candidate in (base, f"{base[: 64 - len(str(number)) - 1].rstrip('-')}-{number}", f"issue-{number}"):
        if slug(candidate) and candidate not in taken:
            return candidate
    raise Refusal(f"issue #{number} cannot be given an id its repo does not already hold")


def read_map(path: Path, config: Config) -> dict[int, str]:
    """
    Read an adoption map, a moved issue's number in this repo to the repo it came from, design 5.4's moved.tsv.

    Args:
        path: the map, one line per issue, the source <repo>#<number>, its URL here and its old URL, tab separated
        config: the repo's config

    Returns:
        dict[int, str]: each issue's number here and its about

    Raises:
        Refusal: for a map that cannot be read, a line not of three columns, an issue of another repo, or a source
            repo the config does not name
    """
    try:
        lines = path.read_text(encoding = "utf-8").splitlines()
    except OSError as error:
        raise Refusal(f"the adoption map {path} cannot be read, {error}") from None
    adopted = {}
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        columns = line.split("\t")
        target  = ISSUE_URL.fullmatch(columns[1].strip()) if len(columns) == 3 else None
        source  = columns[0].partition("#")[0]
        if target is None or (target.group(1).lower(), target.group(2).lower()) != (
            config.owner.lower(),
            config.repo.lower(),
        ):
            raise Refusal(f"the adoption map's line {index} does not name an issue of {config.repo}")
        if source not in config.about:
            raise Refusal(f"the adoption map's line {index} names {source}, a repo the config does not name")
        adopted[int(target.group(3))] = source
    return adopted


def read_remote(reader: Reader, config: Config, keys: set[str]) -> Remote:
    """
    Read what GitHub holds for a config, every read made before anything is written, a failed one refusing.

    Args:
        reader: GitHub's reads
        config: the repo's config, its visibility already read
        keys: the board keys its tickets sit on

    Returns:
        Remote: the issues and the boards
    """
    issues = reader.issues(config.owner, config.repo)
    boards = {key: reader.board(config.boards[key].node) for key in sorted(keys)}
    return Remote(issues = issues, boards = boards)


def about_of(issue: Issue, config: Config, adopted: dict[int, str]) -> tuple[str | None, str]:
    """
    Find an adopted issue's about, from the adoption map, then its board: label, then the repo itself.

    Args:
        issue: the issue
        config: the repo's config
        adopted: the adoption map

    Returns:
        tuple[str | None, str]: the about, or None with the reason it was refused
    """
    if issue.number in adopted:
        return adopted[issue.number], ""
    boards = [label[len(BOARD_LABEL) :] for label in issue.labels if label.startswith(BOARD_LABEL)]
    if len(boards) > 1:
        return None, f"#{issue.number} has more than one board: label"
    if boards:
        repos = [repo for repo, key in config.about.items() if key == boards[0]]
        if len(repos) != 1:
            return None, f"#{issue.number}'s label board:{boards[0]} names no single repo the config keeps"
        return repos[0], ""
    if config.repo in config.about:
        return config.repo, ""
    return None, f"#{issue.number} has no marker and no board: label, and the adoption map does not name it"


def kind_of(issue: Issue, board: dict[str, Any] | None) -> str:
    """
    Choose an adopted issue's kind, from its labels, then its board Type, then feature.

    Args:
        issue: the issue
        board: its board block, if it is on its board

    Returns:
        str: the kind
    """
    for label in issue.labels:
        if label.lower() in KIND_LABELS:
            return KIND_LABELS[label.lower()]
    return KIND_TYPES.get((board or {}).get("type") or "", "feature")


def comments_text(issue: Issue) -> str | None:
    """
    Write an issue's comments file, each comment under its hidden header, a blank line between.

    Args:
        issue: the issue

    Returns:
        str | None: the file's text, None when the issue has no comments
    """
    if not issue.comments:
        return None
    blocks = []
    for comment in issue.comments:
        head = COMMENT_HEAD.format(node = comment.node, author = comment.author, at = comment.created)
        body = comment.body if comment.body.endswith("\n") else f"{comment.body}\n"
        blocks.append(f"{head}\n{body}")
    return "\n".join(blocks)


def comment_stamps(issue: Issue, current: str | None) -> list[str]:
    """
    Date the comments a file does not yet hold as GitHub has them, each by its own time, a deleted one by the issue's.

    Args:
        issue: the issue
        current: the comments file's text as it stands

    Returns:
        list[str]: the times of the changes not yet in the file
    """
    blocks = {}
    for chunk in re.split(r"\n(?=<!-- kdf-comment )", current or ""):
        match = re.match(r"<!-- kdf-comment node=(\S+) ", chunk)
        if match:
            blocks[match.group(1)] = chunk.rstrip("\n")
    stamps = []
    for comment in issue.comments:
        head  = COMMENT_HEAD.format(node = comment.node, author = comment.author, at = comment.created)
        block = f"{head}\n{comment.body}".rstrip("\n")
        if blocks.pop(comment.node, None) != block:
            stamps.append(comment.updated)
    if blocks:
        stamps.append(issue.updated)
    return stamps


class Reconciler:
    """
    One reconciliation of a repo's ticket files with what GitHub holds.
    """
    def __init__(self, config: Config, current: dict[str, Current], remote: Remote, held: set[str]) -> None:
        """
        Keep the config, the files, GitHub's reads and the issues the scan holds, and index the files by their issues.

        Args:
            config: the repo's config
            current: each ticket file by its stem
            remote: GitHub's reads
            held: the node ids of the issues the scan holds back, never adopted, named or written by this run
        """
        self.config  = config
        self.current = current
        self.remote  = remote
        self.held    = held
        self.result  = Result()
        self.by_node = {item.ticket.issue["node"]: stem for stem, item in current.items() if item.ticket.issue}
        # each matched or adopted issue, its stem and whether it is new, set before the boards are read, and each
        # adopted ticket's about
        self.matched:       dict[str, tuple[str, Issue, bool]] = {}
        self.adopted_about: dict[str, str] = {}


    def run(self, adopt: bool, adopted: dict[int, str], take: set[str]) -> Result:
        """
        Reconcile every issue and file.

        Args:
            adopt: True when an unmarked issue no file holds is adopted, False when it is listed alone
            adopted: the adoption map
            take: the stems whose conflicts are settled with GitHub's values

        Returns:
            Result: the reconciliation
        """
        issues  = sorted(self.remote.issues, key = lambda issue: issue.number)
        markers = {}
        for issue in issues:
            marker, _ = split_marker(issue.body)
            if marker is not None and not self.config.left_out(issue.labels):
                markers.setdefault(marker, []).append(issue.number)
        twice = {marker for marker, numbers in markers.items() if len(numbers) > 1}
        for marker in sorted(twice):
            numbers = ", ".join(f"#{number}" for number in markers[marker])
            self.result.refusals.append(f"{numbers} carry one marker, {marker}. The owner settles which is the ticket")
        seen = set()
        for issue in issues:
            seen.add(issue.node)
            if self.config.left_out(issue.labels):
                if issue.node in self.by_node:
                    self.result.differences.append(f"{self.by_node[issue.node]}: now left out by its labels, kept")
                continue
            marker, _ = split_marker(issue.body)
            if (marker is not None and marker in twice) or (issue.node in self.held and issue.node not in self.by_node):
                continue
            self.match(issue, marker, adopt, adopted)
        for stem, item in sorted(self.current.items()):
            if item.ticket.issue is None:
                self.result.differences.append(f"{stem}: not yet pushed, no issue holds it")
            elif item.ticket.issue["node"] not in seen:
                self.result.differences.append(f"{stem}: its issue is gone from GitHub, the file kept")
        for node, (stem, issue, new) in sorted(self.matched.items(), key = lambda pair: pair[1][0]):
            # a held ticket a file already holds keeps its file and its committed id, which other tickets still name
            if node in self.held:
                continue
            self.result.entries[stem] = self.entry(stem, issue, new, stem in take)
        self.board_notes()
        return self.result


    def match(self, issue: Issue, marker: str | None, adopt: bool, adopted: dict[int, str]) -> None:
        """
        Match one issue to its file, or adopt it, or list it.

        Args:
            issue: the issue
            marker: its marker's id, if it has one
            adopt: whether an unmatched issue is adopted
            adopted: the adoption map
        """
        if marker is not None and not slug(marker):
            self.result.refusals.append(f"#{issue.number}'s marker is not a slug, so it names no file")
            return
        stem = self.by_node.get(issue.node)
        if stem is None and marker is not None and marker in self.current:
            held = self.current[marker].ticket.issue
            if held is not None:
                self.result.refusals.append(f"#{issue.number}'s marker names {marker}, whose file holds another issue")
                return
            stem = marker
        if stem is not None:
            self.matched[issue.node] = (stem, issue, False)
            return
        if not adopt:
            self.result.differences.append(f"#{issue.number}: a new issue, adopted by the next pull --backup")
            self.result.stamps.append(issue.created)
            return
        about, reason = about_of(issue, self.config, adopted)
        if about is None:
            self.result.refusals.append(reason)
            return
        taken = set(self.current) | {item[0] for item in self.matched.values()}
        stem  = marker if marker is not None and marker not in taken else slugify(issue.title, issue.number, taken)
        self.matched[issue.node] = (stem, issue, True)
        self.adopted_about[stem] = about


    def about_of_stem(self, stem: str) -> str:
        """
        Give a matched or adopted ticket's about.

        Args:
            stem: the ticket's stem

        Returns:
            str: its about
        """
        return self.adopted_about.get(stem) or self.current[stem].ticket.about


    def name(self, node: str | None, key: str) -> str | None:
        """
        Name a card's issue as <repo>/<id> when this config backs it up on the board named, else None, so another
        repo's issue, an issue left out and this config's ticket bound to another board are passed over.

        Args:
            node: the card's issue's node id
            key: the board's key

        Returns:
            str | None: its name, the config's own repo and the ticket's id
        """
        if node is None or node not in self.matched:
            return None
        stem = self.matched[node][0]
        if self.config.about.get(self.about_of_stem(stem)) != key:
            return None
        return f"{self.config.repo}/{stem}"


    def board_block(self, issue: Issue, key: str) -> tuple[dict[str, Any] | None, str | None]:
        """
        Read an issue's board block from its card on its config's board, after the nearest earlier card this config
        backs up on that board.

        Args:
            issue: the issue
            key: its board's key

        Returns:
            tuple: the block, None when the issue is off its board, and its card's time
        """
        cards = self.remote.boards[key].cards
        above = None
        for card in cards:
            if card.node == issue.node and card.kind == "ISSUE":
                return {**card.fields, "after": above}, card.updated
            named = self.name(card.node, key) if card.kind == "ISSUE" else None
            if named is not None:
                above = named
        return None, None


    def parent_of(self, issue: Issue) -> Any:
        """
        Name an issue's parent as a ticket names one, its id when a ticket of this repo holds it.

        Args:
            issue: the issue

        Returns:
            Any: the parent's id, None for no parent, UNKNOWN for one in another repo or left out, which no read here
                names
        """
        if issue.parent is None:
            return None
        repo, node, _ = issue.parent
        if repo != self.config.repo or node not in self.matched:
            return UNKNOWN
        return self.matched[node][0]


    def entry(self, stem: str, issue: Issue, new: bool, take: bool) -> Entry:
        """
        Build one ticket as a pull would write it, and record its differences.

        Args:
            stem: its file's stem
            issue: its issue
            new: True for an issue adopted by this pull
            take: True to settle its conflicts with GitHub's values

        Returns:
            Entry: the ticket, its comments and whether its files change
        """
        _, body = split_marker(issue.body)
        parent  = self.parent_of(issue)
        current = self.current.get(stem)
        about   = self.adopted_about[stem] if new else current.ticket.about
        key     = self.config.about.get(about)
        board, card_time = self.board_block(issue, key) if key in self.remote.boards else (None, None)
        comments = comments_text(issue)
        if parent is UNKNOWN:
            self.result.differences.append(f"{stem}: its parent on GitHub is an issue no read names, kept")
        if board is None and key in self.remote.boards:
            self.result.differences.append(f"{stem}: off its board, {self.remote.boards[key].title}")
        if new:
            ticket        = form.Ticket(
                id = stem,
                title = issue.title,
                about = about,
                kind = kind_of(issue, board),
                state = issue.state,
                reason = issue.reason,
                labels = list(issue.labels),
                assignees = list(issue.assignees),
                parent = None if parent is UNKNOWN else parent,
                issue = {"repo": self.config.repo, "number": issue.number, "node": issue.node, "url": issue.url},
                board = board,
                body = body,
            )
            ticket.synced = form.synced_from(ticket, comments)
            self.result.stamps.append(issue.created)
            return Entry(stem, ticket, comments, changed = True, new = True)
        return self.merged(stem, issue, body, parent, board, card_time, comments, take)


    def merged(
        self,
        stem: str,
        issue: Issue,
        body: str,
        parent: Any,
        board: dict[str, Any] | None,
        card_time: str | None,
        comments: str | None,
        take: bool,
    ) -> Entry:
        """
        Merge a matched ticket's issue fields, take its board block and comments whole, and record each difference.

        Args:
            stem: its file's stem
            issue: its issue
            body: the issue's body without its marker
            parent: its parent named, or UNKNOWN
            board: its board block as GitHub holds it
            card_time: its card's time
            comments: its comments file as GitHub holds it
            take: True to settle its conflicts with GitHub's values

        Returns:
            Entry: the ticket a pull writes
        """
        current = self.current[stem]
        file    = current.ticket
        base    = file.synced or {key: None for key in form.SYNCED_KEYS}
        fields  = [
            merge.merge_text("title", file.title, issue.title, base["title"], take),
            merge.merge_text("body", file.body, body, base["body"], take),
            merge.merge_value(
                "state",
                (file.state, file.reason),
                (issue.state, issue.reason),
                (base["state"], base["reason"]),
                take,
            ),
            merge.merge_set("labels", file.labels, issue.labels, base["labels"] or []),
            merge.merge_set("assignees", file.assignees, issue.assignees, base["assignees"] or []),
        ]
        if parent is not UNKNOWN:
            fields.append(merge.merge_value("parent", file.parent, parent, base["parent"], take))
        ticket = form.Ticket(**{name: getattr(file, name) for name in form.ORDER})
        synced = dict(base)
        for result in fields:
            self.record(stem, result, issue.updated)
            if result.name == "state":
                ticket.state, ticket.reason = result.value
                synced["state"], synced["reason"] = result.base
            elif result.name in ("title", "body"):
                setattr(ticket, result.name, result.value)
                synced[result.name] = result.base
            else:
                setattr(ticket, result.name, result.value)
                synced[result.name] = result.base
        if board != file.board:
            self.result.differences.append(f"{stem}: board, GitHub's to pull")
            self.result.stamps.append(ORDER if self.order_alone(file.board, board) else card_time or issue.updated)
        if comments != current.comments:
            self.result.differences.append(f"{stem}: comments, GitHub's to pull")
            self.result.stamps.extend(comment_stamps(issue, current.comments))
        ticket.board = board
        synced["board"] = form.board_digest(board)
        synced["comments"] = None if comments is None else text_digest(comments)
        ticket.synced = synced
        changed       = form.dump(ticket) != current.text.replace("\r\n", "\n") or comments != current.comments
        return Entry(stem, ticket, comments, changed = changed)


    def order_alone(self, saved: dict[str, Any] | None, read: dict[str, Any] | None) -> bool:
        """
        Say whether a board block differs only in its after, a card's place, which a drag of another card changes with
        this card unmoved on GitHub, so its own time does not date it.

        Args:
            saved: the file's board block
            read: GitHub's

        Returns:
            bool: True for such a difference
        """
        if saved is None or read is None:
            return False
        return {**saved, "after": None} == {**read, "after": None}


    def record(self, stem: str, result: merge.Merged, updated: str) -> None:
        """
        Record one field's outcome as plan lists it, and the time of a change GitHub holds that the file does not.

        Args:
            stem: the ticket's stem
            result: the field's merge
            updated: the issue's last change on GitHub
        """
        if result.outcome == merge.PUSH:
            self.result.differences.append(f"{stem}: {result.name}, the file's to push")
        elif result.outcome == merge.PULL:
            self.result.differences.append(f"{stem}: {result.name}, GitHub's to pull")
            self.result.stamps.append(updated)
        elif result.outcome == merge.BOTH:
            self.result.differences.append(f"{stem}: {result.name}, GitHub's to pull")
            self.result.differences.append(f"{stem}: {result.name}, the file's to push")
            self.result.stamps.append(updated)
        elif result.outcome == merge.CONFLICT:
            self.result.conflicts.append(
                f"{stem}: {result.name}, a conflict, changed in the file and on GitHub. Settle it with "
                f"pull --only {stem} --take"
            )
            self.result.stamps.append(updated)


    def board_notes(self) -> None:
        """
        List each board's drafts, each issue's items on a board its config does not give it, and pull request items.
        """
        names = {board.node: f"{board.title}, number {board.number}" for board in self.remote.boards.values()}
        known = {board.node: board.title for board in self.config.boards.values()}
        for key, board in sorted(self.remote.boards.items()):
            self.result.notes.append(f"board {key}: {names[board.node]}")
            drafts = sum(1 for card in board.cards if card.kind == "DRAFT_ISSUE")
            pulls  = sum(1 for card in board.cards if card.kind == "PULL_REQUEST")
            if drafts:
                self.result.differences.append(f"board {key}: {drafts} draft items, for the owner to convert")
            if pulls:
                self.result.notes.append(f"board {key}: {pulls} pull request items")
        for node, (stem, issue, _) in sorted(self.matched.items(), key = lambda pair: pair[1][0]):
            if node in self.held:
                continue
            about = self.result.entries[stem].ticket.about
            own   = self.config.boards[self.config.about[about]].node if about in self.config.about else None
            for other in issue.boards:
                if other != own:
                    self.result.differences.append(f"{stem}: also on {known.get(other, other)}, a board not its own")


def reconcile(
    config: Config,
    current: dict[str, Current],
    remote: Remote,
    adopt: bool,
    adopted: dict[int, str] | None = None,
    take: set[str] | None = None,
    held: set[str] | None = None,
) -> Result:
    """
    Reconcile a repo's ticket files with what GitHub holds.

    Args:
        config: the repo's config
        current: each ticket file by its stem
        remote: GitHub's reads
        adopt: True when an unmarked issue no file holds is adopted
        adopted: the adoption map, a moved issue's number to its about
        take: the stems whose conflicts are settled with GitHub's values
        held: the node ids of the issues the scan holds back

    Returns:
        Result: the reconciliation
    """
    return Reconciler(config, current, remote, held or set()).run(adopt, adopted or {}, take or set())
