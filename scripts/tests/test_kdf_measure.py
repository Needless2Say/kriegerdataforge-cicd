"""
Tests for tools/measure/kdf_measure.py, the measure, a read only account of secrets and rules by name and setting.

Every test runs the module against a fake GitHub that answers each path the way the API does, pages a list the way
the API does, and caps the variables lists at 30 a page as GitHub does. Every field of the fake that holds a value,
a variable's value or a deploy key's public key, holds a canary, and the canaries must never reach the output. The
module is loaded by its path, with bytecode off so no cache lands beside it.
"""

from __future__ import annotations

import functools
import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest

MODULE_PATH        = Path(__file__).resolve().parents[2] / "tools" / "measure" / "kdf_measure.py"
LOGIN              = "OwnerLogin2Name"
CANARY             = "CANARY"
GITHUB_TOKEN_SHAPE = "ghp_" + "A1b2" * 9


@functools.cache
def kdf_measure():
    """
    The measure module, loaded once by its path with bytecode off.
    """
    spec   = importlib.util.spec_from_file_location("kdf_measure", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["kdf_measure"] = module
    written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def joined(*parts: str) -> str:
    """
    One expected line from its parts, joined by spaces, so a long line stays within the line length.
    """
    return " ".join(parts)


class Listed:
    """
    A listed endpoint's items, bare or wrapped under a field with a total_count, served a page at a time.
    """
    def __init__(self, items: list, field: str | None = None, cap: int = 100):
        self.items = items
        self.field = field
        self.cap   = cap


    def page(self, params: dict[str, list[str]]) -> object:
        size   = min(int(params.get("per_page", ["30"])[0]), self.cap)
        number = int(params.get("page", ["1"])[0])
        batch  = self.items[(number - 1) * size:number * size]
        if self.field is None:
            return batch
        return {"total_count": len(self.items), self.field: batch}


class FakeGitHub:
    """
    A fake GitHub API, each path without its query mapped to a body, a Listed, or a (status, body) pair.
    """
    def __init__(self, routes: dict[str, object], scopes: str | None = "gist, read:org, repo, workflow"):
        self.routes = routes
        self.scopes = scopes
        self.calls: list[str] = []


    def __call__(self, path: str) -> object:
        self.calls.append(path)
        response = kdf_measure().Response
        base, _, query = path.partition("?")
        params = parse_qs(query)
        if base not in self.routes:
            return response(status = 404, body = {"message": "Not Found"})
        route = self.routes[base]
        status, body = route if isinstance(route, tuple) else (200, route)
        if isinstance(body, Listed):
            body = body.page(params)
        headers = {"x-oauth-scopes": self.scopes} if base == "user" and self.scopes is not None else {}
        return response(status = status, headers = headers, body = body)


def canary_variables(count: int, prefix: str) -> list[dict]:
    """
    Variables whose values are canaries, as GitHub lists them.
    """
    return [{"name": f"{prefix}_{index:02d}", "value": f"{CANARY}-{prefix}-{index}"} for index in range(count)]


def account_routes() -> dict[str, object]:
    """
    A fake account, a private repository with three environments and a public one, and one App installation.
    """
    app    = f"repos/{LOGIN}/app-backend"
    engine = f"repos/{LOGIN}/engine"
    routes: dict[str, object] = {
        "user": {"login": LOGIN, "plan": {"name": "pro"}},
        "user/repos": Listed([
            {"name": "engine", "full_name": f"{LOGIN}/engine", "private": False, "visibility": "public",
             "default_branch": "main", "archived": False, "fork": False, "owner": {"login": LOGIN}},
            {"name": "app-backend", "full_name": f"{LOGIN}/app-backend", "private": True, "visibility": "private",
             "default_branch": "main", "archived": False, "fork": False, "owner": {"login": LOGIN}},
            {"name": "theirs", "full_name": "someone/theirs", "private": True, "owner": {"login": "someone"}},
        ]),
        f"repos/{LOGIN}/engine": {"name": "engine", "full_name": f"{LOGIN}/engine", "private": False,
                                  "visibility": "public", "default_branch": "main"},
        f"{app}/actions/permissions": {"enabled": True, "allowed_actions": "all"},
        f"{app}/actions/permissions/workflow": {"default_workflow_permissions": "read",
                                                "can_approve_pull_request_reviews": False},
        f"{app}/actions/secrets": Listed([{"name": "VERCEL_DEPLOYMENT_TOKEN"}, {"name": "KDF_APP_ID"},
                                          {"name": "KDF_APP_PRIVATE_KEY"}], field = "secrets"),
        f"{app}/actions/variables": Listed(canary_variables(45, "VAR"), field = "variables", cap = 30),
        f"{app}/environments": Listed([
            {"name": "prod", "can_admins_bypass": False,
             "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
             "protection_rules": [
                 {"type": "required_reviewers", "prevent_self_review": False,
                  "reviewers": [{"type": "User", "reviewer": {"login": LOGIN}}]},
                 {"type": "wait_timer", "wait_timer": 0},
                 {"type": "branch_policy"},
             ]},
            {"name": "dev", "can_admins_bypass": True,
             "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
             "protection_rules": []},
            {"name": "staging area", "deployment_branch_policy": None},
        ], field = "environments"),
        f"{app}/environments/prod/deployment-branch-policies": Listed([
            {"name": "v*", "type": "tag"}, {"name": "main", "type": "branch"},
        ], field = "branch_policies"),
        f"{app}/environments/prod/secrets": Listed([{"name": "SIGNING_KEY"}, {"name": "DB_URL"}], field = "secrets"),
        f"{app}/environments/prod/variables": Listed(canary_variables(2, "PROD"), field = "variables", cap = 30),
        f"{app}/environments/dev/secrets": Listed([{"name": "DB_URL"}], field = "secrets"),
        f"{app}/environments/dev/variables": Listed([], field = "variables", cap = 30),
        f"{app}/environments/staging%20area/secrets": Listed([], field = "secrets"),
        f"{app}/environments/staging%20area/variables": Listed(canary_variables(1, "STAGE"), field = "variables",
                                                               cap = 30),
        f"{app}/branches/main/protection": {
            "required_pull_request_reviews": {"required_approving_review_count": 0, "dismiss_stale_reviews": True,
                                              "require_code_owner_reviews": False,
                                              "require_last_push_approval": False},
            "required_status_checks": {"strict": True, "contexts": ["ci / test", "ci / lint"]},
            "enforce_admins": {"enabled": False},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_linear_history": {"enabled": False},
            "required_conversation_resolution": {"enabled": False},
            "required_signatures": {"enabled": False},
            "lock_branch": {"enabled": False},
        },
        f"{app}/rules/branches/main": Listed([{"type": "deletion", "ruleset_id": 7,
                                               "ruleset_source": f"{LOGIN}/app-backend"}]),
        f"{app}/rulesets": Listed([{"id": 7}]),
        f"{app}/rulesets/7": {
            "name": "Protect tags", "target": "tag", "enforcement": "active", "source_type": "Repository",
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": "update"}, {"type": "deletion"}],
            "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
        },
        f"{app}/collaborators": Listed([{"login": LOGIN, "role_name": "admin"}]),
        f"{app}/invitations": Listed([{"invitee": {"login": "invited-login"}, "permissions": "write"}]),
        f"{app}/keys": Listed([{"title": "a deploy key", "key": f"ssh-ed25519 {CANARY}PUBLICKEY",
                                "read_only": False}]),
        f"{engine}/actions/permissions": {"enabled": True, "allowed_actions": "selected"},
        f"{engine}/actions/permissions/workflow": {"default_workflow_permissions": "read",
                                                   "can_approve_pull_request_reviews": False},
        f"{engine}/actions/secrets": Listed([{"name": "CICD_PAT"}], field = "secrets"),
        f"{engine}/actions/variables": Listed([], field = "variables", cap = 30),
        f"{engine}/environments": Listed([], field = "environments"),
        f"{engine}/branches/main/protection": (404, {"message": "Branch not protected"}),
        f"{engine}/rules/branches/main": Listed([]),
        f"{engine}/rulesets": Listed([]),
        f"{engine}/collaborators": Listed([{"login": LOGIN, "role_name": "admin"}]),
        f"{engine}/invitations": Listed([]),
        f"{engine}/keys": Listed([]),
        "user/installations": Listed([
            {"id": 11, "app_id": 4242, "app_slug": "writer-app", "account": {"login": LOGIN},
             "repository_selection": "selected",
             "permissions": {"secrets": "write", "contents": "read"}, "events": [], "suspended_at": None},
        ], field = "installations"),
        "user/installations/11/repositories": Listed([
            {"full_name": f"{LOGIN}/engine"}, {"full_name": f"{LOGIN}/app-backend"},
        ], field = "repositories"),
    }
    return routes


def run(routes: dict[str, object], *argv: str) -> tuple[int, str, str, FakeGitHub]:
    """
    One run of the measure against the fake, its exit status, its output, its errors and the fake with its calls.
    """
    fake   = FakeGitHub(routes)
    out    = io.StringIO()
    err    = io.StringIO()
    status = kdf_measure().main(list(argv), fetch = fake, out = out, err = err)
    return status, out.getvalue(), err.getvalue(), fake

# ======================================================================================================================
# The whole run
# ======================================================================================================================

def test_full_run_prints_every_name_and_setting():
    status, out, err, _ = run(account_routes())
    lines = out.splitlines()
    assert status == 0, err
    assert lines[0] == "measure kdf-measure version=1"
    assert lines[1].startswith("taken ")
    assert lines[2] == f"login {LOGIN} plan=pro scopes=gist,read:org,repo,workflow"
    expected = [
        "repo app-backend visibility=private default_branch=main archived=false fork=false",
        "repo app-backend actions enabled=true allowed=all",
        "repo app-backend workflow_token default=read approves_pull_requests=false",
        "repo app-backend secret KDF_APP_ID",
        "repo app-backend secret VERCEL_DEPLOYMENT_TOKEN",
        "repo app-backend variable VAR_00",
        joined(
            "repo app-backend environment dev admin_bypass=true branch_rule=protected reviewers=-",
            "prevent_self_review=- wait_timer=0",
        ),
        joined(
            "repo app-backend environment prod admin_bypass=false branch_rule=selected reviewers=User:OwnerLogin2Name",
            "prevent_self_review=false wait_timer=0",
        ),
        "repo app-backend environment prod policy branch main",
        "repo app-backend environment prod policy tag v*",
        "repo app-backend environment prod secret DB_URL",
        "repo app-backend environment prod secret SIGNING_KEY",
        "repo app-backend environment prod variable PROD_00",
        "repo app-backend environment dev secret DB_URL",
        joined(
            'repo app-backend environment "staging area" admin_bypass=absent branch_rule=any reviewers=-',
            "prevent_self_review=- wait_timer=0",
        ),
        'repo app-backend environment "staging area" variable STAGE_00',
        joined(
            "repo app-backend protection main pull_request=true approvals=0 dismiss_stale=true code_owners=false",
            'last_push_approval=false pull_request_bypass=- checks_strict=true checks="ci / lint","ci / test"',
            "enforce_admins=false force_pushes=false deletions=false linear_history=false",
            "conversation_resolution=false signatures=false lock_branch=false push_restrictions=-",
        ),
        "repo app-backend branch_rule main deletion ruleset=7 source=OwnerLogin2Name/app-backend",
        joined(
            'repo app-backend ruleset 7 name="Protect tags" target=tag enforcement=active source=Repository',
            "include=refs/tags/v* exclude=- rules=deletion,update bypass=RepositoryRole:5:always",
        ),
        "repo app-backend collaborator OwnerLogin2Name role=admin",
        "repo app-backend invitation invited-login permission=write",
        'repo app-backend deploy_key "a deploy key" read_only=false',
        "repo engine visibility=public default_branch=main archived=false fork=false",
        "repo engine secret CICD_PAT",
        "repo engine protection main none",
        joined(
            "installation writer-app app_id=4242 id=11 account=OwnerLogin2Name selection=selected suspended=false",
            "permissions=contents:read,secrets:write events=-",
        ),
        "installation writer-app repo OwnerLogin2Name/app-backend",
        "installation writer-app repo OwnerLogin2Name/engine",
        "offers private rulesets=yes admin_bypass_switch=absent/present",
    ]
    for line in expected:
        assert line in lines, line
    assert not any("theirs" in line for line in lines)


def test_status_check_names_with_spaces_are_quoted_whole():
    lines      = run(account_routes())[1].splitlines()
    protection = next(line for line in lines if line.startswith("repo app-backend protection main"))
    assert 'checks="ci / lint","ci / test"' in protection


def test_no_value_reaches_the_output():
    status, out, err, _ = run(account_routes())
    assert status == 0, err
    assert CANARY not in out
    assert CANARY not in err


def test_variables_are_read_past_a_page_capped_at_thirty():
    status, out, _, fake = run(account_routes())
    names = [line for line in out.splitlines() if line.startswith("repo app-backend variable ")]
    assert status == 0
    assert len(names) == 45
    assert "repo app-backend variable VAR_44" in names
    assert f"repos/{LOGIN}/app-backend/actions/variables?per_page=100&page=2" in fake.calls


def test_an_environment_name_is_quoted_in_its_path():
    _, _, _, fake = run(account_routes())
    assert f"repos/{LOGIN}/app-backend/environments/staging%20area/secrets?per_page=100&page=1" in fake.calls


def test_two_runs_over_the_same_settings_print_the_same_lines():
    first  = [line for line in run(account_routes())[1].splitlines() if not line.startswith("taken ")]
    second = [line for line in run(account_routes())[1].splitlines() if not line.startswith("taken ")]
    assert first == second

# ======================================================================================================================
# Refusing a value
# ======================================================================================================================

def test_a_token_shape_anywhere_refuses_the_whole_output():
    routes = account_routes()
    routes[f"repos/{LOGIN}/app-backend/rulesets/7"]["name"] = GITHUB_TOKEN_SHAPE
    status, out, err, _ = run(routes)
    assert status == 2
    assert out == ""
    assert "a GitHub token" in err
    assert "repo app-backend" in err
    assert GITHUB_TOKEN_SHAPE not in err


def test_a_refusal_names_no_opening_that_itself_holds_a_shape():
    routes = account_routes()
    routes["user/repos"].items.append(
        {"name": GITHUB_TOKEN_SHAPE, "full_name": f"{LOGIN}/x", "private": False, "owner": {"login": LOGIN}},
    )
    status, out, err, _ = run(routes)
    assert status == 2
    assert out == ""
    assert GITHUB_TOKEN_SHAPE not in err
    assert "a GitHub token" in err


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        (GITHUB_TOKEN_SHAPE, "a GitHub token"),
        ("github_pat_" + "A1b2_" * 6, "a GitHub token"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "a private key"),
        ("eyJhbGciOiJSUzI1NiJ9." + "eyJzdWIiOiIxMjMifQ.c2ln", "a JSON web token"),
        ("postgresql://reader:" + "hunter2@db.example/neondb", "a URL with a password"),
        ("Ab3dEf6hIj9k" + "Lm2nOp5qRs8t", "a long run of mixed case letters and digits"),
        ("q3Zt8Lk2Wb5Yx+Fp9Rm1H" + "s7Vd/Nc4Ga6Ej0Ku2Oi3Ty", "a long base64 run"),
    ],
)
def test_each_credential_shape_is_found(text: str, shape: str):
    assert kdf_measure().find_value_shape(["repo a secret A", f"repo a ruleset 1 name={text}"]) == (2, shape)


