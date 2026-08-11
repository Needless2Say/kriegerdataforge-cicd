"""
Unit tests for scripts/common/check_version.py: the STRICT single-increment rule
(the gate that catches invalid jumps like 0.10.6 -> 0.10.8), the target-consistency
pass, and the sync-PR exemption (ADR D-001 option B, extended to script sync by
ADR D-013).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import common.check_version as cv
import pytest


# ── Strict increment rule ────────────────────────────────────────────────────
def _is_valid_jump(base: str, head: str) -> bool:
    return cv._parse_semver(head) in cv._allowed_next(cv._parse_semver(base))


@pytest.mark.parametrize("head", ["0.10.7", "0.11.0", "1.0.0"])
def test_valid_single_increments_accepted(head):
    assert _is_valid_jump("0.10.6", head) is True


@pytest.mark.parametrize(
    "head",
    [
        "0.10.8",   # patch skip (+2) — the jump that escaped
        "0.11.1",   # minor without patch reset
        "0.12.0",   # minor skip
        "1.1.0",    # major without minor reset
        "1.0.1",    # major without patch reset
        "2.0.0",    # major skip
        "0.10.6",   # no bump
        "0.10.5",   # downgrade
        "0.9.9",    # downgrade
    ],
)
def test_invalid_jumps_rejected(head):
    assert _is_valid_jump("0.10.6", head) is False


def test_allowed_next_lists_exactly_three():
    assert cv._allowed_next((0, 10, 6)) == [(0, 10, 7), (0, 11, 0), (1, 0, 0)]


def test_parse_semver_rejects_malformed():
    for bad in ("1.2", "1.2.3.4", "a.b.c", ""):
        with pytest.raises(ValueError):
            cv._parse_semver(bad)


# ── End-to-end main() in a temp repo ─────────────────────────────────────────
def _run_main(tmp_path: Path, base_version: str | None) -> int | None:
    """
    Run cv.main() against tmp_path with the git base mocked. Returns the SystemExit
    code (or None when main returned normally = passed).
    """
    argv = ["check_version.py", "--root", str(tmp_path)]
    with (
        patch.object(cv.sys, "argv", argv),
        patch.dict(cv.os.environ, {}, clear = True),   # not a PR -> no exemption path
        patch.object(cv, "_fetch_base"),
        patch.object(cv, "_get_base_version", return_value = base_version),
    ):
        try:
            cv.main()
        except SystemExit as exc:
            return exc.code
    return None


def test_main_passes_on_valid_patch_bump(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.7\n", encoding = "utf-8")
    assert _run_main(tmp_path, "0.10.6") is None


def test_main_fails_on_plus_two_jump(tmp_path, capsys):
    # THE bug this feature exists for: 0.10.6 -> 0.10.8 must fail.
    (tmp_path / "VERSION").write_text("0.10.8\n", encoding = "utf-8")
    assert _run_main(tmp_path, "0.10.6") == 1
    out = capsys.readouterr().out
    assert "invalid version jump 0.10.6 -> 0.10.8" in out
    assert "0.10.7, 0.11.0, 1.0.0" in out   # the allowed next versions are named


def test_main_fails_on_no_bump(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.6\n", encoding = "utf-8")
    assert _run_main(tmp_path, "0.10.6") == 1


def test_main_warns_and_passes_when_base_unreadable(tmp_path, capsys):
    # Fresh clone / offline: the increment check is skipped, not failed.
    (tmp_path / "VERSION").write_text("0.10.8\n", encoding = "utf-8")
    assert _run_main(tmp_path, None) is None
    assert "WARNING: could not read VERSION" in capsys.readouterr().out


def test_main_fails_on_target_mismatch(tmp_path):
    # Auto-detected package.json disagreeing with VERSION fails without any flags.
    (tmp_path / "VERSION").write_text("0.10.7\n", encoding = "utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "0.10.6"}), encoding = "utf-8")
    assert _run_main(tmp_path, "0.10.6") == 1


def test_main_passes_with_matching_targets(tmp_path):
    (tmp_path / "VERSION").write_text("0.10.7\n", encoding = "utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"version": "0.10.7"}), encoding = "utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "0.10.7"\n', encoding = "utf-8")
    assert _run_main(tmp_path, "0.10.6") is None


def test_main_accepts_legacy_flags(tmp_path):
    # Consumer ci.yml files still pass --skip-init / --check-package-json.
    (tmp_path / "VERSION").write_text("0.10.7\n", encoding = "utf-8")
    argv = ["check_version.py", "--root", str(tmp_path), "--skip-init", "--check-package-json"]
    with (
        patch.object(cv.sys, "argv", argv),
        patch.dict(cv.os.environ, {}, clear = True),
        patch.object(cv, "_fetch_base"),
        patch.object(cv, "_get_base_version", return_value = "0.10.6"),
    ):
        cv.main()   # no SystemExit


# ── Sync-PR exemption gate ───────────────────────────────────────────────────
def test_not_a_pr_runs_normal_check():
    # No GITHUB_BASE_REF (local run / push) → not exempt.
    with patch.dict(cv.os.environ, {}, clear = True):
        assert cv._is_exempt_sync_pr(Path(".")) is False


def test_all_kit_paths_is_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(
            cv,
            "_changed_files",
            return_value = ["skills.md", "WORKFLOW.md", "docs/agent/DEFINITION_OF_DONE.md"],
        ),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True


def test_all_script_paths_is_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(
            cv,
            "_changed_files",
            return_value = ["scripts/check_version.py", "scripts/bump_version.py", "scripts/version_targets.py"],
        ),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True


def test_makefile_exempt_only_on_scripts_sync_branch(tmp_path):
    changed = ["scripts/check_version.py", "Makefile"]
    with (
        patch.dict(
            cv.os.environ,
            {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": "chore/scripts-sync-1.0.0"},
        ),
        patch.object(cv, "_changed_files", return_value = changed),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True
    # The SAME diff on an ordinary branch must NOT dodge the version gate.
    with (
        patch.dict(
            cv.os.environ,
            {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": "feature/tweak-makefile"},
        ),
        patch.object(cv, "_changed_files", return_value = changed),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False


def test_makefile_only_pr_not_exempt_off_sync_branch(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": "fix/makefile"}),
        patch.object(cv, "_changed_files", return_value = ["Makefile"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False


def test_mixed_paths_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value = ["skills.md", "src/app.py"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False


def test_non_synced_path_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value = ["VERSION"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False


def test_empty_diff_not_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value = []),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is False


def test_docs_agent_templates_are_exempt(tmp_path):
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(
            cv,
            "_changed_files",
            return_value = ["docs/agent/templates/adr-entry.template.md"],
        ),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True


# ── registry-derived exemption (drift-proof) ─────────────────────────────────
def test_kit_exempt_files_includes_registry_files():
    """
    The exempt set is derived from the real kit registry beside the script.
    """
    registry = cv._read_registry("kit_registry.json")
    assert registry is not None, "kit_registry.json not co-located with check_version.py"
    exempt = cv._kit_exempt_files()
    for f in registry["files"]:
        assert f in exempt, f"registry file {f!r} missing from the derived exempt set"


def test_scripts_exempt_files_includes_registry_dests():
    """
    The exempt set is derived from the real scripts registry beside the script.
    """
    registry = cv._read_registry("scripts_registry.json")
    assert registry is not None, "scripts_registry.json not co-located with check_version.py"
    exempt = cv._scripts_exempt_files()
    for entry in registry["files"]:
        assert entry["dest"] in exempt, f"registry dest {entry['dest']!r} missing from the derived exempt set"


def test_real_registries_are_fully_exempt(tmp_path):
    """
    A PR touching exactly the synced kit + script files is recognized as a sync PR.
    """
    kit     = cv._read_registry("kit_registry.json")
    scripts = cv._read_registry("scripts_registry.json")
    changed = list(kit["files"]) + [e["dest"] for e in scripts["files"]]
    with (
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value = changed),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True


def test_future_registry_file_auto_exempt(tmp_path):
    """
    A file added to a registry is auto-exempt without touching this script (no drift).
    """
    fake = {
        "kit_registry.json": {"files": ["skills.md", "WORKFLOW.md", "AGENTS_KIT.md"]},
        "scripts_registry.json": None,
    }
    with (
        patch.object(cv, "_read_registry", side_effect = lambda name: fake.get(name)),
        patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
        patch.object(cv, "_changed_files", return_value = ["AGENTS_KIT.md"]),
    ):
        assert cv._is_exempt_sync_pr(tmp_path) is True


def test_fallback_when_registries_unreadable(tmp_path):
    """
    If no registry is co-located (vendored copy), fall back to the static sets.
    """
    with patch.object(cv, "_read_registry", return_value = None):
        assert cv._kit_exempt_files() == cv.KIT_EXEMPT_FILES_FALLBACK
        assert cv._scripts_exempt_files() == cv.SCRIPTS_EXEMPT_FILES_FALLBACK
        with (
            patch.dict(cv.os.environ, {"GITHUB_BASE_REF": "main"}),
            patch.object(cv, "_changed_files", return_value = ["skills.md", "scripts/bump_version.py"]),
        ):
            assert cv._is_exempt_sync_pr(tmp_path) is True
