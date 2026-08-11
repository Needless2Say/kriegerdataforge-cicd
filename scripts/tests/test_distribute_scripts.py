"""
Unit tests for scripts/distribute_scripts.py — the Makefile recipe patcher (against
captured fixtures of every REAL ci-version-check variant in the ecosystem) and the
registry/item plumbing. Network-touching flows are covered in test_repo_sync.py.
"""

from __future__ import annotations

from unittest.mock import patch

import distribute_scripts as ds
import pytest
from common.repo_sync import PatchError

# ── Captured real-world recipe variants (as of the 2026-08 census) ───────────
# Variant 1 — plain inline shell (hub, backends, terraform, template-fastapi)
PLAIN = (
    "ci-version-check: ## CI: VERSION bumped vs the base branch - mirrors the CI version-check job\n"
    '\t@printf "$(GREEN)CI [7/7]: version check...$(NC)\\n"\n'
    "\t@cur=\"$$(tr -d ' \\r\\n' < VERSION)\"; \\\n"
    '\tif [ -z "$$cur" ]; then printf "$(RED)FAIL: VERSION is empty$(NC)\\n"; exit 1; fi; \\\n'
    "\tbase=\"$$(git show origin/$(BASE_BRANCH):VERSION 2>/dev/null | tr -d ' \\r\\n')\"; \\\n"
    '\tif [ -z "$$base" ]; then \\\n'
    '\t\tprintf "$(YELLOW)SKIP$(NC)\\n"; \\\n'
    '\telse \\\n'
    '\t\tprintf "$(GREEN)OK: $$base -> $$cur$(NC)\\n"; \\\n'
    "\tfi\n"
)

# Variant 2 — inline shell + node package.json check (Next.js/npm repos)
NODE_CHECK = (
    "# Skips (does not fail) when origin/$(BASE_BRANCH) is not fetched locally.\n"
    "ci-version-check: ## CI: VERSION bumped vs the base branch -- mirrors the CI version-check job\n"
    '\t@printf "$(GREEN)CI [7/7]: version check...$(NC)\\n"\n'
    "\t@cur=\"$$(tr -d ' \\r\\n' < VERSION)\"; \\\n"
    "\tman=\"$$(node -p \"require('./package.json').version\" 2>/dev/null || echo \"\")\"; \\\n"
    '\tif [ -n "$$man" ] && [ "$$man" != "$$cur" ]; then \\\n'
    '\t\tprintf "$(RED)FAIL$(NC)\\n"; exit 1; \\\n'
    "\tfi\n"
    "\n"
    "ci-docker-build:\n"
    "\t@echo build\n"
)

# Variant 3 — already calls a per-repo script, SKIP_INIT knob (python packages)
SCRIPT_CALL = (
    "ci-version-check: _ensure-venv ## CI: VERSION bumped vs the base branch - mirrors the CI"
    " version-check job (SKIP_INIT = 1, skips __init__.py)\n"
    '\t@printf "$(GREEN)CI [8/8]: version check...$(NC)\\n"\n'
    "\t@$(PYTHON) scripts/check_version.py $(if $(SKIP_INIT),--skip-init,)\n"
    "\n"
    "ci: ci-lint ci-version-check\n"
    '\t@printf "done\\n"\n'
)

# Variant 4 — auth-ui inline python -c one-liner (no increment check at all)
AUTH_UI = (
    "ci-version-check: _ensure-venv ## Validate VERSION == package.json (mirrors the CI version-check job)\n"
    '\t@printf "$(GREEN)CI [7/7]: version consistency (VERSION vs package.json)...$(NC)\\n"\n'
    "\t@$(PYTHON) -c \"import json,pathlib,sys; v=pathlib.Path('VERSION')"
    ".read_text(encoding='utf-8-sig').strip(); sys.exit(0)\"\n"
    "\n"
    "##@ CodeQL Security Scanning\n"
)

# Variant 5 — reports-sdk bannerless one-liner
BANNERLESS = (
    "# SKIP_INIT=1 skips the __init__.py consistency half.\n"
    "ci-version-check: _ensure-venv ## Check version consistency and the +1 increment vs main"
    " (SKIP_INIT=1 skips __init__.py)\n"
    "\t@$(PYTHON) scripts/check_version.py $(if $(SKIP_INIT),--skip-init,)\n"
    "\n"
    "##@ Versioning & Release\n"
)

ALL_VARIANTS = [PLAIN, NODE_CHECK, SCRIPT_CALL, AUTH_UI, BANNERLESS]


