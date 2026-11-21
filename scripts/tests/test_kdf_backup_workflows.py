"""
The backup's and the restore's workflows hold their secrets apart (the secrets moves, step 2, D-111).

Any step can change what a later step of its job runs, so the backup's caller tool runs in a job holding the source's
string alone, and the store's job, holding the HMAC key and the writer's string, runs cicd's code alone. In each
restore job every step that holds a secret runs before the caller's tool. A drill is held to the job's own service.
The live restore and the python deploy share the one database lock of the repository and environment.
"""

from __future__ import annotations

# standard imports
import re
from pathlib import Path
from typing import Any

# third party imports
import pytest
import yaml


WORKFLOWS: Path = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SECRET:    re.Pattern[str] = re.compile(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}")
CALLER:    re.Pattern[str] = re.compile(r"\$\{\{\s*inputs\.[a-z_]+_command\s*\}\}")
LOCK:      str = "kdf-database-${{ github.repository }}-${{ inputs.environment }}"


def workflow(name: str) -> dict[str, Any]:
    """
    A workflow's jobs, read as YAML.

    Args:
        name: its file name

    Returns:
        dict[str, Any]: its jobs by key
    """
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding = "utf-8"))["jobs"]


def secrets_of(node: Any) -> set[str]:
    """
    Every secret a job's or a step's text names.

    Args:
        node: the job or the step

    Returns:
        set[str]: the secrets' names
    """
    return set(SECRET.findall(yaml.safe_dump(node)))


def caller_step(steps: list[dict[str, Any]]) -> int:
    """
    The index of the step that runs the caller's own command.

    Args:
        steps: a job's steps

    Returns:
        int: its index
    """
    return next(index for index, step in enumerate(steps) if CALLER.search(str(step.get("run", ""))))

# ======================================================================================================================
# The backup
# ======================================================================================================================

def test_each_backup_job_holds_its_own_secrets_alone() -> None:
    jobs = workflow("db-backup.yml")

    assert secrets_of(jobs["precheck"]) == {"BACKUP_STORE_WRITER_URL"}
    assert secrets_of(jobs["dump"]) == {"DB_BACKUP_URL"}
    assert secrets_of(jobs["store"]) == {"BACKUP_HMAC_KEY", "BACKUP_STORE_WRITER_URL"}
    assert secrets_of(jobs["authorize"]) == set() and secrets_of(jobs["report"]) == set()


def test_the_store_job_runs_cicds_code_alone() -> None:
    store = workflow("db-backup.yml")["store"]

    assert not any(CALLER.search(str(step.get("run", ""))) for step in store["steps"])
    checkouts = [step for step in store["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")]
    assert [step["with"]["repository"] for step in checkouts] == ["Needless2Say/kriegerdataforge-cicd"]


def test_the_dump_steps_secret_reaches_the_dump_alone() -> None:
    steps = workflow("db-backup.yml")["dump"]["steps"]
    dump  = caller_step(steps)

    assert [secrets_of(step) for step in steps if secrets_of(step)] == [{"DB_BACKUP_URL"}]
    assert secrets_of(steps[dump]) == {"DB_BACKUP_URL"}


def test_the_sealed_archive_alone_leaves_the_dump_job_and_for_a_day() -> None:
    steps   = workflow("db-backup.yml")["dump"]["steps"]
    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")]

    assert len(uploads) == 1
    assert uploads[0]["with"]["retention-days"] == 1
    paths = [line.strip() for line in uploads[0]["with"]["path"].splitlines() if line.strip()]
    assert [path.rsplit("/", 1)[-1] for path in paths] == ["archive.age", "metadata.json"]


@pytest.mark.parametrize("job", ["precheck", "store"])
def test_the_store_client_is_installed_by_its_hashes_alone(job: str) -> None:
    runs = " ".join(str(step.get("run", "")) for step in workflow("db-backup.yml")[job]["steps"])

    assert "--require-hashes --no-deps --only-binary=:all:" in runs
    assert "pip install psycopg" not in runs

# ======================================================================================================================
# The restore
# ======================================================================================================================

@pytest.mark.parametrize("job", ["drill-16", "drill-17", "live"])
def test_every_secret_of_a_restore_job_is_used_before_the_callers_tool(job: str) -> None:
    steps  = workflow("db-restore.yml")[job]["steps"]
    caller = caller_step(steps)
    after  = set().union(*(secrets_of(step) for step in steps[caller + 1:]))

    assert after <= ({"DB_DATABASE_URL"} if job == "live" else set())
    assert secrets_of(steps[caller]) <= ({"DB_DATABASE_URL"} if job == "live" else set())


@pytest.mark.parametrize("job", ["drill-16", "drill-17"])
def test_a_drill_targets_its_own_service_and_never_a_live_database(job: str) -> None:
    drill = workflow("db-restore.yml")[job]

    assert drill["env"]["KDF_MODE"] == "drill"
    assert drill["env"]["KDF_RESTORE_TARGET_URL"].startswith("postgresql://kdf_drill:kdf-drill-local@127.0.0.1:5432/")
    assert "DB_DATABASE_URL" not in secrets_of(drill)
    assert "concurrency" not in drill


def test_the_live_restore_and_the_python_deploy_share_the_one_database_lock() -> None:
    live   = workflow("db-restore.yml")["live"]
    deploy = workflow("cd-python-vercel.yml")["deploy"]

    assert live["concurrency"] == {"group": LOCK, "cancel-in-progress": False}
    assert deploy["concurrency"] == {"group": LOCK, "cancel-in-progress": False}


def test_a_live_restore_into_prod_asks_its_confirm_before_any_secret() -> None:
    plan  = workflow("db-restore.yml")["plan"]["steps"]
    first = next(index for index, step in enumerate(plan) if secrets_of(step))

    assert "restore ${KDF_APP} prod ${KDF_BACKUP_ID}" in plan[0]["run"]
    assert first > 0
