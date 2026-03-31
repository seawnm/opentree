"""Tests for Receiver — written FIRST (TDD Red phase).

Tests cover:
  - _check_slack_bolt: missing vs present
  - _is_duplicate: first time (False), second time (True)
  - _is_duplicate: max size prunes oldest entries
  - _write_heartbeat: writes timestamp to file
  - _build_task: from mention event, DM event, with/without thread_ts
  - _handle_app_mention: dispatches new event, skips duplicate
  - _handle_message: ignores bot messages, ignores empty text, dispatches DM
  - stop: calls handler close
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Mock slack_bolt before importing receiver so the import guard doesn't fire.
# ---------------------------------------------------------------------------
_mock_bolt_module = MagicMock()
_mock_socket_mode_module = MagicMock()
sys.modules.setdefault("slack_bolt", _mock_bolt_module)
sys.modules.setdefault("slack_bolt.adapter.socket_mode", _mock_socket_mode_module)

from opentree.runner.receiver import Receiver, _check_slack_bolt  # noqa: E402
from opentree.runner.task_queue import Task  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_receiver(
    dispatch_callback=None,
    heartbeat_path=None,
    bot_user_id="UBOT123",
) -> Receiver:
    """Create a Receiver with all Slack dependencies mocked."""
    if dispatch_callback is None:
        dispatch_callback = MagicMock()

    with patch("opentree.runner.receiver._check_slack_bolt"):
        with patch("opentree.runner.receiver.App", MagicMock()) as mock_app_cls:
            receiver = Receiver(
                bot_token="xoxb-fake",
                app_token="xapp-fake",
                bot_user_id=bot_user_id,
                dispatch_callback=dispatch_callback,
                heartbeat_path=heartbeat_path,
            )
            return receiver


def mention_event(
    ts="1000.0001",
    user="U001",
    channel="C001",
    text="<@UBOT123> hello",
    thread_ts=None,
    files=None,
) -> dict:
    ev = {
        "type": "app_mention",
        "ts": ts,
        "user": user,
        "channel": channel,
        "text": text,
    }
    if thread_ts:
        ev["thread_ts"] = thread_ts
    if files:
        ev["files"] = files
    return ev


def dm_event(
    ts="2000.0001",
    user="U002",
    channel="D001",
    text="hello bot",
    thread_ts=None,
) -> dict:
    ev = {
        "type": "message",
        "ts": ts,
        "user": user,
        "channel": channel,
        "channel_type": "im",
        "text": text,
    }
    if thread_ts:
        ev["thread_ts"] = thread_ts
    return ev


# ---------------------------------------------------------------------------
# _check_slack_bolt
# ---------------------------------------------------------------------------

class TestCheckSlackBolt:
    def test_raises_when_missing(self):
        """Should raise ImportError with install hint when slack_bolt absent."""
        with patch.dict(sys.modules, {"slack_bolt": None}):
            with pytest.raises(ImportError, match="pip install opentree\\[slack\\]"):
                _check_slack_bolt()

    def test_no_error_when_present(self):
        """Should not raise when slack_bolt is importable."""
        fake_bolt = MagicMock()
        with patch.dict(sys.modules, {"slack_bolt": fake_bolt}):
            _check_slack_bolt()  # should not raise


# ---------------------------------------------------------------------------
# _is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    def test_first_time_returns_false(self):
        r = make_receiver()
        assert r._is_duplicate("1000.0001") is False

    def test_second_time_returns_true(self):
        r = make_receiver()
        r._is_duplicate("1000.0001")  # prime
        assert r._is_duplicate("1000.0001") is True

    def test_different_ts_not_duplicate(self):
        r = make_receiver()
        r._is_duplicate("1000.0001")
        assert r._is_duplicate("1000.0002") is False

    def test_max_size_prunes_oldest(self):
        """When processed set exceeds _max_processed, oldest entries are pruned."""
        r = make_receiver()
        r._max_processed = 10

        # Fill up to max + 1
        for i in range(11):
            ts = f"{i:013}.0000"
            r._is_duplicate(ts)

        # Set should have been pruned — size must be <= _max_processed
        assert len(r._processed_ts) <= r._max_processed

    def test_after_pruning_new_ts_accepted(self):
        """After pruning, a brand-new ts should not be treated as duplicate."""
        r = make_receiver()
        r._max_processed = 5

        for i in range(6):
            r._is_duplicate(f"{i:013}.0000")

        assert r._is_duplicate("9999999999999.0000") is False

    def test_is_thread_safe(self):
        """Concurrent calls must not raise and should all return consistently."""
        import threading
        r = make_receiver()
        results = []
        lock = threading.Lock()

        def check():
            result = r._is_duplicate("shared.ts")
            with lock:
                results.append(result)

        threads = [threading.Thread(target=check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one thread should have seen False (first time)
        assert results.count(False) == 1
        assert results.count(True) == 19


# ---------------------------------------------------------------------------
# _write_heartbeat
# ---------------------------------------------------------------------------

class TestWriteHeartbeat:
    def test_writes_timestamp_to_file(self, tmp_path):
        path = tmp_path / "bot.heartbeat"
        r = make_receiver(heartbeat_path=path)

        before = int(time.time()) - 1
        r._write_heartbeat()
        after = int(time.time()) + 1

        content = path.read_text().strip()
        ts = int(content)
        assert before <= ts <= after

    def test_no_heartbeat_path_does_not_raise(self):
        r = make_receiver(heartbeat_path=None)
        r._write_heartbeat()  # should not raise

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "subdir" / "nested" / "bot.heartbeat"
        r = make_receiver(heartbeat_path=path)
        r._write_heartbeat()
        assert path.exists()


# ---------------------------------------------------------------------------
# _build_task
# ---------------------------------------------------------------------------

class TestBuildTask:
    def test_build_task_from_mention_event(self):
        r = make_receiver()
        ev = mention_event(ts="1000.0001", user="U001", channel="C001", text="hello")
        task = r._build_task(ev)

        assert isinstance(task, Task)
        assert task.user_id == "U001"
        assert task.channel_id == "C001"
        assert task.message_ts == "1000.0001"
        assert task.text == "hello"

    def test_build_task_uses_thread_ts_when_present(self):
        r = make_receiver()
        ev = mention_event(ts="1000.0002", thread_ts="1000.0001")
        task = r._build_task(ev)

        assert task.thread_ts == "1000.0001"

    def test_build_task_uses_ts_as_thread_root_when_no_thread_ts(self):
        r = make_receiver()
        ev = mention_event(ts="1000.0003")
        task = r._build_task(ev)

        assert task.thread_ts == "1000.0003"

    def test_build_task_from_dm_event(self):
        r = make_receiver()
        ev = dm_event(ts="2000.0001", user="U002", channel="D001", text="hi")
        task = r._build_task(ev)

        assert task.user_id == "U002"
        assert task.channel_id == "D001"
        assert task.text == "hi"
        assert task.message_ts == "2000.0001"

    def test_build_task_includes_files(self):
        r = make_receiver()
        files = [{"id": "F001", "name": "report.pdf"}]
        ev = mention_event(files=files)
        task = r._build_task(ev)

        assert task.files == files

    def test_build_task_no_files_gives_empty_list(self):
        r = make_receiver()
        ev = mention_event()
        task = r._build_task(ev)

        assert task.files == []

    def test_build_task_id_format(self):
        r = make_receiver()
        ev = mention_event(ts="1000.0001", channel="C001", thread_ts="999.0001")
        task = r._build_task(ev)

        # task_id should incorporate channel and ts to be unique
        assert "C001" in task.task_id
        assert "1000.0001" in task.task_id


# ---------------------------------------------------------------------------
# Channel @mention (human, via _handle_message with has_bot_mention)
# ---------------------------------------------------------------------------

class TestChannelMention:
    """Tests for human @mentions in public channels.

    Since app_mention handler is a no-op (to avoid dual-handler race),
    all @mentions are processed by _handle_message via has_bot_mention.
    """

    def test_dispatches_callback_for_channel_mention(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")
        ev = {
            "type": "message", "ts": "1000.0001", "user": "U001",
            "channel": "C001", "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()
        task = callback.call_args[0][0]
        assert isinstance(task, Task)

    def test_does_not_dispatch_duplicate_mention(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")
        ev = {
            "type": "message", "ts": "1000.0002", "user": "U001",
            "channel": "C001", "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())
        r._handle_message(ev, say=MagicMock())  # duplicate

        callback.assert_called_once()

    def test_writes_heartbeat_for_channel_mention(self, tmp_path):
        path = tmp_path / "hb"
        r = make_receiver(heartbeat_path=path, bot_user_id="UBOT123")
        ev = {
            "type": "message", "ts": "1000.0003", "user": "U001",
            "channel": "C001", "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())
        assert path.exists()

    def test_marks_ts_as_processed(self):
        r = make_receiver(bot_user_id="UBOT123")
        ev = {
            "type": "message", "ts": "5000.0001", "user": "U001",
            "channel": "C001", "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())
        assert "5000.0001" in r._processed_ts

    def test_passes_correct_channel_and_user(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")
        ev = {
            "type": "message", "ts": "1000.0004", "user": "U999",
            "channel": "C999", "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())
        task = callback.call_args[0][0]
        assert task.user_id == "U999"
        assert task.channel_id == "C999"


# ---------------------------------------------------------------------------
# _handle_message
# ---------------------------------------------------------------------------

class TestHandleMessage:
    def test_ignores_message_with_bot_id(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback)
        ev = dm_event()
        ev["bot_id"] = "B001"

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_ignores_message_from_bot_user_id(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")
        ev = dm_event(user="UBOT123")

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_ignores_message_with_no_text(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback)
        ev = dm_event(text="")
        del ev["text"]

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_ignores_message_with_empty_text(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback)
        ev = dm_event(text="")

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_dispatches_dm_message(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback)
        ev = dm_event(text="hello bot", user="U001")

        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()
        task = callback.call_args[0][0]
        assert task.user_id == "U001"

    def test_does_not_dispatch_duplicate_dm(self):
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback)
        ev = dm_event(ts="2000.9999", text="hi")

        r._handle_message(ev, say=MagicMock())
        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()

    def test_ignores_non_dm_without_bot_mention(self):
        """Non-DM messages without bot mention should be ignored."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")
        ev = {
            "type": "message",
            "ts": "3000.0001",
            "user": "U001",
            "channel": "C001",
            "channel_type": "channel",
            "text": "hello everyone",
        }

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_dm_writes_heartbeat(self, tmp_path):
        path = tmp_path / "hb"
        r = make_receiver(heartbeat_path=path)
        ev = dm_event(text="hi")

        r._handle_message(ev, say=MagicMock())

        assert path.exists()

    def test_heartbeat_written_on_filtered_message(self, tmp_path):
        """Heartbeat must be written even when the message is filtered out (e.g. bot_id).

        Bug fix: previously heartbeat was only written after successful dispatch,
        so filtered events (bot messages, non-DM channels) left the heartbeat stale.
        """
        path = tmp_path / "hb"
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, heartbeat_path=path)

        # Message with bot_id — should be filtered (not dispatched) but heartbeat written
        ev = dm_event(text="bot message")
        ev["bot_id"] = "B999"

        r._handle_message(ev, say=MagicMock())

        # Dispatch should NOT have been called (filtered out)
        callback.assert_not_called()
        # But heartbeat MUST have been written
        assert path.exists()
        content = path.read_text().strip()
        assert content.isdigit()

    def test_heartbeat_written_on_non_dm_channel_message(self, tmp_path):
        """Heartbeat written even for non-DM channel messages that get filtered."""
        path = tmp_path / "hb"
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, heartbeat_path=path)

        ev = {
            "type": "message",
            "ts": "3000.0001",
            "user": "U001",
            "channel": "C001",
            "channel_type": "channel",
            "text": "hello everyone",
        }

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()
        assert path.exists()

    def test_heartbeat_written_on_empty_text_message(self, tmp_path):
        """Heartbeat written even for messages with empty text that get filtered."""
        path = tmp_path / "hb"
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, heartbeat_path=path)

        ev = dm_event(text="")

        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()
        assert path.exists()


