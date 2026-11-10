"""
The inventory of every credential that can write, held to cicd's `ops` environment (the secrets fence, step 6).

A key that a pull request's job can read grants reads alone, and a key that can write sits in `ops`, an environment
held to `main` that waits for the owner's approval. So every job that reads the writing App's pair, `CICD_PAT`, the
Vercel master token, a staged value or the reader pair it distributes names `ops`, after the owner check, in a
workflow no branch or pull request starts. The repository pair `KDF_APP_ID` and `KDF_APP_PRIVATE_KEY` becomes the
read only App's, so every mint from it asks for reads alone, but for the one bootstrap the sitting runs while the old
writer still holds those names. A scheduled `ops` job skips until the owner arms it. No workflow commits or pushes. The
cron copies live in cicd's `dev` and `prod`, never in a repository secret.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml
from tests.test_owner_check import expression_value

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REGISTRY  = ROOT / "scripts" / "secret_registry.json"
CHECK     = "./.github/workflows/_authorize-owner.yml"
MINT      = "actions/create-github-app-token@"
WRITERS   = {"KDF_WRITER_APP_ID", "KDF_WRITER_APP_PRIVATE_KEY", "CICD_PAT", "VERCEL_MASTER_TOKEN"}
# every staging slot the registry names (D-099), and the projects flow's classic token, a name of its own
STAGING    = {
    slot["slot"]
    for entry in json.loads(REGISTRY.read_text(encoding = "utf-8"))["secrets"]
    for slot in entry.get("staging", [])
} | {"PROVISION_PROJECTS_PAT"}
READER_OPS = {"KDF_READER_APP_ID", "KDF_READER_APP_PRIVATE_KEY"}
HELD       = WRITERS | STAGING | READER_OPS
CRON       = {
    "KDF_HUB_URL_DEV": ("dev", "KDF_HUB_URL"),
    "KDF_HUB_URL_PROD": ("prod", "KDF_HUB_URL"),
    "KDF_HUB_CRON_SECRET_DEV": ("dev", "KDF_HUB_CRON_SECRET"),
    "KDF_HUB_CRON_SECRET_PROD": ("prod", "KDF_HUB_CRON_SECRET"),
}
REPORTS    = ("REPORTS_CRON_SECRET_FITNESS_APP", "REPORTS_CRON_SECRET_TIFFANYS_SPACE")
CICD       = "Needless2Say/kriegerdataforge-cicd"
CONTEXT    = "Needless2Say/kriegerdataforge-context"
BOOTSTRAP  = ("ops-distribute-app-secrets.yml", "run", "bootstrap-token")
ARM        = "vars.ARM_OPS_SCHEDULE"
# a mint whose token writes Actions variables, its workflow, job, step id and the one repository it is held to
VARIABLES_MINTS = (
    ("rotate-vercel-tokens.yml", "rotate", "facts-token", "kriegerdataforge-cicd"),
    ("distribute-staged.yml", "distribute", "facts-token", "kriegerdataforge-cicd"),
    ("ops-setup-e2e.yml", "setup", "app-token", "${{ steps.fields.outputs.repo }}"),
)
# a key shaped as an RSA key is, one DER sequence whose declared length is the bytes that follow, and the same key with
# interior lines removed, its markers built from two parts so no line of this file is a whole key block to a scanner
BEGIN     = "-----BEGIN RSA " + "PRIVATE KEY-----"
END       = "-----END RSA " + "PRIVATE KEY-----"
DER       = b"\x30\x82\x04\xa6" + bytes(range(256)) * 4 + bytes(range(166))
BODY      = base64.b64encode(DER).decode()
PEM       = f"{BEGIN}\n" + "\n".join(textwrap.wrap(BODY, 64)) + f"\n{END}\n"
TRUNCATED = "\n".join(PEM.splitlines()[:3] + PEM.splitlines()[9:]) + "\n"
NOT_DER   = f"{BEGIN}\n" + "\n".join(textwrap.wrap("A" * 1600, 64)) + f"\n{END}\n"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def _events(data: dict) -> list[str]:
    # the YAML reader takes the key `on` for True
    on = data.get("on", data.get(True)) or {}
    return [on] if isinstance(on, str) else list(on)


def _jobs() -> list[tuple[str, str, dict, dict]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = _load(path)
        for name, job in (data.get("jobs") or {}).items():
            found.append((path.name, name, job, data))
    return found


def _job_params() -> list:
    return [pytest.param(*found, id = f"{found[0]}:{found[1]}") for found in _jobs()]


def _secrets(job: dict) -> set[str]:
    return set(re.findall(r"secrets\.([A-Z0-9_]+)", json.dumps(job)))


def _steps(job: dict) -> list[dict]:
    return job.get("steps") or []


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)

# ======================================================================================================================
# The writers in `ops`
# ======================================================================================================================

@pytest.mark.parametrize(("workflow", "name", "job", "data"), _job_params())
def test_every_job_holding_a_writer_or_a_staged_value_names_ops_after_the_owner_check(workflow, name, job, data):
    held = _secrets(job) & HELD
    if not held:
        assert job.get("environment") != "ops", f"{workflow} job {name} names ops and reads nothing held there"
        return
    assert job.get("environment") == "ops", f"{workflow} job {name} reads {sorted(held)} outside ops"
    checks = [other for other, value in data["jobs"].items() if value.get("uses") == CHECK]
    assert checks and set(checks) <= set(_needs(job)), f"{workflow} job {name} runs in ops before the owner check"


def test_no_workflow_with_an_ops_job_starts_from_a_branch():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = _load(path)
        if any(job.get("environment") == "ops" for job in (data.get("jobs") or {}).values()):
            started = set(_events(data))
            assert not started & {"push", "pull_request", "pull_request_target", "workflow_run"}, path.name


def test_the_writers_key_and_id_reach_a_mint_alone():
    # a value read anywhere else could be copied, printed or sent, so the writer's pair is a mint's input and nothing
    for workflow, name, job, _ in _jobs():
        for step in _steps(job):
            text = json.dumps(step)
            if "KDF_WRITER_APP_" not in text:
                continue
            assert str(step.get("uses", "")).startswith(MINT), f"{workflow} job {name} step {step.get('name')}"
            with_ = step.get("with", {})
            assert with_.get("private-key") == "${{ secrets.KDF_WRITER_APP_PRIVATE_KEY }}", f"{workflow} {name}"
            assert with_.get("client-id", with_.get("app-id")) == "${{ secrets.KDF_WRITER_APP_ID }}", workflow


def test_every_mint_from_the_repository_pair_asks_for_reads_alone():
    for workflow, name, job, _ in _jobs():
        for step in _steps(job):
            with_ = step.get("with", {})
            if not str(step.get("uses", "")).startswith(MINT) or "KDF_APP_PRIVATE_KEY }}" not in str(with_):
                continue
            if (workflow, name, step.get("id")) == BOOTSTRAP:
                continue
            asked = {key: value for key, value in with_.items() if key.startswith("permission-")}
            assert asked, f"{workflow} job {name} mints the App's whole set"
            assert set(asked.values()) == {"read"}, f"{workflow} job {name} asks for {asked}"


def test_the_bootstrap_is_the_one_mint_of_a_write_from_the_repository_pair_and_runs_in_ops_for_its_mode_alone():
    # the sitting's bootstrap mints from the old writer under the repository names, and once the read only App's pair
    # holds those names its secrets write is refused, so the mode fails closed by itself
    workflow, name, step_id = BOOTSTRAP
    job = _load(WORKFLOWS / workflow)["jobs"][name]
    assert job.get("environment") == "ops"
    step = next(step for step in _steps(job) if step.get("id") == step_id)
    assert str(step["uses"]).startswith(MINT)
    assert step["with"]["private-key"] == "${{ secrets.KDF_APP_PRIVATE_KEY }}"
    assert step["with"]["client-id"] == "${{ secrets.KDF_APP_ID }}"
    assert step["if"] == "steps.fields.outputs.mode == 'bootstrap'"
    asked = {key: value for key, value in step["with"].items() if key.startswith("permission-")}
    assert asked == {"permission-secrets": "write"}
    writer = next(step for step in _steps(job) if step.get("id") == "app-token")
    assert "steps.fields.outputs.mode != 'bootstrap'" in writer["if"]


@pytest.mark.parametrize(("workflow", "name", "step_id", "repository"), VARIABLES_MINTS)
def test_a_variables_mint_asks_for_no_filter_and_is_held_to_one_repository(workflow, name, step_id, repository):
    # the token API has no key for the Variables permission, so a mint asking for `variables` is refused, 422, "The
    # permissions requested are not granted to this installation", the sitting's record-expiry run 42728994281. so a
    # mint whose token writes variables asks for no filter, taking the writing App's set, and is held to the one
    # repository it writes instead, in ops after the owner's approval
    job  = _load(WORKFLOWS / workflow)["jobs"][name]
    mint = next(step for step in _steps(job) if step.get("id") == step_id)
    assert str(mint["uses"]).startswith(MINT)
    assert not [key for key in mint["with"] if key.startswith("permission-")], f"{workflow} {step_id}"
    assert mint["with"]["repositories"] == repository
    assert job.get("environment") == "ops"


def test_the_staged_run_reads_exactly_the_registrys_slots_each_only_when_selected():
    # a workflow cannot list an environment's secrets by expression, so its slots are a second list held to the
    # registry's here (D-099, the Round Table's L20), each passed only when the dispatch names it
    job   = _load(WORKFLOWS / "distribute-staged.yml")["jobs"]["distribute"]
    step  = next(step for step in _steps(job) if "--mode paste-staged" in str(step.get("run", "")))
    slots = STAGING - {"PROVISION_PROJECTS_PAT"}
    named = {key for key in step["env"] if key.endswith("_NEW")}
    assert named == slots
    for slot in slots:
        value = " ".join(str(step["env"][slot]).split())
        assert value == f"${{{{ contains(inputs.slots, '{slot}') && secrets.{slot} || '' }}}}", slot
    assert job.get("environment") == "ops"
    data = _load(WORKFLOWS / "distribute-staged.yml")
    assert _events(data) == ["workflow_dispatch"]
    assert data["concurrency"] == {"group": "ops-distribute-staged", "cancel-in-progress": False}


def test_the_rotation_never_records_a_staged_tokens_fact():
    # the staged distribution alone writes the packages and npm tokens' facts, from the token it sends, so no second
    # writer can overwrite a newer fact or leave a failed read in its way (Codex's third and fourth reads of D-099)
    text = (WORKFLOWS / "rotate-vercel-tokens.yml").read_text(encoding = "utf-8")
    job  = _load(WORKFLOWS / "rotate-vercel-tokens.yml")["jobs"]["rotate"]
    step = next(step for step in _steps(job) if step.get("name") == "Record the expiry facts")
    assert " ".join(step["run"].split()).endswith("--secrets CICD_PAT,VERCEL_MASTER_TOKEN,VERCEL_DEPLOYMENT_TOKEN")
    assert "GH_PACKAGES_PAT" not in step.get("env", {})
    assert "secrets.GH_PACKAGES_PAT" not in text and "secrets.GH_NPM_TOKEN" not in text


def test_no_workflow_reads_the_retired_shared_slot():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert "SECRET_VALUE_NEW" not in path.read_text(encoding = "utf-8"), path.name


def test_no_mint_asks_for_the_variables_permission_the_token_api_lacks():
    for workflow, name, job, _ in _jobs():
        for step in _steps(job):
            if str(step.get("uses", "")).startswith(MINT):
                assert "permission-variables" not in (step.get("with") or {}), f"{workflow} job {name}"


def test_the_e2e_setup_copies_the_readers_pair():
    job  = _load(WORKFLOWS / "ops-setup-e2e.yml")["jobs"]["setup"]
    copy = next(step for step in _steps(job) if "gh secret set" in str(step.get("run", "")))
    assert copy["env"]["KDF_APP_ID"] == "${{ secrets.KDF_READER_APP_ID }}"
    assert copy["env"]["KDF_APP_PRIVATE_KEY"] == "${{ secrets.KDF_READER_APP_PRIVATE_KEY }}"


def _bash() -> str | None:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


@pytest.mark.parametrize(("app_id", "key", "passes"), [
    ("123456", PEM, True),
    ("not-an-id", PEM, False),
    ("", PEM, False),
    ("123456", "", False),
    ("123456", "a key that is no pem", False),
    (PEM, "123456", False),
    # a header alone or a truncated key passed, Codex's third read of step 6
    ("123456", BEGIN, False),
    ("123456", f"{BEGIN}\n{END}\n", False),
    ("123456", f"{BEGIN}\nMIIshort\n{END}\n", False),
    ("123456", "junk\n" + PEM, False),
    # a key of 512 and more body characters with interior lines removed passed, Codex's fourth read of step 6
    ("123456", TRUNCATED, False),
    ("123456", NOT_DER, False),
])
def test_the_e2e_setup_checks_the_readers_pair_before_anything_is_written(tmp_path, app_id, key, passes):
    # a malformed pair copied over a target's working one would break its lanes (Codex's second read of step 6)
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    steps       = _steps(_load(WORKFLOWS / "ops-setup-e2e.yml")["jobs"]["setup"])
    names       = [step.get("name") for step in steps]
    check       = next(
        step for step in steps if step.get("name") == "Check the read only App's pair before anything is written"
    )
    first_write = next(index for index, step in enumerate(steps) if "gh variable set" in str(step.get("run", "")))
    assert names.index(check["name"]) < first_write
    assert check["env"]["KDF_APP_ID"] == "${{ secrets.KDF_READER_APP_ID }}"
    script = tmp_path / "check.sh"
    script.write_text(check["run"], encoding = "utf-8", newline = "\n")
    run = subprocess.run(
        [bash, script.as_posix()],
        env = {**os.environ, "KDF_APP_ID": app_id, "KDF_APP_PRIVATE_KEY": key},
        capture_output = True,
        text = True,
    )
    assert (run.returncode == 0) == passes, run.stdout + run.stderr
    assert "123456" not in run.stdout and BODY[8:48] not in run.stdout, "no value is printed"


def test_a_paste_with_vercel_targets_hands_its_step_the_master_token():
    # the packages token's paste writes six Vercel copies, which the engine skips with no master token, so a run that
    # left them stale would report success (Codex's fourth read of step 6)
    registry = {entry["name"]: entry for entry in json.loads(REGISTRY.read_text(encoding = "utf-8"))["secrets"]}
    for workflow, name, job, _ in _jobs():
        for step in _steps(job):
            pasted = re.search(r"rotate_secret\.py --mode paste --secrets (\w+)", str(step.get("run", "")))
            if pasted and registry[pasted.group(1)].get("vercel_env_vars"):
                assert step.get("env", {}).get("VERCEL_MASTER_TOKEN") == "${{ secrets.VERCEL_MASTER_TOKEN }}", workflow


def test_no_workflow_commits_or_pushes():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding = "utf-8")
        assert not re.search(r"git (commit|push)\b|gh pr create", text), path.name


@pytest.mark.parametrize("workflow", ["check-oidc-rp-drift.yml", "check-secret-expiry.yml"])
def test_the_monitors_hold_no_writer(workflow):
    for name, job in _load(WORKFLOWS / workflow)["jobs"].items():
        assert not _secrets(job) & HELD, f"{workflow} job {name}"
        assert job.get("environment") != "ops", f"{workflow} job {name}"


def _ops_scheduled() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = _load(path)
        if "schedule" not in _events(data):
            continue
        for name, job in data["jobs"].items():
            if job.get("environment") == "ops":
                found.append((path.name, name, str(job.get("if", "true"))))
    return found


def _schedule_values(armed: str) -> dict[str, str]:
    return {
        "github.event_name": "schedule",
        "github.run_attempt": "1",
        "github.repository": CICD,
        "github.repository_owner": "Needless2Say",
        "github.actor": "github-actions[bot]",
        "github.triggering_actor": "github-actions[bot]",
        ARM: armed,
        "vars.USE_GITHUB_APP": "true",
        "needs.authorize.result": "skipped",
        "needs.due.result": "success",
        "needs.due.outputs.due": "true",
        # the deployment token's due job names the mode it found (D-100)
        "needs.due.outputs.mode": "rotate",
    }


def test_a_scheduled_ops_job_exists_and_skips_until_the_owner_arms_it():
    found = _ops_scheduled()
    assert found, "the monthly rotation keeps a scheduled ops job"
    for workflow, name, condition in found:
        assert not expression_value(condition, _schedule_values("")), f"{workflow} job {name} runs unarmed"
        assert expression_value(condition, _schedule_values("true")), f"{workflow} job {name} never runs armed"


def test_the_token_s_ops_job_asks_no_approval_on_a_day_with_nothing_due():
    found = [entry for entry in _ops_scheduled() if entry[0] == "rotate-vercel-tokens.yml"]
    assert found, "the deployment token keeps a scheduled ops job"
    for _, name, condition in found:
        for mode in ("none", ""):
            values = {**_schedule_values("true"), "needs.due.outputs.mode": mode}
            assert not expression_value(condition, values), f"job {name} runs with the due job's mode {mode!r}"
        values = {**_schedule_values("true"), "needs.due.result": "failure"}
        assert not expression_value(condition, values), f"job {name} runs after a failed due job"

# ======================================================================================================================
# The registry
# ======================================================================================================================

def _entries() -> dict[str, dict]:
    return {entry["name"]: entry for entry in json.loads(REGISTRY.read_text(encoding = "utf-8"))["secrets"]}


@pytest.mark.parametrize("name", sorted(CRON))
def test_each_hub_cron_copy_lives_in_its_own_cicd_environment_alone(name):
    entry = _entries()[name]
    environment, under = CRON[name]
    assert not entry.get("github_repo_secrets"), f"{name} keeps a repository target"
    assert entry["github_env_secrets"] == [{"repo": CICD, "environment": environment, "secret_name": under}]


@pytest.mark.parametrize("name", REPORTS)
def test_each_reports_cron_copy_lives_in_cicds_dev_and_prod(name):
    entry = _entries()[name]
    assert not entry.get("github_repo_secrets"), f"{name} keeps a repository target"
    assert sorted(entry["github_env_secrets"], key = lambda target: target["environment"]) == [
        {"repo": CICD, "environment": "dev", "secret_name": name},
        {"repo": CICD, "environment": "prod", "secret_name": name},
    ]


@pytest.mark.parametrize("name", ["KDF_APP_ID", "KDF_APP_PRIVATE_KEY"])
def test_the_app_pair_goes_to_cicd_and_never_to_the_context_repo(name):
    repos = [target["repo"] for target in _entries()[name]["github_repo_secrets"]]
    assert CICD in repos
    assert CONTEXT not in repos, "only the watch read the context copy, and it reads its own App now"
    assert len(repos) == len(set(repos))


def test_the_cron_workflows_read_each_copy_in_the_environment_that_holds_it():
    names = {under for _, under in CRON.values()} | set(REPORTS)
    for workflow, name, job, _ in _jobs():
        read = _secrets(job) & (names | set(CRON))
        if not read:
            continue
        assert not read & set(CRON), f"{workflow} job {name} reads a repository era name {sorted(read & set(CRON))}"
        environment = str(job.get("environment", ""))
        assert environment and environment != "ops", f"{workflow} job {name} reads {sorted(read)} outside dev or prod"
