"""
Contract tests for the two reusable Vercel deploys, `cd-nextjs-vercel.yml` and `cd-python-vercel.yml`.

Rows 40 and 42 of the auth UI's deferred register and row 83 of the hub's (D-016). The deploy token is
read by the steps that call Vercel's API alone, never written to $GITHUB_ENV, the Next.js deploy
installs once, neither job holds a permission nothing uses, neither header claims a reviewer no
environment has, and the Python deploy deploys without the domains, migrates, smokes the new
deployment and only then promotes it, undoing the migration when the smoke fails. Text level, the
repository keeps no YAML parser among its test dependencies, except that the migrate step's own shell
runs here under bash against an alembic that prints what the hub's env.py prints, the case the first DEV
dispatch of 2026-09-25 met (D-018).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SCRIPTS   = Path(__file__).resolve().parents[1]
NEXTJS    = (WORKFLOWS / "cd-nextjs-vercel.yml").read_text(encoding = "utf-8")
PYTHON    = (WORKFLOWS / "cd-python-vercel.yml").read_text(encoding = "utf-8")

# the lanes a consumer's PROD Gate calls on the release tag, through its ci.yml or beside it
# (D-024, D-025, D-026, D-027)
TEST_LANES = (
    "ci-python-tests.yml",
    "ci-python-integration.yml",
    "ci-python-lint.yml",
    "ci-python-kdf-fmt.yml",
    "ci-python-typecheck.yml",
    "ci-python-security.yml",
    "ci-vercel-compactor.yml",
    "ci-nextjs-tests.yml",
    "ci-nextjs-integration.yml",
    "ci-nextjs-mutation.yml",
    "ci-python-mutation.yml",
    "ci-python-system.yml",
    "ci-nextjs-lint-typecheck.yml",
    "ci-nextjs-build.yml",
    "ci-npm-audit.yml",
    "secret-scan.yml",
)

# each Python lane that can clone a private package, and the one step of it that does. Seven clone in their fetch job,
# the job that names a secret, and install in a job that names none (D-035). The style lane installs only the pinned
# formatter and stays one job
CLONING_STEP = {
    "ci-python-tests.yml": "Clone the private packages as bare mirrors",
    "ci-python-integration.yml": "Clone the private packages as bare mirrors",
    "ci-python-lint.yml": "Clone the private packages as bare mirrors",
    "ci-python-typecheck.yml": "Clone the private packages as bare mirrors",
    "ci-python-mutation.yml": "Clone the private packages as bare mirrors",
    "ci-python-system.yml": "Clone the private packages as bare mirrors",
    "ci-python-kdf-fmt.yml": "Install kdf-fmt (pinned, stdlib-only — no consumer deps)",
    "ci-python-security.yml": "Clone the private packages as bare mirrors",
}

# the step of each split lane that installs or audits the caller's tree, in the job that names no secret
INSTALL_STEP = {
    "ci-python-tests.yml": "Install dependencies",
    "ci-python-integration.yml": "Install dependencies",
    "ci-python-lint.yml": "Install dependencies",
    "ci-python-typecheck.yml": "Install dependencies",
    "ci-python-mutation.yml": "Install dependencies",
    "ci-python-system.yml": "Install dependencies",
    "ci-python-security.yml": "Audit requirements.txt",
}

# a stand in for alembic whose env.py prints two lines of its own to stdout, the hub's shape
FAKE_ALEMBIC = """#!/usr/bin/env bash
echo "[Alembic] Using PROD environment"
echo "[Alembic] Database URL: postgresql://u:****@h/d"
if [ "$1" = "upgrade" ]; then
  echo "upgraded" >> "$FAKE_ALEMBIC_MARK"
  exit 0
fi
case "$FAKE_ALEMBIC_MODE" in
  revision)
    echo "Current revision(s) for postgresql://u:XXXXX@h/d:"
    echo "Rev: f4b8d2e6a1c9 (head)"
    echo "Parent: e1a4c7b9f205"
    ;;
  empty)
    echo "Current revision(s) for postgresql://u:XXXXX@h/d:"
    ;;
  noise)
    ;;
  broken)
    echo "FAILED: could not connect" >&2
    exit 1
    ;;
