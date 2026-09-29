"""
The KDF Code Review Process tooling, run as it ships.

`tools/claude-code/` holds the guard a Claude Code session runs before every tool call, the launcher that starts a
fresh reviewer, the wiring checker and the installer. The guard is held to `guard-cases.json`, one case per tool call
with the role it runs under and whether it must be allowed or refused, so a rule change that opens a hole fails here.
The launcher, the checker and the installer run against a throwaway repo and a throwaway home directory, with a stub in
place of claude, so the failure paths are proven too, a reviewer that edits a file, commits, or runs under a guard that
allows everything. The tests need node and bash. GitHub's runners have both, and a machine without them skips the
module.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

TOOLS     = Path(__file__).resolve().parents[2] / "tools" / "claude-code"
GUARD     = TOOLS / "kdf-guard.js"
CHECKER   = TOOLS / "check-wiring.js"
LAUNCHER  = TOOLS / "kdf-review.sh"
INSTALLER = TOOLS / "install.sh"
NODE      = shutil.which("node")
BASH      = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
CASES     = json.loads((TOOLS / "guard-cases.json").read_text(encoding = "utf-8"))

# a stand in for claude, it writes what STUB_MODE says a reviewer did, and records how it was started
STUB = """#!/usr/bin/env bash
echo "role=${KDF_ROLE:-} selfedit=${KDF_GUARD_ALLOW_SELF_EDIT:-unset}" >> "$STUB_LOG"
echo "args=$*" >> "$STUB_LOG"
echo "pwd=$(pwd)" >> "$STUB_LOG"
echo "app=$(head -n 1 src/app.py 2>/dev/null)" >> "$STUB_LOG"
echo "saw=$(ls docs/security | tr '\\n' ' ')" >> "$STUB_LOG"
report=$(printf '%s' "$2" | sed -n 's/.*write your report to \\(.*\\), edit nothing else\\./\\1/p')
case "${STUB_MODE:-clean}" in
	clean) printf '# report\\nfinding\\n' > "$report" ;;
	tamper) printf '# report\\n' > "$report"; echo "x = 2" >> src/app.py ;;
	outside) printf '# report\\n' > "$report"; echo hi > stray.txt ;;
	scratch) printf '# report\\n' > "$report"; echo notes > docs/security/scratch.md ;;
	commit) printf '# report\\n' > "$report"; git add -A; git commit -q -m sneaky ;;
	branch) printf '# report\\n' > "$report"; git checkout -q -b sneaky ;;
	delete) printf '# report\\n' > "$report"; rm src/app.py ;;
	noreport) : ;;
	fail) printf '# report\\n' > "$report"; exit 9 ;;
esac
"""

pytestmark = pytest.mark.skipif(
    (NODE is None or BASH is None) and not os.environ.get("CI"),
    reason = "node and bash are needed",
)


def _label(case: dict[str, object]) -> str:
    """
    A short readable id for one guard case.
    """
    what = str(case.get("command") or case.get("file") or "")
    return f"{case['role']}-{case['tool']}-{case['expect']}-{what[:48]}".replace(" ", "_")


def _guard_environment(project: Path, case: dict[str, object]) -> dict[str, str]:
    """
    The environment one guard case runs in, the project directory, the role when a variable sets it, and the case's own.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("KDF_")}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    if case["role"] == "reviewer" and case.get("via") == "env":
        env["KDF_ROLE"] = "reviewer"
    env.update(case.get("env", {}))  # type: ignore[arg-type]
    return env


def _run_case(project: Path, case: dict[str, object]) -> tuple[int, str]:
    """
    Feed one tool call to the guard the way Claude Code does, on stdin, and return its exit code and message.
    """
    tool_input: dict[str, str] = {}
    if "file" in case:
        tool_input["file_path"] = str(case["file"]).replace("${PROJ}", project.as_posix())
    elif "command" in case:
        tool_input["command"] = str(case["command"])
    argv = [str(NODE), str(GUARD)]
    if case["role"] == "reviewer" and case.get("via") != "env":
        argv.append("reviewer")
    payload = {"tool_name": case["tool"], "tool_input": tool_input, "cwd": str(project)}
    done    = subprocess.run(
        argv,
        input = json.dumps(payload),
        capture_output = True,
        text = True,
        env = _guard_environment(project, case),
        check = False,
    )
    return done.returncode, done.stderr


