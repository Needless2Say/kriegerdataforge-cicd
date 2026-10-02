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
BRIEF     = TOOLS / "kdf-brief.js"
RETRO     = TOOLS / "kdf-retro.js"
INSTALLER = TOOLS / "install.sh"
NODE      = shutil.which("node")
BASH      = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
CASES     = json.loads((TOOLS / "guard-cases.json").read_text(encoding = "utf-8"))
KIT       = TOOLS.parents[1] / "kit" / "common"

# a closed slice's record in miniature, for the retrospective tool
RETRO_SLICE = Path(__file__).resolve().parent / "fixtures" / "retro" / "s1-example"

# what the guard refuses, in the words the role charter must keep, so a model that runs no guard is told the same
GUARD_RULES_IN_WORDS = (
    "merge",
    "approve",
    "mark ready",
    "tag",
    "release",
    "publish",
    "dispatch a workflow",
    "re-run",
    "DEV or PROD",
    "vercel",
    "terraform apply",
    "`prod`",
    "`dev` without `local`",
    "ENVIRONMENT",
    "push to `main`",
    "force push",
    "`origin`",
    ".env",
    "*.tfvars",
    "*.pem",
    "keys/",
    ".claude/settings",
    ".mcp.json",
    "git hooks",
    "`git -c`",
    "deploy key",
    "gist",
    "KDF_ROLE=reviewer",
    "docs/reviews/",
    "GitHub CLI",
    "connectors",
    "`.env.dev`",
    "`.env.local.bak`",
    "GH_PACKAGES_PAT",
    "GH_NPM_TOKEN",
    "KDF_OIDC_CLIENT_SECRET",
    "`.env.kdf`",
    "`.env.prod`",
    "sources",
    "`.gitignore`",
    "recursive `grep`",
    "`rg -u`",
    "`git grep --no-index`",
    "`.git/kdf-review`",
    "package script",
    "`docker ps`",
    "`docker logs`",
    "`curl`",
    "`localhost`",
    "follows no redirect",
)

