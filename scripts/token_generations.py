"""
The shared Vercel deployment token's generations (the secrets fence, step 10, design 5.5, ADR D-100).

Each rotation is a generation, recorded in cicd's `ops` before any target is written, so a reap acts on the record
alone and never on a name or a creation time. The token lives in each consumer's `dev` and `prod`, with a variable
`VERCEL_TOKEN_GENERATION` beside it, the generation's id and the first 16 hexadecimal digits of the SHA256 of the
trimmed token, nothing secret, which each deploy compares with its own token and prints yes or no.

- rotate               lists the tokens of the name, mints one, records the generation pending with every older token
                       as its predecessor, then writes each target's secret and variable, saving each as it lands. A
                       failed save stops the run. Every target written makes the generation complete.
- reap                 revokes every predecessor of the newest generation, only once it is complete and its last write
                       is six hours old, GitHub's limit on a hosted job, and records each revocation.
- revoke-now           the emergency, revokes the newest generation's predecessors at once despite any failed target,
                       and names the targets to repair.
- retire-repo-copies   deletes the repository copies, only for the newest complete generation, with the owner's list
                       of every target verified equal to the generation's targets and to the registry's.
- due                  outside `ops` and holding no secret, reads the public facts and prints whether a rotation or a
                       reap is due, so the daily schedule asks no approval on a day with nothing to do.

The record is the cicd `ops` environment variable VERCEL_TOKEN_RECORD and the public facts the cicd repository
variable VERCEL_TOKEN_FACTS. Every entry point loads the record when it starts, after the workflow's one concurrency
group lets it run.

Environment variables
    GH_TOKEN              writes the targets' secrets and variables and deletes the repository copies
    FACTS_GH_TOKEN        reads and writes cicd's record and writes its facts
    VERCEL_MASTER_TOKEN   lists, mints and revokes the tokens
    VERCEL_TEAM_ID        the team a minted token belongs to

Usage
    python scripts/token_generations.py rotate
    python scripts/token_generations.py reap
    python scripts/token_generations.py revoke-now --generation G2
    python scripts/token_generations.py retire-repo-copies --generation G1 --verified kriegerdataforge:dev,...
    python scripts/token_generations.py due --facts "generation=G1 state=complete ..."
"""

from __future__ import annotations

# standard imports
import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

# third party imports
import requests
# local imports, found beside this script as Python puts its folder first
import rotate_secret as rs

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ENTRY_NAME          = "VERCEL_DEPLOYMENT_TOKEN"
CICD_REPO           = "Needless2Say/kriegerdataforge-cicd"
RECORD_VARIABLE     = "VERCEL_TOKEN_RECORD"
FACTS_VARIABLE      = "VERCEL_TOKEN_FACTS"
GENERATION_VARIABLE = "VERCEL_TOKEN_GENERATION"

# a reap waits this long after the generation's last write, GitHub's limit on a hosted job, so no deploy that started
# before it still holds a predecessor
REAP_DELAY = timedelta(hours = 6)

# the record keeps this many generations, every token they name and every token not yet revoked
KEEP_GENERATIONS = 12

GENERATION_ID = re.compile(r"G[1-9][0-9]*")
TARGET        = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:(dev|prod)")


class RecordError(RuntimeError):
    """
    The record could not be read or saved, so the run stops.
    """


class Refused(RuntimeError):
    """
    An entry point refused to act, its reason in the message.
    """

# ======================================================================================================================
# The providers
# ======================================================================================================================

