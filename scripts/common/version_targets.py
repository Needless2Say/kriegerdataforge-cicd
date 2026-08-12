"""
Version-target resolution — the ONE place that decides which files carry a repo's version.

Used by BOTH ``bump_version.py`` (writes the new version into every target) and
``check_version.py`` (verifies every target equals VERSION), so the two can never
disagree about what "the version files" are. Vendored byte-identical to every repo
as ``scripts/version_targets.py`` next to those two scripts (canonical source:
``kriegerdataforge-cicd/scripts/common/version_targets.py``, synced by
``distribute_scripts.py`` — ADR D-013).

Two resolution layers:

1. **Auto-detect by presence** (default, zero config). Covers every current repo
   shape — FastAPI backends (pyproject.toml and/or the Vercel-compacted
   ``vercel_api/pyproject.toml``), Python packages (``src/*/__init__.py``
   ``__version__``), Next.js apps and npm packages (package.json +
   package-lock.json), and VERSION-only repos (terraform).
2. **Optional per-repo manifest** ``scripts/version_targets.json`` (NOT vendored;
   create it only where auto-detect is not enough). When present it is
   authoritative and a declared-but-missing file is a HARD FAIL — the
   rename-safety guard auto-detect cannot give (auto-detect silently drops a
   file that gets renamed away). Format::

       {"targets": ["VERSION", "pyproject.toml", {"path": "x/y.toml", "kind": "pyproject"}]}

   String entries infer their kind from the filename; dict entries name it
   explicitly. A future repo type is a manifest entry (or a new kind here) —
   never a new script.

Stdlib-only; ASCII-only output (runs in cp1252 Windows consoles).
"""

from __future__ import annotations

# standard imports
import json
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST_PATH = Path("scripts") / "version_targets.json"

# kinds and the filenames that imply them (for string manifest entries + auto-detect)
KIND_VERSION_FILE = "version-file"
KIND_PYPROJECT    = "pyproject"
KIND_INIT_PY      = "init-py"
KIND_PACKAGE_JSON = "package-json"
KIND_PACKAGE_LOCK = "package-lock"

_KNOWN_KINDS = {KIND_VERSION_FILE, KIND_PYPROJECT, KIND_INIT_PY, KIND_PACKAGE_JSON, KIND_PACKAGE_LOCK}

_PYPROJECT_RE    = re.compile(r'^(version\s*=\s*)"([^"]+)"', re.MULTILINE)
_INIT_RE         = re.compile(r'^(__version__\s*=\s*)"([^"]+)"', re.MULTILINE)
_PACKAGE_JSON_RE = re.compile(r'("version"\s*:\s*)"([^"]+)"')


class TargetError(ValueError):
    """
    A target is misdeclared or unusable: declared in the manifest but missing on
    disk, an unknown kind, or a file whose version field cannot be found.
    """


@dataclass
class Target:
    """
    One version-bearing file: repo-relative ``path`` plus the read/write strategy ``kind``.
    """
    path: str
    kind: str


def _infer_kind(path: str) -> str:
    """
    Infer a target kind from a path's filename (for string manifest entries).

    Args:
        path: repo-relative file path

    Returns:
        str: the inferred kind constant

    Raises:
        TargetError: when the filename implies no known kind
    """
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if name == "VERSION":
        return KIND_VERSION_FILE
    if name == "pyproject.toml":
        return KIND_PYPROJECT
    if name == "__init__.py":
        return KIND_INIT_PY
    if name == "package.json":
        return KIND_PACKAGE_JSON
    if name == "package-lock.json":
        return KIND_PACKAGE_LOCK
    raise TargetError(f"cannot infer a target kind from {path!r} -- declare it as {{'path', 'kind'}}")


def _auto_detect(root: Path) -> list[Target]:
    """
    Detect the version targets present in this repo by file presence.

    VERSION is always included (required); everything else only when it exists.

    Args:
        root: repo root directory

    Returns:
        list[Target]: the detected targets, VERSION first
    """
    targets = [Target("VERSION", KIND_VERSION_FILE)]
    for rel in ("pyproject.toml", "vercel_api/pyproject.toml"):
        if (root / rel).is_file():
            targets.append(Target(rel, KIND_PYPROJECT))
    for init_file in sorted(root.glob("src/*/__init__.py")):
        if _INIT_RE.search(init_file.read_text(encoding = "utf-8")):
            targets.append(Target(init_file.relative_to(root).as_posix(), KIND_INIT_PY))
    for rel, kind in (("package.json", KIND_PACKAGE_JSON), ("package-lock.json", KIND_PACKAGE_LOCK)):
        if (root / rel).is_file():
            targets.append(Target(rel, kind))
    return targets


def _from_manifest(root: Path, manifest_file: Path) -> list[Target]:
    """
    Load the targets declared in scripts/version_targets.json.

    The manifest is authoritative: every declared file must exist and use a known
    kind, or the caller's check/bump hard-fails (the rename-safety guard).

    Args:
        root: repo root directory
        manifest_file: path to the manifest JSON

    Returns:
        list[Target]: the declared targets, in manifest order

    Raises:
        TargetError: on invalid JSON, a bad entry shape, an unknown kind, or a declared-but-missing file
    """
    try:
        data = json.loads(manifest_file.read_text(encoding = "utf-8"))
    except ValueError as exc:
        raise TargetError(f"{manifest_file}: invalid JSON -- {exc}") from exc
    entries = data.get("targets")
    if not isinstance(entries, list) or not entries:
        raise TargetError(f"{manifest_file}: 'targets' must be a non-empty list")

    targets: list[Target] = []
    for entry in entries:
        if isinstance(entry, str):
            target = Target(entry, _infer_kind(entry))
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str) and isinstance(entry.get("kind"), str):
            target = Target(entry["path"], entry["kind"])
        else:
            raise TargetError(f"{manifest_file}: bad entry {entry!r} -- use a path string or {{'path', 'kind'}}")
        if target.kind not in _KNOWN_KINDS:
            raise TargetError(
                f"{manifest_file}: unknown kind {target.kind!r} for {target.path!r} (known: {sorted(_KNOWN_KINDS)})",
            )
        if not (root / target.path).is_file():
            raise TargetError(
                f"{manifest_file}: declared target {target.path!r} does not exist -- renamed or deleted? "
                "Update the manifest."
            )
        targets.append(target)
    return targets


