"""
The OIDC client secrets' generations (the secrets moves' step 3, ADR D-112).

A client's secret is made here once and carried to the hub and to terraform, each step recorded before the next. An
`engine_generated` entry of scripts/secret_registry.json names, for each environment, the value's three homes.

- source    a secret of cicd's `ops`, the one recoverable copy while its generation is open
- pending   a secret of the hub's environment, which the hub's oidc-clients.yml registers from
- active    terraform's environment secret, the root variable's name upper cased, which terraform's next apply sets

A generation moves through its steps in order, each a dispatch of oidc-client-secrets.yml by the owner.

- generate   makes the value and masks it, records it intended with its fingerprint, writes the source, then the
             pending copy
- register   checks the hub's run that registered the pending copy, named by the owner, and records it
- promote    writes the active copy from the source, once the pending copy is shown unchanged since its distribution
- finish     checks terraform's run that applied the active copy and the app's deploy run after it, both named by the
             owner, with the active copy shown unchanged since the promotion, deletes the pending copy and the source,
             and records the generation done
- recover    closes the open generation on purpose, for one of REASONS, records the recovery before deleting its
             pending copy and its source, and never touches the active copy
- status     prints every generation the record keeps, never a value

The value's fingerprint is recorded before the value is written anywhere, so a crash at any point resumes from the
record and the source. A source whose fingerprint matches was written and is never made again, a value is made again
only when none landed, and a source holding another value is refused until a recovery. The pending and active copies
are written from the source after its fingerprint is checked, so a write repeated after a lost answer carries the same
value. A secret's update time by GitHub's clock is recorded at each write, so a step that relies on a copy refuses one
another writer replaced. One generation of a client and environment is open at a time. No value reaches a variable, an
output, an artifact or the log, and a value this flow made is masked before any use, since it is no registered secret.

The record is the cicd `ops` environment variable OIDC_SECRET_RECORD, through token_generations.py's GitHub seam. The
workflow's one concurrency group serializes every step.

Environment variables
    GH_TOKEN                   writes and deletes the homes' secrets, generate, promote, finish and recover
    FACTS_GH_TOKEN             reads and writes the record, every step but status
    RUNS_GH_TOKEN              reads the named runs, register and finish
    OIDC_SECRET_RECORD         the record as the job's vars context gives it, for status, which needs no token
    OIDC_<CLIENT>_<ENV>_SOURCE the selected source as the job's secrets context gives it, generate and promote

Usage, in Actions alone
    python scripts/oidc_generations.py --mode status
    python scripts/oidc_generations.py --mode generate --client fitness --environment dev
    python scripts/oidc_generations.py --mode register --client fitness --environment dev --registered-run 123
    python scripts/oidc_generations.py --mode promote --client fitness --environment dev
    python scripts/oidc_generations.py --mode finish --client fitness --environment dev --applied-run 124 \
        --deployed-run 125
    python scripts/oidc_generations.py --mode recover --client fitness --environment dev --generation O1 \
        --reason hub-refused
"""

from __future__ import annotations

# standard imports
import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

# third party imports
# local imports, found beside this script as Python puts its folder first
import rotate_secret as rs
import token_generations as tg

# ======================================================================================================================
# Configuration
# ======================================================================================================================

KIND            = "engine_generated"
CICD_REPO       = tg.CICD_REPO
OPS_TARGET      = f"{CICD_REPO}:{rs.OPS_ENVIRONMENT}"
RECORD_VARIABLE = "OIDC_SECRET_RECORD"
REGISTRY_FILE   = Path(__file__).resolve().parent / "secret_registry.json"
ENVIRONMENTS    = ("dev", "prod")
EVIDENCE        = ("registered", "applied", "deployed")

# the record keeps every open generation and this many closed ones
KEEP_CLOSED = 12

