"""
The two deploy reusables' stamps, the bot's path and the freshness rule, read from the workflows as GitHub runs them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION    = ROOT / ".github" / "actions" / "deploy-stamp" / "action.yml"
PYTHON    = "cd-python-vercel.yml"
NEXTJS    = "cd-nextjs-vercel.yml"
DEPLOYS   = (PYTHON, NEXTJS)
STAMP     = "Needless2Say/kriegerdataforge-cicd/.github/actions/deploy-stamp@main"
BOT       = "needs.authorize.outputs.path == 'bot'"
NOT_BOT   = "needs.authorize.outputs.path != 'bot'"
META_KEYS = ("kdf_version", "kdf_commit", "kdf_run_id", "kdf_run_attempt", "kdf_started_at")


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_bytes().decode("utf-8"))


def _jobs(name: str) -> dict:
    return _workflow(name)["jobs"]


def _steps(name: str, job: str = "deploy") -> list[dict]:
    return _jobs(name)[job]["steps"]


def _names(name: str, job: str = "deploy") -> list[str]:
    return [str(step.get("name")) for step in _steps(name, job)]


def _step(name: str, step_name: str, job: str = "deploy") -> dict:
    return next(step for step in _steps(name, job) if step.get("name") == step_name)


def _inputs(workflow: dict) -> dict:
    # yaml reads the bare key `on` as True
    return (workflow.get("on") or workflow.get(True))["workflow_call"]["inputs"]


def _deploy_commands(name: str) -> list[dict]:
    return [step for step in _steps(name) if "vercel deploy" in str(step.get("run", ""))]


# ── the stamp ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_first_step_records_the_start_before_any_setting_is_read(workflow):
    first = _steps(workflow)[0]
    assert first["name"] == "Record the start, before any setting is read" and first["id"] == "start"
    assert 'started=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" >> "$GITHUB_OUTPUT"' in first["run"]
    assert _steps(workflow)[1]["name"] == "Checkout", "the caller's checkout follows, its compare after it"


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_every_deploy_command_stamps_the_release_the_commit_the_run_and_the_start(workflow):
    commands = _deploy_commands(workflow)
    assert len(commands) == (1 if workflow == PYTHON else 2)
    for step in commands:
        run = step["run"]
        for key in META_KEYS:
            assert f'--meta "{key}=' in run, f"{step['name']} carries {key}"
        assert '--meta "kdf_run_id=$GITHUB_RUN_ID"' in run and '--meta "kdf_run_attempt=$GITHUB_RUN_ATTEMPT"' in run
        env = step["env"]
        assert env["STAMP_VERSION"] == "${{ inputs.version }}"
        assert env["STAMP_COMMIT"] == "${{ needs.release.outputs.sha }}"
        assert env["STAMP_STARTED"] == "${{ steps.start.outputs.started }}"


# ── the bot's path ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_deployer_check_names_the_deploy_profile_and_hands_on_its_path(workflow):
    authorize = _jobs(workflow)["authorize"]
    assert authorize["outputs"]["path"] == "${{ steps.gate.outputs.path }}"
    gate = _step(workflow, "Verify deployer is approved", "authorize")
    assert gate["id"] == "gate"
    assert gate["env"]["DEPLOY_PROFILE"] == "redeploy"
    assert gate["env"]["DEPLOY_ACTOR_ID"] == "${{ github.actor_id }}"
    assert gate["env"]["DEPLOY_EVENT"] == "${{ github.event_name }}"
    assert gate["env"]["DEPLOY_WORKFLOW_REF"] == "${{ github.workflow_ref }}"
    assert gate["env"]["DEPLOY_RUN_ATTEMPT"] == "${{ github.run_attempt }}"


def test_no_workflow_but_the_two_deploys_names_the_deploy_profile():
    # a bot is admitted only where a deploy job names itself, so every other caller of the check refuses it
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_bytes().decode("utf-8")
        if path.name in DEPLOYS:
            assert text.count("DEPLOY_PROFILE: redeploy") == 1, path.name
        else:
            assert "DEPLOY_PROFILE" not in text, path.name


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_bot_is_held_to_the_live_release_before_anything_is_installed(workflow):
    names = _names(workflow)
    hold  = _step(workflow, "Hold the bot to the live release")
    assert hold["if"] == BOT and hold["uses"] == STAMP
    assert hold["with"]["command"] == "bot"
    assert hold["with"]["version"] == "${{ inputs.version }}"
    assert hold["with"]["commit"] == "${{ needs.release.outputs.sha }}"
    first_install = min(i for i, step in enumerate(_steps(workflow)) if str(step.get("uses", "")).startswith(
        ("actions/setup-python@", "actions/setup-node@")))
    assert names.index("Hold the bot to the live release") < first_install
    assert names.index("Compare the checkout with the release commit") < names.index("Hold the bot to the live release")


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_bots_path_skips_the_prod_gates_search_and_a_human_release_keeps_it(workflow):
    check = _step(workflow, "Verify a successful PROD Gate run exists for this release", "verify-prod-gate")
    assert check["if"] == NOT_BOT
    note = _step(workflow, "The bot's redeploy, held to the live release in the deploy job", "verify-prod-gate")
    assert note["if"] == BOT and "check_prod_gate" not in note["run"]


def test_the_bot_never_migrates_whatever_the_caller_passes():
    for name in ("Install libpq (psycopg2 runtime dependency)", "Run Alembic migrations"):
        assert _step(PYTHON, name)["if"] == f"inputs.run_migrations == 'true' && {NOT_BOT}", name
    undo = _step(PYTHON, "Undo the migration, the new release will not serve")["if"]
    assert "steps.migrate.outcome == 'success'" in undo, "only a migration that ran is undone"


# ── the freshness rule ─────────────────────────────────────────────────────────
def test_the_python_deploy_reads_the_live_target_again_before_promoting_and_undoes_on_a_refusal():
    names = _names(PYTHON)
    order = [names.index(n) for n in (
        "Smoke the new deployment before it serves",
        "Hold the candidate to the live deployment's start",
        "Undo the migration, the new release will not serve",
        "Promote the deployment to the production domains",
    )]
    assert order == sorted(order), names
    fresh = _step(PYTHON, "Hold the candidate to the live deployment's start")
    assert fresh["uses"] == STAMP and fresh["id"] == "fresh" and "if" not in fresh, "the owner's and the bot's alike"
    assert fresh["with"]["command"] == "fresh"
    assert fresh["with"]["started"] == "${{ steps.start.outputs.started }}"
    assert fresh["with"]["path"] == "${{ needs.authorize.outputs.path }}"
    assert "steps.fresh.outcome == 'failure'" in _step(
        PYTHON,
        "Undo the migration, the new release will not serve",
    )["if"]


def test_the_owners_nextjs_deploy_is_held_to_the_live_start_immediately_before_its_one_prod_call():
    names = _names(NEXTJS)
    fresh = names.index("Hold this deploy to the live deployment's start")
    assert names[fresh + 1] == "Deploy prebuilt artifact to Vercel"
    step = _step(NEXTJS, "Hold this deploy to the live deployment's start")
    assert step["if"] == NOT_BOT and step["uses"] == STAMP
    assert step["with"]["command"] == "fresh" and step["with"]["path"] == "human"
    deploy = _step(NEXTJS, "Deploy prebuilt artifact to Vercel")
    assert deploy["if"] == NOT_BOT
    assert "vercel deploy --prebuilt --prod --yes" in deploy["run"] and "--skip-domain" not in deploy["run"]


def test_a_bots_nextjs_run_deploys_without_the_domains_smokes_its_route_then_promotes():
    names = _names(NEXTJS)
    path  = [
        "The bot's candidate, deployed without the domains",
        "The bot's candidate, smoked on its route before it serves",
        "The bot's candidate, held to the live deployment's start",
        "The bot's candidate, promoted to the production domains",
    ]
    assert [names.index(n) for n in path] == sorted(names.index(n) for n in path)
    for name in path:
        assert _step(NEXTJS, name)["if"] == BOT, name
    candidate = _step(NEXTJS, path[0])
    assert "--skip-domain" in candidate["run"] and 'echo "url=$URL" >> "$GITHUB_OUTPUT"' in candidate["run"]
    smoke = _step(NEXTJS, path[1])
    assert smoke["env"]["SMOKE_PATH"] == "${{ inputs.smoke_path }}"
    assert smoke["env"]["BYPASS"] == "${{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}"
    assert '-H "@$BYPASS_HEADER"' in smoke["run"] and "umask 077" in smoke["run"]
    assert "trap 'rm -f \"$BYPASS_HEADER\"' EXIT" in smoke["run"]
    assert 'if [ "$code" = "200" ]' in smoke["run"] and "exit 1" in smoke["run"]
    fresh = _step(NEXTJS, path[2])
    assert fresh["uses"] == STAMP and fresh["with"]["path"] == "bot"
    promote = _step(NEXTJS, path[3])
    assert 'vercel promote "$DEPLOY_URL"' in promote["run"]
    assert promote["env"]["DEPLOY_URL"] == "${{ steps.candidate.outputs.url }}"


def test_a_bots_nextjs_run_with_no_smoke_route_is_refused_before_anything_is_installed():
    names  = _names(NEXTJS)
    refuse = _step(NEXTJS, "Refuse a bot's run with no smoke route")
    assert refuse["if"] == f"{BOT} && !startsWith(inputs.smoke_path, '/')"
    assert "exit 1" in refuse["run"]
    assert names.index("Refuse a bot's run with no smoke route") < names.index("Set up Node.js")
    smoke_path = _inputs(_workflow(NEXTJS))["smoke_path"]
    assert smoke_path["required"] is False and smoke_path["default"] == "", "every caller keeps working unchanged"


# ── the group and the grants ───────────────────────────────────────────────────
@pytest.mark.parametrize("workflow, group", [
    (PYTHON, "kdf-database-${{ github.repository }}-${{ inputs.environment }}"),
    (NEXTJS, "kdf-deploy-${{ github.repository }}-${{ inputs.environment }}"),
])
def test_each_deploy_holds_one_group_per_app_and_environment_no_caller_can_name(workflow, group):
    concurrency = _jobs(workflow)["deploy"]["concurrency"]
    assert concurrency == {"group": group, "cancel-in-progress": False}
    # the callers' own groups are `cd-<environment>` (the hub, the auth UI) or none (the templates and the apps)
    assert not group.startswith("cd-") and group.startswith("kdf-")


@pytest.mark.parametrize("workflow", DEPLOYS)
def test_the_deploy_jobs_grants_are_unchanged(workflow):
    assert _jobs(workflow)["deploy"]["permissions"] == {"contents": "read"}


def test_the_action_runs_the_stamp_script_and_trims_and_masks_the_token():
    action = yaml.safe_load(ACTION.read_bytes().decode("utf-8"))
    run    = action["runs"]["steps"][0]["run"]
    assert '"$GITHUB_ACTION_PATH/../../../scripts/deploy_stamp.py"' in run
    assert "tr -d '[:space:]'" in run and 'echo "::add-mask::$VERCEL_TOKEN"' in run
    assert (ROOT / "scripts" / "deploy_stamp.py").is_file()
