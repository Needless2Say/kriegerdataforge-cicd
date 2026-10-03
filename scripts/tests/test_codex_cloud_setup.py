"""
Tests for the Codex cloud environment's setup script, on trial for the kdf-sdk's S2 (D-039).

`tools/codex-cloud/kdf-codex-setup.sh` installs a reviewed repo with its own `make setup`, the private packages' token
in the environment of that one command, and then fails the setup when the token's value is in any file the install
could have written. Here a stub plays make, so no test touches a network. It records what it was handed without ever
writing the token, and writes the token where a leaking install would, so the self check is proven to fail first.
The script's real install, pip and git through a local server with an image's credential helper, was rehearsed in a
python:3.14.7-slim container, the pull request of D-039 records the run.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT   = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "codex-cloud" / "kdf-codex-setup.sh"
BASH   = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
TOKEN  = "github_pat_FAKE0123456789abcdefTESTONLY0123456789"

# a stand in for make. It says whether it got the token through its environment, never writes the value, and does what
# STUB_MODE says a leaking or a failing install would
STUB_MAKE = """#!/usr/bin/env bash
{
	[ "${GH_PACKAGES_PAT:-}" = "$STUB_EXPECT" ] && echo "pat=match" || echo "pat=mismatch"
	echo "secret=${KDF_CODEX_PACKAGES_TOKEN:-unset}"
	echo "global=${GIT_CONFIG_GLOBAL:-unset} nosystem=${GIT_CONFIG_NOSYSTEM:-unset} prompt=${GIT_TERMINAL_PROMPT:-unset}"
	echo "nocache=${PIP_NO_CACHE_DIR:-unset}"
	echo "args=$*"
} >> "$STUB_LOG"
case "${STUB_MODE:-clean}" in
	clean) echo "installed" ;;
	helper) printf 'https://__token__:%s@github.com\\n' "$GH_PACKAGES_PAT" > "$HOME/.git-credentials" ;;
	venv) mkdir -p .venv/leak; printf 'x' > ".venv/leak/$GH_PACKAGES_PAT.txt" ;;
	noisy) echo "fatal: could not read from https://__token__:$GH_PACKAGES_PAT@github.com/x.git" ;;
	fail) echo "pip failed"; exit 2 ;;
esac
"""

pytestmark = pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "bash is needed")


@dataclass
class Box:
    """
    The places the script searches, a home, a repo, a temp folder and pip's cache, the stub's folder and its log
    outside all of them.
    """
    home: Path
    repo: Path
    tmp: Path
    cache: Path
    bin: Path
    log: Path


@pytest.fixture()
def box(tmp_path: Path) -> Box:
    places = {name: tmp_path / name for name in ("home", "repo", "tmp", "cache", "bin")}
    for place in places.values():
        place.mkdir()
    for name, text in (("make", STUB_MAKE), ("python3.14", "#!/usr/bin/env bash\nexit 0\n")):
        stub = places["bin"] / name
        stub.write_text(text, encoding = "utf-8", newline = "\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Box(**places, log = tmp_path / "stub.log")


def _setup(box: Box, mode: str = "clean", token: str | None = TOKEN) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PATH": box.bin.as_posix() + os.pathsep + os.environ.get("PATH", ""),
        "HOME": box.home.as_posix(),
        "TMPDIR": box.tmp.as_posix(),
        "PIP_CACHE_DIR": box.cache.as_posix(),
        "STUB_LOG": box.log.as_posix(),
        "STUB_MODE": mode,
        "STUB_EXPECT": token or "",
    }
    environment.pop("KDF_CODEX_PACKAGES_TOKEN", None)
    if token is not None:
        environment["KDF_CODEX_PACKAGES_TOKEN"] = token
    return subprocess.run(
        [str(BASH), str(SCRIPT)],
        cwd = box.repo,
        capture_output = True,
        text = True,
        env = environment,
        check = False,
    )


def test_a_clean_install_passes_and_the_token_reached_make_through_its_environment_alone(box: Box) -> None:
    """
    Exit 0. Make got the token as GH_PACKAGES_PAT, not the secret's own name and not on its command line, with git's
    global and system config switched off, no password prompt and no pip cache.
    """
    done = _setup(box)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "the token is in no file" in done.stderr
    log = box.log.read_text(encoding = "utf-8")
    assert "pat=match" in log
    assert "secret=unset" in log
    assert "global=/dev/null nosystem=1 prompt=0" in log
    assert "nocache=1" in log
    assert "args=setup\n" in log
    assert TOKEN not in log


@pytest.mark.parametrize(
    ("mode", "named"),
    [
        ("helper", ".git-credentials"),
        ("venv", "<the token>.txt"),
    ],
)
def test_a_token_left_on_disk_fails_the_setup_and_only_its_path_is_printed(box: Box, mode: str, named: str) -> None:
    """
    The control. An install that leaves the token in a credentials file, or in a path's own name, fails with exit 3, and
    the path is printed with the value masked, the value nowhere in the output.
    """
    done = _setup(box, mode = mode)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "the token is on disk after the install" in done.stderr
    assert named in done.stderr
    assert TOKEN not in done.stdout + done.stderr


def test_what_the_install_prints_is_masked(box: Box) -> None:
    """
    Codex shows the setup's output, so a line that carries the value prints with the value replaced.
    """
    done = _setup(box, mode = "noisy")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "https://__token__:<the token>@github.com/x.git" in done.stdout
    assert TOKEN not in done.stdout + done.stderr


def test_no_secret_and_a_failed_install_stop_before_the_agent(box: Box) -> None:
    """
    No secret is exit 1 before make runs. A failing make is exit 1 and nothing is searched.
    """
    missing = _setup(box, token = None)
    assert missing.returncode == 1
    assert "no KDF_CODEX_PACKAGES_TOKEN secret" in missing.stderr
    assert not box.log.exists()
    failed = _setup(box, mode = "fail")
    assert failed.returncode == 1
    assert "make setup failed, exit 2" in failed.stderr


def test_the_setup_script_keeps_lf_line_ends_and_the_process_names_it() -> None:
    """
    The owner pastes the script into Codex, which runs it under bash on Linux, and the process names it with its secret.
    """
    assert "tools/codex-cloud/*.sh" in (ROOT / ".gitattributes").read_text(encoding = "utf-8")
    assert b"\r" not in SCRIPT.read_bytes()
    process = " ".join(
        (ROOT / "kit" / "common" / "docs" / "agent" / "CODE_REVIEW_PROCESS.md") .read_text(encoding = "utf-8").split(),
    )
    assert "`kriegerdataforge-cicd/tools/codex-cloud/kdf-codex-setup.sh`" in process
    assert "`KDF_CODEX_PACKAGES_TOKEN`" in process
    assert "never `GH_PACKAGES_PAT`" in process
