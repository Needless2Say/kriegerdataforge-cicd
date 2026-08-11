#!/usr/bin/env python3
"""
CI version checker — shared script for all KriegerDataForge repos.

Validates that every version-bearing file agrees with VERSION and that the
current version is EXACTLY ONE valid semver increment ahead of the version on
the base branch:

    patch:  X.Y.Z   -> X.Y.Z+1
    minor:  X.Y.Z   -> X.Y+1.0
    major:  X.Y.Z   -> X+1.0.0

Anything else (no bump, skip by 2, downgrade, minor without patch reset, ...)
fails with the allowed next versions in the message. Which files must agree is
decided by ``version_targets.py`` (auto-detect by presence, or the repo's
optional ``scripts/version_targets.json`` manifest) — the same resolution
``bump_version.py`` writes, so the two can never disagree.

Runs from two locations (byte-identical file, ADR D-013):
  - ``.cicd/scripts/common/check_version.py`` — every consumer repo's CI job.
  - ``scripts/check_version.py``              — vendored per repo; the local
    ``make ci-version-check`` lane runs this one.

Exit code: 0 = all checks pass, 1 = any check fails.

Usage:
    python scripts/check_version.py [options]

Options:
    --root PATH           Repo root to check (default: current working directory).
                          In GitHub Actions the CWD is already the repo checkout root,
                          so this flag is only needed for local use in unusual setups.
    --base-branch NAME    Base branch to compare against (default: main).
    --skip-init           Accepted for back-compat; target detection is automatic now.
    --check-package-json  Accepted for back-compat; target detection is automatic now.
"""

from __future__ import annotations

# standard imports
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# full path to git (S607: no partial executable paths); falls back for exotic setups
_GIT = shutil.which("git") or "git"

# ======================================================================================================================
# Sync-PR exemption config (ADR D-001 option B; extended to script sync by ADR D-013)
# ======================================================================================================================

# A kit-sync PR (distribute_kit.py) or a script-sync PR (distribute_scripts.py)
# only carries centrally-synced files and does NOT bump VERSION; such a PR would
# otherwise fail this gate. When a PR changes ONLY synced paths, skip the version
# check. Outside a PR (no GITHUB_BASE_REF — local runs, pushes) the normal check
# always runs.
#
# The exempt FILE set is DERIVED from the registries (kit_registry.json files[],
# scripts_registry.json files[].dest) — the single sources of truth for what the
# distributors sync — so it can never drift from the synced sets. The static
# fallbacks are used only when a registry isn't co-located with this script
# (consumer CI checks out cicd beside it as `.cicd/`, so it normally is; the
# VENDORED copy has no registries, but the exemption only fires in PR CI, which
# runs the `.cicd` copy). `Makefile` is exempt ONLY on a `chore/scripts-sync-*`
# head branch (the script distributor rewrites one recipe) — an ordinary
# Makefile-only PR still requires a version bump.
_REGISTRY_CANDIDATES          = (
    Path(__file__).resolve().parent.parent,   # canonical: scripts/common/.. -> scripts/
    Path(__file__).resolve().parent,          # vendored:  scripts/
)
KIT_EXEMPT_FILES_FALLBACK     = {"skills.md", "WORKFLOW.md"}
SCRIPTS_EXEMPT_FILES_FALLBACK = {"scripts/check_version.py", "scripts/bump_version.py", "scripts/version_targets.py"}
KIT_EXEMPT_PREFIXES           = ("docs/agent/",)
SCRIPTS_SYNC_BRANCH_PREFIX    = "chore/scripts-sync-"

# local imports — same-directory vendored layout fails over to the canonical package
# layout (scripts/common/ under the cicd checkout / test runs). Sits below the constants
# because a top-level try block ends the module preamble (KDF-102).
try:
    from common import version_targets
except ImportError:
    import version_targets


def _read_version_file(root: Path) -> str:
    """
    Read the repo's plain-text VERSION file.

    Args:
        root: repo root directory

    Returns:
        str: the stripped VERSION value
    """
    return (root / "VERSION").read_text(encoding = "utf-8-sig").strip()


