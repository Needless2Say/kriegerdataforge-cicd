"""
Unit tests for scripts/trigger_triage.py (the reports-triage trigger engine).

All HTTP I/O is mocked. The security-critical invariants get explicit regression tests:
cron-secret values never appear in output, response BODIES are never echoed (only the
whitelisted scalar metadata of a 202 — report content must not leak into public Actions
logs / issue comments), secrets resolve before the first POST, and POSTs are never
status-retried. The real scripts/reports_registry.json is contract-tested so registry
drift (renamed slugs, flipped enables, lost TODO markers) fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import trigger_triage as tt
from trigger_triage import (
    _cron_url,
    fire_one,
    parse_cli_args,
    resolve_secrets,
    run,
    select_entries,
)

SECRET_FITNESS = "s3cret-fitness-value"  # noqa: S105 — fake test value
SECRET_TIFFANYS = "s3cret-tiffanys-value"  # noqa: S105 — fake test value

# Sentinels that must NEVER surface in engine output (report-content leak canaries).
LEAK_CANARIES = (
    "PII leak canary john.doe@example.com",
    "cluster summary canary — user reported their SSN",
    "error message canary with a token ghp_abc123",
)


# ── fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_registry():
    return {
        "apps": [
            {
                "app_slug": "fitness_app",
                "environment": "dev",
                "base_url": "TODO_fitness_dev",
                "cron_secret_env": "REPORTS_CRON_SECRET_FITNESS_APP",
                "enabled": False,
            },
            {
                "app_slug": "fitness_app",
                "environment": "prod",
                "base_url": "https://fitness.example.com/",
                "cron_secret_env": "REPORTS_CRON_SECRET_FITNESS_APP",
                "enabled": True,
            },
            {
                "app_slug": "tiffanys_space",
                "environment": "prod",
                "base_url": "https://tiffanys.example.com",
                "cron_secret_env": "REPORTS_CRON_SECRET_TIFFANYS_SPACE",
                "enabled": False,
            },
        ]
    }


@pytest.fixture
def secret_env(monkeypatch):
    monkeypatch.setenv("REPORTS_CRON_SECRET_FITNESS_APP", SECRET_FITNESS)
    monkeypatch.setenv("REPORTS_CRON_SECRET_TIFFANYS_SPACE", SECRET_TIFFANYS)


def _response(status_code: int, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    if body is None:
        resp.json.side_effect = ValueError("no body")
    else:
        resp.json.return_value = body
    return resp


def _booby_trapped_202():
    """A 202 body salted with content that must never be echoed."""
    return _response(
        202,
        {
            "id": 7,
            "app_slug": "fitness_app",
            "status": "completed",
            "total_reports": 3,
            "clusters_created": 1,
            "issues_opened": 1,
            "model_name": "claude-sonnet-4-5",
            "prompt_version": "v1",
            "error_message": LEAK_CANARIES[2],
            "clusters": [
                {"suggested_title": LEAK_CANARIES[0], "summary_markdown": LEAK_CANARIES[1]}
            ],
        },
    )


# ── registry contract (the REAL file) ───────────────────────────────────────────


class TestRealRegistryContract:
    @pytest.fixture(autouse=True)
    def _load(self):
        path = Path(__file__).resolve().parent.parent / "reports_registry.json"
        self.registry = json.loads(path.read_text(encoding="utf-8"))

    def test_exactly_the_two_apps_by_two_environments(self):
        pairs = {(e["app_slug"], e["environment"]) for e in self.registry["apps"]}
        assert pairs == {
            ("fitness_app", "dev"),
            ("fitness_app", "prod"),
            ("tiffanys_space", "dev"),
            ("tiffanys_space", "prod"),
        }

    def test_every_entry_ships_disabled(self):
        # The weekly schedule must be a no-op at birth (plan directive 8) — arming an
        # app is a deliberate registry edit, never a side effect of another change.
        assert all(e["enabled"] is False for e in self.registry["apps"])

    def test_cron_secret_env_matches_the_design_doc_names(self):
        by_slug = {
            "fitness_app": "REPORTS_CRON_SECRET_FITNESS_APP",
            "tiffanys_space": "REPORTS_CRON_SECRET_TIFFANYS_SPACE",
        }
        for e in self.registry["apps"]:
            assert e["cron_secret_env"] == by_slug[e["app_slug"]]

    def test_tiffanys_urls_are_https_and_fitness_are_todo_markers(self):
        for e in self.registry["apps"]:
            if e["app_slug"] == "tiffanys_space":
                assert e["base_url"].startswith("https://")
            else:  # fitness URLs were not derivable from the repos — see entry notes
                assert e["base_url"].startswith("TODO_")

    def test_entries_carry_required_fields(self):
        for e in self.registry["apps"]:
            assert e["environment"] in tt.ENVIRONMENTS
            assert set(e) >= {"app_slug", "environment", "base_url", "cron_secret_env", "enabled"}


# ── selection ───────────────────────────────────────────────────────────────────


class TestSelectEntries:
    def test_enabled_default_picks_only_enabled_for_the_environment(self, sample_registry):
        selected = select_entries(sample_registry, "enabled", "prod")
        assert [e["app_slug"] for e in selected] == ["fitness_app"]

    def test_enabled_selection_may_be_empty(self, sample_registry):
        assert select_entries(sample_registry, "enabled", "dev") == []

    def test_all_includes_disabled_entries(self, sample_registry):
        selected = select_entries(sample_registry, "all", "prod")
        assert {e["app_slug"] for e in selected} == {"fitness_app", "tiffanys_space"}

    def test_all_skips_todo_urls_with_a_warning_instead_of_firing(self, sample_registry, capsys):
        selected = select_entries(sample_registry, "all", "dev")
        assert selected == []
        out = capsys.readouterr().out
        assert "SKIP fitness_app (dev)" in out
        assert "TODO_" in out

    def test_explicit_slugs_are_honored(self, sample_registry):
        selected = select_entries(sample_registry, "tiffanys_space", "prod")
        assert [e["app_slug"] for e in selected] == ["tiffanys_space"]

    def test_unknown_slug_is_a_hard_error(self, sample_registry):
        with pytest.raises(SystemExit) as exc:
            select_entries(sample_registry, "fitness_app,nope", "prod")
        assert "unknown app slug" in str(exc.value)
        assert "nope" in str(exc.value)

    def test_explicit_todo_url_is_a_hard_error_not_a_skip(self, sample_registry):
        with pytest.raises(SystemExit) as exc:
            select_entries(sample_registry, "fitness_app", "dev")
        assert "TODO_" in str(exc.value)
        assert "Nothing was fired" in str(exc.value)

    def test_unknown_environment_is_a_hard_error(self, sample_registry):
        sample_registry["apps"] = [
            e for e in sample_registry["apps"] if e["environment"] != "dev"
        ]
        with pytest.raises(SystemExit):
            select_entries(sample_registry, "all", "dev")


# ── secret resolution ───────────────────────────────────────────────────────────


class TestResolveSecrets:
    def test_resolves_and_dedupes_by_env_name(self, sample_registry, secret_env):
        entries = select_entries(sample_registry, "all", "prod")
        secrets = resolve_secrets(entries)
        assert secrets == {
            "REPORTS_CRON_SECRET_FITNESS_APP": SECRET_FITNESS,
            "REPORTS_CRON_SECRET_TIFFANYS_SPACE": SECRET_TIFFANYS,
        }

    def test_missing_env_aborts_and_never_names_a_value(self, sample_registry, monkeypatch):
        monkeypatch.delenv("REPORTS_CRON_SECRET_FITNESS_APP", raising=False)
        entries = select_entries(sample_registry, "all", "prod")
        with pytest.raises(SystemExit) as exc:
            resolve_secrets(entries)
        msg = str(exc.value)
        assert "REPORTS_CRON_SECRET_FITNESS_APP is not set" in msg
        assert "Nothing was fired" in msg

    def test_whitespace_only_value_counts_as_missing(self, sample_registry, monkeypatch):
        monkeypatch.setenv("REPORTS_CRON_SECRET_FITNESS_APP", "   ")
        with pytest.raises(SystemExit):
            resolve_secrets(select_entries(sample_registry, "fitness_app", "prod"))


# ── firing one app ──────────────────────────────────────────────────────────────


class TestFireOne:
    @pytest.fixture(autouse=True)
    def _mock_session(self, monkeypatch):
        self.session = MagicMock()
        monkeypatch.setattr(tt, "_SESSION", self.session)

    def _entry(self, base_url="https://fitness.example.com/"):
        return {
            "app_slug": "fitness_app",
            "environment": "prod",
            "base_url": base_url,
            "cron_secret_env": "REPORTS_CRON_SECRET_FITNESS_APP",
            "enabled": True,
        }

    def test_url_join_strips_trailing_slash_and_header_carries_the_secret(self):
        self.session.post.return_value = _response(202, {"id": 1})
        assert fire_one(self._entry(), SECRET_FITNESS) is True
        _, kwargs = self.session.post.call_args
        url = self.session.post.call_args[0][0]
        assert url == "https://fitness.example.com/reports/triage/cron"
        assert kwargs["headers"] == {"X-Cron-Secret": SECRET_FITNESS}
        assert kwargs["timeout"] == tt.REQUEST_TIMEOUT

    def test_202_prints_only_whitelisted_metadata(self, capsys):
        self.session.post.return_value = _booby_trapped_202()
        assert fire_one(self._entry(), SECRET_FITNESS) is True
        out = capsys.readouterr().out
        assert "accepted (202)" in out
        assert "total_reports=3" in out
        assert "issues_opened=1" in out
        for canary in LEAK_CANARIES:
            assert canary not in out
        assert SECRET_FITNESS not in out

    def test_202_with_unparseable_body_is_still_success(self, capsys):
        self.session.post.return_value = _response(202)
        assert fire_one(self._entry(), SECRET_FITNESS) is True
        assert "metadata unavailable" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("status", "fragment"),
        [
            (401, "mismatch"),
            (409, "already running"),
            (503, "fail-closed"),
            (207, "partial_link"),
            (429, "rate-limited"),
            (504, "timed out"),
            (400, "rejected"),
        ],
    )
    def test_known_failure_statuses_map_to_fixed_hints(self, capsys, status, fragment):
        self.session.post.return_value = _response(status, {"detail": LEAK_CANARIES[0]})
        assert fire_one(self._entry(), SECRET_FITNESS) is False
        out = capsys.readouterr().out
        assert f"HTTP {status}" in out
        assert fragment in out
        # The body is NEVER echoed on failure — fixed interpretations only.
        assert LEAK_CANARIES[0] not in out

    def test_unknown_status_prints_generic_hint_without_the_body(self, capsys):
        self.session.post.return_value = _response(500, {"detail": LEAK_CANARIES[1]})
        assert fire_one(self._entry(), SECRET_FITNESS) is False
        out = capsys.readouterr().out
        assert "HTTP 500" in out
        assert "unexpected status" in out
        assert LEAK_CANARIES[1] not in out

    def test_connection_error_prints_type_name_only(self, capsys):
        self.session.post.side_effect = ConnectionError(
            f"boom {SECRET_FITNESS} in exception text"
        )
        assert fire_one(self._entry(), SECRET_FITNESS) is False
        out = capsys.readouterr().out
        assert "could not reach the app" in out
        assert "ConnectionError" in out
        assert SECRET_FITNESS not in out


# ── run orchestration ───────────────────────────────────────────────────────────


class TestRun:
    @pytest.fixture(autouse=True)
    def _mock_session(self, monkeypatch):
        self.session = MagicMock()
        monkeypatch.setattr(tt, "_SESSION", self.session)

    def test_empty_selection_is_a_green_no_op(self, capsys):
        assert run([], "prod", dry_run=False) == 0
        out = capsys.readouterr().out
        assert "Nothing to fire" in out
        assert "RESULT: ok=0 failed=0" in out
        self.session.post.assert_not_called()

    def test_dry_run_validates_secrets_but_never_posts(
        self, sample_registry, secret_env, capsys
    ):
        entries = select_entries(sample_registry, "all", "prod")
        assert run(entries, "prod", dry_run=True) == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "REPORTS_CRON_SECRET_FITNESS_APP present" in out
        assert SECRET_FITNESS not in out
        assert SECRET_TIFFANYS not in out
        self.session.post.assert_not_called()

    def test_dry_run_still_fails_on_a_missing_secret(self, sample_registry, monkeypatch):
        monkeypatch.setenv("REPORTS_CRON_SECRET_FITNESS_APP", SECRET_FITNESS)
        monkeypatch.delenv("REPORTS_CRON_SECRET_TIFFANYS_SPACE", raising=False)
        entries = select_entries(sample_registry, "all", "prod")
        with pytest.raises(SystemExit):
            run(entries, "prod", dry_run=True)
        self.session.post.assert_not_called()

    def test_secrets_resolve_before_the_first_post(self, sample_registry, monkeypatch):
        # Fitness resolves, tiffanys is missing -> the run aborts with ZERO posts fired,
        # even though the fitness entry alone was fireable.
        monkeypatch.setenv("REPORTS_CRON_SECRET_FITNESS_APP", SECRET_FITNESS)
        monkeypatch.delenv("REPORTS_CRON_SECRET_TIFFANYS_SPACE", raising=False)
        entries = select_entries(sample_registry, "all", "prod")
        with pytest.raises(SystemExit):
            run(entries, "prod", dry_run=False)
        self.session.post.assert_not_called()

    def test_per_app_failures_aggregate_without_aborting_the_fanout(
        self, sample_registry, secret_env, capsys
    ):
        self.session.post.side_effect = [_response(202, {"id": 1}), _response(401)]
        entries = select_entries(sample_registry, "all", "prod")
        assert run(entries, "prod", dry_run=False) == 1
        out = capsys.readouterr().out
        assert self.session.post.call_count == 2
        assert "RESULT: ok=1 failed=1" in out
        assert "never status-retried" in out

    def test_all_success_returns_zero(self, sample_registry, secret_env, capsys):
        self.session.post.return_value = _response(202, {"id": 1, "total_reports": 0})
        entries = select_entries(sample_registry, "all", "prod")
        assert run(entries, "prod", dry_run=False) == 0
        assert "RESULT: ok=2 failed=0" in capsys.readouterr().out


# ── transport + CLI contracts ───────────────────────────────────────────────────


class TestTransportContract:
    def test_posts_are_never_status_retried(self):
        # Pins the design: build_session() retries statuses only for GET/PUT/HEAD, so a
        # 502-that-actually-triaged can never double-fire a batch (module docstring).
        adapter = tt._SESSION.get_adapter("https://example.com")
        allowed = {m.upper() for m in adapter.max_retries.allowed_methods}
        assert "POST" not in allowed

    def test_cron_url_handles_base_without_trailing_slash(self):
        assert (
            _cron_url({"base_url": "https://x.example"})
            == "https://x.example/reports/triage/cron"
        )


class TestParseCliArgs:
    def test_defaults(self):
        args = parse_cli_args(["--environment", "prod"])
        assert args.apps == "enabled"
        assert args.environment == "prod"
        assert args.dry_run is False

    def test_environment_is_required_and_choice_checked(self):
        with pytest.raises(SystemExit):
            parse_cli_args([])
        with pytest.raises(SystemExit):
            parse_cli_args(["--environment", "staging"])
