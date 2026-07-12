"""
Unit tests for scripts/provision_projects.py.

All network I/O (the module-level _SESSION) is mocked; selection, diffing, auth-fallback, and
mode orchestration are tested directly. check mode must NEVER mutate; execute mutations must be
guarded by the existence reads (idempotency).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import provision_projects as pp

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    return {
        "status_options": ["Inbox", "Triage", "Done"],
        "standard_fields": {
            "Priority": ["P0", "P1"],
            "Type": ["Bug", "Feature"],
            "Severity": ["Critical", "Minor"],
        },
        "boards": [
            {
                "key": "fitness",
                "title": "KDF — Fitness",
                "existing_node_id": None,
                "repos": ["Needless2Say/fitness-app-frontend", "Needless2Say/fitness-app-backend"],
                "collaborators": [],
            },
            {
                "key": "infra",
                "title": "KDF — Infra",
                "existing_node_id": "PVT_pinned123",
                "repos": ["Needless2Say/kriegerdataforge-cicd"],
                "collaborators": [{"login": "somefriend", "role": "WRITER"}],
            },
        ],
    }


def _gql_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": data}
    return resp


# ── The real registry file ───────────────────────────────────────────────────────


def test_real_registry_is_valid():
    """The committed registry parses, has 6 unique boards, and every repo is owner-qualified."""
    reg = json.loads(
        (Path(pp.__file__).parent / "projects_registry.json").read_text(encoding="utf-8")
    )
    boards = reg["boards"]
    assert len(boards) == 6
    keys = [b["key"] for b in boards]
    titles = [b["title"] for b in boards]
    assert len(set(keys)) == len(keys)
    assert len(set(titles)) == len(titles)
    for board in boards:
        assert board["repos"], f"board {board['key']} has no repos"
        for repo in board["repos"]:
            assert repo.startswith("Needless2Say/"), repo
    # The standard field schema the epic promises (Repo is derived per board, not listed).
    assert set(reg["standard_fields"]) == {"Priority", "Type", "Severity"}
    assert reg["status_options"][0] == "Inbox"  # AI reporter's landing status (v0.2.0 field-set)


def test_real_registry_covers_every_kit_repo_exactly_once():
    """Board membership must partition the ecosystem: every kit-synced repo on exactly one board
    (+ cicd itself, which the kit registry excludes as the source)."""
    reg = json.loads(
        (Path(pp.__file__).parent / "projects_registry.json").read_text(encoding="utf-8")
    )
    board_repos = [r for b in reg["boards"] for r in b["repos"]]
    assert len(board_repos) == len(set(board_repos)), "a repo appears on two boards"
    kit = json.loads((Path(pp.__file__).parent / "kit_registry.json").read_text(encoding="utf-8"))
    kit_repos = {entry["repo"] for entry in kit["repos"]}
    kit_repos.add("Needless2Say/kriegerdataforge-cicd")  # sync-excluded source repo
    missing = kit_repos - set(board_repos)
    # The two new package repos may join the kit registry in a later wave; boards must already
    # carry them, so only assert the boards-side superset.
    assert not missing, f"kit repos missing from every board: {sorted(missing)}"


# ── Selection ───────────────────────────────────────────────────────────────────


def test_select_boards_all(registry):
    assert pp._select_boards(registry, None) == registry["boards"]
    assert pp._select_boards(registry, "") == registry["boards"]
    assert pp._select_boards(registry, "ALL") == registry["boards"]


def test_select_boards_exact_key_and_title(registry):
    assert [b["key"] for b in pp._select_boards(registry, "fitness")] == ["fitness"]
    assert [b["key"] for b in pp._select_boards(registry, "kdf — infra")] == ["infra"]


def test_select_boards_is_exact_not_substring(registry):
    with pytest.raises(SystemExit):
        pp._select_boards(registry, "fit")


def test_repo_field_options_are_short_names(registry):
    assert pp._repo_field_options(registry["boards"][0]) == [
        "fitness-app-frontend",
        "fitness-app-backend",
    ]


def test_target_fields_merges_standard_plus_derived_repo(registry):
    fields = pp._target_fields(registry, registry["boards"][0])
    assert set(fields) == {"Priority", "Type", "Severity", "Repo"}
    assert fields["Repo"] == ["fitness-app-frontend", "fitness-app-backend"]


# ── GraphQL plumbing + auth fallback ─────────────────────────────────────────────


def test_gql_raises_auth_error_on_http_401_403():
    for code in (401, 403):
        resp = MagicMock()
        resp.status_code = code
        resp.text = "denied"
        with patch.object(pp._SESSION, "post", return_value=resp):
            with pytest.raises(pp.ProjectsAuthError):
                pp._gql("tok", "query { x }")


def test_gql_raises_auth_error_on_graphql_forbidden():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"errors": [{"type": "FORBIDDEN", "message": "no projects for you"}]}
    with patch.object(pp._SESSION, "post", return_value=resp):
        with pytest.raises(pp.ProjectsAuthError):
            pp._gql("tok", "query { x }")


def test_gql_raises_runtime_on_other_graphql_errors():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"errors": [{"type": "NOT_FOUND", "message": "nope"}]}
    with patch.object(pp._SESSION, "post", return_value=resp):
        with pytest.raises(RuntimeError):
            pp._gql("tok", "query { x }")


def test_resolve_token_prefers_primary():
    with patch.object(pp, "_gql", return_value={"user": {"projectsV2": {"totalCount": 0}}}) as gql:
        token, label = pp._resolve_token("app-token", "pat", "Needless2Say")
    assert token == "app-token"
    assert "primary" in label
    assert gql.call_count == 1


def test_resolve_token_falls_back_on_auth_refusal():
    calls = {"n": 0}

    def probe(token, query, variables=None):
        calls["n"] += 1
        if token == "app-token":
            raise pp.ProjectsAuthError("insufficient")
        return {"user": {"projectsV2": {"totalCount": 0}}}

    with patch.object(pp, "_gql", side_effect=probe):
        token, label = pp._resolve_token("app-token", "classic-pat", "Needless2Say")
    assert token == "classic-pat"
    assert "fallback" in label
    assert calls["n"] == 2


def test_resolve_token_exits_with_guidance_when_no_fallback():
    with patch.object(pp, "_gql", side_effect=pp.ProjectsAuthError("insufficient")):
        with pytest.raises(SystemExit) as exc:
            pp._resolve_token("app-token", "", "Needless2Say")
    assert "SECRET_VALUE_NEW" in str(exc.value)


def test_probe_requests_project_fields_not_just_totalcount():
    """Live-caught regression (2026-07-12): GitHub answers projectsV2.totalCount even WITHOUT the
    read:project scope, so a totalCount-only probe false-positives and the run then dies mid-
    flight. The probe must request real project fields (nodes { id })."""
    captured: dict = {}

    def fake_gql(token, query, variables=None):
        captured["query"] = query
        return {"user": {"projectsV2": {"nodes": []}}}

    with patch.object(pp, "_gql", side_effect=fake_gql):
        pp._resolve_token("tok", "", "Needless2Say")
    assert "nodes" in captured["query"] and "id" in captured["query"]
    assert "totalCount" not in captured["query"]


def test_mid_run_auth_error_propagates_not_aggregated(registry):
    """A ProjectsAuthError inside the per-board loop must escape (every board fails identically —
    one guidance message beats six aggregated errors), unlike ordinary per-board errors."""
    with (
        patch.object(pp, "_list_projects", return_value={"KDF — Fitness": {"id": "PVT_a"}}),
        patch.object(pp, "_get_project_state", side_effect=pp.ProjectsAuthError("scope")),
    ):
        with pytest.raises(pp.ProjectsAuthError):
            pp.cmd_check(registry, "tok", "Needless2Say", "fitness")


# ── Diffing ─────────────────────────────────────────────────────────────────────


def _converged_state(registry, board):
    fields = {
        name: {"id": f"F_{name}", "dataType": "SINGLE_SELECT", "options": list(options)}
        for name, options in pp._target_fields(registry, board).items()
    }
    fields["Status"] = {
        "id": "F_Status",
        "dataType": "SINGLE_SELECT",
        "options": list(registry["status_options"]),
    }
    return {
        "id": "PVT_x",
        "title": board["title"],
        "fields": fields,
        "linked_repos": set(board["repos"]),
    }


def test_diff_board_converged_is_empty(registry):
    board = registry["boards"][0]
    assert pp._diff_board(registry, board, _converged_state(registry, board)) == []


def test_diff_board_reports_missing_field_and_option_and_link(registry):
    board = registry["boards"][0]
    state = _converged_state(registry, board)
    del state["fields"]["Severity"]
    state["fields"]["Priority"]["options"].remove("P1")
    state["fields"]["Status"]["options"].remove("Triage")
    state["linked_repos"].discard("Needless2Say/fitness-app-backend")
    drift = pp._diff_board(registry, board, state)
    joined = "\n".join(drift)
    assert "field 'Severity' missing" in joined
    assert "field 'Priority' missing option(s): P1" in joined
    assert "Status missing option(s): Triage" in joined
    assert "Needless2Say/fitness-app-backend" in joined
    assert len(drift) == 4


def test_diff_board_flags_wrong_field_kind(registry):
    board = registry["boards"][0]
    state = _converged_state(registry, board)
    state["fields"]["Type"] = {"id": "F_Type", "dataType": "TEXT", "options": []}
    drift = pp._diff_board(registry, board, state)
    assert any("not SINGLE_SELECT" in line for line in drift)


# ── check mode: read-only + aggregation ─────────────────────────────────────────


def test_cmd_check_never_mutates(registry):
    """check must not call any mutation helper even when boards are missing or drifted."""
    infra_state = _converged_state(registry, registry["boards"][1])
    with (
        patch.object(pp, "_list_projects", return_value={}),
        patch.object(pp, "_get_project_state", return_value=infra_state),
        patch.object(pp, "_create_project") as create,
        patch.object(pp, "_create_single_select_field") as create_field,
        patch.object(pp, "_link_repo") as link,
        patch.object(pp, "_invite_collaborators") as invite,
    ):
        rc = pp.cmd_check(registry, "tok", "Needless2Say", None)
    assert rc == 1  # fitness board missing = drift (infra resolves via its pinned node id)
    create.assert_not_called()
    create_field.assert_not_called()
    link.assert_not_called()
    invite.assert_not_called()


def test_cmd_check_converged_returns_zero(registry):
    boards = registry["boards"]
    states = {b["title"]: _converged_state(registry, b) for b in boards}
    by_title = {b["title"]: {"id": states[b["title"]]["id"], "number": 1} for b in boards}

    with (
        patch.object(pp, "_list_projects", return_value=by_title),
        patch.object(pp, "_get_project_state", side_effect=lambda t, pid: states[
            next(b["title"] for b in boards if (b.get("existing_node_id") or by_title[b["title"]]["id"]) == pid)
        ]),
    ):
        # the pinned infra board resolves by node id, the fitness board by title
        rc = pp.cmd_check(registry, "tok", "Needless2Say", None)
    assert rc == 0


def test_cmd_check_aggregates_per_board_errors(registry):
    with (
        patch.object(pp, "_list_projects", return_value={"KDF — Fitness": {"id": "PVT_a"}}),
        patch.object(pp, "_get_project_state", side_effect=RuntimeError("boom")),
    ):
        rc = pp.cmd_check(registry, "tok", "Needless2Say", "fitness")
    assert rc == 1


# ── execute mode: guarded mutations + idempotency ────────────────────────────────


def test_cmd_execute_creates_only_whats_missing(registry):
    """Fitness board missing entirely -> created + fields + links; pinned infra board converged
    -> adopted with zero mutations. Proves the existence-guarded idempotency contract."""
    boards = registry["boards"]
    infra_state = _converged_state(registry, boards[1])
    infra_state["id"] = "PVT_pinned123"
    created_state = _converged_state(registry, boards[0])
    created_state["fields"] = {  # newly created project: only built-in Status exists
        "Status": {"id": "F_S", "dataType": "SINGLE_SELECT", "options": registry["status_options"]}
    }
    created_state["linked_repos"] = set()
    final_fitness = _converged_state(registry, boards[0])

    def state_for(token, pid):
        if pid == "PVT_pinned123":
            return infra_state
        # first read after create: bare; the post-reconcile drift re-read: converged
        return created_state if state_for.first else final_fitness

    state_for.first = True

    def get_state(token, pid):
        result = state_for(token, pid)
        if pid != "PVT_pinned123":
            state_for.first = False
        return result

    with (
        patch.object(pp, "_owner_node_id", return_value="U_owner"),
        patch.object(pp, "_list_projects", return_value={}),
        patch.object(pp, "_create_project", return_value="PVT_new") as create,
        patch.object(pp, "_get_project_state", side_effect=get_state),
        patch.object(pp, "_create_single_select_field") as create_field,
        patch.object(pp, "_repo_node_id", side_effect=lambda t, r: f"R_{r}"),
        patch.object(pp, "_link_repo") as link,
        patch.object(pp, "_invite_collaborators", return_value=[]) as invite,
    ):
        rc = pp.cmd_execute(registry, "tok", "Needless2Say", None)

    assert rc == 0
    create.assert_called_once_with("tok", "U_owner", "KDF — Fitness")  # infra never re-created
    # 4 custom fields created on the new board only (Priority/Type/Severity/Repo).
    assert create_field.call_count == 4
    assert {c.args[2] for c in create_field.call_args_list} == {"Priority", "Type", "Severity", "Repo"}
    # 2 fitness repos linked; infra already linked.
    assert link.call_count == 2
    assert invite.call_count == 2  # called per board (infra's list has one entry, fitness's empty)


def test_cmd_execute_collaborator_failure_is_warning_not_error(registry):
    """An updateProjectV2Collaborators refusal must not fail the run (user-owned support varies)."""
    board = registry["boards"][1]
    state = _converged_state(registry, board)
    state["id"] = "PVT_pinned123"
    with (
        patch.object(pp, "_owner_node_id", return_value="U_owner"),
        patch.object(pp, "_list_projects", return_value={}),
        patch.object(pp, "_get_project_state", return_value=state),
        patch.object(
            pp, "_invite_collaborators", return_value=["collaborator 'somefriend' not invited via API (x)"]
        ),
    ):
        rc = pp.cmd_execute(registry, "tok", "Needless2Say", "infra")
    assert rc == 0


def test_cmd_execute_aggregates_board_failures(registry):
    with (
        patch.object(pp, "_owner_node_id", return_value="U_owner"),
        patch.object(pp, "_list_projects", return_value={}),
        patch.object(pp, "_create_project", side_effect=RuntimeError("boom")),
    ):
        rc = pp.cmd_execute(registry, "tok", "Needless2Say", "fitness")
    assert rc == 1


def test_invite_collaborators_catches_and_warns():
    with patch.object(pp, "_gql", side_effect=pp.ProjectsAuthError("user projects unsupported")):
        warnings = pp._invite_collaborators("tok", "PVT_x", [{"login": "friend", "role": "WRITER"}])
    assert len(warnings) == 1
    assert "friend" in warnings[0]
    assert "UI" in warnings[0]
