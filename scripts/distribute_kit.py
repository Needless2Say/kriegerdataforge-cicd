"""
Check and distribute the agentic-workflow kit (skills.md, WORKFLOW.md, docs/agent/*) from the
canonical source in kriegerdataforge-cicd/kit/common/ to every consumer repo in
scripts/kit_registry.json.

The kit is language-agnostic Markdown vendored byte-identical across the ecosystem. This script is
the propagation engine (see ADR D-001 / kriegerdataforge/docs/epics/agent-kit-distribution.md):
ONE source of truth (kit/common), ONE registry (kit_registry.json), owner-gated PRs.

Modes:
  check       Read-only. For each repo + kit file, fetch the repo's copy via the GitHub Contents
              API and compare it to kit/common/. Also reports gaps in the repo's own files, the role
              pointer in AGENTS.md and the env standard (ADR D-030). Prints a drift report and exits
              non-zero if any repo is out of sync. Used by the scheduled drift-alarm workflow; it OPENS NOTHING.
  distribute  For each repo that has drifted, create a branch, commit the updated kit files, and
              OPEN a pull request titled "chore(kit): sync agentic-workflow kit <KIT_VERSION>".
              It NEVER auto-merges — the owner reviews and merges. Requires a write-scoped token.

IMPORTANT — version-check: kit-sync PRs are docs-only. Each consumer's version-check workflow must
`paths-ignore` the kit paths (ADR D-001, option B) BEFORE running distribute, or the sync PRs will
fail that gate. distribute opens PRs; it does not bump VERSION.

Requirements:
    pip install requests

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write
              (distribute) on all target repos. Use the CICD_PAT value.

Usage:
    GH_TOKEN=... python distribute_kit.py check
    GH_TOKEN=... python distribute_kit.py check --only skills.md
    GH_TOKEN=... python distribute_kit.py distribute --only skills.md
    # Target a subset of repos (comma-separated exact names); blank = all:
    GH_TOKEN=... python distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend
    GH_TOKEN=... python distribute_kit.py check --repos tiffanys-space,tiffanys-space-backend
"""

from __future__ import annotations

# standard imports
import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

# third party imports
# local imports — the shared sync engine (transport + retry session live there; see
# common/repo_sync.py). Imported INTO this module's namespace on purpose: the
# check/distribute loops below call these module-level names, which keeps them
# patchable as `dk._get_remote_file` etc. in the white-box test suite.
from common.repo_sync import (  # noqa: F401  (re-exported for tests/callers)
    _SESSION,
    _create_branch,
    _create_pr,
    _get_branch_sha,
    _get_remote_file,
    _github_headers,
    _normalize,
    _open_pr_url,
    _put_file,
    _select_repos,
)

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR           = Path(__file__).parent
REPO_ROOT             = SCRIPTS_DIR.parent
REGISTRY_FILE         = SCRIPTS_DIR / "kit_registry.json"
KIT_DIR               = REPO_ROOT / "kit" / "common"
KIT_VERSION_FILE      = REPO_ROOT / "kit" / "KIT_VERSION"
VENDORED_VERSION_FILE = KIT_DIR / "docs" / "agent" / "KIT_VERSION"

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _kit_version() -> str:
    if KIT_VERSION_FILE.is_file():
        return KIT_VERSION_FILE.read_text(encoding = "utf-8").strip()
    return "unknown"


def _assert_version_consistency() -> None:
    """
    The vendored marker (``docs/agent/KIT_VERSION``, synced into every repo) must match the
    canonical ``kit/KIT_VERSION`` — bump both together. Guards against shipping a wrong version.
    """
    if not VENDORED_VERSION_FILE.is_file():
        return
    canonical = _kit_version()
    vendored  = VENDORED_VERSION_FILE.read_text(encoding = "utf-8").strip()
    if vendored != canonical:
        sys.exit(
            f"Error: kit version mismatch — kit/KIT_VERSION={canonical!r} but "
            f"docs/agent/KIT_VERSION={vendored!r}. Bump both together."
        )


def _read_local(rel_path: str) -> str:
    return (KIT_DIR / rel_path).read_text(encoding = "utf-8")


def _select_files(registry: dict, only: str | None) -> list[str]:
    files: list[str] = registry.get("files", [])
    if only:
        files = [f for f in files if only in f]
        if not files:
            sys.exit(f"Error: --only '{only}' matched no files in the registry.")
    return files


def compute_drift(token: str, owner_repo: str, branch: str, files: list[str]) -> list[str]:
    """
    Return the kit files whose repo copy differs from kit/common (or is missing).
    """
    drifted: list[str] = []
    for rel in files:
        local = _normalize(_read_local(rel))
        remote, _sha = _get_remote_file(token, owner_repo, branch, rel)
        if remote is None or _normalize(remote) != local:
            drifted.append(rel)
    return drifted


def _ignores(gitignore: str, name: str) -> bool:
    """
    Whether a root .gitignore ignores a file of this name at the repo root, the last matching line winning as in git.
    Directory rules are skipped, the env files live at the root.

    Args:
        gitignore: The text of the repo's root .gitignore
        name: A file name at the repo root, such as .env.kdf

    Returns:
        True when git would ignore the file
    """
    ignored = False
    for raw in gitignore.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate  = line.startswith("!")
        pattern = (line[1:] if negate else line).lstrip("/")
        if pattern.startswith("**/"):
            pattern = pattern[3:]
        if pattern.endswith("/"):
            continue
        if fnmatch.fnmatchcase(name, pattern):
            ignored = not negate
    return ignored