def test_ordinary_names_and_settings_hold_no_credential_shape():
    lines = run(account_routes())[1].splitlines()
    lines.extend([
        "repo kriegerdataforge-template-fastapi secret REPORTS_CRON_SECRET_TIFFANYS_SPACE",
        "installation an-app permissions=administration:write,environments:write,secrets:write",
        "login Needless2Say plan=pro scopes=gist,read:org,repo,workflow",
        "installation kdf-cicd-automation repo Needless2Say/kriegerdataforge-template-fastapi",
        "repo kriegerdataforge branch_rule main deletion ruleset=7 source=Needless2Say/kriegerdataforge",
        "repo tiffanys-space-backend collaborator Needless2Say role=admin",
        "repo kriegerdataforge deploy_key MyLaptop-Key-2026-Personal-Backup read_only=true",
        "installation vercel app_id=8329 id=31112 account=Needless2Say selection=all permissions=contents:read",
    ])
    assert kdf_measure().find_value_shape(lines) is None


def test_the_module_never_reads_a_value_field():
    source = MODULE_PATH.read_text(encoding = "utf-8")
    assert '"value"' not in source
    assert "'value'" not in source
    assert '"key")' not in source

# ======================================================================================================================
# Answers that are not a plain yes
# ======================================================================================================================

