"""
Contract tests for .github/workflows/terraform-run.yml, the reusable terraform workflow (terraform in Actions, design
5.6 to 5.8).

The workflow is read as YAML and as text. Its switch rule runs as a real shell with each mode and switch, so the rule
is tested as it runs and not as it reads. Nothing here reaches GitHub or Terraform.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import terraform_run as tr
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "terraform-run.yml"
MODES    = ("apply", "gate-plan", "deploy", "validate", "recovery", "repair", "acceptance")
PINNED   = re.compile(r"[^@\s]+@[0-9a-f]{40}")

# contract 1, the interface as merged, frozen (design 5.6, Round Table 92, L12)
CONTRACT_1 = Path(__file__).resolve().parent / "fixtures" / "terraform_run" / "contract_1.json"

# a call of a release script, python3 running it by its path in the caller's checkout, never one of cicd's own under
# _kdf_cicd/, so a message naming a script is no call
RELEASE_CALL = re.compile(r"(?<![\w/.$-])python3 scripts/[a-z_]+\.py")

# the names the workflow reads from the release, a path in its checkout, its lock file and its policies
RELEASE_NAMES = re.compile(
    r"(?<![\w/.$-])(?:manifest|scripts|environments|modules|policy)/[\w.-]+(?:/[\w.-]+)*"
    r"|\.terraform\.lock\.hcl|--policy \S+"
)

# the names the workflow asks of the release's root, each variable it sets, each variables file it passes and each
# output it reads, however the argument is quoted (Codex's second read of 3b, of e5cdd09, finding 3)
ROOT_NAMES = (
    (re.compile(r"-var(?:\s+|=)[\"']?([A-Za-z_][\w-]*)[\"']?="), "-var {}"),
    (re.compile(r"-var-file(?:\s+|=)[\"']?([^\"'\s]+)"), "-var-file {}"),
    (re.compile(r"\boutput(?:\s+-[\w=-]+)*\s+[\"']?([A-Za-z_][\w-]*)"), "output {}"),
)

# a Terraform call against the release's root, which reads the root's files, variables, outputs and backend, so each
# is frozen whole with its step's condition (Codex's third read of 3b, of bc1fca8, findings 2 and 3)
TERRAFORM_CALL = re.compile(r"(?<![\w/.$-])terraform\s+-chdir=")

# the keys of a step and of the job that decide whether a step runs, what it reads and what a failure does
STEP_KEYS = ("if", "env", "continue-on-error", "shell", "working-directory")
JOB_KEYS  = ("env", "defaults", "continue-on-error")

# the lines of each verify that may touch the folder a download fills, a read of the copy, its verify and its copy to
# the apply's path, in that order
GATE_VERIFY = " ".join([
    'python3 "$HELPER" verify --manifest "$RUNNER_TEMP/gate/manifest.json"',
    '--expected "$RUNNER_TEMP/expected.json" --floor "$TF_FLOOR" --max-age-hours "$MAX_AGE"',
])
GATE_LINES  = [
    "plan_sha=\"$(sha256sum \"$RUNNER_TEMP/gate/tfplan\" | cut -d' ' -f1)\"",
    GATE_VERIFY,
    'cp "$RUNNER_TEMP/gate/tfplan" "$RUNNER_TEMP/tfplan"',
]

# the apply's own lines, the verified plan at its fixed path and nothing else applied
APPLY_LINES = [
    "set -euo pipefail",
    " ".join([
        'terraform -chdir="$TF_DIR" apply -input=false -var-file="$RUNNER_TEMP/tf-inputs.tfvars.json"',
        '"$RUNNER_TEMP/tfplan"',
    ]),
]

# a Terraform for the repair push's step run as a shell, failing as the real one did when the root's own relative path
# is not there beside the folder it runs in, and recording each call's folder, data folder and backend string (D-108)
FAKE_TERRAFORM = """
import json, os, sys
args  = sys.argv[1:]
chdir = next(a.split("=", 1)[1] for a in args if a.startswith("-chdir="))
rest  = [a for a in args if not a.startswith("-chdir=")]
conn  = os.environ.get("PG_CONN_STR")
call  = {"chdir": chdir, "args": rest, "data_dir": os.environ.get("TF_DATA_DIR"), "conn": conn}
with open(os.environ["FAKE_TF_LOG"], "a", encoding = "utf-8") as log:
    log.write(json.dumps(call) + "\\n")
if not os.path.exists(os.path.join(chdir, "..", "..", "manifest", "manifest.json")):
    print("Error: Invalid function argument, no file exists at ./../../manifest/manifest.json")
    sys.exit(1)
if rest[:2] == ["state", "pull"]:
    which = "FAKE_CANDIDATE" if conn == os.environ["FAKE_RECOVERY"] else "FAKE_LIVE"
    with open(os.environ[which], encoding = "utf-8") as fh:
        sys.stdout.write(fh.read())
