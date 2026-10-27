"""
The ticket file, one YAML file per GitHub issue, written in one canonical form and read by the standard library alone.

Every line but the body's is key: <one JSON value>, which is valid YAML, so json reads each line and PyYAML, in cicd's
tests alone, reads the whole file to the same value. The body is the last key, a literal block with its indentation
explicit when the block can carry the body exactly, else one JSON string (design 5.2). The reader is looser than the
writer, taking keys in any order, comment and blank lines, and a block whose indentation it finds, so fmt can rewrite
a file a session wrote by hand. check refuses any file the writer would not write byte for byte.
"""

from __future__ import annotations

# standard imports
import json
import re
from dataclasses import dataclass, field
from typing import Any

# third party imports
from kdf_tickets.common import text_digest, value_digest

# module constants
# the keys in the order the canonical form writes them, the body last
ORDER       = (
    "id",
    "title",
    "about",
    "also",
    "kind",
    "state",
    "reason",
    "labels",
    "assignees",
    "parent",
    "issue",
    "board",
    "synced",
    "body",
)
REQUIRED    = ("id", "title", "about", "body")
ISSUE_KEYS  = ("repo", "number", "node", "url")
BOARD_KEYS  = ("status", "priority", "type", "severity", "after")
SYNCED_KEYS = ("title", "body", "state", "reason", "labels", "assignees", "parent", "board", "comments")
# the lists written sorted, each a set the merge reads by item
SORTED = ("also", "labels", "assignees")
# the Unicode line and paragraph separators, a byte order mark and the two noncharacters YAML refuses, made from their
# code points, since kdf-fmt's format writes a \u escape as the character itself, in a raw string too, and these would
# then stand in the source unseen
INVISIBLE = "".join(chr(point) for point in (0x2028, 0x2029, 0xFEFF, 0xFFFE, 0xFFFF))
# what a JSON string may hold raw that YAML reads as a line break or refuses as unprintable, written escaped instead,
# the C1 controls with NEL and DEL, INVISIBLE and a lone surrogate
UNSAFE = re.compile(f"[\\x7f-\\x9f{INVISIBLE}\\ud800-\\udfff]")
# what a literal block cannot carry exactly, a carriage return, a control character but a tab and a line feed, and all
# of UNSAFE
UNBLOCKABLE = re.compile(f"[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f{INVISIBLE}\\ud800-\\udfff]")
KEY_LINE    = re.compile(r"([a-z_]+):(?: (.*))?")
BLOCK       = re.compile(r"\|([1-9])?")


class FormError(ValueError):
    """
    A ticket file the reader cannot take, with the line it stopped at where there is one.
    """


@dataclass
class Ticket:
    """
    One ticket, the fields of design 5.2 with reason beside state as one unit.
    """
    id:        str
    title:     str
    about:     str
    also:      list[str] = field(default_factory = list)
    kind:      str = "feature"
    state:     str = "open"
    reason:    str | None = None
    labels:    list[str] = field(default_factory = list)
    assignees: list[str] = field(default_factory = list)
    parent:    str | None = None
    issue:     dict[str, Any] | None = None
    board:     dict[str, Any] | None = None
    synced:    dict[str, Any] | None = None
    body:      str = ""


def scalar(value: object) -> str:
    """
    Write one JSON value as YAML reads it, a string with every character YAML would misread escaped.

    Args:
        value: a string, a number, None, a list or an object

    Returns:
        str: the value on one line
    """
    text = json.dumps(value, ensure_ascii = False, separators = (", ", ": "), allow_nan = False)
    return UNSAFE.sub(lambda match: f"\\u{ord(match.group()):04x}", text)


def blockable(body: str) -> bool:
    """
    Say whether a literal block with explicit indentation carries a body exactly.

    Args:
        body: the body

    Returns:
        bool: True for a body that ends with exactly one line break and holds no line of white space alone and nothing
            UNBLOCKABLE names
    """
    if not body.endswith("\n") or body.endswith("\n\n") or body == "\n":
        return False
    if UNBLOCKABLE.search(body):
        return False
    return all(line == "" or line.strip(" \t") != "" for line in body[:-1].split("\n"))


