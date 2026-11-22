"""
The OIDC client secrets' generations (the secrets moves' step 3, D-112), oidc_generations.py and its workflow.

A generation is recorded before any write, its value's fingerprint among it. The value is made once, masked before any
use, and written first to its source in cicd's ops, the one recoverable copy, then to the hub's pending name, then,
once the hub registered it, to terraform's active name, and the pending copy and the source are deleted once
terraform applied it and the app redeployed. Each outside event is a run the owner names, checked by its repository,
workflow, branch, result, job and time. A crash after or before any write resumes in a new process holding none of the
first's state, and the flow ends on one value, never in the log. No generation starts while another of its client and
environment is open.
"""

from __future__ import annotations

# standard imports
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# third party imports
import oidc_generations as og
import pytest
import rotate_secret as rs
import yaml


ROOT     = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "oidc-client-secrets.yml"
REGISTRY = ROOT / "scripts" / "secret_registry.json"
CICD     = "Needless2Say/kriegerdataforge-cicd"
HUB      = "Needless2Say/kriegerdataforge"
TF       = "Needless2Say/kriegerdataforge-terraform"
APP      = "Needless2Say/fitness-app-frontend"
OPS      = f"{CICD}:ops"
HUB_DEV  = f"{HUB}:dev"
TF_DEV   = f"{TF}:dev"
SOURCE   = "OIDC_FITNESS_DEV_SOURCE"
PENDING  = "KDF_OIDC_PENDING_SECRET_FITNESS"
ACTIVE   = "FITNESS_OIDC_CLIENT_SECRET"
REGISTER = "Register the pending secret of fitness"
START    = datetime(2026, 11, 22, 12, 0, tzinfo = UTC)
STAMP    = "%Y-%m-%dT%H:%M:%SZ"


ENTRY: dict[str, Any] = {
    "name": ACTIVE,
    "kind": "engine_generated",
    "consumer": "terraform",
    "terraform_managed": True,
    "client": "fitness",
    "sources": [
        {"environment": "dev", "secret_name": SOURCE},
        {"environment": "prod", "secret_name": "OIDC_FITNESS_PROD_SOURCE"},
    ],
    "pending_github_env_secrets": [
        {"app": "auth-backend", "repo": HUB, "environment": "dev", "secret_name": PENDING},
        {"app": "auth-backend", "repo": HUB, "environment": "prod", "secret_name": PENDING},
    ],
    "github_env_secrets": [
        {"app": "infra", "repo": TF, "environment": "dev", "secret_name": ACTIVE},
        {"app": "infra", "repo": TF, "environment": "prod", "secret_name": ACTIVE},
    ],
    "evidence": {
        "registered": {
            "repo": HUB,
            "workflows": [".github/workflows/oidc-clients.yml"],
            "jobs": {"dev": f"{REGISTER} (dev)", "prod": f"{REGISTER} (prod)"},
        },
        "applied": {
            "repo": TF,
            "workflows": [".github/workflows/cd.yml", ".github/workflows/release.yml"],
            "jobs": {"dev": "Terraform apply (dev)", "prod": "Terraform deploy (prod)"},
        },
        "deployed": {
            "repo": APP,
            "workflows": [".github/workflows/cd.yml"],
            "jobs": {"dev": "Deploy (dev)", "prod": "Deploy (prod)"},
        },
    },
}


class Crash(Exception):
    """
    The process dying at a write.
    """


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def stamp(moment: datetime) -> str:
    return moment.strftime(STAMP)


def parse(text: str) -> datetime:
    return datetime.strptime(text, STAMP).replace(tzinfo = UTC)


class Store:
    """
    What GitHub holds between processes, every secret with its update time, the record, the runs and their jobs, and
    the one crash a test asks for, at the write of that number counted across every process.
    """
    def __init__(self, crash_after: int | None = None, crash_before: int | None = None) -> None:
        self.secrets: dict[tuple[str, str], tuple[str, datetime]] = {}
        self.record:  str | None = None
        self.runs:    dict[tuple[str, str], dict[str, Any]] = {}
        self.jobs:    dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.clock = START
        self.writes:      list[tuple[str, str, str]] = []
        self.count        = 0
        self.crash_after  = crash_after
        self.crash_before = crash_before
        self.made:        list[tuple[str, str, str]] = []


    def tick(self) -> datetime:
        self.clock += timedelta(minutes = 1)
        return self.clock


    def change(self) -> int:
        self.count += 1
        if self.count == self.crash_before:
            self.crash_before = None
            raise Crash("the process died before its write landed")
        return self.count


    def changed(self, number: int) -> None:
        if number == self.crash_after:
            self.crash_after = None
            raise Crash("the process died after its write landed, its answer lost")