# a stand in for claude, it writes what STUB_MODE says a reviewer did, and records how it was started
STUB = """#!/usr/bin/env bash
echo "role=${KDF_ROLE:-} selfedit=${KDF_GUARD_ALLOW_SELF_EDIT:-unset}" >> "$STUB_LOG"
echo "args=$*" >> "$STUB_LOG"
echo "pwd=$(pwd)" >> "$STUB_LOG"
echo "app=$(head -n 1 src/app.py 2>/dev/null)" >> "$STUB_LOG"
echo "saw=$(ls docs/reviews | tr '\\n' ' ')" >> "$STUB_LOG"
report=$(printf '%s' "$2" | sed -n 's/.*write your report to \\(.*\\), edit nothing else\\./\\1/p')
case "${STUB_MODE:-clean}" in
	clean) printf '# report\\nfinding\\n' > "$report" ;;
	tamper) printf '# report\\n' > "$report"; echo "x = 2" >> src/app.py ;;
	outside) printf '# report\\n' > "$report"; echo hi > stray.txt ;;
	scratch) printf '# report\\n' > "$report"; echo notes > docs/reviews/scratch.md ;;
	brief) printf '# report\\n' > "$report"; echo "settled, nothing to find" >> docs/reviews/BRIEF.md ;;
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
    what = str(case.get("command") or case.get("file") or json.dumps(case.get("input", "")))
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
    for key, value in dict(case.get("input", {})).items():  # type: ignore[call-overload]
        tool_input[key] = str(value).replace("${PROJ}", project.as_posix())
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


def _ignored_tree(project: Path) -> None:
    """
    A repo whose .gitignore covers a virtual environment, node_modules, logs and env files, with a .env.local that
    holds no credential, ones that do by the built in names or by their repo's .env.kdf.example, active or commented
    out, ones already split, and a report the launcher holds.
    """
    subprocess.run(["git", "init", "-q", str(project)], check = True, capture_output = True)
    files = {
        ".gitignore": ".venv/\nnode_modules/\n*.log\n.env*\n!.env.example\n!.env.kdf.example\n",
        ".venv/lib/site.py": "x = 1\n",
        "node_modules/pkg/index.js": "module.exports = 1;\n",
        "build.log": "log\n",
        "src/app.py": "x = 1\n",
        ".env.example": "GH_PACKAGES_PAT=\n",
        ".env.local": "DB_PASSWORD=local-only\nGH_PACKAGES_PAT=\n",
        "tokens/.env.local": "export GH_NPM_TOKEN=\"x\"\n",
        "hub/.env.local": "AUTH_RESEND_API_KEY=re_x\n",
        "custom/.env.kdf.example": "MY_API_KEY=\n",
        "custom/.env.local": "MY_API_KEY=abc\nPORT=3000\n",
        "migrated/.env.kdf.example": "GH_PACKAGES_PAT=\nKDF_SERVICE_KEY=\n",
        "migrated/.env.local": "PORT=3000\nDB_POSTGRES_PASSWORD=local\n",
        "commented/.env.kdf.example": "# Copy this file to .env.kdf, uncomment a line.\n#\n# STRIPE_SECRET_KEY=\n",
        "commented/.env.local": "PORT=3000\nSTRIPE_SECRET_KEY=sk_x\n",
        "moved/.env.kdf.example": "#   STRIPE_SECRET_KEY =\n",
        "moved/.env.local": "PORT=3000\n",
        "environments/dev/common.auto.tfvars": "region = \"x\"\n",
        "environments/dev/credentials.auto.tfvars": "token = \"x\"\n",
        ".env.kdf.example": "GH_PACKAGES_PAT=\n",
        "unadopted/.env.local": "PORT=3000\n",
        "docs/reviews/TRACKED.md": "# an earlier log\n",
        ".git/kdf-review/held/docs/reviews/CODEX.md": "# held\n",
    }
    for name, text in files.items():
        target = project / name
        target.parent.mkdir(parents = True, exist_ok = True)
        target.write_text(text, encoding = "utf-8", newline = "\n")
    tracked = [
        "environments/dev/common.auto.tfvars",
        ".env.kdf.example",
        "custom/.env.kdf.example",
        "migrated/.env.kdf.example",
        "commented/.env.kdf.example",
        "moved/.env.kdf.example",
        "docs/reviews/TRACKED.md",
    ]
    subprocess.run(["git", "-C", str(project), "add", "-f", *tracked], check = True, capture_output = True)


@pytest.fixture(scope = "module")
def guard_results(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[int, str]]:
    """
    Every guard case run once, in parallel, so the per case tests only read an answer.
    """
    project = tmp_path_factory.mktemp("kdf-project")
    _ignored_tree(project)
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


@pytest.mark.parametrize(
    ("command", "says"),
    [
        ("cat .env.prod", "admin files for the DEV and PROD databases"),
        ("cat .env.kdf", "Secret files are the owner's"),
        ("cat tokens/.env.local", "This .env.local is closed"),
    ],
)
def test_each_closed_file_is_refused_with_its_own_reason(tmp_path: Path, command: str, says: str) -> None:
    """
    The owner's admin files, a secret file and a .env.local that is still closed each tell the model why, and the
    credential message is the owner's cue to move a token.
    """
    _ignored_tree(tmp_path)
    code, message = _run_case(tmp_path, {"role": "owner", "tool": "Bash", "command": command, "expect": "block"})
    assert code == 2
    assert says in message


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


def test_the_role_charter_says_every_rule_the_guard_enforces() -> None:
    """
    Other models read AGENT_ROLES.md and run no guard, so the charter must keep naming every rule the guard holds.
    """
    text    = (KIT / "docs" / "agent" / "AGENT_ROLES.md").read_text(encoding = "utf-8")
    missing = [rule for rule in GUARD_RULES_IN_WORDS if rule not in text]
    assert not missing, f"AGENT_ROLES.md no longer names {missing}, change it together with the guard"


def test_every_agent_meets_its_role_where_it_reads() -> None:
    """
    WORKFLOW.md, which every AGENTS.md sends an agent to, opens with the roles, and a reviewer's brief carries its own.
    The charter, WORKFLOW.md and the brief each tell every model to follow .gitignore.
    """
    workflow = (KIT / "WORKFLOW.md").read_text(encoding = "utf-8")
    assert "## Before anything, know your role" in workflow
    assert workflow.index("## Before anything, know your role") < workflow.index("## Step 0.")
    assert "docs/agent/AGENT_ROLES.md" in workflow
    brief = (KIT / "docs" / "agent" / "templates" / "review-brief.template.md").read_text(encoding = "utf-8")
    assert "**Your role.** You are a **reviewer**" in brief
    assert "`docs/agent/AGENT_ROLES.md`" in brief
    registry = json.loads((TOOLS.parents[1] / "scripts" / "kit_registry.json").read_text(encoding = "utf-8"))
    assert "docs/agent/AGENT_ROLES.md" in registry["files"]
    charter = (KIT / "docs" / "agent" / "AGENT_ROLES.md").read_text(encoding = "utf-8")
    assert "**Follow `.gitignore`.**" in charter
    assert "Follow `.gitignore`." in brief
    assert "`.gitignore` covers" in workflow


def test_every_review_is_archived_in_a_dated_folder() -> None:
    """
    The process, its templates and the sync registry agree on the archive, one folder per review under
    docs/reviews/, named by the day it opened, opened with the README template, a folder per step inside.
    """
    process = (KIT / "docs" / "agent" / "CODE_REVIEW_PROCESS.md").read_text(encoding = "utf-8")
    assert "docs/reviews/<YYYY-MM-DD>-<scope>/" in process
    for step in ("step-2-review", "step-4-sol", "round-<n>", "step-5-final", "step-5-second-read-<n>"):
        assert step in process, f"CODE_REVIEW_PROCESS.md no longer names the {step} folder"
    templates = KIT / "docs" / "agent" / "templates"
    readme    = (templates / "review-readme.template.md").read_text(encoding = "utf-8")
    assert "docs/reviews/{YYYY-MM-DD}-{scope}/" in readme
    for name in ("review-brief", "review-plan", "review-adjudication"):
        text = (templates / f"{name}.template.md").read_text(encoding = "utf-8")
        assert "reviews/{YYYY-MM-DD}-{scope}" in text, f"{name} no longer names the review folder"
    registry = json.loads((TOOLS.parents[1] / "scripts" / "kit_registry.json").read_text(encoding = "utf-8"))
    assert "docs/agent/templates/review-readme.template.md" in registry["files"]
    assert "docs/reviews/README.md" in process, "the archive's front door is no longer named"
    stale = [
        str(path.relative_to(KIT))
        for path in KIT.rglob("*.md")
        if "docs/security/reviews" in path.read_text(encoding = "utf-8")
    ]
    assert not stale, f"the old archive root is still named in {stale}"
    standard = (KIT / "docs" / "agent" / "DOCUMENTATION_STANDARD.md").read_text(encoding = "utf-8")
    assert "| `docs/reviews/` |" in standard
    assert "`docs/code_review/`" not in standard


def test_every_slice_closes_with_an_answer_key_and_every_report_names_its_model() -> None:
    """
    A closed slice can score any later reviewer's report. The process names the answer key, the template exists and is
    synced, the adjudication log points at it, and a report's header names the exact model, the tool, the tokens and
    measured times, so two reports of one pin can be compared.
    """
    process   = (KIT / "docs" / "agent" / "CODE_REVIEW_PROCESS.md").read_text(encoding = "utf-8")
    templates = KIT / "docs" / "agent" / "templates"
    assert "`<PFX>_REVIEW_<slice>_ANSWER_KEY.md`" in process
    assert "templates/review-answer-key.template.md" in process
    assert "**The archive is also a benchmark.**" in process
    registry = json.loads((TOOLS.parents[1] / "scripts" / "kit_registry.json").read_text(encoding = "utf-8"))
    assert "docs/agent/templates/review-answer-key.template.md" in registry["files"]
    key = (templates / "review-answer-key.template.md").read_text(encoding = "utf-8")
    for column in ("Reviewer model", "At the step 2 pin", "Present from", "Fixed in", "Needs", "Log row"):
        assert f"| {column} |" in key, f"the answer key template lost its {column} column"
    assert "## 4. Declined, and measured false" in key
    adjudication = (templates / "review-adjudication.template.md").read_text(encoding = "utf-8")
    assert "review-answer-key.template.md" in adjudication
    report = (templates / "review-report.template.md").read_text(encoding = "utf-8")
    for line in ("- **Reviewer.**", "- **Usage.**", "- **Time spent.**"):
        assert line in report, f"the report header lost {line}"
    assert "the times the clock showed" in report, "the report's time spent is an estimate again"


def test_a_supporting_session_builds_what_a_review_finds_outside_the_reviewed_repo() -> None:
    """
    The orchestrator stays on the review (D-034). The process names the supporting session as a role, says what its
    handoff carries, says who brings a merged fix to a review (the orchestrator, by moving the clone forward and
    installing the tooling again between pins, never the supporting session), keeps the session out of the reviewed
    repo's folder, and hands it what cicd owns when the review has one. The roles page says the same.
    """
    process = " ".join((KIT / "docs" / "agent" / "CODE_REVIEW_PROCESS.md").read_text(encoding = "utf-8").split())
    roles   = " ".join((KIT / "docs" / "agent" / "AGENT_ROLES.md").read_text(encoding = "utf-8").split())
    assert "| Supporting session |" in process
    assert "**The supporting session.**" in process
    for part in ("the finding,", "the evidence that proves it,", "what is already done,", "what would prove the fix."):
        assert part in process, f"the handoff lost its part {part!r}"
    who_brings_a_fix = (
        "A merged fix reaches a review only when the machine's clone of the repo that owns it is brought forward and "
        "the reviewer tooling is installed again. The orchestrator does both, between pins and never under an open one,"
    )
    for page in (process, roles):
        assert who_brings_a_fix in page
        assert "the supporting session does neither." in page
        assert "never edits, commits, checks out or stashes anything in the reviewed repo's folder" in page
    assert "The orchestrator hands it to the supporting session when the review has one, section 2" in process
    assert "since v1.10.0" in process
    assert "- **Supporting session**, when the owner started you beside a review's orchestrator" in roles
    assert "**The supporting session** is an implementer started beside the orchestrator." in roles


def test_sol_bundles_go_to_the_workspace_temp_folder_and_never_into_a_repo() -> None:
    """
    The owner manages the Sol bundles (D-036). Section 9 sends them to the workspace's `temp/` folder, made when
    missing, names one lower case file per dispatch, keeps them out of every repo's folder and out of the system's temp
    folder, and leaves their deletion to the owner after the round.
    """
    process   = " ".join((KIT / "docs" / "agent" / "CODE_REVIEW_PROCESS.md").read_text(encoding = "utf-8").split())
    section_9 = process.split("## 9. ChatGPT Sol dispatches", 1)[1].split("## 10.", 1)[0]
    assert "**Bundles go to the workspace's temp folder.**" in section_9
    assert "write into its `temp/` folder, making it when missing, `mkdir -p temp`" in section_9
    assert "`New-Item -ItemType Directory -Force temp`" in section_9
    assert "`kdf-<pfx>-<slice>-dispatch-<n>.txt` in lower case" in section_9
    assert "A bundle never goes into a repo's folder, because a review's launcher counts every new file" in section_9
    assert "never into the system's temp folder" in section_9
    assert "the owner deletes them after the round." in section_9
    assert "since v1.11.0" in process


def test_every_slice_closes_with_a_measured_retrospective_the_owner_decides() -> None:
    """
    The process learns from each slice (D-037). It names the retrospective beside the answer key and the campaign's own,
    the template is synced and laid out as the numbers, the escapes, the friction, the experiments, the proposals and
    the owner's decisions, section 14 has the tool print the numbers, the owner say yes or no to every change, and
    accuracy come before the owner's time and tokens, and the supporting session turns proposals into the owner's list.
    """
    process   = " ".join((KIT / "docs" / "agent" / "CODE_REVIEW_PROCESS.md").read_text(encoding = "utf-8").split())
    templates = KIT / "docs" / "agent" / "templates"
    assert "`<PFX>_REVIEW_<slice>_RETRO.md`" in process
    assert "`<PFX>_REVIEW_CAMPAIGN_RETRO.md`" in process
    assert "templates/review-retro.template.md" in process
    assert "since v1.12.0" in process
    registry = json.loads((TOOLS.parents[1] / "scripts" / "kit_registry.json").read_text(encoding = "utf-8"))
    assert "docs/agent/templates/review-retro.template.md" in registry["files"]
    retro    = (templates / "review-retro.template.md").read_text(encoding = "utf-8")
    sections = (
        "## 1. The numbers",
        "## 2. Escapes",
        "## 3. Friction",
        "## 4. The experiments of earlier retrospectives",
        "## 5. Proposals",
        "## 6. The owner's decisions",
    )
    for heading in sections:
        assert heading in retro, f"the retrospective template lost {heading!r}"
    assert len(retro.splitlines()) < 150
    section_14 = process.split("## 14. Closing a review", 1)[1]
    assert "**Every slice closes with a measured retrospective**" in section_14
    assert "`node <cicd>/tools/claude-code/kdf-retro.js <slice folder>`" in section_14
    assert "Nothing changes without the owner's yes." in section_14
    assert "Accuracy first, the escape rate, then the owner's time and waiting, then tokens" in section_14
    assert "no change saves tokens at the cost of catches" in section_14
    assert "improvement ledger of the bench repo" in section_14
    assert "Turns a closed slice's retrospective into the owner's list of proposals" in process
    for name in ("review-readme.template.md", "review-adjudication.template.md"):
        assert "RETRO.md" in (templates / name).read_text(encoding = "utf-8"), f"{name} does not name the retrospective"


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
    A repo with one commit and a brief, pushed to a bare origin, a home whose settings are exactly what the checker
    prints, and the stub.
    """
    home = tmp_path / "home"
    (home / ".claude" / "hooks").mkdir(parents = True)
    shutil.copy(GUARD, home / ".claude" / "hooks" / "kdf-guard.js")
    _write_settings(home, _printed_settings(home))

    repo = tmp_path / "repo"
    (repo / "docs" / "reviews").mkdir(parents = True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding = "utf-8")
    (repo / "docs" / "reviews" / "BRIEF.md").write_text("# brief\n", encoding = "utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check = True, capture_output = True)
    _git(repo, "remote", "add", "origin", origin.as_posix())
    _git(repo, "push", "-q", "origin", "main")

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
        "docs/reviews/BRIEF.md",
        "--report",
        "docs/reviews/REPORT.md",
        *extra,
        mode = mode,
        env = env,
    )


