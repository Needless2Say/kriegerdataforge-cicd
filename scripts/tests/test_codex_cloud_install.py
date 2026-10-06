"""
Tests for the Codex cloud environment's install script (D-048).

`tools/codex-cloud/kdf-codex-install.sh` installs a reviewed repo with no token, leaving out every development package
from the owner's private repos, and refuses a repo whose runtime lockfile names one. Here stubs play python3.14, uv
and the venv's python, so no test touches a network. Each records how it was called, the venv's pip what it read from
a requirements file, and the script is run against a workspace folder of the test's own. The real install was run on
the kdf-sdk at d9a4602 in a python:3.14.7-slim container and in a uv image without Python, and the owner's
`kdf-sdk-review` environment ran it on 2026-10-04, the pull request of D-048 records both.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT    = Path(__file__).resolve().parents[2]
TOOLS   = ROOT / "tools" / "codex-cloud"
SCRIPT  = TOOLS / "kdf-codex-install.sh"
SKILL   = TOOLS / "kdf-codex-start-skill.md"
BASH    = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
REPO    = "kriegerdataforge-sdk"
PRIVATE = "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@main"

# the venv's python. Each call is one line of the log, and a pip install that reads a requirements file also logs every
# line it read, so a test sees what reached pip. STUB_FAIL names a call that fails, the way a broken install would
VENV_PYTHON = """#!/usr/bin/env bash
echo "venv-python $*" >> "$STUB_LOG"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ] && [ "${3:-}" = "install" ] && [ "${4:-}" = "-r" ]; then
	while IFS= read -r line; do echo "  read $line" >> "$STUB_LOG"; done < "$5"
fi
case "$*" in *"${STUB_FAIL:-no failure}"*) echo "pip failed"; exit 2 ;; esac
exit 0
"""

# a system python. `-m venv --clear .venv` makes a venv whose python is the stub above
SYSTEM_PYTHON = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
	mkdir -p "${@: -1}/bin"
	cp "$STUB_VENV_PYTHON" "${@: -1}/bin/python"
	chmod +x "${@: -1}/bin/python"
fi
exit 0
"""

# uv. `python install 3.14` puts a python under UV_PYTHON_INSTALL_DIR, `python find 3.14` prints its path
UV = """#!/usr/bin/env bash
echo "uv $* dir=${UV_PYTHON_INSTALL_DIR:-unset}" >> "$STUB_LOG"
found="$UV_PYTHON_INSTALL_DIR/cpython-3.14/bin/python3.14"
case "$*" in
	"python install 3.14") mkdir -p "$(dirname "$found")"; cp "$STUB_SYSTEM_PYTHON" "$found"; chmod +x "$found" ;;
	"python find 3.14") echo "$found" ;;
esac
exit 0
"""

pytestmark = pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "bash is needed")


@dataclass
class Box:
    """
    A workspace with the reviewed repo in it, a folder of stubs, and the log the stubs write, outside the workspace.
    """
    workspace: Path
    repo: Path
    stubs: Path
    log: Path


def _executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding = "utf-8", newline = "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture()
def box(tmp_path: Path) -> Box:
    workspace = tmp_path / "workspace"
    repo      = workspace / REPO
    repo.mkdir(parents = True)
    (repo / "requirements.txt").write_text("httpx==0.28.1 \\\n    --hash=sha256:abc\n", encoding = "utf-8")
    (repo / "requirements-dev.in").write_text(f"pip==26.2.1\nruff==0.16.8\n{PRIVATE}\n", encoding = "utf-8")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _executable(stubs / "venv-python", VENV_PYTHON)
    _executable(stubs / "system-python", SYSTEM_PYTHON)
    return Box(workspace = workspace, repo = repo, stubs = stubs, log = tmp_path / "stub.log")


def _path(box: Box, with_python: bool) -> str:
    """
    The stubs first, with python3.14 among them or not, and uv always. Then the machine's own PATH without any folder
    that holds a real python3.14, so the script finds one only where a test put it.
    """
    bin_dir = box.stubs / ("bin-python" if with_python else "bin-uv")
    bin_dir.mkdir(exist_ok = True)
    _executable(bin_dir / "uv", UV)
    if with_python:
        _executable(bin_dir / "python3.14", SYSTEM_PYTHON)
    folders = [
        folder for folder in os.environ.get("PATH", "").split(os.pathsep)
        if folder and not any((Path(folder) / name).exists() for name in ("python3.14", "python3.14.exe"))
    ]
    return os.pathsep.join([bin_dir.as_posix(), *folders])


