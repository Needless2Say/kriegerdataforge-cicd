"""
Unit tests for scripts/distribute_scripts.py — the Makefile path-rewrite + recipe
patcher (incl. the double-nesting regression the vendor-dir layout makes possible),
the kdf-fmt.toml / ruff config patchers, and the registry/item plumbing.
Network-touching flows are covered in test_repo_sync.py.
"""

from __future__ import annotations

from unittest.mock import patch

import distribute_scripts as ds
import pytest
from common.repo_sync import PatchError

# ── Makefile fixtures ────────────────────────────────────────────────────────
# The post-1.0.x state every repo is in today: canonical recipe + flat script paths.
FLAT_CANONICAL = (
    "# banner\n"
    "_BUMP := PYTHONUTF8=1 $(PYTHON) scripts/bump_version.py\n"
    "\n"
    "bump-patch: _ensure-venv ## Bump patch\n"
    "\t@$(_BUMP) patch\n"
    "\n"
    "ci-version-check: _ensure-venv ## CI: version consistency + strict +1 increment"
    " vs origin/main (vendored scripts/check_version.py)\n"
    '\t@printf "$(GREEN)CI: version check...$(NC)\\n"\n'
    '\t@PYTHONUTF8=1 $(PYTHON) scripts/check_version.py --base-branch "$(if $(BASE_BRANCH),$(BASE_BRANCH),main)"\n'
    "\n"
    "ci: ci-lint ci-version-check\n"
    '\t@printf "done\\n"\n'
)

# Legacy pre-canonical variant (still patchable: target exists).
LEGACY_INLINE = (
    "ci-version-check: ## CI: VERSION bumped vs the base branch\n"
    '\t@printf "$(GREEN)CI [7/7]: version check...$(NC)\\n"\n'
    "\t@cur=\"$$(tr -d ' \\r\\n' < VERSION)\"; \\\n"
    '\tif [ -z "$$cur" ]; then exit 1; fi\n'
    "\n"
    "##@ Next section\n"
)


# config-file fixtures for the kdf-fmt / ruff patchers
KDF_WITH_EXCLUDE = (
    'line_length = 120\n'
    '\n'
    'roots = ["api", "scripts"]\n'
    '\n'
    '# backup snapshots are frozen artifacts\n'
    'exclude = ["vercel_api/"]\n'
    '\n'
    '[rules]\n'
    '"KDF-105" = "off"\n'
)

KDF_NO_EXCLUDE = ('line_length = 120\n' '\n' 'roots = ["scripts"]\n' '\n' '[rules]\n' '"KDF-105" = "off"\n')

RUFF_TOML = ("exclude = [\n" '    ".venv",\n' '    "vercel_api",\n' "]\n" "\n" "[lint]\n" 'select = ["F", "S", "B"]\n')

PYPROJECT_PLAIN = (
    "[project]\n"
    'name = "x"\n'
    'version = "1.2.3"\n'
    "\n"
    "[tool.ruff]\n"
    "line-length = 120\n"
    "\n"
    "[tool.ruff.lint]\n"
    'select = ["F", "B", "S"]\n'
)

PYPROJECT_WITH_EXTEND = (
    "[project]\n" 'version = "1.2.3"\n' "\n" "[tool.ruff]\n" 'extend-exclude = ["tests/fixtures"]\n'
)


# ── patch_makefile ───────────────────────────────────────────────────────────
def test_patch_rewrites_all_script_paths():
    patched = ds.patch_makefile(FLAT_CANONICAL)
    assert "scripts/kdf_scripts/bump_version.py" in patched
    assert "scripts/kdf_scripts/check_version.py" in patched
    # no flat references left (lookbehind-safe check: every old path is now prefixed)
    assert "$(PYTHON) scripts/bump_version.py" not in patched
    assert "$(PYTHON) scripts/check_version.py" not in patched
    assert ds.CANONICAL_RECIPE in patched


def test_patch_is_idempotent_no_double_nesting():
    """
    Regression guard for the substring trap: "kdf_scripts/bump_version.py" ends with
    "scripts/bump_version.py", so a naive replace would double-nest on re-runs.
    """
    once  = ds.patch_makefile(FLAT_CANONICAL)
    twice = ds.patch_makefile(once)
    assert once == twice
    assert "kdf_scripts/kdf_scripts" not in twice


def test_patch_legacy_variant_still_converges():
    patched = ds.patch_makefile(LEGACY_INLINE)
    assert ds.CANONICAL_RECIPE in patched
    assert patched.count("ci-version-check:") == 1
    assert "##@ Next section" in patched


