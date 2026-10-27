"""
The stand in for GitHub the tickets tool's tests share, and the worktrees they make.

The stand in answers each named GraphQL query the tool's reader sends through gh's argument list, from the repos,
issues and boards a test gives it, and records every call, so a test reads which reads were made and in what order.
No test reaches GitHub. Every owner, repo, issue and board here is synthetic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS  = Path(__file__).resolve().parents[2] / "tools" / "claude-code"
GIT    = shutil.which("git")
OWNER  = "example-owner"
REPO   = "sample-app"
HOSTER = "sample-tickets"
BOARD  = "PVT_apps"

sys.path.insert(0, str(TOOLS))
written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
try:
    from kdf_tickets import commands, form
    from kdf_tickets.github import Reader
finally:
    sys.dont_write_bytecode = written


class FakeGitHub:
    """
    Answers the reader's named queries from the repos and boards a test gives it, and records each call.
    """
    def __init__(self) -> None:
        self.repos:          dict[str, dict] = {}
        self.boards:         dict[str, dict] = {}
        self.calls:          list[tuple[str, dict]] = []
        self.failing_boards: set[str] = set()
        self.rate_limited = 0


    def repo(self, name: str, private: bool = True) -> dict:
        self.repos[name] = {"private": private, "issues": []}
        return self.repos[name]


    def issue(self, repo: str, number: int, title: str = "", body: str = "A body.\n", **extra) -> dict:
        node = {
            "id": f"I_{repo}_{number}",
            "number": number,
            "url": f"https://github.com/{OWNER}/{repo}/issues/{number}",
            "title": title or f"Issue number {number}",
            "body": body,
            "state": "OPEN",
            "stateReason": None,
            "createdAt": "2026-07-12T10:00:00Z",
            "updatedAt": "2026-07-12T10:00:00Z",
            "labels": [],
            "assignees": [],
            "parent": None,
            "comments": [],
            "boards": [],
        }
        node.update(extra)
        self.repos[repo]["issues"].append(node)
        return node


    def board(self, node: str, number: int, title: str, cards: list[dict]) -> None:
        self.boards[node] = {"number": number, "title": title, "cards": cards}


    def run(self, args: list[str], stdin: str) -> subprocess.CompletedProcess[str]:
        assert args == ["api", "graphql", "--include", "--input", "-"], args
        request   = json.loads(stdin)
        operation = re.search(r"query (\w+)", request["query"]).group(1)
        variables = request["variables"]
        self.calls.append((operation, variables))
        if self.rate_limited:
            self.rate_limited -= 1
            return self._reply({"errors": [{"type": "RATE_LIMITED", "message": "limit"}]}, "Retry-After: 7")
        return self._reply(getattr(self, f"_{operation.lower()}")(variables))


    def _reply(self, body: dict, header: str = "") -> subprocess.CompletedProcess[str]:
        head = "HTTP/2.0 200 OK\n" + (f"{header}\n" if header else "")
        return subprocess.CompletedProcess([], 0, f"{head}\n{json.dumps(body)}", "")


    def _visibility(self, variables: dict) -> dict:
        repo = self.repos.get(variables["name"])
        if repo is None:
            return {"data": {"repository": None}}
        private = repo["private"]
        return {"data": {"repository": {"isPrivate": private, "visibility": "PRIVATE" if private else "PUBLIC"}}}


    def _issues(self, variables: dict) -> dict:
        issues = self.repos[variables["name"]]["issues"]
        start  = int(variables["after"] or 0)
        page   = issues[start : start + 100]
        nodes  = [self._issue_node(issue) for issue in page]
        more   = start + 100 < len(issues)
        info   = {"hasNextPage": more, "endCursor": str(start + 100)}
        return {"data": {"repository": {"issues": {"pageInfo": info, "nodes": nodes}}}}


    def _issue_node(self, issue: dict) -> dict:
        node = {key: issue[key] for key in issue if key not in ("labels", "assignees", "comments", "boards")}
        node["labels"] = {"totalCount": len(issue["labels"]), "nodes": [{"name": name} for name in issue["labels"]]}
        node["assignees"] = {
            "totalCount": len(issue["assignees"]),
            "nodes": [{"login": login} for login in issue["assignees"]],
        }
        node["comments"] = {
            "totalCount": len(issue["comments"]),
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": issue["comments"],
        }
        node["projectItems"] = {
            "totalCount": len(issue["boards"]),
            "nodes": [{"id": f"item_{board}", "project": {"id": board}} for board in issue["boards"]],
        }
        return node


    def _board(self, variables: dict) -> dict:
        if variables["id"] in self.failing_boards or variables["id"] not in self.boards:
            return {"errors": [{"type": "INSUFFICIENT_SCOPES", "message": "needs read:project"}]}
        board = self.boards[variables["id"]]
        info  = {"hasNextPage": False, "endCursor": None}
        items = {"pageInfo": info, "nodes": board["cards"]}
        return {"data": {"node": {"number": board["number"], "title": board["title"], "closed": False, "items": items}}}


    def operations(self) -> list[str]:
        return [operation for operation, _ in self.calls]


def card(repo: str, number: int, status: str = "Backlog", kind: str = "ISSUE", **fields) -> dict:
    """
    Make a board item node for an issue, a pull request or a draft.
    """
    values = [{"name": status, "field": {"name": "Status"}}]
    values += [{"name": value, "field": {"name": name.title()}} for name, value in fields.items()]
    if kind == "DRAFT_ISSUE":
        content = {"id": f"D_{number}", "title": "a draft"}
    else:
        content = {
            "id": f"I_{repo}_{number}",
            "number": number,
            "repository": {"name": repo, "owner": {"login": OWNER}},
        }
    return {
        "id": f"PVTI_{repo}_{number}",
        "type": kind,
        "isArchived": False,
        "updatedAt": "2026-07-12T11:00:00Z",
        "content": content,
        "fieldValues": {"nodes": values},
    }


def git(path: Path, *args: str) -> str:
    """
    Run git in a test's folder with fixed names and dates, every inherited GIT_ variable dropped.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com"})
    environment.update({"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
    environment.update({"GIT_AUTHOR_DATE": "2026-07-15T00:00:00Z", "GIT_COMMITTER_DATE": "2026-07-15T00:00:00Z"})
    done = subprocess.run([GIT, "-C", str(path), *args], check = True, capture_output = True, env = environment)
    return done.stdout.decode()


def registry(folder: Path) -> Path:
    """
    Write a boards' registry of two boards, apps and hosted.
    """
    boards = [
        {"key": "apps", "title": "Board apps", "existing_node_id": BOARD, "repos": [f"{OWNER}/{REPO}"]},
        {"key": "hosted", "title": "Board hosted", "existing_node_id": "PVT_hosted", "repos": [f"{OWNER}/{HOSTER}"]},
    ]
    path   = folder / "registry.json"
    path.write_text(json.dumps({"boards": boards}), encoding = "utf-8")
    return path


def worktree(tmp_path: Path, repo: str = REPO, about: dict | None = None, name: str = "worktree") -> Path:
    """
    Make a repo's worktree with an origin and its tickets config.
    """
    root = tmp_path / name
    (root / "docs" / "tickets").mkdir(parents = True)
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", f"https://github.com/{OWNER}/{repo}.git")
    config = {
        "format": 1,
        "owner": OWNER,
        "repo": repo,
        "about": about or {repo: {"board": "apps"}},
        "leave_out_labels": ["ops", "ai-triaged", "local-only"],
        "backup_age_days": 7,
        "read_only": False,
    }
    (root / "docs" / "tickets" / "config.json").write_text(json.dumps(config, indent = 2), encoding = "utf-8")
    return root


def tickets(root: Path) -> dict[str, form.Ticket]:
    """
    Read every ticket a worktree holds, by its stem.
    """
    folder = root / "docs" / "tickets"
    return {path.stem: form.load(path.read_text(encoding = "utf-8")) for path in sorted(folder.glob("*.yaml"))}


def rewrite(root: Path, ident: str, **changes) -> None:
    """
    Change a ticket's fields as a session would, written in the canonical form.
    """
    path   = root / "docs" / "tickets" / f"{ident}.yaml"
    ticket = form.load(path.read_text(encoding = "utf-8"))
    for name, value in changes.items():
        setattr(ticket, name, value)
    path.write_bytes(form.dump(ticket).encode("utf-8"))


def setup(tmp_path: Path, issues: int = 2) -> tuple[FakeGitHub, Path, Path, Reader]:
    """
    Make a stand in holding a repo with numbered issues on its board, the repo's worktree and a registry.
    """
    github = FakeGitHub()
    github.repo(REPO)
    cards = []
    for number in range(1, issues + 1):
        github.issue(REPO, number, title = f"Ticket number {number}", boards = [BOARD])
        cards.append(card(REPO, number, priority = "P2"))
    github.board(BOARD, 18, "Board apps", cards)
    return github, worktree(tmp_path), registry(tmp_path), Reader(run = github.run, sleep = lambda seconds: None)


def pull(root: Path, registry_path: Path, reader: Reader, **options) -> tuple[int, list[str]]:
    """
    Run pull against a worktree through the stand in.
    """
    return commands.pull(root, reader, registry_path, **options)


def plan(root: Path, registry_path: Path, reader: Reader) -> tuple[int, list[str]]:
    """
    Run plan against a worktree through the stand in.
    """
    return commands.plan(root, reader, registry_path)
