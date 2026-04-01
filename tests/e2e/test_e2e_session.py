"""E2E tests for session management (B6).

Verify that Bot_Walter correctly manages sessions:
- Same thread maintains conversation context
- Different threads have independent sessions
- Session persists across multiple messages
- Session info is written to sessions.json

Session model: each Slack thread maps to a Claude session_id via
SessionManager (data/sessions.json).  Thread context is rebuilt from
Slack thread history by thread_context.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Path to Bot_Walter's session persistence file
_SESSIONS_JSON = Path(
    "/mnt/e/develop/mydev/project/trees/bot_walter/data/sessions.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_sessions_json() -> dict[str, Any]:
    """Read and parse sessions.json, returning an empty dict on failure."""
    if not _SESSIONS_JSON.exists():
        return {}
    try:
        raw = _SESSIONS_JSON.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


# ===================================================================
# B6 -- Session management
# ===================================================================


class TestSessionManagement:
    """B6: thread context, session independence, persistence."""

    def test_same_thread_maintains_context(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        wait_for_nth_bot_reply: Callable[..., str],
    ) -> None:
        """同一 thread 的後續訊息應保持上下文。

        Step 1: 告訴 bot 一個特定數字
        Step 2: 在同一 thread 問剛才的數字是什麼
        驗證: 回覆包含該數字
        """
        # Step 1: establish context
        result = send_message(
            f"{bot_mention} my favourite number is 42"
        )
        thread_ts = result["message_ts"]

        first_reply = wait_for_bot_reply(thread_ts, timeout=120)
        assert first_reply, "Bot did not reply to first message"

        time.sleep(3)

        # Step 2: ask for recall in same thread
        send_message(
            f"{bot_mention} what is my favourite number?",
            thread_ts=thread_ts,
        )

        second_reply = wait_for_nth_bot_reply(thread_ts, n=2, timeout=120)

        assert "42" in second_reply, (
            f"Expected bot to recall '42' in same thread, got: "
            f"{second_reply[:500]}"
        )

    def test_different_threads_independent(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        wait_for_nth_bot_reply: Callable[..., str],
    ) -> None:
        """不同 thread 有獨立的 session，不會互相干擾。

        Thread A: 我叫 Alice
        Thread B: 我叫 Bob
        Thread A: 我叫什麼？ -> Alice
        Thread B: 我叫什麼？ -> Bob
        """
        # Thread A: establish identity as Alice
        result_a = send_message(
            f"{bot_mention} my name is Alice for this conversation"
        )
        thread_a = result_a["message_ts"]

        # Thread B: establish identity as Bob
        result_b = send_message(
            f"{bot_mention} my name is Bob for this conversation"
        )
        thread_b = result_b["message_ts"]

        # Wait for both first replies
        reply_a1 = wait_for_bot_reply(thread_a, timeout=180)
        reply_b1 = wait_for_bot_reply(thread_b, timeout=180)
        assert reply_a1, "Bot did not reply in thread A"
        assert reply_b1, "Bot did not reply in thread B"

        time.sleep(3)

        # Ask in thread A
        send_message(
            f"{bot_mention} what is my name?",
            thread_ts=thread_a,
        )

        # Ask in thread B
        send_message(
            f"{bot_mention} what is my name?",
            thread_ts=thread_b,
        )

        # Wait for second replies
        reply_a2 = wait_for_nth_bot_reply(thread_a, n=2, timeout=180)
        reply_b2 = wait_for_nth_bot_reply(thread_b, n=2, timeout=180)

        # Thread A should know "Alice", not "Bob"
        assert "alice" in reply_a2.lower(), (
            f"Thread A should recall 'Alice' but got: {reply_a2[:500]}"
        )
        # Thread B should know "Bob", not "Alice"
        assert "bob" in reply_b2.lower(), (
            f"Thread B should recall 'Bob' but got: {reply_b2[:500]}"
        )

        # Negative assertions: ensure no cross-thread context leak
        assert "bob" not in reply_a2.lower(), (
            f"Thread A leaked context from Thread B: {reply_a2[:500]}"
        )
        assert "alice" not in reply_b2.lower(), (
            f"Thread B leaked context from Thread A: {reply_b2[:500]}"
        )

    def test_session_persists_across_messages(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        wait_for_nth_bot_reply: Callable[..., str],
    ) -> None:
        """session 在多條訊息間保持上下文。

        發送 3 條相關訊息在同一 thread，驗證第 3 條回覆
        能引用第 1 條的上下文。
        """
        # Message 1: establish a fact
        result = send_message(
            f"{bot_mention} I am planning a trip to Tokyo"
        )
        thread_ts = result["message_ts"]

        reply_1 = wait_for_bot_reply(thread_ts, timeout=120)
        assert reply_1, "Bot did not reply to message 1"

        time.sleep(3)

        # Message 2: add detail
        send_message(
            f"{bot_mention} I plan to visit during cherry blossom season",
            thread_ts=thread_ts,
        )

        reply_2 = wait_for_nth_bot_reply(thread_ts, n=2, timeout=120)
        assert reply_2, "Bot did not reply to message 2"

        time.sleep(3)

        # Message 3: ask about the first message's context
        send_message(
            f"{bot_mention} which city did I say I am visiting?",
            thread_ts=thread_ts,
        )

        reply_3 = wait_for_nth_bot_reply(thread_ts, n=3, timeout=120)

        # The third reply should reference Tokyo from message 1
        assert "tokyo" in reply_3.lower(), (
            f"Expected bot to recall 'Tokyo' across 3 messages, "
            f"got: {reply_3[:500]}"
        )

    def test_session_stored_in_sessions_json(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """session 資訊應寫入 sessions.json。

        發送訊息並等待回覆後，讀取 sessions.json 驗證
        包含對應 thread_ts 的 session entry，且欄位齊全。
        """
        result = send_message(
            f"{bot_mention} hello, this is a session test"
        )
        thread_ts = result["message_ts"]

        # Wait for the bot to process (session_id is persisted after
        # Claude CLI returns successfully).
        wait_for_bot_reply(thread_ts, timeout=120)

        # Give a moment for atomic save to complete
        time.sleep(5)

        # Read and verify sessions.json
        sessions = _read_sessions_json()

        assert thread_ts in sessions, (
            f"thread_ts {thread_ts} not found in sessions.json. "
            f"Available keys (last 5): {list(sessions.keys())[-5:]}"
        )

        entry = sessions[thread_ts]
        assert "session_id" in entry, (
            f"session entry missing 'session_id': {entry}"
        )
        assert entry["session_id"], (
            "session_id is empty"
        )
        assert "created_at" in entry, (
            f"session entry missing 'created_at': {entry}"
        )
        assert "last_used_at" in entry, (
            f"session entry missing 'last_used_at': {entry}"
        )
