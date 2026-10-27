"""
A repo's docs/tickets/config.json and the boards' registry it names, read and checked before any ticket is.

The config names the repo the tool runs in, which must be the worktree's origin, and each repo it keeps tickets about
with that repo's board, a key of cicd's scripts/projects_registry.json, all from its data and none from this code
(design 5.3). A config this release does not know, a key it lacks or a value of the wrong type is refused.
"""

from __future__ import annotations

# standard imports
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# third party imports
from kdf_tickets.common import LOGIN, Refusal, git, repo_name

# module constants
FORMATS  = (1,)
REQUIRED = ("format", "owner", "repo", "about", "leave_out_labels", "backup_age_days", "read_only")
OPTIONAL = ("allow",)
# the checkout this package sits in, three folders up, and its boards' registry
CHECKOUT = Path(__file__).resolve().parents[3]
REGISTRY = CHECKOUT / "scripts" / "projects_registry.json"
# an origin GitHub serves, over HTTPS or SSH, its owner and repo
ORIGIN = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?")


@dataclass(frozen = True)
class Board:
    """
    One board of the registry, its key, title and pinned node id, its number read from GitHub at each run.
    """
    key:   str
    title: str
    node:  str


@dataclass(frozen = True)
class Config:
    """
    A repo's tickets config, checked, with the registry's boards it names.
    """
    owner:            str
    repo:             str
    about:            dict[str, str]
    leave_out_labels: tuple[str, ...]
    backup_age_days:  int
    read_only:        bool
    boards:           dict[str, Board]
    allow:            dict[str, Any] = field(default_factory = dict)


    def left_out(self, labels: list[str]) -> bool:
        """
        Say whether an issue's labels leave it out of the tickets, a label starting with a leave_out_labels entry.

        Args:
            labels: the issue's labels

        Returns:
            bool: True when any label starts with an entry
        """
        return any(label.startswith(prefix) for label in labels for prefix in self.leave_out_labels)


def load_registry(path: Path = REGISTRY) -> dict[str, Board]:
    """
    Read the boards' registry, every board by its key.

    Args:
        path: the registry, cicd's own by default

    Returns:
        dict[str, Board]: the boards

    Raises:
        Refusal: for a registry that cannot be read or holds a board without its key, title or node id
    """
    try:
        data = json.loads(path.read_text(encoding = "utf-8"))
    except (OSError, ValueError) as error:
        raise Refusal(f"the boards' registry {path} cannot be read, {error}") from None
    boards = {}
    for entry in data.get("boards", []):
        key, title, node = entry.get("key"), entry.get("title"), entry.get("existing_node_id")
        # a board the owner's provisioning has yet to make holds no node id, and a config naming it is refused
        if not all(isinstance(value, str) and value for value in (key, title)) or not (
            node is None or (isinstance(node, str) and node)
        ):
            raise Refusal(f"the boards' registry {path} holds a board without its key or title, or a bad node id")
        boards[key] = Board(key = key, title = title, node = node or "")
    return boards


def origin(root: Path) -> tuple[str, str]:
    """
    Read the owner and repo of a worktree's origin.

    Args:
        root: the worktree

    Returns:
        tuple[str, str]: the owner and the repo

    Raises:
        Refusal: for a worktree with no origin, or one GitHub does not serve
    """
    done = git(root, "remote", "get-url", "origin")
    url  = done.stdout.strip()
    if done.returncode != 0 or not url:
        raise Refusal(f"{root} has no origin. Run the tool against a worktree of the repo")
    match = ORIGIN.fullmatch(url)
    if match is None:
        raise Refusal(f"{root}'s origin is not a GitHub repo the tool reads")
    return match.group(1), match.group(2)


def load_config(root: Path, registry: Path = REGISTRY) -> Config:
    """
    Read and check a worktree's tickets config against the registry and the worktree's origin.

    Args:
        root: the worktree
        registry: the boards' registry

    Returns:
        Config: the config

    Raises:
        Refusal: naming what is wrong with it
    """
    path = root / "docs" / "tickets" / "config.json"
    try:
        text = path.read_text(encoding = "utf-8")
    except FileNotFoundError:
        raise Refusal(f"{path} is missing. A repo adopts by a pull request adding its config.json") from None
    except OSError as error:
        raise Refusal(f"{path} cannot be read, {error}") from None
    config = parse_config(text, str(path), registry)
    owner, repo = origin(root)
    if (owner.lower(), repo.lower()) != (config.owner.lower(), config.repo.lower()):
        raise Refusal(
            f"{path} names {config.owner}/{config.repo} but the worktree's origin is {owner}/{repo}. A config "
            "copied from another repo is rewritten for this one"
        )
    return config


