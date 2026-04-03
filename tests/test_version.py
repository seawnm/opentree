"""Tests for opentree.core.version — semver comparison utilities."""

from __future__ import annotations

import pytest

from opentree.core.version import compare_versions, parse_version


class TestParseVersion:
    """parse_version converts dotted string to int tuple."""

    def test_standard_semver(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_major_only(self):
        assert parse_version("2") == (2,)

    def test_major_minor(self):
        assert parse_version("1.0") == (1, 0)

    def test_zero_version(self):
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_numbers(self):
        assert parse_version("10.20.300") == (10, 20, 300)

    def test_strips_whitespace(self):
        assert parse_version("  1.2.3  ") == (1, 2, 3)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty version"):
            parse_version("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty version"):
            parse_version("   ")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="non-numeric|Invalid"):
            parse_version("1.2.beta")

    def test_pre_release_tag_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_version("1.0.0-rc1")


class TestCompareVersions:
    """compare_versions returns -1 / 0 / 1."""

    def test_equal(self):
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_upgrade_available_patch(self):
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_upgrade_available_minor(self):
        assert compare_versions("1.0.0", "1.1.0") == -1

    def test_upgrade_available_major(self):
        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_downgrade_patch(self):
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_downgrade_minor(self):
        assert compare_versions("1.1.0", "1.0.0") == 1

    def test_downgrade_major(self):
        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_complex_upgrade(self):
        assert compare_versions("1.2.3", "1.2.4") == -1

    def test_complex_equal(self):
        assert compare_versions("3.14.159", "3.14.159") == 0

    def test_different_lengths_upgrade(self):
        # (1, 0) < (1, 0, 1) in Python tuple comparison
        assert compare_versions("1.0", "1.0.1") == -1

    def test_different_lengths_equal_prefix(self):
        # (1, 0, 0) > (1, 0) in Python tuple comparison
        assert compare_versions("1.0.0", "1.0") == 1