esac
"""


def _steps(text: str) -> list[str]:
    """
    The step names of a workflow, in order.
    """
    return re.findall(r"^\s+- name: (.+)$", text, flags = re.MULTILINE)


def _step(text: str, name: str) -> str:
    """
    One step's text, from its name to the next step's.
    """
    start = text.index(f"- name: {name}")
    rest  = text[start + 1:]
    end   = re.search(r"^\s+- name: ", rest, flags = re.MULTILINE)
    return text[start:start + 1 + (end.start() if end else len(rest))]


@pytest.mark.parametrize("text", [NEXTJS, PYTHON], ids = ["nextjs", "python"])
def test_the_deploy_verifies_the_releases_prod_gate_run_before_deploying(text):
    """
    A release deploys to prod only after its own PROD Gate run passed, the gate sits between the deployer check
    and the deploy job and reads the runs with the job token (D-019, D-027).
    """
    # the usage comment in the header names a `deploy:` job too, so the anchors start at a line
    assert "\n  verify-prod-gate:\n" in text
    assert "verify-e2e" not in text and "check_e2e" not in text, "the journey alone opens nothing"
    gate = text[text.index("\n  verify-prod-gate:\n"):text.index("\n  deploy:\n")]
    assert "needs: authorize" in gate
    assert "actions: read" in gate, "the runs listing needs it, the calling cd.yml grants it"
    assert "python3 _kdf_cicd/scripts/check_prod_gate.py" in gate
    assert (SCRIPTS / "check_prod_gate.py").is_file() and not (SCRIPTS / "check_e2e.py").exists()
    assert "PROD_GATE_WORKFLOW" not in gate, "no deploy names another workflow to read"
    for line in (
        "DEPLOY_REPO: ${{ github.repository }}",
        "DEPLOY_VERSION: ${{ inputs.version }}",
        "DEPLOY_ENVIRONMENT: ${{ inputs.environment }}",
        "GH_TOKEN: ${{ github.token }}",
    ):
        assert line in gate
    deploy = text[text.index("\n  deploy:\n"):]
    assert "needs: [authorize, verify-prod-gate]" in deploy
    assert "actions: read" in text[:text.index("name: CD")], "the usage header tells the caller to grant it"


@pytest.mark.parametrize("text", [NEXTJS, PYTHON], ids = ["nextjs", "python"])
def test_no_deploy_holds_a_permission_nothing_uses_or_claims_a_reviewer(text):
    assert "id-token: write" not in text
    assert "Requires approval from the configured reviewers" not in text
    assert "Pauses for required reviewer approval" not in text
    assert "repository secret" in text, "the empty token diagnostic names the secret's real scope"
    assert "environment secret on this repo" not in text


def test_the_nextjs_deploy_token_reaches_the_two_vercel_calls_alone():
    assert '>> "$GITHUB_ENV"' not in NEXTJS, "nothing is written where every later step inherits it"
    assert 'echo "token=$TOKEN" >> "$GITHUB_OUTPUT"' in NEXTJS
    for step in ("Pull Vercel project settings and build env", "Deploy prebuilt artifact to Vercel"):
        assert "VERCEL_TOKEN: ${{ steps.token.outputs.token }}" in _step(NEXTJS, step), step
    build = _step(NEXTJS, "Build")
    assert "--token" not in build and "steps.token" not in build, "the build calls no Vercel API"
    assert "GH_NPM_TOKEN: ${{ secrets.GH_NPM_TOKEN }}" in build, "the build's own install keeps the npm credential"


def test_the_nextjs_deploy_installs_once():
    assert "Install dependencies" not in _steps(NEXTJS)
    assert "run: npm ci" not in NEXTJS
    assert NEXTJS.count("run: vercel build") == 1


def test_the_python_deploy_deploys_migrates_smokes_then_promotes():
    names = _steps(PYTHON)
    order = [names.index(n) for n in (
        "Deploy to Vercel, without the domains",
        "Run Alembic migrations",
        "Smoke the new deployment before it serves",
        "Undo the migration, the new release will not serve",
        "Promote the deployment to the production domains",
    )]
    assert order == sorted(order), names
    deploy = _step(PYTHON, "Deploy to Vercel, without the domains")
    assert "vercel deploy --prod --yes --skip-domain" in deploy
    assert 'echo "url=$URL" >> "$GITHUB_OUTPUT"' in deploy
    assert '>> "$GITHUB_ENV"' not in PYTHON


def test_the_python_smoke_gates_the_promotion_and_undoes_the_migration_on_failure():
    smoke = _step(PYTHON, "Smoke the new deployment before it serves")
    assert "/healthz" in smoke and 'if [ "$code" = "200" ]' in smoke
    assert "x-vercel-protection-bypass" in smoke, "a protected deployment URL needs the project's bypass secret"
    # the protection answers a plain request with a 302 to vercel.com's sign in, measured 2026-09-25 on the
    #  hub's DEV project, so the redirect target is read beside the code and both forms name the secret
    assert "%{http_code} %{redirect_url}" in smoke
    assert 'https://vercel.com/sso-api*) protected="yes"' in smoke
    assert 'if [ "$code" = "401" ]; then protected="yes"; fi' in smoke
    assert "no VERCEL_AUTOMATION_BYPASS_SECRET is set" in smoke
    assert "it refused VERCEL_AUTOMATION_BYPASS_SECRET" in smoke, "a set secret the project does not know"
    # a 5xx names Vercel's error code and says the exception is in the deployment's runtime logs, the second
    #  DEV dispatch read `500` six times and nothing more
    assert '-D "$HEADERS"' in smoke and 'tolower($1) == "x-vercel-error:"' in smoke
    assert 'elif [ "${code#5}" != "$code" ]; then' in smoke
    assert "runtime logs in Vercel" in smoke
    undo = _step(PYTHON, "Undo the migration, the new release will not serve")
    assert "steps.smoke.outcome == 'failure'" in undo
    assert 'alembic downgrade "$BEFORE"' in undo
    promote = _step(PYTHON, "Promote the deployment to the production domains")
    assert "vercel promote" in promote and "steps.deploy.outputs.url" in promote


def test_the_python_migrate_step_reads_the_revision_from_alembics_own_line():
    migrate = _step(PYTHON, "Run Alembic migrations")
    undo    = _step(PYTHON, "Undo the migration, the new release will not serve")
    # alembic writes `Rev: <id>` in its verbose report, a repo's env.py may print anything else to stdout
    assert 'REPORT="$(alembic current --verbose)"' in migrate
    assert "awk '$1 == \"Rev:\" { print $2; exit }' <<< \"$REPORT\"" in migrate
    assert "grep -q '^Current revision(s) for ' <<< \"$REPORT\"" in migrate, "base only on alembic's own word"
    assert "2>/dev/null" not in migrate, "a failing alembic is seen, never silenced into an empty capture"
    assert 'echo "before=${BEFORE:-base}" >> "$GITHUB_OUTPUT"' in migrate
    for step in (migrate, undo):
        assert "ENVIRONMENT: ${{ inputs.environment }}" in step, "the state the run deploys to, the label env.py prints"


def _migrate_shell() -> str:
    """
    The migrate step's shell, dedented, as the runner executes it.
    """
    step  = _step(PYTHON, "Run Alembic migrations")
    block = step.split("run: |\n", 1)[1].split("\n        env:", 1)[0]
    return "\n".join(line[10:] for line in block.split("\n")) + "\n"


def _bash() -> str | None:
    """
    A bash that runs the step's shell here. Git's on Windows, System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


