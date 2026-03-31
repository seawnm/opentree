"""E2E tests for admin commands (A2).

Send admin commands to Bot_Walter via Slack and verify responses.
Each test creates its own thread for isolation.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestStatusCommand:
    """A2: The 'status' command should return queue/health information."""

    def test_status_command(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """Send '@Bot status' and verify response contains queue stats."""
        # Send as a new thread (no thread_ts)
        result = send_message(f"{bot_mention} status")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)

        # The status response should contain some queue/health indicators
        reply_lower = reply.lower()
        # Check for at least one of these keywords indicating status info
        status_indicators = [
            "running", "pending", "completed", "queue",
            "task", "status", "uptime", "version",
        ]
        found = [kw for kw in status_indicators if kw in reply_lower]
        assert found, (
            f"Status reply did not contain expected keywords. "
            f"Got: {reply[:500]}"
        )

    def test_status_case_insensitive(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """Send '@Bot STATUS' (uppercase) and verify same behavior."""
        result = send_message(f"{bot_mention} STATUS")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)

        reply_lower = reply.lower()
        status_indicators = [
            "running", "pending", "completed", "queue",
            "task", "status", "uptime", "version",
        ]
        found = [kw for kw in status_indicators if kw in reply_lower]
        assert found, (
            f"STATUS (uppercase) reply did not contain expected keywords. "
            f"Got: {reply[:500]}"
        )


class TestHelpCommand:
    """A2: The 'help' command should return available commands."""

    def test_help_command(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """Send '@Bot help' and verify response contains command list."""
        result = send_message(f"{bot_mention} help")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)

        # Help response should mention available commands or usage
        reply_lower = reply.lower()
        help_indicators = [
            "help", "command", "usage", "status", "shutdown",
        ]
        found = [kw for kw in help_indicators if kw in reply_lower]
        assert found, (
            f"Help reply did not contain expected keywords. "
            f"Got: {reply[:500]}"
        )
