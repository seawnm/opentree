"""Tests for RunnerConfig and load_runner_config.

TDD order:
1. test_default_config
2. test_load_from_file
3. test_partial_config
4. test_frozen
5. test_invalid_timeout
6. test_invalid_max_concurrent
7. test_invalid_json
8. test_empty_file
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentree.runner.config import RunnerConfig, load_runner_config


class TestDefaultConfig:
    """test_default_config — all defaults when no config file exists."""

    def test_all_defaults(self, tmp_path: Path) -> None:
        result = load_runner_config(tmp_path)

        assert result.progress_interval == 10
        assert result.claude_command == "claude"
        assert result.task_timeout == 1800
        assert result.heartbeat_timeout == 900
        assert result.max_concurrent_tasks == 2
        assert result.session_expiry_days == 180
        assert result.drain_timeout == 30

    def test_missing_config_dir_returns_defaults(self, tmp_path: Path) -> None:
        # No config/ dir at all
        home = tmp_path / "nonexistent_home"
        result = load_runner_config(home)

        assert result.task_timeout == 1800
        assert result.max_concurrent_tasks == 2


class TestLoadFromFile:
    """test_load_from_file — load all fields from a valid runner.json."""

    def test_loads_all_fields(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps(
                {
                    "progress_interval": 5,
                    "claude_command": "claude-dev",
                    "task_timeout": 3600,
                    "heartbeat_timeout": 600,
                    "max_concurrent_tasks": 4,
                    "session_expiry_days": 90,
                    "drain_timeout": 60,
                }
            ),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.progress_interval == 5
        assert result.claude_command == "claude-dev"
        assert result.task_timeout == 3600
        assert result.heartbeat_timeout == 600
        assert result.max_concurrent_tasks == 4
        assert result.session_expiry_days == 90
        assert result.drain_timeout == 60


class TestPartialConfig:
    """test_partial_config — only some fields in JSON, rest use defaults."""

    def test_partial_fields_use_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"task_timeout": 600}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.task_timeout == 600
        # All other fields stay at defaults
        assert result.progress_interval == 10
        assert result.claude_command == "claude"
        assert result.heartbeat_timeout == 900
        assert result.max_concurrent_tasks == 2
        assert result.session_expiry_days == 180
        assert result.drain_timeout == 30

    def test_only_claude_command_overridden(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"claude_command": "/usr/local/bin/claude"}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.claude_command == "/usr/local/bin/claude"
        assert result.task_timeout == 1800


class TestFrozen:
    """test_frozen — RunnerConfig cannot be mutated after creation."""

    def test_cannot_set_attribute(self) -> None:
        config = RunnerConfig()
        with pytest.raises((AttributeError, TypeError)):
            config.task_timeout = 9999  # type: ignore[misc]

    def test_cannot_delete_attribute(self) -> None:
        config = RunnerConfig()
        with pytest.raises((AttributeError, TypeError)):
            del config.task_timeout  # type: ignore[misc]


class TestInvalidTimeout:
    """test_invalid_timeout — negative or zero task_timeout raises ValueError."""

    def test_negative_task_timeout_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"task_timeout": -1}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="task_timeout"):
            load_runner_config(tmp_path)

    def test_zero_task_timeout_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"task_timeout": 0}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="task_timeout"):
            load_runner_config(tmp_path)

    def test_negative_heartbeat_timeout_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"heartbeat_timeout": -100}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="heartbeat_timeout"):
            load_runner_config(tmp_path)

    def test_negative_drain_timeout_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"drain_timeout": -5}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="drain_timeout"):
            load_runner_config(tmp_path)

    def test_negative_progress_interval_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"progress_interval": -1}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="progress_interval"):
            load_runner_config(tmp_path)

    def test_negative_session_expiry_days_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"session_expiry_days": 0}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="session_expiry_days"):
            load_runner_config(tmp_path)


class TestInvalidMaxConcurrent:
    """test_invalid_max_concurrent — 0 or negative raises ValueError."""

    def test_zero_max_concurrent_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"max_concurrent_tasks": 0}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            load_runner_config(tmp_path)

    def test_negative_max_concurrent_raises(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"max_concurrent_tasks": -3}),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="max_concurrent_tasks"):
            load_runner_config(tmp_path)

    def test_one_max_concurrent_is_valid(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"max_concurrent_tasks": 1}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.max_concurrent_tasks == 1


class TestInvalidJson:
    """test_invalid_json — malformed JSON returns defaults gracefully."""

    def test_malformed_json_returns_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            "{not valid json!!!",
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.task_timeout == 1800
        assert result.max_concurrent_tasks == 2
        assert result.claude_command == "claude"

    def test_malformed_json_all_fields_default(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            "this is not json at all",
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.progress_interval == 10
        assert result.heartbeat_timeout == 900
        assert result.session_expiry_days == 180
        assert result.drain_timeout == 30


class TestEmptyFile:
    """test_empty_file — empty file content returns defaults."""

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text("", encoding="utf-8")

        result = load_runner_config(tmp_path)

        assert result.task_timeout == 1800
        assert result.max_concurrent_tasks == 2

    def test_whitespace_only_file_returns_defaults(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text("   \n\t  ", encoding="utf-8")

        result = load_runner_config(tmp_path)

        assert result.progress_interval == 10
        assert result.claude_command == "claude"


class TestRunnerConfigDirectInstantiation:
    """Verify RunnerConfig can be instantiated directly with custom values."""

    def test_custom_values(self) -> None:
        config = RunnerConfig(task_timeout=500, max_concurrent_tasks=8)

        assert config.task_timeout == 500
        assert config.max_concurrent_tasks == 8
        # Unchanged defaults
        assert config.claude_command == "claude"

    def test_dataclass_fields_present(self) -> None:
        import dataclasses

        fields = {f.name for f in dataclasses.fields(RunnerConfig)}

        assert "progress_interval" in fields
        assert "claude_command" in fields
        assert "task_timeout" in fields
        assert "heartbeat_timeout" in fields
        assert "max_concurrent_tasks" in fields
        assert "session_expiry_days" in fields
        assert "drain_timeout" in fields
        assert "admin_users" in fields


class TestAdminUsers:
    """Tests for admin_users field on RunnerConfig."""

    def test_admin_users_default_empty(self) -> None:
        """Default admin_users is an empty tuple (backward compat: all users are admins)."""
        config = RunnerConfig()
        assert config.admin_users == ()

    def test_admin_users_from_json(self, tmp_path: Path) -> None:
        """admin_users loaded from runner.json as a tuple."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"admin_users": ["U001", "U002"]}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.admin_users == ("U001", "U002")

    def test_admin_users_empty_list_from_json(self, tmp_path: Path) -> None:
        """Empty admin_users list in JSON results in empty tuple."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"admin_users": []}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.admin_users == ()

    def test_admin_users_missing_from_json_defaults_empty(self, tmp_path: Path) -> None:
        """When admin_users is not in JSON, defaults to empty tuple."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"task_timeout": 600}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.admin_users == ()
