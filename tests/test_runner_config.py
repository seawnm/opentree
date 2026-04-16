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
        assert result.codex_command == "codex"
        assert result.claude_command == "codex"  # deprecated alias
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
                    "codex_command": "codex-dev",
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
        assert result.codex_command == "codex-dev"
        assert result.claude_command == "codex-dev"  # deprecated alias
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
        assert result.codex_command == "codex"
        assert result.heartbeat_timeout == 900
        assert result.max_concurrent_tasks == 2
        assert result.session_expiry_days == 180
        assert result.drain_timeout == 30

    def test_only_codex_command_overridden(self, tmp_path: Path) -> None:
        """codex_command can be overridden via runner.json."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"codex_command": "/usr/local/bin/codex"}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.codex_command == "/usr/local/bin/codex"
        assert result.claude_command == "/usr/local/bin/codex"  # deprecated alias
        assert result.task_timeout == 1800

    def test_legacy_claude_command_key_still_works(self, tmp_path: Path) -> None:
        """Legacy 'claude_command' JSON key is accepted as fallback for codex_command."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"claude_command": "/usr/local/bin/claude"}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.codex_command == "/usr/local/bin/claude"
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
        assert result.codex_command == "codex"

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
        assert result.codex_command == "codex"


class TestRunnerConfigDirectInstantiation:
    """Verify RunnerConfig can be instantiated directly with custom values."""

    def test_custom_values(self) -> None:
        config = RunnerConfig(task_timeout=500, max_concurrent_tasks=8)

        assert config.task_timeout == 500
        assert config.max_concurrent_tasks == 8
        # Unchanged defaults
        assert config.codex_command == "codex"
        assert config.claude_command == "codex"  # deprecated alias

    def test_dataclass_fields_present(self) -> None:
        import dataclasses

        fields = {f.name for f in dataclasses.fields(RunnerConfig)}

        assert "progress_interval" in fields
        assert "codex_command" in fields
        assert "task_timeout" in fields
        assert "heartbeat_timeout" in fields
        assert "max_concurrent_tasks" in fields
        assert "session_expiry_days" in fields
        assert "drain_timeout" in fields
        assert "admin_users" in fields
        assert "memory_extraction_enabled" in fields


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


class TestMemoryExtractionEnabled:
    """Tests for memory_extraction_enabled field on RunnerConfig."""

    def test_default_true(self, tmp_path: Path) -> None:
        """Default memory_extraction_enabled is True when no config file exists."""
        result = load_runner_config(tmp_path)
        assert result.memory_extraction_enabled is True

    def test_from_json_false(self, tmp_path: Path) -> None:
        """memory_extraction_enabled=false in JSON results in False."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"memory_extraction_enabled": False}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.memory_extraction_enabled is False

    def test_from_json_true(self, tmp_path: Path) -> None:
        """memory_extraction_enabled=true in JSON results in True."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"memory_extraction_enabled": True}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.memory_extraction_enabled is True

    def test_missing_from_json_defaults_true(self, tmp_path: Path) -> None:
        """When memory_extraction_enabled is not in JSON, defaults to True."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "runner.json").write_text(
            json.dumps({"task_timeout": 600}),
            encoding="utf-8",
        )

        result = load_runner_config(tmp_path)

        assert result.memory_extraction_enabled is True

    def test_direct_instantiation_default(self) -> None:
        """Direct instantiation defaults to True."""
        config = RunnerConfig()
        assert config.memory_extraction_enabled is True

    def test_direct_instantiation_false(self) -> None:
        """Direct instantiation with memory_extraction_enabled=False."""
        config = RunnerConfig(memory_extraction_enabled=False)
        assert config.memory_extraction_enabled is False
