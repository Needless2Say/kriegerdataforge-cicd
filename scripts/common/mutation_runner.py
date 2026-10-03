"""
The shared mutation engine. Break one rule at a time in a private copy of the repo and prove a test goes red.

One engine for every repo that runs hand written mutants (cicd D-040). Its source is kriegerdataforge-cicd's
``scripts/common/mutation_runner.py``, vendored byte for byte to ``scripts/kdf_scripts/mutation_runner.py`` by the
scripts sync (D-013) and never edited in a repo, which holds its tables and the tests of its tables alone.

A mutant table is the module ``mutation_tests/<lane>.py``, holding ``MUTANTS``, a list of dicts.

    MUTANTS = [
        {
            "id": "XX-M-1",
            "rule": "a row is read by the user who owns it and by no other",
            "file": "api/example/service.py",
            "anchor": "if row.user_id != user.user_id:",
            "replacement": "if False:",
            "suite": "unit",
            "tests": ["unit_tests/example/test_service.py"],
        },
    ]

``id`` is unique in the table. ``rule`` says in one sentence what the mutant breaks. ``file`` is repo relative, and
a path that is absolute, climbs out of the repo or leaves it through a link is refused, the edit is written into
the worktree and nowhere else. ``anchor`` is exact text that occurs ONCE in that file, and ``replacement`` is what
it becomes, a line break written as ``\\n`` matches either line ending. ``suite`` is ``unit``, ``integration`` or
``system``, and ``tests`` names the pytest paths or node ids expected to kill it. ``bundle``, optional and false by
default, regenerates ``vercel_api/`` after the edit, for a mutant a system test proves on the bundle. ``platform``,
optional, is the one ``sys.platform`` the rule exists on, ``win32``, ``linux`` or ``darwin``. Elsewhere the code the
mutant edits never runs, so the mutant is reported as not run and is neither a kill nor a survivor.

What a repo's unit suite needs, the values its ``make ci-unit-tests`` exports, its package ``mutation_tests`` says.
Its ``__init__.py`` may define ``unit_settings(environment)``, which is handed the environment the unit suite would
get and returns the variables set over it, names to strings. Without it the unit suite gets this process's alone.

How a run works. The runner keeps a detached git worktree per lane outside the repo, under the system temp directory,
moves it to the repo's HEAD, and copies in every file the working tree has changed or added, plus ``.env.test``, so
the copy matches what the lane is looking at, uncommitted tests included. It never copies ``.env.local``. It runs the
union of the tests once unmutated, and stops if that control is red. Then for each mutant it applies the edit,
runs that mutant's tests, and restores the file byte for byte. A mutant is killed when pytest exits 1. It survived
when pytest exits 0 having run tests. Anything else, an anchor that is missing or not unique, a collection error,
nothing run, or the timeout, is reported and is not a kill. Every run writes no bytecode, and the worktree's clean
removes what an earlier run left, so each mutant runs its own source. With bytecode written, a mutant that left its
file the size the previous one left it, within the same second, ran the previous mutant's cached code.

The worktree is the one place a run destroys anything. It forces a checkout there and removes every untracked and
ignored file, a nested repository excepted, which git's clean keeps. So ``--worktree`` takes only a path outside this
checkout that does not exist yet, or a worktree an earlier run made, which the runner knows by a mark it wrote in
git's own folder for that worktree. Anything else is refused before a command runs, this checkout itself, a folder
inside it or around it, someone's folder, a developer's own worktree, detached or on a branch. The folders the
worktree stands in are the runner's own, made with mode 0o700, and one that is a link, another user's or writable by
other users is refused, so nobody else can put a link at the path between a judgement and git's act. The path is
resolved once, and right before each of the forced checkout, the clean and ``--remove``, git is asked from inside the
path where it would act, so a path that became another repository after the judgement is refused too, and the
worktree is walked for a link, which git would act through and which the repo never tracks. Every git command runs
without the ``GIT_`` variables of the caller's shell, which name a repository for git whatever folder it runs in, and
which git hands to every hook. A mutated file is restored by a new file made beside it under a name no test knows,
which replaces the directory entry, and the results file beside the worktree is written the same way, over a results
file of the runner's own and nothing else.

An integration mutant needs ``KDF_TEST_DATABASE_URL`` and a system mutant ``KDF_SYSTEM_DATABASE_URL`` in this
process's environment, each naming the lane's own database. Neither is printed. A src layout package is installed
editable, so a test in the worktree would import the package from the repo the environment was installed from and
never see a mutant, and a worktree that holds ``src`` gets it first on the import path. The engine knows the test
command, the table format and the bundle's paths, and nothing else about a repo.

    python scripts/kdf_scripts/mutation_runner.py --lane <lane>
    python scripts/kdf_scripts/mutation_runner.py --lane <lane> --only XX-M-3 --only XX-M-4
    python scripts/kdf_scripts/mutation_runner.py --lane <lane> --list
    python scripts/kdf_scripts/mutation_runner.py --lane <lane> --remove

Exit status. 0 when every mutant run was killed, 1 when any survived or could not run, 2 on a usage error, an invalid
table, a red control run, or a worktree the runner could not act in or restore. A mutant of another platform is not
one that ran. Results are also written as JSON beside the worktree.
"""