def compute_gaps(token: str, owner_repo: str, branch: str) -> list[str]:
    """
    Return what a repo's own files still lack of the ecosystem standard. The role pointer in AGENTS.md, and the env
    standard of ADR D-030, a tracked .env.kdf.example and a .gitignore that keeps .env.kdf out of git. These files are
    the repo's own, so check reports a gap and distribute never opens a pull request for one.

    Args:
        token: A GitHub token that reads the repo
        owner_repo: The repo, as owner/name
        branch: The branch to read

    Returns:
        One line per gap, empty when the repo meets the standard
    """
    gaps: list[str] = []
    agents, _sha = _get_remote_file(token, owner_repo, branch, "AGENTS.md")
    if agents is None or "docs/agent/AGENT_ROLES.md" not in agents:
        gaps.append("AGENTS.md lacks the role pointer to docs/agent/AGENT_ROLES.md")
    example, _sha = _get_remote_file(token, owner_repo, branch, ".env.kdf.example")
    if example is None:
        gaps.append("no .env.kdf.example, the env standard of ADR D-030")
    gitignore, _sha = _get_remote_file(token, owner_repo, branch, ".gitignore")
    if gitignore is None or not _ignores(gitignore, ".env.kdf"):
        gaps.append(".gitignore does not ignore .env.kdf")
    return gaps

# ======================================================================================================================
# Modes
# ======================================================================================================================

def cmd_check(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """
    Read-only drift report. Exit 1 if any repo is out of sync or errored.
    """
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version = _kit_version()
    print(f"Checking agentic-workflow kit {version} across {len(repos)} repo(s), {len(files)} file(s):")

    any_drift = False
    any_gap   = False
    errors: list[str] = []
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_drift(token, repo, branch, files)
            gaps  = compute_gaps(token, repo, branch)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: ERROR — {exc}")
            errors.append(f"{repo}: {exc}")
            continue
        if drift:
            any_drift = True
            print(f"  {repo}: DRIFT ({len(drift)}): {', '.join(drift)}")
        if gaps:
            any_gap = True
            print(f"  {repo}: GAPS ({len(gaps)}): {'; '.join(gaps)}")
        if not drift and not gaps:
            print(f"  {repo}: in sync")

    print()
    if errors:
        print(f"{len(errors)} repo(s) errored.")
        return 1
    if any_drift or any_gap:
        if any_drift:
            print("Drift detected. Run 'distribute' to open sync PRs.")
        if any_gap:
            print("Gaps in the repos' own files. Each is fixed in that repo's own pull request, distribute opens none.")
        return 1
    print("All repos in sync.")
    return 0


def cmd_distribute(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """
    Open one sync PR per drifted repo. Never auto-merges.
    """
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version     = _kit_version()
    sync_branch = f"chore/kit-sync-{version}"
    title       = f"chore(kit): sync agentic-workflow kit {version}"

    opened:  list[str]  = []
    already: list[str] = []
    errors:  list[str]  = []
    print(f"Distributing kit {version} ({len(files)} file(s)) to {len(repos)} repo(s):")
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_drift(token, repo, branch, files)
            if not drift:
                print(f"  {repo}: in sync — no PR")
                continue
            base_sha = _get_branch_sha(token, repo, branch)
            _create_branch(token, repo, sync_branch, base_sha)
            for rel in drift:
                remote, blob_sha = _get_remote_file(token, repo, sync_branch, rel)
                content = _read_local(rel)
                if remote is not None and _normalize(remote) == _normalize(content):
                    continue  # the sync branch already carries it, a re-run
                _put_file(
                    token,
                    repo,
                    sync_branch,
                    rel,
                    content,
                    blob_sha,
                    f"chore(kit): sync {rel} to {version}",
                )
            existing = _open_pr_url(token, repo, sync_branch, branch)
            if existing:
                print(f"  {repo}: PR already open — {existing}")
                already.append(existing)
                continue
            body = (
                f"Automated sync of the agentic-workflow kit to **{version}** from "
                f"`kriegerdataforge-cicd/kit/common/`.\n\n"
                f"Files updated: {', '.join(drift)}\n\n"
                f"Docs-only. See ADR D-001 / the kit-distribution epic. Please review and merge."
            )
            url  = _create_pr(token, repo, sync_branch, branch, title, body)
            print(f"  {repo}: PR opened — {url}")
            opened.append(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: FAILED — {exc}")
            errors.append(f"{repo}: {exc}")

    print()
    print(f"Opened {len(opened)} PR(s).")
    if already:
        print(f"{len(already)} PR(s) were already open, their branches are up to date.")
    if errors:
        print(f"{len(errors)} repo(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description = "Check or distribute the agentic-workflow kit across the ecosystem.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n" "  # Read-only drift report across all repos (scheduled drift alarm)\n" "  GH_TOKEN=... python distribute_kit.py check\n\n" "  # Open sync PRs for skills.md only (v1 scope)\n" "  GH_TOKEN=... python distribute_kit.py distribute --only skills.md\n\n" "  # Target a subset of repos (comma-separated EXACT names, not substrings); blank = all\n" "  GH_TOKEN=... python distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend"
        ),
    )
    parser.add_argument(
        "mode",
        choices = ["check", "distribute"],
        help = "'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default = None,
        help = "Only operate on kit files whose path contains this substring (e.g. 'skills.md').",
    )
    parser.add_argument(
        "--repos",
        default = None,
        help = (
            "Only operate on these repos (comma-separated EXACT names, e.g. " "'kriegerdataforge-sdk,fitness-app-backend'). Matches the full owner/repo or the short " "name exactly (not a substring). Blank = all repos in the registry."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args     = parse_cli_args()
    registry = _load_registry()
    _assert_version_consistency()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    if args.mode == "check":
        sys.exit(cmd_check(registry, token, args.only, args.repos))
    else:
        sys.exit(cmd_distribute(registry, token, args.only, args.repos))


if __name__ == "__main__":
    main()
