"""
What every part of the tickets tool shares, its refusal and exit codes, the patterns an id and a repo name keep, the
digests a file's bases hold, and the one way it runs git.
"""

from __future__ import annotations

# standard imports
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

# module constants
# the exit codes, plan's three of design 5.7 first, then a refusal, a usage, a config or a fence
CLEAN    = 0
FOUND    = 1
CONFLICT = 2
REFUSED  = 3
# a ticket's id and its file's name, design 5.2, checked before any read or write uses one, from a file, a marker or a
# title's slug alike (5.4), so a parent path, an absolute path, a backslash or a dot never names a file
SLUG      = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
LOGIN     = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
# the length of a digest kept in a file's synced block, in hex
DIGEST_LENGTH = 16


class Refusal(Exception):
    """
    A run refused before it finishes, with the exit code it ends on.
    """
    def __init__(self, message: str, code: int = REFUSED) -> None:
        """
        Keep the exit code beside the message.

        Args:
            message: what was refused, and the command that fixes it where there is one
            code: the exit code, a refusal's by default
        """
        super().__init__(message)
        self.code = code


def slug(value: object) -> bool:
    """
    Say whether a value is a ticket id, a string the slug pattern takes whole.

    Args:
        value: the value read

    Returns:
        bool: True for an id the tool may use
    """
    return isinstance(value, str) and SLUG.fullmatch(value) is not None


def repo_name(value: object) -> bool:
    """
    Say whether a value is a repo's name, with no owner, no slash and no parent path.

    Args:
        value: the value read

    Returns:
        bool: True for a name the tool may use
    """
    return isinstance(value, str) and REPO_NAME.fullmatch(value) is not None and ".." not in value


def text_digest(text: str) -> str:
    """
    Digest a text, a title, a body or a comments file, its carriage return and line feed pairs read as line feeds.

    Args:
        text: the text

    Returns:
        str: the first hex digits of its SHA-256
    """
    normal = text.replace("\r\n", "\n")
    return hashlib.sha256(normal.encode("utf-8", "surrogatepass")).hexdigest()[:DIGEST_LENGTH]


def value_digest(value: object) -> str:
    """
    Digest a JSON value, such as a board block, by its value and never its spelling.

    Args:
        value: the value

    Returns:
        str: the first hex digits of the SHA-256 of its sorted, compact JSON
    """
    return text_digest(json.dumps(value, sort_keys = True, ensure_ascii = True, separators = (",", ":")))


def git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """
    Run git in a worktree with every inherited GIT_ variable dropped, lazy fetching and prompts off.

    Args:
        path: the worktree
        args: git's arguments

    Returns:
        subprocess.CompletedProcess[str]: git's result, never checked here
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output = True,
        text = True,
        encoding = "utf-8",
        errors = "replace",
        env = environment,
        check = False,
    )
