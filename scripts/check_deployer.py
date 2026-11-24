"""
Deployer authorization gate for KriegerDataForge CD workflows.

GitHub cannot restrict *who* may trigger a `workflow_dispatch` (anyone with write
access can), so deploy authorization is enforced in-workflow instead. The common
`authorize` job in each reusable CD workflow (cd-nextjs-vercel.yml,
cd-python-vercel.yml, terraform-run.yml — and arthurs-portfolio's self-contained
cd.yml) runs this script BEFORE the deploy job and BEFORE the GitHub
Environment approval gate is requested.

The script looks up both of the run's users against the central allow-list in
`deployer_registry.json`, keyed by repo and environment. A rerun keeps github.actor, who
started the run and chose its inputs, and sets github.triggering_actor to whoever reran it,
so both must be approved, and an approved deployer's rerun of a deploy another started stays
denied. The one who started the run is read from the runner's own GITHUB_ACTOR, which every
job holds, so every caller is checked without passing it.

Decision:
  - repo not in registry                    -> DENY  (exit 1, fail closed)
  - environment not in repo entry           -> DENY  (exit 1, fail closed)
  - either user not in the approved list    -> DENY  (exit 1)
  - both users in the approved list         -> ALLOW (exit 0)

Matching on usernames is case-insensitive (GitHub logins are case-insensitive).

The bot's rule. A run whose starter's numeric id names a bot in the registry's automation section is judged by
that bot's rule alone and never falls back to the logins. A bot is named by the user id a run carries as
GITHUB_ACTOR_ID, never by a login and never by its App's id. It is admitted only where the deploy job names itself,
the profile `redeploy`, so any other workflow that calls this check refuses it, and only on a run it both started
and triggered, a `workflow_dispatch` on its first attempt, the first attempt standing in for the triggering actor,
which a run carries as a login alone, from the exact caller workflow and ref its grant names for the repo and
environment. What it may deploy is the deploy job's own check (scripts/deploy_stamp.py). The path taken, `bot` or
`human`, is written to GITHUB_OUTPUT as `path` when the check allows.

Inputs (CLI flags take precedence over environment variables):
  --repo         / DEPLOY_REPO        / GITHUB_REPOSITORY            e.g. "Needless2Say/fitness-app-frontend"
  --actor        / DEPLOY_ACTOR       / GITHUB_TRIGGERING_ACTOR / GITHUB_ACTOR, who triggered or reran the run
  --started-by   / DEPLOY_STARTED_BY  / GITHUB_ACTOR                 who started the run
  --environment  / DEPLOY_ENVIRONMENT                                e.g. "dev", "prod", "github-pages"
  --actor-id     / DEPLOY_ACTOR_ID    / GITHUB_ACTOR_ID              the starter's numeric user id
  --profile      / DEPLOY_PROFILE                                    `redeploy` from the deploy reusables alone
  --event        / DEPLOY_EVENT       / GITHUB_EVENT_NAME            the caller's event
  --workflow-ref / DEPLOY_WORKFLOW_REF / GITHUB_WORKFLOW_REF         the caller's workflow path and ref
  --run-attempt  / DEPLOY_RUN_ATTEMPT / GITHUB_RUN_ATTEMPT           the run's attempt

Usage:
    python3 check_deployer.py
    python3 check_deployer.py --repo Needless2Say/tiffanys-space --actor someone --environment dev

Requirements: standard library only (no pip install).
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import sys
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

REGISTRY_FILE = Path(__file__).parent / "deployer_registry.json"

# the profile the deploy reusables name, the one place a bot is ever admitted
DEPLOY_PROFILE = "redeploy"

# ======================================================================================================================
# Registry helpers
# ======================================================================================================================

def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: deployer registry not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))

# ======================================================================================================================
# Core authorization logic
# ======================================================================================================================

def is_authorized(
    registry: dict,
    repo: str,
    environment: str,
    actor: str,
) -> tuple[bool, str]:
    """
    Return (authorized, human-readable reason).

    Fails closed: an unknown repo or unknown environment is denied.
    """
    deployers: dict = registry.get("deployers", {})

    repo_entry = deployers.get(repo)
    if repo_entry is None:
        return False, (
            f"Repository '{repo}' is not in the deployer registry — denied (fail closed). "
            f"Add it to scripts/deployer_registry.json before deploying."
        )

    approved = repo_entry.get(environment)
    if approved is None:
        known = ", ".join(sorted(repo_entry)) or "(none)"
        return False, (
            f"Environment '{environment}' is not configured for '{repo}' — denied (fail closed). "
            f"Configured environments: {known}."
        )

    approved_lower = {str(u).strip().lower() for u in approved}
    if actor.strip().lower() in approved_lower:
        return True, f"'{actor}' is an approved deployer for {repo} [{environment}]."

    approved_display = ", ".join(approved) or "(none)"
    return False, (
        f"'{actor}' is NOT an approved deployer for {repo} [{environment}]. " f"Approved deployers: {approved_display}."
    )


def find_bot(registry: dict, actor_id: str) -> dict | None:
    """
    The grants of the bot a numeric user id names, or None when it names none.

    Args:
        registry: the deployer registry
        actor_id: the run's starter's numeric user id

    Returns:
        dict | None: the bot's grants by repo and environment, or None
    """
    candidate = actor_id.strip()
    if not candidate.isdigit():
        return None
    bots   = (registry.get("automation") or {}).get("bots") or {}
    grants = bots.get(candidate)
    return grants if isinstance(grants, dict) else None


def is_bot_authorized(
    grants: dict,
    *,
    repo: str,
    environment: str,
    profile: str,
    event: str,
    workflow_ref: str,
    run_attempt: str,
    started_by: str,
    actor: str,
) -> tuple[bool, str]:
    """
    Return (authorized, human-readable reason) for a run a bot started, every condition required.

    Args:
        grants: the bot's grants by repo and environment
        repo: the repository deployed
        environment: the environment deployed
        profile: the profile the calling job names, `redeploy` from the deploy reusables alone
        event: the caller's event
        workflow_ref: the caller's workflow path and ref, as GitHub writes it
        run_attempt: the run's attempt
        started_by: the login that started the run
        actor: the login that triggered or reran it

    Returns:
        tuple[bool, str]: whether the bot is admitted, and why
    """
    if profile != DEPLOY_PROFILE:
        return False, "A bot is admitted only by a deploy job's own check, and this job names no deploy profile."
    if started_by.strip().lower() != actor.strip().lower():
        return False, f"A bot started this run and {actor!r} triggered it, and a bot's run is admitted only as its own."
    if run_attempt.strip() != "1":
        return False, f"A bot is admitted on a run's first attempt alone, and this is attempt {run_attempt!r}."
    if event != "workflow_dispatch":
        return False, f"A bot is admitted on a workflow_dispatch alone, and this run's event is {event!r}."
    caller = (grants.get(repo) or {}).get(environment)
    if not isinstance(caller, dict):
        return False, f"The bot holds no grant for {repo} [{environment}]."
    expected = f"{repo}/{caller.get('workflow')}@{caller.get('ref')}"
    if workflow_ref != expected:
        return False, f"The bot's run calls from {workflow_ref!r}, and its grant names {expected!r} alone."
    return True, f"The bot is admitted to redeploy {repo} [{environment}] from {expected}."

# ======================================================================================================================
# Output helpers
# ======================================================================================================================

def _emit(message: str, *, ok: bool) -> None:
    """
    Print the result and append it to the GitHub Actions step summary if available.
    """
    # Plain-ASCII prefixes (no emoji) so output is safe on every console encoding,
    # matching the house style of the other scripts.
    line = f"{'OK' if ok else 'DENIED'}: {message}"
    print(line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding = "utf-8") as fh:
                fh.write(f"### Deployer authorization\n\n{line}\n")
        except OSError:
            pass


def _write_path(path: str) -> None:
    """
    The path an allowed run took, as the step's output `path`, when the step has outputs.

    Args:
        path: `bot` or `human`
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding = "utf-8") as handle:
            handle.write(f"path={path}\n")

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = "Verify the dispatching user is an approved deployer for this repo + environment.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = "\n".join((
            "Values fall back to environment variables when flags are omitted:",
            "  --repo         <- DEPLOY_REPO / GITHUB_REPOSITORY",
            "  --actor        <- DEPLOY_ACTOR / GITHUB_TRIGGERING_ACTOR / GITHUB_ACTOR",
            "  --started-by   <- DEPLOY_STARTED_BY / GITHUB_ACTOR",
            "  --environment  <- DEPLOY_ENVIRONMENT",
            "  --actor-id     <- DEPLOY_ACTOR_ID / GITHUB_ACTOR_ID",
            "  --profile      <- DEPLOY_PROFILE",
            "  --event        <- DEPLOY_EVENT / GITHUB_EVENT_NAME",
            "  --workflow-ref <- DEPLOY_WORKFLOW_REF / GITHUB_WORKFLOW_REF",
            "  --run-attempt  <- DEPLOY_RUN_ATTEMPT / GITHUB_RUN_ATTEMPT",
        )),
    )
    parser.add_argument("--repo", default = None, help = "owner/repo, e.g. Needless2Say/tiffanys-space")
    parser.add_argument("--actor", default = None, help = "GitHub username that triggered or reran the deploy")
    parser.add_argument("--started-by", default = None, help = "GitHub username that started the deploy's run")
    parser.add_argument("--environment", default = None, help = "target environment, e.g. dev / prod / github-pages")
    parser.add_argument("--actor-id", default = None, help = "the numeric user id of the run's starter")
    parser.add_argument("--profile", default = None, help = "the profile the calling job names, redeploy alone")
    parser.add_argument("--event", default = None, help = "the caller's event")
    parser.add_argument("--workflow-ref", default = None, help = "the caller's workflow path and ref")
    parser.add_argument("--run-attempt", default = None, help = "the run's attempt")
    return parser.parse_args(argv)


