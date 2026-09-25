"""
Unit tests for scripts/common/version_targets.py — the shared target resolution
that bump_version.py and check_version.py both consume. Fixture trees cover every
current ecosystem repo shape (FastAPI backend, Python package, Next.js/npm,
VERSION-only) plus the manifest override with its rename-safety hard-fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import common.version_targets as vt
import pytest


def _paths(targets: list[vt.Target]) -> list[str]:
    return [t.path for t in targets]


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents = True, exist_ok = True)
        path.write_text(content, encoding = "utf-8")
    return tmp_path


# ── Auto-detection per repo shape ────────────────────────────────────────────
def test_autodetect_fastapi_backend_shape(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "pyproject.toml": 'version = "1.2.3"\n',
            "vercel_api/pyproject.toml": 'version = "1.2.3"\n',
        },
    )
    assert _paths(vt.resolve_targets(root)) == ["VERSION", "pyproject.toml", "vercel_api/pyproject.toml"]


def test_autodetect_python_package_shape(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "pyproject.toml": 'version = "1.2.3"\n',
            "src/kdf_sdk/__init__.py": '__version__ = "1.2.3"\n',
        },
    )
    assert _paths(vt.resolve_targets(root)) == ["VERSION", "pyproject.toml", "src/kdf_sdk/__init__.py"]


def test_autodetect_npm_shape(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "package.json": json.dumps({"name": "x", "version": "1.2.3"}),
            "package-lock.json": json.dumps({"name": "x", "version": "1.2.3", "packages": {"": {"version": "1.2.3"}}}),
        },
    )
    assert _paths(vt.resolve_targets(root)) == ["VERSION", "package.json", "package-lock.json"]


def test_autodetect_version_only_shape(tmp_path):
    root = _make_repo(tmp_path, {"VERSION": "1.2.3\n"})
    assert _paths(vt.resolve_targets(root)) == ["VERSION"]


def test_autodetect_skips_init_without_version_attr(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "src/pkg/__init__.py": "# no version here\n",
        },
    )
    assert _paths(vt.resolve_targets(root)) == ["VERSION"]


# ── Manifest override ────────────────────────────────────────────────────────
def test_manifest_is_authoritative(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "package.json": json.dumps({"version": "1.2.3"}),
            "custom/version.toml": 'version = "1.2.3"\n',
            "scripts/version_targets.json": json.dumps(
                {"targets": ["VERSION", {"path": "custom/version.toml", "kind": "pyproject"}]}
            ),
        },
    )
    # package.json exists but is NOT declared -> not a target; custom file IS.
    assert _paths(vt.resolve_targets(root)) == ["VERSION", "custom/version.toml"]


def test_manifest_missing_declared_file_hard_fails(tmp_path):
    # THE rename-safety guard: a declared target that vanished must be loud.
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "scripts/version_targets.json": json.dumps({"targets": ["VERSION", "pyproject.toml"]}),
        },
    )
    with pytest.raises(vt.TargetError, match = "pyproject.toml"):
        vt.resolve_targets(root)


def test_manifest_unknown_kind_rejected(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "x.cfg": "version: 1.2.3\n",
            "scripts/version_targets.json": json.dumps({"targets": [{"path": "x.cfg", "kind": "ini"}]}),
        },
    )
    with pytest.raises(vt.TargetError, match = "unknown kind"):
        vt.resolve_targets(root)


def test_manifest_uninferable_string_entry_rejected(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "scripts/version_targets.json": json.dumps({"targets": ["somefile.cfg"]}),
        },
    )
    with pytest.raises(vt.TargetError, match = "cannot infer"):
        vt.resolve_targets(root)


def test_manifest_empty_targets_rejected(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "scripts/version_targets.json": json.dumps({"targets": []}),
        },
    )
    with pytest.raises(vt.TargetError, match = "non-empty"):
        vt.resolve_targets(root)


# ── read_version ─────────────────────────────────────────────────────────────
def test_read_version_all_kinds(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "pyproject.toml": '[project]\nname = "x"\nversion = "1.2.3"\n',
            "src/pkg/__init__.py": '__version__ = "1.2.3"\n',
            "package.json": json.dumps({"version": "1.2.3"}),
            "package-lock.json": json.dumps({"version": "1.2.3", "packages": {"": {"version": "1.2.3"}}}),
        },
    )
    for target in vt.resolve_targets(root):
        assert vt.read_version(root, target) == "1.2.3", target.path


def test_read_version_tolerates_bom(tmp_path):
    root = tmp_path
    (root / "VERSION").write_bytes(b"\xef\xbb\xbf1.2.3\n")
    assert vt.read_version(root, vt.Target("VERSION", vt.KIND_VERSION_FILE)) == "1.2.3"


def test_read_version_missing_field_fails(tmp_path):
    root = _make_repo(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n'})
    with pytest.raises(vt.TargetError, match = "no version field"):
        vt.read_version(root, vt.Target("pyproject.toml", vt.KIND_PYPROJECT))


# ── write_version ────────────────────────────────────────────────────────────
def test_write_version_updates_every_kind(tmp_path):
    root = _make_repo(
        tmp_path,
        {
            "VERSION": "1.2.3\n",
            "pyproject.toml": '[project]\nname = "x"\nversion = "1.2.3"\n',
            "vercel_api/pyproject.toml": 'version = "1.2.3"\n',
            "src/pkg/__init__.py": '__version__ = "1.2.3"\n',
            "package.json": json.dumps({"name": "x", "version": "1.2.3"}, indent = 2) + "\n",
            "package-lock.json": json.dumps(
                {"name": "x", "version": "1.2.3", "packages": {"": {"name": "x", "version": "1.2.3"}}},
                indent = 2,
            )
            + "\n",
        },
    )
    for target in vt.resolve_targets(root):
        assert vt.write_version(root, target, "1.2.4") is True, target.path
        assert vt.read_version(root, target) == "1.2.4", target.path


def test_write_version_noop_when_already_set(tmp_path):
    root = _make_repo(tmp_path, {"VERSION": "1.2.4\n"})
    assert vt.write_version(root, vt.Target("VERSION", vt.KIND_VERSION_FILE), "1.2.4") is False


def test_write_lockfile_touches_root_entries_only(tmp_path):
    lock = {
        "name": "x",
        "version": "1.2.3",
        "packages": {
            "": {"name": "x", "version": "1.2.3"},
            "node_modules/react": {"version": "19.0.0"},
        },
    }
    root = _make_repo(tmp_path, {"package-lock.json": json.dumps(lock, indent = 2) + "\n"})
    vt.write_version(root, vt.Target("package-lock.json", vt.KIND_PACKAGE_LOCK), "1.2.4")
    data = json.loads((root / "package-lock.json").read_text(encoding = "utf-8"))
    assert data["version"] == "1.2.4"
    assert data["packages"][""]["version"] == "1.2.4"
    assert data["packages"]["node_modules/react"]["version"] == "19.0.0"   # untouched


def test_write_package_json_preserves_hand_formatting(tmp_path):
    """
    Regression (auth-ui, 2026-08-11): package.json is often hand-formatted; the write
    must be a surgical version-line change, never a whole-file re-dump.
    """
    content = (
        '{\n'
        '    "name": "x",\n'
        '    "version": "1.2.3",\n'
        '    "files": ["dist"],\n'
        '    "scripts": { "build": "tsc" }\n'
        '}\n'
    )
    root    = _make_repo(tmp_path, {"package.json": content})
    vt.write_version(root, vt.Target("package.json", vt.KIND_PACKAGE_JSON), "1.2.4")
    assert (root / "package.json").read_text(encoding = "utf-8") == content.replace("1.2.3", "1.2.4")


def test_write_pyproject_first_version_line_only(tmp_path):
    # A dependency pin further down must not be rewritten.
    content = '[project]\nversion = "1.2.3"\n\n[tool.other]\nversion = "9.9.9"\n'
    root    = _make_repo(tmp_path, {"pyproject.toml": content})
    vt.write_version(root, vt.Target("pyproject.toml", vt.KIND_PYPROJECT), "1.2.4")
    text = (root / "pyproject.toml").read_text(encoding = "utf-8")
    assert 'version = "1.2.4"' in text
    assert 'version = "9.9.9"' in text