def test_patch_preserves_unrelated_content():
    patched = ds.patch_makefile(FLAT_CANONICAL)
    assert "bump-patch: _ensure-venv" in patched
    assert "ci: ci-lint ci-version-check" in patched


def test_patch_handles_crlf_input():
    patched = ds.patch_makefile(FLAT_CANONICAL.replace("\n", "\r\n"))
    assert ds.CANONICAL_RECIPE in patched
    assert "\r\n" not in patched


def test_patch_missing_makefile_raises():
    with pytest.raises(PatchError, match = "not found"):
        ds.patch_makefile(None)


def test_patch_missing_target_raises():
    with pytest.raises(PatchError, match = "no `ci-version-check:`"):
        ds.patch_makefile("build:\n\t@echo hi\n")


def test_canonical_recipe_matches_its_own_regex():
    # idempotency-by-construction depends on this invariant
    match = ds._RECIPE_RE.search(ds.CANONICAL_RECIPE)
    assert match is not None
    assert match.group(0) == ds.CANONICAL_RECIPE


def test_canonical_recipe_uses_vendor_dir_paths():
    assert "scripts/kdf_scripts/check_version.py" in ds.CANONICAL_RECIPE
    # the recipe itself must be a fixed point of the path rewrite
    assert ds._PATH_REWRITE_RE.sub(r"scripts/kdf_scripts/\1.py", ds.CANONICAL_RECIPE) == ds.CANONICAL_RECIPE


# ── patch_kdf_fmt_toml ───────────────────────────────────────────────────────
def test_kdf_fmt_inserts_into_existing_exclude():
    patched = ds.patch_kdf_fmt_toml(KDF_WITH_EXCLUDE)
    assert 'exclude = ["scripts/kdf_scripts/", "vercel_api/"]' in patched


def test_kdf_fmt_creates_exclude_before_first_table():
    patched = ds.patch_kdf_fmt_toml(KDF_NO_EXCLUDE)
    assert 'exclude = ["scripts/kdf_scripts/"]' in patched
    assert patched.index("scripts/kdf_scripts/") < patched.index("[rules]")


def test_kdf_fmt_noop_when_already_excluded():
    once = ds.patch_kdf_fmt_toml(KDF_WITH_EXCLUDE)
    assert ds.patch_kdf_fmt_toml(once) == once
    once = ds.patch_kdf_fmt_toml(KDF_NO_EXCLUDE)
    assert ds.patch_kdf_fmt_toml(once) == once


def test_kdf_fmt_no_tables_appends_at_end():
    patched = ds.patch_kdf_fmt_toml('roots = ["scripts"]\n')
    assert 'exclude = ["scripts/kdf_scripts/"]' in patched


def test_kdf_fmt_missing_raises():
    with pytest.raises(PatchError, match = "kdf-fmt.toml not found"):
        ds.patch_kdf_fmt_toml(None)


# ── ruff patchers ────────────────────────────────────────────────────────────
def test_ruff_toml_inserts_into_exclude():
    patched = ds.patch_ruff_toml(RUFF_TOML)
    assert '"scripts/kdf_scripts/",' in patched
    assert patched.index("scripts/kdf_scripts/") < patched.index(".venv")
    assert ds.patch_ruff_toml(patched) == patched


def test_ruff_toml_missing_exclude_raises():
    with pytest.raises(PatchError, match = "no top-level `exclude`"):
        ds.patch_ruff_toml('[lint]\nselect = ["F"]\n')


def test_ruff_pyproject_adds_extend_exclude_under_header():
    patched = ds.patch_ruff_pyproject(PYPROJECT_PLAIN)
    assert 'extend-exclude = ["scripts/kdf_scripts/"]' in patched
    assert patched.index("scripts/kdf_scripts/") < patched.index("[tool.ruff.lint]")
    assert 'version = "1.2.3"' in patched   # version line untouched
    assert ds.patch_ruff_pyproject(patched) == patched


def test_ruff_pyproject_inserts_into_existing_extend_exclude():
    patched = ds.patch_ruff_pyproject(PYPROJECT_WITH_EXTEND)
    assert 'extend-exclude = ["scripts/kdf_scripts/", "tests/fixtures"]' in patched
    assert ds.patch_ruff_pyproject(patched) == patched


def test_ruff_pyproject_without_tool_ruff_raises():
    with pytest.raises(PatchError, match = "no \\[tool.ruff\\]"):
        ds.patch_ruff_pyproject('[project]\nname = "x"\n')


# ── Item building / registry plumbing ────────────────────────────────────────
def _fake_registry():
    return {
        "files": [
            {"src": "scripts/common/check_version.py", "dest": "scripts/kdf_scripts/check_version.py"},
            {"src": "scripts/common/bump_version.py", "dest": "scripts/kdf_scripts/bump_version.py"},
        ],
        "deletes": ["scripts/check_version.py", "scripts/bump_version.py"],
        "makefile_patch": True,
        "kdf_fmt_patch": True,
    }


