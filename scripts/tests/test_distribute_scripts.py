"""
Unit tests for scripts/distribute_scripts.py — the Makefile path-rewrite + recipe
patcher (incl. the double-nesting regression the vendor-dir layout makes possible),
the kdf-fmt.toml / ruff config patchers, and the registry/item plumbing.
Network-touching flows are covered in test_repo_sync.py.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import distribute_scripts as ds
import pytest
from common.kdf_scan import BLOCK_CLOSE, BLOCK_OPEN, RULES_COMMIT, parse_policy, parse_scan_image
from common.repo_sync import PatchError
from tests.scan_fakes import ACTIVE as SCAN_ACTIVE
from tests.scan_fakes import makefile

# an active set as an activating pull request writes it, for the block's tests
ACTIVE = {
    "image": "ghcr.io/needless2say/kdf-scan",
    "digest": "sha256:" + "d" * 64,
    "commit": "c" * 40,
    "rules_commit": RULES_COMMIT,
    "rules_digest": "e" * 64,
    "contract": "1",
}

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

# minimal Makefiles written for cicd in the shapes of a FastAPI hub's, a Next.js frontend's, terraform's and a package
# template's, each already on the canonical version check, for the managed scan block (D-085). No line is a tenant's.
HUB_MAKEFILE = (
    "# a FastAPI service\n"
    "PYTHON ?= .venv/Scripts/python\n"
    "GREEN := \\033[0;32m\n"
    "NC := \\033[0m\n"
    "\n"
    "##@ Setup\n"
    "_ensure-venv:\n"
    "\t@test -x $(PYTHON) || $(MAKE) venv\n"
    "\n"
    "##@ CI\n"
    "ci-lint: _ensure-venv ## CI: lint\n"
    "\t@$(PYTHON) -m ruff check api scripts\n"
    f"{ds.CANONICAL_RECIPE}"
    "ci: ci-lint ci-version-check ## CI: every lane\n"
)

FRONTEND_MAKEFILE = (
    "NPM ?= npm\n"
    ".PHONY: ci-lint ci-unit-tests\n"
    "ci-lint: ## CI: eslint\n"
    "\t@$(NPM) run lint\n"
    "ci-unit-tests: ## CI: jest\n"
    "\t@$(NPM) test -- --ci\n"
    f"{ds.CANONICAL_RECIPE}"
)

TERRAFORM_MAKEFILE = (
    "TF ?= terraform\n"
    "ci-fmt: ## CI: terraform fmt\n"
    "\t@$(TF) fmt -check -recursive\n"
    "ci-validate: ## CI: terraform validate\n"
    "\t@$(TF) validate\n"
    f"{ds.CANONICAL_RECIPE}"
)

TEMPLATE_MAKEFILE = (
    "PYTHON ?= .venv/bin/python\n"
    "build: ## Build the wheel\n"
    "\t@$(PYTHON) -m build\n"
    f"{ds.CANONICAL_RECIPE}"
    "\n"
    "ci: build ci-version-check\n"
)

SHAPES = {
    "hub": HUB_MAKEFILE,
    "frontend": FRONTEND_MAKEFILE,
    "terraform": TERRAFORM_MAKEFILE,
    "template": TEMPLATE_MAKEFILE,
}


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


# ── the managed scan block (D-085) ───────────────────────────────────────────
@pytest.fixture(autouse = True)
def _an_active_image(monkeypatch):
    # every test sees one active image unless it names another, since SCAN_IMAGE holds the unpinned marker until A3
    monkeypatch.setattr(ds, "active_scan_image", lambda: dict(ACTIVE))


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_an_absent_scan_block_is_inserted_at_the_end_of_each_repo_shape(shape):
    patched = ds.patch_makefile(SHAPES[shape])
    assert patched.count(BLOCK_OPEN) == 1 and patched.count(BLOCK_CLOSE) == 1
    assert patched.endswith(ds.SCAN_BLOCK_HEAD + ds.scan_block_tail(ACTIVE))
    assert "\n\n" + BLOCK_OPEN in patched
    policy = parse_policy(patched)
    assert policy.excludes == () and policy.limits == ()
    assert patched.startswith(SHAPES[shape].rstrip("\n") + "\n")


def test_the_block_runs_cicds_image_by_its_digest_offline_read_only_and_as_no_root():
    tail = ds.scan_block_tail(ACTIVE)
    assert f"KDF_SCAN_IMAGE := {ACTIVE['image']}@{ACTIVE['digest']}\n" in tail
    assert f"KDF_SCAN_RULES_COMMIT := {ACTIVE['rules_commit']}\n" in tail
    for flag in (
        "--pull never",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 65532:65532",
        "MSYS_NO_PATHCONV=1",
    ):
        assert flag in tail, flag
    assert ":/gitdir" not in tail and '--git-dir "/git$${own#"$$common"}"' in tail
    for mount in (":/src:ro", ":/git:ro", ":/rules:ro", ":/repo:ro"):
        assert mount in tail, mount
    assert "git rev-parse --show-toplevel" in tail and "git config core.autocrlf" in tail
    assert ds.SCAN_BLOCK_HEAD.startswith(BLOCK_OPEN + "\n") and tail.endswith(BLOCK_CLOSE + "\n")
    assert "_ensure-venv" not in tail and "KriegerDataForge-scan" not in tail


def test_the_block_names_the_canonical_callers_sha256():
    caller = ds.caller_text()
    assert f"KDF_SCAN_CALLER_SHA := {hashlib.sha256(caller.encode('utf-8')).hexdigest()}\n" in ds.scan_block_tail(
        ACTIVE,
    )


def test_the_scans_own_tests_read_this_block():
    assert makefile().endswith(ds.SCAN_BLOCK_HEAD + ds.scan_block_tail(SCAN_ACTIVE))


def test_while_cicd_pins_no_image_the_makefile_is_left_as_it_stands(monkeypatch):
    monkeypatch.setattr(ds, "active_scan_image", lambda: {})
    patched = ds.patch_makefile(SHAPES["hub"])
    assert BLOCK_OPEN not in patched and ds.CANONICAL_RECIPE in patched


def test_the_repos_scan_image_file_holds_the_unpinned_marker_until_the_first_activation():
    assert parse_scan_image(ds.SCAN_IMAGE_FILE.read_text(encoding = "utf-8")) == {}


def test_the_caller_runs_cicds_reusable_gate_at_main_on_dispatch_alone_with_read_permissions():
    caller = ds.caller_text()
    assert "uses: Needless2Say/kriegerdataforge-cicd/.github/workflows/kdf-scan-gate-reusable.yml@main\n" in caller
    assert "  workflow_dispatch:\n" in caller and "pull_request" not in caller and "push:" not in caller
    assert "  contents: read\n  pull-requests: read\n" in caller and "secrets:" not in caller


def test_the_caller_travels_with_the_block_once_an_image_is_pinned_and_the_registry_allows_it(monkeypatch):
    registry = {"files": [], "deletes": [], "makefile_patch": True, "scan_caller": True}
    items    = ds._build_items(registry, None, {"repo": "Needless2Say/x"})
    caller   = [item for item in items if item.dest == ds.CALLER_PATH]
    assert len(caller) == 1 and caller[0].desired("anything") == ds.caller_text()
    monkeypatch.setattr(ds, "active_scan_image", lambda: {})
    assert not [
        item for item in ds._build_items(registry, None, {"repo": "Needless2Say/x"}) if item.dest == ds.CALLER_PATH
    ]


def test_the_caller_stays_out_of_the_sync_while_the_registry_grants_no_workflow_write():
    # the ops workflows' App token holds contents and pull request writes alone, and a workflow file it cannot write
    # aborts the whole repo's sync, so the caller arrives by a bootstrap pull request instead, Codex's step 6 read
    registry = {"files": [], "deletes": [], "makefile_patch": True}
    items    = ds._build_items(registry, None, {"repo": "Needless2Say/x"})
    assert not [item for item in items if item.dest == ds.CALLER_PATH]
    assert [item for item in items if item.dest == ds.MAKEFILE_DEST]
    assert ds._load_registry().get("scan_caller") is False


def test_a_present_block_is_replaced_whole_but_for_the_repos_own_lines():
    own     = (
        "SCAN_EXCLUDE += src/core/api/generated  # generated from the hub's schema by openapi\n"
        "SCAN_LIMIT += src/app/view.tsx@" + "a" * 64 + "  # opengrep reads its dynamic import only partly\n"
    )
    old     = (
        f"{BLOCK_OPEN}\n# an older header\nSCAN_EXCLUDE ?=\n{own}.PHONY: scan\nscan:\n"
        "\t@D:/KriegerDataForge-scan/python/3.14.6/python.exe -I -S D:/KriegerDataForge-scan/kdf-scan.py\n"
        "STRAY := a line nobody owns\n"
        f"{BLOCK_CLOSE}\n"
        "after: ## a target after the block\n\t@echo after\n"
    )
    patched = ds.patch_makefile(SHAPES["frontend"] + "\n" + old)
    assert ds.SCAN_BLOCK_HEAD + own + ds.scan_block_tail(ACTIVE) in patched
    assert "3.14.6" not in patched and "STRAY" not in patched and "an older header" not in patched
    assert patched.endswith("after: ## a target after the block\n\t@echo after\n")
    policy = parse_policy(patched)
    assert policy.excludes == (("src/core/api/generated", "generated from the hub's schema by openapi"),)
    assert [limit[0] for limit in policy.limits] == ["src/app/view.tsx"]


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_rerun_changes_nothing(shape):
    own  = "SCAN_EXCLUDE += vercel_api  # a bundle the compactor writes from api\n"
    once = ds.patch_makefile(SHAPES[shape])
    once = once.replace("SCAN_EXCLUDE ?=\n", "SCAN_EXCLUDE ?=\n" + own)
    assert ds.patch_makefile(once) == once
    assert ds.patch_makefile(once.replace("\n", "\r\n")) == once


@pytest.mark.parametrize("extra", [
    f"{BLOCK_OPEN}\n{BLOCK_CLOSE}\n{BLOCK_OPEN}\n{BLOCK_CLOSE}\n",
    f"{BLOCK_OPEN}\nSCAN_EXCLUDE ?=\n",
    f"{BLOCK_CLOSE}\n",
])
def test_two_blocks_an_unclosed_block_or_a_stray_close_are_refused(extra):
    with pytest.raises(PatchError, match = "managed scan block"):
        ds.patch_makefile(SHAPES["hub"] + "\n" + extra)


@pytest.mark.parametrize(
    "target",
    [
        "scan:\n\t@echo mine\n",
        "lint scan: ## two at once\n\t@echo both\n",
        "scan :: \n\t@echo double colon\n",
        " scan:\n\t@echo one space, still a rule to make\n",
        "  lint scan:\n\t@echo spaces and two targets\n",
        " \tscan:\n\t@echo a space then a tab, still a rule\n",
        "lint scan &: other\n\t@echo grouped targets\n",
    ],
)
def test_a_scan_target_outside_the_block_is_refused(target):
    with pytest.raises(PatchError, match = "a scan target outside"):
        ds.patch_makefile(SHAPES["template"] + "\n" + target)
    with pytest.raises(PatchError, match = "a scan target outside"):
        ds.patch_makefile(ds.patch_makefile(SHAPES["template"]) + "\n" + target)


def test_targets_that_only_start_with_scan_and_a_phony_line_naming_it_are_kept():
    extra   = (".PHONY: scan scan-local scan-fixtures\nscan-local: ## the wrapper from source\n\t@echo local\n"
               "scan-fixtures:\n\t@echo fixtures\n\tscan: a recipe line, which its tab keeps from a rule\n"
               "SCANNER := other\n")
    patched = ds.patch_makefile(SHAPES["terraform"] + "\n" + extra)
    assert extra in patched and patched.count(BLOCK_OPEN) == 1


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
        "scan_caller": True,
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
        ".github/workflows/kdf-scan-gate.yml",
        "kdf-fmt.toml",
        "ruff.toml",
    ]


def test_build_items_delete_items_have_no_desired():
    items   = ds._build_items(_fake_registry(), None, {"repo": "o/r"})
    deletes = [item for item in items if item.desired is None]
    assert [item.dest for item in deletes] == ["scripts/check_version.py", "scripts/bump_version.py"]


def test_build_items_skip_kdf_fmt_builds_no_kdf_fmt_item():
    # a repo with no style lane carries no kdf-fmt.toml, and the patch raises on a missing file
    items = ds._build_items(_fake_registry(), None, {"repo": "o/r", "skip_kdf_fmt": True})
    assert "kdf-fmt.toml" not in [item.dest for item in items]
    assert "Makefile" in [item.dest for item in items]


def test_registry_entry_without_a_style_lane_skips_the_formatter_pin_too():
    # requirements-dev.in pins kdf-fmt, pointless in a repo that opted out of the lane
    registry  = json.loads((ds.REPO_ROOT / "scripts" / "scripts_registry.json").read_text(encoding = "utf-8"))
    opted_out = [entry for entry in registry["repos"] if entry.get("skip_kdf_fmt")]
    assert [entry["repo"] for entry in opted_out] == [
        "Needless2Say/kriegerdataforge-terraform",
        "Needless2Say/kriegerdataforge-auth-ui",
    ]
    assert all(entry.get("skip_requirements") and entry.get("_skip_reason") for entry in opted_out)


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


def test_a_file_that_names_its_repos_reaches_those_and_no_other():
    """
    The mutation engine (D-040) is for the repos that run Python mutants, a frontend is never handed it.
    """
    registry = _fake_registry()
    engine   = {"src": "scripts/common/mutation_runner.py", "dest": "scripts/kdf_scripts/mutation_runner.py"}
    registry["files"].append({**engine, "repos": ["o/r"]})
    named = [item.dest for item in ds._build_items(registry, None, {"repo": "o/r"})]
    other = [item.dest for item in ds._build_items(registry, None, {"repo": "o/frontend"})]

    assert "scripts/kdf_scripts/mutation_runner.py" in named
    assert "scripts/kdf_scripts/mutation_runner.py" not in other
    assert "scripts/kdf_scripts/check_version.py" in other, "a file that names no repos still reaches every repo"


def test_the_mutation_engine_reaches_the_four_repos_that_run_python_mutants():
    registry = ds._load_registry()
    engine   = next(entry for entry in registry["files"] if entry["src"] == "scripts/common/mutation_runner.py")
    repos    = {entry["repo"] for entry in registry["repos"]}

    assert engine["dest"] == "scripts/kdf_scripts/mutation_runner.py"
    assert sorted(engine["repos"]) == [
        "Needless2Say/fitness-app-backend",
        "Needless2Say/kriegerdataforge",
        "Needless2Say/kriegerdataforge-sdk",
        "Needless2Say/tiffanys-space-backend",
    ]
    assert set(engine["repos"]) <= repos, "every repo the engine names is a repo the sync reaches"


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