@pytest.fixture(scope = "module")
def guard_results(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[int, str]]:
    """
    Every guard case run once, in parallel, so the per case tests only read an answer.
    """
    project = tmp_path_factory.mktemp("kdf-project")
    with ThreadPoolExecutor(max_workers = 8) as pool:
        return list(pool.map(lambda case: _run_case(project, case), CASES))


@pytest.mark.parametrize("index", range(len(CASES)), ids = [_label(case) for case in CASES])
def test_the_guard_decides_each_case(index: int, guard_results: list[tuple[int, str]]) -> None:
    """
    A refused call exits 2 with the reason, an allowed call exits 0.
    """
    case = CASES[index]
    code, message = guard_results[index]
    want = 2 if case["expect"] == "block" else 0
    assert code == want, f"{_label(case)} exited {code}, wanted {want}. {message.strip()}"
    if want == 2:
        assert "refused this call" in message


def test_the_cases_cover_both_roles_and_both_outcomes() -> None:
    """
    The table is a real one, both roles, both outcomes, and every case says what it expects.
    """
    assert len(CASES) > 250
    assert {case["role"] for case in CASES} == {"owner", "reviewer"}
    assert {case["expect"] for case in CASES} == {"allow", "block"}
    for role in ("owner", "reviewer"):
        for expect in ("allow", "block"):
            assert sum(1 for case in CASES if case["role"] == role and case["expect"] == expect) >= 20
    assert any(case.get("via") == "env" for case in CASES)


def test_a_crash_never_blocks(tmp_path: Path) -> None:
    """
    Input the guard cannot read exits 1, a non blocking error to Claude Code, and never 2.
    """
    done = subprocess.run(
        [str(NODE), str(GUARD)],
        input = "not json",
        capture_output = True,
        text = True,
        check = False,
    )
    assert done.returncode == 1


def test_a_refusal_is_logged_when_asked(tmp_path: Path) -> None:
    """
    KDF_GUARD_LOG appends one line per refusal, and an allowed call adds none.
    """
    log = tmp_path / "guard.log"
    env = {**os.environ, "KDF_GUARD_LOG": str(log), "CLAUDE_PROJECT_DIR": str(tmp_path)}
    for command in ("git push origin main", "git status"):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
        subprocess.run(
            [str(NODE), str(GUARD)],
            input = json.dumps(payload),
            env = env,
            capture_output = True,
            text = True,
            check = False,
        )
    lines = log.read_text(encoding = "utf-8").splitlines()
    assert len(lines) == 1
    assert "git push origin main" in lines[0]


def test_the_tools_keep_lf_line_ends_on_every_machine() -> None:
    """
    A carriage return breaks a shell script, so .gitattributes pins the tooling to LF.
    """
    text = (TOOLS.parents[1] / ".gitattributes").read_text(encoding = "utf-8")
    for pattern in ("*.sh", "*.js", "*.json"):
        assert f"tools/claude-code/{pattern}" in text


@dataclass
class Rig:
    """
    A throwaway repo, a throwaway home with the guard wired, and the stub that stands in for claude.
    """
    repo: Path
    home: Path
    stub: Path
    log: Path
    tmp: Path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check = True, capture_output = True, text = True)


def _printed_settings(home: Path) -> dict[str, object]:
    """
    The settings block the checker prints for a home directory, parsed.
    """
    done = subprocess.run(
        [str(NODE), str(CHECKER), "--home", str(home), "--print"],
        capture_output = True,
        text = True,
        check = True,
    )
    return json.loads(done.stdout[done.stdout.index("\n{") + 1 :])


