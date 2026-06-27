#!/usr/bin/env python3
"""
CI version checker — shared script for all KriegerDataForge repos.

Validates that version sources are consistent with each other and that the
current version is strictly greater than the version on the main branch.

Exit code: 0 = all checks pass, 1 = any check fails.

Usage:
    python .cicd/scripts/common/check_version.py [options]

Options:
    --root PATH           Repo root to check (default: current working directory).
                          In GitHub Actions the CWD is already the repo checkout root,
                          so this flag is only needed for local use in unusual setups.
    --skip-init           Skip the src/*/__init__.py __version__ check.
    --check-package-json  Also verify that package.json "version" matches VERSION.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _read_version_file(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8-sig").strip()


def _read_pyproject_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _read_init_versions(root: Path) -> list[tuple[str, str]]:
    """Return [(version, relative_path)] for every src/*/__init__.py with __version__."""
    versions: list[tuple[str, str]] = []
    for path in sorted(root.glob("src/*/__init__.py")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if match:
            versions.append((match.group(1), str(path.relative_to(root))))
    return versions


def _read_package_json_version(root: Path) -> str | None:
    path = root / "package.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("version")
    except (json.JSONDecodeError, OSError):
        return None


def _parse_semver(v: str) -> tuple[int, int, int]:
    parts = v.split(".")
    if len(parts) != 3:
        raise ValueError(f"not a valid semver: {v!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _fetch_main(cwd: Path) -> None:
    subprocess.run(
        ["git", "fetch", "origin", "main", "--depth=1"],
        capture_output=True,
        check=False,
        cwd=cwd,
    )


def _get_main_version(cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "show", "origin/main:VERSION"],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ── Kit-only PR exemption (ADR D-001, option B) ──────────────────────────────
# A kit-sync PR (opened by distribute_kit.py) only touches the byte-identical
# agentic-workflow kit, which is documentation and does NOT bump VERSION. Such a
# PR would otherwise fail this gate. When a PR changes ONLY kit paths, skip the
# version check. Outside a PR (no GITHUB_BASE_REF — local runs, pushes) the normal
# check always runs.
KIT_EXEMPT_FILES = {"skills.md", "WORKFLOW.md"}
KIT_EXEMPT_PREFIXES = ("docs/agent/",)


def _changed_files(cwd: Path, base_ref: str) -> list[str]:
    subprocess.run(
        ["git", "fetch", "origin", base_ref, "--depth=1"],
        capture_output=True,
        check=False,
        cwd=cwd,
    )
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_kit_only_pr(cwd: Path) -> bool:
    """True if this is a PR whose changed files are ALL agentic-workflow kit paths."""
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if not base_ref:
        return False  # not a PR context — run the normal check
    files = _changed_files(cwd, base_ref)
    if not files:
        return False
    for f in files:
        if f in KIT_EXEMPT_FILES:
            continue
        if any(f.startswith(p) for p in KIT_EXEMPT_PREFIXES):
            continue
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="CI version checker")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root to check (default: current working directory)",
    )
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Skip src/*/__init__.py __version__ check",
    )
    parser.add_argument(
        "--check-package-json",
        action="store_true",
        help="Also verify that package.json version matches VERSION",
    )
    args = parser.parse_args()

    root = args.root if args.root is not None else Path.cwd()

    if _is_kit_only_pr(root):
        print(
            "Kit-only PR (skills.md / WORKFLOW.md / docs/agent/**) — skipping version "
            "check (agentic-workflow kit sync, ADR D-001 option B)."
        )
        return

    passed = True

    # Read version from each source
    version = _read_version_file(root)
    pyproject_version = _read_pyproject_version(root)
    init_versions = [] if args.skip_init else _read_init_versions(root)
    package_json_version = _read_package_json_version(root) if args.check_package_json else None

    # Print discovered values
    print(f"VERSION            : {version}")

    if pyproject_version is not None:
        print(f"pyproject.toml     : {pyproject_version}")
    else:
        print("pyproject.toml     : (not found)")

    if args.skip_init:
        print("__init__.py        : (skipped via --skip-init)")
    elif init_versions:
        for init_version, init_path in init_versions:
            print(f"__init__.py        : {init_version}  ({init_path})")
    else:
        print(
            "WARNING: no __version__ found in src/*/__init__.py"
            " -- pass --skip-init to suppress this warning"
        )

    if args.check_package_json:
        if package_json_version is not None:
            print(f"package.json       : {package_json_version}")
        else:
            print("package.json       : (not found or no version field)")

    print()

    # Consistency checks
    if pyproject_version is not None:
        if pyproject_version == version:
            print(f"OK  : pyproject.toml matches VERSION ({version})")
        else:
            print(
                f"FAIL: pyproject.toml version ({pyproject_version!r})"
                f" != VERSION ({version!r})"
            )
            print("      Run: make bump-patch (or bump-minor / bump-major) to sync files.")
            passed = False

    for init_version, init_path in init_versions:
        if init_version == version:
            print(f"OK  : {init_path} matches VERSION ({version})")
        else:
            print(
                f"FAIL: {init_path} __version__ ({init_version!r})"
                f" != VERSION ({version!r})"
            )
            print("      Run: make bump-patch (or bump-minor / bump-major) to sync files.")
            passed = False

    if args.check_package_json:
        if package_json_version is None:
            print("FAIL: package.json not found or has no version field")
            passed = False
        elif package_json_version == version:
            print(f"OK  : package.json matches VERSION ({version})")
        else:
            print(
                f"FAIL: package.json version ({package_json_version!r})"
                f" != VERSION ({version!r})"
            )
            print("      Run: make bump-patch (or bump-minor / bump-major) to sync files.")
            passed = False

    print()

    # Increment check vs main
    print("Checking increment vs origin/main ...")
    _fetch_main(root)
    main_version = _get_main_version(root)

    if main_version is None:
        print(
            "WARNING: could not read VERSION from origin/main -- skipping increment check."
        )
        print(
            "         This is expected on a brand-new repo before the first commit to main."
        )
    else:
        print(f"origin/main        : {main_version}")
        try:
            current_tuple = _parse_semver(version)
            main_tuple = _parse_semver(main_version)
            if current_tuple > main_tuple:
                print(f"OK  : {main_version} -> {version} (increment valid)")
            elif current_tuple == main_tuple:
                print(
                    f"FAIL: version ({version}) is the same as main ({main_version})."
                )
                print("      Bump the version before merging: make bump-patch")
                passed = False
            else:
                print(
                    f"FAIL: version ({version}) is less than main ({main_version})."
                )
                print(
                    "      Check that your branch is up to date with main"
                    " and that the VERSION file was not accidentally reverted."
                )
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
