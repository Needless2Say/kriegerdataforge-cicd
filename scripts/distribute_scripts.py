"""
Check and distribute the ecosystem dev scripts (bump_version.py / check_version.py /
version_targets.py) from the canonical source in kriegerdataforge-cicd/scripts/common/
to every consumer repo's scripts/kdf_scripts/ vendor directory — plus the config edits
that wire them into `make ci` and keep them OUT of tenant lint/style scope.

This is the script-sync sibling of distribute_kit.py (ADR D-013 mirrors the kit's
ADR D-001; the vendored layout is ADR D-014): ONE source of truth (scripts/common/),
ONE registry (scripts_registry.json), owner-gated PRs, built on the shared engine in
common/repo_sync.py. The vendor directory exists because the shipped scripts are only
guaranteed clean under CICD's kdf-fmt/ruff configs — tenant configs vary, so tenants
exclude scripts/kdf_scripts/ and cicd alone governs the style of what it ships.

Synced items (per repo, from the registry):
  - files[]:   the three scripts, vendored byte-identical to scripts/kdf_scripts/.
  - deletes[]: the superseded flat scripts/ copies, removed in the same PR.
  - Makefile ("makefile_patch"): every scripts/<name>.py reference is rewritten to
    scripts/kdf_scripts/<name>.py (covers the `_BUMP :=` line and comments), then the
    `ci-version-check:` recipe block is re-asserted to the canonical thin call.
    Idempotent; a Makefile without the target raises PatchError -> NEEDS MANUAL ATTENTION.
  - kdf-fmt.toml ("kdf_fmt_patch"): appends "scripts/kdf_scripts/" to the top-level
    `exclude` list (creating the key before the first TOML table when absent).
  - ruff config (per-repo "ruff_config": ruff.toml | pyproject.toml): same exclusion,
    into ruff.toml's `exclude` list or [tool.ruff]'s `extend-exclude`.

Modes:
  check       Read-only drift report. Exits non-zero if any repo is out of sync. OPENS NOTHING.
  distribute  Opens one review-gated PR per drifted repo ("chore(scripts): sync ecosystem
              dev scripts <SCRIPTS_VERSION>"). NEVER auto-merges.

IMPORTANT — version-check: scripts-sync PRs do not bump VERSION. The central
scripts/common/check_version.py exempts PRs touching only the registry dest+delete paths
(plus Makefile / kdf-fmt.toml / ruff.toml / pyproject.toml, on chore/scripts-sync-*
branches only), so the sync PRs pass the gate.

Requirements:
    pip install requests

Environment variables:
  GH_TOKEN    GitHub token with contents:read (check) or contents + pull-requests:write
              (distribute) on all target repos. Use the CICD_PAT value.

Usage:
    GH_TOKEN=... python distribute_scripts.py check
    GH_TOKEN=... python distribute_scripts.py check --only check_version.py
    GH_TOKEN=... python distribute_scripts.py distribute
    # Target a subset of repos (comma-separated exact names); blank = all:
    GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import re
import sys
from pathlib import Path

# third party imports
# local imports — the shared sync engine (transport, retry session, fan-out loops)
from common.repo_sync import PatchError, SyncItem, _select_repos, run_check, run_distribute

# ======================================================================================================================
# Configuration
# ======================================================================================================================

SCRIPTS_DIR          = Path(__file__).parent
REPO_ROOT            = SCRIPTS_DIR.parent
REGISTRY_FILE        = SCRIPTS_DIR / "scripts_registry.json"
SCRIPTS_VERSION_FILE = SCRIPTS_DIR / "SCRIPTS_VERSION"

MAKEFILE_DEST     = "Makefile"
KDF_FMT_DEST      = "kdf-fmt.toml"
REQUIREMENTS_DEST = "requirements-dev.in"
CI_YAML_DEST      = ".github/workflows/ci.yml"
VENDOR_DIR        = "scripts/kdf_scripts/"

# Header written above the pins when a repo has no requirements-dev.in at all. Every
# repo carries the vendored scripts, so every repo needs somewhere to declare the
# Python toolchain that lints and formats them -- including the JS repos, which get
# this file and nothing else Python-shaped. Deliberately NOT compiled to a
# requirements.txt there: with no application dependencies there is nothing to lock,
# and a lockfile would add a compile-requirements target to six Makefiles for no gain.
_REQUIREMENTS_HEADER = (
    "# Managed by kriegerdataforge-cicd (distribute_scripts.py, ADR D-013).\n"
    "# Pins the Python toolchain that operates on the vendored scripts/kdf_scripts/\n"
    "# copies. The scripts themselves are stdlib-only and need nothing to RUN.\n"
    "#\n"
    "# The distributor never rewrites a pin it did not expect: a version here that\n"
    "# disagrees with the canonical one fails the sync as NEEDS MANUAL ATTENTION\n"
    "# rather than silently moving you to another release.\n"
)

# `name @ git+https://...` and plain `name==x.y.z` both start with the distribution
# name, which is all we need to decide "is this package already declared here".
_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:@|==|>=|<=|~=|!=|<|>|\[|$)")

# The reusable style job pins kdf-fmt itself, separately from the requirements file.
_KDF_FMT_REF_RE = re.compile(r"^(\s*kdf_fmt_ref\s*:\s*)(\S+)\s*$", re.MULTILINE)

# The canonical `ci-version-check` recipe every repo converges on: a thin call of the
# vendored checker, which owns ALL the logic (consistency + strict increment +
# skip-when-base-unfetchable). `$(if ...)` covers repos that define no BASE_BRANCH;
# PYTHONUTF8=1 matches the `_BUMP` convention (cp1252 Windows consoles).
CANONICAL_RECIPE = (
    "ci-version-check: _ensure-venv ## CI: version consistency + strict +1 increment"
    " vs origin/main (vendored scripts/kdf_scripts/check_version.py)\n"
    '\t@printf "$(GREEN)CI: version check...$(NC)\\n"\n'
    '\t@PYTHONUTF8=1 $(PYTHON) scripts/kdf_scripts/check_version.py'
    ' --base-branch "$(if $(BASE_BRANCH),$(BASE_BRANCH),main)"\n'
)

# A make recipe block: the target line plus the maximal run of tab-prefixed lines.
_RECIPE_RE = re.compile(r"^ci-version-check:[^\n]*\n(?:\t[^\n]*\n)*", re.MULTILINE)

# Old flat script paths -> vendor-dir paths, everywhere in the Makefile (the `_BUMP :=`
# line, the recipe, comments). The negative lookbehind is LOAD-BEARING for idempotency:
# "kdf_scripts/bump_version.py" itself ENDS WITH the substring "scripts/bump_version.py",
# so a naive replace would double-nest the path on every re-run.
_PATH_REWRITE_RE = re.compile(r"(?<!kdf_)scripts/(check_version|bump_version|version_targets)\.py")

# The exclusion appended to tenant style/lint configs (trailing slash = directory).
_VENDOR_EXCLUDE_ENTRY  = f'"{VENDOR_DIR}"'
_KDF_FMT_EXCLUDE_BLOCK = (
    "\n# distributed ecosystem scripts are vendored -- their style is governed in kriegerdataforge-cicd\n"
    f"exclude = [{_VENDOR_EXCLUDE_ENTRY}]\n"
)

_CLI_EPILOG = """Examples:
  GH_TOKEN=... python distribute_scripts.py check
  GH_TOKEN=... python distribute_scripts.py distribute --repos kriegerdataforge,tiffanys-space
  GH_TOKEN=... python distribute_scripts.py distribute --only check_version.py"""

_REPOS_HELP = """Only operate on these repos (comma-separated EXACT names, e.g.
'kriegerdataforge,tiffanys-space'). Matches the full owner/repo or the short name
exactly (not a substring). Blank = all repos in the registry."""

_PR_BODY_TEMPLATE = """Automated sync of the ecosystem dev scripts to **{version}** from
`kriegerdataforge-cicd/scripts/common/` (ADR D-013 / vendored layout ADR D-014).