def _write_settings(home: Path, settings: object) -> None:
    (home / ".claude" / "settings.json").write_text(json.dumps(settings), encoding = "utf-8")


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    """
    A repo with one commit and a brief, a home whose settings are exactly what the checker prints, and the stub.
    """
    home = tmp_path / "home"
    (home / ".claude" / "hooks").mkdir(parents = True)
    shutil.copy(GUARD, home / ".claude" / "hooks" / "kdf-guard.js")
    _write_settings(home, _printed_settings(home))

    repo = tmp_path / "repo"
    (repo / "docs" / "security").mkdir(parents = True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding = "utf-8")
    (repo / "docs" / "security" / "BRIEF.md").write_text("# brief\n", encoding = "utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")

    stub = tmp_path / "stub-claude"
    stub.write_text(STUB, encoding = "utf-8", newline = "\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return Rig(repo = repo, home = home, stub = stub, log = tmp_path / "stub.log", tmp = tmp_path)


def _run(
    rig: Rig,
    *args: str,
    mode: str = "clean",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the launcher with exactly these arguments, the stub playing the reviewer in the given mode.
    """
    environment = {
        **os.environ,
        "KDF_HOME": rig.home.as_posix(),
        "KDF_CLAUDE_BIN": rig.stub.as_posix(),
        "STUB_LOG": rig.log.as_posix(),
        "STUB_MODE": mode,
        "TMPDIR": rig.tmp.as_posix(),
        **(env or {}),
    }
    return subprocess.run(
        [str(BASH), str(LAUNCHER), *args],
        capture_output = True,
        text = True,
        env = environment,
        check = False,
    )


def _launch(
    rig: Rig,
    *extra: str,
    mode: str = "clean",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run the launcher against the rig's brief and report, the stub playing the reviewer in the given mode.
    """
    return _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        "docs/security/BRIEF.md",
        "--report",
        "docs/security/REPORT.md",
        *extra,
        mode = mode,
        env = env,
    )


def test_a_clean_review_is_reported_clean(rig: Rig) -> None:
    """
    The stub writes its report and nothing else, the launcher says clean and hands over the Codex line.
    """
    done = _launch(rig, "--codex-report", "docs/security/CODEX.md")
    assert done.returncode == 0, done.stderr
    assert "clean" in done.stdout
    assert "write your report to docs/security/CODEX.md, edit nothing else." in done.stdout
    assert (rig.repo / "docs" / "security" / "REPORT.md").is_file()


def test_the_reviewer_starts_with_the_role_and_without_the_owners_switch(rig: Rig) -> None:
    """
    The role is set for the reviewer, and the owner's self edit switch is stripped even when the owner has it set.
    """
    done = _launch(rig, env = {"KDF_GUARD_ALLOW_SELF_EDIT": "1"})
    assert done.returncode == 0, done.stderr
    assert "role=reviewer selfedit=unset" in rig.log.read_text(encoding = "utf-8")


def test_the_model_and_the_effort_reach_claude(rig: Rig) -> None:
    """
    The flags the owner picks are passed through as given.
    """
    assert _launch(rig, "--model", "opus", "--effort", "max").returncode == 0
    assert "--model opus --effort max" in rig.log.read_text(encoding = "utf-8")


def test_new_files_under_docs_security_are_allowed(rig: Rig) -> None:
    """
    A reviewer's scratch note beside its report is inside the rule, a new file under docs/security.
    """
    assert _launch(rig, mode = "scratch").returncode == 0


@pytest.mark.parametrize(
    ("mode", "named"),
    [
        ("tamper", "src/app.py"),
        ("outside", "stray.txt"),
        ("delete", "src/app.py"),
        ("commit", "git state changed"),
        ("branch", "git state changed"),
    ],
)
def test_a_reviewer_that_changes_anything_else_is_contamination(rig: Rig, mode: str, named: str) -> None:
    """
    An edit, a stray file, a deletion, a commit or a new branch fails the run with exit 3 and names what changed.
    """
    done = _launch(rig, mode = mode)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "CONTAMINATION" in done.stderr
    assert named in done.stderr


def test_a_missing_report_and_a_failing_claude_are_told_apart(rig: Rig) -> None:
    """
    No report is exit 4, and claude exiting non zero is exit 6.
    """
    assert _launch(rig, mode = "noreport").returncode == 4
    (rig.repo / "docs" / "security" / "REPORT.md").unlink(missing_ok = True)
    assert _launch(rig, mode = "fail").returncode == 6


def test_the_arguments_are_checked_before_anything_runs(rig: Rig) -> None:
    """
    A report outside docs/security, one that exists, a missing brief and a repo that is not a root are all exit 2.
    """
    base = [str(BASH), str(LAUNCHER), "--repo", rig.repo.as_posix()]
    env  = {
        **os.environ,
        "KDF_HOME": rig.home.as_posix(),
        "KDF_CLAUDE_BIN": rig.stub.as_posix(),
        "STUB_LOG": rig.log.as_posix(),
    }


    def run(*args: str) -> int:
        return subprocess.run([*base, *args], capture_output = True, text = True, env = env, check = False).returncode


    assert run("--brief", "docs/security/BRIEF.md", "--report", "src/REPORT.md") == 2
    assert run("--brief", "docs/security/BRIEF.md", "--report", "docs/security/../../REPORT.md") == 2
    assert run("--brief", "docs/security/NOPE.md", "--report", "docs/security/REPORT.md") == 2
    assert run("--brief", "docs/security/BRIEF.md", "--report", "docs/security/BRIEF.md") == 2
    assert run("--brief", "docs/security/BRIEF.md") == 2
    assert not rig.log.exists()
    not_a_root = (rig.repo / "src").as_posix()
    sub        = subprocess.run(
        [str(BASH), str(LAUNCHER), "--repo", not_a_root, "--brief", "x", "--report", "docs/security/R.md"],
        capture_output = True,
        text = True,
        env = env,
        check = False,
    )
    assert sub.returncode == 2


def test_a_dry_run_prints_both_prompts_and_starts_nothing(rig: Rig) -> None:
    """
    The same one line goes to Claude and to Codex, and claude is never run.
    """
    done = _launch(rig, "--codex-report", "docs/security/CODEX.md", "--dry-run")
    assert done.returncode == 0
    assert "Claude prompt, Read docs/security/BRIEF.md and run the review," in done.stdout
    assert "write your report to docs/security/REPORT.md, edit nothing else." in done.stdout
    assert "Codex prompt," in done.stdout
    assert not rig.log.exists()


def test_nothing_starts_without_a_wired_guard(rig: Rig) -> None:
    """
    No installed guard, settings without the hook, and a hook that no longer matches the tools are all exit 5.
    """
    settings = json.loads((rig.home / ".claude" / "settings.json").read_text(encoding = "utf-8"))
    _write_settings(rig.home, {})
    assert _launch(rig).returncode == 5
    settings["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
    _write_settings(rig.home, settings)
    assert _launch(rig).returncode == 5
    (rig.home / ".claude" / "hooks" / "kdf-guard.js").unlink()
    _write_settings(rig.home, _printed_settings(rig.home))
    assert _launch(rig).returncode == 5
    assert not rig.log.exists()


def test_a_guard_that_allows_everything_is_caught_by_the_canary(rig: Rig) -> None:
    """
    An installed copy that always exits 0 passes the wiring check, so the launcher's canary calls must catch it.
    """
    (rig.home / ".claude" / "hooks" / "kdf-guard.js").write_text("process.exit(0);\n", encoding = "utf-8")
    done = _launch(rig)
    assert done.returncode == 5
    assert "canary" in done.stderr
    assert not rig.log.exists()


def _copies(rig: Rig) -> list[str]:
    """
    What is left in the folder beside the repo where the launcher keeps its copies.
    """
    folder = rig.tmp / ".kdf-review"
    return sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []


def _prepare(rig: Rig, report: str, *extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """
    Prepare a copy at HEAD for a reviewer the owner starts by hand, and return the run and the copy.
    """
    done   = _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        "docs/security/BRIEF.md",
        "--report",
        report,
        "--at",
        "HEAD",
        "--prepare",
        *extra,
    )
    copies = [entry for entry in (rig.tmp / ".kdf-review").iterdir() if not entry.name.endswith(".kdf-pin")]
    return done, copies[0]


def _collect(rig: Rig, report: str, copy: Path) -> subprocess.CompletedProcess[str]:
    return _run(rig, "--repo", rig.repo.as_posix(), "--report", report, "--collect", copy.as_posix())


def test_a_pinned_review_runs_in_a_copy_of_its_own_and_brings_the_report_home(rig: Rig) -> None:
    """
    With --at the reviewer works in a worktree at the commit, its report lands in the repo and the copy is removed.
    """
    done = _launch(rig, "--at", "HEAD")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (rig.repo / "docs" / "security" / "REPORT.md").is_file()
    log = rig.log.read_text(encoding = "utf-8")
    assert ".kdf-review" in log.split("pwd=")[1].splitlines()[0]
    assert "role=reviewer" in log
    assert _copies(rig) == []


def test_a_pinned_copy_reads_the_commit_and_not_the_moving_tree(rig: Rig) -> None:
    """
    What the orchestrator changed and did not commit is not in the reviewer's copy, and stays in the repo.
    """
    (rig.repo / "src" / "app.py").write_text("x = 99\n", encoding = "utf-8")
    assert _launch(rig, "--at", "HEAD").returncode == 0
    assert "app=x = 1" in rig.log.read_text(encoding = "utf-8")
    assert (rig.repo / "src" / "app.py").read_text(encoding = "utf-8") == "x = 99\n"


@pytest.mark.parametrize(
    ("mode", "named"),
    [
        ("tamper", "src/app.py"),
        ("outside", "stray.txt"),
        ("commit", "git state changed"),
        ("branch", "git state changed"),
    ],
)
def test_a_pinned_reviewer_that_changes_anything_else_is_caught_and_its_copy_kept(
    rig: Rig,
    mode: str,
    named: str,
) -> None:
    """
    An edit, a stray file, a commit or a branch in the copy is exit 3, nothing reaches the repo, the copy stays.
    """
    done = _launch(rig, "--at", "HEAD", mode = mode)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "CONTAMINATION" in done.stderr
    assert named in done.stderr
    assert not (rig.repo / "docs" / "security" / "REPORT.md").exists()
    assert (rig.repo / "src" / "app.py").read_text(encoding = "utf-8") == "x = 1\n"
    assert len(_copies(rig)) == 2


def test_a_pinned_run_without_a_report_or_with_a_failing_claude_keeps_its_copy(rig: Rig) -> None:
    """
    No report is exit 4 and a failing claude exit 6, and either way the copy is left for a look.
    """
    assert _launch(rig, "--at", "HEAD", mode = "noreport").returncode == 4
    assert len(_copies(rig)) == 2
    (rig.repo / "docs" / "security" / "OTHER.md").write_text("# brief two\n", encoding = "utf-8")
    _git(rig.repo, "add", "docs/security/OTHER.md")
    _git(rig.repo, "commit", "-q", "-m", "second brief")
    failed = _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        "docs/security/OTHER.md",
        "--report",
        "docs/security/OTHER_REPORT.md",
        "--at",
        "HEAD",
        mode = "fail",
    )
    assert failed.returncode == 6
    assert len(_copies(rig)) == 4


def test_a_reviewer_started_by_hand_gets_a_copy_and_its_report_is_collected(rig: Rig) -> None:
    """
    --prepare makes the copy and prints the one line and the collect command, claude is not run, collect brings it home.
    """
    done, copy = _prepare(rig, "docs/security/CODEX.md")
    assert done.returncode == 0, done.stderr
    assert "Read docs/security/BRIEF.md and run the review, write your report to docs/security/CODEX.md" in done.stdout
    assert "--collect" in done.stdout
    assert not rig.log.exists()
    (copy / "docs" / "security" / "CODEX.md").write_text("# codex report\n", encoding = "utf-8")
    collected = _collect(rig, "docs/security/CODEX.md", copy)
    assert collected.returncode == 0, collected.stderr
    assert (rig.repo / "docs" / "security" / "CODEX.md").read_text(encoding = "utf-8") == "# codex report\n"
    assert _copies(rig) == []


@pytest.mark.parametrize("extra", ["code", "stray", "commit"])
def test_collect_refuses_a_copy_where_the_reviewer_did_more_than_report(rig: Rig, extra: str) -> None:
    """
    A reviewer outside Claude Code has no guard, so collect is its check. Anything but the report is exit 3.
    """
    _, copy = _prepare(rig, "docs/security/CODEX.md")
    (copy / "docs" / "security" / "CODEX.md").write_text("# report\n", encoding = "utf-8")
    if extra == "code":
        (copy / "src" / "app.py").write_text("x = 2\n", encoding = "utf-8")
    elif extra == "stray":
        (copy / "stray.txt").write_text("hi\n", encoding = "utf-8")
    else:
        _git(copy, "add", "-A")
        _git(copy, "commit", "-q", "-m", "sneaky")
    collected = _collect(rig, "docs/security/CODEX.md", copy)
    assert collected.returncode == 3, collected.stdout + collected.stderr
    assert not (rig.repo / "docs" / "security" / "CODEX.md").exists()
    assert copy.is_dir()


def test_collect_needs_the_report_and_never_overwrites(rig: Rig) -> None:
    """
    No report is exit 4. A file the repo already has is exit 2 and nothing is copied.
    """
    _, copy = _prepare(rig, "docs/security/CODEX.md")
    assert _collect(rig, "docs/security/CODEX.md", copy).returncode == 4
    (copy / "docs" / "security" / "CODEX.md").write_text("# report\n", encoding = "utf-8")
    (copy / "docs" / "security" / "notes.md").write_text("theirs\n", encoding = "utf-8")
    (rig.repo / "docs" / "security" / "notes.md").write_text("mine\n", encoding = "utf-8")
    assert _collect(rig, "docs/security/CODEX.md", copy).returncode == 2
    assert (rig.repo / "docs" / "security" / "notes.md").read_text(encoding = "utf-8") == "mine\n"
    assert not (rig.repo / "docs" / "security" / "CODEX.md").exists()


def test_a_second_reviewer_never_sees_the_first_report(rig: Rig) -> None:
    """
    Claude's report is in the repo once collected, but Codex's copy at the same commit does not hold it.
    """
    assert _launch(rig, "--at", "HEAD").returncode == 0
    done, copy = _prepare(rig, "docs/security/CODEX.md")
    assert done.returncode == 0, done.stderr
    assert (rig.repo / "docs" / "security" / "REPORT.md").is_file()
    assert not (copy / "docs" / "security" / "REPORT.md").exists()


def test_the_setup_runs_in_the_copy_and_is_not_held_against_the_reviewer(rig: Rig) -> None:
    """
    The setup command runs in the copy with KDF_MAIN_REPO set, and what it leaves is part of the starting point.
    """
    done, copy = _prepare(rig, "docs/security/CODEX.md", "--setup", 'printf "%s" "$KDF_MAIN_REPO" > setup-ran.txt')
    assert done.returncode == 0, done.stderr
    assert (copy / "setup-ran.txt").read_text(encoding = "utf-8").endswith("repo")
    (copy / "docs" / "security" / "CODEX.md").write_text("# report\n", encoding = "utf-8")
    assert _collect(rig, "docs/security/CODEX.md", copy).returncode == 0


def test_a_failing_setup_removes_its_copy(rig: Rig) -> None:
    """
    A setup that fails is exit 7, the copy is removed and claude never runs.
    """
    done = _launch(rig, "--at", "HEAD", "--setup", "exit 3")
    assert done.returncode == 7, done.stdout + done.stderr
    assert _copies(rig) == []
    assert not rig.log.exists()


def test_a_pinned_dry_run_names_the_copy_and_makes_nothing(rig: Rig) -> None:
    """
    The dry run prints where the copy would go, and makes no copy.
    """
    done = _launch(rig, "--at", "HEAD", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "Copy, " in done.stdout
    assert ".kdf-review" in done.stdout
    assert _copies(rig) == []


def test_the_pinned_arguments_are_checked_before_anything_runs(rig: Rig) -> None:
    """
    A commit that is not one, a brief the commit lacks, --prepare or --setup without --at, and a collect of a folder
    the launcher did not make are all exit 2.
    """
    base = ["--repo", rig.repo.as_posix(), "--brief", "docs/security/BRIEF.md", "--report", "docs/security/R.md"]
    assert _run(rig, *base, "--at", "no-such-commit").returncode == 2
    assert _run(rig, *base, "--prepare").returncode == 2
    assert _run(rig, *base, "--setup", "true").returncode == 2
    (rig.repo / "docs" / "security" / "NEW.md").write_text("# not committed\n", encoding = "utf-8")
    uncommitted = ["--repo", rig.repo.as_posix(), "--brief", "docs/security/NEW.md", "--report", "docs/security/R.md"]
    assert _run(rig, *uncommitted, "--at", "HEAD").returncode == 2
    collect = ["--repo", rig.repo.as_posix(), "--report", "docs/security/R.md", "--collect", rig.tmp.as_posix()]
    assert _run(rig, *collect).returncode == 2
    assert _run(rig, *collect, "--at", "HEAD").returncode == 2
    assert not rig.log.exists()
    assert _copies(rig) == []


def _checker(home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NODE), str(CHECKER), "--home", str(home)],
        capture_output = True,
        text = True,
        check = False,
    )


