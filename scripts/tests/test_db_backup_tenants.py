"""
Unit tests for the three tenant entry-point scripts:
  auth/db_backup.py, fitness-app/db_backup.py, tiffanys-closet/db_backup.py

Each script is a 3-line wrapper that calls run_backup(app_name="<app>").
These tests verify the correct app_name is passed by running each script via
runpy.run_path() (which triggers the if __name__ == "__main__" block) with
common.db_backup_base mocked so nothing actually runs.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_script_as_main(script_path: Path) -> MagicMock:
    """
    Execute script_path as __main__ with common.db_backup_base mocked.
    Returns the mock for run_backup so callers can assert on it.
    """
    mock_run_backup = MagicMock()
    mock_module = MagicMock()
    mock_module.run_backup = mock_run_backup

    with patch.dict(
        "sys.modules",
        {
            "common": MagicMock(),
            "common.db_backup_base": mock_module,
        },
    ):
        runpy.run_path(str(script_path), run_name="__main__")

    return mock_run_backup


class TestAuthDbBackup:
    def test_calls_run_backup_with_auth_app_name(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "auth" / "db_backup.py")
        mock_run.assert_called_once_with(app_name="auth")

    def test_called_exactly_once(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "auth" / "db_backup.py")
        assert mock_run.call_count == 1

    def test_not_called_when_imported_not_as_main(self):
        mock_run_backup = MagicMock()
        mock_module = MagicMock()
        mock_module.run_backup = mock_run_backup

        with patch.dict(
            "sys.modules",
            {"common": MagicMock(), "common.db_backup_base": mock_module},
        ):
            # run_name="not_main" means __name__ != "__main__"
            runpy.run_path(
                str(SCRIPTS_DIR / "auth" / "db_backup.py"),
                run_name="not_main",
            )

        mock_run_backup.assert_not_called()


class TestFitnessAppDbBackup:
    def test_calls_run_backup_with_fitness_app_app_name(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "fitness-app" / "db_backup.py")
        mock_run.assert_called_once_with(app_name="fitness-app")

    def test_called_exactly_once(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "fitness-app" / "db_backup.py")
        assert mock_run.call_count == 1

    def test_not_called_when_imported_not_as_main(self):
        mock_run_backup = MagicMock()
        mock_module = MagicMock()
        mock_module.run_backup = mock_run_backup

        with patch.dict(
            "sys.modules",
            {"common": MagicMock(), "common.db_backup_base": mock_module},
        ):
            runpy.run_path(
                str(SCRIPTS_DIR / "fitness-app" / "db_backup.py"),
                run_name="not_main",
            )

        mock_run_backup.assert_not_called()


class TestTiffanysClosetDbBackup:
    def test_calls_run_backup_with_tiffanys_closet_app_name(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "tiffanys-closet" / "db_backup.py")
        mock_run.assert_called_once_with(app_name="tiffanys-closet")

    def test_called_exactly_once(self):
        mock_run = _run_script_as_main(SCRIPTS_DIR / "tiffanys-closet" / "db_backup.py")
        assert mock_run.call_count == 1

    def test_not_called_when_imported_not_as_main(self):
        mock_run_backup = MagicMock()
        mock_module = MagicMock()
        mock_module.run_backup = mock_run_backup

        with patch.dict(
            "sys.modules",
            {"common": MagicMock(), "common.db_backup_base": mock_module},
        ):
            runpy.run_path(
                str(SCRIPTS_DIR / "tiffanys-closet" / "db_backup.py"),
                run_name="not_main",
            )

        mock_run_backup.assert_not_called()