def test_a_plan_without_rulesets_on_a_private_repo_is_a_finding_not_a_failure():
    routes  = account_routes()
    upgrade = (403, {"message": "Upgrade to GitHub Pro or make this repository public to enable this feature."})
    routes[f"repos/{LOGIN}/app-backend/rulesets"] = upgrade
    status, out, err, _ = run(routes)
    assert status == 0, err
    assert "repo app-backend rulesets unavailable" in out.splitlines()
    assert "offers private rulesets=no admin_bypass_switch=absent/present" in out.splitlines()


def test_a_failed_read_is_named_and_the_rest_still_printed():
    routes = account_routes()
    routes[f"repos/{LOGIN}/app-backend/collaborators"] = (500, {"message": "Server Error"})
    status, out, err, _ = run(routes)
    assert status == 1
    assert "unreadable repo app-backend collaborators status=500" in out.splitlines()
    assert "repo engine collaborator OwnerLogin2Name role=admin" in out.splitlines()
    assert "Reads that failed, 1" in err


def test_a_body_of_the_wrong_shape_is_named_malformed():
    routes = account_routes()
    routes[f"repos/{LOGIN}/engine/actions/secrets"] = {"total_count": 1, "secrets": "not a list"}
    status, out, _, _ = run(routes)
    assert status == 1
    assert "unreadable repo engine secret status=malformed" in out.splitlines()