PHASES        = ("intended", "generated", "distributed", "registered", "promoted", "done", "abandoned")
OPEN          = PHASES[:5]
STAMP         = "%Y-%m-%dT%H:%M:%SZ"
GENERATION_ID = re.compile(r"O([1-9][0-9]*)")
RUN_ID        = re.compile(r"[1-9][0-9]{0,19}")
VALUE         = re.compile(r"[0-9a-f]{64}")
FINGERPRINT   = re.compile(r"[0-9a-f]{16}")
CLIENT        = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
MODES         = ("status", "generate", "register", "promote", "finish", "recover")
# a recovery's reason is one of these, never free text, since a dispatch's inputs show on this public repository's runs
# and the reason is kept in the record
REASONS = ("hub-refused", "apply-failed", "deploy-failed", "exposed", "abandoned")

# the tokens each step needs, the writer for the homes, the facts token for the record and the reader for the runs
TOKENS = {
    "generate": ("GH_TOKEN", "FACTS_GH_TOKEN"),
    "register": ("FACTS_GH_TOKEN", "RUNS_GH_TOKEN"),
    "promote": ("GH_TOKEN", "FACTS_GH_TOKEN"),
    "finish": ("GH_TOKEN", "FACTS_GH_TOKEN", "RUNS_GH_TOKEN"),
    "recover": ("GH_TOKEN", "FACTS_GH_TOKEN"),
}


class RecordError(RuntimeError):
    """
    The record could not be read or is out of its shape, so the run stops.
    """


class Refused(RuntimeError):
    """
    A step refused to act, its reason in the message.
    """

# ======================================================================================================================
# The provider
# ======================================================================================================================

class GitHub(Protocol):
    """
    What the flow asks of GitHub, each environment named owner/repo:environment.
    """
    def write_secret(self, target: str, name: str, value: str) -> None:
        """
        Write an environment secret.

        Args:
            target: owner/repo:environment
            name: the secret's name
            value: its value
        """


    def secret_updated_at(self, target: str, name: str) -> str | None:
        """
        When an environment secret was last written, by GitHub's clock.

        Args:
            target: owner/repo:environment
            name: the secret's name

        Returns:
            str | None: the time, None when it is not set
        """


    def delete_secret(self, target: str, name: str) -> None:
        """
        Delete an environment secret, one already gone counting as deleted.

        Args:
            target: owner/repo:environment
            name: the secret's name
        """


    def read_record(self) -> str | None:
        """
        The record as cicd's ops holds it.

        Returns:
            str | None: its text, None before the first save
        """


    def write_record(self, text: str) -> None:
        """
        Save the record in cicd's ops.

        Args:
            text: its text
        """


    def run(self, repo: str, run_id: str) -> dict[str, Any] | None:
        """
        A workflow run.

        Args:
            repo: owner/repo
            run_id: its id

        Returns:
            dict[str, Any] | None: GitHub's run, None when there is none of that id
        """


    def jobs(self, repo: str, run_id: str) -> list[dict[str, Any]]:
        """
        A run's latest jobs.

        Args:
            repo: owner/repo
            run_id: its id

        Returns:
            list[dict[str, Any]]: GitHub's jobs
        """


