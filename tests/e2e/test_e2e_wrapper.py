"""E2E tests for run.sh crash recovery (A6).

Verify that the wrapper script restarts Bot_Walter after a crash.

WARNING: These tests are destructive — they kill the bot process.
Only run when you are prepared for temporary bot downtime.
"""

from __future__ import annotations

import os
import signal
import time
from typing import Callable

import pytest

from tests.e2e.conftest import BOT_HEARTBEAT_FILE, BOT_PID_FILE

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.destructive]

# More precise pattern: only match the actual bot command, not pgrep/test/editor
_BOT_PROCESS_PATTERN = "opentree start --mode slack"


def _read_bot_pid() -> int | None:
    """Read the bot PID from the PID file (ground truth).

    Returns the PID as an int, or None if the file doesn't exist
    or contains invalid data.
    """
    if not BOT_PID_FILE.exists():
        return None
    try:
        text = BOT_PID_FILE.read_text().strip()
        return int(text) if text else None
    except (ValueError, OSError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)  # Signal 0: probe only, no actual signal sent
        return True
    except ProcessLookupError:
        return False  # Process gone
    except PermissionError:
        return False  # Can't signal = likely zombie/gone


def _wait_for_pid_exit(pid: int, timeout: int = 30) -> bool:
    """Poll until PID is gone. Returns True if exited, False if timeout.

    After SIGTERM timeout, escalates to SIGKILL as a last resort
    (handles WSL2 orphan processes that ignore SIGTERM).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.5)

    # Escalate to SIGKILL if SIGTERM didn't work
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return True  # Already gone

    # Wait a bit more after SIGKILL
    for _ in range(10):
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.5)

    return False


def _get_bot_pids() -> list[int]:
    """Get PIDs matching the bot process pattern (precise match).

    Uses a specific pattern to avoid matching pgrep itself, test runners,
    editors, or other processes that happen to contain 'opentree'.
    """
    import subprocess

    result = subprocess.run(
        ["pgrep", "-f", _BOT_PROCESS_PATTERN],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return []
    return [int(pid) for pid in result.stdout.strip().splitlines() if pid.strip()]


def _wait_for_new_process(
    timeout: int = 120,
    poll_interval: int = 5,
    exclude_pids: set[int] | None = None,
) -> int | None:
    """Wait for a new bot process to appear.

    Checks both PID file (primary) and pgrep (fallback).

    Returns the new PID, or None if timed out.
    """
    exclude = exclude_pids or set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Primary: check PID file
        pid_from_file = _read_bot_pid()
        if pid_from_file and pid_from_file not in exclude and _is_pid_alive(pid_from_file):
            return pid_from_file

        # Fallback: pgrep with precise pattern
        pids = _get_bot_pids()
        new_pids = [p for p in pids if p not in exclude]
        if new_pids:
            return new_pids[0]

        time.sleep(poll_interval)
    return None


class TestCrashRecovery:
    """A6: Wrapper should restart the bot after it crashes."""

    @pytest.fixture(autouse=True)
    def _ensure_single_instance(self):
        """Teardown: ensure no orphaned bot processes after test.

        Runs after every test in this class (pass or fail) to prevent
        the 36-instance accumulation bug.
        """
        yield
        # After test: check for multiple instances
        pids = _get_bot_pids()
        if len(pids) <= 1:
            return

        # Keep only the PID from PID file (the legitimate one)
        legit_pid = _read_bot_pid()
        for pid in pids:
            if pid != legit_pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    def test_crash_recovery(
        self,
        check_bot_alive: Callable[[], bool],
        check_heartbeat: Callable[[], tuple[bool, float]],
    ) -> None:
        """Kill the bot process via PID file and verify it restarts.

        Steps:
        1. Verify bot is currently running
        2. Read PID from bot.pid (precise target)
        3. Send SIGTERM and poll until process exits
        4. Wait for a NEW process to appear (different PID)
        5. Verify heartbeat file is updated
        6. Verify no orphaned instances
        """
        # Step 1: Verify bot is running
        assert check_bot_alive(), (
            "Bot is not running — cannot test crash recovery"
        )

        # Step 2: Read PID from PID file (precise, not pgrep)
        target_pid = _read_bot_pid()
        assert target_pid is not None, (
            f"Could not read bot PID from {BOT_PID_FILE}"
        )
        assert _is_pid_alive(target_pid), (
            f"PID {target_pid} from PID file is not running"
        )

        # Record all current PIDs for exclusion
        old_pids = set(_get_bot_pids())

        # Step 3: Send SIGTERM to the specific PID (not pkill)
        os.kill(target_pid, signal.SIGTERM)

        # Poll until process actually exits (not blind sleep)
        exited = _wait_for_pid_exit(target_pid, timeout=30)
        assert exited, (
            f"Bot process (PID {target_pid}) did not exit within 30s after SIGTERM"
        )

        # Step 4: Wait for a new process (wrapper should restart)
        new_pid = _wait_for_new_process(
            timeout=120,
            poll_interval=5,
            exclude_pids=old_pids,
        )
        assert new_pid is not None, (
            f"Bot did not restart within 120s after killing PID {target_pid}"
        )
        assert new_pid not in old_pids, (
            f"New PID {new_pid} is same as old PID — process may not have restarted"
        )

        # Step 5: Wait for the bot to initialize, then check heartbeat
        time.sleep(30)

        is_fresh, age = check_heartbeat()
        assert age < 120, (
            f"Heartbeat not updated after restart (age={age:.0f}s). "
            "Bot may have restarted but is not healthy."
        )

        # Step 6: Verify no orphaned instances
        all_pids = _get_bot_pids()
        assert len(all_pids) <= 2, (
            f"Multiple bot instances detected after crash recovery: {all_pids}. "
            "Possible orphaned processes from previous runs."
        )
