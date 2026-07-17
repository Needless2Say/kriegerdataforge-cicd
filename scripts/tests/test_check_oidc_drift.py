"""
Unit tests for scripts/check_oidc_drift.py (PL-084 interim drift guard).

All network I/O is mocked; the normalize/diff/compare logic is tested directly.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

import check_oidc_drift as cod

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def manifest():
    return {
        "left": {"repo": "Needless2Say/fitness-app-frontend", "branch": "main"},
        "right": {"repo": "Needless2Say/tiffanys-space", "branch": "main"},
        "pairs": [
            {"path": "src/features/auth/utils/oidc.ts"},
            {"path": "src/app/api/auth/oidc/callback/route.ts"},
        ],
    }


def _resp(status=200, content: str | None = None):
    r = MagicMock()
    r.status_code = status
    if content is not None:
        r.json.return_value = {
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii")
        }
    return r


# ── normalize ───────────────────────────────────────────────────────────────────


class TestNormalize:
    def test_crlf_equals_lf(self):
        assert cod.normalize("a\r\nb\r\n") == cod.normalize("a\nb\n")

    def test_trailing_whitespace_ignored(self):
        assert cod.normalize("const x = 1;   \n") == cod.normalize("const x = 1;\n")

    def test_real_content_change_detected(self):
        assert cod.normalize("const x = 1;\n") != cod.normalize("const x = 2;\n")

    def test_leading_indentation_is_significant(self):
        assert cod.normalize("  indented") != cod.normalize("indented")


# ── changed_line_count ──────────────────────────────────────────────────────────


class TestChangedLineCount:
    def test_identical_is_zero(self):
        assert cod.changed_line_count("a\nb", "a\nb") == 0

    def test_one_changed_line_counts_two(self):
        # one line replaced = one '-' + one '+'
        assert cod.changed_line_count("a\nb\nc", "a\nX\nc") == 2

    def test_pure_addition(self):
        assert cod.changed_line_count("a", "a\nb") == 1


# ── compare_pairs ───────────────────────────────────────────────────────────────


class TestComparePairs:
    def test_identical_pair(self, manifest):
        with patch.object(cod, "fetch_file", return_value="same content\n"):
            results = cod.compare_pairs("tok", manifest)
        assert all(r["status"] == "identical" for r in results)
        assert len(results) == 2

    def test_drifted_pair_reports_changed_lines(self, manifest):
        manifest["pairs"] = [{"path": "src/features/auth/utils/oidc.ts"}]

        def fake_fetch(token, repo, branch, path):
            return "line1\nline2\n" if "fitness" in repo else "line1\nCHANGED\n"

        with patch.object(cod, "fetch_file", side_effect=fake_fetch):
            results = cod.compare_pairs("tok", manifest)
        assert results[0]["status"] == "drifted"
        assert results[0]["changed_lines"] == 2

    def test_crlf_only_difference_is_identical(self, manifest):
        manifest["pairs"] = [{"path": "src/features/auth/utils/oidc.ts"}]

        def fake_fetch(token, repo, branch, path):
            return "a\r\nb\r\n" if "fitness" in repo else "a\nb\n"

        with patch.object(cod, "fetch_file", side_effect=fake_fetch):
            results = cod.compare_pairs("tok", manifest)
        assert results[0]["status"] == "identical"

    def test_missing_file_reported_with_repo(self, manifest):
        manifest["pairs"] = [{"path": "src/features/auth/utils/oidc.ts"}]

        def fake_fetch(token, repo, branch, path):
            return None if "tiffanys" in repo else "content"

        with patch.object(cod, "fetch_file", side_effect=fake_fetch):
            results = cod.compare_pairs("tok", manifest)
        assert results[0]["status"] == "missing"
        assert results[0]["missing_in"] == "Needless2Say/tiffanys-space"


# ── fetch_file ──────────────────────────────────────────────────────────────────


class TestFetchFile:
    def test_decodes_content(self):
        with patch.object(cod, "_SESSION") as session:
            session.get.return_value = _resp(200, "hello ✓")
            out = cod.fetch_file("tok", "o/r", "main", "path.ts")
        assert out == "hello ✓"

    def test_404_returns_none(self):
        with patch.object(cod, "_SESSION") as session:
            session.get.return_value = _resp(404)
            assert cod.fetch_file("tok", "o/r", "main", "path.ts") is None

    def test_sends_auth_and_ref(self):
        with patch.object(cod, "_SESSION") as session:
            session.get.return_value = _resp(200, "x")
            cod.fetch_file("tok", "owner/repo", "dev", "a/b.ts")
        _, kwargs = session.get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["params"] == {"ref": "dev"}


# ── main / exit codes ───────────────────────────────────────────────────────────


class TestMain:
    def test_no_token_is_config_error(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert cod.main() == 2

    def test_all_identical_exits_zero(self, manifest, monkeypatch, capsys):
        monkeypatch.setenv("GH_TOKEN", "tok")
        with patch.object(cod, "load_manifest", return_value=manifest), \
             patch.object(cod, "fetch_file", return_value="same\n"):
            rc = cod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "DRIFT_COUNT: 0" in out

    def test_drift_exits_one_and_lists_paths(self, manifest, monkeypatch, capsys):
        monkeypatch.setenv("GH_TOKEN", "tok")

        def fake_fetch(token, repo, branch, path):
            return "a\n" if "fitness" in repo else "b\n"

        with patch.object(cod, "load_manifest", return_value=manifest), \
             patch.object(cod, "fetch_file", side_effect=fake_fetch):
            rc = cod.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert "DRIFT_COUNT: 2" in out
        assert "src/features/auth/utils/oidc.ts" in out
        # Never any file contents in the output — only paths + counts.
        assert "a\n\n" not in out

    def test_api_error_exits_two(self, manifest, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "tok")
        with patch.object(cod, "load_manifest", return_value=manifest), \
             patch.object(cod, "fetch_file", side_effect=RuntimeError("boom")):
            assert cod.main() == 2


# ── Manifest file sanity (the real one on disk) ─────────────────────────────────


class TestRealManifest:
    def test_manifest_loads_and_has_expected_shape(self):
        manifest = cod.load_manifest()
        assert manifest["left"]["repo"].startswith("Needless2Say/")
        assert manifest["right"]["repo"].startswith("Needless2Say/")
        assert len(manifest["pairs"]) >= 4
        for pair in manifest["pairs"]:
            assert pair["path"].endswith(".ts")
