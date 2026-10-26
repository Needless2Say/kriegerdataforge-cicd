"""
The local code scan's wrapper, Opengrep over the code and zizmor over the workflows, before every pull request (D-085).

The wrapper is the entrypoint of one Linux image cicd builds and every run names by digest, `make scan` on a
developer's machine and the gate on GitHub's runners alike, run with -I, -S and -B as a user that is not root, the
network off and the root read only (design 5.1). So no repo holds a scan script a branch could edit. A local run is a
check against accidents and branch edits and never the gate, since the engine and the recipe answer to the account
that runs them, and the gate is the same image dispatched from each repo's main (design 5.3).

A scan checks both executables and the digest of the rules as the pinned commit's raw blobs give them, the rules read
from a cache of the user's mounted read only, never from the image. Its inventory is every file of a scanned language
and every workflow file, less tests and the repo's declared exclusions, derived inside the container. `scan` reads a
mounted working tree's `git ls-files` and the untracked files git does not ignore, so uncommitted work is scanned too,
each git folder named explicitly and the host's core.autocrlf given. `pr-tree` and `--at` read a commit's
`git ls-tree -r -z` and each raw blob by `git cat-file`, never `git archive`, with replacement refs and lazy fetching
off, and take their exclusions and limits from the base, so a branch cannot widen its own. Each file is copied into the
run's own folder, which the tools read alone, run by absolute path with an environment of named variables. Opengrep
runs with --disable-nosem and zizmor with --no-ignores, and the wrapper checks every marker itself, binding each to a
finding by its place before the policy filters what remains. A file a tool did not read, a parse error, a timeout or a
size skip makes the result incomplete, unless a recorded limit names that file's content.

Exit codes. 0 clean, 1 a finding or a bad suppression, 2 a refusal before scanning, 3 a tool that failed to complete,
4 an incomplete scan. `make` itself returns 2 when its recipe fails, so the last line, not make's status, is the
result. Standard library only, Python 3.12 or later.
"""

from __future__ import annotations

# standard imports
import argparse
import bisect
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tokenize
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Mapping, TextIO

# ======================================================================================================================
# The pins, each with where it was read
# ======================================================================================================================

