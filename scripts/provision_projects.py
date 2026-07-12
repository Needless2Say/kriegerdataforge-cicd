"""
Provision the ecosystem's GitHub Projects v2 boards from scripts/projects_registry.json.

Part of the reports-ecosystem epic (ADR D-010 / docs/design/reports-ecosystem.md): ~6 user-owned
boards (per-app + infra) with a standard field schema (Priority / Type / Repo / Severity + the
built-in Status), each linked to its member repos. The AI bug reporter files issues onto these
boards (fitness-app-backend reports module -> kdf_reports package); developers groom them.

Modes:
  check     Read-only. For each registry board: does it exist (by pinned node id, else exact
            title)? Are the standard fields present with all target options? Are the member repos
            linked? Prints a drift report and exits non-zero on drift. MUTATES NOTHING.
  execute   Creates missing boards (createProjectV2), creates missing custom fields
            (createProjectV2Field, single-select with options), links member repos
            (linkProjectV2ToRepository), best-effort collaborator invites
            (updateProjectV2Collaborators — user-owned support varies; failures are warnings).
            Existing boards are ADOPTED and reconciled, never re-created. Prints the
            title -> node_id map to wire into each app's GH_REPORTS_*PROJECT_ID env.

Deliberate limits (documented in docs/guides/PROJECTS_BOARDS.md):
  * The BUILT-IN Status field's options cannot be reliably reshaped via the API — both modes DIFF
    them against the registry's status_options and report; reconciling is a one-time manual UI step.
  * Option drift on an EXISTING custom field is reported, not auto-fixed (option edits via the API
    risk detaching items' selected values); fix in the UI, then re-run check.
  * Views are not API-creatable — manual recipes live in the guide.

Auth (resolved W1 finding, proven live 2026-07-12):
  A GitHub App installation token can READ a user's ProjectsV2 but CANNOT create/modify them —
  `createProjectV2` on a USER `ownerId` is refused ("does not have permission to create projects").
  So the rule is staged-PAT-FIRST (see _resolve_token):
  GH_TOKEN          The App installation token (the ops workflow mints it). Sufficient for a
                    read-only `check` and for `execute` on an ORG-owned board; on a USER board it
                    can read but every mutation is refused — used only when no PAT is staged.
  GH_TOKEN_FALLBACK Classic PAT (project + repo scopes) the owner stages in the SECRET_VALUE_NEW
                    repo secret for a provisioning run. When present it runs the WHOLE session (it
                    does the writes the App token can't); revoke it + clear the slot afterward.
  PROJECTS_OWNER    Board owner login (defaults to Needless2Say). The engine never relies on the
                    GraphQL `viewer` (App installation tokens have none).

Usage:
    GH_TOKEN=... python provision_projects.py check
    GH_TOKEN=... python provision_projects.py check --boards fitness,tiffanys
    GH_TOKEN=... GH_TOKEN_FALLBACK=... python provision_projects.py execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from common.http import build_session

# ============================================================
# Configuration
# ============================================================

GITHUB_API = "https://api.github.com"
GRAPHQL_API = f"{GITHUB_API}/graphql"
SCRIPTS_DIR = Path(__file__).parent
REGISTRY_FILE = SCRIPTS_DIR / "projects_registry.json"
DEFAULT_OWNER = "Needless2Say"

# Colors for created single-select options (ProjectV2SingleSelectFieldOptionInput requires one).
# Cycled in order; purely cosmetic — drift checks compare option NAMES only.
_OPTION_COLORS: tuple[str, ...] = ("GRAY", "BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PINK", "PURPLE")

# Shared HTTP session (retry/backoff on GET; POSTs — i.e. all GraphQL — are deliberately never
# status-retried: every mutation below is guarded by an existence check, so a failed run is safely
# re-runnable instead of risking a duplicate board/field on a 502-that-succeeded.
_SESSION = build_session()


class ProjectsAuthError(RuntimeError):
    """The token cannot access ProjectsV2 (missing scope/permission)."""


# ============================================================
# Registry + selection
# ============================================================


def _load_registry() -> dict:
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _select_boards(registry: dict, boards_arg: str | None) -> list[dict]:
    """Filter registry boards by --boards (comma-separated EXACT keys or titles; blank/ALL = all).

    Mirrors distribute_kit._select_repos: exact match only, case-insensitive, no substrings —
    one key never fans out to siblings. No match is an error.
    """
    boards: list[dict] = registry.get("boards", [])
    if not boards_arg:
        return boards
    tokens = {t.strip().lower() for t in boards_arg.split(",") if t.strip()}
    if not tokens or "all" in tokens:
        return boards
    selected = [
        b for b in boards if b["key"].lower() in tokens or b["title"].lower() in tokens
    ]
    if not selected:
        sys.exit(f"Error: --boards '{boards_arg}' matched no boards in the registry (keys are exact).")
    return selected


def _repo_field_options(board: dict) -> list[str]:
    """The per-board 'Repo' single-select options: short names of the member repos."""
    return [r.split("/", 1)[-1] for r in board.get("repos", [])]


def _target_fields(registry: dict, board: dict) -> dict[str, list[str]]:
    """The custom single-select fields this board must carry (standard + derived Repo)."""
    fields: dict[str, list[str]] = dict(registry.get("standard_fields", {}))
    fields["Repo"] = _repo_field_options(board)
    return fields


# ============================================================
# GraphQL plumbing
# ============================================================


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict:
    """POST one GraphQL request; raise on transport, HTTP, or GraphQL-level errors.

    A FORBIDDEN / INSUFFICIENT_SCOPES GraphQL error (or HTTP 401/403) raises ProjectsAuthError so
    the caller can fall back to the staged classic PAT with a clear message.
    """
    resp = _SESSION.post(
        GRAPHQL_API,
        headers=_github_headers(token),
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    if resp.status_code in (401, 403):
        raise ProjectsAuthError(f"GraphQL HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()
    payload = resp.json()
    errors = payload.get("errors") or []
    if errors:
        types = {e.get("type", "") for e in errors}
        message = "; ".join(e.get("message", "?") for e in errors)
        if types & {"FORBIDDEN", "INSUFFICIENT_SCOPES"}:
            raise ProjectsAuthError(message)
        raise RuntimeError(f"GraphQL error(s): {message}")
    return payload["data"]


# The auth probe: a cheap READ of the owner's ProjectsV2. Requests project FIELDS (`nodes { id }`),
# never `totalCount` — GitHub answers totalCount even without the read:project scope (verified live
# 2026-07-12), so a totalCount probe would false-positive.
_OWNER_PROJECTS_PROBE = (
    "query($login: String!) { user(login: $login) { projectsV2(first: 1) { nodes { id } } } }"
)


def _resolve_token(primary: str, fallback: str, owner: str) -> tuple[str, str]:
    """Return (token, label): the single token to run this whole session with.

    Auth reality, proven live 2026-07-12 (resolves the epic's W1 open question): a GitHub App
    installation token can READ a user's ProjectsV2 but CANNOT create/modify them —
    ``createProjectV2`` on a USER ``ownerId`` is refused ("does not have permission to create
    projects"). A read-probe therefore cannot predict the *write* refusal, so App-first-then-probe
    (the original design) always committed to the App token and then died at the first mutation —
    the staged fallback was unreachable.

    So the rule is *staged-PAT-first*: if the owner has staged the classic PAT
    (``project`` + ``repo``) in ``SECRET_VALUE_NEW``, use it for the whole run — it does the writes
    the App token can't. Otherwise use the App token: enough for a read-only ``check`` and for
    ``execute`` on an ORG-owned board (Apps *can* write org projects); ``execute`` on a USER board
    without the PAT fails at the first mutation with staged-PAT guidance, which is the correct ask.
    Each candidate is validated with the read-probe here, so a wrong-scoped/expired token fails now
    with clear guidance rather than mid-flight.
    """
    if fallback:
        try:
            _gql(fallback, _OWNER_PROJECTS_PROBE, {"login": owner})
            return fallback, "staged classic PAT (SECRET_VALUE_NEW)"
        except ProjectsAuthError as exc:
            sys.exit(_auth_guidance(exc, staged=True))
    try:
        _gql(primary, _OWNER_PROJECTS_PROBE, {"login": owner})
        return primary, "App installation token"
    except ProjectsAuthError as exc:
        sys.exit(_auth_guidance(exc))


def _auth_guidance(exc: Exception, *, staged: bool = False) -> str:
    """The one message a refused run should end with — printed, never a traceback."""
    if staged:
        return (
            "Error: the staged classic PAT (SECRET_VALUE_NEW) cannot access ProjectsV2 "
            f"({exc}).\nEnsure it is a *classic* PAT with BOTH 'project' and 'repo' scopes and is "
            "not expired, re-stage it in the SECRET_VALUE_NEW repo secret, and re-run."
        )
    return (
        "Error: the token cannot access ProjectsV2 for user-owned boards "
        f"({exc}).\nGitHub App installation tokens can READ but NOT create/modify user-owned "
        "ProjectsV2. Create a short-lived CLASSIC PAT with 'project' + 'repo' scopes, stage it in "
        "the SECRET_VALUE_NEW repo secret, and re-run — the workflow passes it as GH_TOKEN_FALLBACK. "
        "Revoke the PAT (and clear SECRET_VALUE_NEW) after the run."
    )


# ============================================================
# Reads (shared by both modes)
# ============================================================

_PROJECT_FIELDS_FRAGMENT = """
fields(first: 50) {
  nodes {
    ... on ProjectV2FieldCommon { id name dataType }
    ... on ProjectV2SingleSelectField { id name dataType options { id name } }
  }
}
repositories(first: 50) { nodes { nameWithOwner } }
"""


def _owner_node_id(token: str, owner: str) -> str:
    data = _gql(token, "query($login: String!) { user(login: $login) { id } }", {"login": owner})
    return data["user"]["id"]


def _list_projects(token: str, owner: str) -> dict[str, dict]:
    """All of the owner's ProjectsV2 as {title: {id, number, closed}} (first 100 is plenty)."""
    query = """
    query($login: String!) {
      user(login: $login) {
        projectsV2(first: 100) { nodes { id number title closed } }
      }
    }
    """
    nodes = _gql(token, query, {"login": owner})["user"]["projectsV2"]["nodes"]
    return {n["title"]: n for n in nodes}


def _get_project_state(token: str, project_id: str) -> dict:
    """One project's fields (+options) and linked repos."""
    query = f"""
    query($id: ID!) {{
      node(id: $id) {{ ... on ProjectV2 {{ id title {_PROJECT_FIELDS_FRAGMENT} }} }}
    }}
    """
    node = _gql(token, query, {"id": project_id})["node"]
    fields: dict[str, dict] = {}
    for f in node["fields"]["nodes"]:
        if not f:  # non-matching fragment members serialize as empty objects
            continue
        fields[f["name"]] = {
            "id": f["id"],
            "dataType": f.get("dataType"),
            "options": [o["name"] for o in f.get("options", [])],
        }
    linked = {r["nameWithOwner"] for r in node["repositories"]["nodes"]}
    return {"id": node["id"], "title": node["title"], "fields": fields, "linked_repos": linked}


def _find_board(token: str, owner: str, board: dict, projects_by_title: dict[str, dict]) -> str | None:
    """Resolve a registry board to an existing project node id (pinned id wins, else exact title)."""
    pinned = board.get("existing_node_id")
    if pinned:
        return str(pinned)
    hit = projects_by_title.get(board["title"])
    return hit["id"] if hit else None


def _diff_board(registry: dict, board: dict, state: dict) -> list[str]:
    """Human-readable drift lines for one existing board (empty = fully converged)."""
    drift: list[str] = []
    # Custom fields: missing field, wrong kind, or missing options.
    for name, want_options in _target_fields(registry, board).items():
        have = state["fields"].get(name)
        if have is None:
            drift.append(f"field '{name}' missing (want single-select: {', '.join(want_options)})")
            continue
        if have["dataType"] != "SINGLE_SELECT":
            drift.append(f"field '{name}' exists but is {have['dataType']}, not SINGLE_SELECT")
            continue
        missing = [o for o in want_options if o not in have["options"]]
        if missing:
            drift.append(
                f"field '{name}' missing option(s): {', '.join(missing)} (add in the UI — "
                "option edits are not automated)"
            )
    # Built-in Status: report-only diff (see module docstring).
    status = state["fields"].get("Status")
    if status is not None:
        want_status = registry.get("status_options", [])
        missing = [o for o in want_status if o not in status["options"]]
        if missing:
            drift.append(
                f"Status missing option(s): {', '.join(missing)} (built-in field — one-time "
                "manual UI reconcile, see PROJECTS_BOARDS.md)"
            )
    # Linked repos.
    unlinked = [r for r in board.get("repos", []) if r not in state["linked_repos"]]
    if unlinked:
        drift.append(f"repo(s) not linked: {', '.join(unlinked)}")
    return drift


# ============================================================
# Mutations (execute mode only — each guarded by the reads above)
# ============================================================


def _create_project(token: str, owner_id: str, title: str) -> str:
    mutation = """
    mutation($ownerId: ID!, $title: String!) {
      createProjectV2(input: { ownerId: $ownerId, title: $title }) { projectV2 { id } }
    }
    """
    return _gql(token, mutation, {"ownerId": owner_id, "title": title})["createProjectV2"]["projectV2"]["id"]


def _create_single_select_field(token: str, project_id: str, name: str, options: list[str]) -> None:
    mutation = """
    mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
      createProjectV2Field(input: {
        projectId: $projectId, dataType: SINGLE_SELECT, name: $name,
        singleSelectOptions: $options
      }) { projectV2Field { ... on ProjectV2SingleSelectField { id } } }
    }
    """
    option_inputs = [
        {"name": o, "color": _OPTION_COLORS[i % len(_OPTION_COLORS)], "description": ""}
        for i, o in enumerate(options)
    ]
    _gql(token, mutation, {"projectId": project_id, "name": name, "options": option_inputs})


def _repo_node_id(token: str, owner_repo: str) -> str:
    owner, repo = owner_repo.split("/", 1)
    resp = _SESSION.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=_github_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["node_id"]


def _link_repo(token: str, project_id: str, repo_node_id: str) -> None:
    mutation = """
    mutation($projectId: ID!, $repositoryId: ID!) {
      linkProjectV2ToRepository(input: { projectId: $projectId, repositoryId: $repositoryId }) {
        repository { id }
      }
    }
    """
    _gql(token, mutation, {"projectId": project_id, "repositoryId": repo_node_id})


def _invite_collaborators(token: str, project_id: str, collaborators: list[dict]) -> list[str]:
    """Best-effort collaborator invites; returns warning lines instead of raising.

    updateProjectV2Collaborators support for USER-owned projects varies — a refusal here must
    never fail the run (manual UI invite is the documented fallback).
    """
    warnings: list[str] = []
    for collab in collaborators:
        login, role = collab["login"], collab.get("role", "WRITER").upper()
        try:
            user_id = _gql(
                token, "query($login: String!) { user(login: $login) { id } }", {"login": login}
            )["user"]["id"]
            mutation = """
            mutation($projectId: ID!, $collaborators: [ProjectV2Collaborator!]!) {
              updateProjectV2Collaborators(input: { projectId: $projectId, collaborators: $collaborators }) {
                collaborators(first: 1) { totalCount }
              }
            }
            """
            _gql(
                token,
                mutation,
                {"projectId": project_id, "collaborators": [{"userId": user_id, "role": role}]},
            )
        except (ProjectsAuthError, RuntimeError) as exc:
            warnings.append(f"collaborator '{login}' not invited via API ({exc}) — invite in the UI")
    return warnings


# ============================================================
# Modes
# ============================================================


def cmd_check(registry: dict, token: str, owner: str, boards_arg: str | None) -> int:
    """Read-only drift report. Exit 1 on any drift or error. Mutates nothing."""
    boards = _select_boards(registry, boards_arg)
    projects_by_title = _list_projects(token, owner)
    print(f"Checking {len(boards)} board(s) against @{owner}'s ProjectsV2:")

    any_drift = False
    errors: list[str] = []
    for board in boards:
        title = board["title"]
        try:
            project_id = _find_board(token, owner, board, projects_by_title)
            if project_id is None:
                any_drift = True
                print(f"  {title}: MISSING — execute will create it")
                continue
            state = _get_project_state(token, project_id)
            drift = _diff_board(registry, board, state)
        except ProjectsAuthError:
            raise  # auth refusals hit every board identically — fail once with guidance (main)
        except Exception as exc:  # noqa: BLE001 — aggregate per-board, rotate_secret-style
            print(f"  {title}: ERROR — {exc}")
            errors.append(f"{title}: {exc}")
            continue
        if drift:
            any_drift = True
            print(f"  {title}: DRIFT ({len(drift)})  [{project_id}]")
            for line in drift:
                print(f"    - {line}")
        else:
            print(f"  {title}: converged  [{project_id}]")

    print()
    if errors:
        print(f"{len(errors)} board(s) errored.")
        return 1
    if any_drift:
        print("Drift detected. Run 'execute' to create/link (option edits stay manual).")
        return 1
    print("All boards converged.")
    return 0


def cmd_execute(registry: dict, token: str, owner: str, boards_arg: str | None) -> int:
    """Create/adopt boards, create missing fields, link repos, best-effort invites. Idempotent."""
    boards = _select_boards(registry, boards_arg)
    owner_id = _owner_node_id(token, owner)
    projects_by_title = _list_projects(token, owner)
    print(f"Provisioning {len(boards)} board(s) for @{owner}:")

    node_ids: dict[str, str] = {}
    manual_steps: list[str] = []
    errors: list[str] = []
    for board in boards:
        title = board["title"]
        try:
            project_id = _find_board(token, owner, board, projects_by_title)
            if project_id is None:
                project_id = _create_project(token, owner_id, title)
                print(f"  {title}: created  [{project_id}]")
            else:
                print(f"  {title}: adopted existing  [{project_id}]")
            node_ids[title] = project_id

            state = _get_project_state(token, project_id)
            # Custom fields: create the missing ones (existing option drift stays manual).
            for name, options in _target_fields(registry, board).items():
                have = state["fields"].get(name)
                if have is None:
                    _create_single_select_field(token, project_id, name, options)
                    print(f"    + field '{name}' ({len(options)} options)")
            # Link member repos not yet linked.
            for owner_repo in board.get("repos", []):
                if owner_repo not in state["linked_repos"]:
                    _link_repo(token, project_id, _repo_node_id(token, owner_repo))
                    print(f"    + linked {owner_repo}")
            # Best-effort collaborators.
            for warning in _invite_collaborators(token, project_id, board.get("collaborators", [])):
                print(f"    ! {warning}")
                manual_steps.append(f"{title}: {warning}")
            # Surviving drift (Status options, option edits) = the manual to-do list.
            for line in _diff_board(registry, board, _get_project_state(token, project_id)):
                print(f"    ~ manual: {line}")
                manual_steps.append(f"{title}: {line}")
        except ProjectsAuthError:
            raise  # auth refusals hit every board identically — fail once with guidance (main)
        except Exception as exc:  # noqa: BLE001
            print(f"  {title}: FAILED — {exc}")
            errors.append(f"{title}: {exc}")

    print()
    print("Board node ids (wire these into each app's GH_REPORTS_*PROJECT_ID env — not secrets):")
    for title, node_id in node_ids.items():
        print(f"  {title}: {node_id}")
    if manual_steps:
        print(f"\n{len(manual_steps)} manual step(s) remain (see PROJECTS_BOARDS.md):")
        for step in manual_steps:
            print(f"  - {step}")
    if errors:
        print(f"\n{len(errors)} board(s) failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0


# ============================================================
# CLI
# ============================================================


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or provision the ecosystem's GitHub Projects v2 boards.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  GH_TOKEN=... python provision_projects.py check\n"
            "  GH_TOKEN=... python provision_projects.py check --boards fitness,tiffanys\n"
            "  GH_TOKEN=... GH_TOKEN_FALLBACK=... python provision_projects.py execute"
        ),
    )
    parser.add_argument(
        "mode",
        choices=["check", "execute"],
        help="'check' reports drift (mutates nothing). 'execute' creates/links idempotently.",
    )
    parser.add_argument(
        "--boards",
        default=None,
        help="Only operate on these boards (comma-separated EXACT keys or titles). Blank/ALL = all.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_cli_args()
    registry = _load_registry()
    primary = os.environ.get("GH_TOKEN", "").strip()
    if not primary:
        sys.exit("Error: GH_TOKEN environment variable not set.")
    fallback = os.environ.get("GH_TOKEN_FALLBACK", "").strip()
    owner = os.environ.get("PROJECTS_OWNER", DEFAULT_OWNER).strip() or DEFAULT_OWNER

    token, label = _resolve_token(primary, fallback, owner)
    print(f"Token: {label}")

    # A ProjectsAuthError can still surface mid-run (e.g. finer-grained refusals the probe can't
    # anticipate) — end with the same guidance, never a traceback.
    try:
        if args.mode == "check":
            sys.exit(cmd_check(registry, token, owner, args.boards))
        else:
            sys.exit(cmd_execute(registry, token, owner, args.boards))
    except ProjectsAuthError as exc:
        sys.exit(_auth_guidance(exc))


if __name__ == "__main__":
    main()
