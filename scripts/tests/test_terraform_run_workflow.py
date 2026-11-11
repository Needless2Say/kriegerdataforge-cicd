"""
Contract tests for .github/workflows/terraform-run.yml, the reusable terraform workflow (terraform in Actions, design
5.6 to 5.8).

The workflow is read as YAML and as text. Its switch rule runs as a real shell with each mode and switch, so the rule
is tested as it runs and not as it reads. Nothing here reaches GitHub or Terraform.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "terraform-run.yml"
MODES    = ("apply", "gate-plan", "deploy", "validate", "recovery", "repair", "acceptance")
PINNED   = re.compile(r"[^@\s]+@[0-9a-f]{40}")


@pytest.fixture(scope = "module")
def text() -> str:
    """
    The workflow's text.
    """
    return WORKFLOW.read_text(encoding = "utf-8")


@pytest.fixture(scope = "module")
def flow(text: str) -> dict:
    """
    The workflow parsed, PyYAML reading the key on as True.
    """
    return yaml.safe_load(text)


def _steps(flow: dict, job: str) -> list[dict]:
    """
    A job's steps.
    """
    return flow["jobs"][job]["steps"]


def _index(steps: list[dict], name: str) -> int:
    """
    The position of the first step whose name holds the words given.
    """
    for i, step in enumerate(steps):
        if name in step.get("name", ""):
            return i
    raise AssertionError(f"no step named {name!r}")


def _bash() -> str | None:
    """
    A bash to run a step's shell, Git Bash on Windows.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")

# ======================================================================================================================
# The interface
# ======================================================================================================================

class TestInterface:
    """
    A reusable workflow alone, its inputs the contract the terraform repo's callers meet.
    """
    def test_it_is_called_and_never_triggered(self, flow):
        assert list(flow[True]) == ["workflow_call"]


    @pytest.mark.parametrize("name", [
        "mode", "environment", "release", "expected_commit", "release_floor", "terraform_version",
    ])
    def test_each_required_input_is_a_string(self, flow, name):
        spec = flow[True]["workflow_call"]["inputs"][name]
        assert spec["required"] is True
        assert spec["type"] == "string"


    def test_every_mode_is_named_in_the_mode_inputs_description(self, flow):
        description = flow[True]["workflow_call"]["inputs"]["mode"]["description"]
        for mode in MODES:
            assert mode in description


    def test_the_workflow_grants_nothing_itself(self, flow):
        assert flow["permissions"] == {}


    def test_every_action_is_pinned_to_a_commit(self, text):
        for line in text.splitlines():
            match = re.match(r"\s*(?:-\s*)?uses:\s*(\S+)", line)
            if match and not match.group(1).startswith("./"):
                assert PINNED.fullmatch(match.group(1)), f"an action not pinned to a commit: {line.strip()}"

# ======================================================================================================================
# The jobs
# ======================================================================================================================

class TestJobs:
    """
    The deployer and switch check holding nothing, then one job in the environment.
    """
    def test_the_authorize_job_holds_no_environment_and_reads_alone(self, flow):
        job = flow["jobs"]["authorize"]
        assert "environment" not in job
        assert job["permissions"] == {"contents": "read"}


    def test_the_run_job_is_in_the_environment_after_the_check(self, flow):
        job = flow["jobs"]["run"]
        assert job["environment"] == "${{ inputs.environment }}"
        assert job["needs"] == "authorize"
        assert job["if"] == "github.actor == github.triggering_actor"


    def test_the_run_job_takes_its_environments_group_with_cancellation_off(self, flow):
        assert flow["jobs"]["run"]["concurrency"] == {
            "group": "terraform-${{ inputs.environment }}",
            "cancel-in-progress": False,
        }


    def test_the_run_job_ends_before_githubs_six_hours(self, flow):
        assert 0 < flow["jobs"]["run"]["timeout-minutes"] <= 330


    def test_the_run_job_grants_exactly_what_it_uses(self, flow):
        assert flow["jobs"]["run"]["permissions"] == {"contents": "read", "actions": "read", "deployments": "write"}

# ======================================================================================================================
# The switch, run as a shell
# ======================================================================================================================

def _switch(flow: dict, mode: str, target: str, dev: str, prod: str, tmp_path: Path) -> int:
    """
    The authorize job's switch step run in bash with the given mode, environment and switch variables.
    """
    shell = _bash()
    if shell is None:
        pytest.skip("no bash to run the step's shell")
    steps  = _steps(flow, "authorize")
    script = steps[_index(steps, "switch")]["run"]
    (tmp_path / "step.sh").write_text(script, encoding = "utf-8", newline = "\n")
    env = {**os.environ, "MODE": mode, "TARGET": target, "SWITCH_DEV": dev, "SWITCH_PROD": prod}
    return subprocess.run(
        [shell, "step.sh"],
        cwd = tmp_path,
        env = env,
        capture_output = True,
        check = False,
    ).returncode