def parse_config(text: str, path: str, registry: Path = REGISTRY) -> Config:
    """
    Read and check a config's text against the registry, its origin left to the caller.

    Args:
        text: the config's text
        path: where it was read, for the messages
        registry: the boards' registry

    Returns:
        Config: the config

    Raises:
        Refusal: naming what is wrong with it
    """
    try:
        data = json.loads(text)
    except ValueError as error:
        raise Refusal(f"{path} cannot be read, {error}") from None
    if not isinstance(data, dict):
        raise Refusal(f"{path} is not a JSON object")
    if data.get("format") not in FORMATS or isinstance(data.get("format"), bool):
        raise Refusal(f"{path} has format {data.get('format')!r}, which this release does not know")
    unknown = sorted(set(data) - set(REQUIRED) - set(OPTIONAL))
    missing = [key for key in REQUIRED if key not in data]
    if unknown or missing:
        raise Refusal(f"{path} has unknown keys {unknown} or lacks {missing}")
    boards = load_registry(registry)
    return Config(
        owner = checked(path, "owner", data["owner"], lambda value: isinstance(value, str) and LOGIN.fullmatch(value)),
        repo = checked(path, "repo", data["repo"], repo_name),
        about = about(path, data["about"], boards),
        leave_out_labels = tuple(checked(path, "leave_out_labels", data["leave_out_labels"], labels)),
        backup_age_days = checked(path, "backup_age_days", data["backup_age_days"], positive),
        read_only = checked(path, "read_only", data["read_only"], lambda value: isinstance(value, bool)),
        boards = boards,
        allow = checked(path, "allow", data.get("allow", {}), lambda value: isinstance(value, dict)),
    )


def checked(path: Path, key: str, value: Any, rule: Any) -> Any:
    """
    Keep a config value its rule takes, else refuse naming the key.

    Args:
        path: the config, for the message
        key: the key
        value: its value
        rule: a function saying whether the value is good

    Returns:
        Any: the value

    Raises:
        Refusal: for a value the rule refuses
    """
    if not rule(value):
        raise Refusal(f"{path}'s {key} is not a value it takes")
    return value


def labels(value: Any) -> bool:
    """
    Say whether a value is a list of label prefixes, none of them empty.

    Args:
        value: the value

    Returns:
        bool: True for a list of non empty strings
    """
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def positive(value: Any) -> bool:
    """
    Say whether a value is a whole number of days above zero.

    Args:
        value: the value

    Returns:
        bool: True for a positive integer
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def about(path: Path, value: Any, boards: dict[str, Board]) -> dict[str, str]:
    """
    Read the repos a config keeps tickets about, each with its board's key, every key one the registry holds.

    Args:
        path: the config, for the message
        value: its about object
        boards: the registry's boards

    Returns:
        dict[str, str]: each repo's board key

    Raises:
        Refusal: for an empty object, a bad repo name, an entry not {"board": <key>}, or a key the registry lacks
    """
    if not isinstance(value, dict) or not value:
        raise Refusal(f"{path}'s about names no repo")
    result = {}
    for repo, entry in value.items():
        if not repo_name(repo) or not isinstance(entry, dict) or set(entry) != {"board"}:
            raise Refusal(f"{path}'s about entry {repo!r} is not <repo>: {{\"board\": <key>}}")
        if entry["board"] not in boards:
            raise Refusal(f"{path}'s about entry {repo} names the board {entry['board']!r}, which the registry lacks")
        if not boards[entry["board"]].node:
            raise Refusal(f"{path}'s about entry {repo} names the board {entry['board']!r}, whose node id the registry "
                          "does not yet pin. The owner's provisioning makes the board, and its id is pinned after")
        result[repo] = entry["board"]
    return result