from __future__ import annotations

# standard imports
import argparse
import contextlib
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

# ======================================================================================================================
# Constants
# ======================================================================================================================

# the repo the engine runs for, two folders up from either seat, scripts/kdf_scripts/ in a repo and scripts/common/
# in cicd
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# the package of a repo's tables, and the function in it that says what the repo's unit suite is given
TABLES_PACKAGE:     str = "mutation_tests"
UNIT_SETTINGS_HOOK: str = "unit_settings"

SUITES: frozenset[str] = frozenset({"unit", "integration", "system"})

# the values of sys.platform a mutant may be bound to
PLATFORMS: frozenset[str] = frozenset({"win32", "linux", "darwin"})

# what a mutant of another platform is reported as, never a kill and never a survivor
NOT_RUN: str = "not run"

# the file the runner writes in git's own folder for a worktree it made, holding the worktree's path. git keeps that
# folder under the repository's .git/worktrees, so no clean of the worktree reaches it, and a detached worktree a
# developer made by hand has none
WORKTREE_MARK: str = "kdf-mutation"

# the keys of every record in a results file and the type of each value, what the runner overwrites and nothing else
_RESULT_TYPES: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "result": str,
    "seconds": (int, float),
    "rule": str,
    "detail": str,
}

# the variable each suite needs, naming the lane's own database. unit needs none
_SUITE_DATABASE_VARIABLE: dict[str, str] = {
    "integration": "KDF_TEST_DATABASE_URL",
    "system": "KDF_SYSTEM_DATABASE_URL",
}

# the bundle files the compactor writes, restored from the repo after a bundle mutant
_BUNDLE_OUTPUTS: tuple[str, ...] = ("vercel_api/app", "vercel_api/requirements.txt", "vercel_api/pyproject.toml")

DEFAULT_TIMEOUT_SECONDS: int = 900

_LANE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_TESTS_RAN = re.compile(r"\b\d+ passed\b")
_REQUIRED  = ("id", "rule", "file", "anchor", "replacement", "suite", "tests")

# ======================================================================================================================
# Table
# ======================================================================================================================

class MutantTableError(ValueError):
    """
    Raised when a mutant table cannot be run as written.
    """


class WorktreeError(ValueError):
    """
    Raised when a path cannot be the lane's worktree, before anything in it is changed.
    """


@dataclass(frozen = True)
class Mutant:
    """
    One deliberate break of one rule.
    """
    id:          str
    rule:        str
    file:        str
    anchor:      str
    replacement: str
    suite:       str
    tests:       tuple[str, ...]
    bundle:   bool = False
    platform: str | None = None


    def runs_here(self) -> bool:
        """
        Whether the rule this mutant breaks exists on the platform the runner is on.

        Returns:
            bool: True for a mutant bound to no platform, or to this one
        """
        return self.platform is None or self.platform == sys.platform


def parse_mutants(entries: object, repo_root: Path) -> list[Mutant]:
    """
    Validate a table's entries and build its mutants.

    Args:
        entries: The table's ``MUTANTS`` value
        repo_root: The repo the files are relative to

    Returns:
        list[Mutant]: The mutants, in table order

    Raises:
        MutantTableError: An entry is malformed, an id repeats, a file does not exist or a suite is unknown
    """
    if not isinstance(entries, list) or not entries:
        raise MutantTableError("MUTANTS must be a non empty list of dicts")
    mutants: list[Mutant] = []
    seen:    set[str] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise MutantTableError(f"entry {position} is not a dict")
        missing = [name for name in _REQUIRED if name not in entry]
        if missing:
            raise MutantTableError(f"entry {position} lacks {missing}")
        unknown = set(entry) - {*_REQUIRED, "bundle", "platform"}
        if unknown:
            raise MutantTableError(f"entry {position} has unknown keys {sorted(unknown)}")
        if entry.get("platform") is not None and entry["platform"] not in PLATFORMS:
            raise MutantTableError(
                f"entry {entry['id']!r} names platform {entry['platform']!r}, one of {sorted(PLATFORMS)}",
            )
        tests = entry["tests"]
        if not isinstance(tests, list) or not tests or not all(isinstance(test, str) and test for test in tests):
            raise MutantTableError(f"entry {entry['id']!r} needs tests, a non empty list of pytest paths")
        for name in ("id", "rule", "file", "anchor", "suite"):
            if not isinstance(entry[name], str) or not entry[name].strip():
                raise MutantTableError(f"entry {position} needs {name}, a non empty string")
        if not isinstance(entry["replacement"], str) or entry["replacement"] == entry["anchor"]:
            raise MutantTableError(f"entry {entry['id']!r} needs a replacement that differs from its anchor")
        if entry["id"] in seen:
            raise MutantTableError(f"the id {entry['id']!r} appears twice")
        if entry["suite"] not in SUITES:
            raise MutantTableError(f"entry {entry['id']!r} names suite {entry['suite']!r}, one of {sorted(SUITES)}")
        # repo relative, and still inside the repo once every link is followed. an absolute path would take the
        # place of the worktree in `worktree / file`, and the mutant would be written into the live file
        named = Path(entry["file"])
        if named.is_absolute() or named.drive or ".." in named.parts:
            raise MutantTableError(f"entry {entry['id']!r} names {entry['file']}, which is not a path inside the repo")
        if repo_root.resolve() not in (repo_root / named).resolve().parents:
            raise MutantTableError(f"entry {entry['id']!r} names {entry['file']}, which is not a path inside the repo")
        if not (repo_root / named).is_file():
            raise MutantTableError(f"entry {entry['id']!r} names {entry['file']}, which is not a file")
        seen.add(entry["id"])
        mutants.append(
            Mutant(
                id = entry["id"],
                rule = entry["rule"],
                file = entry["file"],
                anchor = entry["anchor"],
                replacement = entry["replacement"],
                suite = entry["suite"],
                tests = tuple(tests),
                bundle = bool(entry.get("bundle", False)),
                platform = entry.get("platform"),
            ),
        )
    return mutants


