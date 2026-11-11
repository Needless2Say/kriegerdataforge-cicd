"""
Unit tests for scripts/terraform_run.py, the reusable terraform workflow's generic helpers (terraform in Actions,
design 5.6 and 5.7).

The release resolution runs against a real git repository made in a temporary folder, so the tag, the history and the
ancestry are git's own. The plan check reads plans shaped as `terraform show -json` writes them, the seal and its
verification run on made up fields and a made up key, and the backend identity on made up connection strings.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import terraform_run as tr
from terraform_run import Refused

KEY = "kdfmk-made-up-manifest-key"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo = timezone.utc)

# ======================================================================================================================
# The release resolution
# ======================================================================================================================

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check = True,
        capture_output = True,
        text = True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """
    A repository whose main holds three releases, v0.9.0, v0.10.0 and v0.11.0, and a branch off it holding v0.12.0,
    a tag that never merged.
    """
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "made-up@example.test")
    _git(path, "config", "user.name", "made up")
    for version in ("0.9.0", "0.10.0", "0.11.0"):
        (path / "VERSION").write_text(version + "\n", encoding = "utf-8")
        _git(path, "add", "VERSION")
        _git(path, "commit", "-q", "-m", version)
        _git(path, "tag", "v" + version)
    _git(path, "checkout", "-q", "-b", "side")
    (path / "VERSION").write_text("0.12.0\n", encoding = "utf-8")
    _git(path, "commit", "-q", "-am", "0.12.0")
    _git(path, "tag", "v0.12.0")
    _git(path, "checkout", "-q", "main")
    return path


class TestResolve:
    """
    The release's tag resolved once, its commit in main's history and its version at or above the floor.
    """
    def test_a_release_on_main_at_the_floor_resolves_to_its_commit(self, repo):
        assert tr.resolve(repo, "0.10.0", "0.10.0", "main") == _git(repo, "rev-parse", "v0.10.0^{commit}")


    def test_an_older_release_above_the_floor_resolves(self, repo):
        assert tr.resolve(repo, "0.10.0", "0.9.0", "main") == _git(repo, "rev-parse", "v0.10.0^{commit}")


    def test_a_release_below_the_floor_is_refused(self, repo):
        with pytest.raises(Refused, match = "floor"):
            tr.resolve(repo, "0.9.0", "0.10.0", "main")


    def test_a_tag_that_never_merged_is_refused(self, repo):
        with pytest.raises(Refused, match = "history"):
            tr.resolve(repo, "0.12.0", "0.9.0", "main")


    def test_a_missing_tag_is_refused(self, repo):
        with pytest.raises(Refused, match = "no tag"):
            tr.resolve(repo, "0.13.0", "0.9.0", "main")


    def test_an_annotated_tag_resolves_to_its_commit(self, repo):
        _git(repo, "tag", "-a", "v0.11.1", "-m", "annotated", "v0.11.0")
        assert tr.resolve(repo, "0.11.1", "0.9.0", "main") == _git(repo, "rev-parse", "v0.11.0^{commit}")


    @pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3-rc1", "01.2.3", "1.2.3 ", "1..3", ""])
    def test_a_version_not_x_y_z_is_refused(self, repo, version):
        with pytest.raises(Refused):
            tr.resolve(repo, version, "0.9.0", "main")


    def test_a_floor_not_x_y_z_is_refused(self, repo):
        with pytest.raises(Refused):
            tr.resolve(repo, "0.10.0", "latest", "main")


    def test_versions_compare_as_numbers(self):
        assert tr.version_tuple("0.10.0") > tr.version_tuple("0.9.9")

# ======================================================================================================================
# A plan of no changes
# ======================================================================================================================

def _plan(resources: list[tuple[str, list[str]]], outputs: dict[str, dict] | None = None) -> dict:
    return {
        "resource_changes": [{"address": a, "change": {"actions": actions}} for a, actions in resources],
        "output_changes": outputs or {},
    }


def _marker(before: str, after: str, actions: list[str] | None = None) -> dict:
    return {"release": {"actions": actions or ["update"], "before": before, "after": after}}


class TestNoChanges:
    """
    A plan of no changes, the release marker's move to the run's release the one change allowed.
    """
    def test_no_ops_and_the_markers_move_to_the_runs_release_pass(self):
        plan = _plan([("module.a.vercel_project.this", ["no-op"])], _marker("v0.10.0", "v0.11.0"))
        assert tr.no_change_findings(plan, "v0.11.0") == []


    def test_a_marker_already_at_the_runs_release_passes(self):
        plan = _plan([("a", ["no-op"])], {"release": {"actions": ["no-op"], "before": "v0.11.0", "after": "v0.11.0"}})
        assert tr.no_change_findings(plan, "v0.11.0") == []


    def test_a_first_marker_created_passes(self):
        plan = _plan([("a", ["no-op"])], _marker("", "v0.11.0", ["create"]))
        assert tr.no_change_findings(plan, "v0.11.0") == []


    def test_an_update_of_a_resource_is_a_change(self):
        plan  = _plan([("module.a.vercel_project_environment_variable.secret[\"X\"]", ["update"])])
        found = tr.no_change_findings(plan, "v0.11.0")
        assert len(found) == 1
        assert "secret[\"X\"]" in found[0]


    @pytest.mark.parametrize("actions", [["create"], ["delete"], ["delete", "create"], ["create", "delete"]])
    def test_every_other_resource_action_is_a_change(self, actions):
        assert tr.no_change_findings(_plan([("a", actions)]), "v0.11.0")


    def test_a_data_source_read_is_no_change(self):
        assert tr.no_change_findings(_plan([("data.x.y", ["read"])]), "v0.11.0") == []


    def test_the_marker_moved_to_another_release_is_a_change(self):
        found = tr.no_change_findings(_plan([], _marker("v0.10.0", "v0.12.0")), "v0.11.0")
        assert len(found) == 1
        assert "release" in found[0]


    def test_any_other_output_changing_is_a_change(self):
        outputs = {**_marker("v0.10.0", "v0.11.0"), "kdf_auth_service_project_id": {"actions": ["update"]}}
        found   = tr.no_change_findings(_plan([], outputs), "v0.11.0")
        assert len(found) == 1
        assert "kdf_auth_service_project_id" in found[0]


    def test_a_plan_with_no_changes_listed_at_all_passes(self):
        assert tr.no_change_findings({}, "v0.11.0") == []


    def test_a_plan_marked_errored_is_a_change(self):
        assert tr.no_change_findings({"errored": True}, "v0.11.0")

# ======================================================================================================================
# The sealed plan manifest
# ======================================================================================================================

def _fields(**overrides) -> dict:
    fields = {
        "schema": 1,
        "gate_run_id": "9",
        "gate_run_attempt": "1",
        "environment": "prod",
        "backend_identity": "db.example.test:5432/terraform?schema=prod",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "plan_sha256": "a" * 64,
        "terraform_version": "1.17.1",
        "lock_sha256": "b" * 64,
        "secret_hashes": {"module.a.secret[\"X\"]": "c" * 64},
        "created_at": "2026-11-11T08:00:00Z",
    }
    fields.update(overrides)
    return fields


def _expected(**overrides) -> dict:
    expected = {k: v for k, v in _fields().items() if k not in ("created_at", "terraform_version")}
    expected.update(overrides)
    return expected


class TestSeal:
    """
    The gate's manifest sealed and verified, the seal first and every field after it.
    """
    def test_a_sealed_manifest_verifies(self):
        manifest = tr.seal(_fields(), KEY)
        assert tr.verify(manifest, KEY, _expected(), NOW, floor = "1.17.0") == []


    def test_the_seal_does_not_depend_on_key_order(self):
        fields = _fields()
        assert tr.seal(fields, KEY)["seal"] == tr.seal(dict(reversed(list(fields.items()))), KEY)["seal"]


    def test_a_changed_field_breaks_the_seal_and_nothing_else_is_judged(self):
        manifest = tr.seal(_fields(), KEY)
        manifest["fields"]["plan_sha256"] = "d" * 64
        found = tr.verify(manifest, KEY, _expected(), NOW, floor = "1.17.0")
        assert found == ["the manifest's seal does not hold"]


    def test_another_key_breaks_the_seal(self):
        assert tr.verify(tr.seal(_fields(), KEY), "kdfmk-another", _expected(), NOW, floor = "1.17.0")


    def test_an_empty_key_is_refused(self):
        with pytest.raises(Refused):
            tr.seal(_fields(), "")


    @pytest.mark.parametrize("field, value", [
        ("gate_run_id", "10"),
        ("environment", "dev"),
        ("backend_identity", "other.example.test:5432/terraform?schema=prod"),
        ("commit", "f" * 40),
        ("plan_sha256", "e" * 64),
        ("lock_sha256", "e" * 64),
        ("secret_hashes", {"module.a.secret[\"X\"]": "e" * 64}),
    ])
    def test_each_field_must_equal_the_deploys_own(self, field, value):
        found = tr.verify(tr.seal(_fields(), KEY), KEY, _expected(**{field: value}), NOW, floor = "1.17.0")
        assert len(found) == 1
        assert field in found[0]


    def test_a_plan_older_than_its_limit_is_refused(self):
        old   = tr.seal(_fields(created_at = "2026-11-08T11:00:00Z"), KEY)
        found = tr.verify(old, KEY, _expected(), NOW, floor = "1.17.0")
        assert found and "72 hours" in found[0]
        assert tr.verify(old, KEY, _expected(), NOW, floor = "1.17.0", max_age_hours = 80) == []


    def test_a_plan_from_the_future_is_refused(self):
        ahead = tr.seal(_fields(created_at = (NOW + timedelta(hours = 1)).strftime("%Y-%m-%dT%H:%M:%SZ")), KEY)
        assert tr.verify(ahead, KEY, _expected(), NOW, floor = "1.17.0")


    @pytest.mark.parametrize("version", ["1.17", "~1.17", "1.17.1; curl", "latest", ""])
    def test_a_terraform_version_not_x_y_z_is_refused(self, version):
        manifest = tr.seal(_fields(terraform_version = version), KEY)
        assert tr.verify(manifest, KEY, _expected(), NOW, floor = "1.17.0")


    def test_a_terraform_version_below_the_floor_is_refused(self):
        manifest = tr.seal(_fields(terraform_version = "1.16.9"), KEY)
        found    = tr.verify(manifest, KEY, _expected(), NOW, floor = "1.17.0")
        assert found and "floor" in found[0]


    def test_a_manifest_of_another_schema_is_refused(self):
        manifest = tr.seal(_fields(schema = 2), KEY)
        assert tr.verify(manifest, KEY, _expected(), NOW, floor = "1.17.0")


    def test_a_manifest_missing_its_seal_is_refused(self):
        assert tr.verify({"fields": _fields()}, KEY, _expected(), NOW, floor = "1.17.0")


    def test_the_version_verified_is_returned_for_the_install(self):
        assert tr.verified_terraform_version(tr.seal(_fields(), KEY)) == "1.17.1"

# ======================================================================================================================
# The backend identity
# ======================================================================================================================

class TestIdentity:
    """
    A backend's identity, never its role or password.
    """
    def test_the_identity_holds_the_host_port_database_and_schema_alone(self):
        conn = "postgresql://writer:kdfmk-made-up-password@DB.Example.test:5433/terraform?sslmode=verify-full"
        assert tr.identity(conn, "prod") == "db.example.test:5433/terraform?schema=prod"


    def test_the_default_port_is_named(self):
        assert tr.identity(
            "postgres://u:p@db.example.test/terraform",
            "dev",
        ) == "db.example.test:5432/terraform?schema=dev"


    def test_a_reader_and_a_writer_of_one_state_share_its_identity(self):
        writer = tr.identity("postgresql://writer:a@db.example.test/terraform", "dev")
        reader = tr.identity("postgresql://reader:b@db.example.test/terraform", "dev")
        assert writer == reader


    @pytest.mark.parametrize("conn", [
        "mysql://u:p@db.example.test/terraform",
        "postgresql://u:p@/terraform",
        "postgresql://u:p@db.example.test/",
        "not a url",
        "",
    ])
    def test_a_string_that_is_no_postgres_url_is_refused(self, conn):
        with pytest.raises(Refused):
            tr.identity(conn, "dev")


    def test_a_refusal_never_names_the_string(self):
        conn = "mysql://u:kdfmk-made-up-password@db.example.test/terraform"
        with pytest.raises(Refused) as caught:
            tr.identity(conn, "dev")
        assert "kdfmk" not in str(caught.value)


    def test_a_schema_that_is_no_name_is_refused(self):
        with pytest.raises(Refused):
            tr.identity("postgresql://u:p@db.example.test/terraform", "prod; drop")

# ======================================================================================================================
# The command line
# ======================================================================================================================

class TestCli:
    """
    Each subcommand's exit code and outputs, no secret printed.
    """
    def test_no_changes_exits_by_its_findings(self, tmp_path, capsys):
        good = tmp_path / "good.json"
        good.write_text(json.dumps(_plan([("a", ["no-op"])])), encoding = "utf-8")
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps(_plan([("a", ["update"])])), encoding = "utf-8")
        assert tr.main(["no-changes", "--plan", str(good), "--release", "v0.11.0"]) == 0
        assert tr.main(["no-changes", "--plan", str(bad), "--release", "v0.11.0"]) == 1


    def test_seal_and_verify_read_the_key_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TF_MANIFEST_KEY", KEY)
        fields = tmp_path / "fields.json"
        fields.write_text(json.dumps(_fields(created_at = NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))), encoding = "utf-8")
        expected = tmp_path / "expected.json"
        expected.write_text(json.dumps(_expected()), encoding = "utf-8")
        manifest = tmp_path / "manifest.json"
        assert tr.main(["seal", "--fields", str(fields), "--out", str(manifest)]) == 0
        assert KEY not in manifest.read_text(encoding = "utf-8")
        assert tr.main(["verify", "--manifest", str(manifest), "--expected", str(expected), "--floor", "1.17.0"]) == 0


    def test_identity_reads_the_string_from_a_named_variable_and_never_prints_it(self, monkeypatch, capsys):
        monkeypatch.setenv("TF_STATE_PG_CONN_STR", "postgresql://w:kdfmk-made-up-password@db.example.test/terraform")
        assert tr.main(["identity", "--env-var", "TF_STATE_PG_CONN_STR", "--schema", "dev"]) == 0
        out = capsys.readouterr().out
        assert out.strip() == "db.example.test:5432/terraform?schema=dev"
        assert "kdfmk" not in out


    def test_resolve_writes_the_commit_to_the_step_outputs(self, repo, tmp_path, monkeypatch):
        out = tmp_path / "out"
        out.write_text("", encoding = "utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        args = ["resolve", "--repo-dir", str(repo), "--version", "0.10.0", "--floor", "0.9.0", "--main-ref", "main"]
        assert tr.main(args) == 0
        assert out.read_text(encoding = "utf-8") == f"commit={_git(repo, 'rev-parse', 'v0.10.0^{commit}')}\n"


    def test_a_refusal_exits_two(self, repo):
        args = ["resolve", "--repo-dir", str(repo), "--version", "0.12.0", "--floor", "0.9.0", "--main-ref", "main"]
        assert tr.main(args) == 2
