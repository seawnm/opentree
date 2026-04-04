"""E2E tests for multi-turn conversation (A7).

Verify that Bot_Walter retains context across multiple messages
within the same Slack thread.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestMultiTurnContext:
    """A7: Bot should retain conversation context within a thread."""

    def test_multi_turn_context(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        read_thread: Callable[..., dict[str, Any]],
    ) -> None:
        """Send a greeting with a unique phrase, then ask the bot to recall it.

        Steps:
        1. Send a message with a distinctive phrase to create a new thread
        2. Wait for the bot to reply
        3. Send a follow-up asking what was just said
        4. Verify the bot's second reply references the original phrase
        """
        # Use a distinctive phrase that the bot should remember
        unique_phrase = "purple elephants dancing on Mars"

        # Step 1: First message — create a new thread
        result = send_message(
            f"{bot_mention} I want to tell you something: {unique_phrase}"
        )
        thread_ts = result["message_ts"]

        # Step 2: Wait for first reply
        first_reply = wait_for_bot_reply(thread_ts, timeout=120)
        assert first_reply, "Bot did not reply to first message"

        # Allow time for session persistence + Slack API consistency
        time.sleep(10)

        # Step 3: Follow-up in the same thread (MUST include @mention)
        send_message(
            f"{bot_mention} what did I just tell you about? "
            "Please repeat the exact phrase.",
            thread_ts=thread_ts,
        )

        # Step 4: Wait for second reply and check context retention
        # We need to poll for a NEW reply (not the first one)
        deadline = time.monotonic() + 120
        second_reply = ""
        while time.monotonic() < deadline:
            data = read_thread(thread_ts, limit=50)
            if data.get("success"):
                messages = data.get("messages", [])
                # Find bot replies (skip the first one we already saw)
                bot_replies = [
                    msg.get("text", "")
                    for msg in messages
                    if msg.get("user") == "U0APZ9MR997"  # Bot_Walter user ID
                ]
                if len(bot_replies) >= 2:
                    second_reply = bot_replies[-1]
                    break
            time.sleep(5)

        assert second_reply, (
            "Bot did not send a second reply within timeout"
        )

        # The second reply should reference the unique phrase
        # Check for key words from the phrase
        reply_lower = second_reply.lower()
        key_words = ["purple", "elephants", "mars"]
        found = [w for w in key_words if w in reply_lower]
        assert len(found) >= 2, (
            f"Bot's second reply did not retain context. "
            f"Expected keywords from '{unique_phrase}', "
            f"found {found} in: {second_reply[:500]}"
        )
