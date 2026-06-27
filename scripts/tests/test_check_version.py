"""
Unit tests for the kit-only-PR exemption in scripts/common/check_version.py
(ADR D-001 option B). The version-comparison logic itself is exercised by the
consumer repos' CI; here we cover the exemption gate.
"""

from __future__ import annotations

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