class TestTheSwitch:
    """
    Each mode held to its environment's switch in this workflow as well as its caller (Round Table 78, L2).
    """
    @pytest.mark.parametrize("mode, target, dev, prod, allowed", [
        ("apply", "dev", "true", "", True),
        ("apply", "dev", "", "", False),
        ("apply", "dev", "false", "", False),
        ("apply", "prod", "true", "true", False),
        ("gate-plan", "prod", "", "true", True),
        ("gate-plan", "prod", "", "", False),
        ("gate-plan", "dev", "true", "true", False),
        ("deploy", "prod", "", "true", True),
        ("deploy", "prod", "true", "", False),
        ("deploy", "dev", "true", "true", False),
        ("validate", "dev", "", "", True),
        ("validate", "prod", "", "false", True),
        ("validate", "dev", "true", "", False),
        ("repair", "prod", "", "", True),
        ("repair", "prod", "", "true", False),
        ("recovery", "dev", "true", "", True),
        ("recovery", "prod", "", "", True),
        ("acceptance", "dev", "", "", True),
        ("acceptance", "dev", "true", "", True),
        ("acceptance", "prod", "", "", False),
        ("plan", "dev", "true", "", False),
        ("apply", "staging", "true", "true", False),
    ])
    def test_each_mode_against_its_switch(self, flow, tmp_path, mode, target, dev, prod, allowed):
        code = _switch(flow, mode, target, dev, prod, tmp_path)
        assert (code == 0) is allowed

# ======================================================================================================================
# The run job's order and its guards
# ======================================================================================================================