def _resolve(value: str | None, *env_names: str) -> str:
    """
    Return the CLI value if set, else the first non-empty environment variable.
    """
    if value is not None:
        return value
    for name in env_names:
        candidate = os.environ.get(name, "")
        if candidate:
            return candidate
    return ""

# ======================================================================================================================
# Entry point
# ======================================================================================================================

def main(argv: list[str] | None = None) -> int:
    args = parse_cli_args(argv)

    repo        = _resolve(args.repo, "DEPLOY_REPO", "GITHUB_REPOSITORY")
    actor       = _resolve(args.actor, "DEPLOY_ACTOR", "GITHUB_TRIGGERING_ACTOR", "GITHUB_ACTOR")
    started_by  = _resolve(args.started_by, "DEPLOY_STARTED_BY", "GITHUB_ACTOR")
    environment = _resolve(args.environment, "DEPLOY_ENVIRONMENT")

    inputs  = (("repo", repo), ("actor", actor), ("started_by", started_by), ("environment", environment))
    missing = [name for name, val in inputs if not val.strip()]
    if missing:
        _emit(f"Cannot evaluate deployer authorization — missing input(s): {', '.join(missing)}.", ok = False)
        return 1

    registry = _load_registry()
    # a bot is known by its numeric id alone, and a run it started is its rule's, never the logins'
    grants = find_bot(registry, _resolve(args.actor_id, "DEPLOY_ACTOR_ID", "GITHUB_ACTOR_ID"))
    if grants is not None:
        authorized, reason = is_bot_authorized(
            grants,
            repo = repo,
            environment = environment,
            profile = _resolve(args.profile, "DEPLOY_PROFILE"),
            event = _resolve(args.event, "DEPLOY_EVENT", "GITHUB_EVENT_NAME"),
            workflow_ref = _resolve(args.workflow_ref, "DEPLOY_WORKFLOW_REF", "GITHUB_WORKFLOW_REF"),
            run_attempt = _resolve(args.run_attempt, "DEPLOY_RUN_ATTEMPT", "GITHUB_RUN_ATTEMPT"),
            started_by = started_by,
            actor = actor,
        )
        _emit(reason, ok = authorized)
        if not authorized:
            return 1
        _write_path("bot")
        return 0
    # the one who started the run chose its inputs, and a rerun keeps it, so it is judged first and must pass too
    for user in (started_by, actor):
        authorized, reason = is_authorized(registry, repo, environment, user)
        if not authorized:
            _emit(f"{reason} The run was started by {started_by!r} and triggered by {actor!r}.", ok = False)
            return 1
    _emit(reason, ok = True)
    _write_path("human")
    return 0


if __name__ == "__main__":
    sys.exit(main())