def load_table(lane: str) -> list[Mutant]:
    """
    Import a lane's table and validate it.

    Args:
        lane: The lane, the table's module name

    Returns:
        list[Mutant]: Its mutants

    Raises:
        MutantTableError: The lane name is invalid, the module is missing or its table is malformed
    """
    if not _LANE_NAME.match(lane):
        raise MutantTableError(f"the lane {lane!r} is not a module name")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        module = importlib.import_module(f"{TABLES_PACKAGE}.{lane}")
    except ModuleNotFoundError as error:
        raise MutantTableError(f"there is no {TABLES_PACKAGE}/{lane}.py") from error
    return parse_mutants(getattr(module, "MUTANTS", None), REPO_ROOT)


def unit_settings(environment: Mapping[str, str]) -> dict[str, str]:
    """
    What the repo's unit suite is given over the environment, as its package ``mutation_tests`` says.

    Args:
        environment: The environment the unit suite would get, a copy the repo's function may read

    Returns:
        dict[str, str]: The variables to set, none when the repo holds no such package or it defines no function

    Raises:
        MutantTableError: The repo's function returns anything but names mapped to strings
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        package = importlib.import_module(TABLES_PACKAGE)
    except ModuleNotFoundError as error:
        # the package itself is missing, a module it imports that is missing is the repo's error and says so
        if error.name != TABLES_PACKAGE:
            raise
        return {}
    hook = getattr(package, UNIT_SETTINGS_HOOK, None)
    if hook is None:
        return {}
    settings = hook(dict(environment))
    if not isinstance(settings, Mapping) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in settings.items()
    ):
        raise MutantTableError(f"{TABLES_PACKAGE}.{UNIT_SETTINGS_HOOK} must return names mapped to strings")
    return dict(settings)

# ======================================================================================================================
# Mutation
# ======================================================================================================================

def apply_mutant(text: str, mutant: Mutant) -> tuple[str | None, str]:
    """
    Apply a mutant to a file's text, matching its anchor under the file's own line endings.

    Args:
        text: The file, decoded
        mutant: The mutant

    Returns:
        tuple[str | None, str]: The mutated text and ``applied``, or None and ``stale`` when the anchor is missing
        or ``ambiguous`` when it occurs more than once
    """
    anchor      = mutant.anchor.replace("\r\n", "\n")
    replacement = mutant.replacement.replace("\r\n", "\n")
    if "\r\n" in text:
        anchor, replacement = anchor.replace("\n", "\r\n"), replacement.replace("\n", "\r\n")
    count = text.count(anchor)
    if count == 0:
        return None, "stale"
    if count > 1:
        return None, "ambiguous"
    return text.replace(anchor, replacement), "applied"


def classify(returncode: int | None, output: str) -> str:
    """
    Read a pytest run as a mutant's result.

    Args:
        returncode: pytest's exit status, None when the run timed out
        output: What it printed

    Returns:
        str: ``killed``, ``survived``, ``timeout``, or ``error`` with the reason
    """
    if returncode is None:
        return "timeout"
    if returncode == 1:
        return "killed"
    if returncode == 0:
        return "survived" if _TESTS_RAN.search(output) else "error, no test ran"
    if returncode == 5:
        return "error, no test collected"
    return f"error, pytest exited {returncode}"

# ======================================================================================================================
# Worktree
# ======================================================================================================================

def changed_paths(porcelain: bytes) -> list[str]:
    """
    Every path ``git status --porcelain=v1 -z --untracked-files=all`` reports, a rename's both sides included.

    Args:
        porcelain: The command's output

    Returns:
        list[str]: Repo relative paths, each once, in the order reported
    """
    fields = porcelain.decode("utf-8", "surrogateescape").split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        # a rename or copy carries its source as the next field
        if entry[0] in "RC" or entry[1] in "RC":
            if index < len(fields) and fields[index]:
                paths.append(fields[index])
            index += 1
    return list(dict.fromkeys(paths))


def git_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """
    The environment every git command of the runner is handed, the caller's less every ``GIT_`` variable.

    SECURITY: ``GIT_DIR`` and ``GIT_WORK_TREE`` name the repository and the working tree for every git command,
    whatever folder it runs in, and git exports them to every hook, so a run started from a pre-push hook would
    force its checkout and its clean in the developer's own checkout. The runner's git commands are local and need
    none of them.

    Args:
        environ: The caller's environment

    Returns:
        dict[str, str]: What git is handed
    """
    return {name: value for name, value in environ.items() if not name.upper().startswith("GIT_")}


def _git(*args: str, cwd: Path) -> bytes:
    """
    Run git and return its output, a git that fails raises subprocess's own error.

    Args:
        args: The git arguments
        cwd: Where it runs

    Returns:
        bytes: Its standard output
    """
    return subprocess.run(
        ["git", *args],
        cwd = str(cwd),
        check = True,
        capture_output = True,
        env = git_environment(os.environ),
    ).stdout


def _git_path(*args: str, cwd: Path) -> Path:
    """
    A path git prints, resolved, a relative one against the folder git ran in.

    Args:
        args: The git arguments
        cwd: Where it runs

    Returns:
        Path: The path, resolved
    """
    printed = _git(*args, cwd = cwd).decode("utf-8", errors = "replace").strip()
    return Path(cwd, printed).resolve()


def _said(error: subprocess.CalledProcessError) -> str:
    """
    The tail of what a failed git command printed, masked, the reason a refusal carries.

    Args:
        error: subprocess's error for the command

    Returns:
        str: The last 300 characters of its standard error
    """
    return _masked(error.stderr.decode("utf-8", errors = "replace"))[-300:].strip()


def own_worktrees() -> list[Path]:
    """
    The worktrees of this repo a runner may have made, every registered one that is detached, the main one never.

    Returns:
        list[Path]: Their paths, resolved
    """
    listed = _git("worktree", "list", "--porcelain", "-z", cwd = REPO_ROOT)
    # one block per worktree, the main working tree first, every line ended by NUL and a block by one more, so a
    # path is never quoted. a runner's is added detached, a developer's own worktree is on a branch
    blocks = [block.split(b"\0") for block in listed.split(b"\0\0") if block.strip(b"\0")]
    return [
        Path(block[0].removeprefix(b"worktree ").decode("utf-8", errors = "replace")).resolve()
        for block in blocks[1:]
        if block[0].startswith(b"worktree ") and b"detached" in block
    ]


def not_this_runners_worktree(worktree: Path) -> str | None:
    """
    Why git is not about to act where the runner thinks, asked of git itself from inside the path.

    SECURITY: the path was judged once, by this process, and git acts where its own reading of the path says. The
    two are asked to agree immediately before every command that destroys, a path that became another repository
    after the judgement, a developer's own detached worktree and this repository's main working tree are each
    refused here. A runner's worktree is linked, detached, and carries the mark the runner wrote in git's folder for
    it, which no clean reaches.

    Args:
        worktree: The path git is about to act in

    Returns:
        str | None: The reason, or None for a worktree this runner made of this repository
    """
    target = worktree.resolve()
    try:
        toplevel = _git_path("rev-parse", "--show-toplevel", cwd = worktree)
        common   = _git_path("rev-parse", "--git-common-dir", cwd = worktree)
        git_dir  = _git_path("rev-parse", "--absolute-git-dir", cwd = worktree)
        head     = _git("rev-parse", "--abbrev-ref", "HEAD", cwd = worktree).decode("ascii", errors = "replace").strip()
    except subprocess.CalledProcessError:
        return f"{worktree} is not a git worktree"
    if toplevel != target:
        return f"{worktree} is not the top of a working tree, git's is {toplevel}"
    if common != _git_path("rev-parse", "--git-common-dir", cwd = REPO_ROOT):
        return f"{worktree} belongs to another repository"
    if common not in git_dir.parents:
        return f"{worktree} is this repository's main working tree"
    if head != "HEAD":
        return f"{worktree} is on a branch"
    mark = git_dir / WORKTREE_MARK
    if not mark.is_file() or mark.read_text(encoding = "utf-8").strip() != str(target):
        return f"{worktree} was not made by this runner, remove it with git worktree remove --force and run again"
    return None


def link_problem(worktree: Path) -> str | None:
    """
    Why git must not act in the worktree yet, a link stands inside it, or None. The repo tracks none.

    SECURITY: git's clean removes what stands behind a link that took a tracked folder's place, outside the worktree,
    and a forced checkout writes through one. A test left it, so the run stops and names it. The walk follows nothing.

    Args:
        worktree: The worktree

    Returns:
        str | None: The reason, naming the link, or None
    """
    pending = [worktree]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    return f"{entry.path} is a link inside the worktree, git would act through it, remove it first"
                if entry.is_dir(follow_symlinks = False):
                    pending.append(Path(entry.path))
    return None


def _act(worktree: Path, *args: str) -> None:
    """
    Run one of git's commands that destroy, right after git itself agreed where it is about to act.

    Args:
        worktree: Where it acts
        args: The git arguments

    Raises:
        WorktreeError: git does not read the path as this runner's worktree, a link stands inside it, or the command
            failed, with git's words
    """
    # SECURITY: asked of git itself, with the folder it is about to act in, before each command and not once for
    # both, a hook of the checkout runs between them
    problem = not_this_runners_worktree(worktree)
    if problem is not None:
        raise WorktreeError(problem)
    problem = link_problem(worktree)
    if problem is not None:
        raise WorktreeError(problem)
    try:
        _git(*args, cwd = worktree)
    except subprocess.CalledProcessError as error:
        raise WorktreeError(f"git {args[0]} failed in {worktree}, {_said(error)}") from error


def worktree_problem(worktree: Path) -> str | None:
    """
    Why a path cannot be the lane's worktree, or None when it can.

    SECURITY: the runner forces a checkout in its worktree and removes every untracked and ignored file there. In
    this checkout that is a developer's uncommitted work, their credentials file and their environment, which
    ``--worktree .`` destroyed, and reported a green run. So the path is judged before either command, it is
    outside this checkout, and when it exists it is a detached worktree this repo registered. That is the first
    judgement, by this process, and ``not_this_runners_worktree`` is the second, by git, right before the commands.

    Args:
        worktree: The path named, or the default

    Returns:
        str | None: The reason, or None for a path that does not exist yet or is a runner's own worktree
    """
    target = worktree.resolve()
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        return f"{worktree} is inside this checkout, a run would remove every uncommitted and ignored file there"
    if target in REPO_ROOT.parents:
        return f"{worktree} holds this checkout"
    if target.exists() and target not in own_worktrees():
        return f"{worktree} exists and is not a detached worktree this repo registered, remove it or name another"
    return None


def own_folders(worktree: Path) -> str | None:
    """
    Make the folders the worktree stands in the runner's own, or say why they cannot be.

    SECURITY: a judgement and git's act are two moments, and a folder anyone else can write to lets them put a link
    at the worktree's path in between, which the forced checkout and the clean would follow. So every folder between
    the system temp directory and the worktree, or the worktree's parent when it stands elsewhere, is made by the
    runner with mode 0o700, and one that is a link, another user's or writable by other users is refused. The results
    file is written in the nearest of them.

    Args:
        worktree: The worktree's path, as ``main`` resolved it

    Returns:
        str | None: The reason, or None when every folder is the runner's own
    """
    target  = worktree.absolute()
    temp    = Path(tempfile.gettempdir()).resolve()
    folders = [folder for folder in reversed(target.parents) if temp in folder.parents] or [target.parent]
    for folder in folders:
        try:
            folder.mkdir(mode = 0o700)
        except FileExistsError:
            pass
        except OSError as error:
            return f"{folder} could not be made, {error.strerror}"
        found = os.lstat(folder)
        if stat.S_ISLNK(found.st_mode) or folder.is_junction():
            return f"{folder} is a link, the worktree stands in a folder of the runner's own"
        if not stat.S_ISDIR(found.st_mode):
            return f"{folder} is not a folder"
        if sys.platform != "win32" and found.st_uid != os.getuid():
            return f"{folder} is another user's, name a --worktree in a folder of your own"
        if sys.platform != "win32" and found.st_mode & 0o022:
            return f"{folder} is writable by other users, chmod go-w it or name a --worktree in a folder of your own"
    return None


def prepare_worktree(worktree: Path) -> int:
    """
    Bring the lane's worktree to the repo's HEAD plus every uncommitted change in the working tree.

    Args:
        worktree: The worktree's path, created when missing

    Returns:
        int: How many changed files were copied or removed

    Raises:
        WorktreeError: The path is not one a runner may force a checkout in and clean, or git refused a command
    """
    problem = worktree_problem(worktree)
    if problem is not None:
        raise WorktreeError(problem)
    problem = own_folders(worktree)
    if problem is not None:
        raise WorktreeError(problem)
    head = _git("rev-parse", "HEAD", cwd = REPO_ROOT).decode("ascii").strip()
    if not worktree.exists():
        # the add must succeed, a path that appeared since the judgement makes git refuse it and is never taken as
        # a worktree already prepared
        try:
            _git("worktree", "add", "--detach", str(worktree), head, cwd = REPO_ROOT)
        except subprocess.CalledProcessError as error:
            raise WorktreeError(f"{worktree} could not be added as a worktree, {_said(error)}") from error
        git_dir = _git_path("rev-parse", "--absolute-git-dir", cwd = worktree)
        (git_dir / WORKTREE_MARK).write_text(str(worktree.resolve()), encoding = "utf-8")
    _act(worktree, "checkout", "--detach", "--force", head)
    _act(worktree, "clean", "-fdx", "--quiet")
    synced = 0
    for relative in changed_paths(_git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd = REPO_ROOT)):
        if Path(relative).name.startswith(".env"):
            continue
        source, target = REPO_ROOT / relative, worktree / relative
        if source.is_file():
            target.parent.mkdir(parents = True, exist_ok = True)
            shutil.copy2(source, target)
        elif target.is_file():
            target.unlink()
        synced += 1
    if (REPO_ROOT / ".env.test").is_file():
        shutil.copy2(REPO_ROOT / ".env.test", worktree / ".env.test")
    return synced

# ======================================================================================================================
# Running
# ======================================================================================================================

def suite_environment(suite: str, worktree: Path | None = None) -> dict[str, str]:
    """
    The environment a suite's pytest run gets.

    Args:
        suite: ``unit``, ``integration`` or ``system``
        worktree: The worktree the run happens in, when there is one. A worktree that holds a ``src`` directory
            gets it first on the import path, ahead of an editable install of the repo itself

    Returns:
        dict[str, str]: This process's environment with the suite's settings

    Raises:
        MutantTableError: The suite's database variable is unset, or the repo's unit settings are not names to strings
    """
    # no bytecode is written, CPython trusts a cached .pyc by the source's size and its mtime in whole seconds, so a
    # mutant that left its file the size the previous one did, written within that second, ran the previous one's code
    env      = {**os.environ, "PYTHONUTF8": "1", "HYPOTHESIS_PROFILE": "ci", "PYTHONDONTWRITEBYTECODE": "1"}
    variable = _SUITE_DATABASE_VARIABLE.get(suite)
    if variable is not None and not os.environ.get(variable):
        raise MutantTableError(f"a {suite} mutant needs {variable}, naming the lane's own database")
    if suite == "unit":
        env.update(unit_settings(env))
    # a src layout repo is installed editable from the repo itself, so without this every test in the worktree
    # would import the unmutated package and every mutant of it would read as survived
    if worktree is not None and (worktree / "src").is_dir():
        inherited = os.environ.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join([str(worktree / "src"), *([inherited] if inherited else [])])
    return env


def run_pytest(worktree: Path, suite: str, tests: Sequence[str], timeout: int) -> tuple[int | None, str]:
    """
    Run tests inside the worktree with this interpreter.

    Args:
        worktree: The worktree
        suite: The suite the tests belong to
        tests: pytest paths or node ids
        timeout: Seconds before the run is abandoned

    Returns:
        tuple[int | None, str]: The exit status, None on a timeout, and the output
    """
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-x",
        "-q",
        "--tb=line",
        "-p",
        "no:cacheprovider",
        "-o",
        "log_cli=false",
    ]
    try:
        done = subprocess.run(
            command,
            cwd = str(worktree),
            env = suite_environment(suite, worktree),
            capture_output = True,
            text = True,
            encoding = "utf-8",
            errors = "replace",
            timeout = timeout,
        )
    except subprocess.TimeoutExpired:
        return None, ""
    return done.returncode, done.stdout + done.stderr


def _masked(output: str) -> str:
    """
    Output with every database URL this process holds replaced.

    Args:
        output: Text a child printed

    Returns:
        str: The text, safe to print
    """
    for variable in _SUITE_DATABASE_VARIABLE.values():
        value = os.environ.get(variable)
        if value:
            output = output.replace(value, f"<{variable}>")
    return output


@dataclass
class Result:
    """
    What one mutant's run found.
    """
    id:      str
    result:  str
    seconds: float
    rule:    str
    detail:  str = ""


def restore(worktree: Path, relative: str, original: bytes) -> None:
    """
    Put a mutated file's original bytes back, by a new file beside it that replaces the directory entry.

    SECURITY: the tests ran in between and may have put anything at the path or in its folder's place, a link to a
    file outside the worktree for one, which a write would follow, or at a sibling name a test could guess. The folder
    is asked again to stand inside the worktree, the original is written to a file made exclusively under a name no
    test knows, and that file replaces the entry, so whatever stood there is dropped and never written through.

    Args:
        worktree: The worktree
        relative: The mutated file, repo relative
        original: Its bytes before the mutant

    Raises:
        RuntimeError: The file was not restored, the run cannot go on in this worktree
    """
    path   = worktree / relative
    top    = worktree.resolve()
    folder = path.parent.resolve()
    if top != folder and top not in folder.parents:
        raise RuntimeError(f"{relative} was not restored, its folder leads out of {worktree}")
    handle, made = tempfile.mkstemp(dir = path.parent, prefix = ".kdf-restore-")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(original)
        os.replace(made, path)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.unlink(made)
        raise RuntimeError(f"{relative} was not restored in {worktree}, {error.strerror}") from error
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(original).digest():
        raise RuntimeError(f"{relative} was not restored in {worktree}")


def run_mutant(worktree: Path, mutant: Mutant, timeout: int) -> Result:
    """
    Apply one mutant, run its tests and restore every file it touched.

    Args:
        worktree: The prepared worktree
        mutant: The mutant
        timeout: Seconds before its test run is abandoned

    Returns:
        Result: Its result
    """
    started = time.monotonic()
    path    = worktree / mutant.file
    # a link in the worktree that leads out of it is followed by a write, so the place the mutant lands is asked
    if worktree.resolve() not in path.resolve().parents:
        return Result(mutant.id, "error, its file leads out of the worktree", 0.0, mutant.rule)
    original = path.read_bytes()
    mutated, status = apply_mutant(original.decode("utf-8"), mutant)
    if mutated is None:
        return Result(mutant.id, f"error, anchor {status}", 0.0, mutant.rule)
    try:
        path.write_bytes(mutated.encode("utf-8"))
        if mutant.bundle:
            compacted = subprocess.run(
                [sys.executable, "scripts/vercel_compactor.py", "--skip-import-check"],
                cwd = str(worktree),
                env = suite_environment("unit"),
                capture_output = True,
                text = True,
                encoding = "utf-8",
                errors = "replace",
            )
            if compacted.returncode != 0:
                tail = _masked(compacted.stdout + compacted.stderr)[-600:]
                return Result(
                    mutant.id,
                    "error, the compactor refused the mutant",
                    time.monotonic() - started,
                    mutant.rule,
                    tail,
                )
        returncode, output = run_pytest(worktree, mutant.suite, mutant.tests, timeout)
        result = classify(returncode, output)
        detail = "" if result == "killed" else _masked(output)[-600:]
        return Result(mutant.id, result, round(time.monotonic() - started, 1), mutant.rule, detail)
    finally:
        restore(worktree, mutant.file, original)
        if mutant.bundle:
            for relative in _BUNDLE_OUTPUTS:
                source, target = REPO_ROOT / relative, worktree / relative
                if source.is_dir():
                    shutil.copytree(
                        source,
                        target,
                        dirs_exist_ok = True,
                        ignore = shutil.ignore_patterns("__pycache__", ".env*"),
                    )
                else:
                    shutil.copy2(source, target)


def summary(results: Sequence[Result]) -> str:
    """
    One line for a run, the kills over the mutants that ran, and what another platform holds.

    Args:
        results: Every mutant's result

    Returns:
        str: The line
    """
    ran    = [result for result in results if not result.result.startswith(NOT_RUN)]
    killed = sum(1 for result in ran if result.result == "killed")
    line   = f"{killed} of {len(ran)} killed"
    if len(ran) != len(results):
        line += f", {len(results) - len(ran)} not run on {sys.platform}"
    return line


def _is_result(record: object) -> bool:
    """
    Whether a loaded value is one record of a results file, the five keys with values of a result's types.

    Args:
        record: One value of the loaded list

    Returns:
        bool: True for a record of a result's shape
    """
    if not isinstance(record, dict) or set(record) != set(_RESULT_TYPES):
        return False
    return all(
        isinstance(record[key], kind) and not isinstance(record[key], bool) for key, kind in _RESULT_TYPES.items()
    )


def is_results_file(path: Path) -> bool:
    """
    Whether a file is a results file this runner wrote, a JSON list of records of a result's shape and nothing else.

    Args:
        path: The file

    Returns:
        bool: True for the runner's own, an empty list included
    """
    try:
        loaded = json.loads(path.read_text(encoding = "utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(loaded, list) and all(_is_result(record) for record in loaded)


def write_results(report: Path, text: str) -> str | None:
    """
    Write the results file beside the worktree, by a new file that replaces the directory entry.

    SECURITY: the run took a while, and the one write outside the worktree lands at a path a test could have put
    anything at since the first look. What stands there is asked again to be a results file of the runner's own, and
    a file made exclusively beside it replaces the entry, so a link there is dropped and never written through.

    Args:
        report: The results file's path
        text: The results, JSON

    Returns:
        str | None: Why the file was not written, or None
    """
    handle, made = tempfile.mkstemp(dir = report.parent, prefix = report.stem + "-", suffix = ".part")
    try:
        with os.fdopen(handle, "w", encoding = "utf-8") as file:
            file.write(text)
        if report.exists() and not is_results_file(report):
            os.unlink(made)
            return f"{report} is not a results file of this runner any more, nothing was written over it"
        os.replace(made, report)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.unlink(made)
        return f"{report} could not be written, {error.strerror}"
    return None


def exit_status(results: Sequence[Result]) -> int:
    """
    The run's exit status, 0 when every mutant that ran was killed.

    Args:
        results: Every mutant's result

    Returns:
        int: 0, or 1 when any survived or could not run
    """
    ran = [result for result in results if not result.result.startswith(NOT_RUN)]
    return 0 if all(result.result == "killed" for result in ran) else 1

# ======================================================================================================================
# Entry Point
# ======================================================================================================================

def build_parser() -> argparse.ArgumentParser:
    """
    The command line.

    Returns:
        argparse.ArgumentParser: The parser
    """
    parser = argparse.ArgumentParser(description = "Run a lane's mutants in a private worktree")
    parser.add_argument("--lane", required = True, help = "the lane, mutation_tests/<lane>.py")
    parser.add_argument("--only", action = "append", default = [], help = "run only this mutant id, repeatable")
    parser.add_argument("--list", action = "store_true", help = "print the table and run nothing")
    parser.add_argument(
        "--worktree",
        type = Path,
        default = None,
        help = "the worktree path, one per repo and lane by default",
    )
    parser.add_argument("--timeout", type = int, default = DEFAULT_TIMEOUT_SECONDS, help = "seconds per mutant")
    parser.add_argument("--remove", action = "store_true", help = "remove the lane's worktree and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the lane's mutants and report.

    Args:
        argv: The arguments, sys.argv by default

    Returns:
        int: The exit status the module docstring describes
    """
    args = build_parser().parse_args(argv)
    # the repo is in the path, two repos hold lanes of one name. Resolved once, here, so the path judged and the path
    # every git command is given, from the checkout, are one
    worktree = (args.worktree or Path(tempfile.gettempdir()) / "kdf-mutation" / REPO_ROOT.name / args.lane).resolve()
    if args.remove:
        # judged first, a forced removal of a developer's own worktree loses its work as a forced checkout does
        problem = worktree_problem(worktree)
        if problem is None and not worktree.exists() and worktree in own_worktrees():
            problem = f"{worktree} is gone but git still lists it, run git worktree prune and then --remove again"
        if problem is None and worktree.exists():
            problem = not_this_runners_worktree(worktree)
        if problem is None and worktree.exists():
            problem = link_problem(worktree)
        if problem is not None:
            print(f"the worktree cannot be removed, {problem}")
            return 2
        if worktree.exists():
            try:
                _git("worktree", "remove", "--force", str(worktree), cwd = REPO_ROOT)
            except subprocess.CalledProcessError as error:
                print(f"the worktree could not be removed, {_said(error)}")
                return 2
        print(f"removed {worktree}")
        return 0
    # the results land beside the worktree, the one write outside it, so what stands there is read first and only
    # a results file of the runner's own is written over
    report = worktree.parent / f"mutation-{args.lane}.json"
    if report.exists() and not is_results_file(report):
        print(f"{report} is not a results file of this runner, move it or name another worktree")
        return 2
    try:
        mutants = load_table(args.lane)
    except MutantTableError as error:
        print(f"invalid table, {error}")
        return 2
    if args.only:
        unknown = set(args.only) - {mutant.id for mutant in mutants}
        if unknown:
            print(f"no such mutant {sorted(unknown)}")
            return 2
        mutants = [mutant for mutant in mutants if mutant.id in args.only]
    if args.list:
        for mutant in mutants:
            print(f"{mutant.id:12} {mutant.suite:12} {mutant.file}  {mutant.rule}")
        return 0

    try:
        for suite in sorted({mutant.suite for mutant in mutants if mutant.runs_here()}):
            suite_environment(suite)
    except MutantTableError as error:
        print(str(error))
        return 2

    # a mutant of another platform runs nothing, so its suite needs no database and its tests no control run
    here = [mutant for mutant in mutants if mutant.runs_here()]

    try:
        synced = prepare_worktree(worktree)
    except WorktreeError as error:
        print(f"the worktree cannot be used, {error}")
        return 2
    print(f"worktree {worktree}, {synced} changed files copied in")
    for suite in sorted({mutant.suite for mutant in here}):
        tests = sorted({test for mutant in here if mutant.suite == suite for test in mutant.tests})
        returncode, output = run_pytest(worktree, suite, tests, args.timeout * 2)
        if returncode != 0 or not _TESTS_RAN.search(output):
            print(f"the {suite} control run is red or ran nothing, so no mutant result would mean anything")
            print(_masked(output)[-1500:])
            return 2
        print(f"{suite} control run green, {len(tests)} test paths")

    results = []
    for mutant in mutants:
        if mutant.runs_here():
            try:
                result = run_mutant(worktree, mutant, args.timeout)
            except RuntimeError as error:
                print(f"the run stopped, {error}")
                return 2
        else:
            result = Result(mutant.id, f"{NOT_RUN}, {mutant.platform} only", 0.0, mutant.rule)
        results.append(result)
        print(f"{result.id:12} {result.result:32} {result.seconds:7.1f} s  {result.rule}", flush = True)
        if result.detail:
            print("    " + result.detail.replace("\n", "\n    "))

    problem = write_results(report, json.dumps([asdict(result) for result in results], indent = 2))
    if problem is not None:
        print(problem)
        return 2
    print(f"{summary(results)}, results in {report}")
    return exit_status(results)


if __name__ == "__main__":
    sys.exit(main())