# ---------------------------------------------------------------------------
# Bot-to-bot @mention handling
# ---------------------------------------------------------------------------

class TestBotToBotMention:
    """Verify that messages from other bots with explicit @mention are dispatched."""

    def test_bot_message_with_mention_dispatched(self):
        """Other bot's message that @mentions this bot should be dispatched."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev = {
            "type": "message",
            "ts": "5000.0001",
            "user": "U_OTHER_BOT",
            "channel": "C001",
            "text": "<@UBOT123> status",
            "bot_id": "B_OTHER",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()
        task = callback.call_args[0][0]
        assert task.text == "<@UBOT123> status"

    def test_bot_message_without_mention_filtered(self):
        """Other bot's message WITHOUT @mention should be filtered."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev = {
            "type": "message",
            "ts": "5000.0002",
            "user": "U_OTHER_BOT",
            "channel": "C001",
            "text": "some bot chatter",
            "bot_id": "B_OTHER",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_bot_mention_in_thread_dispatched(self):
        """Other bot's thread reply with @mention should be dispatched."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev = {
            "type": "message",
            "ts": "5000.0003",
            "user": "U_OTHER_BOT",
            "channel": "C001",
            "thread_ts": "4999.0001",
            "text": "<@UBOT123> what was my previous message?",
            "bot_id": "B_OTHER",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()
        task = callback.call_args[0][0]
        assert task.thread_ts == "4999.0001"

    def test_self_message_always_filtered(self):
        """This bot's own messages must always be filtered, even with @mention."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev = {
            "type": "message",
            "ts": "5000.0004",
            "user": "UBOT123",  # self
            "channel": "C001",
            "text": "<@UBOT123> status",
            "bot_id": "B_SELF",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_not_called()

    def test_human_mention_in_channel_dispatched(self):
        """Human @mention in a public channel should also be dispatched."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev = {
            "type": "message",
            "ts": "5000.0005",
            "user": "U_HUMAN",
            "channel": "C001",
            "text": "<@UBOT123> hello",
            "channel_type": "channel",
        }
        r._handle_message(ev, say=MagicMock())

        callback.assert_called_once()

    def test_same_ts_message_events_deduped(self):
        """Two message events with same ts are deduped (single dispatch)."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ts = "6000.0001"
        ev1 = {
            "type": "message", "ts": ts, "user": "U_OTHER",
            "channel": "C001", "text": "<@UBOT123> status",
            "channel_type": "channel",
        }
        ev2 = {
            "type": "message", "ts": ts, "user": "U_OTHER_BOT",
            "channel": "C001", "text": "<@UBOT123> status",
            "bot_id": "B_OTHER", "channel_type": "channel",
        }

        r._handle_message(ev1, say=MagicMock())
        r._handle_message(ev2, say=MagicMock())

        callback.assert_called_once()

    def test_different_ts_both_dispatched(self):
        """Two message events with different ts are both dispatched."""
        callback = MagicMock()
        r = make_receiver(dispatch_callback=callback, bot_user_id="UBOT123")

        ev1 = {
            "type": "message", "ts": "6000.0002", "user": "U_OTHER_BOT",
            "channel": "C001", "text": "<@UBOT123> help",
            "bot_id": "B_OTHER", "channel_type": "channel",
        }
        ev2 = {
            "type": "message", "ts": "6000.0003", "user": "U_OTHER_BOT",
            "channel": "C001", "text": "<@UBOT123> status",
            "bot_id": "B_OTHER", "channel_type": "channel",
        }

        r._handle_message(ev1, say=MagicMock())
        r._handle_message(ev2, say=MagicMock())

        assert callback.call_count == 2


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_stop_calls_handler_close(self):
        r = make_receiver()
        mock_handler = MagicMock()
        r._handler = mock_handler

        r.stop()

        mock_handler.close.assert_called_once()

    def test_stop_sets_handler_to_none(self):
        r = make_receiver()
        r._handler = MagicMock()

        r.stop()

        assert r._handler is None

    def test_stop_when_no_handler_does_not_raise(self):
        r = make_receiver()
        r._handler = None

        r.stop()  # should not raise

    def test_start_creates_app_and_handler(self):
        """start() should instantiate App, register handlers, and call handler.start()."""
        mock_app_instance = MagicMock()
        mock_handler_instance = MagicMock()

        with patch("opentree.runner.receiver.App", return_value=mock_app_instance) as mock_app_cls:
            with patch(
                "opentree.runner.receiver.SocketModeHandler",
                return_value=mock_handler_instance,
            ) as mock_handler_cls:
                with patch("opentree.runner.receiver._check_slack_bolt"):
                    r = Receiver(
                        bot_token="xoxb-fake",
                        app_token="xapp-fake",
                        bot_user_id="UBOT",
                        dispatch_callback=MagicMock(),
                    )
                    r.start()

        mock_handler_cls.assert_called_once_with(mock_app_instance, "xapp-fake")
        mock_handler_instance.start.assert_called_once()

    def test_start_registers_event_handlers(self):
        """start() must register app_mention and message handlers on the bolt App."""
        mock_app_instance = MagicMock()

        with patch("opentree.runner.receiver.App", return_value=mock_app_instance):
            with patch("opentree.runner.receiver.SocketModeHandler", MagicMock()):
                with patch("opentree.runner.receiver._check_slack_bolt"):
                    r = Receiver(
                        bot_token="xoxb-fake",
                        app_token="xapp-fake",
                        bot_user_id="UBOT",
                        dispatch_callback=MagicMock(),
                    )
                    r.start()

        # event() should have been called at least twice (app_mention + message)
        assert mock_app_instance.event.call_count >= 2
        event_names = [c.args[0] for c in mock_app_instance.event.call_args_list]
        assert "app_mention" in event_names
        assert "message" in event_names
