"""
The deploy stamp's two checks, the bot's redeploy and the freshness rule, read from a project's live production target.

Every deploy the two reusables make carries a stamp in its Vercel metadata, five keys the deploy command writes:
the version, the source commit, the run id and attempt that made it, and the time the deploy job's first step
recorded, before it pulled any settings. This script reads the project's production target, the deployment its
production domains serve, and judges a run against that target's stamp.

  bot     A bot's redeploy is admitted only for the version and the exact commit the live target's stamp carries. A
          live target with no stamp, or no live target, refuses it.
  fresh   Before any promotion, the owner's or a bot's, the live target is read again and a candidate whose stamped
          start is before the live deployment's is refused. A live deployment with no stamp, a legacy one, lets the
          owner's deploy promote and says so in the summary, and refuses a bot. A project with no live deployment
          lets the owner's first deploy promote.

The token comes from VERCEL_TOKEN, the account from VERCEL_ORG_ID and the project from VERCEL_PROJECT_ID. It prints
the target's id and its stamp's version, commit and start, never the token. Standard library only.

Usage:
    python3 deploy_stamp.py bot --version 1.4.0 --commit <40 hex>
    python3 deploy_stamp.py fresh --started 2026-11-23T01:07:30.123Z --path human
"""

from __future__ import annotations

# standard imports
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# ======================================================================================================================
# Configuration
# ======================================================================================================================

API = "https://api.vercel.com"

# the stamp's keys, as both deploy commands write them
STAMP_KEYS = ("kdf_version", "kdf_commit", "kdf_run_id", "kdf_run_attempt", "kdf_started_at")

# the time shape the deploy job's first step writes, UTC to the millisecond
TIME_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
COMMIT_SHAPE = re.compile(r"^[0-9a-f]{40}$")

# ======================================================================================================================
# The stamp
# ======================================================================================================================

@dataclass(frozen = True)
class Stamp:
    """
    A deployment's stamp, read whole or not at all.
    """
    version: str
    commit: str
    run_id: str
    run_attempt: str
    started_at: dt.datetime


def parse_time(text: str) -> dt.datetime | None:
    """
    A stamped time, or None when the text is not in the stamp's shape.

    Args:
        text: the time as the deploy job's first step wrote it

    Returns:
        dt.datetime | None: the time, aware and in UTC, or None
    """
    if not isinstance(text, str) or not TIME_SHAPE.match(text):
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo = dt.UTC)
    except ValueError:
        return None


def read_stamp(meta: object) -> Stamp | None:
    """
    The stamp a deployment's metadata carries, or None when any key is missing or malformed.

    Args:
        meta: the deployment's metadata as Vercel returns it

    Returns:
        Stamp | None: the stamp, or None
    """
    if not isinstance(meta, dict):
        return None
    values = [meta.get(key) for key in STAMP_KEYS]
    if not all(isinstance(value, str) and value for value in values):
        return None
    version, commit, run_id, run_attempt, started = values
    started_at = parse_time(started)
    if not COMMIT_SHAPE.match(commit) or not run_id.isdigit() or not run_attempt.isdigit() or int(run_attempt) < 1:
        return None
    if started_at is None:
        return None
    return Stamp(version, commit, run_id, run_attempt, started_at)

# ======================================================================================================================
# The judgements
# ======================================================================================================================

def judge_bot(stamp: Stamp | None, version: str, commit: str) -> tuple[bool, str]:
    """
    Whether a bot may redeploy this version and commit, the live target's own alone.

    Args:
        stamp: the live target's stamp, or None
        version: the version the run deploys
        commit: the commit the release check resolved

    Returns:
        tuple[bool, str]: whether it is admitted, and why
    """
    if stamp is None:
        return False, "The live deployment carries no stamp, so a bot may not redeploy it."
    if version != stamp.version or commit != stamp.commit:
        return False, (
            f"A bot redeploys the live release alone, version {stamp.version} at {stamp.commit}, and this run "
            f"deploys version {version} at {commit}."
        )
    return True, f"The bot redeploys the live release, version {stamp.version} at {stamp.commit}."