def _install(box: Box, with_python: bool = True, fail: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PATH": _path(box, with_python),
        "KDF_CODEX_WORKSPACE": box.workspace.as_posix(),
        "STUB_LOG": box.log.as_posix(),
        "STUB_VENV_PYTHON": (box.stubs / "venv-python").as_posix(),
        "STUB_SYSTEM_PYTHON": (box.stubs / "system-python").as_posix(),
    }
    environment.pop("STUB_FAIL", None)
    if fail is not None:
        environment["STUB_FAIL"] = fail
    return subprocess.run(
        [str(BASH), str(SCRIPT)],
        capture_output = True,
        text = True,
        env = environment,
        check = False,
    )


def _log(box: Box) -> str:
    return box.log.read_text(encoding = "utf-8") if box.log.exists() else ""


def test_a_clean_install_leaves_the_private_package_out_and_reaches_pip_check(box: Box) -> None:
    """
    Exit 0. The image's python3.14 makes the venv, pip installs the lockfile, then the development pins without the
    private line, then the repo itself without dependencies, and pip check closes the install.
    """
    done = _install(box)
    assert done.returncode == 0, done.stdout + done.stderr
    log = _log(box)
    assert "python3.14 -m venv --clear .venv" in log
    assert "venv-python -m pip install -r requirements.txt" in log
    assert "  read pip==26.2.1" in log
    assert "  read ruff==0.16.8" in log
    assert "kdf-fmt" not in log
    assert "venv-python -m pip install -e . --no-deps" in log
    assert log.rstrip().endswith("venv-python -m pip check")
    assert "uv " not in log
    assert "installed kriegerdataforge-sdk without its private development packages" in done.stderr


def test_without_python3_14_uv_installs_it_under_the_workspace(box: Box) -> None:
    """
    An image with no python3.14 gets one from uv, kept under the workspace so the published environment keeps it.
    """
    done = _install(box, with_python = False)
    assert done.returncode == 0, done.stdout + done.stderr
    log      = _log(box)
    expected = f"dir={box.workspace.as_posix()}/.local/share/uv/python"
    assert f"uv python install 3.14 {expected}" in log
    assert f"uv python find 3.14 {expected}" in log
    assert "python3.14 -m venv --clear .venv" in log
    assert "venv-python -m pip check" in log


def test_a_venv_that_runs_is_kept_and_a_broken_one_is_made_again(box: Box) -> None:
    """
    A second run keeps the venv the first one made. A venv whose python is gone is made again with --clear.
    """
    assert _install(box).returncode == 0
    box.log.unlink()
    again = _install(box)
    assert again.returncode == 0, again.stdout + again.stderr
    assert "-m venv" not in _log(box)
    (box.repo / ".venv" / "bin" / "python").unlink()
    box.log.unlink()
    broken = _install(box)
    assert broken.returncode == 0, broken.stdout + broken.stderr
    assert "python3.14 -m venv --clear .venv" in _log(box)


def test_a_private_runtime_package_stops_before_any_install(box: Box) -> None:
    """
    A backend's lockfile names kdf-sdk from a private repo. Its install would need a token, so the script stops with
    exit 1 before it makes a venv.
    """
    lockfile = box.repo / "requirements.txt"
    lockfile.write_text(
        "kdf-sdk @ git+https://github.com/Needless2Say/kriegerdataforge-sdk.git@v0.12.2\n",
        encoding = "utf-8",
    )
    done = _install(box)
    assert done.returncode == 1
    assert "requirements.txt installs a private package, which needs a token" in done.stderr
    assert _log(box) == ""


@pytest.mark.parametrize("missing", ["requirements.txt", "requirements-dev.in"])
def test_a_missing_requirements_file_stops_before_any_install(box: Box, missing: str) -> None:
    (box.repo / missing).unlink()
    done = _install(box)
    assert done.returncode == 1
    assert f"no {missing} in kriegerdataforge-sdk" in done.stderr
    assert _log(box) == ""


@pytest.mark.parametrize(
    "call",
    ["-r requirements.txt", "-r /dev/stdin", "-e . --no-deps", "pip check"],
)
def test_a_failing_step_fails_the_install(box: Box, call: str) -> None:
    """
    The control. Any pip call that fails fails the whole script, so no agent starts on a half installed environment.
    """
    done = _install(box, fail = call)
    assert done.returncode != 0
    assert "installed kriegerdataforge-sdk" not in done.stderr


def test_the_script_holds_no_secret_and_keeps_lf_line_ends() -> None:
    """
    The owner pastes the script into Codex, which runs it under bash on Linux. It names no token or secret, and the
    start skill it ships with names no finding and asks for no credential.
    """
    assert "tools/codex-cloud/*.sh" in (ROOT / ".gitattributes").read_text(encoding = "utf-8")
    script = SCRIPT.read_bytes()
    assert b"\r" not in script
    for word in (b"TOKEN", b"PAT", b"SECRET", b"secret_", b"password"):
        assert word not in script, word
    skill = SKILL.read_text(encoding = "utf-8")
    assert "Never ask for a token or a credential." in skill
    assert "The agent reaches `github.com` alone" in skill
    assert "failed" not in skill
    assert "defect" not in skill
