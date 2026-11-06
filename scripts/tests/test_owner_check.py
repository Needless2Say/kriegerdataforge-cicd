"""
Contract tests for the owner check, `_authorize-owner.yml`, and every workflow that calls it.

A rerun keeps `github.actor`, the one who started the run, and sets `github.triggering_actor` to the one who reran it.
So the check admits a run only when both are the repository's owner, and the owner's rerun of a run another started
stays denied. A rerun of failed jobs alone keeps a passed check's output, so every job after the check tests both
actors in its own condition too. The check's own shell runs here under bash, its environment resolved from the step's
own expressions, so a check that reads the wrong actor fails here.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT        = Path(__file__).resolve().parents[2]
WORKFLOWS   = ROOT / ".github" / "workflows"
CHECK       = "_authorize-owner.yml"
CALL        = f"./.github/workflows/{CHECK}"
OWNER       = "Needless2Say"
BOTH        = (
    "github.actor == github.repository_owner",
    "github.triggering_actor == github.repository_owner",
)
NEWLY_GATED = ("hub-prune-tokens.yml", "trigger-reports-triage.yml", "check-secret-expiry.yml")
CICD        = "Needless2Say/kriegerdataforge-cicd"
TOKEN       = re.compile(
    r"\s*(?:(?P<text>'(?:[^']|'')*')|(?P<op>&&|\|\||==|!=|!|\(|\))|(?P<call>[a-z]+\(\))|(?P<name>[A-Za-z_][\w.\-]*))",
)
OPERATORS   = {"&&": " and ", "||": " or ", "==": " == ", "!=": " != ", "(": "(", ")": ")"}
STATUS      = {"always()": "True", "success()": "True", "failure()": "False", "cancelled()": "False"}


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_bytes().decode("utf-8"))


def _callers() -> list[str]:
    return sorted(
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if path.name != CHECK and CALL in path.read_text(encoding = "utf-8")
    )


def _bash() -> str | None:
    """
    A bash that runs the step's shell here. Git's on Windows, System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def _resolve(value: str, context: dict[str, str]) -> str:
    def one(match: re.Match[str]) -> str:
        return context[match.group(1).strip()]


    return re.sub(r"\$\{\{(.+?)\}\}", one, value)


def _run_check(tmp_path: Path, actor: str, triggering_actor: str) -> tuple[int, str]:
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the check's shell")
    step    = _load(CHECK)["jobs"]["verify"]["steps"][0]
    context = {
        "github.actor": actor,
        "github.triggering_actor": triggering_actor,
        "github.repository_owner": OWNER,
    }
    script  = tmp_path / "check.sh"
    script.write_text(step["run"], encoding = "utf-8", newline = "\n")
    output = tmp_path / "output"
    env    = {
        **os.environ,
        **{name: _resolve(str(value), context) for name, value in step["env"].items()},
        "GITHUB_OUTPUT": output.as_posix(),
        "GITHUB_STEP_SUMMARY": (tmp_path / "summary").as_posix(),
    }
    run    = subprocess.run([bash, "-e", script.as_posix()], env = env, capture_output = True, text = True)
    return run.returncode, output.read_text(encoding = "utf-8") if output.exists() else ""


@pytest.mark.parametrize(("actor", "triggering_actor"), [
    (OWNER, OWNER),
    ("needless2say", "NEEDLESS2SAY"),
])
def test_the_check_admits_the_owner_as_both_actors(tmp_path, actor, triggering_actor):
    code, output = _run_check(tmp_path, actor, triggering_actor)
    assert code == 0
    assert "authorized=true" in output


@pytest.mark.parametrize(("actor", "triggering_actor"), [
    ("github-actions[bot]", OWNER),
    ("a-stranger", OWNER),
    (OWNER, "a-stranger"),
    ("", OWNER),
    (OWNER, ""),
])
def test_the_check_denies_a_run_either_actor_of_which_is_not_the_owner(tmp_path, actor, triggering_actor):
    code, output = _run_check(tmp_path, actor, triggering_actor)
    assert code != 0
    assert "authorized=true" not in output


def test_the_callers_are_found():
    assert len(_callers()) >= 14, _callers()


@pytest.mark.parametrize("workflow", NEWLY_GATED)
def test_a_manual_run_of_each_newly_gated_workflow_calls_the_check(workflow):
    jobs   = _load(workflow)["jobs"]
    checks = [job for job in jobs.values() if job.get("uses") == CALL]
    assert len(checks) == 1, f"{workflow} calls the owner check once"
    assert checks[0]["if"] == "github.event_name == 'workflow_dispatch'", "the schedule's path stays unchanged"


@pytest.mark.parametrize("workflow", _callers())
def test_the_check_inherits_no_write_from_its_caller(workflow):
    # a called workflow's job may hold what its caller's job holds, so the call names its own or inherits a read
    data = _load(workflow)
    for job in data["jobs"].values():
        if job.get("uses") != CALL or "permissions" in job:
            continue
        granted = data.get("permissions", {})
        assert isinstance(granted, dict), f"{workflow} grants {granted!r} to the owner check"
        assert "write" not in granted.values(), f"{workflow} grants {granted} to the owner check"


def test_the_repo_provisioner_calls_the_shared_check_rather_than_its_own():
    jobs   = _load("issue-create-repo.yml")["jobs"]
    checks = [job for job in jobs.values() if job.get("uses") == CALL]
    assert len(checks) == 1, "issue-create-repo.yml calls the owner check"
    assert "github.event.label.name == 'new-repo'" in checks[0]["if"]
    assert "github.triggering_actor }}" not in yaml.safe_dump(jobs), "no check of its own reads one actor alone"