def ordered(name: str, value: Any) -> Any:
    """
    Put a field's value in the order the canonical form writes it, its lists sorted and its objects' keys fixed.

    Args:
        name: the field
        value: its value

    Returns:
        Any: the value as it is written
    """
    if value is None:
        return None
    if name in SORTED:
        return sorted(value)
    keys = {"issue": ISSUE_KEYS, "board": BOARD_KEYS, "synced": SYNCED_KEYS}.get(name)
    if keys is None:
        return value
    written = {key: value[key] for key in keys}
    if name == "synced":
        for key in ("labels", "assignees"):
            written[key] = sorted(written[key])
    return written


def dump(ticket: Ticket) -> str:
    """
    Write a ticket in the canonical form.

    Args:
        ticket: the ticket

    Returns:
        str: the file's text, its lines ending in line feeds
    """
    lines = [f"{name}: {scalar(ordered(name, getattr(ticket, name)))}" for name in ORDER[:-1]]
    if blockable(ticket.body):
        lines.append("body: |2")
        lines.extend(f"  {line}" if line else "" for line in ticket.body[:-1].split("\n"))
    else:
        lines.append(f"body: {scalar(ticket.body)}")
    return "\n".join(lines) + "\n"


def as_dict(ticket: Ticket) -> dict[str, Any]:
    """
    Give a ticket as the mapping its file holds, as PyYAML reads it.

    Args:
        ticket: the ticket

    Returns:
        dict[str, Any]: every key in the canonical order
    """
    return {name: ordered(name, getattr(ticket, name)) for name in ORDER}


def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    """
    Make a JSON object from its pairs, refusing a key given twice, which json would let the last one win.

    Args:
        items: the object's pairs in order

    Returns:
        dict[str, Any]: the object

    Raises:
        ValueError: for a key given twice
    """
    keys = [key for key, _ in items]
    if len(keys) != len(set(keys)):
        raise ValueError("an object with a key twice")
    return dict(items)


def refuse_constant(name: str) -> None:
    """
    Refuse NaN and the infinities, which json reads though JSON has none.

    Args:
        name: the constant read

    Raises:
        ValueError: always
    """
    raise ValueError(f"{name} is not a JSON value")


def strict_json(text: str) -> Any:
    """
    Read one JSON value, refusing NaN, the infinities and an object with a key twice.

    Args:
        text: the value's text

    Returns:
        Any: the value
    """
    return json.loads(text, object_pairs_hook = unique_pairs, parse_constant = refuse_constant)


def read_block(lines: list[str], start: int, indent: int | None) -> tuple[str, int]:
    """
    Read a literal block from the line after its header, keeping one final line break as YAML's clip does.

    Args:
        lines: the file's lines
        start: the index of the block's first line
        indent: the explicit indentation, or None to find it from the first line with text

    Returns:
        tuple[str, int]: the body, and the index of the first line after the block
    """
    if indent is None:
        first  = next((line for line in lines[start:] if line.strip(" ")), "")
        indent = max(len(first) - len(first.lstrip(" ")), 1)
    content = []
    index   = start
    while index < len(lines):
        line = lines[index]
        if line.startswith(" " * indent):
            content.append(line[indent:])
        elif line.strip(" ") == "":
            content.append("")
        else:
            break
        index += 1
    while content and content[-1] == "":
        content.pop()
    return ("\n".join(content) + "\n" if content else ""), index


