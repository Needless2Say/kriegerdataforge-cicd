"""
Unit tests for the kit-only-PR exemption in scripts/common/check_version.py
(ADR D-001 option B). The version-comparison logic itself is exercised by the
consumer repos' CI; here we cover the exemption gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import common.check_version as cv


def test_not_a_pr_runs_normal_check():
    # No GITHUB_BASE_REF (local run / push) → not exempt.
    with patch.dict(cv.os.environ, {}, clear=True):
        assert cv._is_kit_only_pr(Path(".")) is False


def test_all_kit_paths_is_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(
            cv,
            "_changed_files",
            return_value=["skills.md", "WORKFLOW.md", "docs/agent/DEFINITION_OF_DONE.md"],
        ),
    ):
        assert cv._is_kit_only_pr(tmp_path) is True


def test_mixed_paths_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value=["skills.md", "src/app.py"]),
    ):
        assert cv._is_kit_only_pr(tmp_path) is False


def test_non_kit_path_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value=["VERSION"]),
    ):
        assert cv._is_kit_only_pr(tmp_path) is False


def test_empty_diff_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value=[]),
    ):
        assert cv._is_kit_only_pr(tmp_path) is False


def test_docs_agent_templates_are_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(
            cv,
            "_changed_files",
            return_value=["docs/agent/templates/adr-entry.template.md"],
        ),
    ):
        assert cv._is_kit_only_pr(tmp_path) is True


# ── registry-derived exemption (drift-proof) ─────────────────────────────────


def test_kit_exempt_files_includes_registry_files():
    """The exempt set is derived from the real kit registry beside the script."""
    registry = json.loads(cv._REGISTRY_FILE.read_text(encoding="utf-8"))
    exempt = cv._kit_exempt_files()
    for f in registry["files"]:
        assert f in exempt, f"registry file {f!r} missing from the derived exempt set"


def test_real_registry_is_fully_kit_only(tmp_path):
    """A PR touching exactly the synced kit files is recognized as kit-only."""
    registry = json.loads(cv._REGISTRY_FILE.read_text(encoding="utf-8"))
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value=list(registry["files"])),
    ):
        assert cv._is_kit_only_pr(tmp_path) is True


def test_future_kit_file_outside_docs_agent_auto_exempt(tmp_path):
    """A kit file added to the registry OUTSIDE docs/agent/ is auto-exempt (no drift)."""
    reg = tmp_path / "kit_registry.json"
    reg.write_text(
        json.dumps({"files": ["skills.md", "WORKFLOW.md", "AGENTS_KIT.md"]}),
        encoding="utf-8",
    )
    with (
        patch.object(cv, "_REGISTRY_FILE", reg),
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value=["AGENTS_KIT.md"]),
    ):
        assert cv._is_kit_only_pr(tmp_path) is True


def test_fallback_when_registry_unreadable(tmp_path):
    """If the registry isn't co-located, fall back to the static set (no regression)."""
    missing = tmp_path / "no-registry.json"
    with patch.object(cv, "_REGISTRY_FILE", missing):
        assert cv._kit_exempt_files() == cv.KIT_EXEMPT_FILES_FALLBACK
        with (
            patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
            patch.object(cv, "_changed_files", return_value=["skills.md", "WORKFLOW.md"]),
        ):
            assert cv._is_kit_only_pr(tmp_path) is True
