"""E2E tests for concurrent request handling (A5).

Verify that Bot_Walter can handle multiple simultaneous requests
by sending messages to separate threads and checking all get responses.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pytest

from tests.e2e.conftest import (
    BOT_USER_ID,
    CHANNEL_ID,
    _run_message_tool,
    _run_query_tool,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _poll_for_reply(
    thread_ts: str,
    timeout: int = 180,
    poll_interval: int = 5,
) -> str | None:
    """Poll a thread until Bot_Walter replies or timeout.

    Returns the reply text, or None if timed out.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _run_query_tool(
            "read-thread",
            channel=CHANNEL_ID,
            thread_ts=thread_ts,
            limit="50",
        )
        if data.get("success"):
            for msg in data.get("messages", []):
                if msg.get("user") == BOT_USER_ID:
                    return msg.get("text", "")
        time.sleep(poll_interval)
    return None


class TestConcurrentRequests:
    """A5: Bot should handle multiple simultaneous requests."""

    def test_concurrent_requests(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
    ) -> None:
        """Send 3 messages rapidly to separate threads, verify all get replies.

        This tests whether the bot's task queue can handle concurrent
        requests without dropping any.
        """
        # Send 3 messages in quick succession, each creating a new thread
        threads: list[tuple[str, str]] = []  # (thread_ts, question)
        questions = [
            "What is 2 + 2? Reply with just the number.",
            "What color is the sky? Reply with just the color.",
            "What planet do we live on? Reply with just the name.",
        ]

        for question in questions:
            result = send_message(f"{bot_mention} {question}")
            thread_ts = result["message_ts"]
            threads.append((thread_ts, question))
            # Tiny delay to avoid rate limiting, but keep it fast
            time.sleep(1)

        # Now poll all threads with a generous timeout
        # The bot may queue them and process sequentially
        timeout = 300  # 5 minutes total — allows for sequential processing
        replies: dict[str, str | None] = {}

        deadline = time.monotonic() + timeout
        pending = {ts for ts, _ in threads}

        while pending and time.monotonic() < deadline:
            for thread_ts in list(pending):
                data = _run_query_tool(
                    "read-thread",
                    channel=CHANNEL_ID,
                    thread_ts=thread_ts,
                    limit="50",
                )
                if data.get("success"):
                    for msg in data.get("messages", []):
                        if msg.get("user") == BOT_USER_ID:
                            replies[thread_ts] = msg.get("text", "")
                            pending.discard(thread_ts)
                            break
            if pending:
                time.sleep(10)

        # Verify results
        answered = sum(1 for ts, _ in threads if ts in replies)
        total = len(threads)

        # All 3 should have gotten replies
        assert answered == total, (
            f"Only {answered}/{total} concurrent requests got replies. "
            f"Pending threads: {pending}"
        )

        # Verify each reply is non-empty
        for thread_ts, question in threads:
            reply = replies.get(thread_ts)
            assert reply, (
                f"Empty reply for thread {thread_ts} "
                f"(question: {question[:50]})"
            )
