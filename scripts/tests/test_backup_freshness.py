"""
The backups' freshness (the secrets moves, step 2, Round Table 79's L21, D-111), backup_freshness.py and its section in
the ecosystem watch.

A backup counts only by a store job of its environment that succeeded with its store step, so a DEV run never counts
for prod and a drill or a skipped job never counts. Each state is reported, a stale PROD beside a fresh DEV and an
active workflow whose arming variable is off among them.
"""

from __future__ import annotations

# standard imports
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# third party imports
import backup_freshness as bf
import ecosystem_watch as ew
import pytest


NOW:   datetime = datetime(2026, 12, 20, 12, 0, tzinfo = timezone.utc)
REPO:  str = "Needless2Say/fitness-app-backend"
FLOW:  str = f"/repos/{REPO}/actions/workflows/backup.yml"
ENTRY: dict[str, Any] = {"repo": REPO, "workflow": "backup.yml", "app": "fitness", "environments": ["prod"]}


def store_job(
    environment: str = "prod",
    done: str = "2026-12-14T06:20:00Z",
    conclusion: str = "success",
    step: str = "success",
    name: str | None = None,
) -> dict[str, Any]:
    """
    A run's job as GitHub lists it, the store job of db-backup.yml by default.

    Args:
        environment: its environment
        done: its completion time
        conclusion: its conclusion
        step: its store step's conclusion
        name: its name, the store job's when None

    Returns:
        dict[str, Any]: the job
    """
    return {
        "name": name or f"backup / Store the backup ({environment})",
        "conclusion": conclusion,
        "completed_at": done,
        "steps": [{"name": "Store, read back and prune", "conclusion": step}],
    }


class Fake:
    """
    GitHub's answers by path, each run's jobs by its id.
    """
    def __init__(
        self,
        runs: list[dict[str, Any]],
        jobs: dict[int, list[dict[str, Any]]],
        state: str = "active",
        flow_status: int = 200,
        runs_status: int = 200,
    ) -> None:
        self.runs, self.jobs, self.state = runs, jobs, state
        self.flow_status, self.runs_status = flow_status, runs_status
        self.asked: list[dict[str, Any]] = []


    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> ew.Response:
        if path == FLOW:
            return ew.Response(self.flow_status, {"state": self.state} if self.flow_status == 200 else {})
        if path == f"{FLOW}/runs":
            self.asked.append(dict(params or {}))
            return ew.Response(self.runs_status, {"workflow_runs": self.runs})
        run_id = int(path.split("/runs/")[1].split("/")[0])
        return ew.Response(200, {"jobs": self.jobs.get(run_id, [])})


def run(run_id: int, event: str = "schedule", conclusion: str = "success") -> dict[str, Any]:
    return {
        "id": run_id,
        "event": event,
        "status": "completed",
        "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
    }


def keys(result: dict[str, Any]) -> list[str]:
    return [finding["key"] for finding in result["findings"]]

# ======================================================================================================================
# The states
# ======================================================================================================================

def test_a_prod_backup_stored_within_the_days_is_fresh() -> None:
    result = bf.collect_entry(Fake([run(1)], {1: [store_job()]}), ENTRY, NOW, 8)

    assert keys(result) == [] and result["error"] is None
    assert result["fresh"] == {"prod": "2026-12-14T06:20:00Z"}


def test_a_stale_prod_beside_a_fresh_dev_is_stale() -> None:
    entry  = {**ENTRY, "environments": ["dev", "prod"]}
    jobs   = {1: [store_job("dev", "2026-12-19T06:00:00Z")], 2: [store_job("prod", "2026-12-01T06:00:00Z")]}
    result = bf.collect_entry(Fake([run(1, "workflow_dispatch"), run(2)], jobs), entry, NOW, 8)

    assert keys(result) == ["stale:prod"]
    assert result["fresh"] == {"dev": "2026-12-19T06:00:00Z", "prod": "2026-12-01T06:00:00Z"}


@pytest.mark.parametrize(
    "job",
    [
        store_job(name = "restore / Drill on Postgres 17 (prod)"),
        store_job(name = "backup / Preview Store the backup (prod)"),
        store_job(conclusion = "skipped"),
        store_job(step = "failure"),
        store_job(step = "skipped"),
        store_job("dev"),
    ],
)
def test_a_drill_a_skipped_job_a_failed_store_step_or_a_dev_run_never_counts_for_prod(job: dict[str, Any]) -> None:
    result = bf.collect_entry(Fake([run(1)], {1: [job]}), ENTRY, NOW, 8)

    assert "stale:prod" in keys(result)