class Fake:
    """
    One process's view of GitHub.
    """
    def __init__(self, store: Store) -> None:
        self.store = store


    def write_secret(self, target: str, name: str, value: str) -> None:
        number = self.store.change()
        self.store.secrets[(target, name)] = (value, self.store.tick())
        self.store.writes.append((target, name, fingerprint(value)))
        self.store.changed(number)


    def secret_updated_at(self, target: str, name: str) -> str | None:
        held = self.store.secrets.get((target, name))
        return stamp(held[1]) if held else None


    def delete_secret(self, target: str, name: str) -> None:
        number = self.store.change()
        self.store.secrets.pop((target, name), None)
        self.store.changed(number)


    def read_record(self) -> str | None:
        return self.store.record


    def write_record(self, text: str) -> None:
        self.store.record = text


    def run(self, repo: str, run_id: str) -> dict[str, Any] | None:
        return self.store.runs.get((repo, run_id))


    def jobs(self, repo: str, run_id: str) -> list[dict[str, Any]]:
        return self.store.jobs.get((repo, run_id), [])


def engine(store: Store, masked: list[str] | None = None) -> og.Engine:
    """
    A new process, holding none of an earlier one's state.

    Args:
        store: what GitHub holds
        masked: where the values it masks are kept

    Returns:
        og.Engine: the engine
    """
    return og.Engine(
        Fake(store),
        [ENTRY],
        now = store.tick,
        run_id = str(9000 + store.count),
        mask = (masked if masked is not None else []).append,
    )


def source(store: Store, target: str = OPS, name: str = SOURCE) -> str:
    """
    A secret as the next job's secrets context gives it, empty when it is not set.

    Args:
        store: what GitHub holds
        target: its environment
        name: its name

    Returns:
        str: its value
    """
    held = store.secrets.get((target, name))
    return held[0] if held else ""


def record(store: Store) -> dict[str, Any]:
    return json.loads(store.record or "{}")


def generation(store: Store) -> dict[str, Any]:
    return record(store)["generations"][-1]


def a_run(store: Store, repo: str, workflow: str, job: str, after: str, **changes: Any) -> str:
    """
    A run of *workflow* in *repo* that succeeded on main, created a minute after *after*, its working job called from
    a caller as GitHub names a reusable workflow's job.

    Args:
        store: what GitHub holds
        repo: its repository
        workflow: its workflow's path
        job: its working job's name
        after: a time it was created after
        **changes: fields to replace, `jobs` its jobs

    Returns:
        str: its id
    """
    run_id  = str(1000 + len(store.runs))
    created = parse(after) + timedelta(minutes = 1)
    jobs    = changes.pop("jobs", [{"name": f"Caller / {job}", "conclusion": "success"}])
    store.runs[(repo, run_id)] = {
        "id": int(run_id),
        "path": workflow,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "created_at": stamp(created),
        "updated_at": stamp(created + timedelta(minutes = 5)),
        "repository": {"full_name": repo},
        **changes,
    }
    store.jobs[(repo, run_id)] = jobs
    return run_id


def hub_run(store: Store, **changes: Any) -> str:
    after = generation(store)["at"]["distributed"]
    return a_run(store, HUB, ".github/workflows/oidc-clients.yml", f"{REGISTER} (dev)", after, **changes)


def apply_run(store: Store, workflow: str = ".github/workflows/release.yml", **changes: Any) -> str:
    return a_run(store, TF, workflow, "Terraform apply (dev)", generation(store)["at"]["promoted"], **changes)


def deploy_run(store: Store, applied: str, **changes: Any) -> str:
    after = store.runs[(TF, applied)]["updated_at"]
    return a_run(store, APP, ".github/workflows/cd.yml", "Deploy (dev)", after, **changes)


def step(store: Store, name: str) -> None:
    """
    One step of a generation, as a new process runs it, its evidence made first.

    Args:
        store: what GitHub holds
        name: generate, register, promote or finish
    """
    if name == "generate":
        engine(store).generate("fitness", "dev", source(store))
    elif name == "register":
        engine(store).register("fitness", "dev", hub_run(store))
    elif name == "promote":
        engine(store).promote("fitness", "dev", source(store))
    else:
        applied = apply_run(store)
        engine(store).finish("fitness", "dev", applied, deploy_run(store, applied))