def test_a_clean_review_is_reported_clean(rig: Rig) -> None:
    """
    The stub writes its report and nothing else, the launcher says clean and hands over the Codex line.
    """
    done = _launch(rig, "--codex-report", "docs/reviews/CODEX.md")
    assert done.returncode == 0, done.stderr
    assert "clean" in done.stdout
    assert "write your report to docs/reviews/CODEX.md, edit nothing else." in done.stdout
    assert (rig.repo / "docs" / "reviews" / "REPORT.md").is_file()


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


def test_new_files_under_docs_reviews_are_allowed(rig: Rig) -> None:
    """
    A reviewer's scratch note beside its report is inside the rule, a new file under docs/reviews.
    """
    assert _launch(rig, mode = "scratch").returncode == 0


@pytest.mark.parametrize(
    ("mode", "named"),
    [
        ("tamper", "src/app.py"),
        ("brief", "changed, docs/reviews/BRIEF.md"),
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
    (rig.repo / "docs" / "reviews" / "REPORT.md").unlink(missing_ok = True)
    assert _launch(rig, mode = "fail").returncode == 6


def test_the_arguments_are_checked_before_anything_runs(rig: Rig) -> None:
    """
    A report outside docs/reviews, one that exists, a missing brief and a repo that is not a root are all exit 2.
    docs/security holds posture docs, so a report or a Codex report there is refused like any other folder.
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


    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "src/REPORT.md") == 2
    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/security/REPORT.md") == 2
    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews/../security/REPORT.md") == 2
    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews-old/REPORT.md") == 2
    assert (
        run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews/R.md", "--codex-report", "docs/security/C.md")
        == 2
    )
    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews/../../REPORT.md") == 2
    assert run("--brief", "docs/reviews/NOPE.md", "--report", "docs/reviews/REPORT.md") == 2
    assert run("--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews/BRIEF.md") == 2
    assert run("--brief", "docs/reviews/BRIEF.md") == 2
    assert not rig.log.exists()
    not_a_root = (rig.repo / "src").as_posix()
    sub        = subprocess.run(
        [str(BASH), str(LAUNCHER), "--repo", not_a_root, "--brief", "x", "--report", "docs/reviews/R.md"],
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
    done = _launch(rig, "--codex-report", "docs/reviews/CODEX.md", "--dry-run")
    assert done.returncode == 0
    assert "Claude prompt, Read docs/reviews/BRIEF.md and run the review," in done.stdout
    assert "write your report to docs/reviews/REPORT.md, edit nothing else." in done.stdout
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


def _hold(rig: Rig) -> Path:
    """
    The folder in the rig's git directory where an open review keeps its state and the reports it holds.
    """
    return rig.repo / ".git" / "kdf-review"


def _prepare(rig: Rig) -> subprocess.CompletedProcess[str]:
    """
    Open the rig's folder at HEAD for Codex, the reviewer the owner starts by hand.
    """
    return _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        "docs/reviews/BRIEF.md",
        "--report",
        "docs/reviews/REPORT.md",
        "--codex-report",
        "docs/reviews/CODEX.md",
        "--pin",
        "HEAD",
        "--prepare",
    )


def _collect(rig: Rig) -> subprocess.CompletedProcess[str]:
    return _run(rig, "--repo", rig.repo.as_posix(), "--collect")


def _codex_writes_its_report(rig: Rig) -> None:
    (rig.repo / "docs" / "reviews" / "CODEX.md").write_text("# codex report\n", encoding = "utf-8")


def test_a_pinned_review_reads_the_folder_itself(rig: Rig) -> None:
    """
    With --pin the reviewer works in the repo folder, no copy is made, and the review closes when the run ends.
    """
    done = _launch(rig, "--pin", "HEAD")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (rig.repo / "docs" / "reviews" / "REPORT.md").is_file()
    log = rig.log.read_text(encoding = "utf-8")
    assert log.split("pwd=")[1].splitlines()[0].endswith("repo")
    assert "role=reviewer" in log
    assert not (_hold(rig) / "open").exists()
    assert not (rig.tmp / ".kdf-review").exists()


def test_a_folder_that_is_not_at_the_pin_is_never_reviewed(rig: Rig) -> None:
    """
    A tracked file changed since the pin, HEAD moved past it, a pin that is no commit, and a brief the pin lacks are
    all exit 2, and claude never runs.
    """
    pinned = subprocess.run(
        ["git", "-C", str(rig.repo), "rev-parse", "HEAD"],
        capture_output = True,
        text = True,
        check = True,
    ).stdout.strip()
    (rig.repo / "src" / "app.py").write_text("x = 2\n", encoding = "utf-8")
    assert _launch(rig, "--pin", "HEAD").returncode == 2
    _git(rig.repo, "commit", "-q", "-am", "moved on")
    assert _launch(rig, "--pin", pinned).returncode == 2
    assert _launch(rig, "--pin", "no-such-commit").returncode == 2
    (rig.repo / "docs" / "reviews" / "NEW.md").write_text("# not committed\n", encoding = "utf-8")
    uncommitted = _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        "docs/reviews/NEW.md",
        "--report",
        "docs/reviews/REPORT.md",
        "--pin",
        "HEAD",
    )
    assert uncommitted.returncode == 2
    assert not rig.log.exists()


def test_codex_reads_the_same_folder_and_collect_checks_it(rig: Rig) -> None:
    """
    --prepare opens the folder, prints the one line and the collect command, and runs no claude. Collect closes it.
    """
    done = _prepare(rig)
    assert done.returncode == 0, done.stderr
    assert "Read docs/reviews/BRIEF.md and run the review, write your report to docs/reviews/CODEX.md" in done.stdout
    assert "--collect" in done.stdout
    assert not rig.log.exists()
    assert (_hold(rig) / "open").is_dir()
    _codex_writes_its_report(rig)
    collected = _collect(rig)
    assert collected.returncode == 0, collected.stderr
    assert "clean" in collected.stdout
    assert not (_hold(rig) / "open").exists()
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").is_file()


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ("code", "src/app.py"),
        ("brief", "changed, docs/reviews/BRIEF.md"),
        ("stray", "stray.txt"),
        ("commit", "git state changed"),
        ("branch", "git state changed"),
    ],
)
def test_collect_catches_a_reviewer_that_did_more_than_report(rig: Rig, change: str, named: str) -> None:
    """
    A reviewer outside Claude Code has no guard, so collect is its check. Anything but the report is exit 3, and the
    review stays open.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    if change == "code":
        (rig.repo / "src" / "app.py").write_text("x = 2\n", encoding = "utf-8")
    elif change == "brief":
        (rig.repo / "docs" / "reviews" / "BRIEF.md").write_text("# brief\nsettled\n", encoding = "utf-8")
    elif change == "stray":
        (rig.repo / "stray.txt").write_text("hi\n", encoding = "utf-8")
    elif change == "commit":
        _git(rig.repo, "add", "-A")
        _git(rig.repo, "commit", "-q", "-m", "sneaky")
    else:
        _git(rig.repo, "checkout", "-q", "-b", "sneaky")
    collected = _collect(rig)
    assert collected.returncode == 3, collected.stdout + collected.stderr
    assert "CONTAMINATION" in collected.stderr
    assert named in collected.stderr
    assert (_hold(rig) / "open").is_dir()


def test_collect_waits_for_the_report_and_closes_once_the_folder_is_put_right(rig: Rig) -> None:
    """
    No report yet is exit 4 and the review stays open. A change the reviewer made is exit 3 until it is put back.
    """
    assert _prepare(rig).returncode == 0
    assert _collect(rig).returncode == 4
    assert (_hold(rig) / "open").is_dir()
    (rig.repo / "src" / "app.py").write_text("x = 2\n", encoding = "utf-8")
    _codex_writes_its_report(rig)
    assert _collect(rig).returncode == 3
    _git(rig.repo, "checkout", "--", "src/app.py")
    assert _collect(rig).returncode == 0
    assert not (_hold(rig) / "open").exists()


def test_collect_never_passes_a_review_it_has_no_snapshot_for(rig: Rig) -> None:
    """
    An open review whose snapshot is gone is exit 2 and stays open, never a clean collect.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    (_hold(rig) / "open" / "before").unlink()
    assert _collect(rig).returncode == 2
    assert (_hold(rig) / "open").is_dir()


def test_claude_first_its_report_waits_outside_the_tree_while_codex_reads(rig: Rig) -> None:
    """
    Codex never sees Claude's report of the scope, and closing the review puts it back beside Codex's.
    """
    archive = rig.repo / "docs" / "reviews"
    first   = _launch(rig, "--pin", "HEAD", "--codex-report", "docs/reviews/CODEX.md")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "--prepare" in first.stdout
    assert _prepare(rig).returncode == 0
    assert not (archive / "REPORT.md").exists()
    assert (_hold(rig) / "held" / "docs" / "reviews" / "REPORT.md").is_file()
    _codex_writes_its_report(rig)
    assert _collect(rig).returncode == 0
    assert (archive / "REPORT.md").is_file()
    assert (archive / "CODEX.md").is_file()


def test_codex_first_its_report_waits_outside_the_tree_while_claude_reads(rig: Rig) -> None:
    """
    Claude never sees Codex's report of the scope, and the run puts it back when it ends, clean or not.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    assert _collect(rig).returncode == 0
    done = _launch(rig, "--pin", "HEAD", "--codex-report", "docs/reviews/CODEX.md")
    assert done.returncode == 0, done.stdout + done.stderr
    saw = rig.log.read_text(encoding = "utf-8").split("saw=")[1].splitlines()[0]
    assert "BRIEF.md" in saw
    assert "CODEX.md" not in saw
    assert "--prepare" not in done.stdout
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").is_file()
    (rig.repo / "docs" / "reviews" / "REPORT.md").unlink()
    assert _launch(rig, "--codex-report", "docs/reviews/CODEX.md", mode = "tamper").returncode == 3
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").is_file()
    assert not (_hold(rig) / "open").exists()


def test_a_review_archived_in_its_dated_folder_runs_like_a_flat_one(rig: Rig) -> None:
    """
    The archive nests a review under docs/reviews/<date>-<scope>/<slice>/<step>/. The report lands beside the
    brief, Claude's report waits outside the tree under the same nested path while Codex reads, and collect puts both
    back side by side.
    """
    step   = "docs/reviews/2026-09-30-app/s1-core/step-2-review"
    folder = rig.repo / step
    folder.mkdir(parents = True)
    (folder / "APP_REVIEW_S1_PROMPT.md").write_text("# brief\n", encoding = "utf-8")
    _git(rig.repo, "add", "-A")
    _git(rig.repo, "commit", "-q", "-m", "brief in the archive")
    _git(rig.repo, "push", "-q", "origin", "main")
    paths = [
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        f"{step}/APP_REVIEW_S1_PROMPT.md",
        "--report",
        f"{step}/APP_REVIEW_S1_REPORT.md",
        "--codex-report",
        f"{step}/APP_REVIEW_S1_CODEX_REPORT.md",
        "--pin",
        "HEAD",
    ]
    first = _run(rig, *paths)
    assert first.returncode == 0, first.stdout + first.stderr
    assert (folder / "APP_REVIEW_S1_REPORT.md").is_file()
    prepared = _run(rig, *paths, "--prepare")
    assert prepared.returncode == 0, prepared.stderr
    assert f"write your report to {step}/APP_REVIEW_S1_CODEX_REPORT.md, edit nothing else." in prepared.stdout
    assert not (folder / "APP_REVIEW_S1_REPORT.md").exists()
    assert (_hold(rig) / "held" / step / "APP_REVIEW_S1_REPORT.md").is_file()
    (folder / "APP_REVIEW_S1_CODEX_REPORT.md").write_text("# codex report\n", encoding = "utf-8")
    collected = _collect(rig)
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert (folder / "APP_REVIEW_S1_REPORT.md").is_file()
    assert (folder / "APP_REVIEW_S1_CODEX_REPORT.md").is_file()
    assert not (_hold(rig) / "open").exists()


def _names(folder: Path) -> list[str]:
    """
    What a folder holds, files and folders, by name.
    """
    return sorted(path.name for path in folder.iterdir())


def test_the_first_reviewer_s_notes_wait_outside_the_tree_with_its_report(rig: Rig) -> None:
    """
    A brief lets a reviewer keep scratch notes beside its report, and they say what it found as plainly as the report
    does. A review of the SDK left three probes there and the orchestrator moved them out by hand. Every other
    untracked file in the brief's folder waits with the report and comes back with it, byte for byte.
    """
    archive = rig.repo / "docs" / "reviews"
    first   = _launch(rig, "--pin", "HEAD", "--codex-report", "docs/reviews/CODEX.md", mode = "scratch")
    assert first.returncode == 0, first.stdout + first.stderr
    assert _names(archive) == ["BRIEF.md", "REPORT.md", "scratch.md"]
    assert _prepare(rig).returncode == 0
    assert _names(archive) == ["BRIEF.md"]
    assert (_hold(rig) / "held" / "docs" / "reviews" / "scratch.md").read_text(encoding = "utf-8") == "notes\n"
    _codex_writes_its_report(rig)
    assert _collect(rig).returncode == 0
    assert _names(archive) == ["BRIEF.md", "CODEX.md", "REPORT.md", "scratch.md"]
    assert (archive / "scratch.md").read_text(encoding = "utf-8") == "notes\n"
    assert not (_hold(rig) / "open").exists()


def test_codex_first_its_notes_wait_while_claude_reads(rig: Rig) -> None:
    """
    The same the other way round. Claude never sees a note Codex left, and the run puts it back when it ends.
    """
    archive = rig.repo / "docs" / "reviews"
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    (archive / "codex_probe.py").write_text("print('probe')\n", encoding = "utf-8")
    assert _collect(rig).returncode == 0
    done = _launch(rig, "--pin", "HEAD", "--codex-report", "docs/reviews/CODEX.md")
    assert done.returncode == 0, done.stdout + done.stderr
    saw = rig.log.read_text(encoding = "utf-8").split("saw=")[1].splitlines()[0]
    assert "BRIEF.md" in saw
    assert "codex_probe.py" not in saw and "CODEX.md" not in saw
    assert _names(archive) == ["BRIEF.md", "CODEX.md", "REPORT.md", "codex_probe.py"]
    assert (archive / "codex_probe.py").read_text(encoding = "utf-8") == "print('probe')\n"


def test_only_the_brief_s_own_folder_is_emptied(rig: Rig) -> None:
    """
    In the dated archive a review holds what sits in its step folder and below it. An untracked file of another
    step, or at the archive's root, is not this scope's and stays where it is.
    """
    step   = "docs/reviews/2026-09-30-app/s1-core/step-2-review"
    folder = rig.repo / step
    other  = rig.repo / "docs" / "reviews" / "2026-09-30-app" / "s1-core" / "step-5-final"
    folder.mkdir(parents = True)
    (folder / "APP_REVIEW_S1_PROMPT.md").write_text("# brief\n", encoding = "utf-8")
    _git(rig.repo, "add", "-A")
    _git(rig.repo, "commit", "-q", "-m", "brief in the archive")
    _git(rig.repo, "push", "-q", "origin", "main")
    (folder / "APP_REVIEW_S1_REPORT.md").write_text("# report\n", encoding = "utf-8")
    (folder / "probe.py").write_text("print('probe')\n", encoding = "utf-8")
    (folder / "notes").mkdir()
    (folder / "notes" / "more.txt").write_text("more\n", encoding = "utf-8")
    other.mkdir()
    (other / "draft.md").write_text("# the next brief, not written yet\n", encoding = "utf-8")
    (rig.repo / "docs" / "reviews" / "loose.md").write_text("# loose\n", encoding = "utf-8")
    prepared = _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--brief",
        f"{step}/APP_REVIEW_S1_PROMPT.md",
        "--report",
        f"{step}/APP_REVIEW_S1_REPORT.md",
        "--codex-report",
        f"{step}/APP_REVIEW_S1_CODEX_REPORT.md",
        "--pin",
        "HEAD",
        "--prepare",
    )
    assert prepared.returncode == 0, prepared.stderr
    assert [path.name for path in folder.rglob("*") if path.is_file()] == ["APP_REVIEW_S1_PROMPT.md"]
    held = _hold(rig) / "held" / step
    assert (held / "probe.py").is_file() and (held / "notes" / "more.txt").is_file()
    assert (other / "draft.md").is_file()
    assert (rig.repo / "docs" / "reviews" / "loose.md").is_file()
    (folder / "APP_REVIEW_S1_CODEX_REPORT.md").write_text("# codex report\n", encoding = "utf-8")
    collected = _collect(rig)
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert (folder / "probe.py").read_text(encoding = "utf-8") == "print('probe')\n"
    assert (folder / "notes" / "more.txt").read_text(encoding = "utf-8") == "more\n"
    assert (folder / "APP_REVIEW_S1_REPORT.md").is_file()


def test_a_brief_at_the_archive_s_root_holds_the_root_s_own_files_alone(rig: Rig) -> None:
    """
    A flat archive keeps every review in one folder, and the folders below it are other reviews. A note beside the
    brief is held, a file one folder down is not.
    """
    archive = rig.repo / "docs" / "reviews"
    (archive / "REPORT.md").write_text("# report\n", encoding = "utf-8")
    (archive / "notes.txt").write_text("notes\n", encoding = "utf-8")
    (archive / "another").mkdir()
    (archive / "another" / "theirs.md").write_text("# theirs\n", encoding = "utf-8")
    assert _prepare(rig).returncode == 0
    assert _names(archive) == ["BRIEF.md", "another"]
    assert (archive / "another" / "theirs.md").is_file()
    _codex_writes_its_report(rig)
    assert _collect(rig).returncode == 0
    assert _names(archive) == ["BRIEF.md", "CODEX.md", "REPORT.md", "another", "notes.txt"]


def test_one_review_of_a_folder_at_a_time(rig: Rig) -> None:
    """
    While Codex's review is open, a Claude run and a second prepare are both exit 2, and claude never runs.
    """
    assert _prepare(rig).returncode == 0
    refused = _launch(rig, "--pin", "HEAD")
    assert refused.returncode == 2
    assert "one review of a folder at a time" in refused.stderr
    assert not rig.log.exists()
    assert _prepare(rig).returncode == 2


def test_collect_closes_a_claude_run_that_was_cut_off(rig: Rig) -> None:
    """
    A Claude run killed before it closed its review leaves it open. Collect puts the held report back and says so.
    """
    dead = subprocess.run(
        [str(BASH), "-c", "sleep 0 & child=$!; wait $child; echo $child"],
        capture_output = True,
        text = True,
        check = True,
    ).stdout.strip()
    held = _hold(rig) / "held" / "docs" / "reviews"
    held.mkdir(parents = True)
    (held / "CODEX.md").write_text("# codex report\n", encoding = "utf-8")
    opened = _hold(rig) / "open"
    opened.mkdir()
    meta = f"reviewer=claude\nreport=docs/reviews/REPORT.md\npid={dead}\n"
    (opened / "meta").write_text(meta, encoding = "utf-8", newline = "\n")
    (opened / "held").write_text("docs/reviews/CODEX.md\n", encoding = "utf-8", newline = "\n")
    done = _collect(rig)
    assert done.returncode == 6, done.stdout + done.stderr
    assert "cut off" in done.stderr
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").is_file()
    assert not opened.exists()


def test_a_fetch_during_a_review_is_not_held_against_the_reviewer(rig: Rig) -> None:
    """
    An editor's background fetch moves the remote tracking refs, which is not the reviewer's doing.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    _git(rig.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _collect(rig).returncode == 0


def test_a_checkpoint_codex_s_extension_writes_is_not_held_against_the_reviewer(rig: Rig) -> None:
    """
    Codex's editor extension writes a ref under ``refs/codex/`` each turn, a checkpoint of its own that points at a
    tree and that no branch, tag or push names. It is the editor's doing, not the reviewer's.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    checkpoint = "refs/codex/turn-diffs/checkpoints/2e10a5b6/87c38180/1790849086763/6b922ca8"
    _git(rig.repo, "update-ref", checkpoint, "HEAD^{tree}")
    assert _collect(rig).returncode == 0


@pytest.mark.parametrize("ref", ["refs/heads/sneaky", "refs/tags/sneaky", "refs/codexx/sneaky", "refs/notes/sneaky"])
def test_any_other_ref_made_during_a_review_is_still_contamination(rig: Rig, ref: str) -> None:
    """
    Only the remote tracking refs and Codex's own namespace are left out of the snapshot. A branch, a tag, a note
    or a ref beside ``refs/codex/`` that appears during a review fails it.
    """
    assert _prepare(rig).returncode == 0
    _codex_writes_its_report(rig)
    _git(rig.repo, "update-ref", ref, "HEAD")
    collected = _collect(rig)
    assert collected.returncode == 3, collected.stdout + collected.stderr
    assert "REFS" in collected.stderr


def test_a_pinned_dry_run_names_the_pin_and_opens_nothing(rig: Rig) -> None:
    """
    The dry run prints both lines and the pin, and opens no review.
    """
    done = _launch(rig, "--pin", "HEAD", "--codex-report", "docs/reviews/CODEX.md", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "Pin, " in done.stdout
    assert "Codex prompt, " in done.stdout
    assert not (_hold(rig) / "open").exists()
    assert not rig.log.exists()


def test_the_prepare_and_collect_arguments_are_checked_before_anything_runs(rig: Rig) -> None:
    """
    --prepare without the pin or the Codex report, one file for both reports, --collect with more than the repo, and
    --collect with no review open are all exit 2.
    """
    base = ["--repo", rig.repo.as_posix(), "--brief", "docs/reviews/BRIEF.md", "--report", "docs/reviews/REPORT.md"]
    assert _run(rig, *base, "--codex-report", "docs/reviews/CODEX.md", "--prepare").returncode == 2
    assert _run(rig, *base, "--pin", "HEAD", "--prepare").returncode == 2
    assert _run(rig, *base, "--codex-report", "docs/reviews/REPORT.md", "--pin", "HEAD", "--prepare").returncode == 2
    assert _run(rig, "--repo", rig.repo.as_posix(), "--collect", "--pin", "HEAD").returncode == 2
    assert _collect(rig).returncode == 2
    assert not rig.log.exists()
    assert not (_hold(rig) / "open").exists()


def _commit_and_push(rig: Rig, message: str) -> None:
    _git(rig.repo, "add", "-A")
    _git(rig.repo, "commit", "-q", "-m", message)
    _git(rig.repo, "push", "-q", "origin", "main")


def test_a_pin_origin_does_not_hold_is_refused(rig: Rig) -> None:
    """
    Every reviewer, Codex in the cloud and Sol read a pushed commit, so a pin only this folder holds is exit 2.
    """
    (rig.repo / "src" / "app.py").write_text("x = 3\n", encoding = "utf-8")
    _git(rig.repo, "commit", "-q", "-am", "not pushed")
    refused = _launch(rig, "--pin", "HEAD")
    assert refused.returncode == 2
    assert "Push it first" in refused.stderr
    assert not rig.log.exists()
    _git(rig.repo, "push", "-q", "origin", "main")
    assert _launch(rig, "--pin", "HEAD").returncode == 0


def test_a_brief_whose_scope_table_differs_from_the_pin_is_refused(rig: Rig) -> None:
    """
    The launcher measures the brief's line counts at the pin before a reviewer starts, and a stale count is exit 2.
    """
    brief = rig.repo / "docs" / "reviews" / "BRIEF.md"
    table = "# brief\n\n| Files | Lines |\n| --- | --- |\n| `src/app.py` | {n} |\n"
    brief.write_text(table.replace("{n}", "7"), encoding = "utf-8", newline = "\n")
    _commit_and_push(rig, "a brief with a stale count")
    refused = _launch(rig, "--pin", "HEAD")
    assert refused.returncode == 2
    assert "DIFFERS src/app.py, the brief says 7, the pin has 1" in refused.stderr
    assert not rig.log.exists()
    brief.write_text(table.replace("{n}", "1"), encoding = "utf-8", newline = "\n")
    _commit_and_push(rig, "the count measured")
    assert _launch(rig, "--pin", "HEAD").returncode == 0


def _cloud_branch(rig: Rig, branch: str, files: dict[str, str], base: str = "origin/main") -> None:
    """
    Push a branch the way Codex in the cloud hands its report back, the files committed on top of base in a clone.
    """
    cloud = rig.tmp / f"cloud-{branch.replace('/', '-')}"
    subprocess.run(
        ["git", "clone", "-q", (rig.tmp / "origin.git").as_posix(), str(cloud)],
        check = True,
        capture_output = True,
    )
    _git(cloud, "config", "user.email", "codex@example.com")
    _git(cloud, "config", "user.name", "Codex")
    _git(cloud, "config", "core.autocrlf", "false")
    _git(cloud, "checkout", "-q", "-b", branch, base)
    for name, text in files.items():
        target = cloud / name
        target.parent.mkdir(parents = True, exist_ok = True)
        target.write_text(text, encoding = "utf-8", newline = "\n")
    _git(cloud, "add", "-A")
    _git(cloud, "commit", "-q", "-m", "codex report")
    _git(cloud, "push", "-q", "origin", branch)


def _collect_branch(rig: Rig, branch: str) -> subprocess.CompletedProcess[str]:
    return _run(
        rig,
        "--repo",
        rig.repo.as_posix(),
        "--codex-report",
        "docs/reviews/CODEX.md",
        "--pin",
        "HEAD",
        "--collect-branch",
        branch,
    )


def test_a_cloud_report_comes_in_from_its_branch(rig: Rig) -> None:
    """
    Codex in the cloud read the pushed pin and committed its report on a branch. Collect writes only the report in.
    """
    _cloud_branch(rig, "codex/report", {"docs/reviews/CODEX.md": "# codex report\n", "docs/reviews/notes.md": "n\n"})
    done = _collect_branch(rig, "codex/report")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").read_text(encoding = "utf-8") == "# codex report\n"
    assert not (rig.repo / "docs" / "reviews" / "notes.md").exists()
    assert "Close its pull request unmerged" in done.stdout


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"docs/reviews/CODEX.md": "# report\n", "stray.txt": "hi\n"}, 3),
        ({"docs/reviews/CODEX.md": "# report\n", "src/app.py": "x = 2\n"}, 3),
        ({"docs/reviews/OTHER.md": "# not the report\n"}, 4),
    ],
)
def test_a_cloud_branch_that_does_more_than_report_brings_nothing_in(
    rig: Rig,
    files: dict[str, str],
    code: int,
) -> None:
    """
    A stray file or an edit on the branch is exit 3, a branch without the report is exit 4, and nothing is written.
    """
    _cloud_branch(rig, "codex/report", files)
    done = _collect_branch(rig, "codex/report")
    assert done.returncode == code, done.stdout + done.stderr
    assert not (rig.repo / "docs" / "reviews" / "CODEX.md").exists()


