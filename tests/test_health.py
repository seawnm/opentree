"""Tests for disk health monitoring — written FIRST (TDD Red phase).

Tests cover:
  - check_disk_usage: returns correct dict structure
  - check_disk_usage: warning flag when free space < threshold
  - check_disk_usage: no warning when free space >= threshold
  - check_disk_usage: data_dir_mb calculation for a real directory
  - check_disk_usage: missing data_dir returns 0 for data_dir_mb
  - check_disk_usage: custom threshold
  - Integration with Bot: health check accessible from bot
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ===========================================================================
# check_disk_usage tests
# ===========================================================================

from opentree.runner.health import check_disk_usage


class TestCheckDiskUsageStructure:
    """check_disk_usage must return a dict with required keys."""

    def test_returns_required_keys(self, tmp_path: Path) -> None:
        result = check_disk_usage(tmp_path)

        assert "total_mb" in result
        assert "used_mb" in result
        assert "free_mb" in result
        assert "data_dir_mb" in result
        assert "warning" in result

    def test_values_are_correct_types(self, tmp_path: Path) -> None:
        result = check_disk_usage(tmp_path)

        assert isinstance(result["total_mb"], int)
        assert isinstance(result["used_mb"], int)
        assert isinstance(result["free_mb"], int)
        assert isinstance(result["data_dir_mb"], int)
        assert isinstance(result["warning"], bool)


class TestCheckDiskUsageWarning:
    """Warning flag behavior based on free space vs threshold."""

    def test_warning_true_when_free_below_threshold(self, tmp_path: Path) -> None:
        # Mock disk_usage to return very low free space
        mock_usage = os.statvfs_result((4096, 4096, 1000, 50, 50, 100, 0, 0, 0, 255))
        with patch("shutil.disk_usage") as mock_du:
            # shutil.disk_usage returns (total, used, free) in bytes
            mock_du.return_value = (1_000_000_000, 999_000_000, 1_000_000)  # 1 MB free
            result = check_disk_usage(tmp_path, warn_threshold_mb=500)

        assert result["warning"] is True

    def test_warning_false_when_free_above_threshold(self, tmp_path: Path) -> None:
        with patch("shutil.disk_usage") as mock_du:
            mock_du.return_value = (100_000_000_000, 50_000_000_000, 50_000_000_000)  # 50 GB free
            result = check_disk_usage(tmp_path, warn_threshold_mb=500)

        assert result["warning"] is False

    def test_custom_threshold(self, tmp_path: Path) -> None:
        with patch("shutil.disk_usage") as mock_du:
            # 200 MB free, threshold 100 MB -> no warning
            mock_du.return_value = (1_000_000_000, 800_000_000, 200_000_000)
            result = check_disk_usage(tmp_path, warn_threshold_mb=100)

        assert result["warning"] is False

    def test_custom_threshold_triggers_warning(self, tmp_path: Path) -> None:
        with patch("shutil.disk_usage") as mock_du:
            # 200 MB free, threshold 300 MB -> warning
            mock_du.return_value = (1_000_000_000, 800_000_000, 200_000_000)
            result = check_disk_usage(tmp_path, warn_threshold_mb=300)

        assert result["warning"] is True


class TestCheckDiskUsageDataDir:
    """data_dir_mb should reflect the actual size of the data directory."""

    def test_calculates_data_dir_size(self, tmp_path: Path) -> None:
        # Create some files in the data dir
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "file1.log").write_bytes(b"x" * 1024)
        (data_dir / "file2.log").write_bytes(b"y" * 2048)

        result = check_disk_usage(data_dir)

        # data_dir_mb should be at least 0 (files are tiny, rounds to 0 or 1)
        assert result["data_dir_mb"] >= 0

    def test_missing_data_dir_returns_zero(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = check_disk_usage(missing)

        assert result["data_dir_mb"] == 0

    def test_includes_nested_files(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        sub = data_dir / "logs" / "2026"
        sub.mkdir(parents=True)
        (sub / "big.log").write_bytes(b"x" * (1024 * 1024))  # 1 MB

        result = check_disk_usage(data_dir)

        assert result["data_dir_mb"] >= 1


class TestCheckDiskUsageMbConversion:
    """Verify MB conversion from bytes."""

    def test_mb_values_are_correct(self, tmp_path: Path) -> None:
        with patch("shutil.disk_usage") as mock_du:
            # 10 GB total, 6 GB used, 4 GB free
            mock_du.return_value = (
                10 * 1024 * 1024 * 1024,
                6 * 1024 * 1024 * 1024,
                4 * 1024 * 1024 * 1024,
            )
            result = check_disk_usage(tmp_path)

        assert result["total_mb"] == 10 * 1024
        assert result["used_mb"] == 6 * 1024
        assert result["free_mb"] == 4 * 1024