def to(store: Store, last: str) -> None:
    """
    A generation carried through its steps up to *last*.

    Args:
        store: what GitHub holds
        last: the last step run
    """
    for name in ("generate", "register", "promote", "finish"):
        step(store, name)
        if name == last:
            return

# ======================================================================================================================
# The control, every step
# ======================================================================================================================

def test_a_generation_runs_every_step_and_ends_on_one_value(capsys: pytest.CaptureFixture[str]) -> None:
    store, masked = Store(), []

    engine(store, masked).generate("fitness", "dev", source(store))
    value = source(store)
    for name in ("register", "promote", "finish"):
        step(store, name)

    done = generation(store)
    assert store.secrets[(TF_DEV, ACTIVE)][0] == value
    assert (HUB_DEV, PENDING) not in store.secrets and (OPS, SOURCE) not in store.secrets
    assert done["phase"] == "done" and done["fingerprint"] == fingerprint(value)
    assert {written for _, _, written in store.writes} == {fingerprint(value)}
    assert [(target, name) for target, name, _ in store.writes] == [(OPS, SOURCE), (HUB_DEV, PENDING), (TF_DEV, ACTIVE)]
    assert set(
        done["runs"],
    ) >= {"intended", "generated", "distributed", "registered", "promoted", "applied", "deployed"}
    assert masked == [value] and len(value) == 64 and int(value, 16) >= 0
    assert value not in capsys.readouterr().out and value not in (store.record or "")


def test_the_fingerprint_is_recorded_before_the_value_is_written_anywhere() -> None:
    store = Store(crash_before = 1)

    with pytest.raises(Crash):
        engine(store).generate("fitness", "dev", source(store))

    assert generation(store)["phase"] == "intended"
    assert len(generation(store)["fingerprint"]) == 16
    assert not store.secrets and not store.writes

# ======================================================================================================================
# A crash at each write, resumed by a new process
# ======================================================================================================================

def test_a_crash_after_the_source_landed_resumes_on_that_value() -> None:
    store = Store(crash_after = 1)
    with pytest.raises(Crash):
        engine(store).generate("fitness", "dev", source(store))
    first = source(store)

    engine(store).generate("fitness", "dev", source(store))

    assert [name for _, name, _ in store.writes].count(SOURCE) == 1, "its fingerprint matched, so it was never remade"
    assert generation(store)["fingerprint"] == fingerprint(first) and generation(store)["phase"] == "distributed"
    assert source(store, HUB_DEV, PENDING) == first


def test_a_crash_before_the_source_landed_makes_its_one_value_then() -> None:
    store = Store(crash_before = 1)
    with pytest.raises(Crash):
        engine(store).generate("fitness", "dev", source(store))
    lost = generation(store)["fingerprint"]

    engine(store).generate("fitness", "dev", source(store))

    assert [name for _, name, _ in store.writes].count(SOURCE) == 1
    assert generation(store)["fingerprint"] == fingerprint(source(store)) != lost
    assert len(record(store)["generations"]) == 1


@pytest.mark.parametrize("when", ["crash_after", "crash_before"])
@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
def test_a_crash_at_any_write_resumes_and_ends_on_one_value(
    capsys: pytest.CaptureFixture[str],
    when: str,
    number: int,
) -> None:
    store = Store(**{when: number})

    for name in ("generate", "register", "promote", "finish"):
        try:
            step(store, name)
        except Crash:
            step(store, name)

    done   = generation(store)
    active = store.secrets[(TF_DEV, ACTIVE)][0]
    assert done["phase"] == "done"
    assert {written for _, _, written in store.writes} == {done["fingerprint"]} == {fingerprint(active)}
    assert (HUB_DEV, PENDING) not in store.secrets and (OPS, SOURCE) not in store.secrets
    assert len(record(store)["generations"]) == 1
    assert active not in capsys.readouterr().out and active not in (store.record or "")

# ======================================================================================================================
# One at a time, and the order
# ======================================================================================================================

@pytest.mark.parametrize("last", ["generate", "register", "promote"])
def test_no_new_generation_starts_while_one_is_open(last: str) -> None:
    store = Store()
    to(store, last)

    with pytest.raises(og.Refused, match = "open"):
        engine(store).generate("fitness", "dev", source(store))

    assert len(record(store)["generations"]) == 1


