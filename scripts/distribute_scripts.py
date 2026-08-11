"""
Check and distribute the ecosystem dev scripts (bump_version.py / check_version.py /
version_targets.py) from the canonical source in kriegerdataforge-cicd/scripts/common/
to every consumer repo in scripts/scripts_registry.json — plus the one Makefile recipe
that wires them into `make ci`.

This is the script-sync sibling of distribute_kit.py (ADR D-013 mirrors the kit's
ADR D-001): ONE source of truth (scripts/common/), ONE registry (scripts_registry.json),
owner-gated PRs, built on the shared engine in common/repo_sync.py. It exists so the
per-repo copies of the version tooling can never drift again (they had forked into four
variants, one of which let an invalid 0.10.6 -> 0.10.8 jump through).

Synced items:
  - The registry's files[] (src -> dest), vendored byte-identical.
  - The `ci-version-check:` Makefile recipe, REWRITTEN to the canonical thin call of
    the vendored checker (registry key "makefile_patch"). The patch replaces the target
    line plus its tab-indented recipe lines — a well-delimited make block — and is
    idempotent (patching an already-canonical block is a no-op). A Makefile without the
    target raises PatchError -> that repo is reported NEEDS MANUAL ATTENTION.

Modes:
  check       Read-only drift report. Exits non-zero if any repo is out of sync. OPENS NOTHING.
  distribute  Opens one review-gated PR per drifted repo ("chore(scripts): sync ecosystem
              dev scripts <SCRIPTS_VERSION>"). NEVER auto-merges.

IMPORTANT — version-check: scripts-sync PRs do not bump VERSION. The central
scripts/common/check_version.py exempts PRs touching only the registry dest paths
(plus Makefile, on chore/scripts-sync-* branches only), so the sync PRs pass the gate.

Requirements:
    pip install requests

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write
              (distribute) on all target repos. Use the CICD_PAT value.

Usage:
    GH_TOKEN=... python distribute_scripts.py check
    GH_TOKEN=... python distribute_scripts.py check --only check_version.py
    GH_TOKEN=... python distribute_scripts.py distribute
    # Target a subset of repos (comma-separated exact names); blank = all:
    GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import re
import sys
from pathlib import Path

# third party imports
# local imports — the shared sync engine (transport, retry session, fan-out loops)
from common.repo_sync import PatchError, SyncItem, _select_repos, run_check, run_distribute

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR          = Path(__file__).parent
REPO_ROOT            = SCRIPTS_DIR.parent
REGISTRY_FILE        = SCRIPTS_DIR / "scripts_registry.json"
SCRIPTS_VERSION_FILE = SCRIPTS_DIR / "SCRIPTS_VERSION"

MAKEFILE_DEST = "Makefile"

# The canonical `ci-version-check` recipe every repo converges on: a thin call of the
# vendored checker, which owns ALL the logic (consistency + strict increment +
# skip-when-base-unfetchable). `$(if ...)` covers repos that define no BASE_BRANCH;
# PYTHONUTF8=1 matches the `_BUMP` convention (cp1252 Windows consoles).
CANONICAL_RECIPE = (
    "ci-version-check: _ensure-venv ## CI: version consistency + strict +1 increment"
    " vs origin/main (vendored scripts/check_version.py)\n"
    '\t@printf "$(GREEN)CI: version check...$(NC)\\n"\n'
    '\t@PYTHONUTF8=1 $(PYTHON) scripts/check_version.py --base-branch "$(if $(BASE_BRANCH),$(BASE_BRANCH),main)"\n'
)

# A make recipe block: the target line plus the maximal run of tab-prefixed lines.
_RECIPE_RE = re.compile(r"^ci-version-check:[^\n]*\n(?:\t[^\n]*\n)*", re.MULTILINE)

_CLI_EPILOG = """Examples:
  GH_TOKEN=... python distribute_scripts.py check
  GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
  GH_TOKEN=... python distribute_scripts.py distribute --only check_version.py"""

_REPOS_HELP = """Only operate on these repos (comma-separated EXACT names, e.g.
'kriegerdataforge,tiffanys-space'). Matches the full owner/repo or the short name
exactly (not a substring). Blank = all repos in the registry."""

_PR_BODY_TEMPLATE = """Automated sync of the ecosystem dev scripts to **{version}** from
`kriegerdataforge-cicd/scripts/common/` (ADR D-013).

Items updated: {items}

