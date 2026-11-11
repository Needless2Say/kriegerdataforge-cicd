#!/usr/bin/env python3
"""
terraform_run.py, the reusable terraform workflow's generic helpers (terraform in Actions, design 5.6 and 5.7).

Each subcommand is one check the workflow `terraform-run.yml` makes, environment agnostic, the names of tenants,
secrets and roots staying in the caller's own manifest and scripts (AGENTS.md rule 12).

The release's tag is resolved once by `check_release_commit.py`, the one release check every CD workflow runs, and
its floor held by `at-least` here.

  no-changes  A plan of no changes, no resource change and no output change, the release marker's move to the run's
              own release the one change expected and checked to be the marker alone (Round Table 80, L4).
  seal        The gate's plan manifest sealed by an HMAC-SHA256 under TF_MANIFEST_KEY over its canonical JSON.
  verify      A deploy's check of that manifest, the seal first, then each field equal to the deploy's own, the plan's
              age within its limit, the Terraform version's syntax and floor, in that order, since every field is
              untrusted until the seal holds (the revision read of version 9).
  at-least    A version at or above a floor, the release against its environment's, the Terraform version against
              the supported floor, and an automatic run's release against the one the state last applied.
  identity    A backend's identity from its connection string, host, port, database and schema, never the role or
              its password, read from a named environment variable so the string never reaches a process's argv.

Prints names, addresses and digests alone, never a secret. Exit 0 when the check passes, 1 when it finds anything,
2 on a refusal, an input it will not read.

Requirements: standard library only (no pip install).
"""

from __future__ import annotations

# standard imports
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# a release version and a Terraform version, three numbers, no leading zero, nothing else
VERSION: re.Pattern[str] = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

# a backend schema's name, a Postgres identifier the backend block commits
SCHEMA: re.Pattern[str] = re.compile(r"[a-z_][a-z0-9_]{0,62}")

# the manifest's schema, and how long a gate's plan stays good unless the owner sets another limit
MANIFEST_SCHEMA:       int = 1
DEFAULT_MAX_AGE_HOURS: int = 72

# the fields a deploy compares with its own, each equal or the deploy stops
COMPARED_FIELDS: tuple[str, ...] = (
    "gate_run_id",
    "gate_run_attempt",
    "environment",
    "backend_identity",
    "commit",
    "plan_sha256",
    "lock_sha256",
    "secret_hashes",
)

# the resource actions a plan of no changes allows, a no-op and a data source's read
QUIET_ACTIONS: tuple[list[str], ...] = (["no-op"], ["read"])

# the release marker's output (D-018 in the terraform repo)
RELEASE_OUTPUT: str = "release"


class Refused(ValueError):
    """
    An input this script will not read, its message naming no secret.
    """

# ======================================================================================================================
# Versions
# ======================================================================================================================

def version_tuple(version: str) -> tuple[int, int, int]:
    """
    A version's three numbers, refused unless it is exactly X.Y.Z.

    Args:
        version: The version, without a v

    Returns:
        The three numbers, comparable in order

    Raises:
        Refused: When it is not X.Y.Z
    """
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise Refused(f"{version!r} is no version of the form X.Y.Z")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch

# ======================================================================================================================
# A plan of no changes
# ======================================================================================================================

def no_change_findings(plan: dict, release: str) -> list[str]:
    """
    Every change a plan holds beyond the release marker's move to the run's own release.

    Args:
        plan: The plan as `terraform show -json` writes it
        release: The run's release, the tag's name, e.g. v0.11.0

    Returns:
        One finding per change, by address or output name, empty for a plan of no changes
    """
    found: list[str] = []
    if plan.get("errored"):
        found.append("the plan is marked errored")
    for change in plan.get("resource_changes") or []:
        actions = (change.get("change") or {}).get("actions")
        if actions not in QUIET_ACTIONS:
            found.append(f"{change.get('address')} plans {actions}")
    for name, change in sorted((plan.get("output_changes") or {}).items()):
        actions = change.get("actions")
        if actions == ["no-op"]:
            continue
        if name == RELEASE_OUTPUT and actions in (["update"], ["create"]) and change.get("after") == release:
            continue
        found.append(f"output {name} plans {actions}, only {RELEASE_OUTPUT} may move, and only to {release}")
    return found

# ======================================================================================================================
# The sealed plan manifest
# ======================================================================================================================

