"""
The repo untouched and the image's own Python isolated, design 5.9's fifth part and row L31. git status of every file,
ignored ones too, is the same after a scan of the working tree and after a scan at a commit, the repo mounted read only.
A repo venv's .pth file and sitecustomize, and the variables that would point a Python at them, never run inside the
image, whose wrapper runs with -I, -S and -B and an environment of named variables alone.
"""

from __future__ import annotations

from pathlib import Path

from scanfix import installed, make_repo, scan, status


def test_a_scan_leaves_the_repo_as_it_found_it_and_runs_no_repo_python(tmp_path: Path) -> None:
    marker = "KDF-HOOK-RAN"
    hook   = f'print("{marker}")\n'
    repo   = make_repo(tmp_path / "repo", {".gitignore": ".venv/\nbuild/\n", "src/app.py": "print(1)\n"})
    site   = repo / ".venv" / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents = True)
    (site / "hostile.pth").write_text(f"import sys; sys.stdout.write('{marker}')\n", encoding = "utf-8")
    for place in (site, repo):
        (place / "sitecustomize.py").write_text(hook, encoding = "utf-8")
        (place / "usercustomize.py").write_text(hook, encoding = "utf-8")
    (repo / "build").mkdir()
    (repo / "build" / "ignored.txt").write_text("ignored\n", encoding = "utf-8")
    before  = status(repo)
    planted = {
        "VIRTUAL_ENV": "/src/.venv",
        "PYTHONPATH": "/src/.venv/lib/python3.14/site-packages:/src",
        "PYTHONSTARTUP": "/src/sitecustomize.py",
        "PYTHONUSERBASE": "/src/.venv",
        "SEMGREP_RULES": "/src/src",
        "GH_PACKAGES_PAT": "planted",
    }
    result  = scan(installed(), repo, env = planted)
    assert result.result == "CLEAN" and result.last["code"] == "0", result.text
    assert marker not in result.text, "a repo venv's hook ran inside the image"
    assert status(repo) == before


def test_a_scan_at_a_commit_leaves_the_repo_as_it_found_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"})
    (repo / "src" / "app.py").write_text("print(2)\n", encoding = "utf-8")
    before = status(repo)
    result = scan(installed(), repo, "--at", "HEAD")
    assert result.result == "CLEAN" and result.last["state"] == "at-commit", result.text
    assert status(repo) == before
