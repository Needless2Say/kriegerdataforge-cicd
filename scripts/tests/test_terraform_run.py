"""
Unit tests for scripts/terraform_run.py, the reusable terraform workflow's generic helpers (terraform in Actions,
design 5.6 and 5.7).

The release's tag is resolved by check_release_commit.py and tested there. The plan check reads plans shaped as
`terraform show -json` writes them, the seal and its verification run on made up fields and a made up key, and the
backend identity on made up connection strings.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import terraform_run as tr
from terraform_run import Refused

KEY = "kdfmk-made-up-manifest-key"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo = timezone.utc)

# an inherited secrets bundle, made up, and the names the workflow drops before the caller's preflight
BUNDLE = {
    "TF_STATE_PG_CONN_STR": "postgresql://w:kdfmk-live-made-up@db.example.test/terraform",
    "TF_STATE_RECOVERY_CONN_STR": "postgresql://r:kdfmk-scratch-made-up@db.example.test/scratch",
    "APP_SECRET": "kdfmk-app-made-up",
    "github_token": "kdfmk-token-made-up",
}
DROPS  = ["TF_STATE_PG_CONN_STR", "TF_STATE_RECOVERY_CONN_STR", "github_token"]

# a backend identity the proof records bind, made up
IDENTITY = "db.example.test:5432/terraform?schema=dev"

# ======================================================================================================================
# Versions
# ======================================================================================================================

class TestVersions:
    """
    A version is exactly X.Y.Z and compares as three numbers.
    """
    @pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3-rc1", "01.2.3", "1.2.3 ", "1..3", ""])
    def test_a_version_not_x_y_z_is_refused(self, version):
        with pytest.raises(Refused):
            tr.version_tuple(version)


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


class TestDifferences:
    """
    What validate lists for the owner, every planned change and every address a refresh found drifted from the
    stored state, since certifying records the stored bytes (Codex's review of f05c870).
    """
    def test_a_drifted_address_with_a_no_op_change_is_listed(self, capsys):
        plan = _plan([("vercel_project_environment_variable.plain[\"A\"]", ["no-op"])])
        plan["resource_drift"] = [
            {"address": "vercel_project_environment_variable.plain[\"A\"]", "change": {"actions": ["update"]}},
        ]
        assert tr.no_change_findings(plan, "v0.11.0") == []
        found = tr.differences(plan, "v0.11.0")
        assert any("plain[\"A\"]" in line and "drift" in line for line in found)


    def test_planned_changes_are_listed_too_and_nothing_for_a_quiet_plan(self):
        assert tr.differences(_plan([("a.b", ["update"])]), "v0.11.0") == ["a.b plans ['update']"]
        assert tr.differences(_plan([("a.b", ["no-op"])], _marker("v0.10.0", "v0.11.0")), "v0.11.0") == []


    def test_the_cli_lists_and_always_exits_zero(self, tmp_path, capsys):
        plan = _plan([("a.b", ["update"])])
        plan["resource_drift"] = [{"address": "c.d", "change": {"actions": ["update"]}}]
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan), encoding = "utf-8")
        assert tr.main(["differences", "--plan", str(path), "--release", "v0.11.0"]) == 0
        out = capsys.readouterr().out
        assert "a.b" in out and "c.d" in out


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
# A repair's forced push, bound to what the recovery mode recorded
# ======================================================================================================================

def _state(lineage: str = "lineage-1", serial: int = 7, release: str | None = "v0.11.0") -> bytes:
    outputs = {"release": {"value": release, "type": "string"}} if release is not None else {}
    return json.dumps({"version": 4, "lineage": lineage, "serial": serial, "outputs": outputs}).encode("utf-8")


def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


class TestBindPush:
    """
    A forced push skips Terraform's own refusal, so the candidate and the live state must be the ones reviewed.
    """
    def _bind(self, candidate: bytes, live: bytes, **overrides) -> list[str]:
        args = {
            "candidate_sha256": _sha(candidate),
            "live_sha256": _sha(live),
            "lineage": "lineage-1",
            "serial": "7",
            "named_release": "",
        }
        args.update(overrides)
        return tr.bind_push_findings(candidate, live, **args)


    def test_the_reviewed_candidate_and_live_state_pass(self):
        assert self._bind(_state(serial = 5, release = "v0.11.0"), _state()) == []


    def test_a_candidate_other_than_the_one_reviewed_is_refused(self):
        found = self._bind(_state(serial = 5), _state(), candidate_sha256 = "0" * 64)
        assert found and "candidate" in found[0]


    def test_a_live_state_that_changed_since_sends_it_back_to_recovery(self):
        found = self._bind(_state(serial = 5), _state(serial = 8), live_sha256 = _sha(_state()))
        assert any("recovery" in line for line in found)


    def test_another_lineage_or_serial_is_refused(self):
        assert self._bind(_state(serial = 5), _state(), lineage = "lineage-2")
        assert self._bind(_state(serial = 5), _state(), serial = "8")


    def test_an_older_release_marker_is_refused_unless_named(self):
        candidate = _state(serial = 5, release = "v0.10.0")
        found     = self._bind(candidate, _state(release = "v0.11.0"))
        assert found and "older" in found[0]
        assert self._bind(candidate, _state(release = "v0.11.0"), named_release = "v0.10.0") == []


    def test_a_live_state_with_no_marker_holds_nothing_older(self):
        assert self._bind(_state(serial = 5, release = "v0.10.0"), _state(release = None)) == []


    @pytest.mark.parametrize("field, value", [
        ("candidate_sha256", "not a digest"),
        ("live_sha256", ""),
        ("serial", "seven"),
        ("lineage", ""),
    ])
    def test_a_malformed_binding_is_refused(self, field, value):
        with pytest.raises(Refused):
            self._bind(_state(serial = 5), _state(), **{field: value})


    def test_a_candidate_that_is_no_state_is_refused(self):
        with pytest.raises(Refused):
            self._bind(b"not json", _state())


    def test_the_cli_binds_and_the_digest_prints_what_a_later_push_binds(self, tmp_path, capsys):
        candidate = tmp_path / "candidate.json"
        candidate.write_bytes(_state(serial = 5))
        live = tmp_path / "live.json"
        live.write_bytes(_state())
        assert tr.main(["state-digest", "--state", str(live)]) == 0
        assert capsys.readouterr().out.strip() == f"sha256 {_sha(_state())} lineage lineage-1 serial 7"
        args = [
            "bind-push",
            "--candidate",
            str(candidate),
            "--live",
            str(live),
            "--candidate-sha256",
            _sha(_state(serial = 5)),
            "--live-sha256",
            _sha(_state()),
            "--lineage",
            "lineage-1",
            "--serial",
            "7",
        ]
        assert tr.main(args) == 0
        assert tr.main([*args[:-1], "8"]) == 1

# ======================================================================================================================
# The secrets handed to the caller's preflight, the connection strings dropped
# ======================================================================================================================

class TestSecretsFile:
    """
    The caller's code never receives a connection string, so a recovery's guarantee holds in cicd itself (the
    owner's answer of 2026-11-11, after a by-name hand off proved to need cicd to name tenant secrets).
    """
    def test_the_named_secrets_are_dropped_and_the_rest_kept(self):
        assert tr.filtered_secrets(dict(BUNDLE), DROPS) == {"APP_SECRET": "kdfmk-app-made-up"}


    def test_a_drop_absent_from_the_bundle_is_no_error(self):
        assert tr.filtered_secrets({"APP_SECRET": "x"}, DROPS) == {"APP_SECRET": "x"}


    @pytest.mark.parametrize("bundle", [[], "text", {"A": 1}, {"A": None}])
    def test_a_bundle_that_is_no_object_of_strings_is_refused(self, bundle):
        with pytest.raises(Refused):
            tr.filtered_secrets(bundle, DROPS)


    def test_the_cli_writes_the_file_and_prints_names_alone(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("SECRETS_JSON", json.dumps(BUNDLE))
        out  = tmp_path / "tf-secrets.json"
        args = ["secrets-file", "--env-var", "SECRETS_JSON", "--out", str(out)]
        for name in DROPS:
            args += ["--drop", name]
        assert tr.main(args) == 0
        assert json.loads(out.read_text(encoding = "utf-8")) == {"APP_SECRET": "kdfmk-app-made-up"}
        printed = capsys.readouterr().out
        assert "kdfmk" not in printed
        assert "TF_STATE_PG_CONN_STR" in printed


    def test_an_unreadable_bundle_exits_two_and_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRETS_JSON", "{not json")
        out = tmp_path / "tf-secrets.json"
        assert tr.main(["secrets-file", "--env-var", "SECRETS_JSON", "--out", str(out)]) == 2
        assert not out.exists()

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


    def test_verify_writes_the_verified_terraform_version(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TF_MANIFEST_KEY", KEY)
        out = tmp_path / "out"
        out.write_text("", encoding = "utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        manifest = tmp_path / "manifest.json"
        fields   = _fields(created_at = NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        manifest.write_text(json.dumps(tr.seal(fields, KEY)), encoding = "utf-8")
        expected = tmp_path / "expected.json"
        expected.write_text(json.dumps(_expected()), encoding = "utf-8")
        assert tr.main(["verify", "--manifest", str(manifest), "--expected", str(expected), "--floor", "1.17.0"]) == 0
        assert out.read_text(encoding = "utf-8") == "terraform_version=1.17.1\n"


    @pytest.mark.parametrize("version, floor, code", [
        ("0.10.0", "0.10.0", 0),
        ("0.11.0", "0.10.0", 0),
        ("0.9.9", "0.10.0", 1),
        ("v0.10.0", "0.10.0", 0),
        ("0.10", "0.10.0", 2),
        ("0.10.0", "", 2),
    ])
    def test_at_least_compares_two_versions(self, version, floor, code, capsys):
        # a leading v is the tag's spelling and is read as the version, anything else not X.Y.Z is refused
        assert tr.main(["at-least", "--version", version, "--floor", floor, "--what", "the release"]) == code


    def test_a_refusal_exits_two(self, monkeypatch):
        monkeypatch.setenv("TF_STATE_PG_CONN_STR", "mysql://u:p@db.example.test/terraform")
        assert tr.main(["identity", "--env-var", "TF_STATE_PG_CONN_STR", "--schema", "dev"]) == 2

# ======================================================================================================================
# The proof record (design version 14, 5.6 item 6, the second read's H)
# ======================================================================================================================

def _record_fields(state: bytes, **overrides) -> dict:
    fields = tr.record_fields(
        state,
        repository = "owner/terraform",
        environment = "dev",
        backend_identity = IDENTITY,
        release = "v0.11.0",
        commit = "a" * 40,
        kind = "complete",
        run_id = "101",
        run_attempt = "1",
        now = NOW,
    )
    fields.update(overrides)
    return fields


def _records(*sealed: tuple[int, dict]) -> list[dict]:
    return [{"id": deployment, "record": record} for deployment, record in sealed]


def _findings(records: list[dict], state: bytes, key: str = KEY, **overrides) -> list[str]:
    bound = {"repository": "owner/terraform", "environment": "dev", "backend_identity": IDENTITY}
    bound.update(overrides)
    return tr.record_findings(records, key, state_data = state, **bound)


class TestProofRecord:
    """
    A record of a proven state, sealed under the environment's key by its own job, which the PROD gate and deploy
    require of the stored state, the newest record judged alone and never a fallback.
    """
    def test_a_record_binds_the_state_its_repository_environment_backend_and_run(self):
        state  = _state()
        fields = _record_fields(state)
        assert fields["type"] == "terraform_proof_record"
        assert fields["state_sha256"] == _sha(state)
        assert (fields["lineage"], fields["serial"]) == ("lineage-1", 7)
        for name in (
            "repository",
            "environment",
            "backend_identity",
            "release",
            "commit",
            "kind",
            "run_id",
            "run_attempt",
            "created_at",
        ):
            assert fields[name]


    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(Refused):
            tr.record_fields(
                _state(),
                repository = "o/t",
                environment = "dev",
                backend_identity = IDENTITY,
                release = "v0.11.0",
                commit = "a" * 40,
                kind = "anything",
                run_id = "1",
                run_attempt = "1",
                now = NOW,
            )


    def test_the_newest_sealed_record_of_this_state_passes(self):
        state = _state()
        assert _findings(_records((5, tr.seal(_record_fields(state), KEY))), state) == []


    def test_no_record_is_refused(self):
        assert _findings([], _state())


    def test_a_record_of_another_state_is_refused(self):
        sealed = tr.seal(_record_fields(_state(serial = 6)), KEY)
        assert any("state_sha256" in f for f in _findings(_records((5, sealed)), _state()))


    def test_a_newer_unsealed_record_is_refused_and_an_older_good_one_never_used(self):
        state  = _state()
        good   = tr.seal(_record_fields(state), KEY)
        forged = {"fields": _record_fields(state), "seal": "0" * 64}
        assert _findings(_records((5, good), (9, forged)), state)


    def test_a_record_sealed_with_another_environments_key_is_refused(self):
        state = _state()
        assert _findings(_records((5, tr.seal(_record_fields(state), "kdfmk-other-key"))), state)


    @pytest.mark.parametrize("name, value", [
        ("repository", "owner/other"),
        ("environment", "prod"),
        ("backend_identity", "db.example.test:5432/terraform?schema=prod"),
    ])
    def test_a_record_bound_to_another_place_is_refused(self, name, value):
        state = _state()
        found = _findings(_records((5, tr.seal(_record_fields(state), KEY))), state, **{name: value})
        assert any(name in f for f in found)


    def test_a_changed_bound_field_breaks_the_seal(self):
        state  = _state()
        sealed = tr.seal(_record_fields(state), KEY)
        sealed["fields"]["serial"] = 8
        assert any("seal" in f for f in _findings(_records((5, sealed)), state))


    def test_a_record_with_no_fields_or_seal_is_refused(self):
        assert _findings(_records((5, {"seal": "x"})), _state())
        assert _findings(_records((5, "not an object")), _state())


    def test_the_cli_writes_a_deployment_body_and_checks_it_back(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TF_MANIFEST_KEY", KEY)
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/terraform")
        monkeypatch.setenv("GITHUB_RUN_ID", "101")
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
        state = tmp_path / "after.json"
        state.write_bytes(_state())
        body = tmp_path / "body.json"
        assert tr.main(["record-seal", "--state", str(state), "--environment", "dev", "--identity", IDENTITY,
                        "--release", "v0.11.0", "--commit", "a" * 40, "--kind", "partial", "--out", str(body)]) == 0
        written = json.loads(body.read_text(encoding = "utf-8"))
        assert written["environment"] == "dev" and written["ref"] == "a" * 40
        assert written["payload"]["terraform_proof_record"]["fields"]["kind"] == "partial"
        assert "kdfmk" not in json.dumps(written)
        records = tmp_path / "records.jsonl"
        line    = json.dumps({"id": 12, "record": written["payload"]["terraform_proof_record"]})
        records.write_text(line + "\n", encoding = "utf-8")
        assert tr.main(["record-check", "--records", str(records), "--state", str(state), "--environment", "dev",
                        "--identity", IDENTITY]) == 0
        state.write_bytes(_state(serial = 8))
        assert tr.main(["record-check", "--records", str(records), "--state", str(state), "--environment", "dev",
                        "--identity", IDENTITY]) == 1


    def test_the_cli_refuses_a_records_file_that_is_not_json_lines(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TF_MANIFEST_KEY", KEY)
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/terraform")
        state = tmp_path / "s.json"
        state.write_bytes(_state())
        records = tmp_path / "records.jsonl"
        records.write_text("{not json\n", encoding = "utf-8")
        assert tr.main(["record-check", "--records", str(records), "--state", str(state), "--environment", "dev",
                        "--identity", IDENTITY]) == 2