def test_named_repositories_alone_are_read():
    status, out, err, fake = run(account_routes(), "--repo", "engine")
    assert status == 0, err
    assert "repo engine secret CICD_PAT" in out.splitlines()
    assert not any("app-backend" in path for path in fake.calls)
    assert not any(path.startswith("user/repos") for path in fake.calls)


def test_a_named_repository_that_cannot_be_read_is_named():
    status, out, _, _ = run(account_routes(), "--repo", "missing")
    assert status == 1
    assert f"unreadable repo {LOGIN}/missing status=404" in out.splitlines()


def test_login_only_prints_the_login_line_alone():
    status, out, _, fake = run(account_routes(), "--login-only")
    assert status == 0
    assert out.splitlines() == [f"login {LOGIN} plan=pro scopes=gist,read:org,repo,workflow"]
    assert fake.calls == ["user"]


def test_a_login_that_cannot_be_read_stops_the_measure():
    routes = account_routes()
    routes["user"] = (401, {"message": "Bad credentials"})
    status, out, err, _ = run(routes)
    assert status == 3
    assert out == ""
    assert "could not start" in err

# ======================================================================================================================
# Reading through gh
# ======================================================================================================================

def completed(stdout: str) -> subprocess.CompletedProcess:
    """
    What subprocess.run returns for a gh call that wrote stdout.
    """
    return subprocess.CompletedProcess(args = [], returncode = 0, stdout = stdout, stderr = "")