def canonical(fields: dict) -> bytes:
    """
    The manifest's fields as the bytes the seal is taken over, sorted keys, no spaces, ASCII.

    Args:
        fields: The manifest's fields

    Returns:
        The canonical JSON's bytes
    """
    return json.dumps(fields, sort_keys = True, separators = (",", ":"), ensure_ascii = True).encode("ascii")


def _mac(fields: dict, key: str) -> str:
    """
    The HMAC-SHA256 of the fields' canonical bytes under the key.

    Args:
        fields: The manifest's fields
        key: TF_MANIFEST_KEY

    Returns:
        The digest in hex

    Raises:
        Refused: When the key is empty
    """
    if not key:
        raise Refused("the manifest key is empty")
    return hmac.new(key.encode("utf-8"), canonical(fields), hashlib.sha256).hexdigest()


def seal(fields: dict, key: str) -> dict:
    """
    Seal the gate's plan manifest.

    Args:
        fields: The manifest's fields, no secret among them, each secret's keyed hash alone
        key: TF_MANIFEST_KEY

    Returns:
        ``{"fields": fields, "seal": hex}``

    Raises:
        Refused: When the key is empty
    """
    return {"fields": fields, "seal": _mac(fields, key)}


def _parse_time(value: object) -> datetime | None:
    """
    A UTC time written as YYYY-MM-DDTHH:MM:SSZ.

    Args:
        value: The written time

    Returns:
        The time, or None when it is not written so
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo = timezone.utc)
    except ValueError:
        return None


def verify(
    manifest: dict,
    key: str,
    expected: dict,
    now: datetime,
    *,
    floor: str,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> list[str]:
    """
    A deploy's check of the gate's manifest, the seal first and nothing else judged when it fails.

    Args:
        manifest: The manifest the gate uploaded
        key: TF_MANIFEST_KEY
        expected: The deploy's own value of each compared field
        now: The deploy's time
        floor: The supported Terraform floor, X.Y.Z
        max_age_hours: How old a gate's plan may be

    Returns:
        One finding per failed check, empty when the manifest may be applied
    """
    fields = manifest.get("fields") if isinstance(manifest, dict) else None
    given  = manifest.get("seal") if isinstance(manifest, dict) else None
    if not isinstance(fields, dict) or not isinstance(given, str) or not given:
        return ["the manifest holds no fields or no seal"]
    if not hmac.compare_digest(_mac(fields, key), given):
        return ["the manifest's seal does not hold"]
    found: list[str] = []
    if fields.get("schema") != MANIFEST_SCHEMA:
        found.append(f"the manifest's schema is {fields.get('schema')!r}, not {MANIFEST_SCHEMA}")
    for name in COMPARED_FIELDS:
        if fields.get(name) != expected.get(name):
            found.append(f"the manifest's {name} is not the deploy's own")
    created = _parse_time(fields.get("created_at"))
    if created is None:
        found.append("the manifest's created_at is no time")
    elif created > now:
        found.append("the manifest was created after the deploy's own time")
    elif (now - created).total_seconds() > max_age_hours * 3600:
        found.append(f"the gate's plan is older than {max_age_hours} hours, a new gate is needed")
    version = fields.get("terraform_version")
    try:
        if version_tuple(version) < version_tuple(floor):
            found.append(f"the manifest's Terraform {version} is below the floor {floor}")
    except Refused:
        found.append("the manifest's terraform_version is no version of the form X.Y.Z")
    return found


def verified_terraform_version(manifest: dict) -> str:
    """
    The Terraform version a verified manifest names, the one the deploy installs and reads back.

    Args:
        manifest: A manifest ``verify`` passed

    Returns:
        The version, X.Y.Z
    """
    version = manifest["fields"]["terraform_version"]
    version_tuple(version)
    return version

# ======================================================================================================================
# The backend identity
# ======================================================================================================================

def identity(conn: str, schema: str) -> str:
    """
    A pg backend's identity, its host, port, database and schema, the same for every role of one state.

    Args:
        conn: The connection string, postgres or postgresql
        schema: The schema the backend block commits

    Returns:
        ``host:port/database?schema=name``, the host lower cased

    Raises:
        Refused: When the string is no postgres URL with a host and a database, or the schema is no name, the
            message never naming the string
    """
    if not isinstance(schema, str) or not SCHEMA.fullmatch(schema):
        raise Refused("the schema is no Postgres name")
    try:
        parts = urllib.parse.urlsplit(conn or "")
        port  = parts.port or 5432
    except ValueError:
        raise Refused("the connection string is no postgres URL") from None
    database = parts.path.lstrip("/")
    if parts.scheme not in ("postgres", "postgresql") or not parts.hostname or not database or "/" in database:
        raise Refused("the connection string is no postgres URL with a host and a database")
    return f"{parts.hostname.lower()}:{port}/{database}?schema={schema}"

# ======================================================================================================================
# CLI
# ======================================================================================================================

def _read_json(path: str) -> dict:
    """
    A file's JSON object.

    Args:
        path: The file

    Returns:
        The object

    Raises:
        Refused: When the file cannot be read as a JSON object
    """
    try:
        with open(path, encoding = "utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise Refused(f"{path} cannot be read as JSON, {exc.__class__.__name__}") from None
    if not isinstance(data, dict):
        raise Refused(f"{path} holds no JSON object")
    return data


def _write_output(name: str, value: str) -> None:
    """
    Write one step output when the job has an output file.

    Args:
        name: The output's name
        value: Its value, no secret
    """
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding = "utf-8") as output:
            output.write(f"{name}={value}\n")


def _report(found: list[str], what: str) -> int:
    """
    Print each finding and the verdict, and answer the exit code.

    Args:
        found: The findings, no secret in any
        what: The check's name

    Returns:
        0 with none, 1 with any
    """
    for line in found:
        print(f"ERROR: {line}")
    print(f"==> {what} " + (f"FAILED, {len(found)} findings" if found else "PASSED"))
    return 1 if found else 0


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse the subcommand and its flags.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        The parsed namespace
    """
    parser = argparse.ArgumentParser(description = "The reusable terraform workflow's generic helpers.")
    sub    = parser.add_subparsers(dest = "command", required = True)

    quiet_cmd = sub.add_parser("no-changes", help = "check a plan is a plan of no changes")
    quiet_cmd.add_argument("--plan", required = True)
    quiet_cmd.add_argument("--release", required = True)

    seal_cmd = sub.add_parser("seal", help = "seal the gate's plan manifest")
    seal_cmd.add_argument("--fields", required = True)
    seal_cmd.add_argument("--out", required = True)
    seal_cmd.add_argument("--key-env", default = "TF_MANIFEST_KEY")

    verify_cmd = sub.add_parser("verify", help = "verify the gate's plan manifest")
    verify_cmd.add_argument("--manifest", required = True)
    verify_cmd.add_argument("--expected", required = True)
    verify_cmd.add_argument("--floor", required = True)
    verify_cmd.add_argument("--max-age-hours", type = int, default = DEFAULT_MAX_AGE_HOURS)
    verify_cmd.add_argument("--key-env", default = "TF_MANIFEST_KEY")

    least_cmd = sub.add_parser("at-least", help = "check a version is at or above a floor")
    least_cmd.add_argument("--version", required = True)
    least_cmd.add_argument("--floor", required = True)
    least_cmd.add_argument("--what", default = "the version")

    identity_cmd = sub.add_parser("identity", help = "print a backend's identity from a named variable's string")
    identity_cmd.add_argument("--env-var", required = True)
    identity_cmd.add_argument("--schema", required = True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run one subcommand.

    Args:
        argv: The CLI arguments, None for the process's own

    Returns:
        0 when the check passes, 1 when it finds anything, 2 on a refusal
    """
    args = parse_cli_args(argv)
    try:
        if args.command == "no-changes":
            return _report(no_change_findings(_read_json(args.plan), args.release), "Plan of no changes")
        if args.command == "seal":
            sealed = seal(_read_json(args.fields), os.environ.get(args.key_env, ""))
            Path(args.out).write_text(json.dumps(sealed, indent = 2, sort_keys = True) + "\n", encoding = "utf-8")
            print(f"==> Manifest sealed, {args.out}")
            return 0
        if args.command == "verify":
            manifest = _read_json(args.manifest)
            found    = verify(
                manifest,
                os.environ.get(args.key_env, ""),
                _read_json(args.expected),
                datetime.now(timezone.utc),
                floor = args.floor,
                max_age_hours = args.max_age_hours,
            )
            code     = _report(found, "Manifest check")
            if code == 0:
                _write_output("terraform_version", verified_terraform_version(manifest))
            return code
        if args.command == "at-least":
            # a leading v is the tag's spelling of the same version
            version = args.version[1:] if args.version.startswith("v") else args.version
            if version_tuple(version) < version_tuple(args.floor):
                print(f"ERROR: {args.what} {version} is below {args.floor}")
                return 1
            print(f"==> {args.what} {version} is at or above {args.floor}")
            return 0
        print(identity(os.environ.get(args.env_var, ""), args.schema))
        return 0
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
