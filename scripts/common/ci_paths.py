"""
What counts as docs, the one list every private repo's CI and Distribute read (D-075).

A pull request whose every change is docs runs the secret scan alone, every billed lane skipping inside itself, and
bumps no version. A kit sync whose every change is pretested or docs carries `[skip ci]`. Both read `GROUPS` here, so
the two never disagree.

The rules are plain, never globs, so no glob library's reading of `**` decides them. A path is docs when it starts with
the root `docs/` folder, or when its last part ends in `.md`, both case sensitive, so `README.MD` and
`nested/docs/x.txt` are code and fail safe. A file under `docs/` whose extension, in any case, is on the short list of
code stays code, since a lane reads it, ruff over the tree and terraform's recursive format among them. A path with an
empty, `.` or `..` part, or a leading `/`, is never docs.

A repo names the docs its code reads in `not_docs`, a README a wheel packs or a prompt a package loads, patterns over
the whole path in GitHub's own filter syntax, so the same string means the same files here and in a push filter.
`*` matches within one folder and `**` across folders, `**/` matching zero or more folders. GitHub gives `?`, `+`,
`[`, `]` and `!` meanings of their own, which this matcher does not take, and a matcher may read `{` and `}` as
alternation, so a pattern holding one refuses rather than matches, as does an empty one, an absolute one, one with an
empty, `.` or `..` part, a backslash, or one that matches no tracked file. A path whose name holds one of those
characters is named with `*` in its place, a superset that still matches it. A refusal gives no answer, and no answer
runs every lane.

The secret scan's last step runs this file's own text, written into `secret-scan.yml` by `render_ci_paths.py` (a test
holds the copy to this file), with the runner's `/usr/bin/python3` in isolated mode, as `python3 ci_paths.py answer`.
It proves the checkout is the pull request's merge from the event's own commit ids, lists the change with git, and
writes `docs_only=true` to the step's output only when every path is docs. It prints no path to the log, since a path
is the pull request's own text, writes its summary to the step summary file alone, each path escaped, and exits 0 on
every refusal, so it never fails the scan. Standard library only, Python 3.12 or later.
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path
from typing import Collection, Iterable, Mapping

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# the groups, one today, so another later is a data change here. A path is in a group when it starts with one of its
# folders and its extension, in any case, is not in its code, or when its last part ends with one of its suffixes
GROUPS: dict[str, dict[str, frozenset[str]]] = {
    "docs": {
        "folders": frozenset({"docs/"}),
        "suffixes": frozenset({".md"}),
        "code": frozenset({
            ".py",
            ".pyi",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".tf",
            ".tfvars",
            ".tfstate",
            ".tfplan",
            ".hcl",
            ".sh",
            ".go",
            ".sql",
        }),
    },
}

DOCS = "docs"

# the characters GitHub's filter syntax gives a meaning this matcher does not take, and the braces a matcher may read
# as alternation, which would make this one match less than the filter
UNSUPPORTED = frozenset("?+[]!{}")

# a commit id, sha1 or sha256
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

# the summary's heading, how many paths it lists, and how much of each
SUMMARY_HEAD  = "### Docs only (cicd D-075)\n\n"
SUMMARY_PATHS = 50
SUMMARY_WIDTH = 200

# ======================================================================================================================
# The rules
# ======================================================================================================================

def _plain(path: str) -> bool:
    """
    Whether a path is a plain repo relative path, no leading slash and no empty, `.` or `..` part.

    Args:
        path: the path

    Returns:
        bool: True when it is plain
    """
    return bool(path) and not path.startswith("/") and all(part not in ("", ".", "..") for part in path.split("/"))


def in_group(path: str, group: Mapping[str, frozenset[str]]) -> bool:
    """
    Whether one path is in a group by its rules alone.

    Args:
        path: a repo relative path
        group: the group's folders, suffixes and code

    Returns:
        bool: True when the path is in the group
    """
    if not _plain(path):
        return False
    last = path.rsplit("/", 1)[-1]
    if any(last.endswith(suffix) for suffix in group["suffixes"]):
        return True
    extension = posixpath.splitext(last)[1].lower()
    return any(path.startswith(folder) for folder in group["folders"]) and extension not in group["code"]


def malformed(pattern: str) -> str:
    """
    Why a `not_docs` pattern is refused, or nothing when it is well formed.

    Args:
        pattern: the pattern

    Returns:
        str: the reason, empty when the pattern is well formed
    """
    if not pattern:
        return "it is empty"
    if pattern.startswith("/"):
        return "it is absolute"
    if "\\" in pattern:
        return "it holds a backslash"
    if any(part in ("", ".", "..") for part in pattern.split("/")):
        return "it has an empty, . or .. part"
    if any(char.isspace() for char in pattern):
        return "it holds white space"
    if UNSUPPORTED & set(pattern):
        return "it holds a character a path filter reads another way, one of ? + [ ] ! { }, so write * in its place"
    return ""


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """
    A `not_docs` pattern as a regular expression over the whole path, read as GitHub reads a path filter.

    Args:
        pattern: the pattern

    Returns:
        re.Pattern[str]: the expression, matched with fullmatch

    Raises:
        ValueError: when the pattern is malformed
    """
    reason = malformed(pattern)
    if reason:
        raise ValueError(f"a not_docs pattern is refused, {reason}")
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts), re.DOTALL)


def compile_not_docs(not_docs: Iterable[str]) -> list[re.Pattern[str]]:
    """
    Every `not_docs` pattern compiled, a malformed one raising compile_pattern's ValueError.

    Args:
        not_docs: the patterns

    Returns:
        list[re.Pattern[str]]: each pattern's expression
    """
    return [compile_pattern(pattern) for pattern in not_docs]


def check_not_docs(not_docs: Iterable[str], tracked: Collection[str]) -> list[re.Pattern[str]]:
    """
    Every `not_docs` pattern compiled, each held to match at least one tracked file, so a typo gives no answer rather
    than a silent skip.

    Args:
        not_docs: the patterns
        tracked: the checkout's tracked files

    Returns:
        list[re.Pattern[str]]: each pattern's expression

    Raises:
        ValueError: when a pattern is malformed or matches no tracked file
    """
    compiled = compile_not_docs(not_docs)
    for expression in compiled:
        if not any(expression.fullmatch(path) for path in tracked):
            raise ValueError("a not_docs pattern matches no tracked file")
    return compiled


def parse_not_docs(text: str) -> list[str]:
    """
    The `not_docs` input split into its patterns, on any white space.

    Args:
        text: the input's value

    Returns:
        list[str]: the patterns
    """
    return text.split()


def groups_of(path: str, not_docs: Iterable[re.Pattern[str]] = ()) -> set[str]:
    """
    The groups one path falls in, a `not_docs` match taking it out of docs whatever the rules say.

    Args:
        path: a repo relative path
        not_docs: the compiled `not_docs` patterns

    Returns:
        set[str]: the names of the groups it is in
    """
    found = {name for name, group in GROUPS.items() if in_group(path, group)}
    if DOCS in found and any(expression.fullmatch(path) for expression in not_docs):
        found.discard(DOCS)
    return found


def classify(changed: Collection[str], not_docs: Iterable[str] = ()) -> set[str]:
    """
    The groups every changed path falls in, none for an empty change, a malformed `not_docs` pattern raising
    compile_pattern's ValueError.

    Args:
        changed: the repo relative paths a change touches, deletions included and a rename as its two paths
        not_docs: the repo's `not_docs` patterns

    Returns:
        set[str]: the names of the groups that hold every path
    """
    compiled = compile_not_docs(not_docs)
    if not changed:
        return set()
    found = set(GROUPS)
    for path in changed:
        found &= groups_of(path, compiled)
    return found


def docs_only(changed: Collection[str], not_docs: Iterable[str] = ()) -> bool:
    """
    Whether a change is docs only, true only when something changed and every path is docs and none is in `not_docs`,
    a malformed pattern raising compile_pattern's ValueError.

    Args:
        changed: the repo relative paths a change touches, deletions included and a rename as its two paths
        not_docs: the repo's `not_docs` patterns

    Returns:
        bool: True when the change is docs only
    """
    return bool(changed) and DOCS in classify(changed, not_docs)

# ======================================================================================================================
# The scan's answer
# ======================================================================================================================

class Refusal(Exception):
    """
    A proof that failed, so no answer is given and every lane runs. Its text is fixed, never a path.
    """


def _git(repo: Path, *args: str) -> bytes:
    """
    One git call in the checkout, its exit status checked and its error output kept from the log.

    Args:
        repo: the checkout
        *args: git's arguments

    Returns:
        bytes: its output

    Raises:
        Refusal: when git exits other than 0
    """
    found = subprocess.run(["git", "-C", str(repo), *args], capture_output = True, check = False)
    if found.returncode != 0:
        raise Refusal(f"git {args[0]} exited {found.returncode}")
    return found.stdout


def _split(output: bytes) -> list[str]:
    """
    A git listing written with -z, split on NUL with nothing stripped.

    Args:
        output: git's output

    Returns:
        list[str]: each path, bytes that are not UTF-8 kept as surrogates

    Raises:
        Refusal: when the listing does not end with NUL
    """
    if not output:
        return []
    if not output.endswith(b"\0"):
        raise Refusal("git's listing did not end with NUL")
    return [part.decode("utf-8", "surrogateescape") for part in output[:-1].split(b"\0")]


def changed_paths(repo: Path, event_sha: str, base_sha: str, head_sha: str) -> list[str]:
    """
    The paths a pull request changes, after proving the checkout is its merge, from the event's own commit ids.

    HEAD must be the event's commit with exactly two parents, the first the pull request's base and the second its head,
    in a checkout that is not shallow. The change is then listed with renames read as a deletion and an addition.

    Args:
        repo: the checkout
        event_sha: the event's commit, github.sha
        base_sha: the pull request's base commit
        head_sha: the pull request's head commit

    Returns:
        list[str]: the changed paths

    Raises:
        Refusal: when any proof fails or git fails
    """
    for name, value in (("the event's commit", event_sha), ("the base", base_sha), ("the head", head_sha)):
        if not COMMIT.fullmatch(value):
            raise Refusal(f"{name} is not a commit id")
    if _git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise Refusal("the checkout is shallow")
    line = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").decode("ascii", "replace").split()
    if len(line) != 3:
        raise Refusal("HEAD does not have exactly two parents")
    head, first, second = line
    if head != event_sha:
        raise Refusal("HEAD is not the event's commit")
    if first != base_sha:
        raise Refusal("HEAD's first parent is not the pull request's base")
    if second != head_sha:
        raise Refusal("HEAD's second parent is not the pull request's head")
    listing = _git(repo, "diff", "--name-only", "--no-renames", "--no-ext-diff", "--no-textconv", "-z", first, head)
    return _split(listing)


def _escaped(path: str) -> str:
    """
    A path as one line of the summary, quoted and escaped so no character of it reads as Markdown or a newline.

    Args:
        path: the path

    Returns:
        str: the line
    """
    shown = path if len(path) <= SUMMARY_WIDTH else path[:SUMMARY_WIDTH]
    tail  = "" if shown == path else " (cut)"
    return json.dumps(shown) + tail


def _listing(paths: list[str]) -> str:
    """
    A block of the summary listing paths, each escaped, at most SUMMARY_PATHS of them.

    Args:
        paths: the paths

    Returns:
        str: the block
    """
    lines = [_escaped(path) for path in paths[:SUMMARY_PATHS]]
    if len(paths) > SUMMARY_PATHS:
        lines.append(f"and {len(paths) - SUMMARY_PATHS} more")
    return "\n```text\n" + "\n".join(lines) + "\n```\n" if lines else ""


def answer(environ: Mapping[str, str], repo: Path) -> tuple[bool, str, str]:
    """
    The scan's answer for the checkout, its summary and its one line for the log, which holds fixed text and counts
    alone, never a path, so a refusal's reason shows in the log as well as the summary.

    Args:
        environ: EVENT_SHA, BASE_SHA, HEAD_SHA and NOT_DOCS
        repo: the checkout

    Returns:
        tuple[bool, str, str]: whether the change is docs only, the summary's Markdown, and the log's line
    """
    try:
        changed  = changed_paths(
            repo,
            environ.get("EVENT_SHA", ""),
            environ.get("BASE_SHA", ""),
            environ.get("HEAD_SHA", ""),
        )
        tracked  = _split(_git(repo, "ls-files", "-z"))
        compiled = check_not_docs(parse_not_docs(environ.get("NOT_DOCS", "")), tracked)
    except (Refusal, ValueError) as error:
        return False, f"{SUMMARY_HEAD}No answer, so every lane runs. {error}.\n", f"no answer, every lane runs, {error}"
    if not changed:
        said = "not docs only, the pull request changes no path"
        return False, f"{SUMMARY_HEAD}Not docs only, the pull request changes no path.\n", said
    code = [path for path in changed if DOCS not in groups_of(path, compiled)]
    if code:
        counted = f"{len(code)} of {len(changed)} paths are not docs"
        return False, f"{SUMMARY_HEAD}Not docs only, {counted}.\n{_listing(code)}", f"not docs only, {counted}"
    summary = f"{SUMMARY_HEAD}Docs only, {len(changed)} paths, every billed lane skipped.\n{_listing(changed)}"
    return True, summary, f"docs only, {len(changed)} paths, every billed lane skips"


def run_answer(environ: Mapping[str, str], repo: Path) -> int:
    """
    Write the answer to the step's output file and its summary to the step summary file. Never fails, so the scan's
    result is the scan's alone.

    Args:
        environ: the step's environment, GITHUB_OUTPUT and GITHUB_STEP_SUMMARY among it
        repo: the checkout

    Returns:
        int: 0 always
    """
    try:
        positive, summary, said = answer(environ, repo)
    except Exception:  # noqa: BLE001
        positive, summary = False, f"{SUMMARY_HEAD}No answer, so every lane runs. The classifier failed.\n"
        said = "no answer, every lane runs, the classifier failed"
    if positive:
        try:
            with open(environ["GITHUB_OUTPUT"], "a", encoding = "utf-8") as handle:
                handle.write("docs_only=true\n")
        except (KeyError, OSError):
            positive = False
            summary  += "\nThe answer could not be written, so every lane runs.\n"
            said = "no answer, every lane runs, the answer could not be written"
    target = environ.get("GITHUB_STEP_SUMMARY", "")
    if target:
        try:
            with open(target, "a", encoding = "utf-8", errors = "backslashreplace") as handle:
                handle.write(summary)
        except OSError:
            pass
    print(said)
    return 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    """
    The scan's last step, `answer`, run in the checkout.

    Args:
        argv: the arguments, sys.argv when None

    Returns:
        int: 0 always for answer
    """
    parser = argparse.ArgumentParser(description = "Answer whether a pull request is docs only (D-075).")
    parser.add_argument("command", choices = ["answer"])
    parser.parse_args(argv)
    return run_answer(os.environ, Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