def test_gh_fetch_asks_gh_for_one_get_and_never_for_a_token():
    calls: list[list[str]] = []


    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess:
        calls.append(args)
        return completed('HTTP/2.0 200 OK\r\nX-Oauth-Scopes: repo, workflow\r\n\r\n{"login": "someone"}')


    response = kdf_measure().gh_fetch("user", run = runner)
    assert calls == [["gh", "api", "--include", "--method", "GET", "user"]]
    assert response.status == 200
    assert response.headers["x-oauth-scopes"] == "repo, workflow"
    assert response.body == {"login": "someone"}


def test_gh_fetch_reads_a_refused_answer():
    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess:
        return completed(
            'HTTP/2.0 404 Not Found\nContent-Type: application/json\n\n{"message": "Branch not protected"}',
        )


    response = kdf_measure().gh_fetch("repos/a/b/branches/main/protection", run = runner)
    assert response.status == 404
    assert response.message() == "branch not protected"


def test_gh_fetch_with_no_answer_is_unavailable():
    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args = args, returncode = 4, stdout = "", stderr = "not signed in")


    with pytest.raises(kdf_measure().GhUnavailable):
        kdf_measure().gh_fetch("user", run = runner)


def test_gh_that_cannot_run_is_unavailable():
    def runner(args: list[str], **_: object) -> subprocess.CompletedProcess:
        raise FileNotFoundError("gh")


    with pytest.raises(kdf_measure().GhUnavailable):
        kdf_measure().gh_fetch("user", run = runner)


def test_an_answer_with_no_status_line_is_unavailable():
    with pytest.raises(kdf_measure().GhUnavailable):
        kdf_measure().parse_include("not an http answer")


def test_a_body_that_is_not_json_reads_as_none():
    response = kdf_measure().parse_include("HTTP/1.1 502 Bad Gateway\n\n<html>busy</html>")
    assert response.status == 502
    assert response.body is None

# ======================================================================================================================
# Words
# ======================================================================================================================

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "-"),
        (True, "true"),
        ([], "-"),
        (["b", "a"], "a,b"),
        ("", '""'),
        ("plain", "plain"),
        ("two words", '"two words"'),
        ("a=b", '"a=b"'),
        ("tab\there", '"tab\\there"'),
    ],
)
def test_word(value: object, expected: str):
    assert kdf_measure().word(value) == expected