The vendored `scripts/check_version.py` now enforces the STRICT single-increment rule locally
(`make ci` fails on jumps like 0.10.6 -> 0.10.8), and `scripts/bump_version.py` computes bumps
from origin/main so double-bumps are impossible. The `ci-version-check` Makefile recipe is
rewritten to call the vendored checker (the old SKIP_INIT knob and per-repo inline checks are
retired; target detection is automatic via `scripts/version_targets.py`).

No VERSION bump: scripts-sync PRs are exempt from the version gate (see check_version.py /
ADR D-013). Please review and merge."""

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _load_registry() -> dict:
    """
    Load scripts_registry.json from beside this script.

    Returns:
        dict: the parsed registry
    """
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _scripts_version() -> str:
    """
    Read the SCRIPTS_VERSION sync marker.

    Returns:
        str: the marker value, or "unknown" when the file is missing
    """
    if SCRIPTS_VERSION_FILE.is_file():
        return SCRIPTS_VERSION_FILE.read_text(encoding = "utf-8").strip()
    return "unknown"


def patch_ci_version_check(text: str | None) -> str:
    """
    Rewrite the `ci-version-check:` recipe block to CANONICAL_RECIPE.

    Idempotent by construction: the canonical block itself matches the recipe regex
    and maps to itself.

    Args:
        text: the target repo's current Makefile content, or None when absent

    Returns:
        str: the Makefile content with the canonical recipe in place (LF endings)

    Raises:
        PatchError: when the Makefile is missing or has no `ci-version-check` target
    """
    if text is None:
        raise PatchError("Makefile not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if not _RECIPE_RE.search(normalized):
        raise PatchError("Makefile has no `ci-version-check:` recipe to rewrite")
    # function replacement -> inserted literally (no \-escape processing of the recipe)
    return _RECIPE_RE.sub(lambda _match: CANONICAL_RECIPE, normalized, count = 1)


def _build_items(registry: dict, only: str | None) -> list[SyncItem]:
    """
    Build the SyncItems this run operates on.

    The registry's src->dest files (byte-identical) plus the Makefile recipe patch,
    optionally narrowed by --only (dest substring).

    Args:
        registry: the parsed scripts registry
        only: dest-substring filter, or None for all items

    Returns:
        list[SyncItem]: the items to check or distribute
    """
    items: list[SyncItem] = []
    for entry in registry.get("files", []):
        src, dest = entry["src"], entry["dest"]
        canonical = (REPO_ROOT / src).read_text(encoding = "utf-8")
        items.append(SyncItem(dest = dest, desired = lambda _remote, content = canonical: content))
    if registry.get("makefile_patch"):
        items.append(SyncItem(dest = MAKEFILE_DEST, desired = patch_ci_version_check))
    if only:
        items = [item for item in items if only in item.dest]
        if not items:
            sys.exit(f"Error: --only '{only}' matched no synced files (dests + {MAKEFILE_DEST!r}).")
    return items

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    """
    Parse the CLI arguments.

    Returns:
        argparse.Namespace: mode, only, repos
    """
    parser = argparse.ArgumentParser(
        description = "Check or distribute the ecosystem dev scripts across all repos.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = _CLI_EPILOG,
    )
    parser.add_argument(
        "mode",
        choices = ["check", "distribute"],
        help = "'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default = None,
        help = "Only operate on synced files whose DEST path contains this substring (e.g. 'check_version.py').",
    )
    parser.add_argument(
        "--repos",
        default = None,
        help = _REPOS_HELP,
    )
    return parser.parse_args()


def main() -> None:
    """
    Run the selected mode (check or distribute) and exit with its status code.

    Returns:
        None
    """
    args     = parse_cli_args()
    registry = _load_registry()
    token    = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    version = _scripts_version()
    items   = _build_items(registry, args.only)
    repos   = _select_repos(registry, args.repos)

    if args.mode == "check":
        banner = (f"Checking ecosystem dev scripts {version} across {len(repos)} repo(s), {len(items)} item(s):")
        sys.exit(run_check(token, repos, items, banner))
    else:
        print(f"Distributing ecosystem dev scripts {version} ({len(items)} item(s)) to {len(repos)} repo(s):")
        sys.exit(
            run_distribute(
                token,
                repos,
                items,
                sync_branch = f"chore/scripts-sync-{version}",
                pr_title = f"chore(scripts): sync ecosystem dev scripts {version}",
                pr_body_fn = lambda drift: _PR_BODY_TEMPLATE.format(
                    version = version,
                    items = ", ".join(item.dest for item in drift),
                ),
                commit_msg_fn = lambda item: f"chore(scripts): sync {item.dest} to {version}",
            )
        )


if __name__ == "__main__":
    main()