def judge_fresh(started: dt.datetime, stamp: Stamp | None, path: str, *, live: bool) -> tuple[bool, str]:
    """
    Whether a candidate whose deploy job started at `started` may be promoted over the live deployment.

    Args:
        started: the start the candidate's own deploy job stamped
        stamp: the live target's stamp, or None
        path: `human` for the owner's deploy, `bot` for a bot's
        live: whether the project has a live production target at all

    Returns:
        tuple[bool, str]: whether it may be promoted, and why
    """
    if not live:
        if path == "bot":
            return False, "The project has no live deployment, so a bot has nothing to redeploy."
        return True, "The project has no live deployment, so this first deploy is promoted."
    if stamp is None:
        if path == "bot":
            return False, "The live deployment carries no stamp, so a bot may not promote over it."
        return True, "The live deployment carries no stamp, a legacy one, so the owner's deploy is promoted over it."
    if started < stamp.started_at:
        return False, (
            f"This deploy started before the live deployment's, {_iso(started)} before {_iso(stamp.started_at)}, "
            f"so it is not promoted over a newer release."
        )
    return True, f"This deploy started at {_iso(started)}, after the live deployment's {_iso(stamp.started_at)}."


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"

# ======================================================================================================================
# Vercel
# ======================================================================================================================

class Vercel:
    """
    Vercel's REST API through one token, scoped to a team when the account id names one.
    """

    def __init__(self, token: str, org: str) -> None:
        self._token = token
        self.scope = {"teamId": org} if org.startswith("team_") else {}


    def call(self, path: str) -> tuple[int, object]:
        """
        One GET.

        Args:
            path: the path after the host, its version first

        Returns:
            tuple[int, object]: the status and the parsed answer
        """
        query = "?" + urllib.parse.urlencode(self.scope) if self.scope else ""
        request = urllib.request.Request(API + path + query, method = "GET")
        request.add_header("Authorization", "Bearer " + self._token)
        try:
            with urllib.request.urlopen(request, timeout = 30) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return 0, None


def live_target(api: Vercel, project: str) -> tuple[bool, str, dict]:
    """
    The project's production target, read whole.

    Args:
        api: the API
        project: the project's id

    Returns:
        tuple[bool, str, dict]: whether the project was read, and its target's id and metadata, both empty when it
        has no live deployment
    """
    status, answer = api.call(f"/v9/projects/{urllib.parse.quote(project, safe = '')}")
    if status != 200 or not isinstance(answer, dict):
        return False, "", {}
    target = (answer.get("targets") or {}).get("production") or {}
    if not isinstance(target, dict):
        return True, "", {}
    meta = target.get("meta")
    return True, str(target.get("id") or ""), meta if isinstance(meta, dict) else {}

# ======================================================================================================================
# Output
# ======================================================================================================================

def _say(line: str, *, ok: bool) -> None:
    """
    Print the result, an error annotation when refused, and add it to the step's summary.
    """
    print(line if ok else f"::error::{line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding = "utf-8") as handle:
                handle.write(f"### The deploy stamp\n\n{'OK' if ok else 'REFUSED'}: {line}\n")
        except OSError:
            pass

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = "The deploy stamp's checks against the live production target.")
    sub = parser.add_subparsers(dest = "command", required = True)
    bot = sub.add_parser("bot", help = "a bot's redeploy, the live version and commit alone")
    bot.add_argument("--version", required = True)
    bot.add_argument("--commit", required = True)
    fresh = sub.add_parser("fresh", help = "a candidate's start against the live deployment's")
    fresh.add_argument("--started", required = True)
    fresh.add_argument("--path", required = True, choices = ("human", "bot"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, api: Vercel | None = None) -> int:
    args = parse_cli_args(argv)
    token = os.environ.get("VERCEL_TOKEN", "").strip()
    project = os.environ.get("VERCEL_PROJECT_ID", "").strip()
    if not token or not project:
        _say("VERCEL_TOKEN and VERCEL_PROJECT_ID are both needed to read the live target.", ok = False)
        return 1
    started = None
    if args.command == "fresh":
        started = parse_time(args.started)
        if started is None:
            _say(f"The deploy's start {args.started!r} is not in the stamp's shape.", ok = False)
            return 1
    api = api or Vercel(token, os.environ.get("VERCEL_ORG_ID", "").strip())
    read, target_id, meta = live_target(api, project)
    if not read:
        _say("The project's production target could not be read, so nothing is judged and the deploy stops.",
             ok = False)
        return 1
    stamp = read_stamp(meta)
    if stamp is not None:
        print(f"live target {target_id}: version {stamp.version} at {stamp.commit}, started {_iso(stamp.started_at)}")
    if args.command == "bot":
        ok, reason = judge_bot(stamp if target_id else None, args.version, args.commit)
    else:
        ok, reason = judge_fresh(started, stamp, args.path, live = bool(target_id))
    _say(reason, ok = ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
