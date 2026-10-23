"""
Tests for the launcher's verify mode, `kdf-scan.py --pr <link>`, the scan before a merge and the reviewer's local gate
(D-085, design 5.5).

Each test makes a bare remote holding main and a pull request's head at refs/pull/1/head, a clone of it, and a stand
in gh that answers for GitHub, then runs the launcher's verify mode in the clone. The mode asks GitHub for the head
and main, fetches both into a private ref and checks their ids, compares the pasted line's commit with the head, reads
the exclusions and `not_docs` at GitHub's main and scans the head unless the bundle's ci_paths.py calls it docs only.
None of the hostile cases may end CLEAN.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zlib
from pathlib import Path

import pytest
from tests.scan_fakes import (
    COMMIT,
    COMMON,
    FAKE_GH,
    GIT,
    PYTHON,
    bundle_files,
    commit,
    git,
    install_bundle,
    load,
    make_rig,
    makefile,
    platform,
    program,
)

SCAN     = load("kdf_scan", COMMON / "kdf_scan.py")
LAUNCHER = load("kdf_scan_launcher", COMMON / "kdf_scan_launcher.py")
LINK     = "https://github.com/Needless2Say/tenant/pull/1"
CI_YML   = "jobs:\n  secret-scan:\n    with:\n      not_docs: \"README.md\"\n"
VULN     = "eval(x)  # VULN(eval-detected)\n"
FOLDED   = "jobs:\n  s:\n    with:\n      not_docs: >-\n        a.md\n        docs/b.md\n      other: 1\n"

pytestmark = pytest.mark.skipif(GIT is None, reason = "the verify mode's tests need git")


class Pull:
    """
    A pull request's rig, the remote, the clone, its head and GitHub's main, and how GitHub answers.
    """
    def __init__(self, tmp_path: Path, files: dict[str, str | bytes] | None = None) -> None:
        first = {"src/app.py": "print(1)\n", ".github/workflows/ci.yml": CI_YML}
        first.update(files or {})
        self.rig    = make_rig(tmp_path, SCAN, first)
        self.remote = tmp_path / "remote.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.rig.repo), str(self.remote)], check = True)
        git(self.remote, "config", "uploadpack.allowFilter", "true")
        git(self.rig.repo, "remote", "add", "origin", str(self.remote))
        git(self.rig.repo, "fetch", "-q", "origin")
        git(self.rig.repo, "checkout", "-q", "-b", "feature")
        self.head = ""
        self.main = git(self.remote, "rev-parse", "main")
        self.body = ""
        self.answers: dict = {}
        install_bundle(self.rig.base, bundle_files())


    def open(self, files: dict[str, str | bytes], body: str | None = None, staged: bool = False) -> str:
        if staged:
            git(self.rig.repo, "commit", "-q", "-m", "the pull request, its index as staged")
            self.head = git(self.rig.repo, "rev-parse", "HEAD")
        else:
            self.head = commit(self.rig.repo, files, "the pull request")
        git(self.rig.repo, "push", "-q", "-f", "origin", "HEAD:refs/pull/1/head")
        self.body = body if body is not None else self.line(self.head)
        return self.head


    def line(self, head: str) -> str:
        return (f"kdf-scan {head[:12]} clean-tree bundle {COMMIT[:12]} opengrep 1.30.2 rules {self.rig.commit[:8]} "
                f"zizmor 1.30.1 limits 0: CLEAN (exit 0)")


    def compare(self) -> dict:
        # GitHub's compare answer, read from the remote, or main's own when the head names no commit there
        found = subprocess.run(
            ["git", "-C", str(self.remote), "merge-base", self.main, self.head],
            capture_output = True,
            text = True,
            check = False,
        ).stdout.strip()
        if not found:
            return {"merge_base_commit": {"sha": self.main}, "ahead_by": 0, "behind_by": 0}
        ahead  = git(self.remote, "rev-list", "--count", f"{self.main}..{self.head}")
        behind = git(self.remote, "rev-list", "--count", f"{self.head}..{self.main}")
        return {"merge_base_commit": {"sha": found}, "ahead_by": int(ahead), "behind_by": int(behind)}


    def run(self, repo: Path | None = None, link: str = LINK, fence = None) -> int:
        answers = {
            "repos/Needless2Say/kriegerdataforge-cicd/commits": [{"sha": COMMIT}],
            "repos/Needless2Say/kriegerdataforge-cicd/compare": {"status": "identical"},
            "repos/Needless2Say/tenant/pulls/1": {
                "head": {"sha": self.head},
                "base": {"ref": "main"},
                "body": self.body,
            },
            "repos/Needless2Say/tenant/commits/main": {"sha": self.main},
            "repos/Needless2Say/tenant/compare": self.compare(),
        }
        answers.update(self.answers)
        program(self.rig.tools / "gh.py", FAKE_GH)
        (self.rig.tools / "gh.json").write_text(json.dumps({"answers": answers}), encoding = "utf-8")


        def machine(wrapper, root, bundle):
            return self.rig.machine_for(wrapper, bundle = bundle.commit, files = bundle.files, root = root)


        hooks = LAUNCHER.Hooks(
            machine = machine,
            gh = (str(PYTHON), str(self.rig.tools / "gh.py")),
            git = GIT,
            remote = lambda project: self.remote.as_uri(),
        )
        return LAUNCHER.main(
            ["--repo", str(repo or self.rig.repo), "--pr", link],
            root = self.rig.base,
            platform = fence or platform(),
            hooks = hooks,
        )


def verify(pull: Pull, capsys: pytest.CaptureFixture[str], **options) -> tuple[int, str]:
    code = pull.run(**options)
    return code, capsys.readouterr().out

# ======================================================================================================================
# the head, main and the pasted line
# ======================================================================================================================

def test_a_clean_pull_request_whose_pasted_line_names_its_head_matches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    code, out = verify(pull, capsys)
    assert code == 0, out
    assert "pasted MATCH" in out
    last = out.rstrip().splitlines()[-1]
    assert last.startswith(f"kdf-scan {pull.head[:12]} at-commit ") and last.endswith("CLEAN (exit 0)")


@pytest.mark.parametrize(("body", "state"), [
    ("", "MISSING"),
    ("kdf-scan not run, the tools are not installed here", "NOT RUN"),
    (f"kdf-scan {'a' * 12} clean-tree bundle x opengrep 1.30.2: CLEAN (exit 0)", "DIFFERS"),
])
def test_a_missing_unrun_or_other_pasted_line_is_named_and_the_head_scanned(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    body: str,
    state: str,
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": VULN}, body = body)
    code, out = verify(pull, capsys)
    assert code == 1, out
    assert f"pasted {state}" in out


def test_main_comes_from_github_and_overrules_a_stale_local_origin_main(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wide      = makefile("SCAN_EXCLUDE += src  # an old exclusion the base has since dropped")
    pull      = Pull(tmp_path, {"Makefile": wide})
    stale     = git(pull.rig.repo, "rev-parse", "HEAD")
    pull.main = commit(pull.rig.repo, {"Makefile": makefile()}, "main drops the exclusion")
    git(pull.rig.repo, "push", "-q", "origin", "HEAD:main")
    git(pull.rig.repo, "update-ref", "refs/remotes/origin/main", stale)
    pull.open({"src/app.py": VULN})
    code, out = verify(pull, capsys)
    assert code == 1, out
    assert "src/app.py" in out


def test_an_exclusion_the_branch_adds_is_ignored_and_marked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path)
    pull.open({"Makefile": makefile("SCAN_EXCLUDE += src  # the branch hides its own code here"), "src/app.py": VULN})
    code, out = verify(pull, capsys)
    assert code == 1, out
    assert "policy-added" in out.splitlines()[-1]


def test_fetched_ids_unlike_githubs_are_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    pull.head = "e" * 40
    code, out = verify(pull, capsys)
    assert code == 2, out
    assert pull.rig.calls("opengrep") == []


@pytest.mark.parametrize("answer", [
    {"head": {"sha": "f" * 40}, "base": {"ref": "develop"}, "body": ""},
    {"head": {"sha": "not a commit"}, "base": {"ref": "main"}, "body": ""},
])
def test_a_base_other_than_main_or_a_malformed_answer_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    answer: dict,
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    pull.answers["repos/Needless2Say/tenant/pulls/1"] = answer
    assert verify(pull, capsys)[0] == 2


@pytest.mark.parametrize("link", [
    "https://github.com/Needless2Say/tenant/issues/1",
    "Needless2Say/tenant#1",
    "",
    "https://github.com/another-account/tenant/pull/1",
    "https://github.com/Needless2Say/../pull/1",
])
def test_a_link_that_is_not_a_pull_request_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    link: str,
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    assert verify(pull, capsys, link = link)[0] == 2


def test_a_bundle_behind_cicds_main_on_github_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    pull.answers["repos/Needless2Say/kriegerdataforge-cicd/compare"] = {"status": "behind"}
    code, out = verify(pull, capsys)
    assert code == 2 and "kdf-scan-install.sh" in out, out
    assert pull.rig.calls("opengrep") == []


def test_the_fence_holds_for_the_verify_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/more.py": "print(2)\n"})
    assert verify(pull, capsys, fence = platform(elevated = True))[0] == 2

# ======================================================================================================================
# hostile heads
# ======================================================================================================================

def test_a_replacement_ref_over_a_blob_and_a_commit_changes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull  = Pull(tmp_path)
    clean = git(pull.rig.repo, "rev-parse", "HEAD")
    head  = pull.open({"src/app.py": VULN})
    git(
        pull.rig.repo,
        "replace",
        git(pull.rig.repo, "rev-parse", f"{head}:src/app.py"),
        git(pull.rig.repo, "rev-parse", f"{clean}:src/app.py"),
    )
    git(pull.rig.repo, "replace", head, clean)
    code, out = verify(pull, capsys)
    assert code == 1, out


def hashes(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def hostile(pull: Pull, tmp_path: Path) -> Path:
    """
    Make the clone hostile, a hook that writes a marker on any ref change, the same hook through core.hooksPath, an
    alternates file, and the head's vulnerable blob stored loose under its id with clean bytes, Round Table 59's L13.
    """
    marker = tmp_path / "hook-ran"
    hook   = f"#!/bin/sh\necho ran > '{marker.as_posix()}'\n"
    hooks  = tmp_path / "hooks"
    hooks.mkdir()
    for folder in (pull.rig.repo / ".git" / "hooks", hooks):
        (folder / "reference-transaction").write_text(hook, encoding = "utf-8", newline = "\n")
        (folder / "reference-transaction").chmod(0o755)
    git(pull.rig.repo, "config", "core.hooksPath", str(hooks))
    (pull.rig.repo / ".git" / "objects" / "info").mkdir(exist_ok = True)
    (pull.rig.repo / ".git" / "objects" / "info" / "alternates").write_text(str(tmp_path / "donor"), encoding = "utf-8")
    vulnerable = git(pull.rig.repo, "rev-parse", f"{pull.head}:src/app.py")
    loose      = pull.rig.repo / ".git" / "objects" / vulnerable[:2] / vulnerable[2:]
    clean      = b"print(1)\n"
    loose.chmod(0o644)
    loose.write_bytes(zlib.compress(b"blob %d\0" % len(clean) + clean))
    return marker


def test_a_hostile_clone_is_never_read_and_nothing_in_it_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/app.py": VULN})
    marker = hostile(pull, tmp_path)
    before = hashes(pull.rig.repo / ".git")
    code, out = verify(pull, capsys)
    assert code == 1 and "src/app.py:1" in out, out
    assert not marker.exists(), "a hook of the clone ran inside the scan before a merge"
    assert hashes(pull.rig.repo / ".git") == before
    # the negative control, a fetch in that clone as the old verify made runs its hook, so the check above can fire
    git(pull.rig.repo, "fetch", "-q", "origin", f"+refs/pull/1/head:{LAUNCHER.HEAD_REF}")
    assert marker.exists()


@pytest.mark.parametrize("compare", [
    {"merge_base_commit": {"sha": "1" * 40}, "ahead_by": 1, "behind_by": 0},
    {"merge_base_commit": {"sha": "not a commit"}, "ahead_by": 1, "behind_by": 0},
    {"merge_base_commit": {}, "ahead_by": 1, "behind_by": 0},
])
def test_a_merge_base_the_fetch_cannot_reach_or_a_malformed_compare_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    compare: dict,
) -> None:
    pull = Pull(tmp_path)
    pull.open({"src/app.py": VULN})
    pull.answers["repos/Needless2Say/tenant/compare"] = compare
    code, out = verify(pull, capsys)
    assert code == 2, out
    assert pull.rig.calls("opengrep") == []


def test_a_gh_that_names_an_older_clean_head_is_refused_by_gits_own_fetch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull  = Pull(tmp_path)
    clean = pull.open({"src/more.py": "print(2)\n"})
    pull.open({"src/app.py": VULN})
    pull.head = clean
    code, out = verify(pull, capsys)
    assert code == 2 and "git's own fetch from GitHub names another head" in out, out
    assert pull.rig.calls("opengrep") == []


def test_a_symlink_and_a_gitlink_at_the_head_are_incomplete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
    code, out = verify(pull, capsys)
    assert code == 4, out


def test_a_branchs_own_ci_paths_that_always_answers_docs_only_changes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lying = "def docs_only(*args, **kwargs):\n    return True\n"
    pull  = Pull(tmp_path)
    pull.open({"ci_paths.py": lying, "scripts/common/ci_paths.py": lying, "src/app.py": VULN})
    code, out = verify(pull, capsys)
    assert code == 1, out

# ======================================================================================================================
# docs only
# ======================================================================================================================

def test_a_docs_only_pull_request_is_skipped_by_the_bundles_ci_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull = Pull(tmp_path)
    pull.open({"docs/guide.md": "# a guide\n", "NOTES.md": "notes\n"})
    code, out = verify(pull, capsys)
    assert code == 0, out
    assert "docs only" in out and out.rstrip().splitlines()[-1].endswith("DOCS-ONLY (exit 0)")
    assert pull.rig.calls("opengrep") == []


def test_a_docs_pull_request_holding_code_is_scanned(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path)
    pull.open({"docs/guide.md": "# a guide\n", "docs/tool.py": VULN})
    code, out = verify(pull, capsys)
    assert code == 1, out


def test_a_readme_that_not_docs_names_is_scanned_as_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pull = Pull(tmp_path, {"README.md": "the readme\n"})
    pull.open({"README.md": "the readme changed\n"})
    code, out = verify(pull, capsys)
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
    assert LAUNCHER.read_not_docs(text) == expected
