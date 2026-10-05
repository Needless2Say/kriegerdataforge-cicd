"""
Contract tests for the two workflows of D-049, the reusable `ecosystem-watch.yml` and the live
`check-secret-expiry.yml`.

The watch reads the open Dependabot alerts of private repos, so it runs only when a private repo calls it, never on an
event of this public repo, its App token is read only, and its issue is written with the caller's own token. The
expiry monitor hands each live token to the one step that reads it. Text level, as test_workflow_contracts.py is, the
repository keeps no YAML parser among its test dependencies. The issue step's own shell also runs here under bash,
run after run, against a fake `gh` that keeps its issues in a file, as test_ops_distribute_workflows.py runs its close
step.
"""

from __future__ import annotations

# standard imports
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# third party imports
import ecosystem_watch as ew
import pytest

TESTS     = Path(__file__).resolve().parent
WORKFLOWS = TESTS.parents[1] / ".github" / "workflows"
WATCH     = (WORKFLOWS / "ecosystem-watch.yml").read_text(encoding = "utf-8")
EXPIRY    = (WORKFLOWS / "check-secret-expiry.yml").read_text(encoding = "utf-8")
ISSUE     = "Open, update or close the rolling issue"


def _code(text: str) -> str:
    """
    The workflow without its comments, so a caller's example in the header is not read as the workflow.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _step(text: str, name: str) -> str:
    """
    One step's text, from its `- name:` line to the next step's.
    """
    match = re.search(r"\n(\s*)- name: " + re.escape(name) + r"\n(.*?)(?=\n\1- name: |\Z)", _code(text), re.DOTALL)
    assert match, f"no step named {name!r}"
    return match.group(2)


def test_the_watch_runs_only_when_a_repo_calls_it() -> None:
    """
    cicd is public, so an event of its own must never start the watch, its issues and logs would be public.
    """
    on = re.search(r"\non:\n(.*?)\n\S", _code(WATCH), re.DOTALL).group(1)
    assert re.findall(r"^  (\w+):", on, re.MULTILINE) == ["workflow_call"]
    for event in ("schedule", "push", "pull_request", "workflow_dispatch", "issues"):
        assert f"  {event}:" not in on


def test_the_watch_refuses_a_public_caller_before_reading_anything() -> None:
    """
    The security of the watch rests on its caller being private, so its first step asks the API and stops otherwise.
    """
    names = re.findall(r"\n\s*- name: (.+)", _code(WATCH))
    assert names[0] == "Refuse a public caller"
    refuse = _step(WATCH, "Refuse a public caller")
    assert "GH_TOKEN: ${{ github.token }}" in refuse
    assert 'gh api "repos/$REPO" --jq .private' in refuse
    assert '[ "$private" != "true" ]' in refuse and "exit 1" in refuse


def test_a_finding_reopens_the_last_closed_issue() -> None:
    issue = _step(WATCH, "Open, update or close the rolling issue")
    assert '--label "$LABEL" --state "$1"' in issue
    assert 'existing="$(newest open)"' in issue and 'closed="$(newest closed)"' in issue
    assert 'gh issue reopen "$closed"' in issue


def test_the_expiry_monitor_fails_closed_without_a_verdict() -> None:
    """
    A check that crashed prints no verdict, and empty outputs would close the issue as healthy.
    """
    check = _step(EXPIRY, "Run expiry check")
    assert "if ! grep -qE '^NEEDS_ROTATION: ' check.out || ! grep -qE '^REGISTRY_DRIFT: ' check.out; then" in check
    assert "gave no verdict" in check


def test_the_watch_takes_the_app_secrets_by_name_and_never_inherits() -> None:
    code = _code(WATCH)
    assert re.search(r"app_id:\n\s+description: .*\n\s+required: true", code)
    assert re.search(r"app_private_key:\n\s+description: .*\n\s+required: true", code)
    assert "inherit" not in code


def test_the_watch_token_is_read_only_and_only_the_collect_step_holds_it() -> None:
    mint  = _step(WATCH, "Mint a read only App token")
    asked = dict(re.findall(r"permission-([a-z-]+): (\w+)", mint))
    assert asked == {"contents": "read", "vulnerability-alerts": "read", "checks": "read", "actions": "read"}
    assert "owner: ${{ github.repository_owner }}" in mint
    assert "steps.app.outputs.token" in _step(WATCH, "Collect the snapshot")
    holders = [m for m in re.finditer(r"steps\.app\.outputs\.token", _code(WATCH))]
    assert len(holders) == 1


def test_the_issue_is_written_with_the_callers_own_token() -> None:
    issue = _step(WATCH, "Open, update or close the rolling issue")
    assert "GH_TOKEN: ${{ github.token }}" in issue
    assert "steps.app" not in issue
    assert "set -euo pipefail" in issue
    for verb in ("gh issue create", "gh issue edit", "gh issue comment", "gh issue close"):
        assert verb in issue
    assert '--label "$LABEL"' in issue
    assert "news.md" in issue and "state.txt" in issue
    permissions = re.search(r"\npermissions:\n(.*?)\n\S", _code(WATCH), re.DOTALL).group(1)
    assert set(re.findall(r"^  ([a-z-]+): (\w+)", permissions, re.MULTILINE)) == {
        ("contents", "read"),
        ("issues", "write"),
    }


def test_every_action_of_the_watch_is_pinned_to_a_commit() -> None:
    uses = re.findall(r"uses: (\S+)", _code(WATCH))
    assert uses
    for action in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), action


def test_the_watch_runs_cicds_own_scripts_and_keeps_the_snapshot() -> None:
    checkout = _step(WATCH, "Check out cicd's scripts")
    assert "repository: Needless2Say/kriegerdataforge-cicd" in checkout
    assert "persist-credentials: false" in checkout
    assert "/scripts/" in checkout and "/kit/KIT_VERSION" in checkout
    assert "_kdf_cicd/scripts/ecosystem_watch.py collect" in _step(WATCH, "Collect the snapshot")
    keep = _step(WATCH, "Keep the snapshot")
    assert "snapshot.json" in keep and "retention-days:" in keep


def test_the_expiry_monitor_reads_live_and_hands_each_token_to_the_check_alone() -> None:
    check = _step(EXPIRY, "Run expiry check")
    assert "rotate_secret.py --mode check --secrets all --live" in check
    for token in ("CICD_PAT", "GH_PACKAGES_PAT", "VERCEL_MASTER_TOKEN"):
        assert f"{token}: ${{{{ secrets.{token} }}}}" in check
        assert _code(EXPIRY).count(f"secrets.{token}") == 1, f"{token} reaches another step"
    assert "REGISTRY_DRIFT" in check and 'echo "drift=$drift"' in check


def test_the_expiry_monitor_starts_on_its_schedule_or_by_hand_alone() -> None:
    on = re.search(r"\non:\n(.*?)\n\S", _code(EXPIRY), re.DOTALL).group(1)
    assert re.findall(r"^  (\w+):", on, re.MULTILINE) == ["schedule", "workflow_dispatch"]


def test_every_app_token_step_is_on_one_pin_and_passes_a_client_id() -> None:
    """
    The watch's first run found the deprecated `app-id` input across the workflows, and the last v2.2.2 pin, on
    Node.js 20, in `run-e2e`. Every step that mints an App token now names the v3.2.0 commit and `client-id`, which
    the action reads as the App's id or its client id alike.
    """
    root  = TESTS.parents[1]
    files = [*WORKFLOWS.glob("*.yml"), *root.glob(".github/actions/*/action.yml")]
    files.append(root / "scripts" / "fetch_private_job.template.yml")
    steps = []
    every = 0
    for path in files:
        text = path.read_text(encoding = "utf-8")
        every += text.count("uses: actions/create-github-app-token@")
        for match in re.finditer(r"uses: actions/create-github-app-token@(\S+).*\n(\s+)with:\n((?:\2  .*\n)+)", text):
            steps.append((path.name, match.group(1), match.group(3)))
    # each step read, none skipped by a shape the pattern does not know
    assert len(steps) == every >= 25
    for name, pin, inputs in steps:
        assert pin == "bcd2ba49218906704ab6c1aa796996da409d3eb1", f"{name} pins {pin}"
        assert "client-id: ${{" in inputs and "app-id:" not in inputs, f"{name}:\n{inputs}"


def test_the_expiry_issue_opens_on_drift_too() -> None:
    issue = _step(EXPIRY, "Open / update / close the tracking issue")
    assert "DRIFT: ${{ steps.check.outputs.drift }}" in issue
    assert 'if [ -n "$NEEDS" ] || [ -n "$DRIFT" ]; then' in issue
    assert "REJECTED|DRIFT" in issue

# ======================================================================================================================
# The issue step's shell, run after run against a fake gh
# ======================================================================================================================

def _bash() -> str | None:
    """
    A bash that runs the step's shell here. Git's on Windows, System32's is WSL and may hold no distribution.
    """
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.exists():
        return str(git_bash)
    return None if os.name == "nt" else shutil.which("bash")


def _option(argv: list[str], name: str) -> str:
    """
    The value after a flag of a gh call.
    """
    return argv[argv.index(name) + 1]


def fake_gh(argv: list[str]) -> int:
    """
    The `gh` the issue step runs against here. Its issues live in the JSON file FAKE_GH_STATE, and the one verb named in
    FAKE_GH_FAIL fails as a lost connection would. It writes bytes, so Windows adds no carriage return to a number.
    """
    path   = Path(os.environ["FAKE_GH_STATE"])
    state  = json.loads(path.read_text(encoding = "utf-8"))
    issues = state["issues"]
    verb   = " ".join(argv[:2])
    state["calls"].append(verb)
    if verb == os.environ.get("FAKE_GH_FAIL"):
        path.write_text(json.dumps(state), encoding = "utf-8")
        return 1
    if verb == "issue list":
        numbers = [int(number) for number, issue in issues.items() if issue["state"] == _option(argv, "--state")]
        sys.stdout.buffer.write(f"{max(numbers)}\n".encode() if numbers else b"")
    elif verb == "issue view":
        sys.stdout.buffer.write((issues[argv[2]]["body"] + "\n").encode("utf-8"))
    elif verb == "issue edit":
        issues[argv[2]]["body"] = Path(_option(argv, "--body-file")).read_text(encoding = "utf-8")
    elif verb == "issue comment":
        text = _option(argv, "--body") if "--body" in argv else Path(_option(argv, "--body-file")).read_text("utf-8")
        issues[argv[2]]["comments"].append(text)
    elif verb in ("issue close", "issue reopen"):
        issues[argv[2]]["state"] = "closed" if verb == "issue close" else "open"
    elif verb == "issue create":
        body = Path(_option(argv, "--body-file")).read_text(encoding = "utf-8")
        issues[str(len(issues) + 1)] = {"state": "open", "body": body, "comments": []}
    elif verb != "label create":
        sys.stderr.write(f"fake gh: no such call {argv}\n")
        return 2
    path.write_text(json.dumps(state), encoding = "utf-8")
    return 0


def snapshot(*numbers: int) -> dict[str, Any]:
    """
    A snapshot of one repo whose open alerts are these, high each, on packages pkg<number>, everything else clear.
    """
    alerts    = [
        {
            "number": number,
            "severity": "high",
            "ecosystem": "pip",
            "package": f"pkg{number}",
            "manifest": "requirements.txt",
            "vulnerable": "< 2.0.0",
            "patched": "2.0.0",
            "advisory": f"GHSA-{number}",
            "cve": None,
            "summary": "s",
            "url": f"https://github.com/x/alerts/{number}",
        }
        for number in numbers
    ]
    alerts_ok = {"status": "ok", "reason": None, "open": alerts}
    repo = {"repo": f"{ew.OWNER}/repo-a", "alerts": alerts_ok, "pins": [], "drift": [], "notices": [], "errors": []}
    return {
        "schema": ew.SCHEMA,
        "generated_at": "2026-10-05T10:00:00Z",
        "owner": ew.OWNER,
        "kit_version": "v1.15.0",
        "releases": {},
        "canonical_scripts_unreadable": [],
        "repos": [repo],
        "summary": ew.summarize([repo]),
    }


@pytest.fixture()
def watch(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    """
    One weekly run of the issue step, its snapshot given and a gh verb that fails optionally. Its issues persist from
    run to run in the fake's state, read with `watch.state()`.
    """
    bash = _bash()
    if bash is None:
        pytest.skip("no bash to run the step's shell")
    lines = []
    for line in _step(WATCH, ISSUE).split("run: |\n", 1)[1].split("\n"):
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    shell = tmp_path / "issue.sh"
    shell.write_text("\n".join(lines) + "\n", encoding = "utf-8", newline = "\n")
    scripts = tmp_path / "_kdf_cicd" / "scripts"
    scripts.mkdir(parents = True)
    shutil.copy(Path(ew.__file__), scripts / "ecosystem_watch.py")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    call_fake = "import sys, test_ecosystem_watch_workflows as t; sys.exit(t.fake_gh(sys.argv[1:]))"
    for name, text in (("gh", f"exec \"$FAKE_PY\" -c '{call_fake}' \"$@\""), ("python", 'exec "$FAKE_PY" "$@"')):
        (fakebin / name).write_text(f"#!/usr/bin/env bash\n{text}\n", encoding = "utf-8", newline = "\n")
        (fakebin / name).chmod(0o755)
    runner = tmp_path / "runner"
    runner.mkdir()
    state = tmp_path / "gh.json"
    state.write_text(json.dumps({"issues": {}, "calls": []}), encoding = "utf-8")


    def run(snap: dict[str, Any], fail: str = "") -> subprocess.CompletedProcess[str]:
        (runner / "snapshot.json").write_text(json.dumps(snap), encoding = "utf-8")
        env     = {
            **os.environ,
            "PATH": os.pathsep.join([str(fakebin), os.environ.get("PATH", "")]),
            "PYTHONPATH": os.pathsep.join([str(TESTS), str(Path(ew.__file__).parent)]),
            "PYTHONIOENCODING": "utf-8",
            "FAKE_PY": Path(sys.executable).as_posix(),
            "FAKE_GH_STATE": state.as_posix(),
            "FAKE_GH_FAIL": fail,
            "LABEL": "ops:ecosystem-watch",
            "REPO": "Needless2Say/kriegerdataforge-context",
            "RUN_URL": "https://github.com/run/1",
            "RUNNER_TEMP": runner.as_posix(),
        }
        command = [bash, "--noprofile", "--norc", "-eo", "pipefail", shell.as_posix()]
        return subprocess.run(command, cwd = tmp_path, env = env, capture_output = True, text = True)


    run.state = lambda: json.loads(state.read_text(encoding = "utf-8"))
    return run


def _ran(done: subprocess.CompletedProcess[str]) -> None:
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_run_with_nothing_new_rewrites_the_body_and_adds_no_comment(watch: Callable[..., Any]) -> None:
    _ran(watch(snapshot(1)))
    _ran(watch(snapshot(1)))
    issues = watch.state()["issues"]
    assert list(issues) == ["1"] and issues["1"]["state"] == "open"
    assert issues["1"]["comments"] == []
    assert "`pkg1`" in issues["1"]["body"]


def test_news_whose_comment_failed_is_posted_by_the_next_run(watch: Callable[..., Any]) -> None:
    """
    The review's finding, the body that remembers a finding was saved before the news of it was posted, so a comment
    that failed was never posted again. The news now goes first.
    """
    _ran(watch(snapshot(1)))
    assert watch(snapshot(1, 2), fail = "issue comment").returncode != 0
    _ran(watch(snapshot(1, 2)))
    comments = watch.state()["issues"]["1"]["comments"]
    assert len(comments) == 1
    assert "high alert on `pkg2`" in comments[0] and "pkg1" not in comments[0]


def test_a_clear_run_closes_and_a_later_finding_reopens_with_its_news(watch: Callable[..., Any]) -> None:
    """
    A clear run leaves a body that remembers nothing, so a finding that comes back after it is news, on the same issue.
    """
    _ran(watch(snapshot(1)))
    _ran(watch(snapshot()))
    issue = watch.state()["issues"]["1"]
    assert issue["state"] == "closed"
    assert issue["comments"][-1].startswith("All clear, so this closes.")
    assert ew.previous_keys(issue["body"]) == set()
    _ran(watch(snapshot(1)))
    issues = watch.state()["issues"]
    assert list(issues) == ["1"] and issues["1"]["state"] == "open"
    assert "high alert on `pkg1`" in issues["1"]["comments"][-1]


@pytest.mark.parametrize("fail", ["issue reopen", "issue comment"])
def test_a_reopen_that_fails_midway_still_posts_its_news_next_run(watch: Callable[..., Any], fail: str) -> None:
    _ran(watch(snapshot(1)))
    _ran(watch(snapshot()))
    assert watch(snapshot(2), fail = fail).returncode != 0
    _ran(watch(snapshot(2)))
    issues = watch.state()["issues"]
    assert list(issues) == ["1"] and issues["1"]["state"] == "open"
    assert "high alert on `pkg2`" in issues["1"]["comments"][-1]
