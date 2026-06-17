"""
Deployer authorization gate for KriegerDataForge CD workflows.

GitHub cannot restrict *who* may trigger a `workflow_dispatch` (anyone with write
access can), so deploy authorization is enforced in-workflow instead. The common
`authorize` job in each reusable CD workflow (cd-nextjs-vercel.yml,
cd-python-vercel.yml, cd-terraform.yml — and arthurs-portfolio's self-contained
nextjs.yml) runs this script BEFORE the deploy job and BEFORE the GitHub
Environment approval gate is requested.

The script looks up the dispatching user (github.triggering_actor) against the
central allow-list in `deployer_registry.json`, keyed by repo and environment.

Decision:
  - repo not in registry            -> DENY  (exit 1, fail closed)
  - environment not in repo entry   -> DENY  (exit 1, fail closed)
  - actor not in the approved list  -> DENY  (exit 1)
  - actor in the approved list      -> ALLOW (exit 0)

Matching on usernames is case-insensitive (GitHub logins are case-insensitive).

Inputs (CLI flags take precedence over environment variables):
  --repo         / DEPLOY_REPO        / GITHUB_REPOSITORY            e.g. "Needless2Say/fitness-app-frontend"
  --actor        / DEPLOY_ACTOR       / GITHUB_TRIGGERING_ACTOR / GITHUB_ACTOR
  --environment  / DEPLOY_ENVIRONMENT                                e.g. "dev", "prod", "github-pages"

Usage:
    python3 check_deployer.py
    python3 check_deployer.py --repo Needless2Say/tiffanys-space --actor someone --environment dev

Requirements: standard library only (no pip install).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ============================================================
# Configuration
# ============================================================

REGISTRY_FILE = Path(__file__).parent / "deployer_registry.json"


# ============================================================
# Registry helpers
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: deployer registry not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


# ============================================================
# Core authorization logic
# ============================================================


def is_authorized(
    registry: dict,
    repo: str,
    environment: str,
    actor: str,
) -> tuple[bool, str]:
    """Return (authorized, human-readable reason).

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
        f"'{actor}' is NOT an approved deployer for {repo} [{environment}]. "
        f"Approved deployers: {approved_display}."
    )


# ============================================================
# Output helpers
# ============================================================


def _emit(message: str, *, ok: bool) -> None:
    """Print the result and append it to the GitHub Actions step summary if available."""
    # Plain-ASCII prefixes (no emoji) so output is safe on every console encoding,
    # matching the house style of the other scripts.
    line = f"{'OK' if ok else 'DENIED'}: {message}"
    print(line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(f"### Deployer authorization\n\n{line}\n")
        except OSError:
            pass


# ============================================================
# CLI
# ============================================================


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the dispatching user is an approved deployer for this repo + environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Values fall back to environment variables when flags are omitted:\n"
            "  --repo         <- DEPLOY_REPO / GITHUB_REPOSITORY\n"
            "  --actor        <- DEPLOY_ACTOR / GITHUB_TRIGGERING_ACTOR / GITHUB_ACTOR\n"
            "  --environment  <- DEPLOY_ENVIRONMENT"
        ),
    )
    parser.add_argument("--repo", default=None, help="owner/repo, e.g. Needless2Say/tiffanys-space")
    parser.add_argument("--actor", default=None, help="GitHub username that dispatched the deploy")
    parser.add_argument("--environment", default=None, help="target environment, e.g. dev / prod / github-pages")
    return parser.parse_args(argv)


def _resolve(value: str | None, *env_names: str) -> str:
    """Return the CLI value if set, else the first non-empty environment variable."""
    if value is not None:
        return value
    for name in env_names:
        candidate = os.environ.get(name, "")
        if candidate:
            return candidate
    return ""


# ============================================================
# Entry point
# ============================================================


def main(argv: list[str] | None = None) -> int:
    args = parse_cli_args(argv)

    repo = _resolve(args.repo, "DEPLOY_REPO", "GITHUB_REPOSITORY")
    actor = _resolve(args.actor, "DEPLOY_ACTOR", "GITHUB_TRIGGERING_ACTOR", "GITHUB_ACTOR")
    environment = _resolve(args.environment, "DEPLOY_ENVIRONMENT")

    missing = [name for name, val in (("repo", repo), ("actor", actor), ("environment", environment)) if not val.strip()]
    if missing:
        _emit(f"Cannot evaluate deployer authorization — missing input(s): {', '.join(missing)}.", ok=False)
        return 1

    registry = _load_registry()
    authorized, reason = is_authorized(registry, repo, environment, actor)
    _emit(reason, ok=authorized)
    return 0 if authorized else 1


if __name__ == "__main__":
    sys.exit(main())