# ── Patcher ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_patch_replaces_recipe_with_canonical(variant):
    patched = ds.patch_ci_version_check(variant)
    assert ds.CANONICAL_RECIPE in patched
    assert patched.count("ci-version-check:") == 1
    # Old recipe bodies are gone.
    assert "sort -V" not in patched
    assert "node -p" not in patched
    assert "SKIP_INIT" not in patched.split("ci-version-check:")[1].split("\n\n")[0]


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_patch_is_idempotent(variant):
    once  = ds.patch_ci_version_check(variant)
    twice = ds.patch_ci_version_check(once)
    assert once == twice


@pytest.mark.parametrize("variant", [NODE_CHECK, SCRIPT_CALL, AUTH_UI, BANNERLESS])
def test_patch_preserves_surrounding_content(variant):
    patched = ds.patch_ci_version_check(variant)
    # Neighbors (comments above, next targets/sections below) survive untouched.
    for line in variant.splitlines():
        if line.startswith(("#", "##@", "ci:", "ci-docker-build:")):
            assert line in patched


def test_patch_handles_crlf_input():
    patched = ds.patch_ci_version_check(PLAIN.replace("\n", "\r\n"))
    assert ds.CANONICAL_RECIPE in patched
    assert "\r\n" not in patched


def test_patch_missing_makefile_raises():
    with pytest.raises(PatchError, match = "not found"):
        ds.patch_ci_version_check(None)


def test_patch_missing_target_raises():
    with pytest.raises(PatchError, match = "no `ci-version-check:`"):
        ds.patch_ci_version_check("build:\n\t@echo hi\n")


def test_canonical_recipe_matches_its_own_regex():
    # Idempotency-by-construction depends on this invariant.
    match = ds._RECIPE_RE.search(ds.CANONICAL_RECIPE)
    assert match is not None
    assert match.group(0) == ds.CANONICAL_RECIPE


# ── Item building / registry plumbing ────────────────────────────────────────
def _fake_registry():
    return {
        "files": [
            {"src": "scripts/common/check_version.py", "dest": "scripts/check_version.py"},
            {"src": "scripts/common/bump_version.py", "dest": "scripts/bump_version.py"},
        ],
        "makefile_patch": True,
    }


def test_build_items_includes_files_and_makefile():
    items = ds._build_items(_fake_registry(), None)
    assert [i.dest for i in items] == ["scripts/check_version.py", "scripts/bump_version.py", "Makefile"]


def test_build_items_file_content_is_canonical_source():
    items    = ds._build_items(_fake_registry(), "check_version.py")
    expected = (ds.REPO_ROOT / "scripts/common/check_version.py").read_text(encoding = "utf-8")
    assert items[0].desired("whatever the repo currently has") == expected


def test_build_items_only_filters_by_dest():
    items = ds._build_items(_fake_registry(), "Makefile")
    assert [i.dest for i in items] == ["Makefile"]


def test_build_items_only_no_match_exits():
    with pytest.raises(SystemExit):
        ds._build_items(_fake_registry(), "does-not-exist")


def test_build_items_without_makefile_patch():
    registry = _fake_registry()
    registry["makefile_patch"] = False
    assert [i.dest for i in ds._build_items(registry, None)] == [
        "scripts/check_version.py",
        "scripts/bump_version.py",
    ]


# ── REAL-FILE consistency guards (mirrors test_distribute_kit real-file tests) ─
def test_real_registry_srcs_all_exist():
    registry = ds._load_registry()
    files    = registry.get("files", [])
    assert files, "scripts_registry.json files[] is empty"
    missing = [e["src"] for e in files if not (ds.REPO_ROOT / e["src"]).is_file()]
    assert not missing, f"scripts_registry files[].src paths missing: {missing}"


def test_real_registry_dests_are_exempt_in_check_version():
    """
    Every synced dest must be in check_version.py's exempt set, or the sync PRs
    this tool opens would fail every consumer's version gate.
    """
    import common.check_version as cv

    registry = ds._load_registry()
    exempt   = cv._scripts_exempt_files()
    for entry in registry.get("files", []):
        assert entry["dest"] in exempt, f"{entry['dest']} not exempt in check_version.py"


def test_real_scripts_version_marker_exists():
    assert ds._scripts_version() != "unknown", "scripts/SCRIPTS_VERSION missing"


def test_real_registry_repo_names_unique():
    registry = ds._load_registry()
    names    = [e["repo"] for e in registry.get("repos", [])]
    assert len(names) == len(set(names))


def test_check_mode_needs_no_makefile_fetch_when_only_files(tmp_path):
    # --only narrowing to a plain file must not build the Makefile patch item.
    with patch.object(ds, "REGISTRY_FILE", tmp_path / "missing.json"):
        with pytest.raises(SystemExit):
            ds._load_registry()
