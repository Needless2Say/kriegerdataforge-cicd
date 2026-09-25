"""
Unit tests for scripts/common/bump_version.py — the origin/main-based bump that
makes accidental double-bumps (0.10.6 -> 0.10.8) impossible.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import common.bump_version as bv
import pytest


def _run_bump(tmp_path, bump_type: str, base: tuple[str, str] = ("0.10.6", "origin/main")) -> None:
    argv = ["bump_version.py", bump_type, "--root", str(tmp_path)]
    with (
        patch.object(bv.sys, "argv", argv),
        patch.object(bv, "get_base_version", return_value = base),
    ):
        bv.main()


# ── Pure helpers ─────────────────────────────────────────────────────────────
def test_bump_arithmetic():
    assert bv.bump((0, 10, 6), "patch") == (0, 10, 7)
    assert bv.bump((0, 10, 6), "minor") == (0, 11, 0)
    assert bv.bump((0, 10, 6), "major") == (1, 0, 0)


def test_parse_version_rejects_malformed():
    for bad in ("1.2", "1.2.3.4", "a.b.c"):
        with pytest.raises(ValueError):
            bv.parse_version(bad)


# ── Origin/main basis (the double-bump fix) ──────────────────────────────────
def test_bump_patch_is_idempotent(tmp_path):
    """
    Running `make bump-patch` twice must stay ONE increment ahead of main —
    the exact failure that produced 0.10.6 -> 0.10.8.
    """
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"


def test_bump_minor_after_patch_corrects_not_stacks(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.7\n", encoding = "utf-8")   # already patch-bumped
    _run_bump(tmp_path, "minor")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.11.0"


def test_bump_repairs_an_invalid_local_version(tmp_path, capsys):
    # Local VERSION drifted to an invalid 0.10.8; bump-patch rebases onto main.
    (tmp_path / "VERSION").write_text("0.10.8\n", encoding = "utf-8")
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"
    assert "rebasing the bump onto origin/main" in capsys.readouterr().out


def test_bump_writes_all_detected_targets(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "0.10.6"\n', encoding = "utf-8")
    (tmp_path / "vercel_api").mkdir()
    (tmp_path / "vercel_api" / "pyproject.toml").write_text('version = "0.10.6"\n', encoding = "utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "0.10.6"}), encoding = "utf-8")
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"version": "0.10.6", "packages": {"": {"version": "0.10.6"}}}),
        encoding = "utf-8",
    )
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"
    assert '"0.10.7"' in (tmp_path / "pyproject.toml").read_text(encoding = "utf-8")
    assert '"0.10.7"' in (tmp_path / "vercel_api" / "pyproject.toml").read_text(encoding = "utf-8")
    assert json.loads((tmp_path / "package.json").read_text(encoding = "utf-8"))["version"] == "0.10.7"
    lock = json.loads((tmp_path / "package-lock.json").read_text(encoding = "utf-8"))
    assert lock["version"] == "0.10.7"
    assert lock["packages"][""]["version"] == "0.10.7"


# ── Fallback when origin/main is unreadable ──────────────────────────────────
def test_get_base_version_reads_origin(tmp_path):
    show = MagicMock(returncode = 0, stdout = "0.10.6\n")
    with patch.object(bv.subprocess, "run", side_effect = [MagicMock(), show]):
        assert bv.get_base_version(tmp_path, "main") == ("0.10.6", "origin/main")


def test_get_base_version_falls_back_to_local(tmp_path, capsys):
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    failed = MagicMock(returncode = 128, stdout = "")
    with patch.object(bv.subprocess, "run", side_effect = [MagicMock(), failed]):
        assert bv.get_base_version(tmp_path, "main") == ("0.10.6", "local")
    assert "WARNING: could not read VERSION from origin/main" in capsys.readouterr().out


def test_local_fallback_still_bumps(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    _run_bump(tmp_path, "patch", base = ("0.10.6", "local"))
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"


# ── A FastAPI app's committed openapi.json ───────────────────────────────────
def _spec(version: str) -> dict:
    """
    A document shaped like FastAPI's ``app.openapi()``, "openapi" then "info". The description quotes a version and
    a schema example carries a "version" key, and neither may move.
    """
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "x",
            "description": 'Reports its "version": "0.0.1" on GET /version',
            "version": version,
        },
        "paths": {},
        "components": {
            "schemas": {
                "VersionResponse": {
                    "properties": {"version": {"type": "string"}},
                    "example": {"version": "9.9.9"},
                },
            },
        },
    }


def _generated(spec: dict) -> str:
    """
    The text a repo's ``generate_openapi.py`` writes, ``json.dump(spec, f, indent=2)`` with no trailing newline.
    """
    return json.dumps(spec, indent = 2)


def _fastapi_repo(tmp_path, version: str, spec_version: str) -> None:
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding = "utf-8")
    (tmp_path / "openapi.json").write_text(_generated(_spec(spec_version)), encoding = "utf-8")


def _spec_text(tmp_path) -> str:
    return (tmp_path / "openapi.json").read_text(encoding = "utf-8")


def test_bump_moves_a_spec_that_carries_version(tmp_path):
    """
    The hub's shape, its app reads VERSION. Only info.version moves, so a byte for byte spec test still holds.
    """
    _fastapi_repo(tmp_path, "0.10.6", "0.10.6")
    _run_bump(tmp_path, "patch")
    assert _spec_text(tmp_path) == _generated(_spec("0.10.7"))


def test_bump_leaves_a_spec_with_its_own_version_alone(tmp_path, capsys):
    """
    fitness-app-backend's shape, its app publishes a literal 1.0.0, and moving the spec would fail its spec test.
    """
    _fastapi_repo(tmp_path, "0.10.6", "1.0.0")
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"
    assert _spec_text(tmp_path) == _generated(_spec("1.0.0"))
    assert "Left alone: openapi.json carries 1.0.0" in capsys.readouterr().out


def test_bump_twice_leaves_the_spec_one_increment_ahead(tmp_path):
    _fastapi_repo(tmp_path, "0.10.6", "0.10.6")
    _run_bump(tmp_path, "patch")
    _run_bump(tmp_path, "patch")
    assert _spec_text(tmp_path) == _generated(_spec("0.10.7"))


def test_bump_minor_after_patch_moves_the_spec_from_the_local_version(tmp_path):
    # already patch bumped on the branch, so the spec carries the local VERSION rather than main's
    _fastapi_repo(tmp_path, "0.10.7", "0.10.7")
    _run_bump(tmp_path, "minor")
    assert _spec_text(tmp_path) == _generated(_spec("0.11.0"))


def test_a_spec_the_bump_cannot_move_stops_it_before_any_write(tmp_path):
    # hand ordered, so the schema example's "version" comes first
    spec      = _spec("0.10.6")
    reordered = json.dumps({"components": spec["components"], "openapi": spec["openapi"], "info": spec["info"]})
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    (tmp_path / "openapi.json").write_text(reordered, encoding = "utf-8")

    with pytest.raises(SystemExit, match = "not info.version"):
        _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.6"
    assert _spec_text(tmp_path) == reordered


def test_a_spec_without_info_version_stops_the_bump(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    (tmp_path / "openapi.json").write_text("{}", encoding = "utf-8")
    with pytest.raises(SystemExit, match = "no info.version"):
        _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.6"


# ── Guard rails ──────────────────────────────────────────────────────────────
def test_missing_version_file_fails(tmp_path):
    argv = ["bump_version.py", "patch", "--root", str(tmp_path)]
    with patch.object(bv.sys, "argv", argv), pytest.raises(SystemExit):
        bv.main()


def test_bom_tolerated(tmp_path):
    (tmp_path / "VERSION").write_bytes(b"\xef\xbb\xbf0.10.6\n")
    _run_bump(tmp_path, "patch")
    assert (tmp_path / "VERSION").read_text(encoding = "utf-8").strip() == "0.10.7"
