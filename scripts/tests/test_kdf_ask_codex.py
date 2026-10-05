"""
Tests for kdf-ask-codex.sh (D-052), the one way a session asks Codex for a read only review or a second opinion.

The tool runs as it ships, against a throwaway repo and a stand in for codex that records how it was started, the
frame it read on stdin and the folder it ran in, and plays a clean answer, a tool outside the shell, a folder it
changed or a failure. The tests need bash, node and git. GitHub's runners have all three, and a machine without them
skips the module.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "claude-code" / "kdf-ask-codex.sh"
NODE = shutil.which("node")
BASH = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")

# the flags verified on 2026-10-05, each as the tool must pass it
VERIFIED = (
    "--ignore-user-config",
    "-c windows.sandbox=unelevated",
    "--ephemeral",
    "-s read-only",
    "-m gpt-6.1-sol",
    "-c model_reasoning_effort=high",
    "-c approval_policy=never",
    "-c web_search=disabled",
    "--disable memories",
    "--disable plugins",
    "--disable apps",
    "--disable multi_agent",
    "--disable image_generation",
    "--disable goals",
    "--disable browser_use",
    "--disable computer_use",
    "--json",
)

# a stand in for codex, it records how it was started and plays what STUB_MODE says
STUB = """#!/usr/bin/env bash
printf 'args=%s\\n' "$*" >> "$STUB_LOG"
printf 'pwd=%s\\n' "$(pwd)" >> "$STUB_LOG"
printf 'head=%s\\n' "$(git rev-parse HEAD 2>/dev/null)" >> "$STUB_LOG"
cat > "$STUB_FRAME"
answer=""
while [ $# -gt 0 ]; do
    if [ "$1" = "-o" ]; then answer="$2"; shift 2; continue; fi
    shift
done
printf '{"type":"thread.started","thread_id":"t"}\\n'
printf '{"type":"item.completed","item":{"id":"1","type":"command_execution","command":"git log"}}\\n'
case "${STUB_MODE:-clean}" in
    strange) printf '{"type":"item.completed","item":{"id":"2","type":"mcp_tool_call","server":"s","tool":"t"}}\\n' ;;
    dirty) printf 'x\\n' > written.txt ;;
    fail) echo "boom" >&2; exit 3 ;;
esac
printf '{"type":"item.completed","item":{"id":"3","type":"agent_message","text":"No real problems."}}\\n'
printf '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":0,"output_tokens":20}}\\n'
printf 'No real problems.\\n' > "$answer"
"""

pytestmark = pytest.mark.skipif(
    (NODE is None or BASH is None) and not os.environ.get("CI"),
    reason = "kdf-ask-codex.sh needs bash and node",
)


@dataclass
class Rig:
    """
    A repo with two commits, a brief, a settled decisions file, an archive folder and the stand in for codex.
    """
    repo:    Path
    brief:   Path
    stub:    Path
    log:     Path
    frame:   Path
    settled: Path
    archive: Path
    tmp:     Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check = True,
        capture_output = True,
        text = True,
    ).stdout.strip()


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.txt").write_text("first\n", encoding = "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    (repo / "b.txt").write_text("second\n", encoding = "utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")
    brief = tmp_path / "brief.md"
    brief.write_text("Is there a real problem in b.txt?\n", encoding = "utf-8")
    settled = tmp_path / "SETTLED.md"
    settled.write_text("Settled line one.\n", encoding = "utf-8")
    stub = tmp_path / "stub-codex"
    stub.write_text(STUB, encoding = "utf-8", newline = "\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Rig(
        repo = repo,
        brief = brief,
        stub = stub,
        log = tmp_path / "stub.log",
        frame = tmp_path / "frame.txt",
        settled = settled,
        archive = tmp_path / "archive",
        tmp = tmp_path,
    )


def _run(
    rig: Rig,
    *args: str,
    mode: str = "clean",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the tool with exactly these arguments, the stand in playing codex in the given mode, and no role but env's.
    """
    environment = {key: value for key, value in os.environ.items() if key != "KDF_ROLE"}
    environment.update({
        "KDF_CODEX_BIN": rig.stub.as_posix(),
        "KDF_SETTLED": rig.settled.as_posix(),
        "KDF_CODEX_ARCHIVE": rig.archive.as_posix(),
        "STUB_LOG": rig.log.as_posix(),
        "STUB_FRAME": rig.frame.as_posix(),
        "STUB_MODE": mode,
        "TMPDIR": rig.tmp.as_posix(),
    })
    environment.update(env or {})
    return subprocess.run([str(BASH), str(TOOL), *args], capture_output = True, text = True, env = environment)