def test_a_cloud_branch_is_collected_only_onto_its_pin_and_never_over_a_report(rig: Rig) -> None:
    """
    A branch built on another commit, a missing branch, an open review and a report already in the folder are exit 2.
    """
    _cloud_branch(rig, "codex/old", {"docs/reviews/CODEX.md": "# old\n"})
    (rig.repo / "src" / "app.py").write_text("x = 5\n", encoding = "utf-8")
    _commit_and_push(rig, "the pin moved on")
    assert _collect_branch(rig, "codex/old").returncode == 2
    assert _collect_branch(rig, "codex/none").returncode == 2
    _cloud_branch(rig, "codex/new", {"docs/reviews/CODEX.md": "# new\n"})
    assert _prepare(rig).returncode == 0
    assert _collect_branch(rig, "codex/new").returncode == 2
    assert _collect(rig).returncode == 4
    shutil.rmtree(_hold(rig) / "open")
    (rig.repo / "docs" / "reviews" / "CODEX.md").write_text("# mine\n", encoding = "utf-8")
    assert _collect_branch(rig, "codex/new").returncode == 2
    assert (rig.repo / "docs" / "reviews" / "CODEX.md").read_text(encoding = "utf-8") == "# mine\n"


def test_a_report_that_does_not_show_what_it_read_is_warned_about(rig: Rig) -> None:
    """
    A header that names the pin and the files read first passes quietly, one that does not draws two warnings.
    """
    pin    = subprocess.run(
        ["git", "-C", str(rig.repo), "rev-parse", "HEAD"],
        capture_output = True,
        text = True,
        check = True,
    ).stdout.strip()
    header = f"# report\n\nPin read, `{pin[:10]}`. Read first, AGENTS.md, WORKFLOW.md, the brief.\n"
    _cloud_branch(rig, "codex/named", {"docs/reviews/CODEX.md": header})
    named = _collect_branch(rig, "codex/named")
    assert named.returncode == 0, named.stderr
    assert "warning" not in named.stderr
    (rig.repo / "docs" / "reviews" / "CODEX.md").unlink()
    _cloud_branch(rig, "codex/bare", {"docs/reviews/CODEX.md": "# report\n"})
    bare = _collect_branch(rig, "codex/bare")
    assert bare.returncode == 0
    assert "does not name the pin" in bare.stderr
    assert "does not list the files it read first" in bare.stderr


