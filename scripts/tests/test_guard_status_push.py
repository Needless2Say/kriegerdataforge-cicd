"""
Tests for D-046, the one push to main a session makes.

The owner keeps the live status of the work in STATUS.md of kriegerdataforge-context and has sessions commit it
straight to main. The guard allows a plain `git push origin main` there when every commit the push carries changes
STATUS.md alone, and refuses everything else as before. Each case builds a real clone of a bare repo whose path ends in
`Needless2Say/kriegerdataforge-context.git`, commits, and feeds the guard the push the way Claude Code does. A control
runs every refusal against a copy of the guard whose exception lets every push through, so each refusal is shown to
fail on purpose when the guard allows it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "claude-code"
GUARD = TOOLS / "kdf-guard.js"
NODE  = shutil.which("node")
GIT   = shutil.which("git")

CONTEXT = "Needless2Say/kriegerdataforge-context.git"
PUSH    = "git push origin main"

# The two lines the control copy of the guard rewrites, so its exception lets every push through.
SHAPE_LINE = "  if (MODE !== 'reviewer' && dir && rest.length === 2 && rest[0] === 'origin' && rest[1] === 'main') {"
VERDICT_FN = "function statusPush(dir) {"

# Each push the guard refuses, by name, the test ids. _refusal builds the repo and the call for each.
REFUSALS = (
    "another file in a commit",
    "a file added then removed",
    "a commit of another file alone",
    "an empty commit",
    "a merge commit",
    "another repo",
    "a lookalike owner",
    "no remote",
    "a push URL elsewhere",
    "HEAD on another branch",
    "a detached HEAD",
    "force",
    "force with lease",
    "a HEAD refspec",
    "an explicit refspec",
    "another branch name",
    "another remote name",
    "a cd before it",
    "a pipe after it",
    "an env prefix",
    "a git setting",
    "a nested shell",
    "find execdir",
    "a GIT_DIR in the environment",
)

# Remote URLs, and whether each names kriegerdataforge-context in a form a push to main may use.
CONTEXT_URLS = {
    "https://github.com/Needless2Say/kriegerdataforge-context.git": True,
    "https://github.com/needless2say/kriegerdataforge-context": True,
    "https://x-access-token:secret@github.com/Needless2Say/kriegerdataforge-context.git": True,
    "git@github.com:Needless2Say/kriegerdataforge-context.git": True,
    "ssh://git@github.com/Needless2Say/kriegerdataforge-context.git": True,
    "C:\\remotes\\Needless2Say\\kriegerdataforge-context.git": True,
    "/srv/git/Needless2Say/kriegerdataforge-context.git": True,
    "file:///srv/git/Needless2Say/kriegerdataforge-context.git": True,
    "https://github.com/Needless2Say/kriegerdataforge-cicd.git": False,
    "https://github.com/Needless2Say/kriegerdataforge-context-copy.git": False,
    "https://github.com/evil/Needless2Say/kriegerdataforge-context.git": False,
    "https://evil.example.com/Needless2Say/kriegerdataforge-context.git": False,
    "http://github.com/Needless2Say/kriegerdataforge-context.git": False,
    "git@evil.example.com:Needless2Say/kriegerdataforge-context.git": False,
    "file://host/Needless2Say/kriegerdataforge-context.git": False,
    "/srv/git/Someone/kriegerdataforge-context.git": False,
    "": False,
}

pytestmark = pytest.mark.skipif(
    (NODE is None or GIT is None) and not os.environ.get("CI"),
    reason = "node and git are needed",
)


def _git(cwd: Path, *args: str) -> str:
    """
    Run git in a test repo with a fixed identity and no signing, whatever the machine's own settings say.
    """
    done = subprocess.run(
        [
            "git", "-C", str(cwd), "-c", "user.name=kdf-test", "-c", "user.email=kdf-test@example.com",
            "-c", "commit.gpgsign=false", *args,
        ],
        capture_output = True,
        text = True,
        check = True,
        env = _clean_environment(),
    )
    return done.stdout.strip()


def _clean_environment() -> dict[str, str]:
    """
    The caller's environment without the git and guard variables a developer's shell may carry.
    """
    return {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "KDF_"))}


def _commit(work: Path, files: dict[str, str | None], message: str = "status") -> None:
    """
    Write each file, or delete it when its text is None, and commit everything.
    """
    for name, text in files.items():
        target = work / name
        if text is None:
            target.unlink()
        else:
            target.write_text(text, encoding = "utf-8", newline = "\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "--allow-empty", "-m", message)


def _bare(tmp_path: Path, name: str) -> Path:
    """
    A bare repo at <tmp>/remotes/<name>.
    """
    remote = tmp_path / "remotes" / name
    remote.mkdir(parents = True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check = True, capture_output = True)
    return remote


def _clone(tmp_path: Path, name: str = CONTEXT) -> Path:
    """
    A working repo on main whose origin is a bare repo named <name>, with a README and a STATUS.md already pushed.
    """
    remote = _bare(tmp_path, name)
    work   = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check = True, capture_output = True)
    _git(work, "remote", "add", "origin", str(remote))
    _commit(work, {"README.md": "context\n", "STATUS.md": "# Status\n"}, "start")
    _git(work, "push", "-q", "origin", "main")
    return work


def _guard(
    cwd: Path,
    command: str,
    role: str = "owner",
    env: dict[str, str] | None = None,
    guard: Path = GUARD,
) -> tuple[int, str]:
    """
    Feed one Bash call to the guard on stdin, the way Claude Code does, and return its exit code and message.
    """
    argv        = [str(NODE), str(guard)] + (["reviewer"] if role == "reviewer" else [])
    environment = {**_clean_environment(), "CLAUDE_PROJECT_DIR": str(cwd), **(env or {})}
    payload     = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    done        = subprocess.run(
        argv,
        input = json.dumps(payload),
        capture_output = True,
        text = True,
        env = environment,
        check = False,
    )
    return done.returncode, done.stderr

# ======================================================================================================================
# The push that goes through
# ======================================================================================================================

def test_a_commit_of_status_alone_goes_straight_to_main(tmp_path: Path) -> None:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nThe SDK review waits for Wednesday.\n"})
    _commit(work, {"STATUS.md": "# Status\n\nS2 starts on Wednesday.\n"})
    code, message = _guard(work, PUSH)
    assert code == 0, message


def test_git_C_from_another_folder_is_judged_by_the_repo_it_names(tmp_path: Path) -> None:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nupdated\n"})
    code, message = _guard(tmp_path, f"git -C {work.as_posix()} push origin main")
    assert code == 0, message


def test_a_push_with_nothing_new_is_allowed(tmp_path: Path) -> None:
    work = _clone(tmp_path)
    code, message = _guard(work, PUSH)
    assert code == 0, message

# ======================================================================================================================
# The refusals, each a setup and the call it refuses
# ======================================================================================================================

def _another_file(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n", "notes.md": "a note\n"})
    return work, PUSH, {}


def _added_then_removed(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\na\n", "carry.txt": "carried\n"})
    _commit(work, {"STATUS.md": "# Status\n\nb\n", "carry.txt": None})
    return work, PUSH, {}


def _another_file_alone(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"README.md": "changed\n"})
    _commit(work, {"STATUS.md": "# Status\n\nafter\n"})
    return work, PUSH, {}


def _an_empty_commit(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {})
    return work, PUSH, {}


def _a_merge(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _git(work, "checkout", "-q", "-b", "side")
    _commit(work, {"STATUS.md": "# Status\n\nside\n"})
    _git(work, "checkout", "-q", "main")
    _git(work, "merge", "-q", "--no-ff", "-m", "merge", "side")
    return work, PUSH, {}


def _another_repo(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path, "Needless2Say/kriegerdataforge-cicd.git")
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    return work, PUSH, {}


def _a_lookalike_repo(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path, "Someone/kriegerdataforge-context.git")
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    return work, PUSH, {}


def _no_remote(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    _git(work, "remote", "remove", "origin")
    return work, PUSH, {}


def _a_push_url_elsewhere(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work  = _clone(tmp_path)
    other = _bare(tmp_path, "tok3n-holder/elsewhere.git")
    _git(work, "config", "remote.origin.pushurl", str(other))
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    return work, PUSH, {}


def _head_on_another_branch(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    _git(work, "checkout", "-q", "-b", "feature/status")
    return work, PUSH, {}


def _a_detached_head(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    _git(work, "checkout", "-q", "--detach")
    return work, PUSH, {}


def _status_commit(tmp_path: Path, command: str, env: dict[str, str] | None = None) -> tuple[Path, str, dict[str, str]]:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    return work, command.replace("{work}", work.as_posix()), env or {}


def _refusal(name: str, tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    """
    The repo, the call and the environment of one refused push, named as in REFUSALS.
    """
    commands = {
        "force": "git push --force origin main",
        "force with lease": "git push --force-with-lease origin main",
        "a HEAD refspec": "git push origin HEAD",
        "an explicit refspec": "git push origin main:main",
        "another branch name": "git push origin master",
        "another remote name": "git push upstream main",
        "a cd before it": "cd {work} && git push origin main",
        "a pipe after it": "git push origin main 2>&1 | tail -1",
        "an env prefix": "env git push origin main",
        "a git setting": "git -c push.default=current push origin main",
        "a nested shell": "bash -c 'git push origin main'",
        "find execdir": "find {work} -maxdepth 0 -execdir git push origin main \\;",
    }
    if name in commands:
        return _status_commit(tmp_path, commands[name])
    if name == "a GIT_DIR in the environment":
        return _status_commit(tmp_path, PUSH, {"GIT_DIR": "elsewhere/.git"})
    builders = {
        "another file in a commit": _another_file,
        "a file added then removed": _added_then_removed,
        "a commit of another file alone": _another_file_alone,
        "an empty commit": _an_empty_commit,
        "a merge commit": _a_merge,
        "another repo": _another_repo,
        "a lookalike owner": _a_lookalike_repo,
        "no remote": _no_remote,
        "a push URL elsewhere": _a_push_url_elsewhere,
        "HEAD on another branch": _head_on_another_branch,
        "a detached HEAD": _a_detached_head,
    }
    return builders[name](tmp_path)


@pytest.mark.parametrize("name", REFUSALS)
def test_every_other_push_to_main_is_refused(tmp_path: Path, name: str) -> None:
    work, command, env = _refusal(name, tmp_path)
    code, message = _guard(work, command, env = env)
    assert code == 2, f"{name} exited {code}. {message.strip()}"
    assert "refused this call" in message
    assert "tok3n" not in message


def test_a_reviewer_pushes_nothing_even_status(tmp_path: Path) -> None:
    work = _clone(tmp_path)
    _commit(work, {"STATUS.md": "# Status\n\nx\n"})
    code, message = _guard(work, PUSH, role = "reviewer")
    assert code == 2
    assert "Reviewers get read only git" in message


def test_a_refusal_in_the_context_repo_says_why(tmp_path: Path) -> None:
    work, command, env = _another_file(tmp_path)
    code, message = _guard(work, command, env = env)
    assert code == 2
    assert "Only commits that change STATUS.md alone go straight to main of kriegerdataforge-context." in message
    assert "changes more than STATUS.md" in message


def test_another_repo_keeps_the_old_refusal(tmp_path: Path) -> None:
    work, command, env = _another_repo(tmp_path)
    code, message = _guard(work, command, env = env)
    assert code == 2
    assert "Nothing is pushed to main. Push a branch and open a pull request" in message


def test_the_context_remote_is_known_in_every_form_and_no_lookalike_passes() -> None:
    """
    The guard's own contextRemote, run in node on github.com, ssh, scp, file and disk forms, and on lookalikes.
    """
    text   = GUARD.read_text(encoding = "utf-8")
    start  = text.index("function contextRemote(url) {")
    body   = text[start:text.index("\n}\n", start) + 3]
    names  = ("const CONTEXT_ON_GITHUB", "const CONTEXT_ON_DISK")
    consts = [line for line in text.splitlines() if line.startswith(names)]
    probe  = f"console.log(JSON.stringify({json.dumps(list(CONTEXT_URLS))}.map(contextRemote)));"
    script = "\n".join([*consts, body, probe])
    done   = subprocess.run([str(NODE), "-e", script], capture_output = True, text = True, check = True)
    assert dict(zip(CONTEXT_URLS, json.loads(done.stdout), strict = True)) == CONTEXT_URLS

# ======================================================================================================================
# The control, a guard whose exception allows every push lets every refusal through
# ======================================================================================================================

@pytest.fixture(scope = "module")
def open_guard(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    A copy of the guard whose exception takes every push and judges every repo allowed.
    """
    text = GUARD.read_text(encoding = "utf-8")
    assert text.count(SHAPE_LINE) == 1, "the exception's shape line moved, update SHAPE_LINE"
    assert text.count(VERDICT_FN) == 1, "the exception's verdict function moved, update VERDICT_FN"
    text = text.replace(SHAPE_LINE, "  if (true) {").replace(VERDICT_FN, VERDICT_FN + " return { allowed: true };")
    copy = tmp_path_factory.mktemp("open-guard") / "kdf-guard.js"
    copy.write_text(text, encoding = "utf-8", newline = "\n")
    return copy


@pytest.mark.parametrize("name", REFUSALS)
def test_each_refusal_fails_against_a_guard_that_allows_it(tmp_path: Path, name: str, open_guard: Path) -> None:
    """
    A reviewer is left out on purpose, reviewer git refuses every push before the exception is reached.
    """
    work, command, env = _refusal(name, tmp_path)
    code, message = _guard(work, command, env = env, guard = open_guard)
    assert code == 0, f"{name} is refused by something other than the exception. {message.strip()}"
