"""
The backups' freshness, reported by the weekly ecosystem watch (the secrets moves, step 2, Round Table 79's L21, D-111).

The watch's own notices skip a disabled workflow and read each workflow's latest completed run alone, which cannot
show whether a backup was stored, so the backups get a collector of their own. It reads each app's backup workflow from
`backup_registry.json` and reports, per app and source environment, a workflow missing, disabled or failing, a schedule
disarmed, its newest scheduled run skipping every job, or no backup stored and read back within the registry's days.

A backup counts only by a job named `Store the backup (<environment>)` that succeeded with its step `Store, read back
and prune`, the store job of `db-backup.yml`, so a DEV run never counts for prod, and a drill or a skipped job never
counts at all. It reads GitHub's runs alone and has no route to the store.
"""

from __future__ import annotations

# standard imports
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ======================================================================================================================
# Configuration
# ======================================================================================================================

REGISTRY:    Path = Path(__file__).resolve().parent / "backup_registry.json"
STORE_JOB:   str = "Store the backup ({environment})"
STORE_STEP:  str = "Store, read back and prune"
WINDOW_DAYS: int = 35
RUNS_READ:   int = 30
STAMP:       str = "%Y-%m-%dT%H:%M:%SZ"


class RegistryError(Exception):
    """
    The backup registry out of its shape.
    """

# ======================================================================================================================
# The registry
# ======================================================================================================================

def read_registry(path: Path = REGISTRY) -> tuple[int, list[dict[str, Any]]]:
    """
    The registry's days and its backups, checked.

    Args:
        path: the registry

    Returns:
        tuple[int, list[dict[str, Any]]]: the days a backup stays fresh, and each backup workflow

    Raises:
        RegistryError: the registry is out of its shape
    """
    data    = json.loads(path.read_text(encoding = "utf-8"))
    days    = data.get("max_age_days") if isinstance(data, dict) else None
    entries = data.get("backups") if isinstance(data, dict) else None
    if not isinstance(days, int) or isinstance(days, bool) or days < 1 or not isinstance(entries, list):
        raise RegistryError("the backup registry needs a positive max_age_days and a list of backups")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not all(isinstance(entry.get(name), str) and entry[name] for name in ("repo", "workflow", "app"))
            or not isinstance(entry.get("environments"), list)
            or not entry["environments"]
            or not set(entry["environments"]) <= {"dev", "prod"}
        ):
            raise RegistryError(f"a backup entry is out of its shape, {entry!r}")
    return days, entries

# ======================================================================================================================
# The evidence
# ======================================================================================================================

def stored_at(jobs: list[dict[str, Any]], environment: str) -> str | None:
    """
    When a run's store job for an environment stored and read back its backup, or None.

    Args:
        jobs: the run's jobs as GitHub lists them
        environment: the source environment

    Returns:
        str | None: the job's completion time, None when no store job of that environment succeeded with its step
    """
    name  = STORE_JOB.format(environment = environment)
    found = []
    for job in jobs:
        if not str(job.get("name", "")).endswith(name) or job.get("conclusion") != "success":
            continue
        steps = job.get("steps") or []
        if any(step.get("name") == STORE_STEP and step.get("conclusion") == "success" for step in steps):
            found.append(str(job.get("completed_at") or ""))
    return max(filter(None, found), default = None)


def _moment(stamp: str) -> datetime:
    """
    A GitHub time as a moment in UTC.

    Args:
        stamp: `2026-11-20T06:30:00Z`

    Returns:
        datetime: the moment
    """
    return datetime.strptime(stamp, STAMP).replace(tzinfo = timezone.utc)

# ======================================================================================================================
# The collector
# ======================================================================================================================

def collect_entry(transport: Any, entry: dict[str, Any], now: datetime, days: int) -> dict[str, Any]:
    """
    One backup workflow's freshness.

    Args:
        transport: how GitHub is reached, the watch's own
        entry: the registry's entry
        now: the watch's moment
        days: the days a backup stays fresh

    Returns:
        dict[str, Any]: the entry's repo, workflow and app, each finding as a stable key and its text, each
            environment's newest store time, and why it could not be read, None when it was
    """
    repo, workflow = entry["repo"], entry["workflow"]
    result: dict[str, Any] = {
        "repo": repo,
        "workflow": workflow,
        "app": entry["app"],
        "findings": [],
        "fresh": {},
        "error": None,
    }
    flow = transport.get(f"/repos/{repo}/actions/workflows/{workflow}")
    if flow.status == 404:
        result["findings"].append({"key": "missing", "text": "missing, the repository has no workflow of that name"})
        return result
    if not flow.ok or not isinstance(flow.data, dict):
        result["error"] = flow.reason()
        return result
    if flow.data.get("state") != "active":
        result["findings"].append({"key": "disabled", "text": f"disabled, its state is {flow.data.get('state')}"})

    since = (now - timedelta(days = WINDOW_DAYS)).strftime("%Y-%m-%d")
    runs  = transport.get(
        f"/repos/{repo}/actions/workflows/{workflow}/runs",
        {"per_page": RUNS_READ, "created": f">={since}"},
    )
    if not runs.ok or not isinstance(runs.data, dict):
        result["error"] = runs.reason()
        return result
    completed = [run for run in runs.data.get("workflow_runs") or [] if run.get("status") == "completed"]
    if completed and completed[0].get("conclusion") == "failure":
        result[
            "findings"
        ].append({"key": "failing", "text": f"failing, its newest run failed, {completed[0].get('html_url')}"})

    scheduled = next((run for run in completed if run.get("event") == "schedule"), None)
    if scheduled is None:
        result["findings"].append({
            "key": "unscheduled",
            "text": f"with no scheduled run in {WINDOW_DAYS} days, its schedule absent or never armed",
        })
    newest: dict[str, str] = {}
    for run in completed:
        jobs = transport.get(f"/repos/{repo}/actions/runs/{run.get('id')}/jobs", {"per_page": 100})
        if not jobs.ok or not isinstance(jobs.data, dict):
            result["error"] = jobs.reason()
            return result
        listed = jobs.data.get("jobs") or []
        if run is scheduled and listed and all(job.get("conclusion") == "skipped" for job in listed):
            result["findings"].append({
                "key": "disarmed",
                "text": "disarmed, its newest scheduled run skipped every job, so its arming variable is off",
            })
        for environment in entry["environments"]:
            stamp = stored_at(listed, environment)
            if stamp and stamp > newest.get(environment, ""):
                newest[environment] = stamp

    result["fresh"] = newest
    for environment in entry["environments"]:
        stamp = newest.get(environment)
        if stamp is None or now - _moment(stamp) > timedelta(days = days):
            result["findings"].append({
                "key": f"stale:{environment}",
                "text": f"stale in {environment}, no backup stored and read back in {days} days, the newest "
                        f"{stamp or f'none in {WINDOW_DAYS} days'}",
            })
    return result


def collect_backups(transport: Any, now: datetime, registry: Path = REGISTRY) -> list[dict[str, Any]]:
    """
    Every listed backup workflow's freshness.

    Args:
        transport: how GitHub is reached
        now: the watch's moment
        registry: the registry's file

    Returns:
        list[dict[str, Any]]: each entry's freshness
    """
    days, entries = read_registry(registry)
    return [collect_entry(transport, entry, now, days) for entry in entries]