def _brief_tool(rig: Rig, command: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NODE), str(BRIEF), command, "--repo", rig.repo.as_posix(), "--pin", "HEAD", *args],
        capture_output = True,
        text = True,
        check = False,
    )


def test_the_brief_tool_counts_lines_at_the_pin_and_not_in_the_tree(rig: Rig) -> None:
    """
    A row per argument, the pin's line counts in the files' order, a last line without a newline counted, and an
    uncommitted edit ignored.
    """
    (rig.repo / "src" / "two.py").write_text("a\nb", encoding = "utf-8", newline = "\n")
    _commit_and_push(rig, "a second file")
    (rig.repo / "src" / "app.py").write_text("x = 1\ny = 2\nz = 3\n", encoding = "utf-8")
    done = _brief_tool(rig, "counts", "Code=src", "docs/**/*.md")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "| Code, `src/app.py`, `src/two.py` | 1, 2 |",
        "| `docs/reviews/BRIEF.md` | 1 |",
    ]
    assert _brief_tool(rig, "counts", "nope/*.py").returncode == 1


def test_the_brief_tool_checks_a_scope_table_and_states_the_commit(rig: Rig) -> None:
    """
    Matching rows pass, a stale count and a missing path fail, a placeholder row is skipped, and facts names the state
    the brief sits on and describes the pin as the commit that adds the brief, since no commit holds its own hash.
    """
    brief = rig.tmp / "brief.md"
    good  = "| Files | Lines |\n| --- | --- |\n| `src/app.py` | 1 |\n| Tests, `src`, `docs` | 2 |\n| {`p`} | {n} |\n"
    brief.write_text(good, encoding = "utf-8", newline = "\n")
    passed = _brief_tool(rig, "check", brief.as_posix())
    assert passed.returncode == 0, passed.stdout
    assert "skip" in passed.stdout
    brief.write_text(good + "| `src/gone.py` | 4 |\n| `docs/reviews/BRIEF.md` | 9 |\n", encoding = "utf-8")
    failed = _brief_tool(rig, "check", brief.as_posix())
    assert failed.returncode == 1
    assert "MISSING at the pin, src/gone.py" in failed.stdout
    assert "DIFFERS docs/reviews/BRIEF.md, the brief says 9, the pin has 1" in failed.stdout
    state = subprocess.run(
        ["git", "-C", str(rig.repo), "rev-parse", "HEAD"],
        capture_output = True,
        text = True,
        check = True,
    ).stdout.strip()
    facts = _brief_tool(rig, "facts")
    assert f"state   {state}" in facts.stdout
    assert (
        "The pin is the commit that adds this brief and nothing else, on top of the slice's state "
        f"`{state[:10]}`, on branch `main`, which sits on `main` at `{state[:10]}`."
    ) in facts.stdout


