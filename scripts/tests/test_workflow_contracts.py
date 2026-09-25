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
NEXTJS    = (WORKFLOWS / "cd-nextjs-vercel.yml").read_text(encoding = "utf-8")
PYTHON    = (WORKFLOWS / "cd-python-vercel.yml").read_text(encoding = "utf-8")

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
