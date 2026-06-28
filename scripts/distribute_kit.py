"""
Check and distribute the agentic-workflow kit (skills.md, WORKFLOW.md, docs/agent/*) from the
canonical source in kriegerdataforge-cicd/kit/common/ to every consumer repo in
scripts/kit_registry.json.

The kit is language-agnostic Markdown vendored byte-identical across the ecosystem. This script is
the propagation engine (see ADR D-001 / kriegerdataforge/docs/epics/agent-kit-distribution.md):
ONE source of truth (kit/common), ONE registry (kit_registry.json), owner-gated PRs.

Modes:
  check       Read-only. For each repo + kit file, fetch the repo's copy via the GitHub Contents
              API and compare it to kit/common/. Prints a drift report and exits non-zero if any
              repo is out of sync. Used by the scheduled drift-alarm workflow; it OPENS NOTHING.
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

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import requests

# ============================================================
# Configuration
# ============================================================

GITHUB_API = "https://api.github.com"
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
REGISTRY_FILE = SCRIPTS_DIR / "kit_registry.json"
KIT_DIR = REPO_ROOT / "kit" / "common"
KIT_VERSION_FILE = REPO_ROOT / "kit" / "KIT_VERSION"

# ============================================================
# Helpers
# ============================================================


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _kit_version() -> str:
    if KIT_VERSION_FILE.is_file():
        return KIT_VERSION_FILE.read_text(encoding="utf-8").strip()
    return "unknown"


def _read_local(rel_path: str) -> str:
    return (KIT_DIR / rel_path).read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    """Compare on content only, ignoring CRLF/LF line-ending differences."""
    return text.replace("\r\n", "\n")


def _select_files(registry: dict, only: str | None) -> list[str]:
    files: list[str] = registry.get("files", [])
    if only:
        files = [f for f in files if only in f]
        if not files:
            sys.exit(f"Error: --only '{only}' matched no files in the registry.")
    return files


def _select_repos(registry: dict, repos_arg: str | None) -> list[dict]:
    """Filter the registry's repos to those named in --repos.

    --repos is a comma-separated list of names. A registry entry matches a name if the name
    **equals** its full ``owner/repo`` or its short name (case-insensitive) — an **exact** match,
    not a substring, so one name never fans out to siblings (e.g. ``kriegerdataforge`` selects only
    the hub, not ``kriegerdataforge-sdk``). An empty/absent value selects ALL repos. No match is an
    error. To target several repos, list them: ``--repos tiffanys-space,tiffanys-space-backend``.
    """
    repos: list[dict] = registry.get("repos", [])
    if not repos_arg:
        return repos
    tokens = {t.strip().lower() for t in repos_arg.split(",") if t.strip()}
    if not tokens:
        return repos
    selected = [
        entry
        for entry in repos
        if entry["repo"].lower() in tokens
        or entry["repo"].split("/", 1)[-1].lower() in tokens
    ]
    if not selected:
        sys.exit(f"Error: --repos '{repos_arg}' matched no repos in the registry (names are exact).")
    return selected


def _get_remote_file(
    token: str,
    owner_repo: str,
    branch: str,
    path: str,
) -> tuple[str | None, str | None]:
    """Return (content, blob_sha) for a file on a branch, or (None, None) if it does not exist."""
    owner, repo = owner_repo.split("/", 1)
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_github_headers(token),
        params={"ref": branch},
        timeout=30,
    )
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def compute_drift(token: str, owner_repo: str, branch: str, files: list[str]) -> list[str]:
    """Return the kit files whose repo copy differs from kit/common (or is missing)."""
    drifted: list[str] = []
    for rel in files:
        local = _normalize(_read_local(rel))
        remote, _sha = _get_remote_file(token, owner_repo, branch, rel)
        if remote is None or _normalize(remote) != local:
            drifted.append(rel)
    return drifted


# ============================================================
# Distribute helpers (Contents + Git refs API)
# ============================================================


def _get_branch_sha(token: str, owner_repo: str, branch: str) -> str:
    owner, repo = owner_repo.split("/", 1)
    resp = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{branch}",
        headers=_github_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


def _create_branch(token: str, owner_repo: str, new_branch: str, base_sha: str) -> None:
    owner, repo = owner_repo.split("/", 1)
    resp = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/refs",
        headers=_github_headers(token),
        json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
        timeout=30,
    )
    if resp.status_code == 422:  # ref already exists — reuse it
        return
    resp.raise_for_status()


def _put_file(
    token: str,
    owner_repo: str,
    branch: str,
    path: str,
    content: str,
    blob_sha: str | None,
    message: str,
) -> None:
    owner, repo = owner_repo.split("/", 1)
    body: dict[str, str] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": branch,
    }
    if blob_sha:
        body["sha"] = blob_sha
    resp = requests.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=_github_headers(token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()


def _create_pr(
    token: str,
    owner_repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
) -> str:
    owner, repo = owner_repo.split("/", 1)
    resp = requests.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
        headers=_github_headers(token),
        json={"title": title, "head": head, "base": base, "body": body},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]


# ============================================================
# Modes
# ============================================================


def cmd_check(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """Read-only drift report. Exit 1 if any repo is out of sync or errored."""
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version = _kit_version()
    print(f"Checking agentic-workflow kit {version} across {len(repos)} repo(s), {len(files)} file(s):")

    any_drift = False
    errors: list[str] = []
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_drift(token, repo, branch, files)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: ERROR — {exc}")
            errors.append(f"{repo}: {exc}")
            continue
        if drift:
            any_drift = True
            print(f"  {repo}: DRIFT ({len(drift)}): {', '.join(drift)}")
        else:
            print(f"  {repo}: in sync")

    print()
    if errors:
        print(f"{len(errors)} repo(s) errored.")
        return 1
    if any_drift:
        print("Drift detected. Run 'distribute' to open sync PRs.")
        return 1
    print("All repos in sync.")
    return 0


def cmd_distribute(registry: dict, token: str, only: str | None, repos_arg: str | None = None) -> int:
    """Open one sync PR per drifted repo. Never auto-merges."""
    files = _select_files(registry, only)
    repos: list[dict] = _select_repos(registry, repos_arg)
    version = _kit_version()
    sync_branch = f"chore/kit-sync-{version}"
    title = f"chore(kit): sync agentic-workflow kit {version}"

    opened: list[str] = []
    errors: list[str] = []
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
                _remote, blob_sha = _get_remote_file(token, repo, sync_branch, rel)
                _put_file(
                    token, repo, sync_branch, rel, _read_local(rel), blob_sha,
                    f"chore(kit): sync {rel} to {version}",
                )
            body = (
                f"Automated sync of the agentic-workflow kit to **{version}** from "
                f"`kriegerdataforge-cicd/kit/common/`.\n\n"
                f"Files updated: {', '.join(drift)}\n\n"
                f"Docs-only. See ADR D-001 / the kit-distribution epic. Please review and merge."
            )
            url = _create_pr(token, repo, sync_branch, branch, title, body)
            print(f"  {repo}: PR opened — {url}")
            opened.append(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: FAILED — {exc}")
            errors.append(f"{repo}: {exc}")

    print()
    print(f"Opened {len(opened)} PR(s).")
    if errors:
        print(f"{len(errors)} repo(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or distribute the agentic-workflow kit across the ecosystem.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Read-only drift report across all repos (scheduled drift alarm)\n"
            "  GH_TOKEN=... python distribute_kit.py check\n\n"
            "  # Open sync PRs for skills.md only (v1 scope)\n"
            "  GH_TOKEN=... python distribute_kit.py distribute --only skills.md\n\n"
            "  # Target a subset of repos (comma-separated names/substrings); blank = all\n"
            "  GH_TOKEN=... python distribute_kit.py distribute --repos kriegerdataforge-sdk,fitness-app-backend"
        ),
    )
    parser.add_argument(
        "mode",
        choices=["check", "distribute"],
        help="'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Only operate on kit files whose path contains this substring (e.g. 'skills.md').",
    )
    parser.add_argument(
        "--repos",
        default=None,
        help=(
            "Only operate on these repos (comma-separated EXACT names, e.g. "
            "'kriegerdataforge-sdk,fitness-app-backend'). Matches the full owner/repo or the short "
            "name exactly (not a substring). Blank = all repos in the registry."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_cli_args()
    registry = _load_registry()
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    if args.mode == "check":
        sys.exit(cmd_check(registry, token, args.only, args.repos))
    else:
        sys.exit(cmd_distribute(registry, token, args.only, args.repos))


if __name__ == "__main__":
    main()
