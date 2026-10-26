"""
The scan image's own fixtures (D-085, design 5.9, Round Table 66's L14 and L17), run against the exact image the build
is about to publish, with no Semgrep rule and no rule's message printed, so they run in the public cicd's log.

Each runs the image as the gate and `make scan` run it, the network off, the root read only, a tmpfs for the run, no
capability and a user that is not root, and each fence has its control, the same act shown to work where the fence is
absent. The scans use KDF's rules alone on a repo written fresh here. Standard library only.
"""

from __future__ import annotations

# standard imports
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

LOCKED = [
    "--rm",
    "--network",
    "none",
    "--read-only",
    "--tmpfs",
    "/run/kdf-scan:exec,size=1g,uid=65532,gid=65532",
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges",
    "--user",
    "65532:65532",
]
# a line KDF's rule flags, whose message, "is written to a log", a public run never prints, and a clean one
VULNERABLE = (
    "import logging\n\nlogger = logging.getLogger(__name__)\n\n\ndef send(access_token):\n"
    '    logger.info(f"the token is {access_token}")\n'
)
CLEAN      = "print('hello')\n"
FENCE_ONLY = "import urllib.request\nurllib.request.urlopen('https://example.com', timeout = 5)\n"
NO_ROOT    = "open('/opt/kdf-scan/written', 'w').write('x')\n"

# ======================================================================================================================
# The fixtures
# ======================================================================================================================

def docker(*args: str) -> subprocess.CompletedProcess[str]:
    """
    One docker call, its output kept.

    Args:
        *args: docker's arguments

    Returns:
        subprocess.CompletedProcess[str]: the finished call
    """
    return subprocess.run(["docker", *args], capture_output = True, text = True, check = False)


def git(repo: Path, *args: str) -> None:
    """
    One git call on the fixture's repo, with no configuration of the caller's.

    Args:
        repo: the repo
        *args: git's arguments
    """
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "-C", str(repo), *args], check = True, capture_output = True, env = environment)


def make_repo(folder: Path, vulnerable: bool) -> Path:
    """
    A repo of one commit, its first commit as origin/main, with a vulnerable line or none.

    Args:
        folder: where it goes
        vulnerable: whether it holds the line KDF's rule flags

    Returns:
        Path: the repo
    """
    folder.mkdir(parents = True)
    git(folder, "init", "-q", "-b", "main")
    (folder / "app.py").write_text(VULNERABLE if vulnerable else CLEAN, encoding = "utf-8", newline = "\n")
    git(folder, "add", "-A")
    git(folder, "-c", "user.email=fixture@example.com", "-c", "user.name=fixture", "commit", "-q", "-m", "one")
    git(folder, "update-ref", "refs/remotes/origin/main", "HEAD")
    return folder


def scan(image: str, repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """
    The image's scan of a repo's working tree in KDF's rules mode, as make scan mounts it.

    Args:
        image: the image
        repo: the repo
        *extra: further arguments to the scan mode

    Returns:
        subprocess.CompletedProcess[str]: the finished run
    """
    mounts = ["-v", f"{repo}:/src:ro", "-v", f"{repo / '.git'}:/gitdir:ro", "-v", f"{repo / '.git'}:/git:ro"]
    return docker("run", *LOCKED, *mounts, image, "scan", "--kdf-only", *extra)


def python_in(image: str, code: str, locked: bool) -> subprocess.CompletedProcess[str]:
    """
    The image's Python running a line, locked as the scan runs or with the network and root open, the control.

    Args:
        image: the image
        code: the line
        locked: whether the scan's fences apply

    Returns:
        subprocess.CompletedProcess[str]: the finished run
    """
    fences = LOCKED if locked else ["--rm", "--user", "0:0"]
    return docker("run", *fences, "--entrypoint", "python3", image, "-I", "-c", code)


def check(name: str, passed: bool, detail: str, failures: list[str]) -> None:
    """
    Print one fixture's result and keep a failure.

    Args:
        name: the fixture
        passed: whether it held
        detail: what was seen, never a rule's message
        failures: the failures so far
    """
    print(f"fixture   {'ok' if passed else 'FAIL'} {name}{'' if passed else ', ' + detail}")
    if not passed:
        failures.append(name)


def main(argv: list[str] | None = None) -> int:
    """
    Run every fixture against one image.

    Args:
        argv: the image's reference, sys.argv when None

    Returns:
        int: 0 when every fixture held, 1 otherwise
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("fixture   usage, image_fixtures.py <image>")
        return 1
    image, failures = args[0], []
    who = docker("run", *LOCKED, "--entrypoint", "id", image, "-u")
    check("the scan runs as a user that is not root", who.stdout.strip() == "65532", who.stdout.strip(), failures)
    written = python_in(image, NO_ROOT, locked = True)
    control = python_in(image, NO_ROOT, locked = False)
    check(
        "the root is read only, root's write its control",
        written.returncode != 0 and control.returncode == 0,
        f"locked {written.returncode}, open {control.returncode}",
        failures,
    )
    offline = python_in(image, FENCE_ONLY, locked = True)
    online  = python_in(image, FENCE_ONLY, locked = False)
    check(
        "the network is off, an open run's fetch its control",
        offline.returncode != 0 and online.returncode == 0,
        f"locked {offline.returncode}, open {online.returncode}",
        failures,
    )
    with tempfile.TemporaryDirectory(prefix = "kdf-scan-image-") as temp:
        clean = scan(image, make_repo(Path(temp) / "clean", vulnerable = False))
        last  = clean.stdout.strip().splitlines()[-1] if clean.stdout.strip() else ""
        check(
            "a clean repo ends clean in KDF's rules mode, its coverage named",
            clean.returncode == 0 and "rules kdf-only" in last and last.endswith("CLEAN (exit 0)"),
            last or clean.stderr.strip()[-200:],
            failures,
        )
        repo  = make_repo(Path(temp) / "vulnerable", vulnerable = True)
        found = scan(image, repo, "--public")
        named = "kdf-python-logger-secret-value" in found.stdout and "withheld" in found.stdout
        check(
            "KDF's rule finds its line, its message withheld in a public repo's log",
            found.returncode == 1 and named and "is written to a log" not in found.stdout,
            f"exit {found.returncode}",
            failures,
        )
        entry = docker("run", *LOCKED, "--entrypoint", "sh", image, "-c", "echo changed")
        check(
            "an entrypoint changed by hand names no image commit",
            "kdf-scan" not in entry.stdout,
            entry.stdout.strip()[:80],
            failures,
        )
    print(f"fixture   {len(failures)} failed" if failures else "fixture   every fixture held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