def test_the_printed_settings_pass_the_checker(rig: Rig) -> None:
    """
    What the checker tells the owner to add is what it accepts.
    """
    done = _checker(rig.home)
    assert done.returncode == 0, done.stdout
    assert "All checks passed." in done.stdout


def _without_shell(settings: dict) -> None:
    del settings["defaultShell"]


def _without_powershell_deny(settings: dict) -> None:
    settings["permissions"]["deny"].remove("PowerShell")


def _narrow_matcher(settings: dict) -> None:
    settings["hooks"]["PreToolUse"][0]["matcher"] = "Bash|PowerShell"


def _without_hook(settings: dict) -> None:
    settings["hooks"] = {}


def _hooks_off(settings: dict) -> None:
    settings["disableAllHooks"] = True


def _hook_points_nowhere(settings: dict) -> None:
    settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = 'node "/nowhere/kdf-guard.js"'


@pytest.mark.parametrize(
    ("mutate", "says"),
    [
        (_without_shell, "defaultShell"),
        (_without_powershell_deny, "PowerShell tool is not denied"),
        (_narrow_matcher, "matcher misses"),
        (_without_hook, "no PreToolUse hook"),
        (_hooks_off, "hooks are switched off"),
        (_hook_points_nowhere, "does not exist"),
    ],
)
def test_the_checker_fails_each_missing_piece(rig: Rig, mutate, says: str) -> None:  # noqa: ANN001
    """
    Each requirement is checked on its own, so breaking one fails the check and names it.
    """
    settings = json.loads((rig.home / ".claude" / "settings.json").read_text(encoding = "utf-8"))
    mutate(settings)
    _write_settings(rig.home, settings)
    done = _checker(rig.home)
    assert done.returncode == 1
    assert says in done.stdout