def test_build_items_full_set_with_ruff():
    items = ds._build_items(_fake_registry(), None, {"repo": "o/r", "ruff_config": "ruff.toml"})
    assert [item.dest for item in items] == [
        "scripts/kdf_scripts/check_version.py",
        "scripts/kdf_scripts/bump_version.py",
        "scripts/check_version.py",
        "scripts/bump_version.py",
        "Makefile",
        "kdf-fmt.toml",
        "ruff.toml",
    ]


def test_build_items_delete_items_have_no_desired():
    items   = ds._build_items(_fake_registry(), None, {"repo": "o/r"})
    deletes = [item for item in items if item.desired is None]
    assert [item.dest for item in deletes] == ["scripts/check_version.py", "scripts/bump_version.py"]


def test_build_items_without_ruff_config():
    items = ds._build_items(_fake_registry(), None, {"repo": "o/r"})
    assert "ruff.toml" not in [item.dest for item in items]
    assert "pyproject.toml" not in [item.dest for item in items]


def test_build_items_pyproject_ruff_config():
    items = ds._build_items(_fake_registry(), None, {"repo": "o/r", "ruff_config": "pyproject.toml"})
    assert items[-1].dest == "pyproject.toml"


def test_build_items_unknown_ruff_config_raises():
    with pytest.raises(PatchError, match = "unknown ruff_config"):
        ds._build_items(_fake_registry(), None, {"repo": "o/r", "ruff_config": "setup.cfg"})


def test_build_items_file_content_is_canonical_source():
    items    = ds._build_items(_fake_registry(), "kdf_scripts/check_version.py", {"repo": "o/r"})
    expected = (ds.REPO_ROOT / "scripts/common/check_version.py").read_text(encoding = "utf-8")
    assert items[0].desired("whatever the repo currently has") == expected


def test_build_items_only_filters_by_dest():
    items = ds._build_items(_fake_registry(), "Makefile", {"repo": "o/r"})
    assert [item.dest for item in items] == ["Makefile"]


def test_build_items_only_no_match_exits():
    with pytest.raises(SystemExit):
        ds._build_items(_fake_registry(), "does-not-exist", {"repo": "o/r"})


# ── REAL-FILE consistency guards ─────────────────────────────────────────────
def test_real_registry_srcs_all_exist():
    registry = ds._load_registry()
    files    = registry.get("files", [])
    assert files, "scripts_registry.json files[] is empty"
    missing = [entry["src"] for entry in files if not (ds.REPO_ROOT / entry["src"]).is_file()]
    assert not missing, f"scripts_registry files[].src paths missing: {missing}"


def test_real_registry_dests_under_vendor_dir():
    registry = ds._load_registry()
    for entry in registry.get("files", []):
        assert entry["dest"].startswith(ds.VENDOR_DIR), entry["dest"]


def test_real_registry_deletes_disjoint_from_dests():
    registry = ds._load_registry()
    dests    = {entry["dest"] for entry in registry.get("files", [])}
    deletes  = set(registry.get("deletes", []))
    assert deletes, "deletes[] should list the superseded flat paths"
    assert not (dests & deletes)


def test_real_registry_ruff_configs_valid():
    registry = ds._load_registry()
    for entry in registry.get("repos", []):
        ruff_config = entry.get("ruff_config")
        assert ruff_config in (None, "ruff.toml", "pyproject.toml"), entry["repo"]


def test_real_registry_paths_are_exempt_in_check_version():
    """
    Every synced dest AND delete must be in check_version.py's exempt set, or the
    sync PRs this tool opens would fail every consumer's version gate.
    """
    import common.check_version as cv

    registry = ds._load_registry()
    exempt   = cv._scripts_exempt_files()
    for entry in registry.get("files", []):
        assert entry["dest"] in exempt, f"{entry['dest']} not exempt in check_version.py"
    for stale in registry.get("deletes", []):
        assert stale in exempt, f"deleted path {stale} not exempt in check_version.py"


def test_real_scripts_version_marker_exists():
    assert ds._scripts_version() != "unknown", "scripts/SCRIPTS_VERSION missing"


def test_real_registry_repo_names_unique():
    registry = ds._load_registry()
    names    = [entry["repo"] for entry in registry.get("repos", [])]
    assert len(names) == len(set(names))


def test_missing_registry_exits(tmp_path):
    with patch.object(ds, "REGISTRY_FILE", tmp_path / "missing.json"):
        with pytest.raises(SystemExit):
            ds._load_registry()