# where the image keeps the tools and the wrapper's own files, root's and read only at run time (design 5.1)
IMAGE_ROOT = Path("/opt/kdf-scan")
# Opengrep's Linux asset, its name and SHA-256 the owner's match against the release page on 2026-10-26, owner step
# 3, and the exact identity of the workflow that signed the release, read from its certificate on 2026-10-21, a branch
# ref
OPENGREP_VERSION  = "v1.30.2"
OPENGREP_ASSET    = "opengrep_manylinux_x86"
OPENGREP_SHA256   = "a66aa3278457f02b287b985a45b6762aebcaba5000f2689245fd1ed86d1456c7"
OPENGREP_IDENTITY = (
    "https://github.com/opengrep/opengrep/.github/workflows/rolling-release.yml@refs/heads/release-v1.30.2"
)
OPENGREP_ISSUER   = "https://token.actions.githubusercontent.com"
# the asset's release address, its .cert and .sig beside it under the same name
OPENGREP_URL = f"https://github.com/opengrep/opengrep/releases/download/{OPENGREP_VERSION}/{OPENGREP_ASSET}"
# zizmor from PyPI's Linux wheel for x86_64, its address and SHA-256 the owner's read of PyPI's files on 2026-10-26,
# owner step 3, and the program inside it, measured by the image's first build on 2026-10-26 from that wheel
ZIZMOR_VERSION      = "1.30.1"
ZIZMOR_WHEEL_URL    = (
    "https://files.pythonhosted.org/packages/63/55/1900b53d34dcebc207cf3ceb7957b3748e8bb40958f062e3853ab72f2395/"
    "zizmor-1.30.1-py3-none-manylinux_2_28_x86_64.whl"
)
ZIZMOR_WHEEL_SHA256 = "eee12266b793cb87ad4a7e3af2e72404f8a63e3de5eb099b80bf7b1cfd232a8e"
ZIZMOR_SHA256       = "9be5ac955a59e43a111152ee2e0315d3863866a8df4a15a9be7aaa94af72d74a"
# cosign's Linux program, which the image's build runs to verify Opengrep, its SHA-256 the owner's match against the
# release page on 2026-10-26, owner step 3, the 2.6 line, whose verify-blob still takes the separate .sig and .cert Opengrep
# publishes, 3.1's taking a bundle alone, and 2.6.5 the release that carries the fix of GHSA-fx35-mq7g-6g98
COSIGN_VERSION = "v2.6.5"
COSIGN_URL     = "https://github.com/sigstore/cosign/releases/download/v2.6.5/cosign-linux-amd64"
COSIGN_SHA256  = "c3b4f5410e608af03a5eb0aaac84a4313d8da131248e08ff1759ac70c79d1644"
# the rules of Semgrep at the commit the web survey read, the digest of every rule file of RULE_FOLDERS at it, read on
# 2026-10-21 with rules_digest below, and the page of the rules' licence the record keeps whole with its date
RULES_REPO        = "https://github.com/semgrep/semgrep-rules"
RULES_COMMIT      = "17e31e11ebac99fb7dfe1cd288f7a32151b6f3f9"
RULES_DIGEST      = "e2ec51f90a9d26ff7fac7a4a268ad24f935ab357add11304b9da141fc9181ff1"
RULES_LICENSE_URL = "https://semgrep.dev/legal/rules-license"
# the security folders of Semgrep's rules for this stack (design 5.6)
RULE_FOLDERS = (
    "python/lang/security",
    "python/fastapi/security",
    "python/sqlalchemy/security",
    "python/jwt/security",
    "python/requests/security",
    "python/cryptography/security",
    "python/jinja2/security",
    "javascript/lang/security",
    "javascript/browser/security",
    "javascript/jsonwebtoken/security",
    "javascript/jose/security",
    "javascript/node-crypto/security",
    "typescript/lang/security",
    "typescript/react/security",
)

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# the extensions Opengrep reads for the three languages scanned
LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}
# tests stay out of the scan, the owner's answer to design question 7, by folder and by name
TEST_FOLDERS = frozenset({"tests", "test", "__tests__", "unit_tests", "integration_tests", "system_tests"})
TEST_NAMES   = re.compile(r"test_.*\.py|.*_test\.py|conftest\.py|.*\.(?:test|spec)\.(?:js|jsx|mjs|cjs|ts|tsx)")
# the rule policy of design 5.6, the two path rules measured as noise in tooling folders alone, and the logger rule a
# KDF rule replaces
TOOLING_FOLDERS = frozenset({"scripts", "tools", "mutation_tests"})
TOOLING_RULES   = frozenset({"detect-non-literal-fs-filename", "path-join-resolve-traversal"})
REPLACED_RULES  = frozenset({"python-logger-credential-disclosure"})
CONFIDENT       = frozenset({"MEDIUM", "HIGH"})
# a call of cicd's own reusable workflows or actions at main, which the wrapper accepts and zizmor's ref-pin would not
# tell from any other branch (row L13)
CICD_AT_MAIN = re.compile(r"Needless2Say/kriegerdataforge-cicd/[^@\s]+@main")
# the managed block the scripts Distribute writes, and the repo's own lines inside it
BLOCK_OPEN   = "# >>> kdf-scan, managed by cicd's scripts sync"
BLOCK_CLOSE  = "# <<< kdf-scan"
EXCLUDE_LINE = re.compile(r"SCAN_EXCLUDE \+= (?P<path>\S+)\s+#\s*(?P<reason>\S.*?)\s*")
LIMIT_LINE   = re.compile(r"SCAN_LIMIT \+= (?P<path>[^\s@]+)@(?P<sha>[0-9a-f]{64})\s+#\s*(?P<reason>\S.*?)\s*")
# the markers, the one good form of each, and what makes a reason
MARKER       = re.compile(r"(?P<opener>#|//|/\*)\s*(?P<word>nosemgrep|nosem|noopengrep)\b(?P<rest>.*)")
GOOD_MARKER  = re.compile(r":\s*(?P<id>[A-Za-z0-9_.-]+)(?P<more>,\S*)?(?:\s+(?P<reason>.*?))?\s*(?:\*/)?\s*")
ZIZMOR_MARK  = re.compile(r"#\s*zizmor\s*:\s*ignore\b(?P<rest>.*)")
GOOD_ZIZMOR  = re.compile(r"\[(?P<id>[A-Za-z0-9_,-]+)\](?:\s+(?P<reason>.*?))?\s*")
REASON_WORDS = 3
RULE_ID      = re.compile(r"^\s*-\s+id:\s*['\"]?([A-Za-z0-9_.-]+)", re.MULTILINE)
# a marker counts only in a comment, which a reader of the file's kind finds, Codex's read of 2026-10-22, and a file
# whose comments it cannot read whole counts none. Words after which a slash opens a regular expression and a less than
# sign an element, a YAML block scalar's header, and the kinds whose markers are read as text alone, as before
EXPRESSION_WORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield",
    "await",
})
# the words whose parenthesis a statement follows, and the marker words a slash after a brace must not leave unread
CONTROL_WORDS = frozenset({"if", "while", "for", "with"})
MARKER_HINT   = re.compile(r"(?i)nosem|noopengrep|zizmor")
# a line break JavaScript or YAML honours where git's lines do not, which shifts a comment's end, so a file holding one
# has its markers refused (Codex's read of fd624a6)
ODD_BREAK     = re.compile("\r(?!\n)|[  \u0085]")
BLOCK_HEADER  = re.compile(r"[|>][0-9+-]{0,2}(?:[ \t]+(?P<comment>#.*)?)?$")
DOCUMENT      = re.compile(r"---(?:[ \t]|$)")
PROPERTY      = re.compile(r"[&!][^ \t]*")
YAML_SUFFIXES = (".yml", ".yaml")
UNREADABLE    = "its comments could not be read whole, so no marker in it counts"
# a hunk's header in a diff with no context, whose new side gives the lines the branch changed
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", re.MULTILINE)
# what Opengrep and zizmor are given, Semgrep's defaults written out, zizmor's codes for its findings, and whether it
# runs with --no-ignores, which the fixtures settle (the King's F4)
MAX_TARGET_BYTES  = 1000000
RULE_TIMEOUT      = 5
ZIZMOR_EXITS      = frozenset({0, 10, 11, 12, 13, 14})
ZIZMOR_NO_INPUTS  = 3
ZIZMOR_NO_IGNORES = True
ZIZMOR_COMPLETED  = re.compile(r"completed (?P<path>\S.*?)\s*$")
# the only names the scanners' environment holds, every other variable, a token or SEMGREP_RULES, never reaching them,
# each value the wrapper's own, HOME, TMPDIR and the cache inside the run's own folder, so whatever Opengrep's Linux
# build unpacks or logs lands there and goes with the run (Round Table 59's L8, Round Table 66's L8)
TOOL_ENVIRONMENT = ("PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "LANG", "PYTHONUTF8", "NO_COLOR")
TOOL_PATH        = "/usr/local/bin:/usr/bin:/bin"
# whether Opengrep's Linux build unpacks a runtime at run time, as its Windows build does under the profile, held true
# until the image's first build measures it, so a build that unpacks elsewhere stops rather than passes
OPENGREP_UNPACKS = True
# where run folders go, the container's tmpfs, gone with it under --rm, so nothing is swept (Round Table 66's L9), the
# temp folder where it is missing, a test's run
RUN_ROOT   = Path("/run/kdf-scan")
RUN_PREFIX = "kdf-scan-"
# the environment every git call takes instead of the caller's, which neutral_git sets so neither the caller's
# variables nor any global or system configuration reach git, None for a test's own git
NEUTRAL_GIT: dict[str, str] | None = None
# the git folders a scan names explicitly, the paths git may own other than the scan's user, and the host's
# core.autocrlf for a mounted working tree, each set by its mode (Round Table 66's L5)
GIT_FOLDERS: dict[str, dict[str, str]] = {}
SAFE_PATHS:  tuple[str, ...] = ()
AUTOCRLF:    str | None = None
# git as the image installs it
GIT_PATH = "/usr/bin/git"
# the read only mounts each mode reads, the working tree, the common git folder, the rules' cache and a bare repository
# fetched before the scan (design 5.3 and 5.5). A worktree's own git folder is named inside the common one, never
# mounted apart, since git finds a worktree's refs through its commondir file, ../.. from its own folder, and never
# through GIT_COMMON_DIR, measured by the probe of 2026-10-26
SRC_MOUNT    = "/src"
GIT_MOUNT    = "/git"
RULES_MOUNT  = "/rules"
REPO_MOUNT   = "/repo"
# the file the image's build writes, the cicd commit it was built from, and its stand in outside an image
COMMIT_FILE = IMAGE_ROOT / "COMMIT"
# cicd's file naming the active set, each key once (design 5.1), and the marker it holds until the first activation
SCAN_IMAGE_KEYS = ("image", "digest", "commit", "rules_commit", "rules_digest", "contract")
UNPINNED        = "unpinned"
DIGEST          = re.compile(r"sha256:[0-9a-f]{64}")
# the invocation contract this wrapper speaks, its arguments and mounts, which an activation names (design 5.1)
CONTRACT = "1"
# a repository's own configuration that runs a program or reads another file, refused in a mounted working tree,
# since turning hooks and fsmonitor off leaves these to run (Codex's revision plan read)
UNSAFE_CONFIG = re.compile(r"(?i)(?:filter|include|includeif)\..*")
# the gate's caller by its path in every repo, and the names of the gate a pull request's other workflows must not use
CALLER_PATH   = ".github/workflows/kdf-scan-gate.yml"
REUSABLE_PATH = ".github/workflows/kdf-scan-gate-reusable.yml"
GATE_NAMES    = ("kdf-scan-gate-reusable.yml", "kdf-scan-gate:")
# a caller's ci.yml line naming the paths that are not docs, which the docs only answer reads at main
NOT_DOCS = re.compile(r"(?P<indent>\s*)not_docs:\s*(?P<value>.*?)\s*")
BASE_REF = "origin/main"
SETUP    = "make scan-setup"
SHOWN    = 140

# ======================================================================================================================
# The machine
# ======================================================================================================================

class Refusal(Exception):
    """
    A scan refused before it scans, exit 2.
    """


class ToolFailure(Exception):
    """
    A tool that failed to complete or answered outside what it was given, exit 3.
    """


class Unreadable(Exception):
    """
    A file whose comments a reader could not find whole, so none of its markers counts.
    """


@dataclass(frozen = True)
class Tool:
    """
    One program of the image, its version, the file whose SHA-256 is pinned, and the command that runs it.
    """
    name:    str
    version: str
    path:    Path
    sha256:  str
    command: tuple[str, ...]


@dataclass(frozen = True)
class Machine:
    """
    What a scan runs, the tools, the rules' cache at its pinned commit, git, the image's cicd commit and the wrapper's
    own files, whether Semgrep's rules run or KDF's alone, and whether the output is a public repo's.
    """
    root:         Path
    opengrep:     Tool
    zizmor:       Tool
    rules:        Path
    rules_commit: str
    rules_digest: str
    rule_folders: tuple[str, ...]
    git:          str
    image:        str
    files:        Mapping[str, bytes]
    kdf_only: bool = False
    public:   bool = False


def find_git() -> str:
    """
    Git as the image installs it.

    Returns:
        str: git's absolute path

    Raises:
        Refusal: when the image holds no git there
    """
    if Path(GIT_PATH).is_file():
        return GIT_PATH
    raise Refusal(f"no git at {GIT_PATH}, so this is not the scan's image")


def image_commit(root: Path = IMAGE_ROOT) -> str:
    """
    The cicd commit the image was built from, as its build wrote it.

    Args:
        root: the image's folder

    Returns:
        str: the commit, or local outside a built image or for one built with no commit named
    """
    try:
        named = (root / COMMIT_FILE.name).read_text(encoding = "ascii").strip()
    except (OSError, UnicodeDecodeError):
        return "local"
    return named if re.fullmatch(r"[0-9a-f]{40}", named) else "local"


def image_files(root: Path = IMAGE_ROOT) -> dict[str, bytes]:
    """
    The wrapper's own files as the image holds them beside it, its zizmor configuration, ci_paths.py and KDF's rules.

    Args:
        root: the image's folder, or a source tree's scripts/common

    Returns:
        dict[str, bytes]: each file by its path beside the wrapper
    """
    files = {name: (root / name).read_bytes() for name in ("kdf_zizmor.yml", "ci_paths.py") if (root / name).is_file()}
    for rule in sorted((root / "scan_rules").glob("*")):
        if rule.is_file():
            files[f"scan_rules/{rule.name}"] = rule.read_bytes()
    return files


def machine(
    root: Path,
    image: str,
    files: Mapping[str, bytes],
    git: str,
    rules: Path,
    kdf_only: bool = False,
    public: bool = False,
) -> Machine:
    """
    The image's machine the pins describe.

    Args:
        root: the image's folder
        image: the cicd commit the image was built from, or dev
        files: the wrapper's own files by their path beside it
        git: git's absolute path
        rules: the rules' cache, a git folder holding the pinned commit
        kdf_only: whether KDF's rules run alone
        public: whether the output is a public repo's, rule ids and never a message

    Returns:
        Machine: the machine
    """
    opengrep = root / "bin" / "opengrep"
    zizmor   = root / "bin" / "zizmor"
    return Machine(
        root = root,
        opengrep = Tool("opengrep", OPENGREP_VERSION.removeprefix("v"), opengrep, OPENGREP_SHA256, (str(opengrep),)),
        zizmor = Tool("zizmor", ZIZMOR_VERSION, zizmor, ZIZMOR_SHA256, (str(zizmor),)),
        rules = rules,
        rules_commit = RULES_COMMIT,
        rules_digest = RULES_DIGEST,
        rule_folders = RULE_FOLDERS,
        git = git,
        image = image,
        files = files,
        kdf_only = kdf_only,
        public = public,
    )


def pins() -> dict[str, str]:
    """
    The declared pins, which the image's build reads before it downloads anything.

    Returns:
        dict[str, str]: each pin by its name
    """
    names = (
        "OPENGREP_VERSION",
        "OPENGREP_ASSET",
        "OPENGREP_SHA256",
        "OPENGREP_IDENTITY",
        "OPENGREP_ISSUER",
        "OPENGREP_URL",
        "ZIZMOR_VERSION",
        "ZIZMOR_WHEEL_URL",
        "ZIZMOR_WHEEL_SHA256",
        "ZIZMOR_SHA256",
        "COSIGN_VERSION",
        "COSIGN_URL",
        "COSIGN_SHA256",
        "RULES_REPO",
        "RULES_COMMIT",
        "RULES_DIGEST",
        "RULES_LICENSE_URL",
        "CONTRACT",
    )
    return {name: str(globals()[name]) for name in names}


def file_sha256(path: Path) -> str:
    """
    A file's SHA-256, read in chunks.

    Args:
        path: the file

    Returns:
        str: its hex digest, empty when it cannot be read
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def content_sha256(data: bytes) -> str:
    """
    The SHA-256 a recorded limit names, of a file's content with CRLF read as LF, so a checkout's line endings never
    change it.

    Args:
        data: the content

    Returns:
        str: its hex digest
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

# ======================================================================================================================
# Git, read with replacement refs and lazy fetching off
# ======================================================================================================================

def neutral_git(work: Path) -> dict[str, str]:
    """
    A git environment of the run's own, the image's folders alone on the PATH, no system configuration and an empty
    global one in the run's folder, so nothing of the caller's reaches git (Round Table 59's L9 and L10).

    Args:
        work: the run's folder

    Returns:
        dict[str, str]: the environment, which the caller sets as NEUTRAL_GIT
    """
    (work / "empty.gitconfig").write_bytes(b"")
    environment = {
        "PATH": TOOL_PATH,
        "HOME": str(work),
        "TMPDIR": str(work),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(work / "empty.gitconfig"),
        "GIT_ATTR_NOSYSTEM": "1",
    }
    if os.name == "nt":
        # a test's run on Windows, whose programs cannot start without these
        environment.update({name: os.environ[name] for name in ("SYSTEMROOT", "PATH") if name in os.environ})
    return environment


def git_environment(repo: Path | None = None) -> dict[str, str]:
    """
    The environment of every git call, no inherited GIT_ variable, the git folders a mode names for that repo alone,
    so the rules' cache is never read through a working tree's folders, replacement objects and lazy fetching off, and
    no optional lock, so a read never writes the index, NEUTRAL_GIT in place of the caller's when it is set.

    Args:
        repo: the repo the call reads, whose named git folders apply

    Returns:
        dict[str, str]: the environment
    """
    environment = (dict(NEUTRAL_GIT) if NEUTRAL_GIT is not None
                   else {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")})
    if repo is not None:
        environment.update(GIT_FOLDERS.get(str(repo), {}))
    environment.update({
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def run_git(git: str, repo: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """
    One git call, never fetching, never honouring a replacement ref, never running an fsmonitor or a hook, and trusting
    another owner's folder only at the paths a mode names.

    Args:
        git: git's absolute path
        repo: the repo or git folder
        *args: git's arguments
        stdin: what git reads, when anything

    Returns:
        subprocess.CompletedProcess[bytes]: the finished call, its status unchecked
    """
    command = [git, "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.quotePath=false"]
    command += ["-c", f"core.hooksPath={os.devnull}"]
    for path in SAFE_PATHS:
        command += ["-c", f"safe.directory={path}"]
    if AUTOCRLF is not None:
        command += ["-c", f"core.autocrlf={AUTOCRLF}"]
    return subprocess.run(
        [*command, "-C", str(repo), *args],
        input = stdin,
        capture_output = True,
        env = git_environment(repo),
        check = False,
    )


def git_out(git: str, repo: Path, *args: str) -> bytes:
    """
    One git call's output, its status checked.

    Args:
        git: git's absolute path
        repo: the repo or git folder
        *args: git's arguments

    Returns:
        bytes: its output

    Raises:
        Refusal: when git exits other than 0
    """
    done = run_git(git, repo, *args)
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Refusal(f"git {args[0]} failed, {said[-1] if said else f'exit {done.returncode}'}")
    return done.stdout


def split_z(output: bytes) -> list[str]:
    """
    A git listing written with -z, split on NUL.

    Args:
        output: git's output

    Returns:
        list[str]: each record, bytes that are not UTF-8 kept as surrogates
    """
    return [part.decode("utf-8", "surrogateescape") for part in output.split(b"\0") if part]


def resolve(git: str, repo: Path, ref: str) -> str | None:
    """
    A ref's commit, or None when it names none.

    Args:
        git: git's absolute path
        repo: the repo
        ref: the ref or commit

    Returns:
        str | None: the full commit id
    """
    done = run_git(git, repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    if done.returncode != 0:
        return None
    return done.stdout.decode("ascii", "replace").strip() or None


def read_blobs(git: str, repo: Path, oids: list[str]) -> dict[str, bytes | None]:
    """
    Raw blobs by object id through one git cat-file --batch, a missing object None and never fetched.

    Args:
        git: git's absolute path
        repo: the repo or git folder
        oids: the object ids

    Returns:
        dict[str, bytes | None]: each blob, None when it is missing or not a blob

    Raises:
        Refusal: when git fails, or its answer is cut short, malformed or longer than the ids asked
    """
    unique = list(dict.fromkeys(oids))
    if not unique:
        return {}
    done = run_git(git, repo, "cat-file", "--batch", stdin = "".join(f"{oid}\n" for oid in unique).encode())
    if done.returncode != 0:
        raise Refusal(f"git cat-file failed, {tail(done.stderr)}")
    output   = done.stdout
    found    = {}
    position = 0
    for oid in unique:
        end = output.find(b"\n", position)
        if end < 0:
            raise Refusal("git cat-file's answer was cut short")
        header   = output[position:end].decode("ascii", "replace").split()
        position = end + 1
        if len(header) == 2 and header[1] == "missing":
            found[oid] = None
            continue
        if len(header) != 3 or header[0] != oid or not header[2].isdigit():
            raise Refusal("git cat-file's answer could not be read")
        # every body whole, its declared length and the line feed after it, so a cut answer never reads as a short file
        size = int(header[2])
        if output[position + size:position + size + 1] != b"\n":
            raise Refusal(f"git cat-file's answer for {oid[:12]} was cut short")
        found[oid] = output[position:position + size] if header[1] == "blob" else None
        position  += size + 1
    if position != len(output):
        raise Refusal("git cat-file answered more than it was asked")
    return found


def blob_at(git: str, repo: Path, commit: str, path: str) -> bytes | None:
    """
    One file's content at a commit, or None when the commit holds no such file.

    Args:
        git: git's absolute path
        repo: the repo
        commit: the commit
        path: the file's path

    Returns:
        bytes | None: its content
    """
    done = run_git(git, repo, "cat-file", "blob", f"{commit}:{path}")
    return done.stdout if done.returncode == 0 else None

# ======================================================================================================================
# The rules, materialised from the pinned commit's raw blobs
# ======================================================================================================================

def rule_files(git: str, rules: Path, commit: str, folders: tuple[str, ...]) -> dict[str, bytes]:
    """
    Every rule file of the rule folders at the pinned commit, read from its tree and its raw blobs alone, so neither a
    working tree nor an index flag of the clone changes them.

    Args:
        git: git's absolute path
        rules: the rules clone, bare or not
        commit: the pinned commit
        folders: the rule folders

    Returns:
        dict[str, bytes]: each rule file by its path

    Raises:
        Refusal: when the commit, a folder or a blob is missing, or a folder holds a link
    """
    if resolve(git, rules, commit) != commit:
        raise Refusal(f"the rules clone has no commit {commit}")
    records = split_z(git_out(git, rules, "ls-tree", "-r", "-z", commit, "--", *folders))
    entries = {}
    for record in records:
        meta, path = record.split("\t", 1)
        mode, _kind, oid = meta.split(" ")
        if not path.endswith((".yaml", ".yml")):
            continue
        if mode not in ("100644", "100755"):
            raise Refusal(f"a rule folder holds a link at {path}")
        entries[path] = oid
    for folder in folders:
        if not any(path.startswith(f"{folder}/") for path in entries):
            raise Refusal(f"the pinned commit holds no rules under {folder}")
    blobs = read_blobs(git, rules, list(entries.values()))
    files = {}
    for path, oid in entries.items():
        if blobs.get(oid) is None:
            raise Refusal(f"the rules clone is missing {path}")
        files[path] = blobs[oid]
    return files


def rules_digest(files: Mapping[str, bytes]) -> str:
    """
    One SHA-256 over the sorted paths and contents of the rule files, each length framed.

    Args:
        files: each rule file by its path

    Returns:
        str: the digest
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        data = files[path]
        digest.update(f"{path}\0{len(data)}\0".encode("utf-8", "surrogateescape"))
        digest.update(data)
    return digest.hexdigest()


def rule_ids(files: Mapping[str, bytes]) -> dict[str, int]:
    """
    How many rules run under each rule id's last part, so a marker naming one shared by two is refused.

    Args:
        files: each rule file by its path

    Returns:
        dict[str, int]: the count under each id
    """
    counts: dict[str, int] = {}
    for data in files.values():
        for rule in RULE_ID.findall(data.decode("utf-8", "replace")):
            counts[rule] = counts.get(rule, 0) + 1
    return counts

# ======================================================================================================================
# The repo's policy, read from the managed block
# ======================================================================================================================

@dataclass(frozen = True)
class Policy:
    """
    The repo's own lines in the managed block, its exclusions and limits, and the block's other lines, the target.
    """
    excludes: tuple[tuple[str, str], ...] = ()
    limits:   tuple[tuple[str, str, str], ...] = ()
    target:   tuple[str, ...] = ()


def plain_path(path: str) -> bool:
    """
    Whether a path is a plain repo relative path that is safe to write on Windows.

    Args:
        path: the path

    Returns:
        bool: True when no part is empty, `.` or `..` and none holds a backslash, colon or control character
    """
    if not path or path.startswith("/") or any(char in path for char in "\\:*?\"<>|") or not path.isprintable():
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def good_reason(reason: str | None) -> str:
    """
    Why a reason is refused, or nothing when it is good.

    Args:
        reason: the reason

    Returns:
        str: the refusal, empty when the reason holds three words or more and no comma
    """
    if not reason:
        return "it gives no reason"
    if "," in reason:
        return "its reason holds a comma, which Opengrep reads as another rule"
    if len(reason.split()) < REASON_WORDS:
        return "its reason holds fewer than three words"
    return ""


def parse_policy(text: str | None) -> Policy:
    """
    The repo's policy from a Makefile's text, none when it holds no managed block.

    Args:
        text: the Makefile's text, or None when there is none

    Returns:
        Policy: its exclusions, limits and target lines

    Raises:
        Refusal: when the block is doubled, unclosed or holds a malformed line of the repo's own
    """
    lines  = (text or "").replace("\r\n", "\n").split("\n")
    opened = [index for index, line in enumerate(lines) if line.rstrip() == BLOCK_OPEN]
    if not opened:
        return Policy()
    if len(opened) > 1:
        raise Refusal("the Makefile holds two managed scan blocks")
    closed = [index for index, line in enumerate(lines) if line.rstrip() == BLOCK_CLOSE and index > opened[0]]
    if not closed:
        raise Refusal("the Makefile's managed scan block is never closed")
    excludes, limits, target = [], [], []
    for line in lines[opened[0] + 1:closed[0]]:
        if line.startswith("SCAN_EXCLUDE +="):
            match = EXCLUDE_LINE.fullmatch(line)
            path  = match["path"].rstrip("/") if match else ""
            why   = good_reason(match["reason"]) if match else "it is not SCAN_EXCLUDE += <path>  # <reason>"
            if not why and not plain_path(path):
                why = "its path is not a plain path in the repo"
            if why:
                raise Refusal(f"a SCAN_EXCLUDE line is refused, {why}, {line.strip()}")
            excludes.append((path, match["reason"]))
        elif line.startswith("SCAN_LIMIT"):
            match = LIMIT_LINE.fullmatch(line)
            why   = good_reason(match["reason"]) if match else "it is not SCAN_LIMIT += <path>@<sha256>  # <reason>"
            if not why and not plain_path(match["path"]):
                why = "its path is not a plain path in the repo"
            if why:
                raise Refusal(f"a SCAN_LIMIT line is refused, {why}, {line.strip()}")
            limits.append((match["path"], match["sha"], match["reason"]))
        else:
            target.append(line.rstrip())
    return Policy(tuple(excludes), tuple(limits), tuple(target))


def excluded(path: str, policy: Policy) -> str | None:
    """
    The declared exclusion a path falls under, if any.

    Args:
        path: the repo relative path
        policy: the repo's policy

    Returns:
        str | None: the exclusion's path
    """
    for folder, _reason in policy.excludes:
        if path == folder or path.startswith(f"{folder}/"):
            return folder
    return None

# ======================================================================================================================
# The inventory
# ======================================================================================================================

def is_test(path: str) -> bool:
    """
    Whether a path is a test, by a folder of tests or a test's name.

    Args:
        path: the repo relative path

    Returns:
        bool: True for a test
    """
    parts = path.split("/")
    return any(part in TEST_FOLDERS for part in parts[:-1]) or bool(TEST_NAMES.fullmatch(parts[-1]))


def is_workflow(path: str) -> bool:
    """
    Whether a path is a file zizmor audits under `.github/`, a workflow, an action or Dependabot's configuration.

    Args:
        path: the repo relative path

    Returns:
        bool: True for such a file
    """
    parts = path.split("/")
    if parts[0] != ".github" or len(parts) < 2:
        return False
    if len(parts) == 3 and parts[1] == "workflows" and parts[2].endswith((".yml", ".yaml")):
        return True
    if len(parts) == 2 and parts[1] in ("dependabot.yml", "dependabot.yaml"):
        return True
    return parts[-1] in ("action.yml", "action.yaml")


@dataclass
class Inventory:
    """
    The files a scan reads, the code it scans, the excluded code it reads for markers alone, and the workflows.
    """
    commit:     str
    state:      str
    code:       dict[str, bytes] = field(default_factory = dict)
    excluded:   dict[str, bytes] = field(default_factory = dict)
    workflows:  dict[str, bytes] = field(default_factory = dict)
    incomplete: list[str] = field(default_factory = list)


def sort_entry(inventory: Inventory, policy: Policy, path: str, mode: str) -> str | None:
    """
    Where one entry belongs, a link or a gitlink in a scanned place recorded as incomplete.

    Args:
        inventory: the inventory being built
        policy: the policy whose exclusions apply
        path: the repo relative path
        mode: git's mode for it

    Returns:
        str | None: code, excluded or workflow, or None when the scan does not read it

    Raises:
        Refusal: for a .semgrepignore, since the inventory alone decides what is read
    """
    if path.rsplit("/", 1)[-1] == ".semgrepignore":
        raise Refusal(f"the repo holds {path}, refused since the inventory alone decides what is read")
    if is_test(path):
        return None
    kind = "workflow" if is_workflow(path) else "code" if Path(path).suffix in LANGUAGES else None
    if excluded(path, policy):
        return "excluded" if kind == "code" and mode not in ("120000", "160000") else None
    if mode == "160000":
        inventory.incomplete.append(f"{path} is a gitlink, whose files the scan cannot read")
        return None
    if kind and mode == "120000":
        inventory.incomplete.append(f"{path} is a symlink, whose target the scan never reads as code")
        return None
    if kind and not plain_path(path):
        inventory.incomplete.append(f"{path!r} is not a plain path the scan can copy")
        return None
    return kind


def place(inventory: Inventory, kind: str | None, path: str, data: bytes | None) -> None:
    """
    Keep one file's content where its kind belongs, a missing one recorded as incomplete.

    Args:
        inventory: the inventory being built
        kind: code, excluded or workflow, or None
        path: the repo relative path
        data: its content, None when it could not be read
    """
    if kind is None:
        return
    if data is None:
        inventory.incomplete.append(f"{path} could not be read, a missing object is never fetched")
        return
    {"code": inventory.code, "excluded": inventory.excluded, "workflow": inventory.workflows}[kind][path] = data


def worktree_inventory(git: str, repo: Path, policy: Policy) -> Inventory:
    """
    The working tree's inventory, tracked files and the untracked ones git does not ignore, read from disk.

    Args:
        git: git's absolute path
        repo: the repo
        policy: the policy whose exclusions apply

    Returns:
        Inventory: the inventory

    Raises:
        Refusal: when the repo has no commit or holds a .semgrepignore
    """
    head = resolve(git, repo, "HEAD")
    if head is None:
        # git's own words and the folders it read, since a mount it cannot read or join refuses as plainly as a repo
        # with no commit
        said    = run_git(git, repo, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
        folders = run_git(git, repo, "rev-parse", "--git-dir", "--git-common-dir").stdout.decode("utf-8", "replace")
        named   = run_git(git, repo, "symbolic-ref", "-q", "HEAD").stdout.decode("utf-8", "replace").strip()
        raise Refusal(
            f"the repo has no commit to name, {tail(said.stderr)}, git read {' and '.join(folders.split()) or 'no git'}"
            f" folder, HEAD naming {named or 'no branch'}",
        )
    dirty     = git_out(git, repo, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    inventory = Inventory(head, "dirty-tree" if dirty else "clean-tree")
    entries   = {}
    for record in split_z(git_out(git, repo, "ls-files", "-s", "-z")):
        meta, path = record.split("\t", 1)
        entries[path] = meta.split(" ")[0]
    for path in split_z(git_out(git, repo, "ls-files", "-z", "--others", "--exclude-standard")):
        entries.setdefault(path, "100644")
    for path, mode in sorted(entries.items()):
        local = repo / path
        if not os.path.lexists(local):
            continue
        if local.is_symlink():
            mode = "120000"
        kind = sort_entry(inventory, policy, path, mode)
        try:
            data = local.read_bytes() if kind else None
        except OSError:
            data = None
        place(inventory, kind, path, data)
    return inventory


def commit_inventory(git: str, repo: Path, commit: str, policy: Policy) -> Inventory:
    """
    A commit's inventory from its tree and its raw blobs, never the working tree and never git archive. A
    .semgrepignore in the commit raises sort_entry's Refusal.

    Args:
        git: git's absolute path
        repo: the repo
        commit: the resolved commit
        policy: the policy whose exclusions apply

    Returns:
        Inventory: the inventory, incomplete when the tree or a blob cannot be read
    """
    inventory = Inventory(commit, "at-commit")
    listing   = run_git(git, repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    if listing.returncode != 0:
        inventory.incomplete.append("the commit's tree could not be read, a missing object is never fetched")
        return inventory
    wanted = []
    for record in split_z(listing.stdout):
        meta, path = record.split("\t", 1)
        mode, _kind, oid = meta.split(" ")
        kind = sort_entry(inventory, policy, path, mode)
        if kind:
            wanted.append((kind, path, oid))
    blobs = read_blobs(git, repo, [oid for _kind, _path, oid in wanted])
    for kind, path, oid in wanted:
        place(inventory, kind, path, blobs.get(oid))
    return inventory

# ======================================================================================================================
# The scanners, each by absolute path with a named environment
# ======================================================================================================================

def private_home(work: Path) -> Path:
    """
    A home of this run's own, holding the cache a single file build unpacks into, so its engine comes from a folder
    made moments before and removed with the run, never one written before it (Round Table 59's L8).

    Args:
        work: this run's folder

    Returns:
        Path: the home
    """
    home = work / "home"
    (home / ".cache").mkdir(parents = True)
    return home


def tool_environment(temp: Path, home: Path) -> dict[str, str]:
    """
    The scanners' environment, named variables alone, each value the wrapper's own, a temp folder, a home and a cache
    of this run's own and a PATH of the image's folders.

    Args:
        temp: this run's temp folder
        home: this run's home

    Returns:
        dict[str, str]: the environment
    """
    environment = {
        "PATH": TOOL_PATH,
        "HOME": str(home),
        "TMPDIR": str(temp),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LANG": "C.UTF-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
    }
    if os.name == "nt":
        # a test's run on Windows, whose stand ins cannot start without these
        environment.update({name: os.environ[name] for name in ("SYSTEMROOT", "PATH") if name in os.environ})
    return environment


def tail(data: bytes) -> str:
    """
    A tool's last line of error output, for its failure's message.

    Args:
        data: its error output

    Returns:
        str: the last line, cut to fit
    """
    lines = data.decode("utf-8", "replace").strip().splitlines()
    return lines[-1][:SHOWN] if lines else "no error output"


def norm(path: str, prefix: str) -> str | None:
    """
    A path a tool reported, as a repo relative path, None when it lies outside what the tool was given.

    Args:
        path: the reported path
        prefix: the folder the tool was given, empty when it ran inside it

    Returns:
        str | None: the repo relative path
    """
    clean = path.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    if prefix:
        if not clean.startswith(f"{prefix}/"):
            return None
        clean = clean[len(prefix) + 1:]
    return clean if plain_path(clean) else None


@dataclass(frozen = True)
class Finding:
    """
    One match of a rule or an audit, where it starts and ends, and the lines a marker may stand on for it.
    """
    tool:       str
    rule:       str
    path:       str
    start:      int
    end:        int
    message:    str
    category:   str = ""
    confidence: str = ""
    anchors:    tuple[int, ...] = ()


    @property
    def short(self) -> str:
        """
        The rule's last part, the id a marker names.

        Returns:
            str: the last part
        """
        return self.rule.rsplit(".", 1)[-1]


def run_opengrep(machine: Machine, work: Path, environment: dict[str, str]) -> dict:
    """
    Opengrep over the copied code with every rule folder and KDF's rules, nosem markers disabled, its answer read from
    its output stream, so no file in the run's folder carries it (Round Table 59's L12).

    Args:
        machine: the machine
        work: this run's folder, holding rules/ and tree/
        environment: the scanners' environment

    Returns:
        dict: Opengrep's JSON

    Raises:
        ToolFailure: when Opengrep fails or answers with no JSON it can read
    """
    configs = []
    for folder in (*machine.rule_folders, "kdf"):
        if (work / "rules" / folder).is_dir():
            configs += ["--config", f"rules/{folder}"]
    command = [
        *machine.opengrep.command,
        "scan",
        *configs,
        "--taint-intrafile",
        "--disable-nosem",
        "--disable-version-check",
        "--json",
        "--max-target-bytes",
        str(MAX_TARGET_BYTES),
        "--timeout",
        str(RULE_TIMEOUT),
        "tree",
    ]
    done    = subprocess.run(command, cwd = work, env = environment, capture_output = True, check = False)
    if done.returncode != 0 and machine.public:
        # a public repo's log never carries what Opengrep said, which may quote a rule (Round Table 66's L7)
        raise ToolFailure(f"Opengrep exited {done.returncode}, its words withheld from a public repo's log")
    if done.returncode != 0:
        # an error Opengrep may give in its JSON alone, saying nothing else on either stream
        said = tail(done.stderr or done.stdout)
        try:
            errors = json.loads(done.stdout.decode("utf-8")).get("errors", [])
            if errors:
                said = " ".join(str(errors[0].get("message", said)).split())[:2 * SHOWN]
        except (UnicodeDecodeError, ValueError, IndexError, AttributeError):
            pass
        raise ToolFailure(f"Opengrep exited {done.returncode}, {said}")
    try:
        answer = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ToolFailure("Opengrep answered with no JSON the wrapper can read") from error
    if not isinstance(answer, dict):
        raise ToolFailure("Opengrep answered with no JSON the wrapper can read")
    return answer


def unpacked(home: Path) -> None:
    """
    Check Opengrep unpacked its runtime into this run's cache, so a run that took a runtime from anywhere else stops,
    while OPENGREP_UNPACKS says its build unpacks at run time.

    Args:
        home: this run's home

    Raises:
        ToolFailure: when the cache holds no unpacked runtime
    """
    if not OPENGREP_UNPACKS:
        return
    folder = home / ".cache" / "opengrep"
    if not folder.is_dir() or not any(folder.rglob("*")):
        raise ToolFailure(
            f"Opengrep unpacked nothing into the run's own cache, {folder}, so where it ran from is unknown",
        )


def written(work: Path) -> dict[str, str]:
    """
    Every file the wrapper gave the tools, the rules, the copied code and workflows and zizmor's configuration, by its
    path under the run's folder, with its SHA-256.

    Args:
        work: this run's folder

    Returns:
        dict[str, str]: each file's SHA-256
    """
    found = {}
    for part in ("rules", "tree", "workflows"):
        for place, _folders, names in os.walk(work / part):
            for name in names:
                path = Path(place) / name
                found[path.relative_to(work).as_posix()] = file_sha256(path)
    if (work / "kdf_zizmor.yml").is_file():
        found["kdf_zizmor.yml"] = file_sha256(work / "kdf_zizmor.yml")
    return found


def read_back(work: Path, given: Mapping[str, str]) -> None:
    """
    Read back what the tools were given once they exit, a tripwire for a process that changed a file while they ran,
    never a fence, since such a process could change one and put it back (Round Table 59's L12).

    Args:
        work: this run's folder
        given: written's answer before the tools ran

    Raises:
        ToolFailure: when a file was changed, added or removed
    """
    now   = written(work)
    moved = sorted(path for path in set(given) | set(now) if given.get(path) != now.get(path))
    if moved:
        more = len(moved) - 1
        raise ToolFailure(
            f"{moved[0]} changed while the tools ran, and {more} more, so the scan cannot vouch for " f"what they read",
        )


def opengrep_findings(data: dict) -> tuple[list[Finding], set[str], list[tuple[str | None, str]]]:
    """
    Opengrep's findings, the files it read and its errors, each path made repo relative.

    Args:
        data: Opengrep's JSON

    Returns:
        tuple[list[Finding], set[str], list[tuple[str | None, str]]]: the findings, the files read, and each error's
            path, None when it names none, with its kind

    Raises:
        ToolFailure: when a result lies outside the copied tree or names a rule outside the materialised ones
    """
    findings = []
    for result in data.get("results", []):
        path = norm(str(result.get("path", "")), "tree")
        rule = str(result.get("check_id", ""))
        if path is None or not rule.startswith("rules."):
            raise ToolFailure(f"Opengrep answered outside what it was given, {rule} at {result.get('path')}")
        extra    = result.get("extra", {})
        metadata = extra.get("metadata", {})
        findings.append(Finding(
            tool = "opengrep",
            rule = rule.removeprefix("rules."),
            path = path,
            start = int(result.get("start", {}).get("line", 0)),
            end = int(result.get("end", {}).get("line", 0)),
            message = str(extra.get("message", "")),
            category = str(metadata.get("category", "")),
            confidence = str(metadata.get("confidence", "")),
        ))
    scanned = {path for path in (norm(str(item), "tree") for item in data.get("paths", {}).get("scanned", [])) if path}
    errors  = []
    for error in data.get("errors", []):
        kind  = error.get("type")
        kind  = kind[0] if isinstance(kind, list) and kind else kind
        where = error.get(
            "path",
        ) or next((span.get("file") for span in error.get("spans", []) if span.get("file")), None)
        errors.append((norm(str(where), "tree") if where else None, str(kind or error.get("message", "an error"))))
    return findings, scanned, errors


def run_zizmor(machine: Machine, work: Path, environment: dict[str, str]) -> tuple[list, set[str]]:
    """
    zizmor over the copied workflows, offline, at Medium severity and confidence and above, with the image's
    configuration.

    Args:
        machine: the machine
        work: this run's folder, holding workflows/ and kdf_zizmor.yml
        environment: the scanners' environment

    Returns:
        tuple[list, set[str]]: zizmor's findings and the files it says it completed

    Raises:
        ToolFailure: when zizmor fails or writes no JSON it can read
    """
    flags   = ["--offline", "--no-ignores"] if ZIZMOR_NO_IGNORES else ["--offline"]
    command = [
        *machine.zizmor.command,
        *flags,
        "--min-severity",
        "medium",
        "--min-confidence",
        "medium",
        "--format",
        "json",
        "--config",
        str(work / "kdf_zizmor.yml"),
        ".",
    ]
    done    = subprocess.run(command, cwd = work / "workflows", env = environment, capture_output = True, check = False)
    # zizmor says it collected no input when it could load none of the workflows it was given, an answer and not a
    # failure, so none is completed and the coverage makes the scan incomplete
    if done.returncode == ZIZMOR_NO_INPUTS and b"no inputs collected" in done.stderr:
        return [], set()
    if done.returncode not in ZIZMOR_EXITS:
        raise ToolFailure(f"zizmor exited {done.returncode}, {tail(done.stderr)}")
    try:
        found = json.loads(done.stdout.decode("utf-8") or "[]")
    except ValueError as error:
        raise ToolFailure("zizmor wrote no JSON the wrapper can read") from error
    completed = set()
    for line in done.stderr.decode("utf-8", "replace").splitlines():
        match = ZIZMOR_COMPLETED.search(line)
        if match and norm(match["path"], ""):
            completed.add(norm(match["path"], ""))
    return found, completed


def zizmor_findings(found: list) -> tuple[list[Finding], int]:
    """
    zizmor's findings by their primary place, a run block's line kept as an anchor, and cicd's calls at main taken
    out, since the wrapper accepts those alone.

    Args:
        found: zizmor's JSON

    Returns:
        tuple[list[Finding], int]: the findings, and how many calls of cicd at main were accepted

    Raises:
        ToolFailure: when a finding names no place in the copied workflows
    """
    findings, at_main = [], 0
    for item in found:
        locations = item.get("locations", [])
        primary   = next((spot for spot in locations if spot.get("symbolic", {}).get("kind") == "Primary"), None)
        if primary is None:
            raise ToolFailure(f"zizmor's {item.get('ident')} finding names no primary place")
        local    = primary.get("symbolic", {}).get("key", {}).get("Local", {})
        path     = norm(str(local.get("given_path") or local.get("verbatim_path") or ""), "")
        concrete = primary.get("concrete", {})
        feature  = str(concrete.get("feature", ""))
        if path is None:
            raise ToolFailure(f"zizmor answered outside what it was given, {item.get('ident')}")
        if item.get("ident") == "unpinned-uses" and CICD_AT_MAIN.fullmatch(feature.strip()):
            at_main += 1
            continue
        spot           = concrete.get("location", {})
        anchors        = tuple(
            int(other["concrete"]["location"]["start_point"]["row"]) + 1
            for other in locations
            if other is not primary and other.get("concrete", {}).get("feature") == "run"
        )
        determinations = item.get("determinations", {})
        findings.append(Finding(
            tool = "zizmor",
            rule = str(item.get("ident", "")),
            path = path,
            start = int(spot.get("start_point", {}).get("row", 0)) + 1,
            end = int(spot.get("end_point", {}).get("row", 0)) + 1,
            message = str(item.get("desc", "")),
            category = str(determinations.get("severity", "")),
            confidence = str(determinations.get("confidence", "")),
            anchors = anchors,
        ))
    return findings, at_main

# ======================================================================================================================
# Markers and the policy
# ======================================================================================================================

def line_starts(text: str) -> list[int]:
    """
    The offset where each line of a text begins, its lines split at a line feed alone, as git's are.

    Args:
        text: the text

    Returns:
        list[int]: each line's first offset
    """
    return [0, *(match.end() for match in re.finditer("\n", text))]


def python_comments(text: str) -> list[tuple[int, int]]:
    """
    Every comment of a Python file, as Python's own tokenizer finds them, so no string holds one.

    Args:
        text: the file's text

    Returns:
        list[tuple[int, int]]: each comment's first offset and the offset after it

    Raises:
        Unreadable: when the tokenizer stops, or a carriage return alone could split the lines otherwise than git
    """
    if re.search(r"\r(?!\n)", text):
        raise Unreadable("a carriage return stands alone")
    starts = line_starts(text)
    spans  = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                begin = starts[token.start[0] - 1] + token.start[1]
                spans.append((begin, begin + len(token.string)))
    except (tokenize.TokenError, SyntaxError) as error:
        raise Unreadable(f"Python's tokenizer stopped, {type(error).__name__}") from error
    return spans


def string_end(text: str, index: int) -> int:
    """
    The offset after a script's quoted string.

    Args:
        text: the file's text
        index: the opening quote's offset

    Returns:
        int: the offset after the closing quote

    Raises:
        Unreadable: when the string meets its line's end or the file's
    """
    quote, index = text[index], index + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 3 if text.startswith("\r\n", index + 1) else 2
            continue
        if char == quote:
            return index + 1
        if char in "\r\n":
            break
        index += 1
    raise Unreadable("a string never closes on its line")


def regex_end(text: str, index: int) -> int:
    """
    The offset after a script's regular expression and its flags.

    Args:
        text: the file's text
        index: the opening slash's offset

    Returns:
        int: the offset after its flags

    Raises:
        Unreadable: when the expression meets its line's end or the file's
    """
    in_class, index = False, index + 1
    while index < len(text):
        char = text[index]
        if char in "\r\n":
            break
        if char == "\\":
            index += 2
            continue
        if char == "/" and not in_class:
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] in "_$"):
                index += 1
            return index
        in_class = (in_class or char == "[") and char != "]"
        index += 1
    raise Unreadable("a regular expression never closes on its line")


def tag_step(text: str, index: int, stack: list[list]) -> int:
    """
    One step inside an element's tag, past a name, an attribute, its string or the tag's end, an expression opened.

    Args:
        text: the file's text
        index: the offset
        stack: the reader's modes, changed in place

    Returns:
        int: the next offset

    Raises:
        Unreadable: when the tag holds what no tag holds, or closes an element that never opened
    """
    char, closing = text[index], stack[-1][1]
    if char.isspace() or char.isalnum() or char in "_$.:=-":
        return index + 1
    if char in "'\"":
        end = text.find(char, index + 1)
        if end < 0:
            raise Unreadable("an attribute's string never closes")
        return end + 1
    if char == "{":
        stack.append(["code", 0])
        return index + 1
    if text.startswith("/>", index) and not closing:
        stack.pop()
        return index + 2
    if char != ">":
        raise Unreadable(f"{char!r} inside an element's tag")
    stack.pop()
    if not closing:
        stack.append(["children"])
    elif stack[-1][0] == "children":
        stack.pop()
    else:
        raise Unreadable("an element closes that never opened")
    return index + 1


def script_comments(text: str, jsx: bool) -> list[tuple[int, int]]:
    """
    Every comment of a JavaScript or TypeScript file, found past strings, templates and their expressions, regular
    expressions and elements, whose text is never a comment. A slash opens a regular expression, and a less than sign
    before a name an element, where an expression may begin, after a punctuator but a closing bracket or after a word
    EXPRESSION_WORDS names. A file that reads otherwise, a TypeScript arrow's type parameters in .tsx among them, is
    refused whole.

    Args:
        text: the file's text
        jsx: whether the file may hold elements, every kind but .ts

    Returns:
        list[tuple[int, int]]: each comment's first offset and the offset after it

    Raises:
        Unreadable: when a string, template, comment, regular expression or element never closes, or a bracket closes
            what never opened
    """
    spans: list[tuple[int, int]] = []
    stack: list[list] = [["code", 0]]
    # each open parenthesis, whether a control word opened it, so its close lets a regular expression follow
    parens: list[bool] = []
    expression, dotted, index, size = True, False, 0, len(text)
    word, after_brace = "", False
    if text.startswith("#!"):
        index = text.find("\n") if "\n" in text else size
    while index < size:
        mode, char = stack[-1], text[index]
        following = text[index + 1:index + 2]
        if mode[0] == "template":
            if char == "\\":
                index += 2
            elif char == "`":
                stack.pop()
                index, expression = index + 1, False
            elif char + following == "${":
                stack.append(["code", 0])
                index, expression = index + 2, True
            else:
                index += 1
            continue
        if mode[0] == "children":
            if char == "{":
                stack.append(["code", 0])
                expression = True
            elif char == "<":
                stack.append(["tag", following == "/"])
                index += following == "/"
            index += 1
            continue
        if mode[0] == "tag":
            index      = tag_step(text, index, stack)
            expression = text[index - 1] == "{"
            continue
        if char.isspace():
            index += 1
            continue
        if char + following == "//":
            end = text.find("\n", index)
            end = size if end < 0 else end
            spans.append((index, end))
            index = end
            continue
        if char + following == "/*":
            end = text.find("*/", index + 2)
            if end < 0:
                raise Unreadable("a block comment never closes")
            spans.append((index, end + 2))
            index = end + 2
            continue
        this_word = ""
        if char in "'\"":
            index, expression = string_end(text, index), False
        elif char == "`":
            stack.append(["template"])
            index += 1
        elif char == "/" and expression:
            index, expression = regex_end(text, index), False
        elif char == "/":
            # after a block's closing brace a slash may open a regular expression the reader takes for a division, so
            # marker words later on that line refuse the file rather than be read either way
            line_end = text.find("\n", index)
            line_end = size if line_end < 0 else line_end
            if after_brace and MARKER_HINT.search(text, index, line_end):
                raise Unreadable("a slash after a closing brace may open a regular expression holding marker words")
            index, expression = index + 1, True
        elif char == "(":
            parens.append(word in CONTROL_WORDS)
            index, expression = index + 1, True
        elif char == ")":
            if not parens:
                raise Unreadable("a closing parenthesis with no opening one")
            index, expression = index + 1, parens.pop()
        elif char == "<" and jsx and expression and (following.isalpha() or following in ("_", "$", ">")):
            stack.append(["tag", False])
            index += 1
        elif char == "{":
            mode[1] += 1
            index, expression = index + 1, True
        elif char == "}":
            if mode[1]:
                mode[1] -= 1
            elif len(stack) == 1:
                raise Unreadable("a closing brace with no opening one")
            else:
                stack.pop()
            index, expression = index + 1, False
        elif char.isalnum() or char in "_$\\":
            end = index + 1
            while end < size and (text[end].isalnum() or text[end] in "_$\\"):
                end += 1
            expression = not dotted and text[index:end] in EXPRESSION_WORDS
            this_word  = "" if dotted else text[index:end]
            index      = end
        elif char == "]":
            index, expression = index + 1, False
        elif char + following in ("++", "--"):
            index, expression = index + 2, False
        else:
            index, expression = index + 1, True
        word, dotted, after_brace = this_word, char == ".", char == "}"
    if stack != [["code", 0]] or parens:
        raise Unreadable("the file ends inside a template, an element or a bracket")
    return spans


def yaml_comments(text: str) -> list[tuple[int, int]]:
    """
    Every comment of a YAML file, a hash at a line's start or after a space, outside a quoted scalar and outside a
    block scalar's lines, which run while they are blank or indented past the node that owns the scalar, so a script's
    own comment in a run block is never one. A quote opens a scalar only where a scalar may start, never inside a plain
    one or on its next line.

    Args:
        text: the file's text

    Returns:
        list[tuple[int, int]]: each comment's first offset and the offset after it

    Raises:
        Unreadable: when a quoted scalar or a flow collection never closes
    """
    spans: list[tuple[int, int]] = []
    block: int | None = None
    plain: int | None = None
    quote, flow = "", 0
    for raw, offset in zip(text.split("\n"), line_starts(text)):
        line   = raw.rstrip("\r")
        indent = len(line) - len(line.lstrip(" "))
        if block is not None and (not line.strip() or indent > block):
            continue
        block = None
        if not line.strip():
            continue
        continued = plain is not None and indent > plain and not quote and not flow
        start, owner, key = not continued, -1, -1
        last  = "plain" if continued else ""
        index = 0 if quote else 3 if DOCUMENT.match(line) else indent
        while index < len(line):
            char, after = line[index], line[index + 1:index + 2]
            header = BLOCK_HEADER.match(line, index) if start and not flow and char in "|>" else None
            if quote:
                if (quote == '"' and char == "\\") or (quote == "'" and char + after == "''"):
                    index += 1
                elif char == quote:
                    quote, start, last = "", False, "quoted"
            elif char == "#" and (index == 0 or line[index - 1] in " \t"):
                spans.append((offset + index, offset + len(line)))
                last = "comment"
                break
            elif char in " \t":
                pass
            elif start and char in "'\"":
                quote, key = char, index
            elif start and char in "-?" and after in ("", " ", "\t"):
                owner, last = index, "indicator"
            elif start and char in "&!":
                index = PROPERTY.match(line, index).end()
                continue
            elif header:
                if header["comment"]:
                    spans.append((offset + header.start("comment"), offset + len(line)))
                block, last = owner, "block"
                break
            elif char in "[{" and (start or flow):
                flow, start, last = flow + 1, True, "indicator"
            elif flow and char in "]}":
                flow, start, last = flow - 1, False, "quoted"
            elif flow and char == ",":
                start = True
            elif char == ":" and (after in ("", " ", "\t") or (flow and after in (",", "]", "}"))):
                owner, start, last = key if key >= 0 else owner, True, "indicator"
            else:
                key, start, last = index if start else key, False, "plain"
            index += 1
        plain = (owner if owner >= 0 else indent) if last == "plain" and not quote and not flow else None
    if quote or flow:
        raise Unreadable("a quoted scalar or a flow collection never closes")
    return spans


def comment_spans(path: str, text: str) -> list[tuple[int, int]] | None:
    """
    Every comment of a file of a kind a reader knows, Python, JavaScript, TypeScript or YAML.

    Args:
        path: the repo relative path, whose suffix names its kind
        text: the file's text

    Returns:
        list[tuple[int, int]] | None: each comment's first offset and the offset after it, in order, None for a kind
            no reader knows, whose marker text is read as markers

    Raises:
        Unreadable: when the reader cannot find the file's comments whole
    """
    suffix   = Path(path).suffix.lower()
    language = LANGUAGES.get(suffix)
    if language == "python":
        return python_comments(text)
    if (language or suffix in YAML_SUFFIXES) and ODD_BREAK.search(text):
        raise Unreadable("a carriage return alone or a Unicode line separator, a line break git does not count")
    if language:
        return script_comments(text, jsx = suffix != ".ts")
    return yaml_comments(text) if suffix in YAML_SUFFIXES else None


def in_comment(
    pattern: re.Pattern[str],
    line: str,
    offset: int,
    spans: list[tuple[int, int]] | None,
    firsts: list[int],
) -> re.Match[str] | None:
    """
    The first match of a marker's pattern on a line that begins inside a comment, the first match when no reader knows
    the file's comments.

    Args:
        pattern: the marker's pattern
        line: the line
        offset: the line's first offset in the file
        spans: the file's comments in order, None when every match counts
        firsts: each comment's first offset

    Returns:
        re.Match[str] | None: the match, None for none
    """
    position = 0
    while (match := pattern.search(line, position)) is not None:
        index = bisect.bisect_right(firsts, offset + match.start()) - 1
        if spans is None or (index >= 0 and offset + match.start() < spans[index][1]):
            return match
        position = match.start() + 1
    return None


@dataclass
class Marker:
    """
    One suppression marker, its place, the tool it speaks to, the rule it names and its reason, or why it is bad.
    """
    tool:   str
    path:   str
    line:   int
    alone:  bool
    rule:   str = ""
    reason: str = ""
    bad:    str = ""
    bound:  list[Finding] = field(default_factory = list)


def find_markers(path: str, data: bytes) -> list[Marker]:
    """
    Every marker in one file, each checked for the one good form, nosemgrep or zizmor's ignore, one rule and a reason.
    In a file of a kind a reader knows, a marker counts only inside a comment, so marker text in a string, a template,
    an element's text or a run block's script is no marker, and a file whose comments cannot be read whole has every
    marker refused.

    Args:
        path: the repo relative path
        data: its content

    Returns:
        list[Marker]: the markers
    """
    text = data.decode("utf-8-sig", "replace")
    try:
        spans, unread = comment_spans(path, text), ""
    except Unreadable as error:
        spans, unread = None, f"{UNREADABLE}, {error}"
    firsts  = [begin for begin, _end in spans or []]
    markers = []
    for number, (line, offset) in enumerate(zip(text.split("\n"), line_starts(text)), 1):
        line  = line.rstrip("\r")
        match = in_comment(MARKER, line, offset, spans, firsts)
        if match:
            alone  = not line[:match.start()].strip()
            marker = Marker("opengrep", path, number, alone)
            good   = GOOD_MARKER.fullmatch(match["rest"])
            if match["word"] != "nosemgrep":
                marker.bad = f"write nosemgrep: <rule> <reason>, never {match['word']}"
            elif not good:
                marker.bad = "a bare nosemgrep, with no rule named"
            elif good["more"]:
                marker.bad = "two rules in one comment"
            else:
                marker.rule, marker.reason, marker.bad = good["id"], good["reason"] or "", good_reason(good["reason"])
            marker.bad = unread or marker.bad
            markers.append(marker)
        match = in_comment(ZIZMOR_MARK, line, offset, spans, firsts)
        if match:
            marker = Marker("zizmor", path, number, not line[:match.start()].strip())
            good   = GOOD_ZIZMOR.fullmatch(match["rest"])
            if not ZIZMOR_NO_IGNORES:
                marker.bad = "zizmor runs without --no-ignores, so the wrapper refuses its markers"
            elif not good:
                marker.bad = "not zizmor: ignore[<audit>] <reason>"
            elif "," in good["id"]:
                marker.bad = "two audits in one marker"
            else:
                marker.rule, marker.reason, marker.bad = good["id"], good["reason"] or "", good_reason(good["reason"])
            marker.bad = unread or marker.bad
            markers.append(marker)
    return markers


def bind(markers: list[Marker], findings: list[Finding], ids: Mapping[str, int]) -> None:
    """
    Bind each good marker to the findings of its rule at its place, at the end of a finding's first line, alone on the
    line straight above it, or on a run block's line for a finding inside the block. A marker naming a rule two rules
    share is refused, and one that binds nothing is stale.

    Args:
        markers: the markers, each changed in place
        findings: every finding of the full output, before the policy
        ids: how many rules run under each id's last part
    """
    for marker in markers:
        if marker.bad:
            continue
        if marker.tool == "opengrep" and ids.get(marker.rule, 0) > 1:
            marker.bad = f"the rule id {marker.rule} is ambiguous, two rules run under it"
            continue
        line         = marker.line + 1 if marker.alone else marker.line
        marker.bound = [
            finding for finding in findings
            if finding.tool == marker.tool
            and finding.path == marker.path
            and finding.short == marker.rule
            and (finding.start == line or line in finding.anchors)
        ]
        if not marker.bound:
            marker.bad = f"stale, it binds to no {marker.rule} finding at its place"


def kept(finding: Finding) -> bool:
    """
    Whether the policy of design 5.6 keeps a finding.

    Args:
        finding: the finding

    Returns:
        bool: True when it is kept
    """
    if finding.tool == "zizmor" or finding.rule.startswith("kdf."):
        return True
    if finding.category != "security" or finding.short in REPLACED_RULES:
        return False
    if finding.short in TOOLING_RULES and TOOLING_FOLDERS & set(finding.path.split("/")[:-1]):
        return False
    if finding.rule.startswith("python."):
        return finding.confidence.upper() in CONFIDENT
    return True

# ======================================================================================================================
# The branch report
# ======================================================================================================================

@dataclass
class Branch:
    """
    What the branch changed against its merge base with the base, the files, each one's new lines, None for a file
    that is new whole, and the base's policy.
    """
    base:    str | None
    changed: set[str] = field(default_factory = set)
    lines:   dict[str, set[int] | None] = field(default_factory = dict)
    policy:  Policy = field(default_factory = Policy)


def branch_of(git: str, repo: Path, inventory: Inventory, base: str, at_commit: bool) -> Branch:
    """
    The branch's changes against its merge base with the base, none when the base or the merge base is missing.

    Args:
        git: git's absolute path
        repo: the repo
        inventory: the scan's inventory, whose commit the branch ends at
        base: the base ref
        at_commit: whether the scan is at a commit, else the working tree

    Returns:
        Branch: the branch
    """
    target = resolve(git, repo, base)
    merged = run_git(git, repo, "merge-base", inventory.commit, target).stdout.decode().strip() if target else ""
    if not merged:
        return Branch(None)
    ends          = [merged, inventory.commit] if at_commit else [merged]
    listing       = git_out(git, repo, "diff", "--name-only", "--no-renames", "-z", *ends, "--")
    branch        = Branch(merged, set(split_z(listing)))
    branch.policy = parse_policy((blob_at(git, repo, merged, "Makefile") or b"").decode("utf-8", "replace"))
    if not at_commit:
        untracked = split_z(git_out(git, repo, "ls-files", "-z", "--others", "--exclude-standard"))
        branch.changed.update(untracked)
        branch.lines.update(dict.fromkeys(untracked))
    return branch


def changed_lines(git: str, repo: Path, branch: Branch, path: str, commit: str, at_commit: bool) -> set[int] | None:
    """
    The new side's lines the branch changed in one file, read once and kept.

    Args:
        git: git's absolute path
        repo: the repo
        branch: the branch
        path: the repo relative path
        commit: the scanned commit
        at_commit: whether the scan is at a commit

    Returns:
        set[int] | None: the changed line numbers, None when the file is new whole
    """
    if path not in branch.changed or branch.base is None:
        return set()
    if path not in branch.lines:
        ends  = [branch.base, commit] if at_commit else [branch.base]
        patch = run_git(
            git,
            repo,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "-U0",
            "--no-renames",
            *ends,
            "--",
            path,
        ).stdout.decode("utf-8", "replace")
        found = set()
        for hunk in HUNK.finditer(patch):
            start = int(hunk["start"])
            found.update(range(start, start + int(hunk["count"] if hunk["count"] is not None else 1)))
        branch.lines[path] = found
    return branch.lines[path]

# ======================================================================================================================
# The active set on cicd's main, and an image behind it
# ======================================================================================================================

def parse_scan_image(text: str) -> dict[str, str]:
    """
    cicd's SCAN_IMAGE, one key and value a line, each key of SCAN_IMAGE_KEYS once, its digest and commits well formed,
    or the unpinned marker alone before the first activation (design 5.1).

    Args:
        text: the file's text

    Returns:
        dict[str, str]: each key's value, empty for the unpinned marker

    Raises:
        Refusal: when a key is missing, doubled or unknown, or a value is malformed
    """
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    lines = [line for line in lines if not line.startswith("#")]
    if lines == [UNPINNED]:
        return {}
    found: dict[str, str] = {}
    for line in lines:
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key not in SCAN_IMAGE_KEYS or key in found or not value:
            raise Refusal(f"SCAN_IMAGE holds a line it cannot take, {line[:80]!r}")
        found[key] = value
    missing = [key for key in SCAN_IMAGE_KEYS if key not in found]
    if missing:
        raise Refusal(f"SCAN_IMAGE names no {', '.join(missing)}")
    if not DIGEST.fullmatch(found["digest"]) or not DIGEST.fullmatch(f"sha256:{found['rules_digest']}"):
        raise Refusal("SCAN_IMAGE's digests are not sha256 digests")
    if not all(re.fullmatch(r"[0-9a-f]{40}", found[key]) for key in ("commit", "rules_commit")):
        raise Refusal("SCAN_IMAGE's commits are not full commit ids")
    return found


def image_behind(pinned: str, cicd_digest: str) -> str:
    """
    How the digest a repo's managed block pins stands against the one cicd's main pins, which the recipe reads offline
    from a cicd clone's origin/main as last fetched.

    Args:
        pinned: the digest the block names
        cicd_digest: the digest cicd's SCAN_IMAGE names there, empty when there is no cicd clone

    Returns:
        str: a warning's words, empty when the two agree
    """
    if not cicd_digest:
        return "no cicd clone beside the repo, so this image's freshness against cicd's main is unknown"
    if cicd_digest != pinned:
        return f"the block pins {pinned[:19]}, cicd's main {cicd_digest[:19]} as last fetched, a sync brings it"
    return ""

# ======================================================================================================================
# The scan
# ======================================================================================================================

def check_pins(machine: Machine) -> list[str]:
    """
    Both executables checked by SHA-256, a check against a damaged image, the digest being the image's identity.

    Args:
        machine: the machine

    Returns:
        list[str]: each check's line, a failure starting FAIL
    """
    lines = []
    for tool in (machine.opengrep, machine.zizmor):
        found = file_sha256(tool.path)
        state = "ok" if tool.sha256 and found == tool.sha256 else f"FAIL, {tool.path} is {found or 'missing'}"
        lines.append(f"{tool.name} {tool.version} sha256 {state}")
    return lines


def prepare(machine: Machine, work: Path) -> dict[str, int]:
    """
    Check the pins and materialise the rules and the zizmor configuration into this run's folder, Semgrep's rules from
    the cache unless KDF's run alone.

    Args:
        machine: the machine
        work: this run's folder

    Returns:
        dict[str, int]: how many rules run under each id's last part

    Raises:
        Refusal: when a pin fails, or the rules' cache is missing or off its digest
    """
    failed = [line for line in check_pins(machine) if "FAIL" in line]
    if failed:
        raise Refusal("; ".join(failed))
    files: dict[str, bytes] = {}
    if not machine.kdf_only:
        try:
            files = rule_files(machine.git, machine.rules, machine.rules_commit, machine.rule_folders)
        except Refusal as refusal:
            raise Refusal(f"{refusal}, {SETUP} fills the rules' cache") from refusal
        if rules_digest(files) != machine.rules_digest:
            raise Refusal(f"the rules' digest at {machine.rules_commit[:8]} is not the pinned one, {SETUP} again")
    kdf = {
        f"kdf/{name.removeprefix('scan_rules/')}": data
        for name, data in machine.files.items()
        if name.startswith("scan_rules/") and name.endswith((".yaml", ".yml")) and "/" not in name[11:]
    }
    for path, data in {**files, **kdf}.items():
        target = work / "rules" / path
        target.parent.mkdir(parents = True, exist_ok = True)
        target.write_bytes(data)
    if "kdf_zizmor.yml" not in machine.files:
        raise Refusal("the image holds no kdf_zizmor.yml")
    (work / "kdf_zizmor.yml").write_bytes(machine.files["kdf_zizmor.yml"])
    return rule_ids({**files, **kdf})


def copy_tree(folder: Path, files: Mapping[str, bytes], inventory: Inventory) -> None:
    """
    Copy files into a folder the tools read, a file that cannot be written recorded as incomplete.

    Args:
        folder: the folder
        files: each file's content by its repo relative path
        inventory: the inventory, whose incomplete list takes a failed copy
    """
    folder.mkdir(parents = True, exist_ok = True)
    (folder / ".semgrepignore").write_bytes(b"")
    for path, data in files.items():
        try:
            (folder / path).parent.mkdir(parents = True, exist_ok = True)
            (folder / path).write_bytes(data)
        except OSError as error:
            inventory.incomplete.append(f"{path} could not be copied for the tools, {error.strerror}")


@dataclass
class Outcome:
    """
    A scan's lines, its counts and the last line's parts.
    """
    lines:      list[str] = field(default_factory = list)
    failing:    int = 0
    incomplete: int = 0
    limits:     int = 0
    marks:      list[str] = field(default_factory = list)


def coverage(
    outcome: Outcome,
    inventory: Inventory,
    policy: Policy,
    scanned: set[str],
    errors: list,
    completed: set[str],
    ran_zizmor: bool,
    public: bool = False,
) -> None:
    """
    Hold what each tool read against the inventory, a recorded limit passing a file's errors only while its content
    is the one recorded, and in a public repo no word of an Opengrep error but that there was one.

    Args:
        outcome: the scan's outcome, changed in place
        inventory: the inventory
        policy: the policy whose limits apply
        scanned: the files Opengrep read
        errors: Opengrep's errors by path
        completed: the workflow files zizmor completed
        ran_zizmor: whether zizmor ran
        public: whether the output is a public repo's
    """
    limits   = {path: (sha, reason) for path, sha, reason in policy.limits}
    troubled = {path for path, _kind in errors if path} | (set(inventory.code) - scanned)
    passed   = set()
    for path in sorted(troubled):
        recorded = limits.get(path)
        if recorded and path in inventory.code and content_sha256(inventory.code[path]) == recorded[0]:
            passed.add(path)
            outcome.lines.append(f"LIMIT     {path}  {recorded[1]}")
    for path, kind in errors:
        if path not in passed:
            said = "reported an error, its words withheld" if public else kind
            outcome.lines.append(f"INCOMPLETE {path or 'no file named'}  Opengrep {said}")
            outcome.incomplete += 1
    for path in sorted(set(inventory.code) - scanned - passed):
        outcome.lines.append(f"INCOMPLETE {path}  not read by Opengrep")
        outcome.incomplete += 1
    for path in sorted(set(limits) - passed):
        outcome.lines.append(f"BAD       {path}  a scan limit with nothing to pass, or its file changed, remove it")
        outcome.failing += 1
    for path in sorted(set(inventory.workflows) - completed if ran_zizmor else set(inventory.workflows)):
        outcome.lines.append(f"INCOMPLETE {path}  not collected by zizmor")
        outcome.incomplete += 1
    for reason in inventory.incomplete:
        outcome.lines.append(f"INCOMPLETE {reason}")
        outcome.incomplete += 1
    outcome.limits = len(passed)


def report(
    outcome: Outcome,
    markers: list[Marker],
    findings: list[Finding],
    branch: Branch,
    look,
    public: bool = False,
) -> int:
    """
    The findings and markers as report lines, every accepted finding printed with the branch's new and changed ones
    marked, a failing finding in a file the branch did not change named older than it, and in a public repo no rule's
    message, only its id, path and line (Round Table 66's L7).

    Args:
        outcome: the scan's outcome, changed in place
        markers: the bound markers
        findings: every finding
        branch: the branch
        look: a function giving the changed lines of a file
        public: whether the output is a public repo's

    Returns:
        int: how many findings were accepted
    """
    accepted: dict[Finding, Marker] = {}
    for marker in markers:
        if marker.bad:
            outcome.lines.append(f"BAD       {marker.path}:{marker.line}  {marker.bad}")
            outcome.failing += 1
            continue
        for finding in marker.bound:
            accepted.setdefault(finding, marker)
    count = 0
    for finding in sorted(set(findings), key = lambda item: (item.path, item.start, item.rule)):
        if not kept(finding):
            continue
        where = f"{finding.path}:{finding.start}  {finding.short}"
        if finding in accepted:
            marker  = accepted[finding]
            changes = look(finding.path)
            note    = ""
            if changes is None or marker.line in changes:
                note = "  (new)"
            elif changes & set(range(finding.start, finding.end + 1)):
                note = "  (changed)"
            outcome.lines.append(f"ACCEPTED  {where}  {marker.reason}{note}")
            count += 1
            continue
        older   = "" if branch.base is None or finding.path in branch.changed else "  (older than the branch)"
        message = finding.message.splitlines()[0][:SHOWN] if finding.message else ""
        if public and finding.tool == "opengrep":
            message = "its message withheld from a public repo's log"
        outcome.lines.append(f"FAIL      {where}  {message}{older}")
        outcome.failing += 1
    return count


def policy_marks(outcome: Outcome, applied: Policy, branch_policy: Policy, branch: Branch) -> None:
    """
    Mark the branch's additions to the exclusions and limits and a change to the scan target.

    Args:
        outcome: the scan's outcome, changed in place
        applied: the policy the scan applied
        branch_policy: the policy the branch's own Makefile declares
        branch: the branch, whose policy is the base's
    """
    if branch.base is None:
        return
    added = (set(branch_policy.excludes) - set(branch.policy.excludes)) | {
        (path, reason) for path, _sha, reason in set(branch_policy.limits) - set(branch.policy.limits)
    }
    for path, reason in sorted(added):
        state = "applied" if applied == branch_policy else "ignored, the base's policy applies"
        outcome.lines.append(f"POLICY    {path}  the branch adds it, {state}, {reason}")
    if added:
        outcome.marks.append("policy-added")
    if branch_policy.target != branch.policy.target:
        outcome.lines.append("POLICY    the branch changes the scan target's lines in the managed block")
        outcome.marks.append("target-changed")


def last_line(inventory_commit: str, state: str, machine: Machine, outcome: Outcome, code: int, result: str) -> str:
    """
    The scan's last line, the commit, the tree's state, the image's cicd commit, each pin, the limits passed, the marks
    and the result, the rules named kdf-only when Semgrep's did not run, so reduced coverage is never mistaken.

    Args:
        inventory_commit: the commit scanned
        state: clean-tree, dirty-tree or at-commit
        machine: the machine
        outcome: the scan's outcome
        code: the exit code
        result: the result's words

    Returns:
        str: the line
    """
    marks = f" marks {','.join(outcome.marks)}" if outcome.marks else ""
    rules = "kdf-only" if machine.kdf_only else machine.rules_commit[:8]
    return (
        f"kdf-scan {inventory_commit[:12]} {state} image {machine.image[:12]} opengrep {machine.opengrep.version} "
        f"rules {rules} zizmor {machine.zizmor.version} limits {outcome.limits}{marks}: {result} (exit {code})"
    )


def scan(
    machine: Machine,
    repo: Path,
    out: TextIO = sys.stdout,
    at_commit: str | None = None,
    policy_at: str | None = None,
    base: str = BASE_REF,
    notes: tuple[tuple[str, str, str], ...] = (),
) -> int:
    """
    Scan a repo's working tree, or one commit of it, and print the report and the last line.

    Args:
        machine: the machine
        repo: the repo
        out: where the report goes
        at_commit: the commit to scan, the working tree when None
        policy_at: the commit whose managed block gives a scan at a commit its exclusions and limits, the base when
            None
        base: the ref the branch is compared with
        notes: lines a mode adds, each its kind, WARN or BAD, its words and the mark it puts on the last line, a BAD
            one failing the scan

    Returns:
        int: the exit code, 0 to 4
    """
    work = make_run()
    try:
        return _scan(machine, repo, out, at_commit, policy_at, base, work, notes)
    finally:
        remove_run(work)


def make_run() -> Path:
    """
    A run folder under RUN_ROOT, the container's tmpfs, or the temp folder where RUN_ROOT is missing, a test's run.

    Returns:
        Path: the folder
    """
    temp = RUN_ROOT if RUN_ROOT.is_dir() else Path(tempfile.gettempdir())
    return Path(tempfile.mkdtemp(prefix = RUN_PREFIX, dir = temp))


def remove_run(work: Path) -> None:
    """
    Remove a run folder, a read only file made writable first, whatever the container's end leaves aside.

    Args:
        work: the folder
    """
    def writable(function: Callable[[str], object], path: str, _error: BaseException) -> None:
        """
        Make one path writable and try its removal again.

        Args:
            function: the removal that failed
            path: its path
            _error: why
        """
        try:
            os.chmod(path, stat.S_IWRITE)
            function(path)
        except OSError:
            pass


    shutil.rmtree(work, onexc = writable)


def choose(
    machine: Machine,
    repo: Path,
    at_commit: str | None,
    policy_at: str | None,
    base: str,
) -> tuple[Policy, Policy, Inventory]:
    """
    The policy a scan applies, the one the branch declares, and the inventory, from the working tree or from a commit,
    whose exclusions and limits come from the base so a branch never widens its own.

    Args:
        machine: the machine
        repo: the repo
        at_commit: the commit to scan, the working tree when None
        policy_at: the commit whose policy a scan at a commit applies, the base when None
        base: the ref the branch is compared with

    Returns:
        tuple[Policy, Policy, Inventory]: the applied policy, the branch's policy and the inventory

    Raises:
        Refusal: when the commit names nothing, or a policy or the inventory is refused
    """
    if at_commit is None:
        makefile = repo / "Makefile"
        declared = parse_policy(makefile.read_text("utf-8", "replace") if makefile.is_file() else None)
        return declared, declared, worktree_inventory(machine.git, repo, declared)
    commit = resolve(machine.git, repo, at_commit)
    if not commit:
        raise Refusal(f"{at_commit} names no commit in {repo}")
    source   = resolve(machine.git, repo, policy_at or base) or commit
    declared = parse_policy((blob_at(machine.git, repo, commit, "Makefile") or b"").decode("utf-8", "replace"))
    applied  = parse_policy((blob_at(machine.git, repo, source, "Makefile") or b"").decode("utf-8", "replace"))
    return applied, declared, commit_inventory(machine.git, repo, commit, applied)


def _scan(
    machine: Machine,
    repo: Path,
    out: TextIO,
    at_commit: str | None,
    policy_at: str | None,
    base: str,
    work: Path,
    notes: tuple[tuple[str, str, str], ...] = (),
) -> int:
    """
    The scan in its run folder, which the caller removes.

    Args:
        machine: the machine
        repo: the repo
        out: where the report goes
        at_commit: the commit to scan, the working tree when None
        policy_at: the commit whose policy a scan at a commit applies
        base: the ref the branch is compared with
        work: this run's folder
        notes: lines a mode adds, as scan takes them

    Returns:
        int: the exit code
    """
    try:
        ids = prepare(machine, work)
    except Refusal as refusal:
        out.write(f"kdf-scan  refused, {refusal}\n")
        out.write(f"kdf-scan {'-' * 12} REFUSED (exit 2)\n")
        return 2
    try:
        applied, branch_policy, inventory = choose(machine, repo, at_commit, policy_at, base)
    except Refusal as refusal:
        named = resolve(machine.git, repo, at_commit or "HEAD") or "-" * 12
        out.write(f"kdf-scan  refused, {refusal}\nkdf-scan {named[:12]} REFUSED (exit 2)\n")
        return 2
    outcome = Outcome()
    rules   = "kdf-only, Semgrep's rules not run" if machine.kdf_only else (
        f"{machine.rules_commit[:8]} digest {machine.rules_digest} ok"
    )
    out.write(
        f"kdf-scan  opengrep {machine.opengrep.version} sha256 ok  rules {rules}  zizmor {machine.zizmor.version} "
        f"sha256 ok  image {machine.image[:12]}  env {len(TOOL_ENVIRONMENT)} names\n"
    )
    for folder, reason in applied.excludes:
        outcome.lines.append(f"EXCLUDED  {folder}  {reason}")
    for kind, words, mark in notes:
        outcome.lines.append(f"{kind:<9} {words}")
        if mark:
            outcome.marks.append(mark)
        if kind == "BAD":
            outcome.failing += 1
    copy_tree(work / "tree", inventory.code, inventory)
    copy_tree(work / "workflows", inventory.workflows, inventory)
    home        = private_home(work)
    environment = tool_environment(work / "temp", home)
    (work / "temp").mkdir()
    given = written(work)
    try:
        answer = run_opengrep(machine, work, environment)
        unpacked(home)
        found, completed = run_zizmor(machine, work, environment) if inventory.workflows else ([], set())
        read_back(work, given)
        findings, scanned, errors = opengrep_findings(answer)
        z_findings, at_main = zizmor_findings(found)
    except ToolFailure as failure:
        out.write(f"kdf-scan  {failure}\n")
        out.write(last_line(inventory.commit, inventory.state, machine, outcome, 3, "FAILED") + "\n")
        return 3
    coverage(outcome, inventory, applied, scanned, errors, completed, bool(inventory.workflows), machine.public)
    markers = []
    for path, data in {**inventory.code, **inventory.workflows}.items():
        markers.extend(find_markers(path, data))
    for path, data in inventory.excluded.items():
        for marker in find_markers(path, data):
            marker.bad = "a marker in a file the scan does not read"
            markers.append(marker)
    every = findings + z_findings
    bind(markers, every, ids)
    branch = branch_of(machine.git, repo, inventory, base, at_commit is not None)
    if branch.base is None:
        outcome.lines.append(f"INCOMPLETE no merge base with {base}, so the branch's changes cannot be compared")
        outcome.incomplete += 1
    policy_marks(outcome, applied, branch_policy, branch)
    accepted = report(
        outcome,
        markers,
        every,
        branch,
        lambda path: changed_lines(machine.git, repo, branch, path, inventory.commit, at_commit is not None),
        machine.public,
    )
    kept_og  = [finding for finding in findings if kept(finding)]
    out.write(f"opengrep  {len(scanned & set(inventory.code))} of {len(inventory.code)} inventory files read, "
              f"{len(kept_og)} findings\n")
    out.write(f"zizmor    {len(inventory.workflows)} workflow files, {len(z_findings)} findings, {at_main} calls of "
              f"cicd at main accepted, {accepted} findings accepted in all\n")
    for line in outcome.lines:
        out.write(line + "\n")
    if outcome.incomplete:
        code   = 4
        result = f"INCOMPLETE {outcome.incomplete}" + (f" FINDINGS {outcome.failing}" if outcome.failing else "")
    elif outcome.failing:
        code, result = 1, f"FINDINGS {outcome.failing}"
    else:
        code, result = 0, "CLEAN"
    out.write(last_line(inventory.commit, inventory.state, machine, outcome, code, result) + "\n")
    return code

# ======================================================================================================================
# The modes, a mounted working tree and a pull request's fetched tree
# ======================================================================================================================

@contextmanager
def git_view(
    work: Path,
    folders: Mapping[str, Mapping[str, str]],
    safe: tuple[str, ...],
    autocrlf: str | None,
) -> Iterator[None]:
    """
    Set the git view a mode reads through, a neutral environment, each repo's git folders named explicitly, the paths
    git may own other than the scan's user, and the host's core.autocrlf, put back when the mode ends.

    Args:
        work: a folder for the neutral environment's empty configuration
        folders: each repo's path with the GIT_ variables that name its folders
        safe: the paths git may trust though another user owns them
        autocrlf: the host's core.autocrlf, None for none

    Returns:
        Iterator[None]: the view, set while the block runs
    """
    global NEUTRAL_GIT, GIT_FOLDERS, SAFE_PATHS, AUTOCRLF
    before = (NEUTRAL_GIT, GIT_FOLDERS, SAFE_PATHS, AUTOCRLF)
    NEUTRAL_GIT, GIT_FOLDERS, SAFE_PATHS, AUTOCRLF = (
        neutral_git(work),
        {path: dict(names) for path, names in folders.items()},
        safe,
        autocrlf,
    )
    try:
        yield
    finally:
        NEUTRAL_GIT, GIT_FOLDERS, SAFE_PATHS, AUTOCRLF = before


def unsafe_config(git: str, repo: Path) -> list[str]:
    """
    The keys of a repository's own configuration that would run a program or read another file, a filter or an
    include, which turning hooks and fsmonitor off leaves to run (Codex's revision plan read).

    Args:
        git: git's absolute path
        repo: the working tree

    Returns:
        list[str]: each such key

    Raises:
        Refusal: when git cannot read the configuration
    """
    done = run_git(git, repo, "config", "--list", "--name-only", "--show-scope")
    if done.returncode != 0:
        raise Refusal(f"git could not read the repository's configuration, {tail(done.stderr)}")
    found = set()
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        scope, _, name = line.partition("\t")
        if scope in ("local", "worktree") and UNSAFE_CONFIG.fullmatch(name):
            found.add(name)
    return sorted(found)


def read_not_docs(text: str) -> list[str] | None:
    """
    The `not_docs` patterns of a caller's ci.yml, a quoted value or a folded block, None when it names none or two.

    Args:
        text: the ci.yml's text

    Returns:
        list[str] | None: the patterns, None when there is no single answer
    """
    lines = text.replace("\r\n", "\n").split("\n")
    found = [(index, NOT_DOCS.fullmatch(line)) for index, line in enumerate(lines)]
    found = [(index, match) for index, match in found if match]
    if len(found) != 1:
        return None
    index, match = found[0]
    value = match["value"]
    if value in (">", ">-", "|", "|-", ">+", "|+"):
        block = []
        for line in lines[index + 1:]:
            if line.strip() and len(line) - len(line.lstrip()) <= len(match["indent"]):
                break
            block.append(line.strip())
        return " ".join(block).split()
    if value[:1] in ("'", '"'):
        closing = value.find(value[0], 1)
        return value[1:closing].split() if closing > 0 else None
    return value.split("#", 1)[0].split()


def load_ci_paths(files: Mapping[str, bytes]) -> types.ModuleType:
    """
    The image's own copy of cicd's ci_paths.py as a module, so a branch's copy never decides what is docs only.

    Args:
        files: the wrapper's own files

    Returns:
        types.ModuleType: the module

    Raises:
        Refusal: when the image holds no ci_paths.py
    """
    source = files.get("ci_paths.py")
    if source is None:
        raise Refusal("the image holds no ci_paths.py")
    module = types.ModuleType("kdf_scan_ci_paths")
    exec(compile(source, "ci_paths.py", "exec"), module.__dict__)  # noqa: S102 the image's own file beside the wrapper
    return module


def gate_notes(git: str, repo: Path, changed: list[str], head: str, caller_sha: str) -> list[tuple[str, str, str]]:
    """
    A pull request's change to the gate's caller, passing and printed first when it equals the canonical caller whose
    SHA-256 the gate holds, failing otherwise, and any other workflow it changes that names the gate, failing, cicd's
    own reusable workflow apart, which the caller names by its repo (design 5.3, Codex's revision plan read).

    Args:
        git: git's absolute path
        repo: the fetched repository
        changed: the paths the pull request changes
        head: its head
        caller_sha: the canonical caller's SHA-256

    Returns:
        list[tuple[str, str, str]]: the notes, as scan takes them
    """
    notes: list[tuple[str, str, str]] = []
    for path in changed:
        data = blob_at(git, repo, head, path)
        if path == CALLER_PATH:
            if data is not None and caller_sha and hashlib.sha256(data).hexdigest() == caller_sha:
                notes.insert(0, ("WARN", f"{path} becomes cicd's canonical caller, read the change", "caller-changed"))
            else:
                notes.append(("BAD", f"{path} changes to other than cicd's canonical caller", "caller-changed"))
        elif path != REUSABLE_PATH and is_workflow(path) and data and any(name.encode() in data for name in GATE_NAMES):
            notes.append(("BAD", f"{path} names the gate, which only the canonical caller may", "gate-named"))
    return notes


def pr_tree(
    machine: Machine,
    repo: Path,
    commits: tuple[str, str, str],
    caller_sha: str,
    out: TextIO = sys.stdout,
) -> int:
    """
    The gate's scan, and a local --pr's, of a pull request's head fetched before the scan into a bare repository, each
    id resolving to itself, the merge base the one GitHub named, docs only by the image's own ci_paths.py, and the head
    scanned with main's exclusions and limits, never falling back to the branch's (design 5.3).

    Args:
        machine: the machine
        repo: the bare repository
        commits: the head, main and their merge base as GitHub named them
        caller_sha: the canonical caller's SHA-256
        out: where the report goes

    Returns:
        int: the scan's exit code, 0 for a docs only pull request, 2 for a refusal
    """
    def refuse(reason: str) -> int:
        """
        Print a refusal and its last line.

        Args:
            reason: why the scan refuses

        Returns:
            int: 2
        """
        out.write(f"kdf-scan  refused, {reason}\nkdf-scan {'-' * 12} REFUSED (exit 2)\n")
        return 2


    head, main, merged = commits
    git = machine.git
    for name, value in (("head", head), ("main", main), ("merge base", merged)):
        if not re.fullmatch(r"[0-9a-f]{40}", value) or resolve(git, repo, value) != value:
            return refuse(f"the {name} {value[:40]!r} does not resolve in the fetched repository")
    found = run_git(git, repo, "merge-base", main, head)
    if found.returncode != 0 or found.stdout.decode().strip() != merged:
        return refuse("the fetched history does not reach the merge base GitHub names")
    listed = run_git(git, repo, "diff", "--name-only", "--no-renames", "-z", merged, head)
    if listed.returncode != 0:
        return refuse(f"git could not list the pull request's changes, {tail(listed.stderr)}")
    changed = split_z(listed.stdout)
    rules   = "kdf-only" if machine.kdf_only else machine.rules_digest
    out.write(f"verify    head {head} main {main} merge base {merged} image {machine.image} rules {rules}\n")
    try:
        ci_paths = load_ci_paths(machine.files)
    except Refusal as refusal:
        return refuse(str(refusal))
    caller   = blob_at(git, repo, main, ".github/workflows/ci.yml")
    patterns = read_not_docs(caller.decode("utf-8", "replace")) if caller else None
    if patterns is not None:
        tree = run_git(git, repo, "ls-tree", "-r", "-z", "--name-only", main)
        if tree.returncode != 0:
            return refuse(f"git could not list main's tree, {tail(tree.stderr)}")
        try:
            ci_paths.check_not_docs(patterns, split_z(tree.stdout))
            docs = ci_paths.docs_only(changed, patterns)
        except ValueError:
            docs = False
        if docs:
            out.write(f"verify    docs only by the image's ci_paths.py, {len(changed)} paths, nothing to scan\n")
            out.write(f"kdf-scan {head[:12]} verify image {machine.image[:12]}: DOCS-ONLY (exit 0)\n")
            return 0
    notes = tuple(gate_notes(git, repo, changed, head, caller_sha))
    return scan(machine, repo, out = out, at_commit = head, policy_at = main, base = main, notes = notes)


def mounted_scan(machine: Machine, args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """
    `make scan`'s scan of a mounted working tree, each git folder named explicitly and trusted though another user
    owns it, a worktree's own folder inside the common one, the host's core.autocrlf given, a repository's own filter
    or include refused, and an image behind cicd's main warned of (design 5.4 and 5.5).

    Args:
        machine: the machine
        args: the scan mode's arguments
        out: where the report goes

    Returns:
        int: the exit code
    """
    if args.autocrlf not in ("", "true", "false", "input"):
        out.write(f"kdf-scan  refused, core.autocrlf {args.autocrlf!r} is none git takes\n")
        out.write(f"kdf-scan {'-' * 12} REFUSED (exit 2)\n")
        return 2
    common, own = Path(args.common_dir), Path(args.git_dir)
    if own != common and own.parent != common / "worktrees":
        # git reads a worktree's refs through its commondir file, so its folder must sit inside the common one
        out.write(f"kdf-scan  refused, the git folder {own} is neither {common} nor a worktree's folder inside it\n")
        out.write(f"kdf-scan {'-' * 12} REFUSED (exit 2)\n")
        return 2
    src     = str(Path(args.src))
    folders = {src: {"GIT_DIR": args.git_dir, "GIT_COMMON_DIR": args.common_dir, "GIT_WORK_TREE": src}}
    safe    = (src, args.git_dir, args.common_dir, str(machine.rules))
    view    = make_run()
    try:
        with git_view(view, folders, safe, args.autocrlf or None):
            try:
                unsafe = unsafe_config(machine.git, Path(src))
            except Refusal as refusal:
                unsafe = [str(refusal)]
            if unsafe:
                out.write(f"kdf-scan  refused, the repository's own configuration runs or reads more, "
                          f"{', '.join(unsafe)}\nkdf-scan {'-' * 12} REFUSED (exit 2)\n")
                return 2
            warning = image_behind(args.pinned, args.cicd_digest) if args.pinned else ""
            notes   = (("WARN", warning, "image-behind"),) if warning else ()
            return scan(machine, Path(src), out = out, notes = notes)
    finally:
        remove_run(view)


def fetched_scan(machine: Machine, args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """
    The gate's scan, and a local --pr's, of a bare repository fetched before the scan.

    Args:
        machine: the machine
        args: the pr-tree mode's arguments
        out: where the report goes

    Returns:
        int: the exit code
    """
    repo = str(Path(args.repo))
    view = make_run()
    try:
        with git_view(view, {}, (repo, str(machine.rules)), None):
            return pr_tree(machine, Path(repo), (args.head, args.main, args.merge_base), args.caller_sha, out)
    finally:
        remove_run(view)


def main(argv: list[str] | None = None) -> int:
    """
    The image's entrypoint, a scan of a mounted working tree, a pull request's fetched tree or a commit, --pins for the
    image's build, or --rules-digest of a rules clone.

    Args:
        argv: the arguments, sys.argv when None

    Returns:
        int: the exit code
    """
    parser = argparse.ArgumentParser(description = "The local code scan's wrapper, the image's entrypoint (D-085).")
    parser.add_argument("--pins", action = "store_true", help = "print the declared pins and stop")
    parser.add_argument("--rules-digest", metavar = "GIT_DIR", help = "print the rules' digest at the pinned commit")
    parser.add_argument("--git", help = "the git a run uses, the image's own by default")
    modes = parser.add_subparsers(dest = "mode")
    each  = []
    tree  = modes.add_parser("scan", help = "a mounted working tree, make scan's")
    tree.add_argument("--src", default = SRC_MOUNT, help = "the working tree")
    tree.add_argument(
        "--git-dir",
        default = GIT_MOUNT,
        help = "the working tree's own git folder, the common one or a worktree's folder inside it",
    )
    tree.add_argument("--common-dir", default = GIT_MOUNT, help = "the common git folder, the same for a plain clone")
    tree.add_argument("--autocrlf", default = "", help = "the host's core.autocrlf, empty for none")
    tree.add_argument("--pinned", default = "", help = "the digest the repo's managed block pins")
    tree.add_argument(
        "--cicd-digest",
        default = "",
        help = "the digest a cicd clone's origin/main pins, empty for none",
    )
    each.append(tree)
    fetched = modes.add_parser("pr-tree", help = "a pull request's head fetched into a bare repository, the gate's")
    fetched.add_argument("--repo", default = REPO_MOUNT, help = "the bare repository")
    fetched.add_argument("--head", required = True, help = "the head GitHub names")
    fetched.add_argument("--main", required = True, help = "the base's main GitHub names")
    fetched.add_argument("--merge-base", required = True, help = "their merge base GitHub names")
    fetched.add_argument("--caller-sha", default = "", help = "the canonical caller's SHA-256 the gate holds")
    each.append(fetched)
    commit = modes.add_parser("at", help = "one commit of a repository, a developer's tool and never a gate")
    commit.add_argument("--repo", default = SRC_MOUNT, help = "the repository")
    commit.add_argument("--at", required = True, help = "the commit to scan")
    commit.add_argument("--policy-at", help = "the commit whose exclusions and limits apply, the base by default")
    commit.add_argument("--base", default = BASE_REF, help = "the ref the branch is compared with")
    each.append(commit)
    for mode in each:
        mode.add_argument("--rules", default = RULES_MOUNT, help = "the rules' cache, a git folder")
        mode.add_argument("--kdf-only", action = "store_true", help = "run KDF's rules alone, its coverage named")
        mode.add_argument("--public", action = "store_true", help = "a public repo's log, rule ids and no message")
    args = parser.parse_args(argv)
    if args.pins:
        for name, value in pins().items():
            print(f"{name}={value}")
        return 0
    if args.git is not None and not Path(args.git).is_file():
        print(f"kdf-scan  refused, no git at {args.git}")
        return 2
    try:
        git = args.git or find_git()
        if args.rules_digest:
            print(rules_digest(rule_files(git, Path(args.rules_digest), RULES_COMMIT, RULE_FOLDERS)))
            return 0
    except Refusal as refusal:
        print(f"kdf-scan  refused, {refusal}")
        return 2
    if args.mode is None:
        parser.print_help()
        return 2
    image = machine(IMAGE_ROOT, image_commit(), image_files(), git, Path(args.rules), args.kdf_only, args.public)
    if args.mode == "scan":
        return mounted_scan(image, args)
    if args.mode == "pr-tree":
        return fetched_scan(image, args)
    repo = str(Path(args.repo))
    view = make_run()
    try:
        with git_view(view, {}, (repo, str(image.rules)), None):
            return scan(image, Path(repo), at_commit = args.at, policy_at = args.policy_at, base = args.base)
    finally:
        remove_run(view)


if __name__ == "__main__":
    sys.exit(main())