def test_a_new_generation_starts_once_the_last_is_done() -> None:
    store = Store()
    to(store, "finish")

    engine(store).generate("fitness", "dev", source(store))

    assert [(g["id"], g["phase"]) for g in record(store)["generations"]] == [("O1", "done"), ("O2", "distributed")]


def test_another_environment_starts_its_own() -> None:
    store = Store()
    to(store, "generate")

    engine(store).generate("fitness", "prod", source(store, OPS, "OIDC_FITNESS_PROD_SOURCE"))

    assert [g["environment"] for g in record(store)["generations"]] == ["dev", "prod"]


@pytest.mark.parametrize(
    ("last", "call", "needed"),
    [
        ("generate", "promote", "registered"),
        ("generate", "finish", "promoted"),
        ("register", "register", "distributed"),
        ("register", "finish", "promoted"),
        ("promote", "promote", "registered"),
    ],
)
def test_a_step_out_of_its_order_is_refused(last: str, call: str, needed: str) -> None:
    store = Store()
    to(store, last)
    before = store.record

    with pytest.raises(og.Refused, match = needed):
        if call == "promote":
            engine(store).promote("fitness", "dev", source(store))
        elif call == "register":
            engine(store).register("fitness", "dev", "1000")
        else:
            engine(store).finish("fitness", "dev", "1000", "1001")

    assert store.record == before


@pytest.mark.parametrize("given", ["0" * 64, "", "not a value"])
def test_a_source_that_is_not_the_generations_value_is_refused(given: str) -> None:
    store = Store()
    to(store, "register")

    with pytest.raises(og.Refused, match = "fingerprint"):
        engine(store).promote("fitness", "dev", given)

    assert (TF_DEV, ACTIVE) not in store.secrets and generation(store)["phase"] == "registered"

# ======================================================================================================================
# The evidence of each outside event
# ======================================================================================================================

@pytest.mark.parametrize(
    "changes",
    [
        {"path": ".github/workflows/cd.yml"},
        {"head_branch": "feature/x"},
        {"conclusion": "failure"},
        {"status": "in_progress", "conclusion": None},
        {"repository": {"full_name": "Someone/kriegerdataforge"}},
        {"created_at": "2026-11-22T11:00:00Z"},
        {"jobs": []},
        {"jobs": [{"name": f"Caller / {REGISTER} (dev)", "conclusion": "skipped"}]},
        {"jobs": [{"name": f"Caller / {REGISTER} (prod)", "conclusion": "success"}]},
        {"jobs": [{"name": "Register the pending secret of tiffanys-space (dev)", "conclusion": "success"}]},
    ],
)
def test_a_registration_run_out_of_its_shape_is_refused(changes: dict[str, Any]) -> None:
    store = Store()
    to(store, "generate")
    run = hub_run(store, **changes)

    with pytest.raises(og.Refused):
        engine(store).register("fitness", "dev", run)

    assert generation(store)["phase"] == "distributed"


@pytest.mark.parametrize("run_id", ["424242", "12a", "", "0", "../1", "1" * 21])
def test_an_unknown_or_malformed_run_id_is_refused(run_id: str) -> None:
    store = Store()
    to(store, "generate")

    with pytest.raises(og.Refused):
        engine(store).register("fitness", "dev", run_id)


def test_the_registering_job_may_be_the_workflows_own_or_a_callers() -> None:
    store = Store()
    to(store, "generate")
    run = hub_run(store, jobs = [{"name": f"{REGISTER} (dev)", "conclusion": "success"}])

    engine(store).register("fitness", "dev", run)

    assert generation(store)["phase"] == "registered" and generation(store)["runs"]["registered"] == int(run)


@pytest.mark.parametrize("workflow", [".github/workflows/cd.yml", ".github/workflows/release.yml"])
def test_either_terraform_workflow_may_carry_the_apply(workflow: str) -> None:
    store = Store()
    to(store, "promote")
    applied = apply_run(store, workflow)

    engine(store).finish("fitness", "dev", applied, deploy_run(store, applied))

    assert generation(store)["phase"] == "done" and generation(store)["runs"]["applied"] == int(applied)


