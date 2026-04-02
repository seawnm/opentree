"""E2E pre-check tests (A0 + A1).

Verify that Bot_Walter is alive and its environment is properly configured
before running heavier interaction tests.
"""

from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

pytestmark = [pytest.mark.e2e]


class TestBotProcessAlive:
    """A0: Verify bot process is running."""

    def test_bot_process_alive(
        self,
        check_bot_alive: Callable[[], bool],
    ) -> None:
        """pgrep should find at least one opentree-related process."""
        assert check_bot_alive(), (
            "No opentree process found. Is Bot_Walter running?"
        )


class TestHeartbeat:
    """A0: Verify heartbeat file is reasonably fresh."""

    def test_heartbeat_file_exists(self, bot_home: Path) -> None:
        """The heartbeat file must exist."""
        hb = bot_home / "data" / "bot.heartbeat"
        assert hb.exists(), f"Heartbeat file not found: {hb}"

    def test_heartbeat_fresh(
        self,
        check_heartbeat: Callable[[], tuple[bool, float]],
    ) -> None:
        """Heartbeat should have been updated within 600 seconds.

        We use a generous threshold because the bot may be busy with a
        long-running Claude CLI task.
        """
        is_fresh, age = check_heartbeat()
        # Use 600s threshold (10 minutes) — generous for busy bot
        assert age < 600, (
            f"Heartbeat is {age:.0f}s old (threshold 600s). "
            "Bot may be hung or not running."
        )


class TestLogActivity:
    """A1: Verify log file has recent entries."""

    def test_log_file_exists(self, bot_log_path: Path) -> None:
        """Today's log file must exist."""
        assert bot_log_path.exists(), (
            f"Today's log file not found: {bot_log_path}"
        )

    def test_log_recent_activity(self, bot_log_path: Path) -> None:
        """Log file should have entries within the last 10 minutes.

        We check the file's mtime as a quick proxy — if the file was
        modified recently, the bot is writing logs.
        """
        if not bot_log_path.exists():
            pytest.skip("Log file does not exist yet")

        mtime = bot_log_path.stat().st_mtime
        age = time.time() - mtime
        # 10 minutes = 600 seconds
        assert age < 600, (
            f"Log file last modified {age:.0f}s ago (threshold 600s). "
            "Bot may not be logging."
        )

    def test_log_has_content(self, bot_log_path: Path) -> None:
        """Log file should not be empty."""
        if not bot_log_path.exists():
            pytest.skip("Log file does not exist yet")

        size = bot_log_path.stat().st_size
        assert size > 0, "Log file is empty"


class TestConfigEnvironment:
    """A1: Verify bot configuration is properly set up."""

    def test_config_dir_exists(self, bot_home: Path) -> None:
        """The config directory should exist with registry files."""
        config_dir = bot_home / "config"
        assert config_dir.is_dir(), f"Config directory not found: {config_dir}"

    def test_registry_json_exists(self, bot_home: Path) -> None:
        """registry.json should exist in config/."""
        registry = bot_home / "config" / "registry.json"
        assert registry.exists(), f"Registry not found: {registry}"

    def test_permissions_json_exists(self, bot_home: Path) -> None:
        """permissions.json should exist in config/."""
        perms = bot_home / "config" / "permissions.json"
        assert perms.exists(), f"Permissions not found: {perms}"

    def test_run_sh_exists(self, bot_home: Path) -> None:
        """bin/run.sh wrapper should exist."""
        run_sh = bot_home / "bin" / "run.sh"
        assert run_sh.exists(), f"run.sh not found: {run_sh}"

    def test_workspace_claude_md_exists(self, bot_home: Path) -> None:
        """workspace/CLAUDE.md should be generated."""
        claude_md = bot_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists(), f"workspace/CLAUDE.md not found: {claude_md}"