class LiveGitHub(tg.LiveGitHub):
    """
    token_generations.py's GitHub seam, its record this flow's own, and the runs read through a token that reads alone.
    """
    def __init__(self, gh_token: str, facts_token: str, runs_token: str) -> None:
        """
        Args:
            gh_token: writes and deletes the homes' secrets
            facts_token: reads and writes cicd's record
            runs_token: reads the named runs
        """
        super().__init__(gh_token, facts_token)
        self.runs_token = runs_token


    def read_record(self) -> str | None:
        """
        The record as cicd's ops holds it.

        Returns:
            str | None: its text, None before the first save
        """
        resp = rs._SESSION.get(
            f"{self._env_variable_url(CICD_REPO, rs.OPS_ENVIRONMENT)}/{RECORD_VARIABLE}",
            headers = rs._github_headers(self.facts_token),
            timeout = 30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()["value"]


    def write_record(self, text: str) -> None:
        """
        Save the record in cicd's ops.

        Args:
            text: its text
        """
        self._set_env_variable(self.facts_token, CICD_REPO, rs.OPS_ENVIRONMENT, RECORD_VARIABLE, text)


    def secret_updated_at(self, target: str, name: str) -> str | None:
        """
        When an environment secret was last written, from GitHub's metadata, never its value.

        Args:
            target: owner/repo:environment
            name: the secret's name

        Returns:
            str | None: the time, None when it is not set
        """
        repo, environment = target.rsplit(":", 1)
        return rs.github_env_secret_updated_at(self.gh_token, repo, environment, name)


    def delete_secret(self, target: str, name: str) -> None:
        """
        Delete an environment secret, one already gone counting as deleted.

        Args:
            target: owner/repo:environment
            name: the secret's name
        """
        repo, environment = target.rsplit(":", 1)
        rs.delete_github_env_secret(self.gh_token, repo, environment, name)


    def run(self, repo: str, run_id: str) -> dict[str, Any] | None:
        """
        A workflow run.

        Args:
            repo: owner/repo
            run_id: its id, digits alone

        Returns:
            dict[str, Any] | None: GitHub's run, None when there is none of that id
        """
        resp = rs._SESSION.get(
            f"{rs.GITHUB_API}/repos/{repo}/actions/runs/{run_id}",
            headers = rs._github_headers(self.runs_token),
            timeout = 30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


    def jobs(self, repo: str, run_id: str) -> list[dict[str, Any]]:
        """
        A run's latest jobs, the first hundred, more than any workflow here runs.

        Args:
            repo: owner/repo
            run_id: its id, digits alone

        Returns:
            list[dict[str, Any]]: GitHub's jobs
        """
        resp = rs._SESSION.get(
            f"{rs.GITHUB_API}/repos/{repo}/actions/runs/{run_id}/jobs",
            headers = rs._github_headers(self.runs_token),
            params = {"filter": "latest", "per_page": 100},
            timeout = 30,
        )
        resp.raise_for_status()
        return resp.json().get("jobs", [])

# ======================================================================================================================
# The flow
# ======================================================================================================================

@dataclass(frozen = True)
class Homes:
    """
    A client's homes in one environment, each a target and a secret's name, and the evidence each outside step needs.
    """
    source:   tuple[str, str]
    pending:  tuple[str, str]
    active:   tuple[str, str]
    evidence: dict[str, dict[str, Any]]


def fingerprint(value: str) -> str:
    """
    The first 16 hexadecimal digits of a value's SHA256, nothing secret.

    Args:
        value: the value

    Returns:
        str: its fingerprint
    """
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _parse(text: str) -> datetime:
    """
    A time as GitHub and the record write it.

    Args:
        text: the time

    Returns:
        datetime: it, in UTC

    Raises:
        Refused: when it is no such time
    """
    try:
        return datetime.strptime(str(text), STAMP).replace(tzinfo = UTC)
    except ValueError as exc:
        raise Refused(f"{text!r} is no time GitHub writes") from exc


def _one(entry: dict[str, Any], key: str, environment: str) -> dict[str, Any]:
    """
    An entry's one target of a kind in an environment.

    Args:
        entry: the registry entry
        key: the kind of target, sources, pending_github_env_secrets or github_env_secrets
        environment: the environment

    Returns:
        dict[str, Any]: the target

    Raises:
        Refused: when the entry names none or more than one
    """
    found = [target for target in entry.get(key, []) if target.get("environment") == environment]
    if len(found) != 1:
        raise Refused(f"{entry['name']} names {len(found)} {key} in {environment}, not one")
    return found[0]


def parse_record(text: str | None) -> dict[str, Any]:
    """
    The record from its text, an empty one before the first save, refused out of its shape. Public, so another reader
    of OIDC_SECRET_RECORD, the terraform rotation's among them, takes the same refusals. A generation is open while its
    phase is in OPEN, whatever its recovery holds.

    Args:
        text: the record's text, None before the first save

    Returns:
        dict[str, Any]: the record

    Raises:
        RecordError: when it is no JSON or out of its shape
    """
    if text is None:
        return {"version": 1, "next": 1, "generations": []}
    try:
        record = json.loads(text)
    except ValueError as exc:
        raise RecordError("the record is no JSON") from exc
    shaped = (
        isinstance(record, dict)
        and record.get("version") == 1
        and type(record.get("next")) is int
        and record["next"] >= 1
        and isinstance(record.get("generations"), list)
    )
    if not shaped:
        raise RecordError("the record is out of its shape")
    numbers = []
    for generation in record["generations"]:
        number = GENERATION_ID.fullmatch(str(generation.get("id"))) if isinstance(generation, dict) else None
        whole  = (
            number is not None
            and generation.get("phase") in PHASES
            and CLIENT.fullmatch(str(generation.get("client")))
            and generation.get("environment") in ENVIRONMENTS
            and (generation.get("fingerprint") is None or FINGERPRINT.fullmatch(str(generation["fingerprint"])))
            and isinstance(generation.get("at"), dict)
            and isinstance(generation.get("runs"), dict)
        )
        if not whole:
            raise RecordError(f"the record's generation {str(generation)[:40]!r} is out of its shape")
        numbers.append(int(number.group(1)))
    if len(set(numbers)) != len(numbers) or record["next"] <= max(numbers, default = 0):
        raise RecordError("the record's generation ids repeat or reach its next id")
    return record


def _unrecovered(generation: dict[str, Any]) -> None:
    """
    Refuse a step on a generation whose recovery has begun, which only a recovery finishes.

    Args:
        generation: the generation

    Raises:
        Refused: when its recovery has begun
    """
    if generation.get("recovery"):
        raise Refused(f"{generation['id']}'s recovery has begun, so dispatch recover for it again")


def _mask_in_log(value: str) -> None:
    """
    Mask a value in the job's log before any use, the runner taking the line as its command.

    Args:
        value: the value
    """
    print(f"::add-mask::{value}", flush = True)


class Engine:
    """
    The steps of a generation over GitHub, each loading the record when it starts.
    """
    def __init__(
        self,
        github: GitHub,
        entries: list[dict[str, Any]],
        *,
        now: Callable[[], datetime] | None = None,
        run_id: str = "",
        mask: Callable[[str], None] = _mask_in_log,
        out: Callable[[str], None] = print,
    ) -> None:
        """
        Args:
            github: GitHub
            entries: the registry's entries, those of the engine generated kind kept
            now: the clock
            run_id: this run's id, recorded with each phase it moves
            mask: masks a value in the log
            out: prints a line
        """
        self.github  = github
        self.entries = [entry for entry in entries if entry.get("kind") == KIND]
        self.now     = now or (lambda: datetime.now(UTC))
        self.run_id  = run_id
        self.mask    = mask
        self.out     = out


    def homes(self, client: str, environment: str) -> Homes:
        """
        A client's homes in one environment, as its entry names them.

        Args:
            client: the client, as its entry names it
            environment: dev or prod

        Returns:
            Homes: its homes

        Raises:
            Refused: when the registry holds no such client or environment, or names a home twice
        """
        entry = next((entry for entry in self.entries if entry.get("client") == client), None)
        if environment not in ENVIRONMENTS or entry is None:
            raise Refused(f"the registry holds no engine generated client {client!r} in {environment!r}")
        source   = _one(entry, "sources", environment)
        pending  = _one(entry, "pending_github_env_secrets", environment)
        active   = _one(entry, "github_env_secrets", environment)
        evidence = {
            phase: {
                "repo": entry["evidence"][phase]["repo"],
                "workflows": entry["evidence"][phase]["workflows"],
                "job": entry["evidence"][phase]["jobs"][environment],
            }
            for phase in EVIDENCE
        }
        return Homes(
            source = (OPS_TARGET, source["secret_name"]),
            pending = (f"{pending['repo']}:{environment}", pending["secret_name"]),
            active = (f"{active['repo']}:{environment}", active["secret_name"]),
            evidence = evidence,
        )

    # =================================================== The record ===================================================

    def _load(self) -> dict[str, Any]:
        """
        The record, an empty one before the first save.

        Returns:
            dict[str, Any]: the record

        Raises:
            RecordError: when it is no JSON or out of its shape
        """
        return parse_record(self.github.read_record())


    def _save(self, record: dict[str, Any]) -> None:
        """
        Save the record, every open generation kept and the last ones to close.

        Args:
            record: the record
        """
        closed = sorted(
            (generation for generation in record["generations"] if generation["phase"] not in OPEN),
            key = lambda generation: (generation["at"].get(generation["phase"], ""), int(generation["id"][1:])),
        )
        keep   = {generation["id"] for generation in closed[-KEEP_CLOSED:]}
        record["generations"] = [
            generation
            for generation in record["generations"]
            if generation["phase"] in OPEN or generation["id"] in keep
        ]
        self.github.write_record(json.dumps(record, sort_keys = True, separators = (",", ":")))


    def _open(self, record: dict[str, Any], client: str, environment: str) -> dict[str, Any] | None:
        """
        The open generation of a client and environment.

        Args:
            record: the record
            client: the client
            environment: the environment

        Returns:
            dict[str, Any] | None: the generation, None when none is open

        Raises:
            RecordError: when more than one is open
        """
        found = [
            generation
            for generation in record["generations"]
            if generation["client"] == client
            and generation["environment"] == environment
            and generation["phase"] in OPEN
        ]
        if len(found) > 1:
            raise RecordError(f"{len(found)} generations of {client} in {environment} are open")
        return found[0] if found else None


    def _at(self, record: dict[str, Any], client: str, environment: str, phase: str) -> dict[str, Any]:
        """
        The open generation of a client and environment, refused unless it is at *phase*.

        Args:
            record: the record
            client: the client
            environment: the environment
            phase: the phase this step starts from

        Returns:
            dict[str, Any]: the generation

        Raises:
            Refused: when none is open, or it is at another phase
        """
        generation = self._open(record, client, environment)
        if generation is None:
            raise Refused(f"no generation of {client} in {environment} is open")
        _unrecovered(generation)
        if generation["phase"] != phase:
            held = f"{generation['id']} of {client} in {environment} is {generation['phase']}"
            raise Refused(f"{held}, and this step needs it {phase}")
        return generation


    def _move(self, record: dict[str, Any], generation: dict[str, Any], phase: str, when: str, run: str = "") -> None:
        """
        Move a generation to its next phase and save the record.

        Args:
            record: the record
            generation: the generation
            phase: its new phase
            when: the time, by GitHub's clock where a write or a run gives it
            run: the run that moved it, this run when empty
        """
        generation["phase"] = phase
        generation["at"][phase] = when
        generation["runs"][phase] = int(run or self.run_id or 0)
        self._save(record)


    def _stamp(self) -> str:
        """
        Now, as the record writes a time.

        Returns:
            str: the time
        """
        return self.now().strftime(STAMP)

    # =================================================== The values ===================================================

    def _make(self, record: dict[str, Any], generation: dict[str, Any], homes: Homes) -> str:
        """
        Make a value, mask it, record its fingerprint, then write the source.

        Args:
            record: the record
            generation: the intended generation
            homes: its homes

        Returns:
            str: the value
        """
        value = secrets.token_hex(32)
        self.mask(value)
        generation["fingerprint"] = fingerprint(value)
        generation["at"]["intended"] = self._stamp()
        generation["runs"]["intended"] = int(self.run_id or 0)
        self._save(record)
        self.github.write_secret(*homes.source, value)
        return value


    def _check(self, generation: dict[str, Any], given: str) -> str:
        """
        The source, refused unless it is the generation's value, masked before any use.

        Args:
            generation: the generation
            given: the source as the job's secrets context gives it

        Returns:
            str: the value

        Raises:
            Refused: when its fingerprint is not the generation's
        """
        if not (VALUE.fullmatch(given or "") and fingerprint(given) == generation["fingerprint"]):
            raise Refused(f"the source is not {generation['id']}'s value, its fingerprint differs")
        self.mask(given)
        return given


    def _written(self, home: tuple[str, str]) -> str:
        """
        When a home's secret was written, by GitHub's clock.

        Args:
            home: the target and the secret's name

        Returns:
            str: the time

        Raises:
            Refused: when GitHub shows it unset after its write
        """
        landed = self.github.secret_updated_at(*home)
        if landed is None:
            raise Refused(f"{home[1]} in {home[0]} shows unset after its write, dispatch the step again")
        return landed


    def _unchanged(self, home: tuple[str, str], written: str) -> None:
        """
        Refuse unless a home's secret is still the step's own write, its update time by GitHub's clock the one recorded
        when it was written, so no other writer has replaced it since.

        Args:
            home: the target and the secret's name
            written: the time recorded at its write

        Raises:
            Refused: when it was written again since, or is gone
        """
        landed = self.github.secret_updated_at(*home)
        if landed != written:
            raise Refused(f"{home[1]} in {home[0]} was written at {landed}, not at {written} as recorded, so recover")

    # ================================================== The evidence ==================================================

    def _evidence(self, spec: dict[str, Any], run_id: str, after: str) -> dict[str, Any]:
        """
        A run the owner named, refused unless it is the evidence the step needs.

        It must be a run of the spec's repository and of one of its workflows, on main, completed with success,
        created after *after*, holding the spec's job, the workflow's own or a caller's, every such job a success.

        Args:
            spec: the repository, the workflows and the job
            run_id: the run's id
            after: the time it must be created after

        Returns:
            dict[str, Any]: the run

        Raises:
            Refused: when it is not
        """
        if not RUN_ID.fullmatch(run_id or ""):
            raise Refused(f"{run_id!r} is no run id")
        run = self.github.run(spec["repo"], run_id)
        if run is None:
            raise Refused(f"{spec['repo']} has no run {run_id}")
        wrong = []
        if (run.get("repository") or {}).get("full_name") != spec["repo"]:
            wrong.append("of another repository")
        if run.get("path") not in spec["workflows"]:
            wrong.append(f"of the workflow {run.get('path')!r}")
        if run.get("head_branch") != "main":
            wrong.append(f"on the branch {run.get('head_branch')!r}")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            wrong.append(f"{run.get('status')} with {run.get('conclusion')}")
        # strictly later, since a run created in the same second may have started before the time it must follow
        if _parse(run.get("created_at", "")) <= _parse(after):
            wrong.append(f"created at {run.get('created_at')!r}, not after {after}")
        jobs = [
            job
            for job in self.github.jobs(spec["repo"], run_id)
            if job.get("name") == spec["job"] or str(job.get("name", "")).endswith(f" / {spec['job']}")
        ]
        if not jobs or any(job.get("conclusion") != "success" for job in jobs):
            wrong.append(f"with no job {spec['job']!r} that succeeded")
        if wrong:
            raise Refused(f"run {run_id} of {spec['repo']} is not the evidence, it is {', '.join(wrong)}")
        # its end, by GitHub's clock, is what a later step's evidence must follow
        _parse(run.get("updated_at", ""))
        return run

    # =================================================== The steps ====================================================

    def generate(self, client: str, environment: str, given: str) -> None:
        """
        Make the value and write the source, then the pending copy, resuming an intended or generated generation.

        Args:
            client: the client
            environment: the environment
            given: the source as the job's secrets context gives it, empty when it is not set

        Raises:
            Refused: when another generation of the client and environment is open past its source or recovering, or
                the source holds a value that is not the intended generation's
        """
        homes      = self.homes(client, environment)
        record     = self._load()
        generation = self._open(record, client, environment)
        if generation is not None:
            _unrecovered(generation)
        if generation is not None and generation["phase"] not in ("intended", "generated"):
            held = f"{generation['id']} of {client} in {environment} is open, {generation['phase']}"
            raise Refused(f"{held}, so finish or recover it first")
        if generation is None:
            generation = {
                "id": f"O{record['next']}",
                "client": client,
                "environment": environment,
                "phase": "intended",
                "fingerprint": None,
                "at": {},
                "runs": {},
                "recovery": None,
            }
            record["next"] += 1
            record["generations"].append(generation)
        if generation["phase"] == "intended":
            if given and generation["fingerprint"] and fingerprint(given) == generation["fingerprint"]:
                # the source landed before the answer was lost, so its value is this generation's
                self.mask(given)
                value = given
            elif given and generation["fingerprint"]:
                # a value this generation never made, which only a recovery clears
                raise Refused(f"the source holds a value that is not {generation['id']}'s, so recover it")
            else:
                value = self._make(record, generation, homes)
            self._move(record, generation, "generated", self._written(homes.source))
        else:
            value = self._check(generation, given)
        self.github.write_secret(*homes.pending, value)
        self._move(record, generation, "distributed", self._written(homes.pending))
        self.out(
            f"{generation['id']} of {client} in {environment} distributed, fingerprint {generation['fingerprint']}",
        )


    def register(self, client: str, environment: str, run_id: str) -> None:
        """
        Record the hub's run that registered the pending copy.

        Args:
            client: the client
            environment: the environment
            run_id: the hub's run
        """
        homes      = self.homes(client, environment)
        record     = self._load()
        generation = self._at(record, client, environment, "distributed")
        run        = self._evidence(homes.evidence["registered"], run_id, generation["at"]["distributed"])
        self._move(record, generation, "registered", run["updated_at"], run_id)
        self.out(f"{generation['id']} of {client} in {environment} registered by the hub's run {run_id}")


    def promote(self, client: str, environment: str, given: str) -> None:
        """
        Write the active copy from the source, once the pending copy is shown unchanged since its distribution, so the
        hub's run, created after it, registered this generation's value.

        Args:
            client: the client
            environment: the environment
            given: the source as the job's secrets context gives it
        """
        homes      = self.homes(client, environment)
        record     = self._load()
        generation = self._at(record, client, environment, "registered")
        value      = self._check(generation, given)
        self._unchanged(homes.pending, generation["at"]["distributed"])
        self.github.write_secret(*homes.active, value)
        self._move(record, generation, "promoted", self._written(homes.active))
        promoted = f"{generation['id']} of {client} in {environment} promoted to {homes.active[1]}"
        self.out(f"{promoted}, terraform's apply and the app's deploy next")


    def finish(self, client: str, environment: str, applied_run: str, deployed_run: str) -> None:
        """
        Check terraform's apply after the promotion and the app's deploy after it, with the active copy shown unchanged
        since the promotion, so the apply set this generation's value, then delete the pending copy and the source,
        and record the generation done.

        Args:
            client: the client
            environment: the environment
            applied_run: terraform's run
            deployed_run: the app's deploy run
        """
        homes      = self.homes(client, environment)
        record     = self._load()
        generation = self._at(record, client, environment, "promoted")
        applied    = self._evidence(homes.evidence["applied"], applied_run, generation["at"]["promoted"])
        deployed   = self._evidence(homes.evidence["deployed"], deployed_run, applied["updated_at"])
        self._unchanged(homes.active, generation["at"]["promoted"])
        self.github.delete_secret(*homes.pending)
        self.github.delete_secret(*homes.source)
        generation["at"]["applied"] = applied["updated_at"]
        generation["at"]["deployed"] = deployed["updated_at"]
        generation["runs"]["applied"] = int(applied_run)
        generation["runs"]["deployed"] = int(deployed_run)
        self._move(record, generation, "done", self._stamp())
        self.out(f"{generation['id']} of {client} in {environment} done")


    def recover(self, client: str, environment: str, generation_id: str, reason: str) -> None:
        """
        Close the open generation on purpose, deleting its pending copy and its source, never the active copy. The
        recovery is recorded before the first delete, so no other step resumes the generation once it has begun, and a
        recovery dispatched again finishes it.

        Args:
            client: the client
            environment: the environment
            generation_id: the open generation, named so the owner closes the one they read
            reason: one of REASONS, kept in the record

        Raises:
            Refused: when the reason is none of REASONS, or the generation is not the open one
        """
        if reason not in REASONS:
            raise Refused(f"a reason is one of {', '.join(REASONS)}")
        homes      = self.homes(client, environment)
        record     = self._load()
        generation = self._open(record, client, environment)
        if generation is None:
            raise Refused(f"no generation of {client} in {environment} is open")
        if not GENERATION_ID.fullmatch(generation_id or "") or generation["id"] != generation_id:
            raise Refused(f"{generation_id!r} is not the open generation of {client} in {environment}")
        if not generation.get("recovery"):
            generation["recovery"] = {"at": self._stamp(), "run": int(self.run_id or 0), "reason": reason}
            self._save(record)
        self.github.delete_secret(*homes.pending)
        self.github.delete_secret(*homes.source)
        self._move(record, generation, "abandoned", self._stamp())
        self.out(f"{generation['id']} of {client} in {environment} abandoned, {homes.active[1]} untouched")


    def status(self) -> None:
        """
        Print every generation the record keeps, never a value.
        """
        generations = self._load()["generations"]
        if not generations:
            self.out("No generation is recorded.")
        for generation in generations:
            named = f"{generation['id']} {generation['client']} {generation['environment']} {generation['phase']}"
            self.out(f"{named} fingerprint {generation.get('fingerprint')}")

# ======================================================================================================================
# The command
# ======================================================================================================================

class HeldRecord:
    """
    The record as the job's vars context gives it, for the status, which reads it alone.
    """
    def __init__(self, text: str) -> None:
        """
        Args:
            text: the record, empty before the first save
        """
        self.text = text


    def read_record(self) -> str | None:
        """
        The record.

        Returns:
            str | None: its text, None before the first save
        """
        return self.text or None


def registry_entries() -> list[dict[str, Any]]:
    """
    The registry's engine generated entries.

    Returns:
        list[dict[str, Any]]: the entries
    """
    registry = json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))
    return [entry for entry in registry["secrets"] if entry.get("kind") == KIND]


