"""
Unit tests for the requirements-dev.in merge and the read-only ci.yml pin check
added to distribute_scripts.py (ADR D-013).

The merge exists to make ONE case loud: a repo that already declares the toolchain at
a different version. kriegerdataforge-sdk was live proof it happens -- it pinned
kdf-fmt v1.1.1 for local dev while its CI style job ran v1.1.0 -- so the conflict
tests below are the point of the file, not an edge case.
"""

from __future__ import annotations

import distribute_scripts as ds
import pytest
from common.repo_sync import PatchError

CANONICAL = [
    {"name": "kdf-fmt", "spec": "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.1.1"},
]
SPEC      = CANONICAL[0]["spec"]

EXISTING_OTHER = ("# dev toolchain\n" "ruff==0.6.9\n" "mypy==1.11.2\n")

# ci.yml fixtures: the reusable style job pins kdf-fmt separately from the requirements
# file, which is exactly how kriegerdataforge-sdk ended up running two versions.
CI_OK    = "jobs:\n  style:\n    with:\n      kdf_fmt_ref: v1.1.1\n"
CI_DRIFT = "jobs:\n  style:\n    with:\n      kdf_fmt_ref: v1.1.0\n"


# ── requirements-dev.in: creation ────────────────────────────────────────────
def test_creates_file_when_absent() -> None:
    """
    A repo with no requirements-dev.in gets one, header first.
    """
    result = ds.patch_requirements(None, CANONICAL)
    assert result.startswith("# Managed by kriegerdataforge-cicd")
    assert SPEC in result
    assert result.endswith("\n")


def test_created_file_is_idempotent() -> None:
    """
    Re-running over the file just created must produce no further change.
    """
    once  = ds.patch_requirements(None, CANONICAL)
    twice = ds.patch_requirements(once, CANONICAL)
    assert twice == once


# ── requirements-dev.in: merging ─────────────────────────────────────────────
def test_appends_when_package_absent() -> None:
    """
    An existing file keeps its content and gains the pin.
    """
    result = ds.patch_requirements(EXISTING_OTHER, CANONICAL)
    assert "ruff==0.6.9" in result
    assert "mypy==1.11.2" in result
    assert SPEC in result


def test_no_change_when_already_pinned_identically() -> None:
    """
    The whole point of idempotence: a synced repo produces no diff.
    """
    already = EXISTING_OTHER + SPEC + "\n"
    assert ds.patch_requirements(already, CANONICAL) == already


def test_crlf_input_is_normalised_not_duplicated() -> None:
    """
    A Windows-checkout file must not gain a second copy of the pin.
    """
    already = (EXISTING_OTHER + SPEC + "\n").replace("\n", "\r\n")
    result  = ds.patch_requirements(already, CANONICAL)
    assert result.count("kriegerdataforge-fmt.git") == 1
    assert "\r" not in result


def test_name_normalisation_matches_underscore_and_case() -> None:
    """
    kdf_fmt / KDF-FMT are the same distribution and must not be re-appended.
    """
    already = "KDF_FMT @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.1.1\n"
    with pytest.raises(PatchError):
        # same distribution, different literal spec -> conflict, NOT a silent append
        ds.patch_requirements(already, CANONICAL)


def test_commented_pin_does_not_count_as_declared() -> None:
    """
    A commented-out pin is not a declaration; the real one still gets added.
    """
    already = "# kdf-fmt @ git+https://example.invalid/x.git@v0.0.1\n"
    result  = ds.patch_requirements(already, CANONICAL)
    assert SPEC in result


# ── requirements-dev.in: the conflict case ───────────────────────────────────
def test_different_version_raises_rather_than_rewriting() -> None:
    """
    A divergent pin must never be silently moved.
    """
    already = EXISTING_OTHER + \
        "kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@v1.1.0\n"
    with pytest.raises(PatchError) as excinfo:
        ds.patch_requirements(already, CANONICAL)
    assert "v1.1.0" in str(excinfo.value)
    assert "by hand" in str(excinfo.value)


def test_conflict_leaves_the_file_untouched() -> None:
    """
    The raising path must not have mutated the input on its way out.
    """
    already = "kdf-fmt==0.9.0\n"
    before  = already
    with pytest.raises(PatchError):
        ds.patch_requirements(already, CANONICAL)
    assert already == before


# ── ci.yml: read-only pin check ──────────────────────────────────────────────
def test_ci_yaml_in_sync_returns_content_unchanged() -> None:
    """
    Returning the input verbatim is what stops the engine writing workflow files.
    """
    assert ds.patch_ci_yaml(CI_OK, "v1.1.1") is CI_OK


def test_ci_yaml_quoted_ref_accepted() -> None:
    """
    A quoted ref is the same pin.
    """
    quoted = 'jobs:\n  style:\n    with:\n      kdf_fmt_ref: "v1.1.1"\n'
    assert ds.patch_ci_yaml(quoted, "v1.1.1") is quoted


def test_ci_yaml_drift_raises() -> None:
    """
    The kriegerdataforge-sdk case: local dev and CI on different kdf-fmt versions.
    """
    with pytest.raises(PatchError) as excinfo:
        ds.patch_ci_yaml(CI_DRIFT, "v1.1.1")
    assert "v1.1.0" in str(excinfo.value)


def test_ci_yaml_missing_key_is_a_no_op_not_a_block() -> None:
    """
    A workflow that never calls the reusable style job has no second pin to disagree
    with, so it is not drift. Raising here failed the ENTIRE repo -- requirements pin
    and vendored scripts included -- for 8 of the 17 registry repos.
    """
    no_key = "jobs:\n  style:\n    with:\n      other: 1\n"
    assert ds.patch_ci_yaml(no_key, "v1.1.1") is no_key


def test_ci_yaml_absent_file_raises() -> None:
    """
    A missing workflow must not be created by the distributor.
    """
    with pytest.raises(PatchError):
        ds.patch_ci_yaml(None, "v1.1.1")
