"""
Contract tests for where the ops workflows read their secrets.

The issue triggered reports triage parses the untrusted issue body in a job that holds no secret and names no
environment, and reads the cron copies in another job that names the environment the parse chose, so the copies can
live in cicd's `dev` and `prod`. The hub prune fails when an environment's credentials are absent, so a prune that
never ran is never green. Its step's shell runs here under bash.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
BODY      = "github.event.issue.body"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_bytes().decode("utf-8"))


def _bash() -> str | None:
    """
    A bash that runs the step's shell here. Git's on Windows, System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def _text(job: dict) -> str:
    return yaml.safe_dump(job, width = 10_000)


def test_the_triage_parses_the_issue_in_a_job_with_no_secret_and_fires_in_the_chosen_environment():
    jobs    = _load("ops-triage-reports.yml")["jobs"]
    parsers = [name for name, job in jobs.items() if BODY in _text(job)]
    firers  = [name for name, job in jobs.items() if "secrets.REPORTS_CRON_SECRET_" in _text(job)]
    assert len(parsers) == 1 and len(firers) == 1 and parsers != firers
    parse, fire = jobs[parsers[0]], jobs[firers[0]]
    assert "secrets." not in _text(parse), "the job that reads the untrusted body holds no secret"
    assert "environment" not in parse
    assert parse.get("permissions") == {}, "the parse job needs no token"
    assert BODY not in _text(fire), "the job that holds the cron copies never reads the issue body"
    assert fire["environment"] == "${{ needs.%s.outputs.environment }}" % parsers[0]
    assert parsers[0] in fire["needs"]


def _registry() -> list[dict]:
    return json.loads((ROOT / "scripts" / "secret_registry.json").read_text(encoding = "utf-8"))["secrets"]


def test_every_secret_the_hub_prune_reads_has_a_registry_entry_of_its_own():
    text  = (WORKFLOWS / "hub-prune-tokens.yml").read_text(encoding = "utf-8")
    names = sorted(set(re.findall(r"secrets\.([A-Z0-9_]+)", text)))
    assert names == ["KDF_HUB_CRON_SECRET_DEV", "KDF_HUB_CRON_SECRET_PROD", "KDF_HUB_URL_DEV", "KDF_HUB_URL_PROD"]
    entries = {entry["name"]: entry for entry in _registry()}
    for name in names:
        # one entry per value, so a paste writes one environment's value and never the other's
        targets = entries[name]["github_repo_secrets"]
        assert targets == [{"repo": "Needless2Say/kriegerdataforge-cicd", "secret_name": name}]
        assert entries[name]["kind"] == "paste"


def test_the_npm_token_is_recorded_as_a_read_alone():
    entry = next(entry for entry in _registry() if entry["name"] == "GH_NPM_TOKEN")
    assert entry["scopes"] == ["read:packages"]


def _provisioner_steps() -> dict[str, str]:
    jobs = _load("issue-create-repo.yml")["jobs"]
    return {step["name"]: step.get("run", "") for step in jobs["create-repo"]["steps"]}


@pytest.mark.parametrize("environment", ["prod", "dev"])
def test_the_provisioner_holds_each_environment_to_main_and_asks_for_no_reviewer(environment):
    steps = _provisioner_steps()
    run   = next(run for name, run in steps.items() if f"environments/{environment}\"" in run)
    assert "reviewers" not in run and "OWNER_ID" not in run
    assert '"custom_branch_policies": true' in run and '"protected_branches": false' in run
    assert f"environments/{environment}/deployment-branch-policies" in run
    assert '-f name="main"' in run and '-f type="branch"' in run


def test_the_provisioners_comment_sends_the_owner_to_the_registries_and_a_rotation():
    comment = _provisioner_steps()["Post completion comment"]
    for gone in ("Collaborator", "add friend", "approval gate", "Required reviewers"):
        assert gone not in comment
    for named in (
        "scripts/deployer_registry.json",
        "scripts/secret_registry.json",
        "VERCEL_DEPLOYMENT_TOKEN",
        "KDF_APP_ID",
        "Rotate Vercel Deployment Token",
    ):
        assert named in comment


def _prune_step() -> dict:
    return _load("hub-prune-tokens.yml")["jobs"]["prune"]["steps"][0]


@pytest.mark.parametrize(("hub_url", "cron_secret"), [("", ""), ("https://hub.invalid", ""), ("", "a-value")])
def test_the_hub_prune_fails_when_an_environment_has_no_credentials(tmp_path, hub_url, cron_secret):
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    script = tmp_path / "prune.sh"
    script.write_text(_prune_step()["run"], encoding = "utf-8", newline = "\n")
    env = {
        **os.environ,
        "ENVIRONMENT": "dev",
        "HUB_URL": hub_url,
        "CRON_SECRET": cron_secret,
        "GITHUB_STEP_SUMMARY": (tmp_path / "summary").as_posix(),
    }
    run = subprocess.run([bash, script.as_posix()], env = env, capture_output = True, text = True, cwd = tmp_path)
    assert run.returncode != 0, run.stdout + run.stderr
    assert "::error::" in run.stdout
