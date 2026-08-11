#!/usr/bin/env python3
"""
Bump the project version (patch | minor | major) across all version-bearing files.

Canonical ecosystem script (source: ``kriegerdataforge-cicd/scripts/common/``,
vendored byte-identical to every repo as ``scripts/bump_version.py`` by
``distribute_scripts.py`` — ADR D-013). Which files get written is decided by
``version_targets.py`` (auto-detect by presence, or the repo's optional
``scripts/version_targets.json`` manifest) so this script and the CI checker can
never disagree about the target set.

The bump is computed from **origin/<base-branch>'s VERSION** whenever it is
readable — NOT from the local VERSION file. That makes an accidental double-bump
impossible: re-running ``make bump-patch`` is idempotent (0.10.6 on main stays
-> 0.10.7), and ``make bump-minor`` after a stray patch-bump corrects the branch
to 0.11.0 instead of stacking on top. When origin/<base-branch> cannot be read
(fresh clone, offline, brand-new repo) it falls back to the local VERSION with a
warning — CI still enforces the strict single-increment rule either way.

Usage:
    python scripts/bump_version.py <patch|minor|major> [--base-branch main] [--root PATH]

Stdlib-only; ASCII-only output (runs in cp1252 Windows consoles).
"""

from __future__ import annotations

# standard imports
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# full path to git (S607: no partial executable paths); falls back for exotic setups
_GIT = shutil.which("git") or "git"

# local imports — same-directory vendored layout fails over to the canonical package
# layout (scripts/common/ under the cicd checkout / test runs). Sits below the constant
# because a top-level try block ends the module preamble (KDF-102).
try:
    from common import version_targets
except ImportError:
    import version_targets


def parse_version(v: str) -> tuple[int, int, int]:
    """
    Parse a semver string into an (major, minor, patch) integer tuple.

    Args:
        v: the version string, e.g. "0.10.6"

    Returns:
        tuple[int, int, int]: the parsed (major, minor, patch)

    Raises:
        ValueError: when the string is not X.Y.Z with integer components
    """
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"'{v}' is not a valid semver (expected X.Y.Z)")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(f"'{v}' contains non-integer components")


def bump(current: tuple[int, int, int], bump_type: str) -> tuple[int, int, int]:
    """
    Compute the next version for one bump type.

    Args:
        current: the (major, minor, patch) tuple to bump from
        bump_type: one of "patch", "minor", "major"

    Returns:
        tuple[int, int, int]: the bumped version tuple

    Raises:
        ValueError: on an unknown bump type
    """
    maj, min_, pat = current
    if bump_type == "major":
        return (maj + 1, 0, 0)
    if bump_type == "minor":
        return (maj, min_ + 1, 0)
    if bump_type == "patch":
        return (maj, min_, pat + 1)
    raise ValueError(f"Unknown bump type {bump_type!r}. Use: patch, minor, or major.")


def fmt(v: tuple[int, int, int]) -> str:
    """
    Format a version tuple back into its dotted string form.

    Args:
        v: the (major, minor, patch) tuple

    Returns:
        str: the "X.Y.Z" string
    """
    return f"{v[0]}.{v[1]}.{v[2]}"


def find_root(override: Path | None) -> Path:
    """
    Locate the repo root to operate on.

    --root wins when given; otherwise the nearest ancestor of the CWD holding a
    VERSION file; otherwise the script location's repo (vendored scripts/.. or
    canonical scripts/common/../..).

    Args:
        override: the --root value, or None

    Returns:
        Path: the repo root (guaranteed to hold a VERSION file)
    """
    if override is not None:
        if not (override / "VERSION").is_file():
            sys.exit(f"FAIL: no VERSION file at --root {override}")
        return override
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "VERSION").is_file():
            return candidate
    here = Path(__file__).resolve()
    for fallback in (here.parent.parent, here.parent.parent.parent):  # scripts/.. and scripts/common/..
        if (fallback / "VERSION").is_file():
            return fallback
    sys.exit("FAIL: no VERSION file found walking up from the current directory.")


def get_base_version(root: Path, base_branch: str) -> tuple[str, str]:
    """
    Read the version the bump should be computed FROM.

    Tries origin/<base_branch>'s VERSION (after a best-effort shallow fetch);
    falls back to the local VERSION file with a warning when it cannot be read.

    Args:
        root: repo root directory
        base_branch: the base branch name (usually "main")

    Returns:
        tuple[str, str]: (version, source) where source is "origin/<base_branch>" or "local"
    """
    subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "fetch", "origin", base_branch, "--depth=1"],
        capture_output = True,
        check = False,
        cwd = root,
    )
    result = subprocess.run(  # noqa: S603  (internal args only)
        [_GIT, "show", f"origin/{base_branch}:VERSION"],
        capture_output = True,
        text = True,
        check = False,
        cwd = root,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip(), f"origin/{base_branch}"
    print(
        f"WARNING: could not read VERSION from origin/{base_branch} -- bumping from the local "
        "VERSION file instead. CI still enforces the strict single-increment rule."
    )
    local = (root / "VERSION").read_text(encoding = "utf-8-sig").strip()
    return local, "local"


def parse_cli_args() -> argparse.Namespace:
    """
    Parse the CLI arguments.

    Returns:
        argparse.Namespace: bump_type, base_branch, root
    """
    parser = argparse.ArgumentParser(description = "Bump the project version across all version files.")
    parser.add_argument("bump_type", choices = ["patch", "minor", "major"], help = "Which semver component to bump.")
    parser.add_argument(
        "--base-branch",
        default = "main",
        help = "Branch whose VERSION the bump is computed from (default: main).",
    )
    parser.add_argument(
        "--root",
        type = Path,
        default = None,
        help = "Repo root (default: nearest ancestor of the CWD with a VERSION file).",
    )
    return parser.parse_args()


def main() -> None:
    """
    Compute the new version from the base branch and write it into every target.

    Returns:
        None
    """
    args = parse_cli_args()
    root = find_root(args.root)

    base_str, base_source = get_base_version(root, args.base_branch)
    try:
        base = parse_version(base_str)
    except ValueError as exc:
        sys.exit(f"FAIL: {base_source} VERSION -- {exc}")

    local_str = (root / "VERSION").read_text(encoding = "utf-8-sig").strip()
    new_str   = fmt(bump(base, args.bump_type))

    print(f"Bumping {args.bump_type} from {base_source}: {base_str} -> {new_str}")
    if base_source != "local" and local_str not in (base_str, new_str):
        print(f"NOTE: local VERSION was {local_str}; rebasing the bump onto {base_source} ({base_str}).")
    print()

    try:
        targets = version_targets.resolve_targets(root)
    except version_targets.TargetError as exc:
        sys.exit(f"FAIL: {exc}")

    updated:   list[str] = []
    unchanged: list[str] = []
    for target in targets:
        try:
            changed = version_targets.write_version(root, target, new_str)
        except version_targets.TargetError as exc:
            sys.exit(f"FAIL: {exc}")
        (updated if changed else unchanged).append(target.path)

    print("Updated:")
    for path in updated:
        print(f"    {path}")
    for path in unchanged:
        print(f"    {path} (already {new_str})")
    print(f"\n->  Next: open a PR -- the version check validates {base_str} -> {new_str} as a strict single increment.")


if __name__ == "__main__":
    main()