def _retro_tool(folder: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NODE), str(RETRO), str(folder)],
        capture_output = True,
        text = True,
        check = False,
    )


def test_the_retro_tool_counts_findings_escapes_minutes_and_missing_answers() -> None:
    """
    On the fixture slice, every source in the order the review ran, the deferred finding counted as agreed, the escapes
    (a Sol and a final finding in the step 2 tree) and the one marked unsure left out, a run past midnight, both ways of
    writing tokens and an unknown one, and the Sol dispatch whose answer is not archived. The same files print the same.
    """
    done = _retro_tool(RETRO_SLICE)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    for row in (
        "| Step 1, orchestrator | step 1 | 1 | 1 | 0 | 0 | 0 | - |",
        "| Step 2, Claude | step 2 | 2 | 2 | 0 | 0 | 1 | - |",
        "| Step 2, Codex | step 2 | 1 | 0 | 1 | 0 | 0 | - |",
        "| Sol R1, dispatch 1 | Sol | 1 | 1 | 0 | 0 | 1 | 1 |",
        "| Step 5 final, Claude | final | 1 | 1 | 0 | 0 | 1 | 1 |",
        "| Step 5 final, Codex | final | 1 | 1 | 0 | 0 | 0 | 0 |",
        "| All | | 7 | 6 | 1 | 0 | 3 | 2 |",
        "| round-1 | 2 | 1 | `EX_REVIEW_S1_SOL_R1_D2_PROMPT.md` |",
    ):
        assert row in lines, f"missing {row!r} in\n{done.stdout}"
    reports: dict[str, list[str]] = {}
    for line in lines:
        if line.startswith("| step-"):
            row = [cell.strip() for cell in line.strip().strip("|").split("|")]
            reports[row[1]] = row[2:]
    codex  = "`EX_REVIEW_S1_CODEX_REPORT.md`"
    final  = "`EX_REVIEW_S1_FINAL_REPORT.md`"
    claude = "`EX_REVIEW_S1_REPORT.md`"
    fable  = "claude-fable-5-1, Claude Code, effort max."
    assert sorted(reports) == [codex, final, claude], "a brief or another file was read as a report"
    assert reports[codex] == ["gpt-5.5-codex, Codex in VS Code, effort high.", "45", "unknown", "unknown"]
    assert reports[claude] == [fable, "42", "1,204,000", "38,500"]
    assert reports[final] == [fable, "90", "900,000", "41,000"]
    assert (
        "Escapes, agreed findings in the step 2 tree that a later source found, 2 of 3 (67%), `EX-S1-D1-R1-1`, "
        "`EX-S1-FIN-1`. 1 more agreed finding is marked unsure at the step 2 pin and is not counted."
    ) in lines
    assert any(line.startswith("1 Sol dispatch(es) without an archived answer") for line in lines)
    assert _retro_tool(RETRO_SLICE).stdout == done.stdout