class TestTheRunJob:
    """
    The checkout held to the resolved commit first, the backend's identity and the seal before what rests on them.
    """
    def test_the_checkout_is_the_expected_commit_without_its_credentials(self, flow):
        first = next(s for s in _steps(flow, "run") if str(s.get("uses", "")).startswith("actions/checkout@"))
        assert first["with"]["ref"] == "${{ inputs.expected_commit }}"
        assert first["with"]["persist-credentials"] is False


    def test_the_run_job_holds_the_switch_first_on_every_execution_word_for_word(self, flow):
        # a rerun of failed jobs alone keeps the authorize job's pass (Codex's first read of 144057c)
        run_steps = _steps(flow, "run")
        first     = run_steps[0]
        assert "switch" in first["name"]
        authorize = _steps(flow, "authorize")
        assert first["run"] == authorize[_index(authorize, "switch")]["run"]
        assert first["env"]["SWITCH_DEV"] == "${{ vars.TF_ACTIONS_ON_DEV }}"
        assert first["env"]["SWITCH_PROD"] == "${{ vars.TF_ACTIONS_ON_PROD }}"


    def test_a_repair_goes_ahead_on_a_state_the_check_refuses(self, flow):
        # the repair the failure summary prescribes cures what this check refuses (Codex's first read of 144057c)
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state before the plan")]["run"]
        assert script.count('"$MODE" != repair') == 2
        assert "exit 1" in script


    def test_the_proof_after_a_change_refuses_an_empty_state_itself(self, flow):
        # both roots always hold projects, so an empty state after an apply or a repair is wrong whatever the caller's
        # proof says of it (Codex's second read of 82c3c8e)
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state proof after")]["run"]
        assert "state list" in script
        assert "empty after" in script


    def test_a_deploy_claims_its_gate_run_once_before_the_apply(self, flow):
        steps = _steps(flow, "run")
        claim = _index(steps, "Claim the gate run")
        assert claim < _index(steps, "Terraform apply")
        assert steps[claim]["if"] == "inputs.mode == 'deploy'"
        assert "already consumed" in steps[claim]["run"] and "exit 1" in steps[claim]["run"]
        assert "terraform_gate_run" in steps[claim]["run"]
        mark = steps[_index(steps, "Mark the gate run's deployment")]
        assert mark["if"] == "always() && steps.claim.outcome == 'success'"


    def test_head_is_checked_before_any_of_the_callers_code_or_terraform_runs(self, flow):
        steps = _steps(flow, "run")
        check = _index(steps, "resolved commit")
        assert 'git rev-parse HEAD' in steps[check]["run"]
        assert steps[check]["env"]["EXPECTED_COMMIT"] == "${{ inputs.expected_commit }}"
        for step in steps[1:check]:
            assert "terraform" not in step.get("run", "") and "scripts/" not in step.get("run", "")


    def test_the_live_string_is_never_mapped_in_recovery_even_with_its_own_secret_empty(self, flow):
        mapping = flow["jobs"]["run"]["env"]["PG_CONN_STR"]
        assert mapping == (
            "${{ inputs.mode == 'recovery' && secrets.TF_STATE_RECOVERY_CONN_STR "
            "|| inputs.mode != 'recovery' && secrets.TF_STATE_PG_CONN_STR || '' }}"
        )


    def test_the_live_string_is_named_nowhere_else_but_the_recovery_refusal(self, text):
        # the mapping, and the recovery's presence check, which reads true or false and never the value
        assert text.count("secrets.TF_STATE_PG_CONN_STR") == 2
        assert "LIVE_PRESENT: ${{ secrets.TF_STATE_PG_CONN_STR != '' }}" in text


    def test_a_recovery_refuses_to_hold_the_live_string_before_any_caller_code(self, flow):
        # the bundle handed to the caller's preflight would hold it, so a recovery's caller passes its secrets by name
        # without it, and this step fails closed when it is there at all (the owner's answer of 2026-11-11)
        steps  = _steps(flow, "run")
        refuse = _index(steps, "Refuse the live string in a recovery")
        assert steps[refuse]["if"] == "inputs.mode == 'recovery'"
        assert refuse < _index(steps, "Check out the release commit")
        assert refuse < _index(steps, "Map the inputs")


    @pytest.mark.parametrize("present, allowed", [("false", True), ("true", False), ("", False), ("False", False)])
    def test_the_recovery_refusal_runs_as_a_shell(self, flow, tmp_path, present, allowed):
        shell = _bash()
        if shell is None:
            pytest.skip("no bash to run the step's shell")
        steps = _steps(flow, "run")
        (tmp_path / "step.sh").write_text(
            steps[_index(steps, "Refuse the live string in a recovery")]["run"],
            encoding = "utf-8",
            newline = "\n",
        )
        env  = {**os.environ, "LIVE_PRESENT": present}
        code = subprocess.run([shell, "step.sh"], cwd = tmp_path, env = env, capture_output = True, check = False)
        assert (code.returncode == 0) is allowed


    def test_the_identity_is_held_before_init(self, flow):
        steps    = _steps(flow, "run")
        identity = _index(steps, "backend's identity")
        assert identity < _index(steps, "Terraform init")
        script = steps[identity]["run"]
        assert "TF_STATE_IDENTITY" in str(steps[identity]["env"])
        assert '"$MODE" = recovery' in script


    def test_a_deploy_verifies_the_seal_before_installing_terraform(self, flow):
        steps  = _steps(flow, "run")
        verify = _index(steps, "Verify the gate's manifest")
        setup  = [
            i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("hashicorp/setup-terraform@")
        ]
        deploy = [
            i for i in setup if "deploy" in str(steps[i].get("if", "")) and "!=" not in str(steps[i].get("if", ""))
        ]
        assert deploy and all(verify < i for i in deploy)


    def test_terraforms_wrapper_is_off_wherever_it_is_installed(self, flow):
        for step in _steps(flow, "run"):
            if str(step.get("uses", "")).startswith("hashicorp/setup-terraform@"):
                assert step["with"]["terraform_wrapper"] is False


    def test_the_state_proof_runs_after_every_apply_that_started(self, flow):
        steps = _steps(flow, "run")
        apply = _index(steps, "Terraform apply")
        proof = _index(steps, "state proof after")
        assert proof > apply
        assert "always()" in steps[proof]["if"]
        assert "steps.apply.outcome != 'skipped'" in steps[proof]["if"]


    def test_a_forced_push_is_made_by_a_repair_alone(self, flow):
        for step in _steps(flow, "run"):
            if "state push -force" in step.get("run", ""):
                assert "inputs.mode == 'repair'" in step["if"]


    def test_validate_and_acceptance_hold_the_plan_to_no_changes_before_any_apply(self, flow):
        steps = _steps(flow, "run")
        quiet = _index(steps, "plan of no changes")
        assert quiet < _index(steps, "Terraform apply")
        for mode in ("validate", "acceptance"):
            assert mode in steps[quiet]["if"]


    def test_validate_recovery_and_gate_plan_never_apply(self, flow):
        condition = _steps(flow, "run")[_index(_steps(flow, "run"), "Terraform apply")]["if"]
        for mode in ("apply", "deploy", "acceptance"):
            assert f"'{mode}'" in condition
        for mode in ("validate", "recovery", "gate-plan", "repair"):
            assert f"'{mode}'" not in condition


    def test_the_gates_artifact_holds_the_plan_and_its_manifest_alone_for_three_days(self, flow):
        uploads = [s for s in _steps(flow, "run") if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
        assert len(uploads) == 1
        files = [line.strip() for line in uploads[0]["with"]["path"].splitlines() if line.strip()]
        assert sorted(Path(f).name for f in files) == ["manifest.json", "tfplan"]
        assert uploads[0]["with"]["retention-days"] <= 3


    def test_no_state_file_is_ever_uploaded(self, text):
        assert "errored.tfstate" not in text.split("actions/upload-artifact@", 1)[1].split("- name:", 1)[0]