def main(argv: list[str] | None = None) -> int:
    """
    Run one step, in Actions alone.

    Args:
        argv: the arguments, sys.argv's by default

    Returns:
        int: 0 when the step acted, 1 when it refused or a token is missing
    """
    parser = argparse.ArgumentParser(description = "The OIDC client secrets' generations (D-112).")
    parser.add_argument("--mode", required = True, choices = MODES)
    parser.add_argument("--client", default = "")
    parser.add_argument("--environment", default = "")
    parser.add_argument("--registered-run", default = "")
    parser.add_argument("--applied-run", default = "")
    parser.add_argument("--deployed-run", default = "")
    parser.add_argument("--generation", default = "")
    parser.add_argument("--reason", default = "")
    args = parser.parse_args(argv)

    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("Error: oidc_generations.py runs in Actions alone, through oidc-client-secrets.yml", file = sys.stderr)
        return 1
    if args.mode == "status":
        # the record as the job's vars context gives it, read with no token
        try:
            Engine(HeldRecord(os.environ.get(RECORD_VARIABLE, "")), registry_entries()).status()
        except RecordError as exc:
            print(f"Error: {exc}", file = sys.stderr)
            return 1
        return 0
    tokens  = {name: os.environ.get(name, "").strip() for name in ("GH_TOKEN", "FACTS_GH_TOKEN", "RUNS_GH_TOKEN")}
    missing = sorted(name for name in TOKENS[args.mode] if not tokens[name])
    if missing:
        print(f"Error: {', '.join(missing)} not set", file = sys.stderr)
        return 1

    engine = Engine(
        LiveGitHub(tokens["GH_TOKEN"], tokens["FACTS_GH_TOKEN"], tokens["RUNS_GH_TOKEN"]),
        registry_entries(),
        run_id = os.environ.get("GITHUB_RUN_ID", ""),
    )
    try:
        homes = engine.homes(args.client, args.environment)
        # the source reaches the steps that write from it alone
        given = os.environ.get(homes.source[1], "") if args.mode in ("generate", "promote") else ""
        if args.mode == "generate":
            engine.generate(args.client, args.environment, given)
        elif args.mode == "register":
            engine.register(args.client, args.environment, args.registered_run)
        elif args.mode == "promote":
            engine.promote(args.client, args.environment, given)
        elif args.mode == "finish":
            engine.finish(args.client, args.environment, args.applied_run, args.deployed_run)
        else:
            engine.recover(args.client, args.environment, args.generation, args.reason)
    except (Refused, RecordError) as exc:
        print(f"Error: {exc}", file = sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
