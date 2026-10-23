"""
The harness of the local code scan's fixtures (D-085, design 5.9), run by `make scan-fixtures` against the owner's
installed tools after each install and at every pin move, never by `make ci`, whose pytest collects no fixture_*.py.

Each fixture builds a small git repo under its temp folder, its Makefile holding the managed scan block the scripts
sync writes, its first commit as origin/main, and runs the installed launcher on it as `make scan` does, under the scan
folder's own Python with -I, -S and -B, then reads the report and the last line. KDF_SCAN_ROOT names another scan
folder than D:/KriegerDataForge-scan. The vulnerable files are written fresh for cicd and name rule ids alone, never
copied from the test files of Semgrep's licensed rules, row L25.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import distribute_scripts as ds
import pytest
from tests.scan_fakes import commit, git, init_repo, write

ROOT     = Path(os.environ.get("KDF_SCAN_ROOT", "D:/KriegerDataForge-scan"))
BLOCK    = ds.SCAN_BLOCK_HEAD + ds.SCAN_BLOCK_TAIL
GIT      = shutil.which("git")
VERSION  = re.compile(r'^PYTHON_VERSION += "([0-9.]+)"$', re.MULTILINE)
LAST     = re.compile(
    r"kdf-scan (?P<commit>\S+) (?:(?P<state>clean-tree|dirty-tree|at-commit) bundle (?P<bundle>\S+) .*? limits "
    r"(?P<limits>\d+)(?: marks (?P<marks>\S+))?: )?(?P<result>.+) \(exit (?P<code>\d)\)"
)
FAIL     = re.compile(r"^FAIL      (?P<path>\S+?):(?P<line>\d+)  (?P<rule>\S+)", re.MULTILINE)
ACCEPTED = re.compile(r"^ACCEPTED  (?P<path>\S+?):(?P<line>\d+)  (?P<rule>\S+)", re.MULTILINE)
BAD      = re.compile(r"^BAD       (?P<path>\S+?):(?P<line>\d+)  (?P<why>.+)$", re.MULTILINE)


@dataclass
class Result:
    """
    One run of the installed launcher, its exit code, its whole output and its last line read.
    """
    code: int
    text: str


    @property
    def last(self) -> re.Match[str]:
        line  = self.text.rstrip("\n").splitlines()[-1] if self.text.strip() else ""
        match = LAST.fullmatch(line)
        assert match, f"the last line is not the scan's, {line!r}\n{self.text}"
        return match


    @property
    def result(self) -> str:
        return self.last["result"].split()[0]


    def fails(self) -> set[tuple[str, str]]:
        return {(match["path"], match["rule"]) for match in FAIL.finditer(self.text)}


    def accepted(self) -> set[tuple[str, str]]:
        return {(match["path"], match["rule"]) for match in ACCEPTED.finditer(self.text)}


    def bad(self) -> list[tuple[str, str]]:
        return [(match["path"], match["why"]) for match in BAD.finditer(self.text)]


@dataclass(frozen = True)
class Machine:
    """
    The installed scan folder, its Python, its launcher and its current bundle.
    """
    root:   Path
    python: Path
    bundle: str


    @property
    def launcher(self) -> Path:
        return self.root / "kdf-scan.py"


def installed(root: Path = ROOT) -> Machine:
    """
    The installed machine, failing the fixture run when the owner's install is not there.
    """
    current = root / "current"
    if not current.is_file():
        pytest.fail(f"no install at {root}, the owner installs first, plan owner step 2", pytrace = False)
    bundle = current.read_text(encoding = "ascii").strip()
    source = (root / "bundles" / bundle / "kdf_scan.py").read_text(encoding = "utf-8")
    found  = VERSION.search(source)
    assert found, "the installed bundle's kdf_scan.py names no Python version"
    return Machine(root, root / "python" / found.group(1) / "python.exe", bundle)


def lines(*parts: str) -> str:
    """
    A file's text from its lines, each given alone, so no fixture's line grows past what the house style allows.
    """
    return "\n".join(parts) + "\n"


def pin(machine: Machine, name: str) -> str:
    """
    One plain pin of the installed bundle's kdf_scan.py, as the install's strict pattern reads it.
    """
    source = (machine.root / "bundles" / machine.bundle / "kdf_scan.py").read_text(encoding = "utf-8")
    found  = re.search(rf'^{name} += "([^"\n]+)"$', source, re.MULTILINE)
    assert found, f"the installed bundle names no {name}"
    return found.group(1)


def makefile(*own: str) -> str:
    """
    A Makefile holding the managed block, the repo's own SCAN_EXCLUDE and SCAN_LIMIT lines inside it.
    """
    lines = "".join(f"{line}\n" for line in own)
    return "help:\n\t@echo help\n\n" + ds.SCAN_BLOCK_HEAD + lines + ds.SCAN_BLOCK_TAIL


def make_repo(folder: Path, files: dict[str, str | bytes], own: tuple[str, ...] = (), base: bool = True) -> Path:
    """
    A repo whose first commit holds the Makefile and nothing else, set as origin/main, and whose second holds the
    fixture's files, so the branch's report names them as the branch's own.
    """
    repo = init_repo(folder)
    commit(repo, {"Makefile": makefile(*own), "README.md": "a fixture repo\n"}, "base")
    if base:
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    if files:
        commit(repo, files, "the fixture")
    return repo


def scan(machine: Machine, repo: Path, *args: str, env: dict[str, str] | None = None, timeout: int = 900) -> Result:
    """
    The installed launcher on a repo, as the managed block's recipe runs it.
    """
    command = [str(machine.python), "-I", "-S", "-B", str(machine.launcher), "--repo", str(repo), *args]
    done    = subprocess.run(
        command,
        cwd = repo,
        env = env if env is not None else dict(os.environ),
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        timeout = timeout,
        check = False,
    )
    return Result(done.returncode, done.stdout.decode("utf-8", "replace"))


def status(repo: Path) -> str:
    """
    git status of every file, ignored ones too, which a scan must leave as it found it.
    """
    return git(repo, "status", "--porcelain", "--ignored")
