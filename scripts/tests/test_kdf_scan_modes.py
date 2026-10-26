"""
Tests for the wrapper's modes (D-085, design 5.3 to 5.5), `pr-tree`, the gate's scan and a local --pr's of a pull
request fetched into a bare repository before the scan, and `scan`, make scan's scan of a mounted working tree.

A pull request's rig is the scan's rig with a branch whose head is the pull request's, and a bare repository holding
main and the head, as the gate's first job fetches them. `pr-tree` takes the head, main and their merge base as GitHub
named them, checks each resolves in the bare repository, reads main's exclusions and `not_docs`, skips a docs only pull
request by the image's own ci_paths.py, checks the pull request's change to the gate's caller, and scans the head. A
mounted working tree's tests give the wrapper its git folders by argument, as the recipe's mounts do, a plain clone's
and a worktree's, and the host's core.autocrlf. None of the hostile cases may end CLEAN.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import subprocess
from pathlib import Path

import pytest
from tests.scan_fakes import COMMON, GIT, commit, git, load, make_rig, makefile, write

SCAN   = load("kdf_scan", COMMON / "kdf_scan.py")
CI_YML = "jobs:\n  secret-scan:\n    with:\n      not_docs: \"README.md\"\n"
VULN   = "eval(x)  # VULN(eval-detected)\n"
FOLDED = "jobs:\n  s:\n    with:\n      not_docs: >-\n        a.md\n        docs/b.md\n      other: 1\n"
CALLER = (COMMON / "kdf-scan-gate-caller.yml").read_text(encoding = "utf-8")

pytestmark = pytest.mark.skipif(GIT is None, reason = "the modes' tests need git")


class Pull:
    """
    A pull request's rig, its repo on a branch, the bare repository the gate fetched, and GitHub's ids.
    """
    def __init__(self, tmp_path: Path, files: dict[str, str | bytes] | None = None) -> None:
        first = {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": CI_YML}
        first.update(files or {})
        self.tmp  = tmp_path
        self.rig  = make_rig(tmp_path, SCAN, first)
        self.main = git(self.rig.repo, "rev-parse", "HEAD")
        self.bare = tmp_path / "fetched.git"
        self.head = ""
        git(self.rig.repo, "checkout", "-q", "-b", "feature")


    def open(self, files: dict[str, str | bytes], staged: bool = False) -> str:
        if staged:
            git(self.rig.repo, "commit", "-q", "-m", "the pull request, its index as staged")
            self.head = git(self.rig.repo, "rev-parse", "HEAD")
        else:
            self.head = commit(self.rig.repo, files, "the pull request")
        if self.bare.exists():
            subprocess.run(
                ["git", "-C", str(self.bare), "fetch", "-q", str(self.rig.repo), "+feature:refs/kdf/head"],
                check = True,
                capture_output = True,
            )
        else:
            subprocess.run(["git", "clone", "-q", "--bare", str(self.rig.repo), str(self.bare)], check = True)
        return self.head


    def merged(self) -> str:
        return git(self.bare, "merge-base", self.main, self.head)


    def run(self, commits: tuple[str, str, str] | None = None, caller_sha: str = "", **machine) -> tuple[int, str]:
        buffer = io.StringIO()
        code   = SCAN.pr_tree(
            self.rig.machine(**machine),
            self.bare,
            commits or (self.head, self.main, self.merged()),
            caller_sha,
            buffer,
        )
        return code, buffer.getvalue()

# ======================================================================================================================
# pr-tree, the head, main and their merge base
# ======================================================================================================================

def test_a_clean_pull_request_is_scanned_at_its_head_and_names_the_ids(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    code, out = pull.run()
    assert code == 0, out
    assert f"verify    head {pull.head} main {pull.main} merge base {pull.merged()} image {'b' * 40}" in out
    last = out.rstrip().splitlines()[-1]
    assert last.startswith(f"kdf-scan {pull.head[:12]} at-commit ") and last.endswith("CLEAN (exit 0)")


def test_mains_exclusions_apply_and_one_the_branch_adds_is_ignored_and_marked(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"Makefile": makefile("SCAN_EXCLUDE += src  # the branch hides its own code here"), "src/app.py": VULN})
    code, out = pull.run()
    assert code == 1, out
    assert "policy-added" in out.splitlines()[-1]


def test_main_is_the_id_github_named_and_its_policy_overrules_an_older_one(tmp_path: Path) -> None:
    wide = makefile("SCAN_EXCLUDE += src  # an old exclusion the base has since dropped")
    pull = Pull(tmp_path, {"Makefile": wide})
    git(pull.rig.repo, "checkout", "-q", "main")
    pull.main = commit(pull.rig.repo, {"Makefile": makefile()}, "main drops the exclusion")
    git(pull.rig.repo, "checkout", "-q", "feature")
    git(pull.rig.repo, "merge", "-q", "--no-edit", "main")
    pull.open({"src/app.py": VULN})
    code, out = pull.run()
    assert code == 1 and "src/app.py" in out, out


@pytest.mark.parametrize("which", ["head", "main", "merge base", "malformed"])
def test_an_id_that_does_not_resolve_is_refused_before_any_tool_runs(tmp_path: Path, which: str) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    head, main, merged = pull.head, pull.main, pull.merged()
    commits = {
        "head": ("e" * 40, main, merged),
        "main": (head, "e" * 40, merged),
        "merge base": (head, main, "e" * 40),
        "malformed": ("not a commit", main, merged),
    }[which]
    code, out = pull.run(commits)
    assert code == 2 and "REFUSED (exit 2)" in out, out
    assert pull.rig.calls("opengrep") == []


def test_a_merge_base_other_than_githubs_is_refused(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/app.py": VULN})
    code, out = pull.run((pull.head, pull.main, pull.head))
    assert code == 2 and "merge base" in out, out
    assert pull.rig.calls("opengrep") == []

# ======================================================================================================================
# pr-tree, hostile heads and repositories
# ======================================================================================================================

def test_a_replacement_ref_over_a_blob_and_a_commit_changes_nothing(tmp_path: Path) -> None:
    pull  = Pull(tmp_path)
    clean = pull.main
    head  = pull.open({"src/app.py": VULN})
    git(
        pull.bare,
        "replace",
        git(pull.bare, "rev-parse", f"{head}:src/app.py"),
        git(pull.bare, "rev-parse", f"{clean}:src/app.py"),
    )
    code, out = pull.run()
    assert code == 1, out


def test_a_hook_in_the_fetched_repository_never_runs(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/app.py": VULN})
    marker = tmp_path / "hook-ran"
    hook   = pull.bare / "hooks" / "reference-transaction"
    hook.parent.mkdir(exist_ok = True)
    hook.write_text(f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n", encoding = "utf-8", newline = "\n")
    hook.chmod(0o755)
    code, out = pull.run()
    assert code == 1 and "src/app.py:1" in out, out
    assert not marker.exists()


def test_a_symlink_and_a_gitlink_at_the_head_are_incomplete(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    blob = subprocess.run(
        ["git", "-C", str(pull.rig.repo), "hash-object", "-w", "--stdin"],
        input = b"src/app.py",
        capture_output = True,
        check = True,
    ).stdout.decode().strip()
    git(pull.rig.repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},src/link.py")
    git(pull.rig.repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},vendor/lib")
    pull.open({}, staged = True)
    code, out = pull.run()
    assert code == 4, out


def test_a_branchs_own_ci_paths_that_always_answers_docs_only_changes_nothing(tmp_path: Path) -> None:
    lying = "def docs_only(*args, **kwargs):\n    return True\n"
    pull  = Pull(tmp_path)
    pull.open({"ci_paths.py": lying, "scripts/common/ci_paths.py": lying, "src/app.py": VULN})
    code, out = pull.run()
    assert code == 1, out

# ======================================================================================================================
# pr-tree, docs only
# ======================================================================================================================

def test_a_docs_only_pull_request_is_skipped_by_the_images_ci_paths(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"docs/guide.md": "# a guide\n", "NOTES.md": "notes\n"})
    code, out = pull.run()
    assert code == 0, out
    assert "docs only" in out and out.rstrip().splitlines()[-1].endswith("DOCS-ONLY (exit 0)")
    assert pull.rig.calls("opengrep") == []


def test_a_docs_pull_request_holding_code_is_scanned(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({"docs/guide.md": "# a guide\n", "docs/tool.py": VULN})
    code, out = pull.run()
    assert code == 1, out


def test_a_readme_that_not_docs_names_is_scanned_as_code(tmp_path: Path) -> None:
    pull = Pull(tmp_path, {"README.md": "the readme\n"})
    pull.open({"README.md": "the readme changed\n"})
    code, out = pull.run()
    assert code == 0, out
    assert "docs only" not in out and pull.rig.calls("opengrep")


@pytest.mark.parametrize(("text", "expected"), [
    (CI_YML, ["README.md"]),
    ("jobs:\n  s:\n    with:\n      not_docs: \"\"\n", []),
    (FOLDED, ["a.md", "docs/b.md"]),
    ("jobs:\n  s:\n    with:\n      other: 1\n", None),
    ("jobs:\n  a:\n    with:\n      not_docs: \"a.md\"\n  b:\n    with:\n      not_docs: \"b.md\"\n", None),
])
def test_not_docs_is_read_from_the_callers_ci_yml(text: str, expected: list[str] | None) -> None:
    assert SCAN.read_not_docs(text) == expected

# ======================================================================================================================
# pr-tree, the gate's caller and workflows that name the gate
# ======================================================================================================================

def test_a_caller_change_to_cicds_canonical_text_passes_and_is_printed_first(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({SCAN.CALLER_PATH: CALLER})
    code, out = pull.run(caller_sha = hashlib.sha256(CALLER.encode("utf-8")).hexdigest())
    assert code == 0, out
    assert "becomes cicd's canonical caller" in out and "caller-changed" in out.splitlines()[-1]


def test_any_other_caller_change_fails(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({SCAN.CALLER_PATH: CALLER.replace("kdf-scan-gate-reusable.yml@main", "kdf-scan-gate-reusable.yml@v1")})
    code, out = pull.run(caller_sha = hashlib.sha256(CALLER.encode("utf-8")).hexdigest())
    assert code == 1 and "changes to other than cicd's canonical caller" in out, out


def test_a_caller_change_with_no_canonical_hash_to_hold_it_to_fails(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({SCAN.CALLER_PATH: CALLER})
    code, out = pull.run()
    assert code == 1, out


def test_another_workflow_that_names_the_gate_fails_and_cicds_own_reusable_is_apart(tmp_path: Path) -> None:
    pull = Pull(tmp_path)
    pull.open({".github/workflows/fake.yml": "jobs:\n  kdf-scan-gate:\n    runs-on: ubuntu-latest\n"})
    code, out = pull.run()
    assert code == 1 and ".github/workflows/fake.yml names the gate" in out, out
    pull = Pull(tmp_path / "cicd")
    pull.open({SCAN.REUSABLE_PATH: "on:\n  workflow_call:\njobs:\n  kdf-scan-gate:\n    runs-on: ubuntu-latest\n"})
    code, out = pull.run()
    assert "names the gate" not in out, out

# ======================================================================================================================
# scan, a mounted working tree
# ======================================================================================================================

def mounted(src: Path, git_dir: Path, common: Path, autocrlf: str = "", pinned: str = "", cicd: str = "") -> object:
    return argparse.Namespace(
        src = str(src),
        git_dir = str(git_dir),
        common_dir = str(common),
        autocrlf = autocrlf,
        pinned = pinned,
        cicd_digest = cicd,
    )


def mounted_run(rig, args) -> tuple[int, str]:
    buffer = io.StringIO()
    code   = SCAN.mounted_scan(rig.machine(), args, buffer)
    return code, buffer.getvalue()


def test_a_plain_clone_scans_through_its_named_git_folder(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git"))
    assert code == 0, out
    assert " clean-tree " in out.splitlines()[-1]


def test_windows_line_endings_read_clean_with_the_hosts_autocrlf_and_dirty_without(tmp_path: Path) -> None:
    # a Windows checkout's index records the CRLF file's size, as Git for Windows refreshed it, and inside the
    # container the stat data differs while the size matches, so git hashes the content and core.autocrlf decides
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": "a = 1\nb = 2\n"})
    file = rig.repo / "src" / "app.py"
    file.write_bytes(b"a = 1\r\nb = 2\r\n")
    # staged as Git for Windows would, the same LF blob and the CRLF file's size in the index, since git calls a file
    # whose size differs from its index entry changed without reading it
    git(rig.repo, "-c", "core.autocrlf=true", "add", "src/app.py")
    assert git(rig.repo, "rev-parse", ":src/app.py") == git(rig.repo, "rev-parse", "HEAD:src/app.py")
    later = file.stat().st_mtime + 60
    os.utime(file, (later, later))
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git", autocrlf = "true"))
    assert code == 0 and " clean-tree " in out.splitlines()[-1], out
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git"))
    assert " dirty-tree " in out.splitlines()[-1], out


def test_a_worktree_scans_through_its_own_and_its_common_git_folder(tmp_path: Path) -> None:
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    tree = tmp_path / "worktree"
    git(rig.repo, "worktree", "add", "-q", "-b", "feature", str(tree))
    write(tree, {"src/new.py": VULN})
    admin = Path(git(tree, "rev-parse", "--path-format=absolute", "--git-dir"))
    code, out = mounted_run(rig, mounted(tree, admin, rig.repo / ".git"))
    assert code == 1 and "src/new.py:1" in out, out
    assert " dirty-tree " in out.splitlines()[-1]


def test_a_git_folder_outside_the_common_one_is_refused(tmp_path: Path) -> None:
    # git reads a worktree's refs through its commondir file, so a folder mounted apart from the common one resolves
    # nothing, found by the probe of 2026-10-26, and is refused with the reason
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    code, out = mounted_run(rig, mounted(rig.repo, tmp_path / "elsewhere", rig.repo / ".git"))
    assert code == 2 and "neither" in out, out
    assert rig.calls("opengrep") == []


@pytest.mark.parametrize("key", ["filter.lfs.clean", "include.path", "includeIf.gitdir:/x.path"])
def test_a_repositorys_own_filter_or_include_is_refused(tmp_path: Path, key: str) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    git(rig.repo, "config", key, "cat")
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git"))
    assert code == 2 and key.lower().split(".")[0] in out.lower(), out
    assert rig.calls("opengrep") == []


def test_an_fsmonitor_in_the_repositorys_configuration_is_turned_off_and_never_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    git(rig.repo, "config", "core.fsmonitor", str(tmp_path / "no-such-program"))
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git"))
    assert code == 0, out


def test_an_autocrlf_git_takes_none_of_is_refused(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git", autocrlf = "yes"))
    assert code == 2, out


def test_the_block_pinning_another_digest_than_cicds_warns(tmp_path: Path) -> None:
    rig  = make_rig(tmp_path, SCAN, {"src/app.py": "print(1)\n"})
    args = mounted(
        rig.repo,
        rig.repo / ".git",
        rig.repo / ".git",
        pinned = "sha256:" + "a" * 64,
        cicd = "sha256:" + "b" * 64,
    )
    code, out = mounted_run(rig, args)
    assert code == 0 and "image-behind" in out.splitlines()[-1], out


def test_the_rules_cache_is_read_through_its_own_folder_never_the_working_trees(tmp_path: Path) -> None:
    # the git folders a mode names apply to the working tree alone, so the rules' cache reads as itself
    rig = make_rig(tmp_path, SCAN, {"src/app.py": "eval(x)  # VULN(eval-detected)\n"})
    code, out = mounted_run(rig, mounted(rig.repo, rig.repo / ".git", rig.repo / ".git"))
    assert code == 1 and "eval-detected" in out, out
    assert SCAN.GIT_FOLDERS == {} and SCAN.NEUTRAL_GIT is None and SCAN.AUTOCRLF is None
