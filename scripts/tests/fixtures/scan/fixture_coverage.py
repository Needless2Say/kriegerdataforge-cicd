"""
Coverage, design 5.9's third part. A file the tools did not read whole makes the scan incomplete, never clean, unless a
recorded limit names that file's content. Python 3.14's `except A, B:` and template strings, a file over the size
limit, an unparsable one, a recorded limit passing on its blob and failing after one byte changes, and a workflow
zizmor cannot load. At a commit, export-ignore and export-subst, a replacement ref, a symlink and a gitlink, none ending
CLEAN, row L2 and Codex's revision read.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from scanfix import commit, git, installed, lines, make_repo, scan

SHELL = "import subprocess\n\n\ndef run(command):\n    return subprocess.run(command, shell=True, check=True)\n"
BROKEN          = "def broken(:\n    pass\n"
ATTRIBUTES      = lines(
    "src/hidden.py export-ignore",
    ".github/workflows/hidden.yml export-ignore",
    "src/subst.py export-subst",
)
HIDDEN_WORKFLOW = lines(
    "name: hidden",
    "on: push",
    "permissions: {}",
    "jobs:",
    "  build:",
    "    runs-on: ubuntu-latest",
    "    steps:",
    "      - uses: actions/checkout@v4",
)


def test_python_3_14s_new_forms_are_read_whole_or_the_scan_is_incomplete(tmp_path: Path) -> None:
    modern = (
        "def safe(call):\n    try:\n        return call()\n    except ValueError, TypeError:\n        return None\n\n\n"
        'def greet(name):\n    return t"hello {name}"\n'
    )
    result = scan(installed(), make_repo(tmp_path / "repo", {"src/modern.py": modern}))
    print(f"FIXTURE-NOTE python 3.14 forms, {result.last['result']}")
    if result.result == "CLEAN":
        assert "opengrep  1 of 1 inventory files read" in result.text, result.text
    else:
        assert result.result == "INCOMPLETE", result.text


def test_a_file_over_the_size_limit_and_an_unparsable_one_are_each_incomplete(tmp_path: Path) -> None:
    for name, text in (("big", "x = 1\n" * 200000), ("broken", BROKEN)):
        result = scan(installed(), make_repo(tmp_path / name, {f"src/{name}.py": text}))
        assert result.result == "INCOMPLETE" and result.last["code"] == "4", (name, result.text)


def test_a_recorded_limit_passes_on_its_blob_and_fails_after_one_byte_changes(tmp_path: Path) -> None:
    digest = hashlib.sha256(BROKEN.encode()).hexdigest()
    limit  = f"SCAN_LIMIT += src/broken.py@{digest}  # opengrep cannot parse this fixture file at all"
    repo   = make_repo(tmp_path / "repo", {"src/broken.py": BROKEN}, own = (limit,))
    result = scan(installed(), repo)
    assert result.result == "CLEAN" and result.last["limits"] == "1", result.text
    (repo / "src" / "broken.py").write_text(BROKEN + "#\n", encoding = "utf-8", newline = "\n")
    result = scan(installed(), repo)
    assert result.result == "INCOMPLETE", result.text


def test_a_workflow_zizmor_cannot_load_is_incomplete(tmp_path: Path) -> None:
    files  = {".github/workflows/bad.yml": "name: bad\non: push\njobs: [unclosed\n"}
    result = scan(installed(), make_repo(tmp_path / "repo", files))
    assert result.result == "INCOMPLETE", result.text


def test_export_ignore_and_export_subst_hide_nothing_from_a_scan_at_a_commit(tmp_path: Path) -> None:
    files  = {
        ".gitattributes": ATTRIBUTES,
        "src/hidden.py": SHELL,
        "src/subst.py": "# $Format:%H$\n" + SHELL,
        ".github/workflows/hidden.yml": HIDDEN_WORKFLOW,
    }
    repo   = make_repo(tmp_path / "repo", files)
    result = scan(installed(), repo, "--at", "HEAD")
    assert result.result != "CLEAN", result.text
    found = result.fails()
    assert ("src/hidden.py", "subprocess-shell-true") in found, result.text
    assert ("src/subst.py", "subprocess-shell-true") in found, result.text
    assert (".github/workflows/hidden.yml", "unpinned-uses") in found, result.text


def test_a_replacement_ref_swapping_in_a_clean_blob_changes_nothing_scanned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo", {"src/run_command.py": SHELL})
    vuln = git(repo, "rev-parse", "HEAD:src/run_command.py")
    (repo / "clean.txt").write_text("def run(command):\n    return command\n", encoding = "utf-8", newline = "\n")
    clean = git(repo, "hash-object", "-w", "clean.txt")
    (repo / "clean.txt").unlink()
    git(repo, "replace", vuln, clean)
    result = scan(installed(), repo, "--at", "HEAD")
    assert ("src/run_command.py", "subprocess-shell-true") in result.fails(), result.text


def test_a_symlink_and_a_gitlink_at_a_commit_are_incomplete(tmp_path: Path) -> None:
    repo   = make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"})
    target = git(repo, "rev-parse", "HEAD:src/app.py")
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{target},src/link.py")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{git(repo, 'rev-parse', 'HEAD')},vendor/sub")
    git(repo, "commit", "-q", "-m", "a symlink and a gitlink")
    result = scan(installed(), repo, "--at", "HEAD")
    assert result.result == "INCOMPLETE", result.text


def test_a_clean_repo_ends_clean_and_names_its_commit_and_the_bundle(tmp_path: Path) -> None:
    machine = installed()
    repo    = make_repo(tmp_path / "repo", {"src/app.py": "print(1)\n"})
    result  = scan(machine, repo)
    assert result.result == "CLEAN" and result.last["code"] == "0", result.text
    assert result.last["commit"] == git(repo, "rev-parse", "HEAD")[:12]
    assert result.last["bundle"] == machine.bundle[:12]
    commit(repo, {"src/more.py": "print(2)\n"})
    assert scan(machine, repo).last["state"] == "clean-tree"
