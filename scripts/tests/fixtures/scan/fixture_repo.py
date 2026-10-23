"""
The repo untouched and the scan's own Python isolated, design 5.9's fifth part and row L31. git status of every file,
ignored ones too, is the same after `make scan` and after a scan at a commit. A repo venv's .pth file and sitecustomize,
and the variables that would point a Python at them, never run under the managed block's recipe. No run writes
bytecode into the scan folder, whose Python and bundle `--check` holds to their manifests from an ordinary window.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scanfix import ROOT, installed, make_repo, scan, status

MAKE = shutil.which("make")


@pytest.mark.skipif(MAKE is None or ROOT != Path("D:/KriegerDataForge-scan"), reason = "make scan runs the D: folder")
def test_make_scan_leaves_the_repo_as_it_found_it_and_runs_no_repo_python(tmp_path: Path) -> None:
    installed()
    marker = tmp_path / "hook-ran"
    hook   = f'import pathlib; pathlib.Path(r"{marker}").write_text("ran")\n'
    repo   = make_repo(tmp_path / "repo", {".gitignore": ".venv/\nbuild/\n", "src/app.py": "print(1)\n"})
    site   = repo / ".venv" / "Lib" / "site-packages"
    site.mkdir(parents = True)
    (site / "hostile.pth").write_text(hook, encoding = "utf-8")
    for place in (site, repo):
        (place / "sitecustomize.py").write_text(hook, encoding = "utf-8")
        (place / "usercustomize.py").write_text(hook, encoding = "utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "ignored.txt").write_text("ignored\n", encoding = "utf-8")
    before      = status(repo)
    environment = {
        **os.environ,
        "VIRTUAL_ENV": str(repo / ".venv"),
        "PYTHONPATH": os.pathsep.join([str(site), str(repo)]),
        "PYTHONSTARTUP": str(repo / "sitecustomize.py"),
        "PYTHONUSERBASE": str(repo / ".venv"),
    }
    done        = subprocess.run([MAKE, "scan"], cwd = repo, env = environment, capture_output = True, check = False)
    text        = done.stdout.decode("utf-8", "replace")
    assert done.returncode == 0 and text.rstrip("\n").splitlines()[-1].endswith("CLEAN (exit 0)"), text
    assert not marker.exists(), "a repo venv's hook ran under the scan's Python"
    assert status(repo) == before


def test_a_scan_at_a_commit_leaves_the_repo_as_it_found_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"})
    (repo / "src" / "app.py").write_text("print(2)\n", encoding = "utf-8")
    before = status(repo)
    result = scan(installed(), repo, "--at", "HEAD")
    assert result.result == "CLEAN" and result.last["state"] == "at-commit", result.text
    assert status(repo) == before


def test_no_run_writes_bytecode_and_check_passes_from_an_ordinary_window(tmp_path: Path) -> None:
    machine = installed()
    scan(machine, make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"}))
    assert not [path for path in machine.root.rglob("__pycache__")], "bytecode was written into the scan folder"
    command = [str(machine.python), "-I", "-S", "-B", str(machine.launcher), "--check"]
    done    = subprocess.run(command, capture_output = True, check = False)
    text    = done.stdout.decode("utf-8", "replace")
    assert done.returncode == 0, text
    assert "check     python" in text and "manifest ok" in text
    assert "check     permission ok" in text
