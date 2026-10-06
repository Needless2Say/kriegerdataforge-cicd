"""
Tests for kdf-ask-codex.sh (D-052), the one way a session asks Codex for a read only review or a second opinion.

The tool runs as it ships, against a throwaway repo and a stand in for codex that records how it was started, the
frame it read on stdin and the folder it ran in, and plays a clean answer, a tool outside the shell, a folder it
changed, a commit, a broken or locked worktree, events that vouch for nothing, no answer or a failure. Stand ins for
cp, date and node, put first on PATH, play a race, one second and a broken reader. The tests need bash, node and git.
GitHub's runners have all three, and a machine without them skips the module. The stand in logs its folder with
`pwd -W` where Git Bash has it, so a Windows path is checked on Windows and not a `/c/...` path Python cannot find.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "claude-code" / "kdf-ask-codex.sh"
NODE = shutil.which("node")
BASH = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")

# the review panel's fourteen questions by the words each opens with in a frame (D-056)
QUESTION_WORDS = {
    1: "1. Outcome.",
    2: "2. Assumptions.",
    3: "3. Blast radius.",
    4: "4. Inputs and authority.",
    5: "5. Trust.",
    6: "6. Failure, order and undo.",
    7: "7. Time.",
    8: "8. Load.",
    9: "9. Evidence of success.",
    10: "10. The class.",
    11: "11. Enforcement and wording.",
    12: "12. Contradiction and drift.",
    13: "13. The doer and the cost.",
    14: "14. Pre mortem.",
}

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
printf 'pwd=%s\\n' "$(pwd -W 2>/dev/null || pwd)" >> "$STUB_LOG"
printf 'head=%s\\n' "$(git rev-parse HEAD 2>/dev/null)" >> "$STUB_LOG"
printf 'gitenv=%s\\n' "$(env | grep -c '^GIT_')" >> "$STUB_LOG"
cat > "$STUB_FRAME"
answer=""
while [ $# -gt 0 ]; do
    if [ "$1" = "-o" ]; then answer="$2"; shift 2; continue; fi
    shift
done
if [ "${STUB_MODE:-clean}" = noevents ]; then printf 'No real problems.\\n' > "$answer"; exit 0; fi
printf '{"type":"thread.started","thread_id":"t"}\\n'
printf '{"type":"item.completed","item":{"id":"1","type":"command_execution","command":"git log"}}\\n'
case "${STUB_MODE:-clean}" in
    strange) printf '{"type":"item.completed","item":{"id":"2","type":"mcp_tool_call","server":"s","tool":"t"}}\\n' ;;
    garbled) printf 'not an event\\n' ;;
    shapeless) printf '{}\\n[]\\n' ;;
    turns) usage='"usage":{"input_tokens":100,"cached_input_tokens":150,"output_tokens":10}'
           printf '{"type":"turn.completed",%s}\\n' "$usage" ;;
    dirty) printf 'x\\n' > written.txt ;;
    commit) git -c user.name=s -c user.email=s@example.com commit -q --allow-empty -m moved ;;
    nogit) rm -f .git ;;
    lock) git worktree lock --reason stand-in . ;;
    lockbroken) git worktree lock --reason stand-in . && rm -f .git ;;
    silent) answer="" ;;
    fail) echo "boom" >&2; exit 3 ;;
esac
printf '{"type":"item.completed","item":{"id":"3","type":"agent_message","text":"No real problems."}}\\n'
printf '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":20}}\\n'
[ -z "$answer" ] || printf 'No real problems.\\n' > "$answer"
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


def _stand_ins(rig: Rig, **bodies: str) -> dict[str, str]:
    """
    Put stand ins for the named programs first on PATH, each reaching the real one with its folder taken off PATH.
    """
    folder = rig.tmp / "bin"
    folder.mkdir(exist_ok = True)
    for name, body in bodies.items():
        program = folder / name
        program.write_text(f'#!/usr/bin/env bash\nPATH="${{PATH#*:}}"\n{body}', encoding = "utf-8", newline = "\n")
        program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"}


def _left(rig: Rig) -> list[Path]:
    """
    What a run left behind, its scratch folder in TMPDIR and any worktree but the repo itself.
    """
    return [*rig.tmp.glob("kdf-ask-codex.*"), *[Path(line) for line in _worktrees(rig)[1:]]]

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
    assert "**Verdict.** passed." in text and "**Kind.** review." in text, "review is the default kind"
    assert "**Tokens.** 60 new input, 40 cached input read again, 20 output." in text
    assert ", 1 commands, " in text and text.rstrip().endswith("No real problems.")
    assert answers[0].with_suffix(".events.jsonl").is_file() and (rig.archive / f"{answers[0].stem}.frame.md").is_file()
    assert "its folder unchanged" in done.stdout and not _left(rig)


def test_codex_reads_the_commit_in_a_worktree_of_its_own_that_is_removed_after(rig: Rig) -> None:
    first = _git(rig.repo, "rev-parse", "HEAD~1")
    done  = _ask(rig, "--at", "HEAD~1")
    assert done.returncode == 0, done.stderr
    assert _logged(rig, "head=") == first
    ran_in = Path(_logged(rig, "pwd="))
    assert ran_in.name == "folder" and ran_in.parent.parent == rig.tmp, "a native path, so exists() means something"
    assert not ran_in.exists() and not _left(rig), "the worktree, its registration and the scratch folder are gone"


def test_two_runs_in_the_same_second_keep_their_own_answer_frame_and_events(rig: Rig) -> None:
    frozen = _stand_ins(rig, date = 'exec date -d "2026-10-05 12:00:00" "$@"\n')
    assert _ask(rig, env = frozen).returncode == 0 and _ask(rig, env = frozen).returncode == 0
    answers = _answers(rig)
    assert len(answers) == 2 and all(answer.name.startswith("2026-10-05-120000-") for answer in answers)
    assert len(list(rig.archive.glob("*.frame.md"))) == 2 and len(list(rig.archive.glob("*.events.jsonl"))) == 2


@pytest.mark.parametrize("kind, closes", [
    ("review", "Report only real problems, most severe first"),
    ("plan", "The question holds a plan, not code. Judge it against what you read, in this order."),
    ("decision", "The question holds a decision and its options. Choose as if the choice were yours."),
    ("rules", "The question holds rules or process text, proposed or about to be pushed"),
])
def test_each_kind_closes_the_frame_with_its_own_instruction(rig: Rig, kind: str, closes: str) -> None:
    others = {
        "review": "Report only real problems",
        "plan": "holds a plan",
        "decision": "Name your pick first",
        "rules": "holds rules or process text",
    }
    assert _ask(rig).returncode == 0
    review = rig.frame.read_text(encoding = "utf-8")
    assert _ask(rig, "--kind", kind).returncode == 0
    frame = rig.frame.read_text(encoding = "utf-8")
    assert frame.count(closes) == 1 and frame.rstrip().endswith("it changes nothing by itself.")
    assert not [text for name, text in others.items() if name != kind and text in frame], "one closing, its own"
    review_closes = "Report only real problems, most severe first"
    assert frame.split(closes)[0] == review.split(review_closes)[0], "the frame before the closing is the same"
    assert frame.count("it changes nothing by itself.") == 1
    assert f"**Kind.** {kind}." in max(_answers(rig), key = lambda path: path.stat().st_mtime_ns).read_text(
        encoding = "utf-8",
    )


def test_a_plan_asks_whether_its_route_is_worth_taking_before_it_is_judged(rig: Rig) -> None:
    # D-055, the owner's ask of 2026-10-06. A reader asked only what is wrong takes the route as given, so a plan first
    # asks for the reader's own approach, then whether the route is worth taking at all and its simplest alternative,
    # and only then for its problems
    assert _ask(rig, "--kind", "plan").returncode == 0
    closing = " ".join(rig.frame.read_text(encoding = "utf-8").split("The question holds")[-1].split())
    asked   = [closing.find(words) for words in (
        "how you would approach it yourself", "worth taking at all", "the simplest alternative",
        "report what is wrong, missing or riskier",
    )]
    assert -1 not in asked and asked == sorted(asked), "own approach, worth taking, simplest alternative, then judged"


def test_a_decision_names_its_pick_first_and_lets_it_be_none_of_the_options(rig: Rig) -> None:
    # D-053 keeps a decision's pick first, since the owner wants a pick and the case against it. D-055 lets that pick
    # be none of the options or doing nothing, so the question of worth is asked there too
    assert _ask(rig, "--kind", "decision").returncode == 0
    closing = " ".join(rig.frame.read_text(encoding = "utf-8").split("The question holds")[-1].split())
    asked   = [closing.find(words) for words in (
        "Name your pick first", "doing nothing included", "a simpler alternative", "worth taking at all",
        "the strongest case against your pick",
    )]
    assert -1 not in asked and asked == sorted(asked), "the pick first, then none or simpler, then the case against"


def test_a_review_asks_no_worth_taking_question(rig: Rig) -> None:
    # a review reads a change the session already made, so its closing asks for real problems alone
    assert _ask(rig).returncode == 0
    frame = " ".join(rig.frame.read_text(encoding = "utf-8").split())
    assert "worth taking" not in frame and "how you would approach it yourself" not in frame


@pytest.mark.parametrize("args, asked, header", [
    (["--kind", "plan"], {1, 2, 3, 6, 14}, "plan, 1 2 3 6 14"),
    (["--kind", "decision"], {1, 2, 9, 13, 14}, "decision, 1 2 9 13 14"),
    (["--kind", "rules"], {3, 7, 11, 12, 13}, "rules, 3 7 11 12 13"),
    ([], {2, 3, 4, 6, 9}, "review, 2 3 4 6 9"),
    (["--fix"], {2, 10, 4, 6, 9}, "review, 2 10 4 6 9"),
    (["--security"], {2, 3, 4, 5, 9}, "review, 2 3 4 5 9"),
    (["--fix", "--security"], {2, 10, 4, 5, 9}, "review, 2 10 4 5 9"),
    # what the session declares on top of a kind's five, each once, in the order given
    (["--kind", "plan", "--also", "8"], {1, 2, 3, 6, 14, 8}, "plan, 1 2 3 6 14 8"),
    (["--kind", "plan", "--security"], {1, 2, 3, 6, 14, 5}, "plan, 1 2 3 6 14 5"),
    (["--kind", "decision", "--fix"], {1, 2, 9, 13, 14, 10}, "decision, 1 2 9 13 14 10"),
    (["--also", "8"], {2, 3, 4, 6, 9, 8}, "review, 2 3 4 6 9 8"),
    (["--kind", "plan", "--also", "3"], {1, 2, 3, 6, 14}, "plan, 1 2 3 6 14"),
    (["--kind", "rules", "--also", "8", "--also", "5"], {3, 7, 11, 12, 13, 8, 5}, "rules, 3 7 11 12 13 8 5"),
])
def test_each_kind_asks_exactly_its_five_and_the_answer_names_them(
    rig: Rig,
    args: list[str],
    asked: set[int],
    header: str,
) -> None:
    # D-056. Each kind asks its five of the bank, a review's swaps declared by the session so every reader gets the
    # same five, and the answer's header names them, so a question left out, mapped wrong, or a frame from an old
    # clone shows
    assert _ask(rig, *args).returncode == 0
    frame = rig.frame.read_text(encoding = "utf-8")
    lines = frame.splitlines()
    found = {number for number, words in QUESTION_WORDS.items() if any(line.startswith(words) for line in lines)}
    # each asked once, whole, a heading alone or a repeat failing
    for number in asked:
        printed = [line for line in lines if line.startswith(QUESTION_WORDS[number])]
        assert len(printed) == 1 and printed[0].endswith("?") and len(printed[0]) > len(QUESTION_WORDS[number]) + 20
    assert found == asked
    assert "the probe it rests on" in frame and "not applicable" in frame and "unresolved" in frame
    answer = max(_answers(rig), key = lambda path: path.stat().st_mtime_ns).read_text(encoding = "utf-8")
    assert f"**Questions.** {header}." in answer


def test_the_bank_holds_all_fourteen_questions_once() -> None:
    # the words live in the script alone, every question of the bank once, those in no kind's five included
    text    = TOOL.read_text(encoding = "utf-8")
    numbers = [int(match) for match in re.findall(r"^questions\[(\d+)\]=", text, re.MULTILINE)]
    assert sorted(numbers) == list(range(1, 15))
    # each whole, its number first and a question at its end, a part added with += included
    bank = {number: "" for number in numbers}
    for number, part in re.findall(r'^questions\[(\d+)\]\+?="(.*)"$', text, re.MULTILINE):
        bank[int(number)] += part
    assert all(
        words.startswith(f"{number}. ") and words.endswith("?") and len(words) > 40 for number, words in bank.items()
    )


def test_rules_is_its_own_kind_with_its_own_opening_and_archived_as_rules(rig: Rig) -> None:
    # rules or process text is read as text that sessions follow, not as a plan, and its answer says so
    assert _ask(rig, "--kind", "rules").returncode == 0
    frame = " ".join(rig.frame.read_text(encoding = "utf-8").split())
    assert "The question holds rules or process text" in frame and "holds a plan" not in frame
    assert "**Kind.** rules." in max(_answers(rig), key = lambda path: path.stat().st_mtime_ns).read_text(
        encoding = "utf-8",
    )


def test_the_frame_carries_the_question_the_conventions_and_the_settled_decisions(rig: Rig) -> None:
    first = _git(rig.repo, "rev-parse", "HEAD~1")
    assert _ask(rig, "--base", "HEAD~1").returncode == 0
    frame = rig.frame.read_text(encoding = "utf-8")
    assert "Is there a real problem in b.txt?" in frame and "PowerShell" in frame
    assert "commas and periods" in frame and "Settled line one." in frame
    assert f"git diff {first}..HEAD" in frame
    assert _ask(rig, "--no-settled").returncode == 0
    assert "Settled line one." not in rig.frame.read_text(encoding = "utf-8")
    texts = [answer.read_text(encoding = "utf-8") for answer in _answers(rig)]
    assert sorted("in the frame.** yes." in text for text in texts) == [False, True], "one run with them, one without"


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


def test_a_git_variable_cannot_point_the_tool_or_codex_anywhere_else(rig: Rig) -> None:
    other = rig.tmp / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "-c", "user.name=o", "-c", "user.email=o@example.com", "commit", "-q", "--allow-empty", "-m", "other")
    moved = {"GIT_DIR": (other / ".git").as_posix(), "GIT_CONFIG": (other / ".git" / "config").as_posix()}
    done  = _ask(rig, env = moved)
    assert done.returncode == 0, done.stderr
    assert _logged(rig, "head=") == _git(rig.repo, "rev-parse", "HEAD"), "Codex read the repo it was given"
    assert _logged(rig, "gitenv=") == "0", "no GIT_ variable reached Codex"
    assert not _left(rig)


def test_the_worktree_is_made_with_no_checkout_so_no_hook_of_the_repo_runs(rig: Rig) -> None:
    log  = rig.tmp / "git.log"
    body = f'case " $* " in *" worktree add "*) printf "%s\\n" "$*" >> "{log.as_posix()}" ;; esac\nexec git "$@"\n'
    assert _ask(rig, env = _stand_ins(rig, git = body)).returncode == 0
    assert "--no-checkout" in log.read_text(encoding = "utf-8").split()
    assert _logged(rig, "head=") == _git(rig.repo, "rev-parse", "HEAD") and not _left(rig)


def test_a_worktree_whose_registration_cannot_be_read_is_still_removed(rig: Rig) -> None:
    blind = _stand_ins(rig, git = 'case " $* " in *" --absolute-git-dir "*) exit 1 ;; esac\nexec git "$@"\n')
    done  = _ask(rig, env = blind)
    assert done.returncode == 2 and "could not be read" in done.stderr, done.stderr
    assert not rig.log.exists() and not _left(rig)


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
    (["--repo", "REPO", "--brief", "BRIEF", "--kind", "essay"], "review, plan, decision or rules"),
    (["--repo", "REPO", "--brief", "BRIEF", "--also", "15"], "--also takes a question's number, 1 to 14"),
    (["--repo", "REPO", "--brief", "BRIEF", "--also", "load"], "--also takes a question's number, 1 to 14"),
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
    assert not rig.log.exists() and not _left(rig)


@pytest.mark.parametrize("name, text, says", [
    (".env.kdf", "Is there a real problem?\n", "named like a secret file"),
    ("CLIENT.PEM", "Is there a real problem?\n", "named like a secret file"),
    ("brief.md", "Is " + "gh" + "p_" + "A" * 36 + " real?\n", "token's shape"),
])
def test_a_brief_that_could_hold_a_secret_is_refused_dry_run_too(rig: Rig, name: str, text: str, says: str) -> None:
    brief = rig.tmp / name
    brief.write_text(text, encoding = "utf-8")
    done = _run(rig, "--repo", rig.repo.as_posix(), "--brief", brief.as_posix(), "--dry-run")
    assert done.returncode == 2 and says in done.stderr, done.stderr
    assert "real" not in done.stdout and not rig.log.exists()


@pytest.mark.parametrize("brief", ["missing/.env.prod", "C:\\work\\keys\\notes.md", "C:\\work\\.ENV.KDF"])
def test_a_briefs_secret_name_is_judged_before_any_file_is_read(rig: Rig, brief: str) -> None:
    done = _run(rig, "--repo", rig.repo.as_posix(), "--brief", brief, "--dry-run")
    assert done.returncode == 2 and "named like a secret file" in done.stderr, done.stderr


def test_the_frame_reads_the_brief_it_checked_never_the_file_again(rig: Rig) -> None:
    token = "gh" + "p_" + "B" * 36
    # a cp that, once the brief is copied, writes a token into the file the session named
    racing = _stand_ins(
        rig,
        cp = f'cp "$@" || exit\ncase "${{@: -1}}" in */brief.md) printf "{token}\\n" >> "${{@: -2:1}}" ;; esac\n',
    )
    done   = _ask(rig, env = racing)
    assert done.returncode == 0, done.stderr
    assert token in rig.brief.read_text(encoding = "utf-8") and token not in rig.frame.read_text(encoding = "utf-8")


def test_a_brief_that_is_a_symbolic_link_is_refused(rig: Rig) -> None:
    link = rig.tmp / "linked.md"
    try:
        link.symlink_to(rig.brief)
    except OSError:
        pytest.skip("this machine cannot make a symbolic link")
    done = _run(rig, "--repo", rig.repo.as_posix(), "--brief", link.as_posix())
    assert done.returncode == 2 and "symbolic link" in done.stderr and not rig.log.exists()


def test_a_commit_that_tracks_a_symbolic_link_is_refused(rig: Rig) -> None:
    target = rig.tmp / "target.txt"
    target.write_text("../../outside/.env.kdf", encoding = "utf-8")
    blob = _git(rig.repo, "hash-object", "-w", target.as_posix())
    _git(rig.repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link")
    _git(rig.repo, "commit", "-q", "-m", "a link")
    done = _ask(rig)
    assert done.returncode == 2 and "tracks docs/link, a symbolic link" in done.stderr, done.stderr
    assert not rig.log.exists() and not _left(rig)

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
    assert not _left(rig) and not Path(_logged(rig, "pwd=")).exists()
    text = _answers(rig)[0].read_text(encoding = "utf-8")
    assert "**Verdict.** failed, Codex changed its folder" in text, "its answer is kept and never passes for a review"


def test_a_commit_in_the_folder_fails_the_run_though_git_status_is_clean(rig: Rig) -> None:
    done = _ask(rig, mode = "commit")
    assert done.returncode == 1 and "its HEAD moved" in done.stderr, done.stderr
    assert not _left(rig)


def test_a_folder_git_cannot_read_fails_the_run_and_its_registration_still_goes(rig: Rig) -> None:
    done = _ask(rig, mode = "nogit")
    assert done.returncode == 1 and "git could not read the folder" in done.stderr, done.stderr
    assert not _left(rig), "git would not remove the broken worktree, so its registration went by hand"


def test_a_locked_worktree_is_still_removed(rig: Rig) -> None:
    done = _ask(rig, mode = "lock")
    assert done.returncode == 0, done.stderr
    assert not _left(rig)


def test_a_locked_and_broken_worktree_is_still_unregistered(rig: Rig) -> None:
    done = _ask(rig, mode = "lockbroken")
    assert done.returncode == 1 and "git could not read the folder" in done.stderr, done.stderr
    assert not _left(rig), "git would not remove it and prune would skip its lock, so its registration went by hand"


def test_cleanup_unregisters_its_own_worktree_and_no_other(rig: Rig) -> None:
    other = rig.tmp / "other"
    _git(rig.repo, "worktree", "add", "-q", "--detach", other.as_posix(), "HEAD")
    shutil.rmtree(other)
    assert _ask(rig, mode = "nogit").returncode == 1
    registered = [Path(line.split(" ", 1)[1]).name for line in _worktrees(rig)[1:]]
    assert registered == ["other"], "another session's moved worktree keeps its registration"


def test_codex_failing_fails_the_run_and_keeps_what_it_was_told(rig: Rig) -> None:
    done = _ask(rig, mode = "fail")
    assert done.returncode == 1 and "codex exited 3" in done.stderr and "boom" in done.stderr
    assert list(rig.archive.glob("*.frame.md")), "the frame is archived for the next try"
    assert "**Verdict.** failed, codex exited 3" in _answers(rig)[0].read_text(encoding = "utf-8")


def test_codex_writing_no_answer_fails_the_run(rig: Rig) -> None:
    done = _ask(rig, mode = "silent")
    assert done.returncode == 1 and "wrote no answer" in done.stderr, done.stderr
    text = _answers(rig)[0].read_text(encoding = "utf-8")
    assert "(no answer was written)" in text
    assert "**Verdict.** failed, Codex exited cleanly and wrote no answer." in text


def test_events_that_cannot_be_read_fail_the_run(rig: Rig) -> None:
    done = _ask(rig, env = _stand_ins(rig, node = "exit 1\n"))
    assert done.returncode == 1 and "with 1 errors" in done.stderr, done.stderr
    assert "WARNING" in done.stdout and "unread" in done.stdout


@pytest.mark.parametrize("mode, warns", [("noevents", ""), ("garbled", "unreadable"), ("shapeless", "unreadable")])
def test_events_that_vouch_for_nothing_fail_the_run(rig: Rig, mode: str, warns: str) -> None:
    done = _ask(rig, mode = mode)
    assert done.returncode == 1 and "with 1 errors" in done.stderr, done.stderr
    assert warns in done.stdout


def test_an_archive_that_cannot_be_written_fails_the_run_and_prints_the_answer(rig: Rig) -> None:
    rig.archive.write_text("a file where the archive folder should be\n", encoding = "utf-8")
    done = _ask(rig)
    assert done.returncode == 1 and "could not be made" in done.stderr, done.stderr
    assert "could not be archived" in done.stdout and "No real problems." in done.stdout
    assert not _left(rig)


def test_a_frame_that_cannot_be_kept_beside_the_answer_fails_the_run(rig: Rig) -> None:
    broken = _stand_ins(rig, cp = 'case "${@: -1}" in *.frame.md) exit 1 ;; esac\nexec cp "$@"\n')
    done   = _ask(rig, env = broken)
    assert done.returncode == 1 and "could not be written beside" in done.stderr, done.stderr
    assert "No real problems." in done.stdout and not _left(rig)
    assert _answers(rig) == [], "no answer stays behind to claim a verdict its archive could not keep"


def test_new_input_is_counted_turn_by_turn(rig: Rig) -> None:
    assert _ask(rig, mode = "turns").returncode == 0
    text = _answers(rig)[0].read_text(encoding = "utf-8")
    assert "**Tokens.** 60 new input, 140 cached input read again, 30 output." in text, text

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
    ("patches/.ENV.KDF", "X=1\n", "named like a secret file"),
    ("keys/deploy.pem", "x\n", "named like a secret file"),
    ("keys/notes.txt", "x\n", "named like a secret file"),
    ("certs/client.PFX", "x\n", "named like a secret file"),
    ("ssh/id_ed25519", "x\n", "named like a secret file"),
    ("infra/terraform.tfstate", "{}\n", "named like a secret file"),
    ("notes.md", "gh" + "p_" + "A" * 36 + "\n", "token's shape"),
    (".git/HEAD", "ref: refs/heads/main\n", "is a repo"),
    ("other/.git/HEAD", "ref: refs/heads/main\n", "is a repo inside it"),
])
def test_files_mode_refuses_a_secret_a_token_or_a_repo(rig: Rig, name: str, text: str, says: str) -> None:
    bundle = rig.tmp / "bundle"
    (bundle / name).parent.mkdir(parents = True, exist_ok = True)
    (bundle / name).write_text(text, encoding = "utf-8")
    done = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix())
    assert done.returncode == 2 and says in done.stderr, done.stderr
    assert not rig.log.exists() and not _left(rig)


def test_files_mode_refuses_a_secret_name_before_it_copies_anything(rig: Rig) -> None:
    bundle = rig.tmp / "bundle"
    (bundle / "keys").mkdir(parents = True)
    (bundle / "keys" / "deploy.txt").write_text("x\n", encoding = "utf-8")
    log     = rig.tmp / "cp.log"
    watched = _stand_ins(rig, cp = f'printf "%s\\n" "$*" >> "{log.as_posix()}"\nexec cp "$@"\n')
    done    = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix(), env = watched)
    assert done.returncode == 2 and "keys/deploy.txt in" in done.stderr, done.stderr
    assert "-R" not in log.read_text(encoding = "utf-8").split(), "the brief was copied, the folder never was"


def test_files_mode_checks_the_copy_so_a_file_that_lands_during_it_is_caught(rig: Rig) -> None:
    bundle = rig.tmp / "bundle"
    bundle.mkdir()
    (bundle / "1-change.patch").write_text("diff --git a/x b/x\n", encoding = "utf-8")
    # a cp that drops a secret file into the copy as it finishes, after any check of the source
    landing = _stand_ins(rig, cp = 'cp "$@" || exit\n[ ! -d "${@: -1}" ] || printf "X=1\\n" > "${@: -1}/.env.kdf"\n')
    done    = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix(), env = landing)
    assert done.returncode == 2 and ".env.kdf in" in done.stderr and "secret file" in done.stderr, done.stderr
    assert not rig.log.exists() and not _left(rig)


def test_files_mode_refuses_a_symbolic_link(rig: Rig) -> None:
    bundle = rig.tmp / "bundle"
    bundle.mkdir()
    try:
        (bundle / "notes.md").symlink_to(rig.settled)
    except OSError:
        pytest.skip("this machine cannot make a symbolic link")
    done = _run(rig, "--files", bundle.as_posix(), "--brief", rig.brief.as_posix())
    assert done.returncode == 2 and "notes.md in" in done.stderr and "symbolic link" in done.stderr, done.stderr
    assert not rig.log.exists() and not _left(rig)


def test_help_is_the_tools_own_header() -> None:
    done = subprocess.run([str(BASH), str(TOOL), "--help"], capture_output = True, text = True)
    assert done.returncode == 0 and done.stdout.startswith("kdf-ask-codex.sh, ask Codex")