@pytest.mark.parametrize(
    "case",
    [
        "apply before the promotion",
        "a validate run",
        "the apply skipped",
        "deploy before the apply ended",
        "prod deploy",
    ],
)
def test_a_finish_without_its_apply_and_its_later_deploy_is_refused(case: str) -> None:
    store = Store()
    to(store, "promote")
    promoted = parse(generation(store)["at"]["promoted"])
    applied  = apply_run(store)
    if case == "apply before the promotion":
        store.runs[(TF, applied)]["created_at"] = stamp(promoted - timedelta(minutes = 1))
    elif case == "a validate run":
        store.jobs[(TF, applied)] = [{"name": "Caller / Terraform validate (dev)", "conclusion": "success"}]
    elif case == "the apply skipped":
        store.jobs[(TF, applied)] = [{"name": "Apply the release to DEV", "conclusion": "skipped"}]
    deployed = deploy_run(store, applied)
    if case == "deploy before the apply ended":
        store.runs[(APP, deployed)]["created_at"] = store.runs[(TF, applied)]["created_at"]
    elif case == "prod deploy":
        store.jobs[(APP, deployed)] = [{"name": "Deploy to prod / Deploy (prod)", "conclusion": "success"}]

    with pytest.raises(og.Refused):
        engine(store).finish("fitness", "dev", applied, deployed)

    assert (HUB_DEV, PENDING) in store.secrets and (OPS, SOURCE) in store.secrets
    assert generation(store)["phase"] == "promoted"

# ======================================================================================================================
# The recovery
# ======================================================================================================================

@pytest.mark.parametrize("last", ["generate", "register", "promote"])
def test_a_recovery_closes_the_named_generation_and_never_touches_the_active_copy(last: str) -> None:
    store = Store()
    store.secrets[(TF_DEV, ACTIVE)] = ("a" * 64, START)
    to(store, last)
    active = store.secrets[(TF_DEV, ACTIVE)]

    engine(store).recover("fitness", "dev", "O1", "the hub refused the registration")

    closed = generation(store)
    assert closed["phase"] == "abandoned" and closed["recovery"]["reason"] == "the hub refused the registration"
    assert store.secrets[(TF_DEV, ACTIVE)] == active
    assert (HUB_DEV, PENDING) not in store.secrets and (OPS, SOURCE) not in store.secrets
    engine(store).generate("fitness", "dev", source(store))
    assert [g["phase"] for g in record(store)["generations"]] == ["abandoned", "distributed"]


@pytest.mark.parametrize(
    ("generation_id", "reason"),
    [("O2", "a reason given"), ("O1", ""), ("O1", "x" * 201), ("O1", "two\n::warning::lines"), ("1", "a reason")],
)
def test_a_recovery_of_another_generation_or_with_a_bad_reason_is_refused(generation_id: str, reason: str) -> None:
    store = Store()
    to(store, "generate")

    with pytest.raises(og.Refused):
        engine(store).recover("fitness", "dev", generation_id, reason)

    assert generation(store)["phase"] == "distributed" and (HUB_DEV, PENDING) in store.secrets


def test_a_recovery_with_no_open_generation_is_refused() -> None:
    store = Store()
    to(store, "finish")

    with pytest.raises(og.Refused, match = "open"):
        engine(store).recover("fitness", "dev", "O1", "nothing is open")

# ======================================================================================================================
# The inputs and the record
# ======================================================================================================================

@pytest.mark.parametrize(
    ("client", "environment"),
    [("tiffanys-space", "dev"), ("fitness", "staging"), ("../x", "dev"), ("", "dev"), ("fitness\n", "dev")],
)
def test_a_client_or_environment_the_registry_does_not_hold_is_refused(client: str, environment: str) -> None:
    store = Store()

    with pytest.raises(og.Refused):
        engine(store).generate(client, environment, "")

    assert store.record is None and not store.writes


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"version": 2, "next": 1, "generations": []}),
        json.dumps({"version": 1, "next": 1, "generations": 7}),
        json.dumps({"version": 1, "next": "1", "generations": []}),
        json.dumps({"version": 1, "next": 2, "generations": [{"id": "O1", "phase": "lost"}]}),
    ],
)
def test_a_record_out_of_its_shape_stops_the_run(text: str) -> None:
    store        = Store()
    store.record = text

    with pytest.raises(og.RecordError):
        engine(store).generate("fitness", "dev", source(store))

    assert store.record == text and not store.writes


def test_the_record_keeps_every_open_generation_and_the_last_closed_ones() -> None:
    closed       = [
        {
            "id": f"O{number}",
            "client": "fitness",
            "environment": "dev",
            "phase": "abandoned",
            "fingerprint": None,
            "at": {},
            "runs": {},
            "recovery": None,
        }
        for number in range(1, 15)
    ]
    store        = Store()
    store.record = json.dumps({"version": 1, "next": 15, "generations": closed})

    engine(store).generate("fitness", "dev", "")

    assert [g["id"] for g in record(store)["generations"]] == [f"O{number}" for number in range(3, 16)]