def test_the_retro_tool_refuses_a_folder_without_a_key_or_a_key_it_does_not_know(tmp_path: Path) -> None:
    """
    Exit 2 and no table when there is no answer key, and when the key's findings table has columns other than the
    template's, rather than counting from a table it would have to guess at.
    """
    empty = _retro_tool(tmp_path)
    assert empty.returncode == 2
    assert "no answer key" in empty.stderr
    assert not empty.stdout
    slice_ = tmp_path / "s1-example"
    shutil.copytree(RETRO_SLICE, slice_)
    key = slice_ / "EX_REVIEW_S1_ANSWER_KEY.md"
    key.write_text(key.read_text(encoding = "utf-8").replace("| Needs |", "| Needed |"), encoding = "utf-8")
    unknown = _retro_tool(slice_)
    assert unknown.returncode == 2
    assert "this tool reads only" in unknown.stderr
    assert not unknown.stdout


def _report_minutes(stdout: str) -> dict[str, str]:
    minutes: dict[str, str] = {}
    for line in stdout.splitlines():
        if line.startswith("| step-"):
            row = [cell.strip() for cell in line.strip().strip("|").split("|")]
            minutes[row[1]] = row[3]
    return minutes


def _set_time_spent(report: Path, line: str) -> None:
    text = report.read_text(encoding = "utf-8")
    old  = next(row for row in text.splitlines() if row.startswith("- **Time spent.**"))
    report.write_text(text.replace(old, "- **Time spent.** " + line), encoding = "utf-8")


