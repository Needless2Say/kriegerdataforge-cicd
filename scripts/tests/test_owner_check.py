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

ROOT       = Path(__file__).resolve().parents[2]
WORKFLOWS  = ROOT / ".github" / "workflows"
CHECK      = "_authorize-owner.yml"
CALL       = f"./.github/workflows/{CHECK}"
OWNER      = "Needless2Say"
BOTH       = (
    "github.actor == github.repository_owner",
    "github.triggering_actor == github.repository_owner",
)
NEWLY_GATED = ("hub-prune-tokens.yml", "trigger-reports-triage.yml", "check-secret-expiry.yml")


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
    output  = tmp_path / "output"
    env     = {
        **os.environ,
        **{name: _resolve(str(value), context) for name, value in step["env"].items()},
        "GITHUB_OUTPUT": output.as_posix(),
        "GITHUB_STEP_SUMMARY": (tmp_path / "summary").as_posix(),
    }
    run     = subprocess.run([bash, "-e", script.as_posix()], env = env, capture_output = True, text = True)
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
