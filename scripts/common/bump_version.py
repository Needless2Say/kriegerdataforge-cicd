#!/usr/bin/env python3
"""Bump the project version (patch | minor | major) across all version files."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_version(v: str) -> tuple[int, int, int]:
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"'{v}' is not a valid semver (expected X.Y.Z)")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(f"'{v}' contains non-integer components")


def bump(current: tuple[int, int, int], bump_type: str) -> tuple[int, int, int]:
    maj, min_, pat = current
    if bump_type == "major":
        return (maj + 1, 0, 0)
    if bump_type == "minor":
        return (maj, min_ + 1, 0)
    if bump_type == "patch":
        return (maj, min_, pat + 1)
    raise ValueError(f"Unknown bump type {bump_type!r}. Use: patch, minor, or major.")


def fmt(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("patch", "minor", "major"):
        print("Usage: python3 scripts/common/bump_version.py <patch|minor|major>")
        sys.exit(1)

    bump_type = sys.argv[1]
    # scripts/common/bump_version.py -> scripts/common/ -> scripts/ -> repo root
    root = Path(__file__).parent.parent.parent

    # ── VERSION (required) ──────────────────────────────────────────────────
    version_file = root / "VERSION"
    if not version_file.exists():
        print("ERROR: VERSION file not found at repo root.")
        sys.exit(1)

    old_str = version_file.read_text().strip()
    try:
        old = parse_version(old_str)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    new = bump(old, bump_type)
    new_str = fmt(new)
    print(f"Bumping {bump_type}: {old_str} -> {new_str}\n")
    updated: list[str] = []

    version_file.write_text(new_str + "\n")
    updated.append("VERSION")

    # ── pyproject.toml ──────────────────────────────────────────────────────
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        new_text = re.sub(
            r'(?m)^(version\s*=\s*)"[^"]+"',
            f'\\1"{new_str}"',
            text,
            count=1,
        )
        if new_text != text:
            pyproject.write_text(new_text)
            updated.append("pyproject.toml")

    # ── src/**/__init__.py ──────────────────────────────────────────────────
    for init_file in sorted(root.glob("src/**/__init__.py")):
        text = init_file.read_text()
        new_text = re.sub(
            r'(?m)^(__version__\s*=\s*)"[^"]+"',
            f'\\1"{new_str}"',
            text,
            count=1,
        )
        if new_text != text:
            init_file.write_text(new_text)
            updated.append(str(init_file.relative_to(root)))

    # ── package.json ────────────────────────────────────────────────────────
    package_json = root / "package.json"
    if package_json.exists():
        text = package_json.read_text()
        new_text = re.sub(
            r'"version":\s*"[^"]+"',
            f'"version": "{new_str}"',
            text,
            count=1,
        )
        if new_text != text:
            package_json.write_text(new_text)
            updated.append("package.json")

    print("OK  Updated:")
    for f in updated:
        print(f"    {f}")
    print(f"\n->  Next: open a PR -- version bump check will validate {old_str} -> {new_str}")


if __name__ == "__main__":
    main()
