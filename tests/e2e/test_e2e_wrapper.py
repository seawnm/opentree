"""E2E tests for run.sh crash recovery (A6).

Verify that the wrapper script restarts Bot_Walter after a crash.

WARNING: These tests are destructive — they kill the bot process.
Only run when you are prepared for temporary bot downtime.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

import pytest

from tests.e2e.conftest import BOT_HEARTBEAT_FILE, BOT_PID_FILE

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.destructive]


def _get_bot_pids() -> list[int]:
    """Get all PIDs matching the bot process pattern."""
    result = subprocess.run(
        ["pgrep", "-f", "opentree"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return []
    return [int(pid) for pid in result.stdout.strip().splitlines() if pid.strip()]


def _wait_for_process(
    timeout: int = 120,
    poll_interval: int = 5,
    exclude_pids: set[int] | None = None,
) -> int | None:
    """Wait for a new bot process to appear.

    Args:
        timeout: Max seconds to wait.
        poll_interval: Seconds between polls.
        exclude_pids: PIDs to ignore (the ones we just killed).

    Returns:
        The new PID, or None if timed out.
    """
    exclude = exclude_pids or set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = _get_bot_pids()
        new_pids = [p for p in pids if p not in exclude]
        if new_pids:
            return new_pids[0]
        time.sleep(poll_interval)
    return None


class TestCrashRecovery:
    """A6: Wrapper should restart the bot after it crashes."""

    def test_crash_recovery(
        self,
        check_bot_alive: Callable[[], bool],
        check_heartbeat: Callable[[], tuple[bool, float]],
    ) -> None:
        """Kill the bot process and verify it restarts.

        Steps:
        1. Verify bot is currently running
        2. Record current PIDs
        3. Send SIGTERM to bot process (graceful kill)
        4. Wait for a NEW process to appear (different PID)
        5. Verify heartbeat file is updated
        """
        # Step 1: Verify bot is running
        assert check_bot_alive(), (
            "Bot is not running — cannot test crash recovery"
        )

        # Step 2: Record current PIDs
        old_pids = set(_get_bot_pids())
        assert old_pids, "Could not find bot PIDs to kill"

        # Step 3: Send SIGTERM (graceful shutdown)
        # We use pkill which sends SIGTERM by default
        result = subprocess.run(
            ["pkill", "-f", "opentree"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # pkill returns 0 if at least one process was signaled
        assert result.returncode == 0, (
            f"pkill failed: {result.stderr}"
        )

        # Brief wait for process to die
        time.sleep(5)

        # Step 4: Wait for a new process (wrapper should restart)
        # The wrapper typically waits a few seconds then restarts
        new_pid = _wait_for_process(
            timeout=120,
            poll_interval=5,
            exclude_pids=old_pids,
        )
        assert new_pid is not None, (
            f"Bot did not restart within 120s after killing PIDs {old_pids}"
        )
        assert new_pid not in old_pids, (
            f"New PID {new_pid} is same as old PID — process may not have restarted"
        )

        # Step 5: Wait a bit for the bot to initialize, then check heartbeat
        # The bot needs time to start up and write its first heartbeat
        time.sleep(30)

        is_fresh, age = check_heartbeat()
        assert age < 120, (
            f"Heartbeat not updated after restart (age={age:.0f}s). "
            "Bot may have restarted but is not healthy."
        )
