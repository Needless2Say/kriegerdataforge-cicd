"""
Contract tests that the deploy workflows put no secret into a command's arguments, where a process listing on the
runner reads it.

The packages token reaches git through `GIT_CONFIG_COUNT` and its key in the step's environment, as
`fetch-private-packages.yml` gives it, never through `git config` on a command line or a global config file. The
deployment protection's bypass value reaches curl as a header file the smoke step writes and deletes, never as a
`-H` argument. The Vercel token stays on the CLI's `--token` until a probe on the pinned CLI shows its environment
route honoured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPLOYS   = ("cd-python-vercel.yml", "cd-nextjs-vercel.yml")


def _steps(workflow: str) -> list[dict]:
    jobs = yaml.safe_load((WORKFLOWS / workflow).read_bytes().decode("utf-8"))["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


def _step(workflow: str, name: str) -> dict:
    return next(step for step in _steps(workflow) if step.get("name") == name)


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_no_step_writes_a_credential_into_git_config_on_a_command_line(workflow):
    for step in _steps(workflow):
        run = str(step.get("run", ""))
        assert "git config" not in run or "@github.com" not in run, f"{workflow} step {step.get('name')}"


def test_the_python_install_hands_git_the_packages_token_through_its_environment():
    step = _step("cd-python-vercel.yml", "Install Python dependencies")
    env  = step["env"]
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "${{ format('url.https://__token__:{0}@github.com/.insteadOf', secrets.GH_PACKAGES_PAT) }}"
    assert env["GIT_CONFIG_VALUE_0"] == "https://github.com/"
    assert "GH_PACKAGES_PAT" not in step["run"]


def test_the_smoke_sends_the_bypass_value_from_a_header_file_it_deletes():
    run = _step("cd-python-vercel.yml", "Smoke the new deployment before it serves")["run"]
    assert "x-vercel-protection-bypass: $BYPASS\"" not in run.replace("'", '"')
    assert '-H "@$BYPASS_HEADER"' in run
    assert "umask 077" in run
    assert "trap 'rm -f \"$BYPASS_HEADER\"' EXIT" in run