@pytest.mark.parametrize("mode, before, upgraded", [
    ("revision", "before=f4b8d2e6a1c9", True),   # the DEV dispatch of 2026-09-25 recorded `[Alembic]` here
    ("empty",    "before=base",         True),   # a fresh database, alembic's header and no revision
    ("noise",    None,                  False),  # env.py's lines alone prove nothing, the step stops first
    ("broken",   None,                  False),  # a failing alembic fails the step, never an empty capture
], ids = ["revision", "empty", "noise", "broken"])
def test_the_revision_capture_reads_alembics_line_past_an_env_that_prints(tmp_path, mode, before, upgraded):
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "alembic"
    fake.write_text(FAKE_ALEMBIC, encoding = "utf-8", newline = "\n")
    fake.chmod(0o755)
    shell = tmp_path / "migrate.sh"
    shell.write_text(_migrate_shell(), encoding = "utf-8", newline = "\n")
    output = tmp_path / "github_output"
    mark   = tmp_path / "mark"
    output.write_text("")
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(fakebin), env.get("PATH", "")])
    env["FAKE_ALEMBIC_MODE"] = mode
    env["FAKE_ALEMBIC_MARK"] = mark.as_posix()
    env["GITHUB_OUTPUT"] = output.as_posix()
    run = subprocess.run([bash, "-e", shell.as_posix()], env = env, capture_output = True, text = True)
    if before is None:
        assert run.returncode != 0, run.stdout
        assert output.read_text() == "", "nothing recorded"
    else:
        assert run.returncode == 0, run.stdout + run.stderr
        assert output.read_text().strip() == before
    assert mark.exists() == upgraded, "the upgrade runs after a revision or alembic's own word that there is none"


