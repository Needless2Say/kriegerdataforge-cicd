"""
The harness of the local code scan's fixtures (D-085, design 5.9), run by `make scan-fixtures` against an image, the
exact digest a pin names or `kdf-scan:dev` built from the tree, at every pin move, never by `make ci`, whose pytest
collects no fixture_*.py.

Each fixture builds a small git repo under its temp folder, its Makefile holding the managed scan block the scripts
sync writes, its first commit as origin/main, and runs the image on it as `make scan` does, the network off, the root
read only, no capability and a user that is not root, the working tree, its git folder and the rules' cache mounted
read only, then reads the report and the last line. KDF_SCAN_FIXTURE_IMAGE names the image, kdf-scan:dev unless set,
and KDF_SCAN_FIXTURE_RULES the rules' cache, the one `make scan-setup` fills unless set. The vulnerable files are
written fresh for cicd and name rule ids alone, never copied from the test files of Semgrep's licensed rules, row L25.
These fixtures read Semgrep's rules, so they run on the owner's machines and never in the public cicd's log.
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
from tests.scan_fakes import ACTIVE, COMMON, commit, git, init_repo, write

IMAGE    = os.environ.get("KDF_SCAN_FIXTURE_IMAGE", "kdf-scan:dev")
RULES    = Path(os.environ.get("KDF_SCAN_FIXTURE_RULES", Path.home() / ".cache" / "kdf-scan" / "semgrep-rules.git"))
GIT      = shutil.which("git")
DOCKER   = shutil.which("docker")
LOCKED   = (
    "--rm",
    "--network",
    "none",
    "--read-only",
    "--tmpfs",
    "/run/kdf-scan:exec,size=1g",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    "--user",
    "65532:65532",
)
LAST     = re.compile(
    r"kdf-scan (?P<commit>\S+) (?:(?P<state>clean-tree|dirty-tree|at-commit) image (?P<image>\S+) .*? limits "
    r"(?P<limits>\d+)(?: marks (?P<marks>\S+))?: )?(?P<result>.+) \(exit (?P<code>\d)\)"
)
FAIL     = re.compile(r"^FAIL      (?P<path>\S+?):(?P<line>\d+)  (?P<rule>\S+)", re.MULTILINE)
ACCEPTED = re.compile(r"^ACCEPTED  (?P<path>\S+?):(?P<line>\d+)  (?P<rule>\S+)", re.MULTILINE)
BAD      = re.compile(r"^BAD       (?P<path>\S+?):(?P<line>\d+)  (?P<why>.+)$", re.MULTILINE)


@dataclass
class Result:
    """
    One run of the image, its exit code, its whole output and its last line read.
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
    The image a fixture runs and the rules' cache it mounts.
    """
    image: str
    rules: Path


def installed(image: str = IMAGE) -> Machine:
    """
    The image under test, failing the fixture run when it is not on this machine or the rules' cache is missing.
    """
    if DOCKER is None:
        pytest.fail("no docker on this machine, the scan's one prerequisite", pytrace = False)
    found = subprocess.run(["docker", "image", "inspect", image], capture_output = True, check = False)
    if found.returncode != 0:
        pytest.fail(f"no image {image}, make scan-image builds one or make scan-setup pulls the pin", pytrace = False)
    if not RULES.is_dir():
        pytest.fail(f"no rules' cache at {RULES}, make scan-setup fills it", pytrace = False)
    return Machine(image, RULES)


def lines(*parts: str) -> str:
    """
    A file's text from its lines, each given alone, so no fixture's line grows past what the house style allows.
    """
    return "\n".join(parts) + "\n"


def pin(name: str) -> str:
    """
    One plain pin of the tree's kdf_scan.py, as the image's build reads it.
    """
    source = (COMMON / "kdf_scan.py").read_text(encoding = "utf-8")
    found  = re.search(rf'^{name} += "([^"\n]*)"$', source, re.MULTILINE)
    assert found, f"kdf_scan.py names no {name}"
    return found.group(1)


def makefile(*own: str) -> str:
    """
    A Makefile holding the managed block, the repo's own SCAN_EXCLUDE and SCAN_LIMIT lines inside it.
    """
    lines = "".join(f"{line}\n" for line in own)
    return "help:\n\t@echo help\n\n" + ds.SCAN_BLOCK_HEAD + lines + ds.scan_block_tail(ACTIVE)


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


def mounts(machine: Machine, repo: Path) -> list[str]:
    """
    The read only mounts make scan's recipe gives the image, a plain clone's git folder as both of its folders.
    """
    return [
        "-v",
        f"{repo}:/src:ro",
        "-v",
        f"{repo / '.git'}:/gitdir:ro",
        "-v",
        f"{repo / '.git'}:/git:ro",
        "-v",
        f"{machine.rules}:/rules:ro",
    ]


def scan(machine: Machine, repo: Path, *args: str, env: dict[str, str] | None = None, timeout: int = 900) -> Result:
    """
    The image on a repo's working tree as make scan runs it, or at a commit when the arguments open with --at, with
    each name of env set inside the container, a variable that must never reach a scanner.
    """
    named = [part for key, value in (env or {}).items() for part in ("-e", f"{key}={value}")]
    if args[:1] == ("--at",):
        mode = ["at", "--repo", "/src", "--at", args[1], *args[2:]]
    else:
        mode = ["scan", "--autocrlf", "false", *args]
    done = subprocess.run(
        ["docker", "run", *LOCKED, *named, *mounts(machine, repo), machine.image, *mode],
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
