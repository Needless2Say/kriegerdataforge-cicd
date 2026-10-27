"""
The merge of design 5.5, issue fields only. Each field has three values, the file's (F), GitHub's (G) and the base
(B) kept in synced, a digest for a text and the value itself for the rest.

F equal to G is in step. F changed with G equal to B is the file's to push. G changed with F equal to B is GitHub's to
pull. Both changed apart is a conflict, nothing written for that field. A set, labels and assignees, merges by item
against the base's own list, so each side's own change is taken, and since an add and a remove of one item cannot
both be measured against one base, a set never conflicts. Board fields are never merged here, the board's being read
whole by pull.
"""

from __future__ import annotations

# standard imports
from dataclasses import dataclass
from typing import Any

# third party imports
from kdf_tickets.common import text_digest

# module constants
SAME     = "same"
PULL     = "pull"
PUSH     = "push"
BOTH     = "both"
CONFLICT = "conflict"


@dataclass(frozen = True)
class Merged:
    """
    One field's merge, its outcome, the value the file takes, and the base the file keeps.
    """
    name:    str
    outcome: str
    value:   Any
    base:    Any


def merge_text(name: str, file: str, github: str, base: str | None, take: bool = False) -> Merged:
    """
    Merge a text field, a title or a body, its base a digest.

    Args:
        name: the field
        file: the file's text
        github: GitHub's text
        base: the digest of the last value both held, None when never synced
        take: True to settle a conflict with GitHub's value

    Returns:
        Merged: the outcome, the text the file takes and its base
    """
    ours, theirs = text_digest(file), text_digest(github)
    if ours == theirs:
        return Merged(name, SAME, github, theirs)
    if base is not None and theirs == base:
        return Merged(name, PUSH, file, base)
    if base is not None and ours == base:
        return Merged(name, PULL, github, theirs)
    if take:
        return Merged(name, PULL, github, theirs)
    return Merged(name, CONFLICT, file, base)


def merge_value(name: str, file: Any, github: Any, base: Any, take: bool = False) -> Merged:
    """
    Merge a field compared by its value, the state and reason unit or the parent.

    Args:
        name: the field
        file: the file's value
        github: GitHub's value
        base: the last value both held
        take: True to settle a conflict with GitHub's value

    Returns:
        Merged: the outcome, the value the file takes and its base
    """
    if file == github:
        return Merged(name, SAME, github, github)
    if github == base:
        return Merged(name, PUSH, file, base)
    if file == base or take:
        return Merged(name, PULL, github, github)
    return Merged(name, CONFLICT, file, base)


def kept(in_file: bool, in_github: bool, in_base: bool) -> bool:
    """
    Say whether one item stays in a merged set, the side that changed it against the base deciding.

    Args:
        in_file: whether the file holds it
        in_github: whether GitHub holds it
        in_base: whether the base held it

    Returns:
        bool: True when the merged set holds it
    """
    if in_file == in_github:
        return in_file
    return in_github if in_file == in_base else in_file


def merge_set(name: str, file: list[str], github: list[str], base: list[str]) -> Merged:
    """
    Merge a set by item against the base's own list, each side's own change taken.

    Args:
        name: the field
        file: the file's items
        github: GitHub's items
        base: the items both last held

    Returns:
        Merged: SAME, PULL for GitHub's changes alone, PUSH for the file's alone, BOTH for changes on each side, the
            items the file takes, and GitHub's items as the base, since a base takes only what GitHub has shown
    """
    ours, theirs, before = set(file), set(github), set(base)
    merged = {item for item in ours | theirs | before if kept(item in ours, item in theirs, item in before)}
    if ours == theirs:
        outcome = SAME
    elif merged == theirs:
        outcome = PULL
    elif merged == ours:
        outcome = PUSH
    else:
        outcome = BOTH
    return Merged(name, outcome, sorted(merged), sorted(theirs))