def test_the_checker_fails_on_broken_json_and_warns_on_secret_reads(rig: Rig) -> None:
    """
    A settings file that is not JSON fails. Missing secret read denies only warn, the guard still covers the shell.
    """
    settings = json.loads((rig.home / ".claude" / "settings.json").read_text(encoding = "utf-8"))
    settings["permissions"]["deny"] = ["PowerShell"]
    _write_settings(rig.home, settings)
    warned = _checker(rig.home)
    assert warned.returncode == 0
    assert "WARN" in warned.stdout
    (rig.home / ".claude" / "settings.json").write_text("{ nope", encoding = "utf-8")
    assert _checker(rig.home).returncode == 1


def test_the_installer_installs_and_smoke_tests_the_guard(tmp_path: Path) -> None:
    """
    It copies the guard, proves it refuses and allows, and prints the block for the owner to add. It edits no settings.
    """
    home = tmp_path / "home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if key != "CLAUDECODE"}
    env["KDF_HOME"] = home.as_posix()
    done = subprocess.run([str(BASH), str(INSTALLER)], capture_output = True, text = True, env = env, check = False)
    assert done.returncode == 0, done.stderr
    assert "Smoke test passed" in done.stdout
    assert (home / ".claude" / "hooks" / "kdf-guard.js").read_bytes() == GUARD.read_bytes()
    assert '"defaultShell": "bash"' in done.stdout
    assert not (home / ".claude" / "settings.json").exists()
    checked = subprocess.run(
        [str(BASH), str(INSTALLER), "--check"],
        capture_output = True,
        text = True,
        env = env,
        check = False,
    )
    assert checked.returncode == 1


def test_the_installer_refuses_to_run_inside_a_session(tmp_path: Path) -> None:
    """
    A session does not install or change its own guardrails, Claude Code sets CLAUDECODE in the shells it starts.
    """
    env  = {**os.environ, "CLAUDECODE": "1", "KDF_HOME": tmp_path.as_posix()}
    done = subprocess.run([str(BASH), str(INSTALLER)], capture_output = True, text = True, env = env, check = False)
    assert done.returncode == 1
    assert "does not install its own guardrails" in done.stderr
    assert not (tmp_path / ".claude").exists()