def _lane(name: str) -> str:
    """
    One reusable lane's text, its line ends the runner's.
    """
    return (WORKFLOWS / name).read_text(encoding = "utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("name", TEST_LANES)
def test_a_test_lane_checks_out_the_ref_it_is_given(name):
    """
    A release is tested on its tag. A lane that ignores the ref tests the head of the branch the dispatch ran on,
    and passes for a release it never read (D-024).
    """
    text = _lane(name)
    assert re.search(r"\n      ref:\n        description: [^\n]+\n        type: string\n        default: \"\"\n", text)
    checkouts = re.findall(
        r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n((?:        [^\n]*\n|          [^\n]*\n)*)",
        text,
    )
    assert checkouts, name
    for given in checkouts:
        assert given.startswith("        with:\n          ref: ${{ inputs.ref }}\n"), name


@pytest.mark.parametrize("name, target", [
    ("ci-nextjs-tests.yml", "make ci-unit-tests"),
    ("ci-nextjs-integration.yml", "make ci-integration-tests"),
], ids = ["unit", "integration"])
def test_a_nextjs_lane_runs_the_callers_own_target(name, target):
    """
    The two lanes differ by the target alone, so a release names which suite failed (D-025).
    """
    text = _lane(name)
    assert f"        run: {target}\n" in text
    assert text.count("        run: make ") == 1
    assert "GH_NPM_TOKEN: ${{ secrets.GH_NPM_TOKEN }}" in text, "the install reads the private npm scope"


def test_the_nextjs_integration_lane_holds_a_read_only_token_and_its_own_job_name():
    text = _lane("ci-nextjs-integration.yml")
    assert "\npermissions:\n  contents: read\n" in text
    assert "\n  integration-tests:\n    name: Integration Tests\n" in text


@pytest.mark.parametrize("name, runner", [
    ("ci-nextjs-mutation.yml", 'node mutation_tests/run.mjs --lane "$LANE" --report "$RUNNER_TEMP/kdf-mutation"'),
    (
        "ci-python-mutation.yml",
        'python mutation_tests/run.py --lane "$LANE" --worktree "$RUNNER_TEMP/kdf-mutation/$LANE"',
    ),
], ids = ["nextjs", "python"])
def test_a_mutation_lane_runs_each_lane_the_caller_names_and_a_survivor_fails_it(name, runner):
    """
    One job per lane, none stopped by another's failure, and the lane's name reaches the shell as a variable,
    a name written into the script's own text would be run as shell (D-027).
    """
    text = _lane(name)
    assert "\npermissions:\n  contents: read\n" in text
    assert "\n      lanes:\n" in text and "        required: true\n" in text
    assert "\n      fail-fast: false\n      matrix:\n        lane: ${{ fromJSON(inputs.lanes) }}\n" in text
    step = text[
        text.index("      - name: Run the lane's mutants\n"):text.index("      - name: Keep the lane's report\n")
    ]
    assert "        env:\n          LANE: ${{ matrix.lane }}\n" in step
    assert f"        run: {runner}\n" in step
    assert "${{" not in step.split("        run: ", 1)[1], "no expression is written into the shell"
    assert "continue-on-error" not in text


def test_the_nextjs_mutation_lane_leaves_no_credential_in_the_tree_it_mutates():
    text = _lane("ci-nextjs-mutation.yml")
    assert "          ref: ${{ inputs.ref }}\n" in text
    assert "          persist-credentials: false\n" in text


@pytest.mark.parametrize("name, database", [
    ("ci-python-system.yml", "kdf_system"),
    ("ci-python-mutation.yml", "kdf_mutation_sys"),
], ids = ["system", "mutation"])
def test_a_system_suite_is_given_a_database_of_its_own(name, database):
    """
    A system test commits rows. On the integration suite's database, which rolls back, those rows are read by
    the next integration test.
    """
    text = _lane(name)
    assert f"KDF_SYSTEM_DATABASE_URL: postgresql+psycopg2://kdf:kdf@localhost:5432/{database}\n" in text
    assert "localhost:5432/kdf_test\n" not in text and "POSTGRES_DB: kdf_test\n" not in text


@pytest.mark.parametrize("name", ["ci-python-system.yml", "ci-python-mutation.yml"])
def test_a_lane_that_installs_a_private_package_asks_the_app_first(name):
    """
    The package token is a person's and expires, the App's is minted per job (D-010). On 2026-09-27 the token
    expired and every lane that fell back to it failed at its install.
    """
    text = _lane(name)
    mint = text.index("      - name: Mint GitHub App token for private-package installs\n")
    assert mint < text.index("      - name: Clone the private packages as bare mirrors\n")
    assert "        if: ${{ vars.USE_GITHUB_APP == 'true' && steps.plan.outputs.repositories != '' }}\n" in text
    assert "steps.pkg-token.outputs.token || secrets.GH_PACKAGES_PAT" in text
    assert "permission-contents: read" in text
    assert "          repositories: ${{ steps.plan.outputs.repositories }}\n" in text


def _named_steps(text: str) -> dict[str, str]:
    """
    A lane's named steps, each by its name with its own text, comments above the next step left out.
    """
    found: dict[str, str] = {}
    for chunk in text.split("\n      - ")[1:]:
        first, _, rest = chunk.partition("\n")
        if first.startswith("name: "):
            found[first.removeprefix("name: ")] = "\n".join(
                line for line in rest.splitlines() if not line.lstrip().startswith("#")
            )
    return found


@pytest.mark.parametrize("name", sorted(CLONING_STEP))
def test_the_package_token_goes_to_the_step_that_clones_and_into_no_file(name):
    """
    Each lane wrote the token into the job's global git config, a file every later step could read, a test or a
    dependency a test imports among them (SDK review S1-48). It reaches git through the cloning step's own
    environment now, settings that live for that step's processes, and no other step names it.
    """
    text  = _lane(name)
    steps = _named_steps(text)
    clone = steps[CLONING_STEP[name]]
    assert "git config" not in "\n".join(steps.values()), "a lane writes a git config again"
    # the token's rewrite lives in the cloning step alone, the install job's rewrite points at the mirrors on disk
    assert "url.https://__token__" not in "\n".join(body for step, body in steps.items() if step != CLONING_STEP[name])
    assert "GIT_CONFIG_KEY_0: ${{" in clone and "url.https://__token__:{0}@github.com/.insteadOf" in clone
    assert "          GIT_CONFIG_VALUE_0: https://github.com/\n" in clone + "\n"
    naming = sorted(step for step, body in steps.items() if "GH_PACKAGES_PAT" in body or "pkg-token.outputs" in body)
    assert naming == [CLONING_STEP[name]], f"{naming} name the token, only the cloning step may"
    # and it is the mint, then the clone, then whatever runs the caller's code, in that order
    names = list(steps)
    assert names.index("Mint GitHub App token for private-package installs") < names.index(CLONING_STEP[name])


@pytest.mark.parametrize("name", sorted(INSTALL_STEP))
def test_a_lane_that_was_not_asked_for_package_access_hands_git_no_setting(name):
    """
    The install step holds no git setting and no secret at all. The fetch job and the steps that read the mirrors run
    only when the caller sets needs_sdk_auth, so a caller that never sets it gets one job and git reads no rewrite.
    """
    text    = _lane(name)
    install = _named_steps(text)[INSTALL_STEP[name]]
    assert "GIT_CONFIG" not in install and "secrets." not in install
    assert "  fetch-private:\n    name: Fetch private packages\n    if: ${{ inputs.needs_sdk_auth }}\n" in text
    for step in ("Download the private mirrors", "Point git at the private mirrors"):
        assert "        if: ${{ inputs.needs_sdk_auth }}\n" in _step(text, step), step
    # the guard runs on a cancelled run too, and without package access only then (D-035, fail closed)
    guard = "        if: ${{ cancelled() || (inputs.needs_sdk_auth && needs.fetch-private.result != 'success') }}\n"
    assert guard in _step(text, "Require the private packages")


def test_the_security_lane_installs_its_two_tools_at_a_pin():
    """
    The lane installed bandit and pip-audit by a bare name, the newest release on the day, so a release of either
    could turn a lane red in a repo that had not changed, and a caller's own pin of the same tool said nothing about
    what CI ran (SDK review S1-4). A caller that pins another release names it.
    """
    text = _lane("ci-python-security.yml")
    assert '        run: pip install "bandit[toml]==${{ inputs.bandit_version }}"\n' in text
    assert '        run: pip install "pip-audit==${{ inputs.pip_audit_version }}"\n' in text
    for tool in ("bandit_version", "pip_audit_version"):
        block = text.split(f"      {tool}:\n", 1)[1].split("      needs_sdk_auth:", 1)[0]
        assert re.search(r'        default: "\d+\.\d+\.\d+"\n', block), f"{tool} has no pinned default"
    assert "pip install bandit[toml]\n" not in text and "pip install pip-audit\n" not in text


@pytest.mark.parametrize("tracked, code", [
    ((".env.example", ".env.local.example", ".env.kdf.example", "e2e/.env.example"), 0),
    ((".env.kdf.example", ".env.kdf"), 1),
    (("apps/web/.env.local",), 1),
    ((".env",), 1),
], ids = ["examples", "env-kdf", "nested-env-local", "bare-env"])
def test_the_secret_scan_refuses_a_committed_env_file_and_passes_the_examples(tmp_path, tracked, code):
    """
    A .env file holds real values that gitleaks may not see, so the scan every repo calls fails a pull request that
    commits one, and passes the examples (D-030). The step's own shell runs here against a scratch repo.
    """
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    step  = _step((WORKFLOWS / "secret-scan.yml").read_text(encoding = "utf-8"), "Refuse committed env files")
    block = step.split("run: |\n", 1)[1]
    shell = tmp_path / "step.sh"
    shell.write_text("\n".join(line[10:] for line in block.split("\n")) + "\n", encoding = "utf-8", newline = "\n")
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check = True)
    for name in tracked:
        path = repo / name
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text("X=\n", encoding = "utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-f", *tracked], check = True)
    run = subprocess.run([bash, shell.as_posix()], cwd = repo, capture_output = True, text = True)
    assert run.returncode == code, run.stdout + run.stderr


def test_the_integration_lane_declares_a_ci_run_local():
    """
    A stack started in Actions is local by the owner's definition (2026-09-30), never the DEV account, and the states
    are spelled local, dev and prod alone. The lane's job env names the state its callers' suites run in.
    """
    lane     = _lane("ci-python-integration.yml")
    declared = [line.strip() for line in lane.split("\n") if line.strip().startswith("ENVIRONMENT:")]
    assert declared == ["ENVIRONMENT: local"], declared
    for word in ("ENVIRONMENT: dev", "ENVIRONMENT: development", "ENVIRONMENT: production", "ENVIRONMENT: prod"):
        assert word not in lane, word