def test_the_status_names_each_generation_and_never_a_value(capsys: pytest.CaptureFixture[str]) -> None:
    store = Store()
    to(store, "finish")
    engine(store).generate("fitness", "dev", source(store))
    value = source(store)

    engine(store).status()

    out = capsys.readouterr().out
    assert "O1 fitness dev done" in out and "O2 fitness dev distributed" in out
    assert value not in out

# ======================================================================================================================
# The command, in Actions alone
# ======================================================================================================================

class Printing(Fake):
    """
    A view of GitHub that prints each write's place, so the log's order shows the mask came first.
    """
    def write_secret(self, target: str, name: str, value: str) -> None:
        print(f"WRITE {target} {name}")
        super().write_secret(target, name, value)


@pytest.fixture
def actions(monkeypatch: pytest.MonkeyPatch) -> Store:
    store = Store()


    def live(gh_token: str, facts_token: str, runs_token: str) -> Printing:
        store.made.append((gh_token, facts_token, runs_token))
        return Printing(store)


    monkeypatch.setattr(og, "LiveGitHub", live)
    monkeypatch.setattr(og, "registry_entries", lambda: [ENTRY])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GH_TOKEN", "writer")
    monkeypatch.setenv("FACTS_GH_TOKEN", "facts")
    monkeypatch.setenv("RUNS_GH_TOKEN", "runs")
    monkeypatch.delenv(SOURCE, raising = False)
    return store


def test_the_command_masks_a_made_value_before_any_write(actions: Store, capsys: pytest.CaptureFixture[str]) -> None:
    assert og.main(["--mode", "generate", "--client", "fitness", "--environment", "dev"]) == 0

    value = source(actions)
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if value in line] == [f"::add-mask::{value}"]
    assert lines.index(f"::add-mask::{value}") < lines.index(f"WRITE {OPS} {SOURCE}")
    assert actions.made == [("writer", "facts", "runs")]