def _parse_semver(v: str) -> tuple[int, int, int]:
    """
    Parse a semver string into an integer tuple.

    Args:
        v: the version string

    Returns:
        tuple[int, int, int]: the parsed (major, minor, patch)

    Raises:
        ValueError: when the string is not X.Y.Z with integer components
    """
    parts = v.split(".")
    if len(parts) != 3:
        raise ValueError(f"not a valid semver: {v!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _allowed_next(base: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """
    List the only versions a PR may carry: exactly one patch / minor / major increment.

    Args:
        base: the base branch's (major, minor, patch)

    Returns:
        list[tuple[int, int, int]]: the three allowed next versions, in patch/minor/major order
    """
    maj, min_, pat = base
    return [
        (maj, min_, pat + 1),   # patch
        (maj, min_ + 1, 0),     # minor
        (maj + 1, 0, 0),        # major
    ]


def _fetch_base(cwd: Path, base_branch: str) -> None:
    """
    Best-effort shallow fetch of the base branch so origin/<base> is resolvable.

    Args:
        cwd: repo directory to run git in
        base_branch: the base branch name

    Returns:
        None
    """
    subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "fetch", "origin", base_branch, "--depth=1"],
        capture_output = True,
        check = False,
        cwd = cwd,
    )


def _get_base_version(cwd: Path, base_branch: str) -> str | None:
    """
    Read VERSION as it exists on origin/<base_branch>.

    Args:
        cwd: repo directory to run git in
        base_branch: the base branch name

    Returns:
        str | None: the base branch's VERSION, or None when unreadable
    """
    result = subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "show", f"origin/{base_branch}:VERSION"],
        capture_output = True,
        text = True,
        check = False,
        cwd = cwd,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _read_registry(name: str) -> dict | None:
    """
    Load a registry JSON co-located with this script (canonical or vendored layout).

    Args:
        name: registry filename, e.g. "kit_registry.json"

    Returns:
        dict | None: the parsed registry, or None when not readable in any candidate dir
    """
    for candidate_dir in _REGISTRY_CANDIDATES:
        try:
            return json.loads((candidate_dir / name).read_text(encoding = "utf-8"))
        except (OSError, ValueError):
            continue
    return None


def _kit_exempt_files() -> set[str]:
    """
    Collect the kit files exempt from the version check.

    Derived from the kit registry's file list unioned with the static fallback;
    just the fallback when the registry can't be read.

    Returns:
        set[str]: exempt kit file paths
    """
    files = set(KIT_EXEMPT_FILES_FALLBACK)
    data  = _read_registry("kit_registry.json")
    if data is not None:
        files.update(path for path in data.get("files", []) if isinstance(path, str))
    return files


def _scripts_exempt_files() -> set[str]:
    """
    Collect the synced-script destination paths exempt from the version check.

    Derived from scripts_registry.json files[].dest, with a static fallback.

    Returns:
        set[str]: exempt script destination paths
    """
    files = set(SCRIPTS_EXEMPT_FILES_FALLBACK)
    data  = _read_registry("scripts_registry.json")
    if data is not None:
        files.update(
            entry["dest"]
            for entry in data.get("files", [])
            if isinstance(entry, dict) and isinstance(entry.get("dest"), str)
        )
    return files


def _changed_files(cwd: Path, base_ref: str) -> list[str]:
    """
    List the files a PR changes relative to its base ref.

    Args:
        cwd: repo directory to run git in
        base_ref: the PR's base branch name (GITHUB_BASE_REF)

    Returns:
        list[str]: changed file paths, empty when the diff cannot be computed
    """
    subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "fetch", "origin", base_ref, "--depth=1"],
        capture_output = True,
        check = False,
        cwd = cwd,
    )
    result = subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "diff", "--name-only", f"origin/{base_ref}", "HEAD"],
        capture_output = True,
        text = True,
        check = False,
        cwd = cwd,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_exempt_sync_pr(cwd: Path) -> bool:
    """
    Decide whether this run is a PR whose changed files are ALL centrally-synced paths.

    Covers the agentic-workflow kit and the distributed dev scripts (plus their
    Makefile recipe, on scripts-sync branches only).

    Args:
        cwd: repo directory to run git in

    Returns:
        bool: True when the version check should be skipped for this PR
    """
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if not base_ref:
        return False  # not a PR context — run the normal check
    files = _changed_files(cwd, base_ref)
    if not files:
        return False
    kit_exempt     = _kit_exempt_files()
    scripts_exempt = _scripts_exempt_files()
    on_sync_branch = os.environ.get("GITHUB_HEAD_REF", "").startswith(SCRIPTS_SYNC_BRANCH_PREFIX)
    for changed in files:
        if changed in kit_exempt or changed in scripts_exempt:
            continue
        if any(changed.startswith(prefix) for prefix in KIT_EXEMPT_PREFIXES):
            continue
        if changed == "Makefile" and on_sync_branch:
            continue
        return False
    return True


def main() -> None:
    """
    Run the consistency and strict-increment checks; exit 1 on any failure.

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description = "CI version checker")
    parser.add_argument(
        "--root",
        type = Path,
        default = None,
        help = "Repo root to check (default: current working directory)",
    )
    parser.add_argument(
        "--base-branch",
        default = "main",
        help = "Base branch to compare against (default: main)",
    )
    parser.add_argument(
        "--skip-init",
        action = "store_true",
        help = "Accepted for back-compat; target detection is automatic now",
    )
    parser.add_argument(
        "--check-package-json",
        action = "store_true",
        help = "Accepted for back-compat; target detection is automatic now",
    )
    args = parser.parse_args()

    root = args.root if args.root is not None else Path.cwd()

    if _is_exempt_sync_pr(root):
        print(
            "Sync PR (agentic-workflow kit or distributed dev scripts) — skipping version "
            "check (ADR D-001 option B / ADR D-013)."
        )
        return

    passed  = True
    version = _read_version_file(root)

    # consistency: every resolved target must carry VERSION's value
    try:
        targets = version_targets.resolve_targets(root)
    except version_targets.TargetError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)

    width = max(len(target.path) for target in targets)
    for target in targets:
        try:
            value = version_targets.read_version(root, target)
        except version_targets.TargetError as exc:
            print(f"{target.path:<{width}} : FAIL -- {exc}")
            passed = False
            continue
        print(f"{target.path:<{width}} : {value}")

    print()
    for target in targets:
        if target.path == "VERSION":
            continue
        try:
            value = version_targets.read_version(root, target)
        except version_targets.TargetError:
            continue  # already reported above
        if value == version:
            print(f"OK  : {target.path} matches VERSION ({version})")
        else:
            print(f"FAIL: {target.path} version ({value!r}) != VERSION ({version!r})")
            print("      Run: make bump-patch (or bump-minor / bump-major) to sync files.")
            passed = False

    print()

    # strict single-increment check vs the base branch
    print(f"Checking increment vs origin/{args.base_branch} ...")
    _fetch_base(root, args.base_branch)
    base_version = _get_base_version(root, args.base_branch)

    if base_version is None:
        print(f"WARNING: could not read VERSION from origin/{args.base_branch} -- skipping increment check.")
        print("         This is expected on a brand-new repo before the first commit to main.")
    else:
        print(f"origin/{args.base_branch}: {base_version}")
        try:
            current_tuple = _parse_semver(version)
            base_tuple    = _parse_semver(base_version)
            allowed       = _allowed_next(base_tuple)
            if current_tuple == base_tuple:
                print(f"FAIL: version ({version}) is the same as origin/{args.base_branch} ({base_version}).")
                print("      Bump the version before merging: make bump-patch")
                passed = False
            elif current_tuple in allowed:
                bump_type = ["patch", "minor", "major"][allowed.index(current_tuple)]
                print(f"OK  : {base_version} -> {version} (valid {bump_type} bump)")
            else:
                allowed_str = ", ".join(".".join(str(part) for part in candidate) for candidate in allowed)
                print(f"FAIL: invalid version jump {base_version} -> {version}.")
                print(f"      Allowed next versions: {allowed_str}")
                print("      Rules: increment exactly one component by 1; minor resets patch to 0;")
                print("             major resets minor and patch to 0; skipping versions is not allowed.")
                print("      Run: make bump-patch (or bump-minor / bump-major) -- it bumps from the base branch.")
                passed = False
        except ValueError as exc:
            print(f"FAIL: could not parse semver -- {exc}")
            passed = False

    print()
    if passed:
        print("All version checks passed.")
    else:
        print("Version check failed. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
