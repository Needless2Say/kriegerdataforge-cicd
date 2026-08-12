"""
Generic file-sync engine for ecosystem distribution scripts.

Extracted from ``distribute_kit.py`` so every "keep file X identical across the
ecosystem" feature shares ONE GitHub Contents/Refs API layer and ONE fan-out
loop, instead of growing per-feature copies (the copy-drift disease these
distributors exist to cure). Current consumers:

  - ``distribute_kit.py``     — agentic-workflow kit sync (ADR D-001). It keeps
    its own check/distribute loops (its white-box tests patch names on the dk
    module) but imports the HTTP helpers from here, so the transport layer —
    session, retries, Contents API quirks — lives in exactly one place.
  - ``distribute_scripts.py`` — ecosystem dev-script sync (ADR D-013). Uses the
    generic ``SyncItem`` loops below.

A sync target is a ``SyncItem``: a destination path in the target repo plus a
``desired(remote_text)`` callable that returns the content the file SHOULD have.
Whole-file items ignore ``remote_text`` and return the canonical copy; patch
items (e.g. the Makefile recipe rewrite) transform the repo's current content
and raise ``PatchError`` when the content is unpatchable. A ``PatchError`` marks
the repo NEEDS MANUAL ATTENTION without aborting the fan-out.

check mode reports drift and opens nothing; distribute mode opens one
review-gated PR per drifted repo and NEVER auto-merges.
"""

from __future__ import annotations

# standard imports
import base64
import sys
from dataclasses import dataclass
from typing import Callable

# third party imports
from common.http import build_session

# ======================================================================================================================
# Configuration
# ======================================================================================================================

GITHUB_API = "https://api.github.com"

# shared HTTP session with retry/backoff so a transient GitHub 5xx / 429 / DNS blip
# doesn't abort a repo mid-fan-out. Config + rationale live in common/http.py.
# Retries idempotent methods (GET/PUT) only.
_SESSION = build_session()

# ======================================================================================================================
# Sync-item model
# ======================================================================================================================

class PatchError(RuntimeError):
    """
    A patch-style SyncItem could not be applied to the repo's current content
    (e.g. the anchor the patch rewrites is missing). The repo needs a human.
    """


@dataclass
class SyncItem:
    """
    One file to keep in sync in a target repo.

    ``desired`` receives the repo's current content for ``dest`` (None if the
    file does not exist there) and returns the content it should have.
    Whole-file items ignore the argument; patch items transform it and raise
    ``PatchError`` when they cannot. ``desired = None`` means the file must NOT
    exist (a delete item, e.g. a superseded path after a layout move).
    """
    dest: str
    desired: Callable[[str | None], str] | None

# ======================================================================================================================
# GitHub API helpers (Contents + Git refs)
# ======================================================================================================================

def _github_headers(token: str) -> dict[str, str]:
    """
    Build the standard GitHub REST headers for every API call.

    Args:
        token: GitHub token used as the Bearer credential

    Returns:
        dict[str, str]: Authorization/Accept/API-version request headers
    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_remote_file(
    token: str,
    owner_repo: str,
    branch: str,
    path: str,
) -> tuple[str | None, str | None]:
    """
    Fetch a file's content and blob sha from a branch via the Contents API.

    Args:
        token: GitHub token (contents:read)
        owner_repo: full ``owner/repo`` slug
        branch: branch to read from
        path: repo-relative file path

    Returns:
        tuple[str | None, str | None]: (content, blob_sha), or (None, None) if the file does not exist
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers = _github_headers(token),
        params = {"ref": branch},
        timeout = 30,
    )
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data    = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def _get_branch_sha(token: str, owner_repo: str, branch: str) -> str:
    """
    Resolve a branch name to its current commit sha.

    Args:
        token: GitHub token (contents:read)
        owner_repo: full ``owner/repo`` slug
        branch: branch name to resolve

    Returns:
        str: the commit sha the branch currently points at
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{branch}",
        headers = _github_headers(token),
        timeout = 30,
    )
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


def _create_branch(token: str, owner_repo: str, new_branch: str, base_sha: str) -> None:
    """
    Create a branch at the given sha; an already-existing branch is reused silently.

    Args:
        token: GitHub token (contents:write)
        owner_repo: full ``owner/repo`` slug
        new_branch: branch name to create
        base_sha: commit sha the new branch starts from

    Returns:
        None
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/refs",
        headers = _github_headers(token),
        json = {"ref": f"refs/heads/{new_branch}", "sha": base_sha},
        timeout = 30,
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
    """
    Create or update one file on a branch via the Contents API (an upsert).

    Args:
        token: GitHub token (contents:write)
        owner_repo: full ``owner/repo`` slug
        branch: branch to commit to
        path: repo-relative file path
        content: full new file content
        blob_sha: current blob sha when updating an existing file, None when creating
        message: commit message

    Returns:
        None
    """
    owner, repo = owner_repo.split("/", 1)
    body: dict[str, str] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": branch,
    }
    if blob_sha:
        body["sha"] = blob_sha
    resp = _SESSION.put(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers = _github_headers(token),
        json = body,
        timeout = 30,
    )
    resp.raise_for_status()


