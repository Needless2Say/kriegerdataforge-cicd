"""
Contract tests for the two workflows of D-049, the reusable `ecosystem-watch.yml` and the live
`check-secret-expiry.yml`.

The watch reads the open Dependabot alerts of private repos, so it runs only when a private repo calls it, never on an
event of this public repo, its App token is read only, and its issue is written with the caller's own token. The
expiry monitor hands each live token to the one step that reads it. Text level, as test_workflow_contracts.py is, the
repository keeps no YAML parser among its test dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
WATCH     = (WORKFLOWS / "ecosystem-watch.yml").read_text(encoding = "utf-8")
EXPIRY    = (WORKFLOWS / "check-secret-expiry.yml").read_text(encoding = "utf-8")


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


def test_the_expiry_issue_opens_on_drift_too() -> None:
    issue = _step(EXPIRY, "Open / update / close the tracking issue")
    assert "DRIFT: ${{ steps.check.outputs.drift }}" in issue
    assert 'if [ -n "$NEEDS" ] || [ -n "$DRIFT" ]; then' in issue
    assert "REJECTED|DRIFT" in issue
