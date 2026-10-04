"""
Contract tests for the issue-triggered Distribute workflows (cicd D-047).

Each one posts its result on the issue and then closes it, completed when the run succeeded and not planned when it
did not, so finished runs stop piling up as open issues and a failed one can be reopened. The close step's own shell
runs here under bash against a fake `gh`. The combined kit and scripts workflow is gated like the others, by its own
label and the owner-only gate.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT                 = Path(__file__).resolve().parents[2]
WORKFLOWS            = ROOT / ".github" / "workflows"
TEMPLATES            = ROOT / ".github" / "ISSUE_TEMPLATE"
DISTRIBUTE_WORKFLOWS = (
    "ops-distribute-kit.yml",
    "ops-distribute-scripts.yml",
    "ops-distribute-all.yml",
    "ops-distribute-app-secrets.yml",
)


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _steps(text: str) -> list[str]:
    return re.findall(r"^\s+- name: (.+)$", text, flags = re.MULTILINE)


def _step(text: str, name: str) -> str:
    start = text.index(f"- name: {name}")
    rest  = text[start + 1:]
    end   = re.search(r"^\s+- name: ", rest, flags = re.MULTILINE)
    return text[start:start + 1 + (end.start() if end else len(rest))]


def _bash() -> str | None:
    """
    A bash that runs the step's shell here. Git's on Windows, System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def _close_shell(tmp_path: Path, workflow: str) -> Path:
    lines = []
    for line in _step(_text(workflow), "Close the issue").split("run: |\n", 1)[1].split("\n"):
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    shell = tmp_path / "close.sh"
    shell.write_text("\n".join(lines) + "\n", encoding = "utf-8", newline = "\n")
    return shell


@pytest.mark.parametrize("workflow", DISTRIBUTE_WORKFLOWS)
def test_each_distribute_run_closes_its_issue_last_and_always(workflow):
    text  = _text(workflow)
    steps = _steps(text)
    assert steps[-1] == "Close the issue", f"{workflow} must close its issue as its last step"
    assert any(step.startswith("Comment") for step in steps[:-1]), "the result is posted before the issue closes"
    close = _step(text, "Close the issue")
    assert "if: always()" in close
    assert "OUTCOME: ${{ job.status }}" in close
    assert 'gh issue close "$ISSUE" --repo "$REPO" --reason "$reason"' in close
    assert "issues: write" in text, "the close uses the issues permission the job already holds"


def _run_close(tmp_path: Path, workflow: str, outcome: str, shell: Path | None = None) -> list[str]:
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    shell   = shell or _close_shell(tmp_path, workflow)
    fakebin = tmp_path / "bin"
    fakebin.mkdir(exist_ok = True)
    fake = fakebin / "gh"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$FAKE_GH_ARGS"\n', encoding = "utf-8", newline = "\n")
    fake.chmod(0o755)
    called = tmp_path / "called"
    env    = {
        **os.environ,
        "PATH": os.pathsep.join([str(fakebin), os.environ.get("PATH", "")]),
        "FAKE_GH_ARGS": called.as_posix(),
        "ISSUE": "264",
        "REPO": "Needless2Say/kriegerdataforge-cicd",
        "OUTCOME": outcome,
    }
    run    = subprocess.run([bash, "-e", shell.as_posix()], env = env, capture_output = True, text = True)
    assert run.returncode == 0, run.stdout + run.stderr
    return called.read_text(encoding = "utf-8").splitlines()


@pytest.mark.parametrize("workflow", DISTRIBUTE_WORKFLOWS)
@pytest.mark.parametrize(("outcome", "reason"), [
    ("success", "completed"),
    ("failure", "not planned"),
    ("cancelled", "not planned"),
])
def test_the_close_reason_follows_the_run(tmp_path, workflow, outcome, reason):
    args = _run_close(tmp_path, workflow, outcome)
    assert args == ["issue", "close", "264", "--repo", "Needless2Say/kriegerdataforge-cicd", "--reason", reason]


def test_the_control_a_close_that_ignores_the_outcome_calls_a_failure_completed(tmp_path):
    """
    The same step with its test of the outcome replaced by `true` closes a failed run as completed, so the test above
    fails without that test.
    """
    shell = _close_shell(tmp_path, "ops-distribute-kit.yml")
    shell.write_text(
        shell.read_text(encoding = "utf-8").replace('[ "$OUTCOME" = "success" ]', "true"),
        encoding = "utf-8",
        newline = "\n",
    )
    assert _run_close(tmp_path, "ops-distribute-kit.yml", "failure", shell = shell)[-1] == "completed"


def test_the_combined_workflow_is_gated_by_its_own_label_and_the_owner():
    text = _text("ops-distribute-all.yml")
    assert text.count("github.event.label.name == 'ops:distribute-all'") == 2
    assert "uses: ./.github/workflows/_authorize-owner.yml" in text
    assert "needs.authorize.outputs.authorized == 'true'" in text
    assert 'python scripts/distribute_all.py "${ARGS[@]}"' in text
    assert "${{ github.event.issue.body }}" not in _step(text, "Run distribute_all")


def test_the_combined_issue_form_names_the_label_that_runs_it():
    form = (TEMPLATES / "ops-distribute-all.yml").read_text(encoding = "utf-8")
    assert "ops:distribute-all" in form
    assert "label: Mode" in form and "label: Target repos" in form