@pytest.mark.parametrize("workflow", _callers())
def test_every_job_after_the_check_tests_both_actors_itself(workflow):
    for name, job in _load(workflow)["jobs"].items():
        if job.get("uses") == CALL:
            continue
        condition = str(job.get("if", ""))
        for comparison in BOTH:
            assert comparison in condition, f"{workflow} job {name} must test {comparison} in its own if"

# ======================================================================================================================
# Each job's condition evaluated, as GitHub evaluates it, for every way a run starts or is rerun
# ======================================================================================================================

class Text(str):
    """
    A string compared as GitHub's expressions compare two strings, case blind.
    """
    def __eq__(self, other: object) -> bool:
        return isinstance(other, str) and self.lower() == other.lower()


    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


    def __hash__(self) -> int:
        return hash(self.lower())


def _evaluate(condition: str, values: dict[str, str]) -> bool:
    """
    Whether a job's `if` holds, as GitHub reads its value.
    """
    return bool(expression_value(condition, values))


def expression_value(condition: str, values: dict[str, str]) -> str | bool:
    """
    The value of an expression built from the operators these workflows use, a name GitHub would leave empty read as
    '', and `&&` and `||` giving an operand as GitHub's do.
    """
    text   = condition.strip()
    text   = text[3:-2] if text.startswith("${{") and text.endswith("}}") else text
    source = []
    at     = 0
    while text[at:].strip():
        token = TOKEN.match(text, at)
        assert token is not None, f"cannot read {text[at:]!r}"
        at = token.end()
        if token["text"] is not None:
            source.append(f"Text({token['text'][1:-1].replace(chr(39) * 2, chr(39))!r})")
        elif token["op"] is not None:
            # a `not` binds looser than `==` in Python, unlike GitHub's `!`, so a condition holding one is refused here
            assert token["op"] != "!", f"the evaluator does not read ! in {condition!r}"
            source.append(OPERATORS[token["op"]])
        elif token["call"] is not None:
            source.append(STATUS[token["call"]])
        else:
            source.append(f"value({token['name']!r})")
    names = {"value": lambda name: Text(values.get(name, ""))}
    return eval("".join(source), {"__builtins__": {}, "Text": Text}, names)


def _values(workflow: str, event: str, attempt: str, actor: str, triggering_actor: str) -> dict[str, str]:
    jobs   = _load(workflow)["jobs"]
    values = {
        "github.event_name": event,
        "github.run_attempt": attempt,
        "github.actor": actor,
        "github.triggering_actor": triggering_actor,
        "github.repository_owner": OWNER,
        "github.repository": CICD,
        "github.event.label.name": "new-repo",
    }
    for name, job in jobs.items():
        checked = job.get("uses") == CALL
        skipped = checked and event == "schedule"
        values[f"needs.{name}.result"] = "skipped" if skipped else "success"
        if checked and not skipped:
            # the check passed on an earlier attempt, and a rerun of failed jobs alone keeps its output
            values[f"needs.{name}.outputs.authorized"] = "true"
    return values


def _guarded_jobs(workflow: str) -> list[tuple[str, str]]:
    data = _load(workflow)
    return [(name, str(job.get("if", "true"))) for name, job in data["jobs"].items() if job.get("uses") != CALL]


def _events(workflow: str) -> list[str]:
    # the YAML reader takes the key `on` for True
    data = _load(workflow)
    return list((data.get("on") or data.get(True) or {}).keys())


def _arm(values: dict[str, str], condition: str) -> dict[str, str]:
    # every arm switch a schedule path reads is on, so the attempt alone decides
    for name in re.findall(r"vars\.\w+", condition):
        values[name] = "true"
    return values


@pytest.mark.parametrize("workflow", _callers())
def test_no_job_runs_when_another_login_reruns_or_triggers_a_run(workflow):
    for event in _events(workflow):
        for actor, triggering_actor in (
            (OWNER, "github-actions[bot]"),
            ("github-actions[bot]", OWNER),
            ("a-stranger", "a-stranger"),
        ):
            # the scheduler's own first attempt has no human actor and runs unattended, the next test's case
            for attempt in ("2", "3") if event == "schedule" else ("1", "2", "3"):
                for name, condition in _guarded_jobs(workflow):
                    values = _arm(_values(workflow, event, attempt, actor, triggering_actor), condition)
                    assert not _evaluate(condition, values), (
                        f"{workflow} job {name} runs on {event} attempt {attempt} by {actor} and {triggering_actor}"
                    )


@pytest.mark.parametrize("workflow", [name for name in _callers() if "schedule" in _events(name)])
def test_a_schedules_first_attempt_runs_unattended_and_the_owners_rerun_runs_too(workflow):
    for name, condition in _guarded_jobs(workflow):
        first = _arm(_values(workflow, "schedule", "1", "github-actions[bot]", "github-actions[bot]"), condition)
        assert _evaluate(condition, first), f"{workflow} job {name} skips its own schedule"
        rerun = _arm(_values(workflow, "schedule", "2", OWNER, OWNER), condition)
        assert _evaluate(condition, rerun), f"{workflow} job {name} skips the owner's rerun"


def test_the_evaluator_reads_the_operators_as_github_does():
    values = {"github.actor": "Needless2Say", "github.repository_owner": "needless2say"}
    assert _evaluate("github.actor == github.repository_owner", values), "a comparison is case blind"
    assert not _evaluate("github.actor != github.repository_owner", values)
    assert _evaluate("${{ always() && (false_name == '' || x == 'y') }}", values)
    assert not _evaluate("github.missing == 'a' && always()", values)