def _ask(
    rig: Rig,
    *extra: str,
    mode: str = "clean",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Ask about the rig's repo with the rig's brief.
    """
    return _run(rig, "--repo", rig.repo.as_posix(), "--brief", rig.brief.as_posix(), *extra, mode = mode, env = env)


def _logged(rig: Rig, key: str) -> str:
    lines = rig.log.read_text(encoding = "utf-8").splitlines()
    return next(line.split("=", 1)[1] for line in lines if line.startswith(key))


def _answers(rig: Rig) -> list[Path]:
    return sorted(path for path in rig.archive.glob("*.md") if not path.name.endswith(".frame.md"))


def _worktrees(rig: Rig) -> list[str]:
    lines = _git(rig.repo, "worktree", "list", "--porcelain").splitlines()
    return [line for line in lines if line.startswith("worktree")]

# ======================================================================================================================
# a clean run
# ======================================================================================================================

def test_a_clean_run_passes_the_verified_flags_and_archives_the_answer(rig: Rig) -> None:
    done = _ask(rig)
    assert done.returncode == 0, done.stderr
    args = _logged(rig, "args=")
    for flag in VERIFIED:
        assert f" {flag} " in f" {args} ", flag
    assert args.endswith(" -"), "the frame reaches codex on stdin"
    answers = _answers(rig)
    assert len(answers) == 1
    text = answers[0].read_text(encoding = "utf-8")
    assert text.startswith("# Codex on repo at commit ")
    assert "**Settled decisions in the frame.** yes." in text and "**Outside the shell.** none." in text
    assert "120 tokens, 1 commands" in text and text.rstrip().endswith("No real problems.")
    assert answers[0].with_suffix(".events.jsonl").is_file() and (rig.archive / f"{answers[0].stem}.frame.md").is_file()
    assert "its folder unchanged" in done.stdout


def test_codex_reads_the_commit_in_a_worktree_of_its_own_that_is_removed_after(rig: Rig) -> None:
    first = _git(rig.repo, "rev-parse", "HEAD~1")
    done  = _ask(rig, "--at", "HEAD~1")
    assert done.returncode == 0, done.stderr
    assert _logged(rig, "head=") == first
    ran_in = Path(_logged(rig, "pwd="))
    assert ran_in.name == "folder" and not ran_in.exists(), "the worktree is gone after the run"
    assert len(_worktrees(rig)) == 1, "only the repo itself is left in git's worktree list"


def test_the_frame_carries_the_question_the_conventions_and_the_settled_decisions(rig: Rig) -> None:
    first = _git(rig.repo, "rev-parse", "HEAD~1")
    assert _ask(rig, "--base", "HEAD~1").returncode == 0
    frame = rig.frame.read_text(encoding = "utf-8")
    assert "Is there a real problem in b.txt?" in frame and "PowerShell" in frame
    assert "commas and periods" in frame and "Settled line one." in frame
    assert f"git diff {first}..HEAD" in frame
    assert _ask(rig, "--no-settled").returncode == 0
    assert "Settled line one." not in rig.frame.read_text(encoding = "utf-8")
    assert "**Settled decisions in the frame.** no." in _answers(rig)[-1].read_text(encoding = "utf-8")


def test_a_base_is_read_from_its_merge_base_as_three_dots_would(rig: Rig) -> None:
    first  = _git(rig.repo, "rev-parse", "HEAD~1")
    moved  = _git(rig.repo, "commit-tree", "-p", first, "-m", "main moved on", f"{first}^{{tree}}")
    orphan = _git(rig.repo, "commit-tree", "-m", "no shared history", f"{first}^{{tree}}")
    assert _ask(rig, "--base", moved).returncode == 0
    frame = rig.frame.read_text(encoding = "utf-8")
    assert f"git diff {first}..HEAD" in frame and moved not in frame
    done = _ask(rig, "--base", orphan)
    assert done.returncode == 2 and "share no history" in done.stderr, done.stderr
    assert len(_worktrees(rig)) == 1, "the refusal leaves no worktree"


def test_a_dry_run_prints_the_frame_and_starts_nothing(rig: Rig) -> None:
    done = _ask(rig, "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "Is there a real problem in b.txt?" in done.stdout and "Codex was not started" in done.stdout
    assert not rig.log.exists() and len(_worktrees(rig)) == 1

# ======================================================================================================================
# refusals, before codex starts
# ======================================================================================================================

def test_a_session_in_the_reviewer_role_is_refused(rig: Rig) -> None:
    done = _ask(rig, env = {"KDF_ROLE": "reviewer"})
    assert done.returncode == 2 and "reviewer role" in done.stderr
    assert not rig.log.exists()


@pytest.mark.parametrize("args, says", [
    (["--brief", "BRIEF"], "give --repo or --files"),
    (["--repo", "REPO"], "--brief is required"),
    (["--repo", "REPO", "--brief", "EMPTY"], "missing or empty"),
    (["--repo", "REPO", "--brief", "BRIEF", "--at", "0123456789abcdef"], "has no commit"),
    (["--repo", "REPO", "--files", "REPO", "--brief", "BRIEF"], "give --repo or --files"),
    (["--files", "TMP", "--brief", "BRIEF", "--at", "HEAD"], "go with --repo"),
    (["--repo", "REPO", "--brief", "BRIEF", "--effort", "low"], "high or xhigh"),
    (["--repo", "REPO", "--brief", "BRIEF", "--surprise"], "unknown argument"),
])
def test_a_wrong_call_is_refused_before_codex_starts(rig: Rig, args: list[str], says: str) -> None:
    empty = rig.tmp / "empty.md"
    empty.write_text("", encoding = "utf-8")
    names = {
        "REPO": rig.repo.as_posix(),
        "BRIEF": rig.brief.as_posix(),
        "EMPTY": empty.as_posix(),
        "TMP": rig.tmp.as_posix(),
    }
    done  = _run(rig, *[names.get(arg, arg) for arg in args])
    assert done.returncode == 2 and says in done.stderr, done.stderr
    assert not rig.log.exists() and len(_worktrees(rig)) == 1

# ======================================================================================================================
# what codex did
# ======================================================================================================================

def test_a_tool_outside_the_shell_is_warned(rig: Rig) -> None:
    done = _ask(rig, mode = "strange")
    assert done.returncode == 0, done.stderr
    assert "WARNING" in done.stdout and "mcp_tool_call" in done.stdout
    assert "**Outside the shell.** mcp_tool_call." in _answers(rig)[0].read_text(encoding = "utf-8")


def test_codex_changing_its_folder_fails_the_run_and_the_worktree_still_goes(rig: Rig) -> None:
    done = _ask(rig, mode = "dirty")
    assert done.returncode == 1 and "changed its folder" in done.stderr and "written.txt" in done.stderr
    assert len(_worktrees(rig)) == 1 and not Path(_logged(rig, "pwd=")).exists()


def test_codex_failing_fails_the_run_and_keeps_what_it_was_told(rig: Rig) -> None:
    done = _ask(rig, mode = "fail")
    assert done.returncode == 1 and "codex exited 3" in done.stderr and "boom" in done.stderr
    assert list(rig.archive.glob("*.frame.md")), "the frame is archived for the next try"

# ======================================================================================================================
# files mode
# ======================================================================================================================

def test_files_mode_reads_a_throwaway_repo_of_the_files(rig: Rig) -> None:
    bundle = rig.tmp / "bundle"
    (bundle / "patches").mkdir(parents = True)
    (bundle / "patches" / "1-change.patch").write_text("diff --git a/x b/x\n", encoding = "utf-8")
    done = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix())
    assert done.returncode == 0, done.stderr
    ran_in = Path(_logged(rig, "pwd="))
    assert ran_in != bundle and len(_logged(rig, "head=")) == 40 and not ran_in.exists()
    assert "the files of bundle" in rig.frame.read_text(encoding = "utf-8")


@pytest.mark.parametrize("name, text, says", [
    (".env.kdf", "X=1\n", "named like a secret file"),
    ("keys/deploy.pem", "x\n", "named like a secret file"),
    ("notes.md", "gh" + "p_" + "A" * 36 + "\n", "token's shape"),
    (".git/HEAD", "ref: refs/heads/main\n", "is a repo"),
])
def test_files_mode_refuses_a_secret_a_token_or_a_repo(rig: Rig, name: str, text: str, says: str) -> None:
    bundle = rig.tmp / "bundle"
    (bundle / name).parent.mkdir(parents = True, exist_ok = True)
    (bundle / name).write_text(text, encoding = "utf-8")
    done = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix())
    assert done.returncode == 2 and says in done.stderr, done.stderr
    assert not rig.log.exists()


def test_help_is_the_tools_own_header() -> None:
    done = subprocess.run([str(BASH), str(TOOL), "--help"], capture_output = True, text = True)
    assert done.returncode == 0 and done.stdout.startswith("kdf-ask-codex.sh, ask Codex")