def test_the_command_reads_the_selected_source_alone(actions: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    og.main(["--mode", "generate", "--client", "fitness", "--environment", "dev"])
    value = source(actions)
    og.main(["--mode", "register", "--client", "fitness", "--environment", "dev", "--registered-run", hub_run(actions)])
    monkeypatch.setenv("OIDC_FITNESS_PROD_SOURCE", value)

    assert og.main(["--mode", "promote", "--client", "fitness", "--environment", "dev"]) == 1
    monkeypatch.setenv(SOURCE, value)
    assert og.main(["--mode", "promote", "--client", "fitness", "--environment", "dev"]) == 0
    assert source(actions, TF_DEV, ACTIVE) == value


def test_the_command_runs_in_actions_alone(actions: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS")

    assert og.main(["--mode", "generate", "--client", "fitness", "--environment", "dev"]) == 1
    assert actions.record is None and not actions.made


@pytest.mark.parametrize(("mode", "missing"), [("generate", "GH_TOKEN"), ("register", "RUNS_GH_TOKEN")])
def test_each_mode_needs_its_tokens_and_the_status_the_facts_token_alone(
    actions: Store,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    missing: str,
) -> None:
    monkeypatch.delenv(missing)

    assert og.main(["--mode", mode, "--client", "fitness", "--environment", "dev", "--registered-run", "1"]) == 1
    monkeypatch.delenv("GH_TOKEN", raising = False)
    monkeypatch.delenv("RUNS_GH_TOKEN", raising = False)
    assert og.main(["--mode", "status"]) == 0
    assert actions.record is None


def test_a_refusal_fails_the_command_with_its_reason(actions: Store, capsys: pytest.CaptureFixture[str]) -> None:
    assert og.main(["--mode", "promote", "--client", "fitness", "--environment", "dev"]) == 1

    assert "Error: no generation of fitness in dev is open" in capsys.readouterr().err

# ======================================================================================================================
# The live seam, token_generations' GitHub with this flow's record and a reading token for the runs
# ======================================================================================================================

class Response:
    """
    One answer of GitHub's API.
    """
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self.ok          = status < 400
        self.body        = body or {}


    def json(self) -> dict[str, Any]:
        return self.body


    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    """
    The engine's HTTP session, answering each call from a table and keeping its verb, URL and token.
    """
    def __init__(self, answers: dict[str, Response]) -> None:
        self.answers = answers
        self.calls:  list[tuple[str, str, str]] = []


    def _call(self, verb: str, url: str, headers: dict[str, str]) -> Response:
        self.calls.append((verb, url, headers["Authorization"]))
        return self.answers.get(f"{verb} {url}", Response(404))


    def get(self, url: str, headers: dict[str, str], **_: Any) -> Response:
        return self._call("GET", url, headers)


    def patch(self, url: str, headers: dict[str, str], **_: Any) -> Response:
        return self._call("PATCH", url, headers)


    def post(self, url: str, headers: dict[str, str], **_: Any) -> Response:
        return self._call("POST", url, headers)


def test_the_live_seam_keeps_this_flows_record_with_the_facts_token(monkeypatch: pytest.MonkeyPatch) -> None:
    url     = f"{rs.GITHUB_API}/repos/{CICD}/environments/ops/variables/OIDC_SECRET_RECORD"
    session = Session({f"GET {url}": Response(200, {"value": "{}"}), f"PATCH {url}": Response(204)})
    monkeypatch.setattr(rs, "_SESSION", session)
    live = og.LiveGitHub("writer", "facts", "runs")

    assert live.read_record() == "{}"
    live.write_record("{}")

    assert [(verb, called) for verb, called, _ in session.calls] == [("GET", url), ("PATCH", url)]
    assert {rs._github_headers("facts")["Authorization"]} == {token for _, _, token in session.calls}


def test_the_live_seam_reads_runs_with_the_reading_token(monkeypatch: pytest.MonkeyPatch) -> None:
    url     = f"{rs.GITHUB_API}/repos/{HUB}/actions/runs/1000"
    session = Session({f"GET {url}": Response(200, {"id": 1000}), f"GET {url}/jobs": Response(200, {"jobs": []})})
    monkeypatch.setattr(rs, "_SESSION", session)
    live = og.LiveGitHub("writer", "facts", "runs")

    assert live.run(HUB, "1000") == {"id": 1000} and live.jobs(HUB, "1000") == []
    assert live.run(HUB, "1001") is None

    assert {rs._github_headers("runs")["Authorization"]} == {token for _, _, token in session.calls}


def test_the_live_seam_writes_and_deletes_secrets_with_the_writers_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(rs, "update_github_env_secret", lambda *args: calls.append(("write", *args[:4])))
    monkeypatch.setattr(rs, "delete_github_env_secret", lambda *args: calls.append(("delete", *args)))
    monkeypatch.setattr(rs, "github_env_secret_updated_at", lambda *args: calls.append(("read", *args)) or "t")
    live = og.LiveGitHub("writer", "facts", "runs")

    live.write_secret(HUB_DEV, PENDING, "v" * 64)
    assert live.secret_updated_at(HUB_DEV, PENDING) == "t"
    live.delete_secret(HUB_DEV, PENDING)

    assert calls == [
        ("write", "writer", HUB, "dev", PENDING),
        ("read", "writer", HUB, "dev", PENDING),
        ("delete", "writer", HUB, "dev", PENDING),
    ]

# ======================================================================================================================
# The registry and the engine's refusal
# ======================================================================================================================

def kind_entries() -> list[dict[str, Any]]:
    entries = json.loads(REGISTRY.read_text(encoding = "utf-8"))["secrets"]
    return [entry for entry in entries if entry.get("kind") == "engine_generated"]


def test_the_registry_holds_each_client_with_its_three_homes_in_dev_and_prod() -> None:
    entries   = {entry["client"]: entry for entry in kind_entries()}
    frontends = {"fitness": "fitness-app-frontend", "tiffanys-space": "tiffanys-space"}
    assert sorted(entries) == sorted(frontends) and og.registry_entries() == list(entries.values())
    for client, entry in entries.items():
        upper = client.upper().replace("-", "_")
        assert entry["name"] == f"{upper}_OIDC_CLIENT_SECRET", "terraform's root variable, upper cased by tf_inputs.py"
        assert entry["consumer"] == "terraform" and entry["terraform_managed"] is True
        assert "staging" not in entry and "check" not in entry and "github_repo_secrets" not in entry
        for environment in ("dev", "prod"):
            homes = og.Engine(Fake(Store()), [entry]).homes(client, environment)
            assert homes.source == (OPS, f"OIDC_{upper}_{environment.upper()}_SOURCE")
            assert homes.pending == (f"{HUB}:{environment}", f"KDF_OIDC_PENDING_SECRET_{upper}")
            assert homes.active == (f"{TF}:{environment}", entry["name"])
            assert homes.evidence["registered"]["job"] == f"Register the pending secret of {client} ({environment})"
            assert homes.evidence["deployed"]["repo"] == f"Needless2Say/{frontends[client]}"
        assert entry[
            "evidence"
        ]["applied"]["jobs"] == {"dev": "Terraform apply (dev)", "prod": "Terraform deploy (prod)"}


def test_the_engine_refuses_every_write_of_the_kind_and_names_its_one_writer() -> None:
    for entry in kind_entries():
        with pytest.raises(SystemExit, match = "oidc_generations.py alone"):
            rs._refuse_if_terraform_managed(entry)
        with pytest.raises(SystemExit, match = "oidc_generations.py alone"):
            rs.cmd_generate([entry], frozenset(), frozenset(), "gh", "master")
        with pytest.raises(SystemExit):
            rs.cmd_paste(entry, frozenset(), "gh", "master", "v")


def test_any_other_terraform_owned_entry_is_still_refused() -> None:
    with pytest.raises(SystemExit, match = "Terraform-managed"):
        rs._refuse_if_terraform_managed({"name": "X", "kind": "generate", "terraform_managed": True})

# ======================================================================================================================
# The workflow
# ======================================================================================================================

def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding = "utf-8"))