def _delete_file(
    token: str,
    owner_repo: str,
    branch: str,
    path: str,
    blob_sha: str,
    message: str,
) -> None:
    """
    Delete one file on a branch via the Contents API.

    Not retried on status (same policy as POST: a 502 GitHub already processed
    must not replay); the caller treats a 404 as already-deleted.

    Args:
        token: GitHub token (contents:write)
        owner_repo: full ``owner/repo`` slug
        branch: branch to commit the deletion to
        path: repo-relative file path
        blob_sha: current blob sha of the file being deleted
        message: commit message

    Returns:
        None
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.delete(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers = _github_headers(token),
        json = {"message": message, "sha": blob_sha, "branch": branch},
        timeout = 30,
    )
    if resp.status_code == 404:  # already gone — idempotent re-run
        return
    resp.raise_for_status()


def _create_pr(
    token: str,
    owner_repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
) -> str:
    """
    Open a pull request.

    Args:
        token: GitHub token (pull-requests:write)
        owner_repo: full ``owner/repo`` slug
        head: source branch of the PR
        base: target branch of the PR
        title: PR title
        body: PR body (Markdown)

    Returns:
        str: the created pull request's html_url
    """
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.post(
        f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
        headers = _github_headers(token),
        json = {"title": title, "head": head, "base": base, "body": body},
        timeout = 30,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]

# ======================================================================================================================
# Shared pure helpers
# ======================================================================================================================

def _normalize(text: str) -> str:
    """
    Normalize text for comparison, ignoring CRLF/LF line-ending differences.

    Args:
        text: raw file content

    Returns:
        str: the content with CRLF collapsed to LF
    """
    return text.replace("\r\n", "\n")


def _select_repos(registry: dict, repos_arg: str | None) -> list[dict]:
    """
    Filter the registry's repos to those named in --repos.

    --repos is a comma-separated list of names. A registry entry matches a name if the name
    **equals** its full ``owner/repo`` or its short name (case-insensitive) — an **exact** match,
    not a substring, so one name never fans out to siblings (e.g. ``kriegerdataforge`` selects only
    the hub, not ``kriegerdataforge-sdk``). An empty/absent value selects ALL repos. No match is an
    error. To target several repos, list them: ``--repos tiffanys-space,tiffanys-space-backend``.

    Args:
        registry: parsed registry JSON with a ``repos`` list
        repos_arg: comma-separated exact repo names, or None/blank for all

    Returns:
        list[dict]: the selected registry repo entries
    """
    repos: list[dict] = registry.get("repos", [])
    if not repos_arg:
        return repos
    names = {name.strip().lower() for name in repos_arg.split(",") if name.strip()}
    if not names:
        return repos
    selected = [
        entry for entry in repos if entry["repo"].lower() in names or entry["repo"].split("/", 1)[-1].lower() in names
    ]
    if not selected:
        sys.exit(f"Error: --repos '{repos_arg}' matched no repos in the registry (names are exact).")
    return selected

# ======================================================================================================================
# Generic fan-out loops (SyncItem consumers)
# ======================================================================================================================

def compute_item_drift(
    token: str,
    owner_repo: str,
    branch: str,
    items: list[SyncItem],
) -> list[SyncItem]:
    """
    Determine which items differ from their desired content in one repo.

    A ``PatchError`` from ``item.desired`` propagates to the caller, which reports
    that repo as needing manual attention.

    Args:
        token: GitHub token (contents:read)
        owner_repo: full ``owner/repo`` slug
        branch: branch whose copies are compared
        items: the sync items to evaluate

    Returns:
        list[SyncItem]: the items whose repo copy differs from the desired content (or is missing)
    """
    drifted: list[SyncItem] = []
    for item in items:
        remote, _sha = _get_remote_file(token, owner_repo, branch, item.dest)
        if item.desired is None:  # delete item: drift iff the file still exists
            if remote is not None:
                drifted.append(item)
            continue
        desired = item.desired(remote)
        if remote is None or _normalize(remote) != _normalize(desired):
            drifted.append(item)
    return drifted


def _resolve_items(
    items: list[SyncItem] | Callable[[dict], list[SyncItem]],
    entry: dict,
) -> list[SyncItem]:
    """
    Resolve the items for one registry repo entry.

    Args:
        items: a static item list, or a callable building the list per repo entry
        entry: the registry repo entry

    Returns:
        list[SyncItem]: the items to evaluate for this repo
    """
    return items(entry) if callable(items) else items


def run_check(
    token: str,
    repos: list[dict],
    items: list[SyncItem] | Callable[[dict], list[SyncItem]],
    banner: str,
) -> int:
    """
    Print a read-only drift report across repos (opens nothing).

    Args:
        token: GitHub token (contents:read)
        repos: registry repo entries to check
        items: the sync items to evaluate per repo (static list, or a callable building them per repo entry)
        banner: heading line printed before the per-repo report

    Returns:
        int: 0 when everything is in sync; 1 on drift, error, or a repo needing manual attention
    """
    print(banner)
    any_drift = False
    errors: list[str] = []
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_item_drift(token, repo, branch, _resolve_items(items, entry))
        except PatchError as exc:
            print(f"  {repo}: NEEDS MANUAL ATTENTION — {exc}")
            errors.append(f"{repo}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: ERROR — {exc}")
            errors.append(f"{repo}: {exc}")
            continue
        if drift:
            any_drift = True
            print(f"  {repo}: DRIFT ({len(drift)}): {', '.join(item.dest for item in drift)}")
        else:
            print(f"  {repo}: in sync")

    print()
    if errors:
        print(f"{len(errors)} repo(s) errored or need manual attention.")
        return 1
    if any_drift:
        print("Drift detected. Run 'distribute' to open sync PRs.")
        return 1
    print("All repos in sync.")
    return 0


def run_distribute(
    token: str,
    repos: list[dict],
    items: list[SyncItem] | Callable[[dict], list[SyncItem]],
    *,
    sync_branch: str,
    pr_title: str,
    pr_body_fn: Callable[[list[SyncItem]], str],
    commit_msg_fn: Callable[[SyncItem], str],
) -> int:
    """
    Open one sync PR per drifted repo. NEVER auto-merges.

    For each drifted item the desired content is recomputed against the SYNC
    BRANCH copy, so re-running against a half-updated ``sync_branch`` stays
    idempotent (and a patch item patches what is actually on that branch).

    Args:
        token: GitHub token (contents + pull-requests write)
        repos: registry repo entries to distribute to
        items: the sync items to evaluate per repo (static list, or a callable building them per repo entry)
        sync_branch: branch name created in each drifted repo
        pr_title: title for every opened PR
        pr_body_fn: builds the PR body from the repo's drifted items
        commit_msg_fn: builds the commit message for one item

    Returns:
        int: 0 when every repo synced or was already in sync; 1 when any repo failed or needs manual attention
    """
    opened: list[str] = []
    errors: list[str] = []
    for entry in repos:
        repo, branch = entry["repo"], entry.get("branch", "main")
        try:
            drift = compute_item_drift(token, repo, branch, _resolve_items(items, entry))
            if not drift:
                print(f"  {repo}: in sync — no PR")
                continue
            base_sha = _get_branch_sha(token, repo, branch)
            _create_branch(token, repo, sync_branch, base_sha)
            for item in drift:
                remote, blob_sha = _get_remote_file(token, repo, sync_branch, item.dest)
                if item.desired is None:  # delete item
                    if remote is not None and blob_sha is not None:
                        _delete_file(token, repo, sync_branch, item.dest, blob_sha, commit_msg_fn(item))
                    continue  # already gone on the sync branch (re-run)
                desired = item.desired(remote)
                if remote is not None and _normalize(remote) == _normalize(desired):
                    continue  # sync branch already carries this item (re-run)
                _put_file(token, repo, sync_branch, item.dest, desired, blob_sha, commit_msg_fn(item))
            url = _create_pr(token, repo, sync_branch, branch, pr_title, pr_body_fn(drift))
            print(f"  {repo}: PR opened — {url}")
            opened.append(url)
        except PatchError as exc:
            print(f"  {repo}: NEEDS MANUAL ATTENTION — {exc}")
            errors.append(f"{repo}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {repo}: FAILED — {exc}")
            errors.append(f"{repo}: {exc}")

    print()
    print(f"Opened {len(opened)} PR(s).")
    if errors:
        print(f"{len(errors)} repo(s) failed or need manual attention:")
        for err in errors:
            print(f"  - {err}")
        return 1
    return 0