def test_the_runs_are_read_from_main_alone() -> None:
    fake = Fake([run(1)], {1: [store_job()]})

    bf.collect_entry(fake, ENTRY, NOW, 8)

    assert fake.asked and all(asked["branch"] == "main" for asked in fake.asked)


def test_an_active_workflow_with_its_arming_variable_off_is_disarmed() -> None:
    skipped = [{"name": "backup", "conclusion": "skipped", "steps": []}]
    fresh   = [store_job(done = "2026-12-15T06:00:00Z")]
    result  = bf.collect_entry(Fake([run(2), run(1, "workflow_dispatch")], {2: skipped, 1: fresh}), ENTRY, NOW, 8)

    assert keys(result) == ["disarmed"]


def test_a_workflow_with_no_scheduled_run_says_so() -> None:
    result = bf.collect_entry(Fake([run(1, "workflow_dispatch")], {1: [store_job()]}), ENTRY, NOW, 8)

    assert keys(result) == ["unscheduled"]


def test_a_disabled_workflow_is_disabled() -> None:
    result = bf.collect_entry(Fake([run(1)], {1: [store_job()]}, state = "disabled_manually"), ENTRY, NOW, 8)

    assert keys(result) == ["disabled"]


def test_a_missing_workflow_is_missing() -> None:
    result = bf.collect_entry(Fake([], {}, flow_status = 404), ENTRY, NOW, 8)

    assert keys(result) == ["missing"]


def test_a_newest_run_that_failed_is_failing() -> None:
    jobs   = {2: [store_job(conclusion = "failure")], 1: [store_job(done = "2026-12-15T06:00:00Z")]}
    result = bf.collect_entry(Fake([run(2, conclusion = "failure"), run(1)], jobs), ENTRY, NOW, 8)

    assert keys(result) == ["failing"]


def test_runs_that_cannot_be_read_are_a_blind_spot() -> None:
    result = bf.collect_entry(Fake([], {}, runs_status = 403), ENTRY, NOW, 8)

    assert result["error"] and keys(result) == []

# ======================================================================================================================
# The registry
# ======================================================================================================================

def test_cicds_own_registry_is_in_its_shape() -> None:
    days, entries = bf.read_registry()

    assert days == 8
    assert {entry["app"] for entry in entries} == {"fitness", "hub"}
    assert all(entry["environments"] == ["prod"] for entry in entries)


@pytest.mark.parametrize(
    "data",
    [
        {"max_age_days": 0, "backups": []},
        {"max_age_days": 8, "backups": [{"repo": "a/b", "workflow": "backup.yml", "app": "x", "environments": []}]},
        {"max_age_days": 8, "backups": [{"repo": "a/b", "workflow": "", "app": "x", "environments": ["prod"]}]},
        {"max_age_days": 8, "backups": [{"repo": "a/b", "workflow": "b.yml", "app": "x", "environments": ["qa"]}]},
    ],
)
def test_a_registry_out_of_its_shape_is_refused(tmp_path: Path, data: dict[str, Any]) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))

    with pytest.raises(bf.RegistryError):
        bf.read_registry(path)

# ======================================================================================================================
# The watch's section
# ======================================================================================================================

def test_the_watch_reports_each_finding_and_keeps_its_issue_open() -> None:
    snapshot = {
        "backups": [bf.collect_entry(Fake([run(1)], {1: [store_job(done = "2026-12-01T06:00:00Z")]}), ENTRY, NOW, 8)],
    }
    findings: dict[str, str] = {}

    lines = ew._backups_section(snapshot, findings)

    assert any("stale in prod" in line for line in lines)
    assert list(findings) == ["backup:fitness-app-backend:backup.yml:stale:prod"]


def test_a_fresh_backup_is_shown_and_no_finding() -> None:
    snapshot = {"backups": [bf.collect_entry(Fake([run(1)], {1: [store_job()]}), ENTRY, NOW, 8)]}
    findings: dict[str, str] = {}

    lines = ew._backups_section(snapshot, findings)

    assert any("fresh, prod stored 2026-12-14T06:20:00Z" in line for line in lines)
    assert findings == {}


def test_a_snapshot_before_the_backups_renders_no_section() -> None:
    assert ew._backups_section({}, {}) == []


def test_a_registry_that_cannot_be_read_is_a_blind_spot_of_the_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(transport: Any, moment: datetime) -> list:
        raise bf.RegistryError("the backup registry needs a positive max_age_days and a list of backups")


    monkeypatch.setattr(ew.backup_freshness, "collect_backups", refused)

    found = ew.collect_backups(Fake([], {}), NOW)

    assert len(found) == 1 and found[0]["error"]
