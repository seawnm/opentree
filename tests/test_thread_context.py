"""Tests for ThreadContextBuilder — thread history formatter for Claude context.

TDD order:
1.  test_empty_thread — no replies returns empty string
2.  test_single_message_excluded — only the trigger message, returns empty string
3.  test_basic_context — 2 user messages + 1 bot message filtered
4.  test_bot_messages_excluded — bot's own messages are never included
5.  test_empty_text_excluded — messages with empty/missing text are skipped
6.  test_max_messages_limit — sliding window keeps most recent N messages
7.  test_max_chars_truncation — oldest messages dropped when over char limit
8.  test_format_message_with_display_name — display name resolved via slack_api
9.  test_format_message_bot_excluded — _format_message returns None for bot user
10. test_truncate_to_limit — helper trims from oldest when over limit
11. test_api_error_returns_empty — SlackAPI error is swallowed gracefully
12. test_last_message_excluded — the triggering (last) message is always excluded
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from opentree.runner.thread_context import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_MESSAGES,
    _format_message,
    _truncate_to_limit,
    build_thread_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOT_ID = "UBOT001"
USER_A_ID = "U001"
USER_B_ID = "U002"
CHANNEL = "C001"
THREAD_TS = "1700000000.000001"


def _make_slack_api(
    *,
    replies: list[dict] | None = None,
    display_names: dict[str, str] | None = None,
    raises: Exception | None = None,
) -> MagicMock:
    """Return a MagicMock SlackAPI with pre-configured return values."""
    api = MagicMock()

    if raises is not None:
        api.get_thread_replies.side_effect = raises
    else:
        api.get_thread_replies.return_value = replies or []

    def _display_name(user_id: str) -> str:
        mapping = display_names or {}
        return mapping.get(user_id, user_id)

    api.get_user_display_name.side_effect = _display_name
    return api


def _user_msg(user_id: str, text: str, ts: str = "1700000001.000001") -> dict:
    return {"user": user_id, "text": text, "ts": ts}


def _bot_msg(bot_id: str, text: str, ts: str = "1700000002.000001") -> dict:
    return {"user": bot_id, "text": text, "ts": ts}


# ---------------------------------------------------------------------------
# 1. test_empty_thread
# ---------------------------------------------------------------------------


class TestEmptyThread:
    """Returns empty string when the thread has no replies."""

    def test_no_replies_returns_empty_string(self):
        api = _make_slack_api(replies=[])

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""
        api.get_thread_replies.assert_called_once_with(CHANNEL, THREAD_TS)


# ---------------------------------------------------------------------------
# 2. test_single_message_excluded
# ---------------------------------------------------------------------------


class TestSingleMessageExcluded:
    """When thread contains only the triggering (last) message, return empty string."""

    def test_only_trigger_message_returns_empty(self):
        replies = [_user_msg(USER_A_ID, "Hey bot")]
        api = _make_slack_api(replies=replies)

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""

    def test_only_bot_trigger_returns_empty(self):
        replies = [_bot_msg(BOT_ID, "I am bot")]
        api = _make_slack_api(replies=replies)

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""


# ---------------------------------------------------------------------------
# 3. test_basic_context
# ---------------------------------------------------------------------------


class TestBasicContext:
    """Two user messages before the trigger are included; bot messages excluded."""

    def test_two_user_messages_included(self):
        replies = [
            _user_msg(USER_A_ID, "Hello", ts="1700000001.000001"),
            _user_msg(USER_B_ID, "World", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger message", ts="1700000003.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice", USER_B_ID: "Bob"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "Alice: Hello" in result
        assert "Bob: World" in result

    def test_trigger_message_not_in_context(self):
        replies = [
            _user_msg(USER_A_ID, "first", ts="1700000001.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000002.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "first" in result
        assert "trigger" not in result

    def test_context_format_is_name_colon_text(self):
        replies = [
            _user_msg(USER_A_ID, "some text", ts="1700000001.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000002.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "Alice: some text" in result


# ---------------------------------------------------------------------------
# 4. test_bot_messages_excluded
# ---------------------------------------------------------------------------


class TestBotMessagesExcluded:
    """The bot's own messages are never included in context."""

    def test_bot_messages_not_in_output(self):
        replies = [
            _user_msg(USER_A_ID, "user says hi", ts="1700000001.000001"),
            _bot_msg(BOT_ID, "bot replies", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "bot replies" not in result
        assert "user says hi" in result

    def test_all_messages_are_bot_returns_empty(self):
        replies = [
            _bot_msg(BOT_ID, "first bot msg", ts="1700000001.000001"),
            _bot_msg(BOT_ID, "second bot msg", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(replies=replies)

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""


# ---------------------------------------------------------------------------
# 5. test_empty_text_excluded
# ---------------------------------------------------------------------------


class TestEmptyTextExcluded:
    """Messages with empty or missing text are skipped."""

    def test_empty_string_text_skipped(self):
        replies = [
            {"user": USER_A_ID, "text": "", "ts": "1700000001.000001"},
            _user_msg(USER_A_ID, "valid text", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "valid text" in result

    def test_missing_text_key_skipped(self):
        replies = [
            {"user": USER_A_ID, "ts": "1700000001.000001"},  # no "text" key
            _user_msg(USER_A_ID, "valid", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "valid" in result

    def test_all_empty_text_returns_empty_string(self):
        replies = [
            {"user": USER_A_ID, "text": "", "ts": "1700000001.000001"},
            {"user": USER_A_ID, "text": "", "ts": "1700000002.000001"},
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(replies=replies)

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""


# ---------------------------------------------------------------------------
# 6. test_max_messages_limit
# ---------------------------------------------------------------------------


class TestMaxMessagesLimit:
    """Sliding window: only the most recent max_messages are included."""

    def test_older_messages_excluded_when_over_limit(self):
        # 5 user messages + 1 trigger = 6 total; max_messages=3 means only 3 of
        # the non-trigger messages can appear (the most recent ones).
        replies = [
            _user_msg(USER_A_ID, f"msg{i}", ts=f"170000000{i}.000001")
            for i in range(6)
        ]
        # Last one is the trigger
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(
            api, CHANNEL, THREAD_TS, BOT_ID, max_messages=3
        )

        # trigger (index 5) excluded; of remaining 5, only 3 most recent kept
        # → indices 2, 3, 4
        assert "msg2" in result
        assert "msg3" in result
        assert "msg4" in result
        assert "msg0" not in result
        assert "msg1" not in result

    def test_exact_limit_keeps_all(self):
        replies = [
            _user_msg(USER_A_ID, f"msg{i}", ts=f"170000000{i}.000001")
            for i in range(4)
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(
            api, CHANNEL, THREAD_TS, BOT_ID, max_messages=3
        )

        # 4 messages → last is trigger, 3 history messages = exactly max_messages
        assert "msg0" in result
        assert "msg1" in result
        assert "msg2" in result


# ---------------------------------------------------------------------------
# 7. test_max_chars_truncation
# ---------------------------------------------------------------------------


class TestMaxCharsTruncation:
    """Oldest messages dropped when total chars exceed max_chars."""

    def test_oldest_dropped_when_over_limit(self):
        # Three user messages each 100 chars; max_chars=150 → only 1 fits fully
        long_text = "x" * 100
        replies = [
            _user_msg(USER_A_ID, "OLDEST " + long_text, ts="1700000001.000001"),
            _user_msg(USER_A_ID, "MIDDLE " + long_text, ts="1700000002.000001"),
            _user_msg(USER_A_ID, "NEWEST " + long_text, ts="1700000003.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000004.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(
            api, CHANNEL, THREAD_TS, BOT_ID, max_chars=150
        )

        assert "NEWEST" in result
        assert "OLDEST" not in result

    def test_all_messages_within_limit_kept(self):
        replies = [
            _user_msg(USER_A_ID, "short", ts="1700000001.000001"),
            _user_msg(USER_A_ID, "text", ts="1700000002.000001"),
            _user_msg(USER_A_ID, "trigger", ts="1700000003.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(
            api, CHANNEL, THREAD_TS, BOT_ID, max_chars=8000
        )

        assert "short" in result
        assert "text" in result


# ---------------------------------------------------------------------------
# 8. test_format_message_with_display_name
# ---------------------------------------------------------------------------


class TestFormatMessageWithDisplayName:
    """_format_message resolves the user display name via slack_api."""

    def test_returns_display_name_colon_text(self):
        msg = _user_msg(USER_A_ID, "hello world")
        api = MagicMock()
        api.get_user_display_name.return_value = "Alice"

        result = _format_message(msg, api, BOT_ID)

        assert result == "Alice: hello world"
        api.get_user_display_name.assert_called_once_with(USER_A_ID)

    def test_falls_back_to_user_id_when_display_name_empty(self):
        msg = _user_msg(USER_A_ID, "hi")
        api = MagicMock()
        api.get_user_display_name.return_value = ""

        result = _format_message(msg, api, BOT_ID)

        assert USER_A_ID in result
        assert "hi" in result

    def test_returns_none_when_text_is_empty(self):
        msg = {"user": USER_A_ID, "text": "", "ts": "1700000001.000001"}
        api = MagicMock()
        api.get_user_display_name.return_value = "Alice"

        result = _format_message(msg, api, BOT_ID)

        assert result is None

    def test_returns_none_when_text_key_missing(self):
        msg = {"user": USER_A_ID, "ts": "1700000001.000001"}
        api = MagicMock()

        result = _format_message(msg, api, BOT_ID)

        assert result is None


# ---------------------------------------------------------------------------
# 9. test_format_message_bot_excluded
# ---------------------------------------------------------------------------


class TestFormatMessageBotExcluded:
    """_format_message returns None for messages belonging to the bot."""

    def test_bot_message_returns_none(self):
        msg = _bot_msg(BOT_ID, "I am the bot")
        api = MagicMock()

        result = _format_message(msg, api, BOT_ID)

        assert result is None
        api.get_user_display_name.assert_not_called()

    def test_different_bot_id_not_excluded(self):
        other_bot = "UOTHERBOT"
        msg = _bot_msg(other_bot, "other bot message")
        api = MagicMock()
        api.get_user_display_name.return_value = "OtherBot"

        result = _format_message(msg, api, BOT_ID)

        # A different bot's message is treated as a regular user
        assert result is not None
        assert "other bot message" in result


# ---------------------------------------------------------------------------
# 10. test_truncate_to_limit
# ---------------------------------------------------------------------------


class TestTruncateToLimit:
    """_truncate_to_limit removes oldest entries until total chars <= max_chars."""

    def test_under_limit_unchanged(self):
        messages = ["short", "text"]
        result = _truncate_to_limit(messages, max_chars=1000)
        assert result == ["short", "text"]

    def test_exact_limit_unchanged(self):
        messages = ["abcde"]  # 5 chars
        result = _truncate_to_limit(messages, max_chars=5)
        assert result == ["abcde"]

    def test_oldest_removed_when_over_limit(self):
        messages = ["OLDEST", "MIDDLE", "NEWEST"]  # 6+6+6=18 chars
        result = _truncate_to_limit(messages, max_chars=12)  # fits 2
        assert "OLDEST" not in result
        assert "NEWEST" in result

    def test_single_large_message_kept(self):
        """Even if a single message exceeds the limit, it is kept (never empty)."""
        messages = ["x" * 10000]
        result = _truncate_to_limit(messages, max_chars=100)
        assert result == ["x" * 10000]

    def test_empty_list_returns_empty(self):
        result = _truncate_to_limit([], max_chars=100)
        assert result == []

    def test_removes_multiple_oldest(self):
        messages = ["A" * 50, "B" * 50, "C" * 50, "D" * 50]  # 200 chars total
        result = _truncate_to_limit(messages, max_chars=60)
        # Only the last 1 message fits; "D" * 50 = 50 chars <= 60
        assert "D" * 50 in result
        assert "A" * 50 not in result
        assert "B" * 50 not in result


# ---------------------------------------------------------------------------
# 11. test_api_error_returns_empty
# ---------------------------------------------------------------------------


class TestApiErrorReturnsEmpty:
    """SlackAPI exceptions are caught and empty string is returned."""

    def test_get_thread_replies_exception_returns_empty(self):
        api = _make_slack_api(raises=Exception("network timeout"))

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""

    def test_get_thread_replies_runtime_error_returns_empty(self):
        api = _make_slack_api(raises=RuntimeError("connection reset"))

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert result == ""

    def test_does_not_propagate_exception(self):
        api = _make_slack_api(raises=ValueError("unexpected"))

        # Must not raise
        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 12. test_last_message_excluded
# ---------------------------------------------------------------------------


class TestLastMessageExcluded:
    """The last message in the thread (the trigger) is always excluded."""

    def test_last_message_not_in_context(self):
        trigger_text = "this is the current question"
        replies = [
            _user_msg(USER_A_ID, "prior message", ts="1700000001.000001"),
            _user_msg(USER_A_ID, trigger_text, ts="1700000002.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert trigger_text not in result
        assert "prior message" in result

    def test_last_message_excluded_regardless_of_user(self):
        """Even if the last message is from a different user, it is excluded."""
        replies = [
            _user_msg(USER_A_ID, "context", ts="1700000001.000001"),
            _user_msg(USER_B_ID, "last message", ts="1700000002.000001"),
        ]
        api = _make_slack_api(
            replies=replies,
            display_names={USER_A_ID: "Alice", USER_B_ID: "Bob"},
        )

        result = build_thread_context(api, CHANNEL, THREAD_TS, BOT_ID)

        assert "last message" not in result
        assert "context" in result


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    """Verify module-level default constants are sensible."""

    def test_default_max_messages_is_20(self):
        assert DEFAULT_MAX_MESSAGES == 20

    def test_default_max_chars_is_8000(self):
        assert DEFAULT_MAX_CHARS == 8000
