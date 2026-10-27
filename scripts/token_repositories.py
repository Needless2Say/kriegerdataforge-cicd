"""
The repositories a workflow's App token may reach, for its `repositories:` input, each list read from the same registry
and the same selection the operation itself uses, so the token names every repo the operation acts on and no other
(D-085, design 5.7, row L19). Printed as `repositories=<names>` for `$GITHUB_OUTPUT`, the short names comma joined.

Usage:
    python scripts/token_repositories.py kit [REPOS]          # distribute_kit.py's targets, --repos when given
    python scripts/token_repositories.py scripts [REPOS]      # distribute_scripts.py's targets
    python scripts/token_repositories.py all [REPOS]          # distribute_all.py's targets, both registries merged
    python scripts/token_repositories.py secrets NAMES        # rotate_secret.py's writes for the named secrets
    python scripts/token_repositories.py watch                # ecosystem_watch.py's repos, cicd among them

Standard library only.
"""
from __future__ import annotations

# standard imports
import argparse
import json
import sys
from pathlib import Path

# local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
import distribute_all  # noqa: E402
from common.repo_sync import _select_repos  # noqa: E402

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR = Path(__file__).resolve().parent
CICD_REPO   = "Needless2Say/kriegerdataforge-cicd"

# ======================================================================================================================
# The lists
# ======================================================================================================================

def registry(name: str) -> dict:
    """
    One registry beside this script.

    Args:
        name: its file name

    Returns:
        dict: the parsed registry
    """
    return json.loads((SCRIPTS_DIR / name).read_text(encoding = "utf-8"))


def short(repos: list[str]) -> str:
    """
    The repositories' short names, sorted, unique and comma joined, as the token's input takes them.

    Args:
        repos: owner and name of each

    Returns:
        str: the list
    """
    return ",".join(sorted({repo.split("/", 1)[-1] for repo in repos}))


def sync_targets(kind: str, repos_arg: str | None) -> list[str]:
    """
    The repos a Distribute writes to, its registry's or both merged as distribute_all.py merges them, filtered by
    --repos exactly as repo_sync filters them.

    Args:
        kind: kit, scripts or all
        repos_arg: the --repos value, None or blank for every repo

    Returns:
        list[str]: owner and name of each
    """
    if kind == "all":
        merged ={"repos": distribute_all.merged_entries(registry("kit_registry.json"), registry("scripts_registry.json"))}
        return [entry["repo"] for entry in _select_repos(merged, repos_arg)]
    name = "kit_registry.json" if kind == "kit" else "scripts_registry.json"
    return [entry["repo"] for entry in _select_repos(registry(name), repos_arg)]


def secret_targets(names: str) -> list[str]:
    """
    Every repo rotate_secret.py may write for the named secrets, their environment, repository and retired copies.

    Args:
        names: the secrets, comma or space separated, case as the registry ignores it, or `all` as rotate_secret.py
            takes it for every entry

    Returns:
        list[str]: owner and name of each

    Raises:
        SystemExit: when a name is in no entry of the registry, or none is named
    """
    wanted  = {name.strip().lower() for name in names.replace(",", " ").split() if name.strip()}
    entries = {entry["name"].lower(): entry for entry in registry("secret_registry.json")["secrets"]}
    if wanted == {"all"}:
        wanted = set(entries)
    unknown = sorted(wanted - set(entries))
    if not wanted or unknown:
        raise SystemExit(f"token_repositories: no secret named {', '.join(unknown) or 'at all'}")
    repos = []
    for name in sorted(wanted):
        for key in ("github_env_secrets", "github_repo_secrets", "retired_github_env_secrets"):
            repos += [target["repo"] for target in entries[name].get(key, [])]
    return repos


def watch_targets() -> list[str]:
    """
    The repos the ecosystem watch reads, cicd and every kit target, as ecosystem_watch.read_registries lists them.

    Returns:
        list[str]: owner and name of each
    """
    return [CICD_REPO] + [entry["repo"] for entry in registry("kit_registry.json")["repos"]]


def main(argv: list[str] | None = None) -> int:
    """
    Print one operation's repositories for its App token.

    Args:
        argv: the arguments, sys.argv's by default

    Returns:
        int: 0, a failure exits through SystemExit

    Raises:
        SystemExit: when the list is empty, since the action reads no repositories as every repo the App reaches
    """
    parser = argparse.ArgumentParser(description = "The repositories a workflow's App token may reach (D-085).")
    parser.add_argument("kind", choices = ("kit", "scripts", "all", "secrets", "watch"))
    parser.add_argument("names", nargs = "?", default = "", help = "--repos for a Distribute, the secrets for secrets")
    args = parser.parse_args(argv)
    if args.kind == "secrets":
        repos = secret_targets(args.names)
    elif args.kind == "watch":
        repos = watch_targets()
    else:
        repos = sync_targets(args.kind, args.names or None)
    if not repos:
        raise SystemExit("token_repositories: no repository to reach, so no token is minted")
    print(f"repositories={short(repos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