def load(text: str) -> Ticket:
    """
    Read a ticket file, its carriage return and line feed pairs read as line feeds.

    Args:
        text: the file's text

    Returns:
        Ticket: the ticket, its types checked

    Raises:
        FormError: for a line the reader cannot take, a key twice or missing, or a value of the wrong type
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    values: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        match = KEY_LINE.fullmatch(line)
        if match is None:
            raise FormError(f"line {index} is not key: <one JSON value>")
        key, rest = match.group(1), match.group(2) or ""
        if key not in ORDER:
            raise FormError(f"line {index} has the unknown key {key}")
        if key in values:
            raise FormError(f"line {index} repeats the key {key}")
        header = BLOCK.fullmatch(rest.strip())
        if key == "body" and header is not None:
            indent = int(header.group(1)) if header.group(1) else None
            values[key], index = read_block(lines, index, indent)
            continue
        try:
            values[key] = strict_json(rest)
        except ValueError as error:
            raise FormError(f"line {index}, {key}, is not one JSON value, {error}") from None
    missing = [key for key in REQUIRED if key not in values]
    if missing:
        raise FormError(f"the keys {', '.join(missing)} are missing")
    typed(values)
    return Ticket(**values)


def is_text(value: Any) -> bool:
    """
    Say whether a value is a string.

    Args:
        value: the value

    Returns:
        bool: True for a string
    """
    return isinstance(value, str)


def is_maybe(value: Any) -> bool:
    """
    Say whether a value is a string or None.

    Args:
        value: the value

    Returns:
        bool: True for a string or None
    """
    return value is None or isinstance(value, str)


def is_texts(value: Any) -> bool:
    """
    Say whether a value is a list of strings.

    Args:
        value: the value

    Returns:
        bool: True for a list whose every item is a string
    """
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def is_shaped(value: Any, keys: tuple[str, ...]) -> bool:
    """
    Say whether a value is None or an object holding exactly the keys named.

    Args:
        value: the value
        keys: the keys its object holds

    Returns:
        bool: True for None or an object of exactly those keys
    """
    return value is None or (isinstance(value, dict) and sorted(value) == sorted(keys))


def typed(values: dict[str, Any]) -> None:
    """
    Check every value read has its field's type, so the writer can sort and order it.

    Args:
        values: the values read, by key

    Raises:
        FormError: naming the first field of the wrong type
    """
    rules = {
        "id": is_text,
        "title": is_text,
        "about": is_text,
        "kind": is_text,
        "state": is_text,
        "body": is_text,
        "reason": is_maybe,
        "parent": is_maybe,
        "also": is_texts,
        "labels": is_texts,
        "assignees": is_texts,
        "issue": lambda value: is_shaped(value, ISSUE_KEYS),
        "board": lambda value: is_shaped(value, BOARD_KEYS) and all(is_maybe(item) for item in (value or {}).values()),
        "synced": lambda value: is_shaped(value, SYNCED_KEYS),
    }
    for key, value in values.items():
        if not rules[key](value):
            raise FormError(f"{key} is not of its field's type")
    issue = values.get("issue")
    if issue is not None:
        number = issue["number"]
        if not (isinstance(number, int) and not isinstance(number, bool)) or not all(
            is_text(issue[key]) for key in ("repo", "node", "url")
        ):
            raise FormError("issue's repo, node and url must be strings and its number an integer")
    synced = values.get("synced")
    if synced is not None:
        lists  = all(is_texts(synced[key]) for key in ("labels", "assignees"))
        others = all(is_maybe(synced[key]) for key in SYNCED_KEYS if key not in ("labels", "assignees"))
        if not (lists and others):
            raise FormError("synced holds a value of the wrong type")
    for key in SORTED:
        if key in values and len(set(values[key])) != len(values[key]):
            raise FormError(f"{key} names an item twice")


def board_digest(board: dict[str, Any] | None) -> str | None:
    """
    Digest a board block for its base in synced, None for a ticket off its board.

    Args:
        board: the board block

    Returns:
        str | None: its digest, or None
    """
    return None if board is None else value_digest(ordered("board", board))


def synced_from(ticket: Ticket, comments: str | None) -> dict[str, Any]:
    """
    Make the bases of a ticket whose every field GitHub has just given, as a pull writes them.

    Args:
        ticket: the ticket as read from GitHub
        comments: its comments file's text, or None when it has none

    Returns:
        dict[str, Any]: the synced block
    """
    return {
        "title": text_digest(ticket.title),
        "body": text_digest(ticket.body),
        "state": ticket.state,
        "reason": ticket.reason,
        "labels": sorted(ticket.labels),
        "assignees": sorted(ticket.assignees),
        "parent": ticket.parent,
        "board": board_digest(ticket.board),
        "comments": None if comments is None else text_digest(comments),
    }