class GitHub(Protocol):
    """
    What the engine asks of GitHub, each target named owner/repo:environment.
    """
    def write_secret(self, target: str, name: str, value: str) -> None:
        """
        Write a target's environment secret.

        Args:
            target: owner/repo:environment
            name: the secret's name
            value: the token
        """


    def write_variable(self, target: str, name: str, value: str) -> None:
        """
        Write a target's environment variable, nothing secret.

        Args:
            target: owner/repo:environment
            name: the variable's name
            value: its value
        """


    def delete_repo_secret(self, repo: str, name: str) -> None:
        """
        Delete a repository secret, one already gone counting as deleted.

        Args:
            repo: owner/repo
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


    def write_facts(self, text: str) -> None:
        """
        Write the public facts as a cicd repository variable.

        Args:
            text: the facts
        """


class Vercel(Protocol):
    """
    What the engine asks of Vercel's token API.
    """
    def names(self, name: str) -> list[str]:
        """
        The ids of every token of a name.

        Args:
            name: the tokens' name

        Returns:
            list[str]: their ids
        """


    def mint(self, name: str) -> tuple[str, str]:
        """
        Mint a token of a name.

        Args:
            name: its name

        Returns:
            tuple[str, str]: its id and its value
        """


    def revoke(self, token_id: str) -> None:
        """
        Revoke a token, one already gone counting as revoked.

        Args:
            token_id: its id
        """


class LiveGitHub:
    """
    GitHub's API, the targets through one token and cicd's record and facts through another.
    """
    def __init__(self, gh_token: str, facts_token: str) -> None:
        """
        Args:
            gh_token: writes the targets' secrets and variables and deletes the repository copies
            facts_token: reads and writes cicd's record and writes its facts
        """
        self.gh_token    = gh_token
        self.facts_token = facts_token


    def _env_variable_url(self, repo: str, environment: str) -> str:
        """
        An environment's variables endpoint.

        Args:
            repo: owner/repo
            environment: the environment

        Returns:
            str: the URL
        """
        return f"{rs.GITHUB_API}/repos/{repo}/environments/{environment}/variables"


    def _set_env_variable(self, token: str, repo: str, environment: str, name: str, value: str) -> None:
        """
        Update an environment variable, or create it when it does not exist yet.

        Args:
            token: a token that writes the environment
            repo: owner/repo
            environment: the environment
            name: the variable's name
            value: its value, never a secret

        Raises:
            RuntimeError: when GitHub refuses the write
        """
        base = self._env_variable_url(repo, environment)
        body = {"name": name, "value": value}
        resp = rs._SESSION.patch(f"{base}/{name}", headers = rs._github_headers(token), json = body, timeout = 30)
        if resp.status_code == 404:
            resp = rs._SESSION.post(base, headers = rs._github_headers(token), json = body, timeout = 30)
        if not resp.ok:
            raise RuntimeError(
                f"GitHub answered HTTP {resp.status_code} to the write of {name} in {repo} [{environment}]",
            )


    def write_secret(self, target: str, name: str, value: str) -> None:
        """
        Write a target's environment secret.

        Args:
            target: owner/repo:environment
            name: the secret's name
            value: the token
        """
        repo, environment = target.rsplit(":", 1)
        rs.update_github_env_secret(self.gh_token, repo, environment, name, value)


    def write_variable(self, target: str, name: str, value: str) -> None:
        """
        Write a target's environment variable, nothing secret.

        Args:
            target: owner/repo:environment
            name: the variable's name
            value: its value
        """
        repo, environment = target.rsplit(":", 1)
        self._set_env_variable(self.gh_token, repo, environment, name, value)


    def delete_repo_secret(self, repo: str, name: str) -> None:
        """
        Delete a repository secret, one already gone counting as deleted.

        Args:
            repo: owner/repo
            name: the secret's name
        """
        resp = rs._SESSION.delete(
            f"{rs.GITHUB_API}/repos/{repo}/actions/secrets/{name}",
            headers = rs._github_headers(self.gh_token),
            timeout = 30,
        )
        if resp.status_code != 404:
            resp.raise_for_status()


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


    def write_facts(self, text: str) -> None:
        """
        Write the public facts as a cicd repository variable.

        Args:
            text: the facts
        """
        rs.set_repo_variable(self.facts_token, CICD_REPO, FACTS_VARIABLE, text)


class LiveVercel:
    """
    Vercel's token API through the master token.
    """
    def __init__(self, master_token: str, team_id: str) -> None:
        """
        Args:
            master_token: lists, mints and revokes the tokens
            team_id: the team a minted token belongs to
        """
        self.master_token = master_token
        self.team_id      = team_id


    def names(self, name: str) -> list[str]:
        """
        The ids of every token of a name.

        Args:
            name: the tokens' name

        Returns:
            list[str]: their ids
        """
        return [token["id"] for token in rs.list_vercel_tokens(self.master_token) if token.get("name") == name]


    def mint(self, name: str) -> tuple[str, str]:
        """
        Mint a token of a name, for TOKEN_EXPIRY_DAYS.

        Args:
            name: its name

        Returns:
            tuple[str, str]: its id and its value
        """
        return rs.create_vercel_token(self.master_token, name, self.team_id)


    def revoke(self, token_id: str) -> None:
        """
        Revoke a token, one already gone counting as revoked.

        Args:
            token_id: its id
        """
        try:
            rs.delete_vercel_token(self.master_token, token_id)
        except requests.HTTPError as exc:
            # a token already gone is revoked
            if exc.response is None or exc.response.status_code != 404:
                raise

# ======================================================================================================================
# The record and the facts
# ======================================================================================================================

def fingerprint(value: str) -> str:
    """
    The first 16 hexadecimal digits of the SHA256 of the trimmed token, nothing secret.

    Args:
        value: the token

    Returns:
        str: its fingerprint
    """
    return hashlib.sha256(value.strip().encode()).hexdigest()[:16]


def _iso(moment: datetime) -> str:
    """
    A time as the record writes it.

    Args:
        moment: the time

    Returns:
        str: its ISO form
    """
    return moment.isoformat()


def _parse_time(raw: object) -> datetime | None:
    """
    A time from the record or the facts, None when it is no time with a zone.

    Args:
        raw: the text

    Returns:
        datetime | None: the time
    """
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _outstanding(record: dict, generation: str) -> list[str]:
    """
    Every token the record holds that the generation retires, not its own and not yet revoked.

    Args:
        record: the record
        generation: the generation's id

    Returns:
        list[str]: the tokens' ids, sorted
    """
    return sorted(
        token_id for token_id, token in record["tokens"].items()
        if token["generation"] != generation and token["revoked"] is None
    )


def facts_text(record: dict) -> str:
    """
    The public facts of the newest generation, nothing secret, as the due job reads them.

    Args:
        record: the record

    Returns:
        str: the facts, one line of key=value words
    """
    if not record["generations"]:
        return "generation=none"
    gen = record["generations"][-1]
    return " ".join([
        f"generation={gen['id']}",
        f"state={'complete' if gen['completed_at'] else 'pending'}",
        f"minted={gen['minted_at']}",
        f"completed={gen['completed_at'] or 'none'}",
        f"outstanding={len(_outstanding(record, gen['id']))}",
    ])


def parse_facts(text: str) -> dict[str, str]:
    """
    The facts' words.

    Args:
        text: the facts

    Returns:
        dict[str, str]: each key and its value
    """
    return dict(word.split("=", 1) for word in text.split() if "=" in word)


def due(text: str, now: datetime) -> str:
    """
    Whether a rotation or a reap is due, from the public facts alone.

    Nothing is due before the first generation, which the owner starts by dispatch as the token's move (the plan's
    step 11), so the armed schedule never moves the token on its own. Once one exists, a rotation is due when the
    newest is incomplete, a failed run tried again the next day, when it was minted before this month, the owner's
    rotation on the 1st, or when the facts cannot be read. A reap is due when the newest is complete, still retires a
    token, and its last write is six hours old.

    Args:
        text: the facts
        now: the time

    Returns:
        str: rotate, reap or none
    """
    facts = parse_facts(text or "")
    if facts.get("generation", "none") == "none":
        return "none"
    minted = _parse_time(facts.get("minted"))
    if not GENERATION_ID.fullmatch(facts.get("generation", "")) or minted is None:
        return "rotate"
    if facts.get("state") != "complete" or (minted.year, minted.month) != (now.year, now.month):
        return "rotate"
    completed = _parse_time(facts.get("completed"))
    if completed is None:
        return "rotate"
    if facts.get("outstanding", "0") != "0" and now - completed >= REAP_DELAY:
        return "reap"
    return "none"


def registry_targets(entry: dict) -> tuple[list[str], list[str]]:
    """
    The token's environment targets and its repository copies, from its registry entry.

    Args:
        entry: the registry's entry

    Returns:
        tuple[list[str], list[str]]: each target as owner/repo:environment, and each repository copy's repo
    """
    targets = sorted(f"{target['repo']}:{target['environment']}" for target in entry.get("github_env_secrets", []))
    copies  = sorted({target["repo"] for target in entry.get("retired_github_repo_secrets", [])})
    return targets, copies

# ======================================================================================================================
# The engine
# ======================================================================================================================

class Engine:
    """
    The generations of one shared token, over its providers and a clock.
    """
    def __init__(
        self,
        github: GitHub,
        vercel: Vercel,
        targets: list[str],
        repo_copies: list[str],
        secret_name: str,
        token_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """
        Args:
            github: the targets, the record and the facts
            vercel: the token API
            targets: each target, owner/repo:environment
            repo_copies: each repository copy's repo, retired once verified
            secret_name: the secret's name in each target
            token_name: the tokens' name at Vercel
            clock: the time, injected by the tests
        """
        self.github      = github
        self.vercel      = vercel
        self.targets     = sorted(targets)
        self.repo_copies = sorted(repo_copies)
        self.secret_name = secret_name
        self.token_name  = token_name
        self.clock       = clock
        self.failures: list[str] = []


    def load(self) -> dict:
        """
        The record as saved, an empty one before the first generation.

        Returns:
            dict: the record

        Raises:
            RecordError: when it cannot be read or parsed
        """
        try:
            text = self.github.read_record()
        except Exception as exc:  # noqa: BLE001
            raise RecordError(f"the record could not be read, {exc}") from exc
        if not text:
            return {"version": 1, "next": 1, "generations": [], "tokens": {}, "retired_repo_copies": {}}
        try:
            record = json.loads(text)
        except ValueError as exc:
            raise RecordError("the record is not JSON, so nothing is done") from exc
        if not isinstance(record, dict) or record.get("version") != 1:
            raise RecordError("the record has no version 1, so nothing is done")
        return record


    def save(self, record: dict) -> None:
        """
        Save the record, keeping its newest generations, every token they name, every token still valid, and every
        revocation of a token no generation held, the repository era's among them.

        Args:
            record: the record, trimmed in place

        Raises:
            RecordError: when GitHub refuses it, which stops the run
        """
        record["generations"] = record["generations"][-KEEP_GENERATIONS:]
        kept = {gen["id"] for gen in record["generations"]}
        record["tokens"] = {
            token_id: token for token_id, token in record["tokens"].items()
            if token["revoked"] is None or token["generation"] is None or token["generation"] in kept
        }
        try:
            self.github.write_record(json.dumps(record, sort_keys = True, separators = (",", ":")))
        except Exception as exc:  # noqa: BLE001
            raise RecordError(f"the record could not be saved, so the run stops, {exc}") from exc


    def publish(self, record: dict, errors: list[str]) -> None:
        """
        Write the public facts, a failure kept as an error since the record holds the truth.

        Args:
            record: the record
            errors: the run's errors, added to in place
        """
        try:
            self.github.write_facts(facts_text(record))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"the public facts could not be written, {exc}")


    def newest(self, record: dict, generation: str | None = None) -> dict:
        """
        The newest generation, the one named when one is.

        Args:
            record: the record
            generation: the id the caller named, None for any

        Returns:
            dict: the generation

        Raises:
            Refused: when there is none, or the one named is not the newest
        """
        if not record["generations"]:
            raise Refused("no generation is recorded yet")
        gen = record["generations"][-1]
        if generation is not None and gen["id"] != generation:
            raise Refused(f"{generation} is not the newest generation, {gen['id']} is")
        return gen


    def rotate(self) -> list[str]:
        """
        Mint a generation and write it to every target.

        Returns:
            list[str]: each failed target

        Raises:
            RecordError: when the record cannot be read or saved
        """
        record = self.load()
        before = self.vercel.names(self.token_name)
        token_id, value = self.vercel.mint(self.token_name)
        gen_id = f"G{record['next']}"
        now    = self.clock()
        for old in before:
            # a token of the name the record never held, the repository era's or a crashed mint's, is a predecessor
            record["tokens"].setdefault(old, {"generation": None, "revoked": None})
        record["tokens"][token_id] = {"generation": gen_id, "revoked": None}
        gen = {
            "id": gen_id,
            "token_id": token_id,
            "fingerprint": fingerprint(value),
            "minted_at": _iso(now),
            "targets": list(self.targets),
            "written": {},
            "completed_at": None,
        }
        record["generations"].append(gen)
        record["next"] += 1
        try:
            self.save(record)
        except RecordError:
            try:
                self.vercel.revoke(token_id)
            except Exception:  # noqa: BLE001
                pass  # a token the record never held is a predecessor of the next generation
            raise
        # The facts say pending before any write, so a run that stops part way is seen by the next day's due job and
        # tried again, never hidden behind an older complete generation's facts (Codex's review read, M).
        try:
            self.github.write_facts(facts_text(record))
        except Exception as exc:  # noqa: BLE001
            raise RecordError(
                f"the public facts could not say {gen_id} is pending, so no target is written, {exc}",
            ) from exc
        print(f"{gen_id} minted, writing {len(self.targets)} target(s)")
        errors = []
        for target in gen["targets"]:
            print(f"  {target}", end = " ... ", flush = True)
            try:
                self.github.write_secret(target, self.secret_name, value)
                self.github.write_variable(target, GENERATION_VARIABLE, f"{gen_id}:{gen['fingerprint']}")
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"{target}: {exc}")
                continue
            gen["written"][target] = _iso(self.clock())
            self.save(record)
            print("OK")
        if len(gen["written"]) == len(gen["targets"]):
            gen["completed_at"] = max(gen["written"].values()) if gen["written"] else _iso(self.clock())
            self.save(record)
            print(f"{gen_id} complete, its predecessors reaped six hours after its last write")
        else:
            print(f"{gen_id} incomplete, every older token stays valid")
        self.publish(record, errors)
        return errors


    def _revoke(self, record: dict, gen: dict, errors: list[str]) -> None:
        """
        Revoke every predecessor of a generation, saving each revocation as it lands.

        Args:
            record: the record, changed in place
            gen: the generation
            errors: the run's errors, a failed revocation added and kept for the next run
        """
        for token_id in _outstanding(record, gen["id"]):
            print(f"  revoke {token_id}", end = " ... ", flush = True)
            try:
                self.vercel.revoke(token_id)
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"revoke {token_id}: {exc}")
                continue
            record["tokens"][token_id]["revoked"] = _iso(self.clock())
            self.save(record)
            print("OK")


    def reap(self) -> list[str]:
        """
        Revoke the newest complete generation's predecessors, six hours after its last write.

        Returns:
            list[str]: each failed revocation, kept for the next reap

        Raises:
            Refused: when the newest generation is incomplete or its last write is too recent
        """
        record = self.load()
        gen    = self.newest(record)
        if not gen["completed_at"]:
            raise Refused(f"{gen['id']} is incomplete, so no token is revoked")
        completed = _parse_time(gen["completed_at"])
        if completed is None or self.clock() - completed < REAP_DELAY:
            raise Refused(f"{gen['id']}'s last write is not yet six hours old, so no token is revoked")
        errors: list[str] = []
        self._revoke(record, gen, errors)
        self.publish(record, errors)
        return errors


    def revoke_now(self, generation: str) -> list[str]:
        """
        The emergency. Revoke the named newest generation's predecessors at once, despite any failed target.

        Args:
            generation: the newest generation's id, named so a stale dispatch is refused

        Returns:
            list[str]: the targets to repair, each still holding a revoked token

        Raises:
            Refused: when the generation named is not the newest
        """
        record = self.load()
        gen    = self.newest(record, generation)
        errors: list[str] = []
        self._revoke(record, gen, errors)
        self.publish(record, errors)
        self.failures = errors
        repair        = [target for target in gen["targets"] if target not in gen["written"]]
        for target in repair:
            print(f"REPAIR {target}, it holds no token of {gen['id']}")
        return repair


    def _normalise(self, verified: str) -> set[str]:
        """
        The owner's verified list, each repo:env given its owner.

        Args:
            verified: the list, comma or space separated

        Returns:
            set[str]: each target, owner/repo:environment
        """
        owner = self.targets[0].split("/", 1)[0] if self.targets else ""
        out   = set()
        for word in verified.replace(" ", ",").split(","):
            word = word.strip()
            if word:
                out.add(word if "/" in word else f"{owner}/{word}")
        return out


    def retire_repo_copies(self, generation: str, verified: str) -> list[str]:
        """
        Delete the repository copies once every target of the newest complete generation is verified.

        Args:
            generation: the newest generation's id
            verified: the owner's list of every target with a yes for it, owner/repo:env or repo:env, comma separated

        Returns:
            list[str]: each failed delete, kept for the next run

        Raises:
            Refused: when the generation is not the newest or is incomplete, or the list is not its exact target set
        """
        record = self.load()
        gen    = self.newest(record, generation)
        if not gen["completed_at"]:
            raise Refused(f"{gen['id']} is incomplete, so no repository copy is deleted")
        listed = self._normalise(verified)
        wanted = set(gen["targets"])
        faults = []
        bad    = sorted(target for target in listed if not TARGET.fullmatch(target))
        if bad:
            faults.append(f"not a target, {', '.join(bad)}")
        if listed - wanted:
            faults.append(f"not a target of {gen['id']}, {', '.join(sorted(listed - wanted))}")
        if wanted - listed:
            faults.append(f"not verified, {', '.join(sorted(wanted - listed))}")
        if set(self.targets) != wanted:
            changed = sorted(set(self.targets) ^ wanted)
            faults.append(f"the registry's targets changed since {gen['id']}, {', '.join(changed)}")
        if faults:
            raise Refused("; ".join(faults))
        errors: list[str] = []
        retired = record.setdefault("retired_repo_copies", {})
        for repo in self.repo_copies:
            if repo in retired:
                continue
            print(f"  delete {repo} [repo] {self.secret_name}", end = " ... ", flush = True)
            try:
                self.github.delete_repo_secret(repo, self.secret_name)
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED - {exc}")
                errors.append(f"{repo}: {exc}")
                continue
            retired[repo] = {"generation": gen["id"], "at": _iso(self.clock())}
            self.save(record)
            print("OK")
        self.publish(record, errors)
        return errors

# ======================================================================================================================
# The command line
# ======================================================================================================================

def _registry_entry() -> dict:
    """
    The token's registry entry.

    Returns:
        dict: the entry
    """
    return next(entry for entry in rs._load_registry()["secrets"] if entry["name"] == ENTRY_NAME)


def _need(name: str) -> str:
    """
    An environment variable the mode needs.

    Args:
        name: its name

    Returns:
        str: its value

    Raises:
        SystemExit: when it is not set
    """
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"token_generations: {name} is not set")
    return value


def main(argv: list[str] | None = None) -> int:
    """
    Run one entry point.

    Args:
        argv: the arguments, sys.argv's by default

    Returns:
        int: 0 when it did all it set out to, 1 when a target, a revocation or a delete failed

    Raises:
        SystemExit: when a needed variable is not set or a generation is not named
    """
    parser = argparse.ArgumentParser(description = "The shared Vercel deployment token's generations (D-100).")
    parser.add_argument("mode", choices = ("rotate", "reap", "revoke-now", "retire-repo-copies", "due"))
    parser.add_argument("--generation", default = "")
    parser.add_argument("--verified", default = "")
    parser.add_argument("--facts", default = "")
    args = parser.parse_args(argv)
    if args.mode == "due":
        print(f"mode={due(args.facts, datetime.now(timezone.utc))}")
        return 0
    if args.mode in ("revoke-now", "retire-repo-copies") and not GENERATION_ID.fullmatch(args.generation):
        raise SystemExit("token_generations: --generation must name a generation, such as G1")
    targets, copies = registry_targets(_registry_entry())
    github = LiveGitHub(os.environ.get("GH_TOKEN", ""), _need("FACTS_GH_TOKEN"))
    vercel = LiveVercel(os.environ.get("VERCEL_MASTER_TOKEN", ""), os.environ.get("VERCEL_TEAM_ID", ""))
    engine = Engine(github, vercel, targets, copies, ENTRY_NAME, ENTRY_NAME)
    try:
        if args.mode == "rotate":
            _need("GH_TOKEN")
            _need("VERCEL_MASTER_TOKEN")
            errors = engine.rotate()
        elif args.mode == "reap":
            _need("VERCEL_MASTER_TOKEN")
            errors = engine.reap()
        elif args.mode == "revoke-now":
            _need("VERCEL_MASTER_TOKEN")
            # each target to repair, and each revocation that failed, fails the run so the owner sees them
            errors = engine.revoke_now(args.generation) + engine.failures
        else:
            _need("GH_TOKEN")
            errors = engine.retire_repo_copies(args.generation, args.verified)
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 1
    except (RecordError, rs.VercelMasterScopeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return rs._summary(errors)


if __name__ == "__main__":
    sys.exit(main())
