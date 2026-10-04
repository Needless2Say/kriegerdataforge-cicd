"""
Check and distribute the agentic-workflow kit and the ecosystem dev scripts together, one sync pull request per repo
(ADR D-047).

A kit Distribute and a scripts Distribute each open a pull request in every repo, and each pull request ran the repo's
whole CI. When both are due this flow carries both in ONE branch per repo, `chore/ecosystem-sync-kit-<kit>-scripts-
<scripts>`, so a repo gets one pull request. The kit's items, the AGENTS.md context line and the Dependabot limits come
from distribute_kit.py, the scripts' items and patches from distribute_scripts.py, and the shared engine in
common/repo_sync.py makes the commits. The skip rule applies to the whole change set of a repo, so the pull request
skips CI only when every file it changes is on the union of the two allowlists. A Makefile patch or the mutation
engine in it lets CI run.

The separate flows keep working, this one is for the day both are due.

Modes:
  check       Read-only drift report across both sets. OPENS NOTHING.
  distribute  Opens one review-gated PR per drifted repo. NEVER auto-merges.

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write (distribute).

Usage:
    GH_TOKEN=... python distribute_all.py check
    GH_TOKEN=... python distribute_all.py distribute --repos kriegerdataforge-sdk,fitness-app-backend
"""

from __future__ import annotations

# standard imports
import argparse
import os
import sys

# third party imports
import distribute_kit as dk
import distribute_scripts as ds
from common.repo_sync import SyncItem, _select_repos, run_check, run_distribute

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SYNC_BRANCH_PREFIX = "chore/ecosystem-sync-"

_PR_BODY_TEMPLATE = """Automated sync of the agentic-workflow kit **{kit}** and the ecosystem dev scripts **{scripts}**
from `kriegerdataforge-cicd`, in one pull request (cicd D-047).

Items updated: {items}

No VERSION bump, a combined sync branch is exempt from the version gate like the kit's and the scripts' own (D-001,
D-013, D-047). Please review and merge."""

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def merged_entries(kit_registry: dict, scripts_registry: dict) -> list[dict]:
    """
    One entry per repo across both registries, the scripts entry's settings kept, and a flag for each registry the repo
    is in, so a repo in one registry alone gets that registry's items alone.

    Args:
        kit_registry: the parsed kit registry
        scripts_registry: the parsed scripts registry

    Returns:
        list[dict]: the entries, in the scripts registry's order then the kit registry's
    """
    merged: dict[str, dict] = {}
    for registry, flag in ((scripts_registry, "_scripts"), (kit_registry, "_kit")):
        for entry in registry.get("repos", []):
            name = entry["repo"]
            if name not in merged:
                merged[name] = {"repo": name, "branch": entry.get("branch", "main")}
            merged[name].update({key: value for key, value in entry.items() if key not in ("repo", "branch")})
            merged[name][flag] = True
    return list(merged.values())


def kit_items(token: str, entry: dict, files: list[str]) -> list[SyncItem]:
    """
    The kit's items for one repo, its files, plus the AGENTS.md line and the Dependabot limits when the repo's own
    pages need them. A repo without AGENTS.md or dependabot.yml gets neither written.

    Args:
        token: a GitHub token that reads the repo
        entry: the merged repo entry
        files: the kit files

    Returns:
        list[SyncItem]: the items
    """
    items  = [SyncItem(dest = rel, desired = lambda _remote, content = dk._read_local(rel): content) for rel in files]
    repo   = entry["repo"]
    branch = entry.get("branch", "main")
    if dk.agents_line_missing(token, repo, branch):
        items.append(SyncItem(dest = dk.AGENTS_FILE, desired = lambda text: dk.insert_ecosystem_line(text or "")))
    if dk.dependabot_due(token, repo, branch):
        items.append(SyncItem(dest = dk.DEPENDABOT_FILE, desired = lambda text: dk.limit_dependabot_prs(text or "")))
    return items


def pretested_for(entry: dict, files: list[str], scripts_registry: dict) -> set[str]:
    """
    The union of the two allowlists for one repo (D-047).

    Args:
        entry: the merged repo entry
        files: the kit files
        scripts_registry: the parsed scripts registry

    Returns:
        set[str]: the exact paths this repo's sync may change without running CI
    """
    allow: set[str] = set()
    if entry.get("_kit"):
        allow |= dk.pretested_paths(files)
    if entry.get("_scripts"):
        allow |= ds.pretested_dests(scripts_registry, entry)
    return allow

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    """
    Parse the CLI arguments.

    Returns:
        argparse.Namespace: mode, repos
    """
    parser = argparse.ArgumentParser(description = "Check or distribute the kit and the dev scripts together.")
    parser.add_argument("mode", choices = ["check", "distribute"], help = "'check' opens nothing.")
    parser.add_argument("--repos", default = None, help = "Comma separated EXACT repo names, blank for all.")
    return parser.parse_args()


def main() -> None:
    """
    Run the selected mode across both registries and exit with its status code.

    Returns:
        None
    """
    args             = parse_cli_args()
    kit_registry     = dk._load_registry()
    scripts_registry = ds._load_registry()
    dk._assert_version_consistency()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    kit_version     = dk._kit_version()
    scripts_version = ds._scripts_version()
    files           = kit_registry.get("files", [])
    repos           = _select_repos({"repos": merged_entries(kit_registry, scripts_registry)}, args.repos)


    def items_for(entry: dict) -> list[SyncItem]:
        """
        Build one repo's items from both sets.

        Args:
            entry: the merged repo entry

        Returns:
            list[SyncItem]: the items
        """
        items = kit_items(token, entry, files) if entry.get("_kit") else []
        if entry.get("_scripts"):
            items += ds._build_items(scripts_registry, None, entry)
        return items


    if args.mode == "check":
        banner = f"Checking kit {kit_version} and dev scripts {scripts_version} across {len(repos)} repo(s):"
        sys.exit(run_check(token, repos, items_for, banner))
    print(f"Distributing kit {kit_version} and dev scripts {scripts_version} to {len(repos)} repo(s):")
    sys.exit(
        run_distribute(
            token,
            repos,
            items_for,
            sync_branch = f"{SYNC_BRANCH_PREFIX}kit-{kit_version}-scripts-{scripts_version}",
            pr_title = f"chore(sync): kit {kit_version} and dev scripts {scripts_version}",
            pr_body_fn = lambda drift: _PR_BODY_TEMPLATE.format(
                kit = kit_version,
                scripts = scripts_version,
                items = ", ".join(item.dest for item in drift),
            ) + (f"\n\n{dk.DEPENDABOT_NOTE}" if any(item.dest == dk.DEPENDABOT_FILE for item in drift) else ""),
            commit_msg_fn = lambda item: (
                f"chore(sync): remove superseded {item.dest} (kit {kit_version}, scripts {scripts_version})"
                if item.desired is None
                else f"chore(sync): sync {item.dest} (kit {kit_version}, scripts {scripts_version})"
            ),
            pretested = lambda entry: pretested_for(entry, files, scripts_registry),
        )
    )


if __name__ == "__main__":
    main()