def test_the_retro_tool_reads_a_stated_duration_marked_and_leaves_words_unknown(tmp_path: Path) -> None:
    """
    Reports written before the template asked for the clock state a duration. One in digits prints converted to minutes
    and marked stated, an estimate a reader tells apart from a clock. One in words prints unknown. A line that gives the
    clock and also a stated duration prints the clock.
    """
    slice_ = tmp_path / "s1-example"
    shutil.copytree(RETRO_SLICE, slice_)
    _set_time_spent(slice_ / "step-2-review" / "EX_REVIEW_S1_CODEX_REPORT.md", "0.6 hours.")
    _set_time_spent(slice_ / "step-2-review" / "EX_REVIEW_S1_REPORT.md", "About three hours.")
    _set_time_spent(
        slice_ / "step-5-final" / "EX_REVIEW_S1_FINAL_REPORT.md",
        "From 2026-10-02T14:00:00-05:00 to 2026-10-02T15:30:00-05:00, about 2 hours by my estimate.",
    )
    done = _retro_tool(slice_)
    assert done.returncode == 0, done.stderr
    minutes = _report_minutes(done.stdout)
    assert minutes["`EX_REVIEW_S1_CODEX_REPORT.md`"] == "36 stated"
    assert minutes["`EX_REVIEW_S1_REPORT.md`"] == "unknown"
    assert minutes["`EX_REVIEW_S1_FINAL_REPORT.md`"] == "90"
    assert "A number marked stated is the duration the report wrote, an estimate and not a clock" in done.stdout


def test_the_retro_tool_places_a_late_orchestrator_finding_and_shows_how_it_read_each_source(tmp_path: Path) -> None:
    """
    An orchestrator's finding made after the pin reads as after step 2 and counts as an escape, it is not taken for a
    step 1 one. A source the tool cannot place reads as unplaced, sorts last and still counts as an escape, so a wording
    the tool does not know never hides one. The Read as column shows both in the retrospective itself.
    """
    slice_ = tmp_path / "s1-example"
    shutil.copytree(RETRO_SLICE, slice_)
    key   = slice_ / "EX_REVIEW_S1_ANSWER_KEY.md"
    text  = key.read_text(encoding = "utf-8")
    late  = (
        "| EX-S1-47 | Orchestrator, after step 2 | claude-fable-5-1 | M | no | Agreed | `src/h.py:5` "
        "| before the review | `ggggggg` | yes | read the file at the pin | the repo alone | A late find. | section 8 |"
    )
    odd   = (
        "| EX-S1-X1 | The owner, by hand | owner | E | no | Agreed | `src/i.py:1` | before the review | `hhhhhhh` "
        "| yes | read the file at the pin | the repo alone | An unplaced find. | section 8 |"
    )
    first = next(row for row in text.splitlines() if row.startswith("| EX-S1-D1-R1-1 |"))
    key.write_text(text.replace(first, late + "\n" + odd + "\n" + first), encoding = "utf-8")
    done = _retro_tool(slice_)
    assert done.returncode == 0, done.stderr
    lines    = done.stdout.splitlines()
    late_row = "| Orchestrator, after step 2 | after step 2 | 1 | 1 | 0 | 0 | 1 | 1 |"
    odd_row  = "| The owner, by hand | unplaced | 1 | 1 | 0 | 0 | 1 | 1 |"
    sol_row  = "| Sol R1, dispatch 1 | Sol | 1 | 1 | 0 | 0 | 1 | 1 |"
    for row in (late_row, odd_row, sol_row, "| All | | 9 | 8 | 1 | 0 | 5 | 4 |"):
        assert row in lines, f"missing {row!r} in\n{done.stdout}"
    assert lines.index("| Step 2, Codex | step 2 | 1 | 0 | 1 | 0 | 0 | - |") < lines.index(late_row)
    assert lines.index(late_row) < lines.index(sol_row)
    assert lines[lines.index(odd_row) + 1].startswith("| All |"), "an unplaced source sorts last"
    assert any(line.startswith("Escapes, agreed findings in the step 2 tree that a later source found, 4 of 5 (80%)")
               for line in lines)


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


def _matcher_without_the_read_tools(settings: dict) -> None:
    """
    The matcher every machine carried before the guard read Read, Grep and Glob calls.
    """
    matcher = settings["hooks"]["PreToolUse"][0]["matcher"]
    settings["hooks"]["PreToolUse"][0]["matcher"] = matcher.replace("Read|Grep|Glob|", "")


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
        (_matcher_without_the_read_tools, "Read, Grep, Glob"),
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
