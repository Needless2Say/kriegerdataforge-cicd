"""
Contract tests for the two reusable Vercel deploys, `cd-nextjs-vercel.yml` and `cd-python-vercel.yml`.

Rows 40 and 42 of the auth UI's deferred register and row 83 of the hub's (D-016). The deploy token is
read by the steps that call Vercel's API alone, never written to $GITHUB_ENV, the Next.js deploy
installs once, neither job holds a permission nothing uses, neither header claims a reviewer no
environment has, and the Python deploy deploys without the domains, migrates, smokes the new
deployment and only then promotes it, undoing the migration when the smoke fails. Text level, the
repository keeps no YAML parser among its test dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
NEXTJS    = (WORKFLOWS / "cd-nextjs-vercel.yml").read_text(encoding = "utf-8")
PYTHON    = (WORKFLOWS / "cd-python-vercel.yml").read_text(encoding = "utf-8")


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
    undo = _step(PYTHON, "Undo the migration, the new release will not serve")
    assert "steps.smoke.outcome == 'failure'" in undo
    assert 'alembic downgrade "$BEFORE"' in undo
    migrate = _step(PYTHON, "Run Alembic migrations")
    assert 'echo "before=${BEFORE:-base}" >> "$GITHUB_OUTPUT"' in migrate
    promote = _step(PYTHON, "Promote the deployment to the production domains")
    assert "vercel promote" in promote and "steps.deploy.outputs.url" in promote