Items updated: {items}

The version tooling now lives in the **`scripts/kdf_scripts/` vendor directory**: the old
flat `scripts/` copies are deleted in this PR, every Makefile reference (including
`_BUMP :=` and the `ci-version-check` recipe) points at the new paths, and the directory
is excluded from this repo's `kdf-fmt.toml` (and ruff config, where present) — the style
of vendored scripts is governed in kriegerdataforge-cicd, so tenant formatting configs
can never fail a sync PR again.

No VERSION bump: scripts-sync PRs are exempt from the version gate (see check_version.py /
ADR D-013). Please review and merge."""

# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _load_registry() -> dict:
    """
    Load scripts_registry.json from beside this script.

    Returns:
        dict: the parsed registry
    """
    if not REGISTRY_FILE.is_file():
        sys.exit(f"Error: registry file not found: {REGISTRY_FILE}")
    return json.loads(REGISTRY_FILE.read_text(encoding = "utf-8"))


def _scripts_version() -> str:
    """
    Read the SCRIPTS_VERSION sync marker.

    Returns:
        str: the marker value, or "unknown" when the file is missing
    """
    if SCRIPTS_VERSION_FILE.is_file():
        return SCRIPTS_VERSION_FILE.read_text(encoding = "utf-8").strip()
    return "unknown"

# ======================================================================================================================
# Patchers (all idempotent; PatchError -> repo reported NEEDS MANUAL ATTENTION)
# ======================================================================================================================

def patch_makefile(text: str | None) -> str:
    """
    Point every script reference at the vendor dir and re-assert the canonical recipe.

    Step 1 rewrites all `scripts/<name>.py` references to `scripts/kdf_scripts/<name>.py`
    (the lookbehind in _PATH_REWRITE_RE keeps already-rewritten paths untouched). Step 2
    replaces the `ci-version-check:` recipe block with CANONICAL_RECIPE. Idempotent by
    construction: the canonical block matches the recipe regex and maps to itself.

    Args:
        text: the target repo's current Makefile content, or None when absent

    Returns:
        str: the patched Makefile content (LF endings)

    Raises:
        PatchError: when the Makefile is missing or has no `ci-version-check` target
    """
    if text is None:
        raise PatchError("Makefile not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if not _RECIPE_RE.search(normalized):
        raise PatchError("Makefile has no `ci-version-check:` recipe to rewrite")
    rewritten = _PATH_REWRITE_RE.sub(r"scripts/kdf_scripts/\1.py", normalized)
    # function replacement -> inserted literally (no \-escape processing of the recipe)
    return _RECIPE_RE.sub(lambda _match: CANONICAL_RECIPE, rewritten, count = 1)


def patch_kdf_fmt_toml(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to a tenant's kdf-fmt.toml.

    No-op when the path is already excluded. When a top-level `exclude = [` list exists,
    the entry is inserted after the opening bracket; otherwise the key is created before
    the first TOML table header (top-level keys must precede tables).

    Args:
        text: the repo's current kdf-fmt.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when kdf-fmt.toml is missing from the repo
    """
    if text is None:
        raise PatchError("kdf-fmt.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    match = re.search(r"^(exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if match:
        return normalized[: match.end()] + _VENDOR_EXCLUDE_ENTRY + ", " + normalized[match.end():]
    table = re.search(r"^\[", normalized, re.MULTILINE)
    if table:
        return normalized[: table.start()] + _KDF_FMT_EXCLUDE_BLOCK + "\n" + normalized[table.start():]
    return normalized.rstrip("\n") + "\n" + _KDF_FMT_EXCLUDE_BLOCK


def patch_requirements(text: str | None, packages: list[dict]) -> str:
    """
    Merge the canonical toolchain pins into a repo's requirements-dev.in.

    Four cases per package, and only two of them write anything:
      absent            -> the pinned spec is appended
      present, same     -> untouched (idempotent; a re-run produces no diff)
      present, differs  -> PatchError, so the repo is reported NEEDS MANUAL ATTENTION
      file absent       -> created with the header, then the pins appended

    The third case is the point of the whole exercise. Silently rewriting a pin would
    move a repo onto a different kdf-fmt without anyone deciding to, and a kdf-fmt
    version change shifts style findings against the baselines -- so divergence is
    surfaced for a human instead of resolved by a tool.

    Args:
        text: the repo's current requirements-dev.in content, or None when absent
        packages: canonical entries, each ``{"name": ..., "spec": ...}``

    Returns:
        str: the merged file content (LF endings)

    Raises:
        PatchError: when a package is already declared at a different version
    """
    normalized = (text or _REQUIREMENTS_HEADER).replace("\r\n", "\n")
    lines      = normalized.split("\n")

    declared: dict[str, tuple[int, str]] = {}
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _REQ_NAME_RE.match(line)
        if match:
            declared[match.group(1).lower().replace("_", "-")] = (index, line.strip())

    additions: list[str] = []
    for package in packages:
        key  = package["name"].lower().replace("_", "-")
        spec = package["spec"]
        if key not in declared:
            additions.append(spec)
            continue
        _index, existing = declared[key]
        if existing != spec:
            raise PatchError(
                f"{package['name']} is pinned as {existing!r} but the canonical pin is "
                f"{spec!r}. Reconcile it by hand -- the distributor will not move a pin "
                "for you, because changing kdf-fmt versions moves style baselines too."
            )

    if not additions:
        return normalized
    body = normalized.rstrip("\n")
    return (body + "\n" if body else "") + "\n".join(additions) + "\n"


def patch_ci_yaml(text: str | None, expected_ref: str) -> str:
    """
    Verify the reusable style job pins the same kdf-fmt the requirements file does.

    Returns the content UNCHANGED when the two agree, which the engine treats as "no
    drift" and therefore never writes. That is deliberate: pushing a change to
    .github/workflows/ requires the `workflow` token scope, and no other distributor
    in this repo writes workflow files. Drift is reported instead of repaired.

    This is the check that would have caught kriegerdataforge-sdk, which pinned
    kdf-fmt v1.1.1 for local dev while its CI style job ran v1.1.0.

    Args:
        text: the repo's current ci.yml content, or None when absent
        expected_ref: the canonical git ref, e.g. ``v1.1.1``

    Returns:
        str: the content exactly as received, when it is already consistent

    Raises:
        PatchError: when ci.yml is missing, has no kdf_fmt_ref, or pins another ref
    """
    if text is None:
        raise PatchError(f"{CI_YAML_DEST} not found in the target repo")
    match = _KDF_FMT_REF_RE.search(text.replace("\r\n", "\n"))
    if match is None:
        raise PatchError(f"{CI_YAML_DEST} declares no kdf_fmt_ref to compare")
    found = match.group(2).strip().strip("\"'")
    if found != expected_ref:
        raise PatchError(
            f"{CI_YAML_DEST} pins kdf_fmt_ref {found} but the canonical pin is "
            f"{expected_ref}. Local dev and CI would format with different kdf-fmt "
            "versions. Update the workflow by hand (the distributor never writes "
            "workflow files)."
        )
    return text


def patch_ruff_toml(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to a tenant's ruff.toml `exclude` list.

    Args:
        text: the repo's current ruff.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when ruff.toml is missing or has no top-level `exclude` list
    """
    if text is None:
        raise PatchError("declared ruff.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    match = re.search(r"^(exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if not match:
        raise PatchError("ruff.toml has no top-level `exclude` list to extend")
    return normalized[: match.end()] + "\n    " + _VENDOR_EXCLUDE_ENTRY + "," + normalized[match.end():]


def patch_ruff_pyproject(text: str | None) -> str:
    """
    Append the vendor-dir exclusion to `[tool.ruff]` in a tenant's pyproject.toml.

    Inserts into an existing `extend-exclude = [` list, or adds the key directly under
    the `[tool.ruff]` header. Never touches anything else in the file (notably the
    project version line).

    Args:
        text: the repo's current pyproject.toml content, or None when absent

    Returns:
        str: the patched config (LF endings)

    Raises:
        PatchError: when pyproject.toml is missing or has no `[tool.ruff]` table
    """
    if text is None:
        raise PatchError("declared pyproject.toml not found in the target repo")
    normalized = text.replace("\r\n", "\n")
    if VENDOR_DIR in normalized:
        return normalized
    extend = re.search(r"^(extend-exclude\s*=\s*\[)", normalized, re.MULTILINE)
    if extend:
        return normalized[: extend.end()] + _VENDOR_EXCLUDE_ENTRY + ", " + normalized[extend.end():]
    header = re.search(r"^\[tool\.ruff\]\s*$", normalized, re.MULTILINE)
    if not header:
        raise PatchError("pyproject.toml has no [tool.ruff] table to extend")
    insert = (
        "\n# distributed ecosystem scripts are vendored -- linted in kriegerdataforge-cicd\n"
        f"extend-exclude = [{_VENDOR_EXCLUDE_ENTRY}]"
    )
    return normalized[: header.end()] + insert + normalized[header.end():]


def _build_items(registry: dict, only: str | None, entry: dict) -> list[SyncItem]:
    """
    Build the SyncItems for ONE registry repo entry.

    The registry's src->dest files (byte-identical), the deletes[] of superseded paths,
    the Makefile patch, the kdf-fmt.toml exclusion, and — when the entry declares a
    `ruff_config` — the matching ruff exclusion. Optionally narrowed by --only
    (dest substring).

    Args:
        registry: the parsed scripts registry
        only: dest-substring filter, or None for all items
        entry: the registry repo entry the items are built for

    Returns:
        list[SyncItem]: the items to check or distribute for this repo

    Raises:
        PatchError: when the entry declares an unknown ruff_config value
    """
    items: list[SyncItem] = []
    for file_entry in registry.get("files", []):
        src, dest = file_entry["src"], file_entry["dest"]
        canonical = (REPO_ROOT / src).read_text(encoding = "utf-8")
        items.append(SyncItem(dest = dest, desired = lambda _remote, content = canonical: content))
    for stale in registry.get("deletes", []):
        items.append(SyncItem(dest = stale, desired = None))
    if registry.get("makefile_patch"):
        items.append(SyncItem(dest = MAKEFILE_DEST, desired = patch_makefile))
    if registry.get("kdf_fmt_patch"):
        items.append(SyncItem(dest = KDF_FMT_DEST, desired = patch_kdf_fmt_toml))
    # A repo that PROVIDES one of the canonical packages must not pin it: kdf-fmt's own
    # repo would end up depending on itself, and it carries no kdf_fmt_ref in ci.yml
    # because it is the formatter rather than a consumer of one.
    requirements = registry.get("requirements_patch")
    if requirements and not entry.get("skip_requirements"):
        packages = requirements.get("packages", [])
        items.append(SyncItem(
            dest = requirements.get("target", REQUIREMENTS_DEST),
            desired = lambda text, pkgs = packages: patch_requirements(text, pkgs),
        ))
        # Read-only companion: proves the workflow pins the same ref, writes nothing.
        toolchain_ref = requirements.get("kdf_fmt_ref")
        if toolchain_ref:
            items.append(SyncItem(
                dest = CI_YAML_DEST,
                desired = lambda text, ref = toolchain_ref: patch_ci_yaml(text, ref),
            ))
    ruff_config = entry.get("ruff_config")
    if ruff_config:
        ruff_patchers = {"ruff.toml": patch_ruff_toml, "pyproject.toml": patch_ruff_pyproject}
        patcher       = ruff_patchers.get(ruff_config)
        if patcher is None:
            raise PatchError(f"unknown ruff_config {ruff_config!r} (use 'ruff.toml' or 'pyproject.toml')")
        items.append(SyncItem(dest = ruff_config, desired = patcher))
    if only:
        items = [item for item in items if only in item.dest]
        if not items:
            sys.exit(f"Error: --only '{only}' matched no synced items for this run.")
    return items

# ======================================================================================================================
# CLI
# ======================================================================================================================

def parse_cli_args() -> argparse.Namespace:
    """
    Parse the CLI arguments.

    Returns:
        argparse.Namespace: mode, only, repos
    """
    parser = argparse.ArgumentParser(
        description = "Check or distribute the ecosystem dev scripts across all repos.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = _CLI_EPILOG,
    )
    parser.add_argument(
        "mode",
        choices = ["check", "distribute"],
        help = "'check' reports drift (opens nothing). 'distribute' opens one PR per drifted repo.",
    )
    parser.add_argument(
        "--only",
        default = None,
        help = "Only operate on synced items whose DEST path contains this substring (e.g. 'check_version.py').",
    )
    parser.add_argument(
        "--repos",
        default = None,
        help = _REPOS_HELP,
    )
    return parser.parse_args()


def main() -> None:
    """
    Run the selected mode (check or distribute) and exit with its status code.

    Returns:
        None
    """
    args     = parse_cli_args()
    registry = _load_registry()
    token    = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        sys.exit("Error: GH_TOKEN environment variable not set.")

    version = _scripts_version()
    repos   = _select_repos(registry, args.repos)


    def items_for(entry: dict) -> list[SyncItem]:
        """
        Build this repo entry's items (closure over the registry and --only filter).

        Args:
            entry: the registry repo entry

        Returns:
            list[SyncItem]: the items for this repo
        """
        return _build_items(registry, args.only, entry)


    if args.mode == "check":
        banner = f"Checking ecosystem dev scripts {version} across {len(repos)} repo(s):"
        sys.exit(run_check(token, repos, items_for, banner))
    else:
        print(f"Distributing ecosystem dev scripts {version} to {len(repos)} repo(s):")
        sys.exit(
            run_distribute(
                token,
                repos,
                items_for,
                sync_branch = f"chore/scripts-sync-{version}",
                pr_title = f"chore(scripts): sync ecosystem dev scripts {version}",
                pr_body_fn = lambda drift: _PR_BODY_TEMPLATE.format(
                    version = version,
                    items = ", ".join(item.dest for item in drift),
                ),
                commit_msg_fn = lambda item: (
                    f"chore(scripts): remove superseded {item.dest} ({version})"
                    if item.desired is None
                    else f"chore(scripts): sync {item.dest} to {version}"
                ),
            )
        )


if __name__ == "__main__":
    main()