def resolve_targets(root: Path) -> list[Target]:
    """
    Resolve the repo's version targets.

    The manifest wins when present (authoritative, missing-file = TargetError);
    otherwise targets are auto-detected by file presence.

    Args:
        root: repo root directory

    Returns:
        list[Target]: the version targets for this repo

    Raises:
        TargetError: propagated from manifest validation
    """
    manifest_file = root / MANIFEST_PATH
    if manifest_file.is_file():
        return _from_manifest(root, manifest_file)
    return _auto_detect(root)


def read_version(root: Path, target: Target) -> str:
    """
    Read the version string a target currently carries.

    Args:
        root: repo root directory
        target: the target to read

    Returns:
        str: the version value found in the target file

    Raises:
        TargetError: when the file is missing, unparseable, or has no version field
    """
    path = root / target.path
    if not path.is_file():
        raise TargetError(f"{target.path}: file not found")
    text = path.read_text(encoding = "utf-8-sig")

    if target.kind == KIND_VERSION_FILE:
        value = text.strip()
        if not value:
            raise TargetError(f"{target.path}: empty")
        return value

    if target.kind in (KIND_PYPROJECT, KIND_INIT_PY):
        pattern = _PYPROJECT_RE if target.kind == KIND_PYPROJECT else _INIT_RE
        match   = pattern.search(text)
        if not match:
            raise TargetError(f"{target.path}: no version field found")
        return match.group(2)

    # KIND_PACKAGE_JSON / KIND_PACKAGE_LOCK
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise TargetError(f"{target.path}: invalid JSON -- {exc}") from exc
    value = data.get("version")
    if not isinstance(value, str):
        raise TargetError(f"{target.path}: no top-level 'version' field")
    return value


def write_version(root: Path, target: Target, new_version: str) -> bool:
    """
    Write ``new_version`` into the target.

    JSON targets are parsed (never regex'd): package.json gets its top-level
    "version"; package-lock.json additionally gets ``packages[""].version`` (the
    root-package entry) — nested dependency versions are never touched.

    Args:
        root: repo root directory
        target: the target to write
        new_version: the semver string to write

    Returns:
        bool: True when the file changed, False when it already carried the value

    Raises:
        TargetError: when the file is missing, unparseable, or has no version field
    """
    path = root / target.path
    if not path.is_file():
        raise TargetError(f"{target.path}: file not found")

    if target.kind == KIND_VERSION_FILE:
        old = path.read_text(encoding = "utf-8-sig")
        new = new_version + "\n"
        if old == new:
            return False
        path.write_text(new, encoding = "utf-8")
        return True

    if target.kind in (KIND_PYPROJECT, KIND_INIT_PY):
        pattern = _PYPROJECT_RE if target.kind == KIND_PYPROJECT else _INIT_RE
        old     = path.read_text(encoding = "utf-8")
        if not pattern.search(old):
            raise TargetError(f"{target.path}: no version field found")
        new = pattern.sub(f'\\g<1>"{new_version}"', old, count = 1)
        if new == old:
            return False
        path.write_text(new, encoding = "utf-8")
        return True

    if target.kind == KIND_PACKAGE_JSON:
        # package.json is often HAND-formatted (compact arrays, custom spacing), so a
        # parse+re-dump would reformat the whole file just to move one version. Surgical
        # regex on the FIRST "version" key instead — top-level "version" precedes
        # scripts/dependencies in every ecosystem manifest. Validity is still checked
        # by parsing first.
        old = path.read_text(encoding = "utf-8-sig")
        try:
            json.loads(old)
        except ValueError as exc:
            raise TargetError(f"{target.path}: invalid JSON -- {exc}") from exc
        if not _PACKAGE_JSON_RE.search(old):
            raise TargetError(f"{target.path}: no top-level 'version' field")
        new = _PACKAGE_JSON_RE.sub(f'\\g<1>"{new_version}"', old, count = 1)
        if new == old:
            return False
        path.write_text(new, encoding = "utf-8")
        return True

    # KIND_PACKAGE_LOCK — machine-written by npm (JSON.stringify(data, null, 2)), so a
    # parse + re-dump in the same style is byte-stable apart from the two version keys:
    # the top level and packages[""] (the root-package entry). Nested dependency
    # versions are never touched.
    old = path.read_text(encoding = "utf-8-sig")
    try:
        data = json.loads(old)
    except ValueError as exc:
        raise TargetError(f"{target.path}: invalid JSON -- {exc}") from exc
    data["version"] = new_version
    root_pkg = data.get("packages", {}).get("")
    if isinstance(root_pkg, dict):
        root_pkg["version"] = new_version
    new = json.dumps(data, indent = 2, ensure_ascii = False) + "\n"
    if new == old:
        return False
    path.write_text(new, encoding = "utf-8")
    return True