def flow_steps() -> list[dict[str, Any]]:
    return workflow()["jobs"]["flow"]["steps"]


def named(step_name: str) -> dict[str, Any]:
    return next(found for found in flow_steps() if found.get("name") == step_name)


def test_the_workflow_runs_in_ops_after_the_owner_check_in_one_group_that_never_cancels() -> None:
    data = workflow()
    assert list(data.get("on", data.get(True))) == ["workflow_dispatch"]
    assert data["concurrency"] == {"group": "oidc-client-secrets", "cancel-in-progress": False}
    assert data["permissions"] == {"contents": "read"}
    assert data["jobs"]["authorize"]["uses"] == "./.github/workflows/_authorize-owner.yml"
    flow = data["jobs"]["flow"]
    assert flow["environment"] == "ops" and flow["needs"] == "authorize"
    assert "github.triggering_actor == github.repository_owner" in flow["if"]


def test_the_flow_reads_each_source_only_when_its_client_and_environment_are_selected() -> None:
    env     = named("Run the flow")["env"]
    sources = {
        found["secret_name"]: (entry["client"], found["environment"])
        for entry in kind_entries()
        for found in entry["sources"]
    }
    assert {key for key in env if key.endswith("_SOURCE")} == set(sources)
    for name, (client, environment) in sources.items():
        value    = " ".join(str(env[name]).split())
        selected = f"inputs.client == '{client}' && inputs.environment == '{environment}'"
        assert value == f"${{{{ {selected} && secrets.{name} || '' }}}}", name


def test_no_run_line_interpolates_an_input_and_the_status_holds_no_writer_or_source() -> None:
    for found in flow_steps():
        assert "${{" not in str(found.get("run", "")), found.get("name")
    status = named("Show the generations")
    assert set(status["env"]) == {"FACTS_GH_TOKEN"} and status["if"] == "inputs.mode == 'status'"
    assert named("Run the flow")["if"] == "inputs.mode != 'status'"


def test_the_writers_token_reaches_its_writes_alone_and_the_runs_token_reads_alone() -> None:
    writer = named("Mint GitHub App token")["with"]
    runs   = named("Mint GitHub App token (runs)")["with"]
    assert writer["repositories"] == "${{ steps.targets.outputs.repositories }}"
    assert {key: value for key, value in writer.items() if key.startswith("permission-")} == {
        "permission-secrets": "write",
        "permission-environments": "write",
    }
    assert runs["repositories"] == "${{ steps.runs.outputs.repositories }}"
    assert {
        key: value for key, value in runs.items() if key.startswith("permission-")
    } == {"permission-actions": "read"}
    text = WORKFLOW.read_text(encoding = "utf-8")
    assert 'scripts/token_repositories.py oidc --names="$CLIENT" >> "$GITHUB_OUTPUT"' in text
    assert 'scripts/token_repositories.py oidc-runs --names="$CLIENT" >> "$GITHUB_OUTPUT"' in text
