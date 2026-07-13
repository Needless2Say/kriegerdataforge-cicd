"""
Unit tests for scripts/distribute_app_secrets.py (the App-credential distribution engine).

All GitHub I/O is mocked. The security-critical invariants get explicit regression tests:
values never appear in output, validation failures name the shape (not the value), and a
missing/mis-wired source env aborts BEFORE any write.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import distribute_app_secrets as das
from distribute_app_secrets import (
    _distributable,
    _looks_valid,
    _select_entries,
    _target_repos,
    cmd_check,
    cmd_execute,
    cmd_targets,
    list_repo_secret_meta,
)

# ── fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_registry():
    return {
        "secrets": [
            {
                # A rotation-engine secret that must NEVER be writable via this engine.
                "name": "VERCEL_DEPLOYMENT_TOKEN",
                "kind": "generate",
                "github_repo_secrets": [
                    {"repo": "Needless2Say/r1", "secret_name": "VERCEL_DEPLOYMENT_TOKEN"},
                ],
            },
            {
                "name": "KDF_APP_ID",
                "kind": "distribute",
                "distribute_source_env": "KDF_APP_ID",
                "value_format": "numeric",
                "github_repo_secrets": [
                    {"repo": "Needless2Say/r1", "secret_name": "KDF_APP_ID"},
                    {"repo": "Needless2Say/r2", "secret_name": "KDF_APP_ID"},
                ],
            },
            {
                "name": "KDF_APP_PRIVATE_KEY",
                "kind": "manual",
                "distribute_source_env": "KDF_APP_PRIVATE_KEY",
                "value_format": "pem",
                "github_repo_secrets": [
                    {"repo": "Needless2Say/r1", "secret_name": "KDF_APP_PRIVATE_KEY"},
                ],
            },
        ]
    }


@pytest.fixture
def entries(sample_registry):
    return _distributable(sample_registry)


PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIexampleexample\n-----END RSA PRIVATE KEY-----\n"


@pytest.fixture
def source_env(monkeypatch):
    monkeypatch.setenv("KDF_APP_ID", "123456")
    monkeypatch.setenv("KDF_APP_PRIVATE_KEY", PEM)


# ── selection ───────────────────────────────────────────────────────────────────


def test_distributable_keeps_only_entries_with_a_source_env(sample_registry):
    names = [e["name"] for e in _distributable(sample_registry)]
    assert names == ["KDF_APP_ID", "KDF_APP_PRIVATE_KEY"]


def test_select_entries_all_and_named(sample_registry):
    assert len(_select_entries(sample_registry, "all")) == 2
    assert len(_select_entries(sample_registry, "")) == 2
    only = _select_entries(sample_registry, "kdf_app_id")
    assert [e["name"] for e in only] == ["KDF_APP_ID"]


def test_select_entries_refuses_unknown_name(sample_registry):
    with pytest.raises(SystemExit) as exc:
        _select_entries(sample_registry, "NOPE")
    assert "not distributable" in str(exc.value)


def test_select_entries_refuses_rotation_engine_secrets(sample_registry):
    """A registry entry WITHOUT distribute_source_env must be refused even though it
    exists — this engine must never become a second write path for rotation secrets."""
    with pytest.raises(SystemExit) as exc:
        _select_entries(sample_registry, "VERCEL_DEPLOYMENT_TOKEN")
    assert "not distributable" in str(exc.value)


def test_target_repos_is_the_sorted_union(entries):
    assert _target_repos(entries) == ["Needless2Say/r1", "Needless2Say/r2"]


# ── value shape checks ──────────────────────────────────────────────────────────


def test_looks_valid_numeric():
    assert _looks_valid("123456", "numeric")
    assert not _looks_valid("12a", "numeric")
    assert not _looks_valid(PEM, "numeric")


def test_looks_valid_pem():
    assert _looks_valid(PEM, "pem")
    assert not _looks_valid("123456", "pem")


def test_looks_valid_unknown_format_is_a_no_op():
    assert _looks_valid("anything", "")
    assert _looks_valid("anything", "hex")


# ── targets mode ────────────────────────────────────────────────────────────────


def test_cmd_targets_prints_short_names(sample_registry, capsys):
    assert cmd_targets(sample_registry) == 0
    assert capsys.readouterr().out.strip() == "r1,r2"


# ── check mode ──────────────────────────────────────────────────────────────────


def _session_returning(payload_by_repo):
    """A fake session whose .get() answers per-repo from `payload_by_repo`."""
    session = MagicMock()

    def _get(url, **kwargs):
        resp = MagicMock()
        for repo, secrets in payload_by_repo.items():
            if f"/repos/{repo}/actions/secrets" in url:
                if isinstance(secrets, Exception):
                    resp.raise_for_status.side_effect = secrets
                else:
                    resp.json.return_value = {"secrets": secrets}
                return resp
        raise AssertionError(f"unexpected URL {url}")

    session.get.side_effect = _get
    return session


def test_cmd_check_reports_present_and_missing(entries, capsys, monkeypatch):
    monkeypatch.setattr(
        das,
        "_SESSION",
        _session_returning(
            {
                # r1 holds only the id — the key is missing.
                "Needless2Say/r1": [{"name": "KDF_APP_ID", "updated_at": "2026-07-01T00:00:00Z"}],
                # r2 is only a KDF_APP_ID target and holds it.
                "Needless2Say/r2": [{"name": "KDF_APP_ID", "updated_at": "2026-07-02T00:00:00Z"}],
            }
        ),
    )
    assert cmd_check(entries, "tok") == 0
    out = capsys.readouterr().out
    assert "KDF_APP_ID: present (updated 2026-07-01T00:00:00Z)" in out
    assert "KDF_APP_PRIVATE_KEY: MISSING" in out
    assert "MISSING: 1" in out
    # r2 is not a KDF_APP_PRIVATE_KEY target, so no PRIVATE_KEY line may appear for it.
    r2_block = out.split("Needless2Say/r2:", 1)[1]
    assert "KDF_APP_PRIVATE_KEY" not in r2_block.split("MISSING:")[0]


def test_cmd_check_api_error_is_a_failure(entries, capsys, monkeypatch):
    monkeypatch.setattr(
        das,
        "_SESSION",
        _session_returning(
            {
                "Needless2Say/r1": RuntimeError("403 forbidden"),
                "Needless2Say/r2": [{"name": "KDF_APP_ID", "updated_at": "x"}],
            }
        ),
    )
    assert cmd_check(entries, "tok") == 1
    out = capsys.readouterr().out
    assert "ERROR listing secrets" in out
    assert "could not be audited" in out


def test_cmd_check_requires_token(entries):
    with pytest.raises(SystemExit) as exc:
        cmd_check(entries, "")
    assert "GH_TOKEN" in str(exc.value)


def test_list_repo_secret_meta_maps_names(monkeypatch):
    monkeypatch.setattr(
        das,
        "_SESSION",
        _session_returning({"Needless2Say/r1": [{"name": "A", "updated_at": "t1"}, {"name": "B"}]}),
    )
    assert list_repo_secret_meta("tok", "Needless2Say/r1") == {"A": "t1", "B": "?"}


# ── execute mode ────────────────────────────────────────────────────────────────


def test_cmd_execute_writes_every_target(entries, source_env, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        das,
        "update_github_repo_secret",
        lambda tok, repo, name, value: calls.append((tok, repo, name, value)),
    )
    assert cmd_execute(entries, "tok") == 0
    assert ("tok", "Needless2Say/r1", "KDF_APP_ID", "123456") in calls
    assert ("tok", "Needless2Say/r2", "KDF_APP_ID", "123456") in calls
    assert ("tok", "Needless2Say/r1", "KDF_APP_PRIVATE_KEY", PEM) in calls
    assert len(calls) == 3
    assert "All targets updated successfully." in capsys.readouterr().out


def test_cmd_execute_missing_env_aborts_before_any_write(entries, capsys, monkeypatch):
    monkeypatch.delenv("KDF_APP_ID", raising=False)
    monkeypatch.setenv("KDF_APP_PRIVATE_KEY", PEM)
    written = []
    monkeypatch.setattr(
        das, "update_github_repo_secret", lambda *a: written.append(a)
    )
    with pytest.raises(SystemExit) as exc:
        cmd_execute(entries, "tok")
    assert "KDF_APP_ID is not set" in str(exc.value)
    assert "Nothing was written" in str(exc.value)
    assert written == []


def test_cmd_execute_swapped_values_refused_and_value_never_leaks(
    entries, capsys, monkeypatch
):
    """A PEM wired into KDF_APP_ID (classic swapped-env mistake) must abort before any
    write, and the error must name the expected SHAPE — never echo the value."""
    monkeypatch.setenv("KDF_APP_ID", PEM)
    monkeypatch.setenv("KDF_APP_PRIVATE_KEY", PEM)
    written = []
    monkeypatch.setattr(
        das, "update_github_repo_secret", lambda *a: written.append(a)
    )
    with pytest.raises(SystemExit) as exc:
        cmd_execute(entries, "tok")
    message = str(exc.value)
    assert "does not look like an all-digits GitHub App id" in message
    assert PEM not in message
    assert "MIIexampleexample" not in message
    assert written == []


def test_cmd_execute_partial_failure_aggregates_and_continues(
    entries, source_env, capsys, monkeypatch
):
    def _update(tok, repo, name, value):
        if repo == "Needless2Say/r1" and name == "KDF_APP_ID":
            raise RuntimeError("boom")

    monkeypatch.setattr(das, "update_github_repo_secret", _update)
    assert cmd_execute(entries, "tok") == 1
    out = capsys.readouterr().out
    assert "FAILED - boom" in out
    # the failure did not stop the rest of the fan-out
    assert out.count("OK") == 2
    assert "1 target(s) failed" in out


def test_cmd_execute_output_never_contains_a_value(entries, source_env, capsys, monkeypatch):
    monkeypatch.setattr(das, "update_github_repo_secret", lambda *a: None)
    cmd_execute(entries, "tok")
    out = capsys.readouterr().out
    assert "123456" not in out
    assert "MIIexampleexample" not in out


def test_cmd_execute_requires_token(entries, source_env):
    with pytest.raises(SystemExit) as exc:
        cmd_execute(entries, "")
    assert "GH_TOKEN" in str(exc.value)


# ── the real registry (drift guards binding data <-> engine expectations) ────────


def _real_registry():
    return json.loads(das.REGISTRY_FILE.read_text(encoding="utf-8"))


def test_real_registry_carries_both_app_secret_entries():
    by_name = {e["name"]: e for e in _distributable(_real_registry())}
    assert set(by_name) == {"KDF_APP_ID", "KDF_APP_PRIVATE_KEY"}
    assert by_name["KDF_APP_ID"]["value_format"] == "numeric"
    assert by_name["KDF_APP_PRIVATE_KEY"]["value_format"] == "pem"
    # the pair must travel together: identical target sets
    id_targets = {t["repo"] for t in by_name["KDF_APP_ID"]["github_repo_secrets"]}
    key_targets = {t["repo"] for t in by_name["KDF_APP_PRIVATE_KEY"]["github_repo_secrets"]}
    assert id_targets == key_targets
    # the source repo must never be a target (it holds the originals)
    assert "Needless2Say/kriegerdataforge-cicd" not in id_targets
    # every target writes the same-named secret (consumers read KDF_APP_ID/KDF_APP_PRIVATE_KEY)
    for entry in by_name.values():
        assert all(t["secret_name"] == entry["name"] for t in entry["github_repo_secrets"])


def test_real_registry_covers_the_epic_consumers():
    """Wave 2.5 contract: the six E2E-journey repos + both package repos + the four
    templates hold App-credential copies (superset of ops-setup-e2e's allow-list)."""
    targets = {
        t["repo"]
        for e in _distributable(_real_registry())
        for t in e["github_repo_secrets"]
    }
    expected = {
        "Needless2Say/kriegerdataforge",
        "Needless2Say/kriegerdataforge-auth-ui",
        "Needless2Say/fitness-app-frontend",
        "Needless2Say/fitness-app-backend",
        "Needless2Say/tiffanys-space",
        "Needless2Say/tiffanys-space-backend",
        "Needless2Say/kriegerdataforge-reports-sdk",
        "Needless2Say/kriegerdataforge-report-form",
        "Needless2Say/kriegerdataforge-template-fastapi",
        "Needless2Say/kriegerdataforge-template-nextjs",
        "Needless2Say/kriegerdataforge-template-npm-package",
        "Needless2Say/kriegerdataforge-template-python-package",
    }
    assert targets == expected


def test_real_registry_gh_packages_pat_covers_the_reports_sdk_repo():
    """reports-sdk CI installs kdf_sdk via git+https, so the PAT fallback must reach it
    (the exact gap cicd PR #84 fixed for the first four SDK consumers)."""
    registry = _real_registry()
    pat = next(e for e in registry["secrets"] if e["name"] == "GH_PACKAGES_PAT")
    repos = {t["repo"] for t in pat["github_repo_secrets"]}
    assert "Needless2Say/kriegerdataforge-reports-sdk" in repos
