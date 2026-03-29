"""Tests for UserConfig and load_user_config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentree.core.config import UserConfig, load_user_config


class TestLoadConfigFromFile:
    """test_load_config_from_file — config/user.json exists with all fields."""

    def test_loads_all_fields(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text(
            json.dumps(
                {
                    "bot_name": "Groot",
                    "team_name": "DOGI Team",
                    "admin_channel": "C012345",
                }
            ),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.bot_name == "Groot"
        assert result.team_name == "DOGI Team"
        assert result.admin_channel == "C012345"
        assert result.opentree_home == str(tmp_path)
        assert result.admin_description == ""


class TestLoadConfigMissingFile:
    """test_load_config_missing_file — returns defaults."""

    def test_returns_defaults(self, tmp_path: Path) -> None:
        result = load_user_config(tmp_path)

        assert result.bot_name == "OpenTree"
        assert result.team_name == ""
        assert result.admin_channel == ""
        assert result.opentree_home == str(tmp_path)


class TestLoadConfigPartialFields:
    """test_load_config_partial_fields — missing fields use defaults."""

    def test_partial_fields_use_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text(
            json.dumps({"bot_name": "MyBot"}),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.bot_name == "MyBot"
        assert result.team_name == ""
        assert result.admin_channel == ""


class TestUserConfigFrozen:
    """test_user_config_frozen — cannot modify attributes."""

    def test_cannot_set_attribute(self) -> None:
        config = UserConfig()
        with pytest.raises(AttributeError):
            config.bot_name = "Modified"  # type: ignore[misc]


class TestLoadConfigEmptyJson:
    """test_load_config_empty_json — {} returns defaults with opentree_home."""

    def test_empty_json_returns_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text("{}", encoding="utf-8")

        result = load_user_config(tmp_path)

        assert result.bot_name == "OpenTree"
        assert result.team_name == ""
        assert result.admin_channel == ""
        assert result.opentree_home == str(tmp_path)


class TestLoadConfigUnicodeBotName:
    """test_load_config_unicode_bot_name — Chinese bot_name works."""

    def test_chinese_bot_name(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text(
            json.dumps({"bot_name": "大樹"}, ensure_ascii=False),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.bot_name == "大樹"


class TestUserConfigDefaultValues:
    """test_user_config_default_values — verify all defaults."""

    def test_all_defaults(self) -> None:
        config = UserConfig()

        assert config.bot_name == "OpenTree"
        assert config.team_name == ""
        assert config.admin_channel == ""
        assert config.opentree_home == ""


class TestOpentreeHomeAlwaysSet:
    """test_opentree_home_always_set — even from file, opentree_home comes from parameter."""

    def test_opentree_home_from_parameter_not_file(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        # Even if the file had an opentree_home field, the parameter should win
        config_file.write_text(
            json.dumps({"opentree_home": "/some/other/path"}),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.opentree_home == str(tmp_path)


class TestAdminDescriptionDefault:
    """test_admin_description_default_empty -- default is empty string."""

    def test_default_empty(self) -> None:
        config = UserConfig()
        assert config.admin_description == ""


class TestAdminDescriptionFromJson:
    """test_admin_description_from_json -- loaded from user.json."""

    def test_from_json(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text(
            json.dumps({"admin_description": "The team admin"}),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.admin_description == "The team admin"


class TestAdminDescriptionMissingUsesDefault:
    """test_admin_description_missing_uses_default -- missing field defaults to empty."""

    def test_missing_uses_default(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "user.json"
        config_file.write_text(
            json.dumps({"bot_name": "TestBot"}),
            encoding="utf-8",
        )

        result = load_user_config(tmp_path)

        assert result.admin_description == ""
