"""
The tickets tool's one way to read GitHub, gh run with an argument list and a GraphQL request on its input, never
through a shell, and the reads it makes, a repo's visibility, its issues with their comments and board items, and a
board's items in their order.

Every read pages a hundred items a query inside the tool (design 5.7). A rate limit reply is waited out, its
Retry-After or its reset time, and the read sent again, since a read changes nothing. Nothing here writes.
"""

from __future__ import annotations

# standard imports
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# third party imports
from kdf_tickets.common import Refusal

# module constants
# how many times a rate limited read is sent again, and the longest wait taken for one, in seconds
RETRIES   = 5
LONGEST   = 3700
SCOPE_FIX = "The login lacks read:project. Ask the owner to run gh auth refresh -h github.com -s read:project"
# the board's single select fields a ticket's board block holds, by their names on the board
FIELDS = {"Status": "status", "Priority": "priority", "Type": "type", "Severity": "severity"}

VISIBILITY = """
query Visibility($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { isPrivate visibility }
}
"""
ISSUES     = """
query Issues($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id number url title body state stateReason createdAt updatedAt
        labels(first: 100) { totalCount nodes { name } }
        assignees(first: 100) { totalCount nodes { login } }
        parent { id number repository { name owner { login } } }
        comments(first: 100) {
          totalCount pageInfo { hasNextPage endCursor }
          nodes { id author { login } createdAt updatedAt body }
        }
        projectItems(first: 20, includeArchived: false) { totalCount nodes { id project { id closed } } }
      }
    }
  }
}
"""
COMMENTS   = """
query Comments($id: ID!, $after: String) {
  node(id: $id) {
    ... on Issue {
      comments(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id author { login } createdAt updatedAt body }
      }
    }
  }
}
"""
BOARD      = """
query Board($id: ID!, $after: String) {
  node(id: $id) {
    ... on ProjectV2 {
      number title closed
      items(first: 100, after: $after, orderBy: {field: POSITION, direction: ASC}) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id type isArchived updatedAt
          content {
            ... on Issue { id number repository { name owner { login } } }
            ... on PullRequest { id number repository { name owner { login } } }
            ... on DraftIssue { id title }
          }
          fieldValues(first: 30) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2SingleSelectField { name } } }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen = True)
class Comment:
    """
    One comment on an issue, as GitHub holds it.
    """
    node:    str
    author:  str
    created: str
    updated: str
    body:    str


@dataclass
class Issue:
    """
    One issue as GitHub holds it, its body with carriage return and line feed pairs read as line feeds.
    """
    node:      str
    number:    int
    url:       str
    title:     str
    body:      str
    state:     str
    reason:    str | None
    labels:    list[str]
    assignees: list[str]
    parent:    tuple[str, str, int] | None
    created:   str
    updated:   str
    comments: list[Comment] = field(default_factory = list)
    boards:   list[str] = field(default_factory = list)


@dataclass(frozen = True)
class Card:
    """
    One item on a board, the issue, pull request or draft it holds, and its single select fields by the board block's
    keys.
    """
    item:    str
    kind:    str
    node:    str | None
    repo:    str | None
    number:  int | None
    fields:  dict[str, str | None]
    updated: str


@dataclass(frozen = True)
class Board:
    """
    One board read by its pinned node id, its number and title from GitHub, and its cards in their order.
    """
    node:   str
    number: int
    title:  str
    cards:  list[Card]


def run_gh(args: list[str], stdin: str) -> subprocess.CompletedProcess[str]:
    """
    Run gh with an argument list, never through a shell, its request on its input.

    Args:
        args: gh's arguments
        stdin: what gh reads

    Returns:
        subprocess.CompletedProcess[str]: gh's result, never checked here

    Raises:
        Refusal: for a machine with no gh on its path
    """
    try:
        return subprocess.run(
            ["gh", *args],
            input = stdin,
            capture_output = True,
            text = True,
            encoding = "utf-8",
            errors = "replace",
            check = False,
        )
    except FileNotFoundError:
        raise Refusal("gh is not on this machine's path. The tool reads GitHub through gh") from None


def split_reply(text: str) -> tuple[int, dict[str, str], str]:
    """
    Split a reply gh printed with --include into its status, its headers and its body.

    Args:
        text: what gh printed

    Returns:
        tuple[int, dict[str, str], str]: the status, 0 when none was printed, the headers in lower case, and the body
    """
    normal = text.replace("\r\n", "\n")
    if not normal.startswith("HTTP/"):
        return 0, {}, text
    head, _, body = normal.partition("\n\n")
    lines = head.split("\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        status = 0
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


class Reader:
    """
    GitHub's reads, through gh by default or through a stand in a test passes.
    """
    def __init__(
        self,
        run: Callable[[list[str], str], subprocess.CompletedProcess[str]] = run_gh,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """
        Keep the runner, the sleep and the clock a rate limit wait uses.

        Args:
            run: runs gh with an argument list and an input
            sleep: waits a number of seconds
            clock: the time now, in seconds since the epoch
        """
        self.run   = run
        self.sleep = sleep
        self.clock = clock


    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """
        Send one GraphQL read and give its data, waiting out a rate limit reply.

        Args:
            query: the query, a named operation
            variables: its variables

        Returns:
            dict[str, Any]: the reply's data

        Raises:
            Refusal: for a read GitHub refused or answered with errors, a missing scope named with its fix
        """
        request = json.dumps({"query": query, "variables": variables})
        for _ in range(RETRIES + 1):
            done = self.run(["api", "graphql", "--include", "--input", "-"], request)
            status, headers, body = split_reply(done.stdout)
            try:
                reply = json.loads(body) if body.strip() else {}
            except ValueError:
                reply = {}
            wait = self.rate_wait(status, headers, reply)
            if wait is not None:
                print(f"kdf-tickets: rate limited, waiting {int(wait)} seconds", file = sys.stderr)
                self.sleep(wait)
                continue
            errors = reply.get("errors") if isinstance(reply, dict) else None
            if errors:
                text = "; ".join(str(error.get("message", error)) for error in errors)
                if any(error.get("type") == "INSUFFICIENT_SCOPES" for error in errors) or "read:project" in text:
                    raise Refusal(f"{SCOPE_FIX}. GitHub said {text}")
                raise Refusal(f"GitHub refused a read, {text}")
            if done.returncode != 0 or not isinstance(reply, dict) or "data" not in reply:
                message = (done.stderr or body).strip()[:300]
                raise Refusal(f"gh could not read GitHub, {message or 'no answer'}")
            return reply["data"]
        raise Refusal(f"GitHub's rate limit held through {RETRIES} waits. Run the command again later")


    def rate_wait(self, status: int, headers: dict[str, str], reply: Any) -> float | None:
        """
        Say how long a rate limited reply asks to wait, None for a reply that is not one.

        Args:
            status: the reply's status
            headers: its headers
            reply: its body read

        Returns:
            float | None: the seconds to wait, at least one and at most LONGEST
        """
        errors  = reply.get("errors", []) if isinstance(reply, dict) else []
        limited = any(isinstance(error, dict) and error.get("type") == "RATE_LIMITED" for error in errors)
        limited = limited or (
            status in (403, 429) and ("retry-after" in headers or headers.get("x-ratelimit-remaining") == "0")
        )
        if not limited:
            return None
        if headers.get("retry-after", "").isdigit():
            seconds = float(headers["retry-after"])
        elif headers.get("x-ratelimit-reset", "").isdigit():
            seconds = float(headers["x-ratelimit-reset"]) - self.clock() + 1
        else:
            seconds = 60.0
        return min(max(seconds, 1.0), LONGEST)


    def private(self, owner: str, repo: str) -> bool:
        """
        Say whether GitHub calls a repo private, the one read made before any other.

        Args:
            owner: the repo's owner
            repo: its name

        Returns:
            bool: True for a private repo

        Raises:
            Refusal: for a repo GitHub does not show this login
        """
        data       = self.graphql(VISIBILITY, {"owner": owner, "name": repo})
        repository = data.get("repository")
        if repository is None:
            raise Refusal(f"GitHub shows no repo {owner}/{repo} to this login")
        return repository.get("isPrivate") is True and repository.get("visibility") == "PRIVATE"


    def issues(self, owner: str, repo: str) -> list[Issue]:
        """
        Read every issue of a repo, open and closed, with its comments and the boards it is on.

        Args:
            owner: the repo's owner
            repo: its name

        Returns:
            list[Issue]: the issues, oldest first

        Raises:
            Refusal: for an issue with more than a hundred labels or assignees, which one query cannot hold
        """
        issues: list[Issue] = []
        after = None
        while True:
            data       = self.graphql(ISSUES, {"owner": owner, "name": repo, "after": after})
            connection = data["repository"]["issues"]
            for node in connection["nodes"]:
                for kind in ("labels", "assignees"):
                    if node[kind]["totalCount"] > 100:
                        raise Refusal(f"{repo}#{node['number']} has more than 100 {kind}")
                issue          = make_issue(node)
                issue.comments = [make_comment(item) for item in node["comments"]["nodes"]]
                pages          = node["comments"]["pageInfo"]
                while pages["hasNextPage"]:
                    more = self.graphql(COMMENTS, {"id": node["id"], "after": pages["endCursor"]})["node"]["comments"]
                    issue.comments.extend(make_comment(item) for item in more["nodes"])
                    pages = more["pageInfo"]
                issues.append(issue)
            if not connection["pageInfo"]["hasNextPage"]:
                return issues
            after = connection["pageInfo"]["endCursor"]


    def board(self, node: str) -> Board:
        """
        Read a board by its pinned node id, its number and title, and its cards in their order on the board.

        Args:
            node: the board's node id

        Returns:
            Board: the board

        Raises:
            Refusal: for a node that is no board this login reads, so a pull never writes an empty board block
        """
        cards: list[Card] = []
        number, title, after = 0, "", None
        while True:
            data    = self.graphql(BOARD, {"id": node, "after": after})
            project = data.get("node")
            if not project or "items" not in project:
                raise Refusal(f"the board {node} cannot be read. {SCOPE_FIX}, or check the registry's node id")
            if project.get("closed"):
                raise Refusal(f"the board {project['title']} is closed, and a closed board is never backed up. "
                              "The owner reopens it or the config names an open one")
            number, title = project["number"], project["title"]
            connection = project["items"]
            cards.extend(make_card(item) for item in connection["nodes"] if not item.get("isArchived"))
            if not connection["pageInfo"]["hasNextPage"]:
                return Board(node = node, number = number, title = title, cards = cards)
            after = connection["pageInfo"]["endCursor"]


def make_comment(node: dict[str, Any]) -> Comment:
    """
    Make a comment from its GraphQL node, a deleted author read as ghost, as GitHub shows one.

    Args:
        node: the comment's node

    Returns:
        Comment: the comment
    """
    author = (node.get("author") or {}).get("login") or "ghost"
    return Comment(
        node = node["id"],
        author = author,
        created = node["createdAt"],
        updated = node.get("updatedAt") or node["createdAt"],
        body = node["body"].replace("\r\n", "\n"),
    )


def make_issue(node: dict[str, Any]) -> Issue:
    """
    Make an issue from its GraphQL node, state and reason one unit, an open issue holding no reason.

    Args:
        node: the issue's node

    Returns:
        Issue: the issue, its comments not yet read
    """
    state  = node["state"].lower()
    reason = (node.get("stateReason") or "").lower() or None
    parent = node.get("parent")
    return Issue(
        node = node["id"],
        number = node["number"],
        url = node["url"],
        title = node["title"],
        body = node["body"].replace("\r\n", "\n"),
        state = state,
        reason = None if state == "open" else reason,
        labels = sorted(label["name"] for label in node["labels"]["nodes"]),
        assignees = sorted(user["login"] for user in node["assignees"]["nodes"]),
        parent = None if not parent else (parent["repository"]["name"], parent["id"], parent["number"]),
        created = node["createdAt"],
        updated = node["updatedAt"],
        # a closed board is never backed up, so an issue's item on one is passed over (D-091)
        boards = [item["project"]["id"] for item in node["projectItems"]["nodes"] if not item["project"].get("closed")],
    )


def make_card(node: dict[str, Any]) -> Card:
    """
    Make a card from its board item node, its single select fields by the board block's keys.

    Args:
        node: the item's node

    Returns:
        Card: the card
    """
    content = node.get("content") or {}
    fields: dict[str, str | None] = {key: None for key in FIELDS.values()}
    for value in node.get("fieldValues", {}).get("nodes", []):
        name = ((value or {}).get("field") or {}).get("name")
        if name in FIELDS:
            fields[FIELDS[name]] = value.get("name")
    repository = content.get("repository") or {}
    return Card(
        item = node["id"],
        kind = node.get("type", "ISSUE"),
        node = content.get("id"),
        repo = repository.get("name"),
        number = content.get("number"),
        fields = fields,
        updated = node.get("updatedAt", ""),
    )