sys.exit(0)
"""


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


def _run_certify(flow: dict, tmp_path: Path, state: bytes, named: str) -> tuple[subprocess.CompletedProcess, Path]:
    """
    The validate's certify step run in bash on a pulled state with a named digest, the real helper reached through a
    python3 on the path, and the runner's folder holding its summary and outputs.
    """
    shell = _bash()
    if shell is None:
        pytest.skip("no bash to run the step's shell")
    steps  = _steps(flow, "run")
    script = steps[_index(steps, "Certify the named state")]["run"]
    (tmp_path / "step.sh").write_text(script, encoding = "utf-8", newline = "\n")
    programs = tmp_path / "bin"
    programs.mkdir()
    python = programs / "python3"
    python.write_text('#!/usr/bin/env bash\nexec "$FAKE_PY" "$@"\n', encoding = "utf-8", newline = "\n")
    python.chmod(0o755)
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "before.json").write_bytes(state)
    (runner / "tfplan.proof.json").write_text(json.dumps({"resource_changes": []}), encoding = "utf-8")
    env = {
        **os.environ,
        "PATH": os.pathsep.join([programs.as_posix(), os.environ.get("PATH", "")]),
        "FAKE_PY": Path(sys.executable).as_posix(),
        "HELPER": Path(tr.__file__).as_posix(),
        "RUNNER_TEMP": runner.as_posix(),
        "TARGET": "dev",
        "RELEASE": "0.11.0",
        "CERTIFY_DIGEST": named,
        "GITHUB_STEP_SUMMARY": (runner / "summary.md").as_posix(),
        "GITHUB_OUTPUT": (runner / "output").as_posix(),
    }
    run = subprocess.run(
        [shell, "--noprofile", "--norc", "step.sh"],
        cwd = tmp_path,
        env = env,
        capture_output = True,
        text = True,
        check = False,
    )
    return run, runner


def _run_push(flow: dict, tmp_path: Path, live_sha: str | None = None) -> tuple[subprocess.CompletedProcess, list]:
    """
    The repair's push step run in bash in a made up checkout whose root reads ../../manifest, as the terraform repo's
    does, the real helper's bind-push between a fake Terraform's pulls, and each Terraform call it made.
    """
    shell = _bash()
    if shell is None:
        pytest.skip("no bash to run the step's shell")
    steps  = _steps(flow, "run")
    script = steps[_index(steps, "Repair, push the candidate")]["run"]
    repo   = tmp_path / "repo"
    (repo / "environments" / "dev").mkdir(parents = True)
    (repo / "manifest").mkdir()
    (repo / "manifest" / "manifest.json").write_text("{}", encoding = "utf-8")
    (repo / "step.sh").write_text(script, encoding = "utf-8", newline = "\n")
    programs = tmp_path / "bin"
    programs.mkdir()
    fake = tmp_path / "fake_terraform.py"
    fake.write_text(FAKE_TERRAFORM, encoding = "utf-8")
    for name, target in (("python3", '"$@"'), ("terraform", '"$FAKE_TF" "$@"')):
        program = programs / name
        program.write_text(f'#!/usr/bin/env bash\nexec "$FAKE_PY" {target}\n', encoding = "utf-8", newline = "\n")
        program.chmod(0o755)
    runner = tmp_path / "runner"
    runner.mkdir()
    # two states of one lineage and serial that differ, so a read of one through the other's string breaks the binding
    candidate = b'{"version": 4, "serial": 5, "lineage": "l", "outputs": {"from": {"value": "scratch"}}}'
    live      = b'{"version": 4, "serial": 5, "lineage": "l", "outputs": {"from": {"value": "live"}}}'
    (tmp_path / "candidate.json").write_bytes(candidate)
    (tmp_path / "live.json").write_bytes(live)
    env = {
        **os.environ,
        "PATH": os.pathsep.join([programs.as_posix(), os.environ.get("PATH", "")]),
        "FAKE_PY": Path(sys.executable).as_posix(),
        "FAKE_TF": fake.as_posix(),
        "FAKE_TF_LOG": (tmp_path / "calls.jsonl").as_posix(),
        "FAKE_RECOVERY": "postgresql://r:kdfmk-scratch-made-up@db.example.test/scratch",
        "FAKE_CANDIDATE": (tmp_path / "candidate.json").as_posix(),
        "FAKE_LIVE": (tmp_path / "live.json").as_posix(),
        "HELPER": Path(tr.__file__).as_posix(),
        "RUNNER_TEMP": runner.as_posix(),
        "TF_DIR": "environments/dev",
        "PG_CONN_STR": "postgresql://w:kdfmk-live-made-up@db.example.test/terraform",
        "RECOVERY_CONN_STR": "postgresql://r:kdfmk-scratch-made-up@db.example.test/scratch",
        "CANDIDATE_SHA": tr.state_digest(candidate),
        "LIVE_SHA": live_sha or tr.state_digest(live),
        "LIVE_LINEAGE": "l",
        "LIVE_SERIAL": "5",
        "NAMED_RELEASE": "",
    }
    env.pop("TF_DATA_DIR", None)
    run   = subprocess.run(
        [shell, "--noprofile", "--norc", "step.sh"],
        cwd = repo,
        env = env,
        capture_output = True,
        text = True,
        check = False,
    )
    log   = tmp_path / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text(encoding = "utf-8").splitlines()] if log.exists() else []
    return run, calls


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
        assert steps[claim]["if"] == "inputs.mode == 'deploy' || inputs.mode == 'acceptance'"
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


    def test_the_live_string_is_named_nowhere_else(self, text):
        assert text.count("secrets.TF_STATE_PG_CONN_STR") == 1


    def test_the_bundle_reaches_cicds_own_filter_alone(self, flow, text):
        # a caller passes secrets by name only when cicd declares each, so it inherits them all, and cicd's own step
        # drops the connection strings before the caller's code sees any (the owner's answer of 2026-11-11)
        assert text.count("toJSON(secrets)") == 1
        steps  = _steps(flow, "run")
        bundle = steps[_index(steps, "Drop the connection strings")]
        assert bundle["env"]["SECRETS_JSON"] == "${{ toJSON(secrets) }}"
        script = bundle["run"]
        assert 'python3 "$HELPER" secrets-file' in script
        for name in ("TF_STATE_PG_CONN_STR", "TF_STATE_RECOVERY_CONN_STR", "TF_MANIFEST_KEY", "github_token"):
            assert f"--drop {name}" in script
        assert "scripts/" not in script.replace("_kdf_cicd/scripts/", "")


    def test_the_callers_preflight_reads_the_filtered_file_and_never_the_bundle(self, flow):
        steps     = _steps(flow, "run")
        preflight = steps[_index(steps, "Map the inputs")]
        assert "SECRETS_JSON" not in preflight.get("env", {})
        assert '--secrets-file "$RUNNER_TEMP/tf-secrets.json"' in preflight["run"]
        assert _index(steps, "Drop the connection strings") < _index(steps, "Map the inputs")


    def test_no_step_refuses_an_inherited_live_string(self, text):
        # an inherited bundle always holds it, so such a refusal would stop every recovery
        assert "LIVE_PRESENT" not in text


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

# ======================================================================================================================
# The saved plan read whole, the run's rules and the proof record (design version 14, Round Table 88)
# ======================================================================================================================

def _if(steps: list[dict], name: str) -> str:
    """
    A step's condition, by the words in its name.
    """
    return str(steps[_index(steps, name)].get("if", ""))


class TestThePlanProofAndTheRecord:
    """
    The binary plan given by name, full rules built from the plan a run applies, a sealed record of each proven state
    the PROD gate and deploy require, and the owner's named validate as the way back.
    """
    def test_certify_digest_is_an_optional_string(self, flow):
        spec = flow[True]["workflow_call"]["inputs"]["certify_digest"]
        assert spec["required"] is False and spec["type"] == "string" and spec["default"] == ""


    def test_a_certify_digest_outside_validate_is_refused(self, flow):
        steps = _steps(flow, "run")
        step  = steps[_index(steps, "certify_digest outside validate")]
        assert "exit 1" in step["run"]
        assert step["if"] == "inputs.certify_digest != '' && inputs.mode != 'validate'"
        assert _index(steps, "certify_digest outside validate") < _index(steps, "Terraform init")


    def test_the_proofs_json_is_written_from_the_binary_in_the_step_that_saves_it(self, flow):
        # the policies' step rewrites its own copy, so the proof and the builder read one it never touches (M2)
        steps = _steps(flow, "run")
        plan  = steps[_index(steps, "Terraform plan")]["run"]
        assert '-out="$RUNNER_TEMP/tfplan"' in plan and "tfplan.proof.json" in plan
        assert "tfplan.proof.json" not in steps[_index(steps, "The policies")]["run"]


    def test_a_deploy_decodes_the_gates_binary_with_the_manifests_terraform(self, flow):
        steps  = _steps(flow, "run")
        decode = _index(steps, "Decode the gate's plan")
        assert _if(steps, "Decode the gate's plan") == "inputs.mode == 'deploy'"
        assert 'show -json "$RUNNER_TEMP/tfplan" > "$RUNNER_TEMP/tfplan.proof.json"' in steps[decode]["run"]
        assert _index(steps, "Verify the gate's manifest") < decode
        assert _index(steps, "Set up Terraform for the deploy") < decode < _index(steps, "Terraform apply")


    def test_the_rules_are_built_from_the_proofs_json_in_each_mode_that_writes_or_gates(self, flow):
        steps     = _steps(flow, "run")
        build     = _index(steps, "Build the run's rules")
        condition = _if(steps, "Build the run's rules")
        for mode in ("apply", "gate-plan", "acceptance", "deploy"):
            assert f"'{mode}'" in condition
        for mode in ("validate", "recovery", "repair"):
            assert f"'{mode}'" not in condition
        script = steps[build]["run"]
        assert "scripts/tf_state_rules.py" in script and '"$RUNNER_TEMP/tfplan.proof.json"' in script
        assert "tf-inputs.tfvars.json" not in script
        assert build > _index(steps, "Decode the gate's plan") and build < _index(steps, "Terraform apply")


    def test_the_plan_proof_reads_the_binary_by_name_in_the_gate_acceptance_and_devs_apply(self, flow):
        steps     = _steps(flow, "run")
        proof     = _index(steps, "Prove every state the saved plan carries")
        condition = _if(steps, "Prove every state the saved plan carries")
        for mode in ("apply", "gate-plan", "acceptance"):
            assert f"'{mode}'" in condition
        script = steps[proof]["run"]
        for argument in (
            '--plan "$RUNNER_TEMP/tfplan.proof.json"',
            '--planfile "$RUNNER_TEMP/tfplan"',
            '--stored "$RUNNER_TEMP/before.json"',
            "--existing-rules",
            "--full-rules",
        ):
            assert argument in script
        assert _index(steps, "Build the run's rules") < proof < _index(steps, "Terraform apply")
        assert proof < _index(steps, "Keep the plan and its manifest")


    def test_the_plan_proof_searches_for_every_value_the_preflight_wrote(self, flow, text):
        # the known search beside the structural proof (Round Table 88, L1, the owner's answer of 2026-11-12)
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "Prove every state the saved plan carries")]["run"]
        assert '--var-file "$RUNNER_TEMP/tf-inputs.tfvars.json"' in script
        assert _index(steps, "Map the inputs") < _index(steps, "Prove every state the saved plan carries")
        assert "known search" in text.split("name: CD, Terraform run", 1)[0]


    def test_the_stored_state_is_kept_for_the_proof_and_removed_at_the_end(self, flow):
        steps = _steps(flow, "run")
        hold  = steps[_index(steps, "state before the plan")]["run"]
        assert 'rm -f "$RUNNER_TEMP/before.json"' not in hold
        assert "scripts/tf_state_extra.py" in hold
        last = steps[_index(steps, "Remove the pulled states")]
        assert last["if"] == "always()"
        assert 'rm -f "$RUNNER_TEMP/before.json"' in last["run"]


    def test_the_prod_gate_and_deploy_require_the_last_sealed_record_before_anything_rests_on_the_state(self, flow):
        # acceptance runs the same check on DEV (Round Table 92, the owner's answers of 2026-11-12)
        steps   = _steps(flow, "run")
        require = _index(steps, "Require the last proof record")
        assert _if(steps, "Require the last proof record") == (
            "inputs.mode == 'gate-plan' || inputs.mode == 'deploy' || inputs.mode == 'acceptance'"
        )
        script = steps[require]["run"]
        assert "--paginate" in script and 'python3 "$HELPER" record-check' in script
        assert steps[require]["env"]["TF_MANIFEST_KEY"] == "${{ secrets.TF_MANIFEST_KEY }}"
        assert _index(steps, "state before the plan") < require < _index(steps, "Terraform plan")
        assert require < _index(steps, "Keep the plan and its manifest")
        assert require < _index(steps, "Claim the gate run")


    def test_the_proof_after_a_write_takes_the_full_rules_or_the_partial_rule_and_names_its_record(self, flow):
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state proof after")]["run"]
        assert "state-rules-full.json" in script and "scripts/tf_state_extra.py" in script
        assert "--partial-plan" in script
        assert "record=complete" in script and "record=partial" in script and "record=none" in script


    def test_a_completed_write_is_held_to_the_full_rules_and_never_the_committed_ones(self, flow):
        # a mutation giving the success branch the structural rules passed before (Codex's review of f05c870)
        steps   = _steps(flow, "run")
        script  = steps[_index(steps, "state proof after")]["run"]
        success = script.split('elif [ "$APPLY" = success ]; then', 1)[1].split("else", 1)[0]
        assert success.count('--rules "$full"') == 2
        assert "STATE_RULES" not in success


    def test_validate_lists_every_difference_and_drift_and_the_certify_step_does_too(self, flow):
        steps  = _steps(flow, "run")
        lister = steps[_index(steps, "List what differs")]
        assert lister["if"] == "inputs.mode == 'validate'"
        assert 'python3 "$HELPER" differences' in lister["run"]
        assert 'python3 "$HELPER" differences' in steps[_index(steps, "Certify the named state")]["run"]
        assert "no-changes" not in steps[_index(steps, "Certify the named state")]["run"]


    @pytest.mark.parametrize("step", ["state before the plan", "state proof after"])
    def test_the_supplemental_check_runs_before_the_frozen_proof(self, flow, step):
        # the frozen proof names a private data key it does not hold, the payload's own bytes, and the supplemental
        # check refuses such data by count, so it runs first and the frozen proof never sees it (D-105)
        steps  = _steps(flow, "run")
        script = steps[_index(steps, step)]["run"]
        extra  = [i for i in range(len(script)) if script.startswith("scripts/tf_state_extra.py", i)]
        proof  = [i for i in range(len(script)) if script.startswith("scripts/tf_state_proof.py", i)]
        assert extra and len(extra) == len(proof)
        for e, p in zip(extra, proof):
            assert e < p
        # a refusal stops the step before the frozen proof, by && before the plan and by set -e after a write, and
        # the order alone would not hold that (Codex's review of 9b71366)
        if step == "state before the plan":
            between = script[extra[0]:proof[0]]
            assert "&& python3 scripts/tf_state_proof.py" in script and ";" not in between
        else:
            assert script.lstrip().startswith("set -euo pipefail")
            assert "|| true" not in script


    def test_the_check_before_the_plan_takes_rules_built_from_the_stored_state(self, flow):
        # a release that moves a secret leaves it at its old address in the stored state, which the committed rules
        # alone would refuse, so the caller adds every address holding a write only version (D-105, the owner's
        # choice of 2026-11-12)
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state before the plan")]["run"]
        build  = script.index("scripts/tf_state_rules.py --existing-only")
        assert build < script.index("scripts/tf_state_extra.py")
        assert '--stored "$RUNNER_TEMP/before.json"' in script
        assert script.count('--rules "$RUNNER_TEMP/state-rules-stored.json"') == 2
        assert '--rules "$STATE_RULES"' not in script.split("scripts/tf_state_rules.py", 1)[1]


    def test_a_repair_and_a_partial_write_take_rules_built_from_the_written_state(self, flow):
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state proof after")]["run"]
        assert "scripts/tf_state_rules.py --existing-only" in script
        assert '--stored "$after"' in script
        for branch in (
            script.split('if [ "$MODE" = repair ]; then', 1)[1].split("elif", 1)[0],
            script.split('elif [ "$APPLY" = success ]; then', 1)[1].split("else", 1)[1],
        ):
            assert '--rules "$written"' in branch and '--rules "$STATE_RULES"' not in branch


    def test_a_repair_never_makes_a_record(self, flow):
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "state proof after")]["run"]
        repair = script.split('"$MODE" = repair', 1)[1].split("fi", 1)[0]
        assert "record=none" in repair


    def test_the_record_is_sealed_by_the_environments_job_after_its_proof(self, flow):
        steps  = _steps(flow, "run")
        record = _index(steps, "Record the proven state")
        step   = steps[record]
        assert "steps.proof.outcome == 'success'" in step["if"] and "steps.certify.outcome == 'success'" in step["if"]
        assert 'python3 "$HELPER" record-seal' in step["run"]
        assert step["env"]["TF_MANIFEST_KEY"] == "${{ secrets.TF_MANIFEST_KEY }}"
        assert "deployments" in step["run"]
        assert record > _index(steps, "state proof after") and record > _index(steps, "Certify the named state")


    def test_the_named_validate_certifies_the_pulled_state_and_skips_the_plan_of_no_changes(self, flow):
        steps   = _steps(flow, "run")
        certify = steps[_index(steps, "Certify the named state")]
        assert certify["if"] == "inputs.mode == 'validate' && inputs.certify_digest != ''"
        assert "CERTIFY_DIGEST" in certify["env"]
        # the helper's canonical digest held to the named one, a mismatch failing the step by set -e (D-107)
        assert certify["run"].lstrip().startswith("set -euo pipefail")
        assert 'python3 "$HELPER" state-digest --state "$RUNNER_TEMP/before.json" --expect "$CERTIFY_DIGEST"' in (
            certify["run"]
        )
        assert "sha256sum" not in certify["run"]
        quiet = _if(steps, "plan of no changes")
        assert "inputs.certify_digest == ''" in quiet and "'acceptance'" in quiet


    @pytest.mark.parametrize("named, certified", [("same", True), ("other", False), ("forged", False)])
    def test_the_certify_step_records_the_named_state_alone(self, flow, tmp_path, named, certified):
        # the step run as a shell with the real helper, so a mismatch is shown to stop it before anything is recorded,
        # not read from its text (Codex's review of 6e74666)
        state = (
            b'{"version": 4, "serial": 7, "lineage": "l",'
            b' "check_results": [{"config_addr": "b"}, {"config_addr": "a"}]}'
        )
        other = b'{"version": 4, "serial": 8, "lineage": "l"}'
        given = {
            "same": tr.state_digest(state.replace(b'"b"}, {"config_addr": "a"', b'"a"}, {"config_addr": "b"')),
            "other": tr.state_digest(other),
            "forged": tr.state_digest(state) + "\n::error::forged",
        }[named]
        run, runner = _run_certify(flow, tmp_path, state, given)
        output  = (runner / "output").read_text(encoding = "utf-8") if (runner / "output").exists() else ""
        summary = (runner / "summary.md").read_text(encoding = "utf-8") if (runner / "summary.md").exists() else ""
        if certified:
            assert run.returncode == 0 and "record=certified" in output
            assert f"Certifying the dev state {given}" in summary
        else:
            assert run.returncode != 0 and "record=certified" not in output and "Certifying" not in summary
            assert "::error::forged" not in run.stdout


    def test_no_state_is_hashed_by_its_bytes(self, text):
        # a pull writes one stored state in many byte strings, its check results in Go's map order, so every digest
        # of a state is the helper's canonical one, and sha256sum hashes the plan, the lock file and the tools alone
        assert not re.findall(r"sha256sum[^\n]*\.json", text)
        assert not re.findall(r"sha256sum[^\n]*(?:before|after|candidate|live)\b", text)


    def test_the_header_names_each_script_and_both_rules_files(self, text):
        header = text.split("name: CD, Terraform run", 1)[0]
        for name in (
            "tf_state_rules.py",
            "tf_state_extra.py",
            "tf_plan_proof.py",
            "certify_digest",
            "state-rules-full.json",
            "manifest/run_contract.json",
        ):
            assert name in header

# ======================================================================================================================
# The repair's push, its candidate read in the root itself (D-108)
# ======================================================================================================================

class TestTheRepairPush:
    """
    The push reads its candidate from the scratch in the root itself, a data folder of its own keeping that backend
    apart, since a copy of the root alone loses every path the root reaches outside it (the rehearsal of 2026-11-15).
    """
    def test_the_candidate_is_read_in_the_root_with_a_data_folder_of_its_own_and_pushed(self, flow, tmp_path):
        run, calls = _run_push(flow, tmp_path)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "Forced push binding PASSED" in run.stdout
        recovery  = "postgresql://r:kdfmk-scratch-made-up@db.example.test/scratch"
        live_conn = "postgresql://w:kdfmk-live-made-up@db.example.test/terraform"
        candidate = [call for call in calls if call["conn"] == recovery]
        live      = [call for call in calls if call["conn"] != recovery]
        assert [call["args"][:2] for call in candidate] == [["init", "-input=false"], ["state", "pull"]]
        for call in candidate:
            assert call["chdir"] == "environments/dev"
            assert call["data_dir"] and Path(call["data_dir"]).is_absolute()
            assert Path(call["data_dir"]).as_posix().startswith((tmp_path / "runner").as_posix())
        # the candidate's init and pull share one data folder, so the pull reads the backend the init set
        assert candidate[0]["data_dir"] == candidate[1]["data_dir"]
        # the live state's own calls keep the job's string and the root's .terraform, the scratch's data never in it
        assert [call["args"][:2] for call in live] == [["state", "pull"], ["state", "push"]]
        assert all(call["conn"] == live_conn for call in live)
        assert all(call["data_dir"] is None and call["chdir"] == "environments/dev" for call in live)
        assert live[1]["args"] == ["state", "push", "-force", (tmp_path / "runner" / "candidate.json").as_posix()]


    def test_a_binding_that_does_not_hold_pushes_nothing(self, flow, tmp_path):
        run, calls = _run_push(flow, tmp_path, live_sha = "0" * 64)
        assert run.returncode != 0
        assert "Forced push binding FAILED" in run.stdout and "the live state changed since it was read" in run.stdout
        assert not any(call["args"][:2] == ["state", "push"] for call in calls)


    def test_the_step_copies_no_root(self, flow):
        steps  = _steps(flow, "run")
        script = steps[_index(steps, "Repair, push the candidate")]["run"]
        assert "cp -r" not in script and "candidate-root" not in script

# ======================================================================================================================
# The run contract (design 5.6, Round Table 92, L12, the owner's answers of 2026-11-12)
# ======================================================================================================================

def _shell_lines(script: str) -> list[str]:
    """
    A step's script as its shell runs it, each continued line joined, its spaces made single and its comments left out.
    """
    joined = re.sub(r"\\\n[ \t]*", " ", script)
    lines  = (" ".join(line.split()) for line in joined.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _prints_only(line: str) -> bool:
    """
    Whether a shell line only prints, an echo with no redirect either way, no command run inside it and nothing
    chained to it or run beside it (Codex's second read of 3b, of e5cdd09, finding 2).
    """
    is_echo = line == "echo" or line.startswith("echo ")
    return is_echo and not any(mark in line for mark in (">", "<", "$(", "`", "|", ";", "&"))


def _names_in(text: str) -> set[str]:
    """
    Every name the release is read by that a line or a variable's value holds.
    """
    names = {match.group(0) for match in RELEASE_NAMES.finditer(text)}
    for pattern, shape in ROOT_NAMES:
        names.update(shape.format(match.group(1)) for match in pattern.finditer(text))
    return names


def _logical_lines(script: str) -> list[str]:
    """
    The lines of a step that can change what the release is asked, its shell lines less each one that only prints,
    so a changed message declares nothing.
    """
    return [line for line in _shell_lines(script) if not _prints_only(line)]


def release_interface(flow: dict) -> dict:
    """
    What the workflow asks of the release it runs, contract 1's parts. Each step that calls a release script, whole,
    in order, its condition, its variables, whether a failure stops it, its shell and every line it runs but its
    comments and its echoes that only print. Then the job's variables, the release's checkout, the defaults of the
    caller's file inputs, every path in the release's checkout and name of its root the job reads (Codex's review of
    a2bdbd1, finding 1), and every Terraform call against the root with its step's condition (its third read, of
    bc1fca8).
    """
    inputs = flow[True]["workflow_call"]["inputs"]
    job    = flow["jobs"]["run"]
    calls:     list[dict]     = []
    terraform: list[dict] = []
    names:     set[str]       = set()
    for key in job.get("env") or {}:
        if key.startswith("TF_VAR_"):
            names.add("env " + key)
    for step in job["steps"]:
        lines = _logical_lines(step.get("run", ""))
        for text in [*lines, *(str(value) for value in (step.get("env") or {}).values())]:
            names.update(_names_in(text))
        names.update("env " + key for key in (step.get("env") or {}) if key.startswith("TF_VAR_"))
        terraform.extend({"if": str(step.get("if", "")), "line": line} for line in lines if TERRAFORM_CALL.search(line))
        if not any(RELEASE_CALL.search(line) for line in lines):
            continue
        frozen = {key: step[key] for key in STEP_KEYS if key in step}
        frozen["run"] = lines
        calls.append(frozen)
    checkout = next(
        step for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@") and "repository" not in (step.get("with") or {})
    )
    return {
        "job": {key: job[key] for key in JOB_KEYS if key in job},
        "checkout": checkout["with"],
        "manifest_path": inputs["manifest_path"]["default"],
        "state_rules_path": inputs["state_rules_path"]["default"],
        "names": sorted(names),
        "calls": calls,
        "terraform": terraform,
    }


class TestTheRunContract:
    """
    The release declares the interface it holds, read before any of its scripts runs, and contract 1 is frozen here
    wider than the interface itself, a tripwire. A change it catches that every contract 1 release still meets updates
    the frozen copy in its pull request, the decision log naming why no script argument, release file, root name or
    exit handling changed. A change a contract 1 release cannot meet declares contract 2, in order, a terraform release
    declaring 2, its floors raised, then cicd moved to 2, every run between refused by the reader, so no workflow runs
    two contracts (D-106, the owner's answer of 2026-11-12).
    """
    def test_the_declaration_is_read_after_the_checkouts_hold_and_before_any_release_script(self, flow):
        steps    = _steps(flow, "run")
        contract = _index(steps, "run contract")
        step     = steps[contract]
        assert "if" not in step and "id" not in step
        assert step["run"].strip() == 'python3 "$HELPER" contract --root . --release "v$RELEASE"'
        helpers = next(i for i, s in enumerate(steps) if (s.get("with") or {}).get("path") == "_kdf_cicd")
        assert _index(steps, "resolved commit") < helpers < contract
        first = next(i for i, s in enumerate(steps) if RELEASE_CALL.search(s.get("run", "")))
        assert contract < first
        assert contract < _index(steps, "Terraform init")


    def test_contract_1_is_the_interface_as_merged(self, flow):
        frozen = json.loads(CONTRACT_1.read_text(encoding = "utf-8"))
        assert release_interface(flow) == frozen, (
            "the frozen copy of contract 1 changed. If every release declaring contract 1 still meets the change, "
            "update scripts/tests/fixtures/terraform_run/contract_1.json in this pull request, its decision log line "
            "naming why no script argument, release file, root name or exit handling changed. Else it declares "
            "contract 2, in order, a terraform release declaring 2, its floors raised, then cicd moved to 2 (D-106)"
        )


    @pytest.mark.parametrize("step, field, old, new", [
        # an argument, the exit handling, a branch and a mode's condition
        ("Map the inputs", "run", "--hashes", "--new --hashes"),
        ("Map the inputs", "run", "set -euo pipefail\n", ""),
        ("Map the inputs", "run", "set -euo pipefail\n", "set -euo pipefail\nset +e\n"),
        ("Hold the state before the plan", "run", "&& python3 scripts/tf_state_proof.py",
         "|| python3 scripts/tf_state_proof.py"),
        ("Hold the state before the plan", "run", 'if [ "$MODE" != repair ]; then', 'if [ "$MODE" != validate ]; then'),
        ("The state proof after", "run", 'elif [ "$APPLY" = success ]', 'elif [ "$APPLY" = failure ]'),
        ("Build the run's rules", "if", "inputs.mode == 'apply' || ", ""),
        # the secrets file kept after the call, and a name the release is read by (Codex's review of a2bdbd1)
        ("Map the inputs", "run", 'rm -f "$RUNNER_TEMP/tf-secrets.json"', 'true'),
        ("The policies", "run", "--policy policy", "--policy rules"),
        ("The policies", "run", "--policy policy", "--policy policy --data manifest/new-policy.json"),
        ("Refuse an obsolete run", "run", "output -raw release", "output -raw marker"),
        # a file read by an echo, and a variable or variables file the root must take, however quoted (Codex's second
        # read of 3b, of e5cdd09, findings 2 and 3)
        ("Map the inputs", "run", "set -euo pipefail\n",
         'set -euo pipefail\necho "starting preflight" < manifest/required.json\n'),
        ("Terraform plan", "run", '-var "release=v$RELEASE"', "-var \"release=v$RELEASE\" -var 'new_required=true'"),
        ("Terraform plan", "run", '-var "release=v$RELEASE"', '-var "release=v$RELEASE" -var=other_required=1'),
        ("Terraform plan", "run", '-var "release=v$RELEASE"',
         '-var "release=v$RELEASE" -var-file="$RUNNER_TEMP/extra.tfvars.json"'),
        # a file a Terraform call now needs, and a variable hidden by joined quotes (Codex's third read of 3b, of
        # bc1fca8, findings 2 and 3)
        ("Terraform init", "run", "-lockfile=readonly", "-lockfile=readonly -backend-config=backend.hcl"),
        ("Terraform plan", "run", '-var "release=v$RELEASE"', "-var \"release=v$RELEASE\" -var 'new_required'=true"),
    ])
    def test_the_freeze_sees_each_part_of_the_interface(self, flow, step, field, old, new):
        changed = copy.deepcopy(flow)
        target  = changed["jobs"]["run"]["steps"][_index(changed["jobs"]["run"]["steps"], step)]
        assert old in target[field]
        target[field] = target[field].replace(old, new)
        assert release_interface(changed) != release_interface(flow)


    def test_the_freeze_sees_a_moved_removal_a_step_variable_a_kept_failure_and_the_jobs_own(self, flow):
        # each a change Codex's review of a2bdbd1 made that the first freeze missed
        changes = []
        moved   = copy.deepcopy(flow)
        step    = _steps(moved, "run")[_index(_steps(moved, "run"), "Map the inputs")]
        removal = 'rm -f "$RUNNER_TEMP/tf-secrets.json"\n'
        assert removal in step["run"]
        step["run"] = step["run"].replace(removal, "").replace("set -euo pipefail\n", "set -euo pipefail\n" + removal)
        changes.append(moved)
        renamed = copy.deepcopy(flow)
        _steps(renamed, "run")[_index(_steps(renamed, "run"), "Map the inputs")]["env"]["MANIFEST_PATH"] = (
            "manifest/new-name.json"
        )
        changes.append(renamed)
        kept = copy.deepcopy(flow)
        _steps(kept, "run")[_index(_steps(kept, "run"), "Map the inputs")]["continue-on-error"] = True
        changes.append(kept)
        rooted = copy.deepcopy(flow)
        rooted["jobs"]["run"]["env"]["TF_DIR"] = "roots/${{ inputs.environment }}"
        changes.append(rooted)
        variable = copy.deepcopy(flow)
        plan     = _steps(variable, "run")[_index(_steps(variable, "run"), "Terraform plan")]
        plan.setdefault("env", {})["TF_VAR_new_required"] = "1"
        changes.append(variable)
        moved_checkout = copy.deepcopy(flow)
        next(s for s in _steps(moved_checkout, "run") if str(s.get("uses", "")).startswith("actions/checkout@")
             and "repository" not in s["with"])["with"]["path"] = "release"
        changes.append(moved_checkout)
        for changed in changes:
            assert release_interface(changed) != release_interface(flow)


    @pytest.mark.parametrize("step, old, new", [
        ("Map the inputs", "set -euo pipefail\n", 'set -euo pipefail\necho "the preflight starts"\n'),
        ("Terraform plan", "set -euo pipefail\n", 'set -euo pipefail\necho "scripts/tf_inputs.py finished"\n'),
        ("Hold the state before the plan", "set -euo pipefail\n", "set -euo pipefail\n# a note on the check\n"),
    ])
    def test_a_message_or_a_comment_declares_nothing(self, flow, step, old, new):
        changed = copy.deepcopy(flow)
        target  = _steps(changed, "run")[_index(_steps(changed, "run"), step)]
        assert old in target["run"]
        target["run"] = target["run"].replace(old, new, 1)
        assert release_interface(changed) == release_interface(flow)


    def test_cicd_keeps_contract_1_at_its_fixed_name(self):
        assert 1 in tr.SUPPORTED_CONTRACTS
        assert tr.CONTRACT_FILE == "manifest/run_contract.json"

# ======================================================================================================================
# The handoff inside acceptance, PROD's gate and deploy run on DEV in one job (Round Table 92)
# ======================================================================================================================

def _downloads(steps: list[dict]) -> list[int]:
    return [i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/download-artifact@")]


def handoff_faults(flow: dict) -> list[str]:
    """
    Every way acceptance could verify or apply a copy the download did not bring back, or skip the seal or the upload,
    so the handoff it runs is the deploy's (Codex's review of a2bdbd1, finding 2).
    """
    faults: list[str] = []
    steps  = _steps(flow, "run")
    seal   = _index(steps, "Seal the gate's manifest")
    upload = _index(steps, "Keep the plan and its manifest")
    for place in (seal, upload):
        if steps[place].get("if") != "inputs.mode == 'gate-plan' || inputs.mode == 'acceptance'":
            faults.append(f"{steps[place]['name']} does not run in both the gate and acceptance")
    verifies = (_index(steps, "Verify the gate's manifest"), _index(steps, "Verify the downloaded copy"))
    for i, step in enumerate(steps):
        text = json.dumps({key: value for key, value in step.items() if key != "name"})
        if "sealed" in text and i not in (seal, upload):
            faults.append(f"{step['name']} names the sealed folder")
        gate = [line for line in _shell_lines(step.get("run", "")) if "$RUNNER_TEMP/gate" in line]
        if i in verifies and gate != GATE_LINES:
            faults.append(f"{step['name']} touches the downloaded copy other than to read, verify and apply it")
        if i not in verifies and gate:
            faults.append(f"{step['name']} touches the folder a download fills")
        # inside a verify, the plan is named only to read the copy and to copy it to the apply's path, that copy its
        # last line (Codex's third read of 3b, of bc1fca8, finding 1)
        lines = _shell_lines(step.get("run", ""))
        if i in verifies and ([line for line in lines if "tfplan" in line] != [GATE_LINES[0], GATE_LINES[2]]
                              or lines[-1:] != [GATE_LINES[2]]):
            faults.append(f"{step['name']} names the plan other than to read the copy and apply it last")
    # the verified copy is the plan applied, so between acceptance's verify and the apply stands the claim alone, and
    # nothing there touches the plan (Codex's second read of 3b, of e5cdd09, finding 1)
    apply  = _index(steps, "Terraform apply")
    window = range(verifies[1] + 1, apply)
    if [steps[i]["name"] for i in window] != ["Claim the gate run"]:
        faults.append("a step other than the claim stands between acceptance's verify and the apply")
    for i in window:
        if "tfplan" in json.dumps({key: value for key, value in steps[i].items() if key != "name"}):
            faults.append(f"{steps[i]['name']} touches the plan between acceptance's verify and the apply")
    if _shell_lines(steps[apply].get("run", "")) != APPLY_LINES:
        faults.append("the apply applies something other than the plan at its fixed path")
    return faults


class TestTheAcceptanceHandoff:
    """
    Acceptance runs the gate's upload, the deploy's download by a run's id, its verify of that copy, the record check,
    the claim and the apply of the copy on the same code, so their plumbing runs on DEV before PROD needs it.
    """
    def test_the_seal_writes_a_folder_of_its_own_and_a_download_alone_fills_the_gates(self, flow):
        steps = _steps(flow, "run")
        seal  = steps[_index(steps, "Seal the gate's manifest")]["run"]
        assert '--out "$RUNNER_TEMP/sealed/manifest.json"' in seal
        assert 'cp "$RUNNER_TEMP/tfplan" "$RUNNER_TEMP/sealed/tfplan"' in seal
        assert "$RUNNER_TEMP/gate" not in seal
        upload = steps[_index(steps, "Keep the plan and its manifest")]["with"]["path"].splitlines()
        assert sorted(line.strip() for line in upload if line.strip()) == [
            "${{ runner.temp }}/sealed/manifest.json",
            "${{ runner.temp }}/sealed/tfplan",
        ]
        assert [steps[i]["with"]["path"] for i in _downloads(steps)] == ["${{ runner.temp }}/gate"] * 2
        assert handoff_faults(flow) == []


    @pytest.mark.parametrize("change", [
        "the verifies fill the folder from the sealed one first",
        "the seal skips acceptance",
        "the upload skips acceptance",
        "a later step copies the sealed plan to the apply's path",
        "the seal keeps a local plan and the claim restores it",
        "a step is put between acceptance's verify and the apply",
        "the apply names another plan",
        "the verifies end by copying a local plan over the verified one",
        "the verifies copy a local plan in place from inside the folder",
    ])
    def test_each_way_around_the_download_is_a_fault(self, flow, change):
        # each passed every case before (Codex's review of a2bdbd1, finding 2, and its second read, of e5cdd09,
        # finding 1)
        changed = copy.deepcopy(flow)
        steps   = _steps(changed, "run")
        claim   = steps[_index(steps, "Claim the gate run")]
        if change.startswith("the verifies"):
            filled = 'if [ -d "$RUNNER_TEMP/sealed" ]; then cp "$RUNNER_TEMP/sealed/"* "$RUNNER_TEMP/gate/"; fi\n'
            for name in ("Verify the gate's manifest", "Verify the downloaded copy"):
                step = steps[_index(steps, name)]
                step["run"] = step["run"].replace("set -euo pipefail\n", "set -euo pipefail\n" + filled)
        elif change == "the seal skips acceptance":
            steps[_index(steps, "Seal the gate's manifest")]["if"] = "inputs.mode == 'gate-plan'"
        elif change == "the upload skips acceptance":
            steps[_index(steps, "Keep the plan and its manifest")]["if"] = "inputs.mode == 'gate-plan'"
        elif change == "a later step copies the sealed plan to the apply's path":
            claim["run"] = 'cp "$RUNNER_TEMP/sealed/tfplan" "$RUNNER_TEMP/tfplan"\n' + claim["run"]
        elif change == "the seal keeps a local plan and the claim restores it":
            seal = steps[_index(steps, "Seal the gate's manifest")]
            seal["run"] += 'cp "$RUNNER_TEMP/tfplan" "$RUNNER_TEMP/local-plan"\n'
            claim["run"] = 'cd "$RUNNER_TEMP" && cp local-plan tfplan\n' + claim["run"]
        elif change == "a step is put between acceptance's verify and the apply":
            steps.insert(_index(steps, "Terraform apply"), {"name": "Note the plan", "run": "true\n"})
        elif change.startswith("the verifies end") or change.startswith("the verifies copy"):
            swap = (
                'if [ "$MODE" = acceptance ]; then cp "$RUNNER_TEMP/local-plan" "$RUNNER_TEMP/tfplan"; fi\n'
                if change.startswith("the verifies end")
                else 'cd "$RUNNER_TEMP" && cp local-plan tfplan\n'
            )
            for name in ("Verify the gate's manifest", "Verify the downloaded copy"):
                steps[_index(steps, name)]["run"] += swap
        else:
            apply = steps[_index(steps, "Terraform apply")]
            apply["run"] = apply["run"].replace('"$RUNNER_TEMP/tfplan"', '"$RUNNER_TEMP/local-plan"')
        assert handoff_faults(changed)


    def test_the_upload_keeps_the_gates_and_the_acceptances_plan_after_its_proofs(self, flow):
        steps = _steps(flow, "run")
        assert _if(steps, "Keep the plan and its manifest") == (
            "inputs.mode == 'gate-plan' || inputs.mode == 'acceptance'"
        )
        assert _index(steps, "Prove every state the saved plan carries") < _index(steps, "Seal the gate's manifest")
        assert _index(steps, "Seal the gate's manifest") < _index(steps, "Keep the plan and its manifest")


    def test_acceptance_downloads_the_same_artifact_back_by_its_own_run_id(self, flow):
        steps = _steps(flow, "run")
        deploy, back = _downloads(steps)
        assert steps[deploy]["if"] == "inputs.mode == 'deploy'"
        assert steps[back]["if"] == "inputs.mode == 'acceptance'"
        assert steps[back]["uses"] == steps[deploy]["uses"]
        mine, theirs = dict(steps[back]["with"]), dict(steps[deploy]["with"])
        assert mine.pop("run-id") == "${{ github.run_id }}"
        assert theirs.pop("run-id") == "${{ inputs.gate_run_id }}"
        assert mine == theirs
        assert back > _index(steps, "Keep the plan and its manifest")


    def test_acceptance_verifies_that_copy_with_the_deploys_own_script_against_its_own_values(self, flow):
        steps  = _steps(flow, "run")
        deploy = steps[_index(steps, "Verify the gate's manifest")]
        place  = _index(steps, "Verify the downloaded copy")
        back   = steps[place]
        assert back["if"] == "inputs.mode == 'acceptance'"
        assert back["run"] == deploy["run"]
        assert back["env"]["GATE_RUN_ID"] == "${{ github.run_id }}"
        assert back["env"]["GATE_RUN_ATTEMPT"] == "${{ github.run_attempt }}"
        own = ("GATE_RUN_ID", "GATE_RUN_ATTEMPT")
        assert {k: v for k, v in back["env"].items() if k not in own} == {
            k: v for k, v in deploy["env"].items() if k not in own
        }
        assert _downloads(steps)[1] < place < _index(steps, "Claim the gate run")
        assert 'cp "$RUNNER_TEMP/gate/tfplan" "$RUNNER_TEMP/tfplan"' in back["run"]
        verifies = [s for s in steps if 'python3 "$HELPER" verify' in s.get("run", "")]
        assert len(verifies) == 2


    def test_acceptance_claims_its_own_run_then_applies_the_copy_and_marks_the_claim(self, flow):
        steps = _steps(flow, "run")
        claim = steps[_index(steps, "Claim the gate run")]
        assert claim["env"]["GATE_RUN_ID"] == (
            "${{ inputs.mode == 'acceptance' && github.run_id || steps.gate.outputs.gate_run_id }}"
        )
        assert "terraform_gate_run" in claim["run"]
        assert _index(steps, "Verify the downloaded copy") < _index(steps, "Claim the gate run")
        assert _index(steps, "Claim the gate run") < _index(steps, "Terraform apply")
        assert '"$RUNNER_TEMP/tfplan"' in steps[_index(steps, "Terraform apply")]["run"]
        assert _if(steps, "Mark the gate run's deployment") == "always() && steps.claim.outcome == 'success'"


    def test_the_deploy_keeps_its_own_values(self, flow):
        # nothing of the deploy changes, its run, attempt and artifact the named gate's
        steps  = _steps(flow, "run")
        verify = steps[_index(steps, "Verify the gate's manifest")]
        assert verify["if"] == "inputs.mode == 'deploy'"
        assert verify["env"]["GATE_RUN_ID"] == "${{ steps.gate.outputs.gate_run_id }}"
        assert verify["env"]["GATE_RUN_ATTEMPT"] == "${{ steps.gate.outputs.gate_run_attempt }}"
        assert _index(steps, "Verify the gate's manifest") < _index(steps, "Set up Terraform for the deploy")
