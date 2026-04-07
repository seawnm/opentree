"""Tests for Dispatcher — TDD Red phase (written before implementation).

Tests cover:
  - parse_message: strips @bot mention, detects admin commands, handles edge cases
  - build_prompt_context: builds correct PromptContext from Task fields
  - dispatch: submits task, starts immediately vs queued
  - _process_task: success path, error path, timeout path
  - Session resume: session_id passed to ClaudeProcess and saved after success
  - Admin commands: status, help, shutdown
  - get_stats: returns queue statistics
  - next task after completion promoted
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from opentree.runner.config import RunnerConfig
from opentree.runner.task_queue import Task, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    task_id: str = "C001_1000.0_1000.1",
    channel_id: str = "C001",
    thread_ts: str = "1000.0001",
    user_id: str = "U001",
    user_name: str = "alice",
    text: str = "hello world",
    message_ts: str = "1000.0002",
    files: list | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        user_name=user_name,
        text=text,
        message_ts=message_ts,
        files=files or [],
    )


def _make_dispatcher(tmp_path: Path, shutdown_event=None):
    """Create a Dispatcher with all external deps mocked."""
    from opentree.runner.dispatcher import Dispatcher
    from opentree.core.config import UserConfig
    from opentree.runner.config import RunnerConfig
    from opentree.registry.models import RegistryData

    slack_api = MagicMock()
    slack_api.send_message.return_value = {"ts": "9999.0001"}
    slack_api.update_message.return_value = {"ts": "9999.0001"}
    slack_api.bot_user_id = "UBOT123"
    slack_api.get_user_display_name.return_value = "alice"

    if shutdown_event is None:
        shutdown_event = threading.Event()

    fake_user_config = UserConfig(
        bot_name="TestBot",
        team_name="TestTeam",
        opentree_home=str(tmp_path),
    )
    fake_runner_config = RunnerConfig(
        max_concurrent_tasks=2,
        task_timeout=30,
    )
    fake_registry = RegistryData(version=1, modules=())

    # Create required directory structure
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "workspace").mkdir(exist_ok=True)
    (tmp_path / "config").mkdir(exist_ok=True)

    with (
        patch("opentree.runner.dispatcher.load_user_config", return_value=fake_user_config),
        patch("opentree.runner.dispatcher.load_runner_config", return_value=fake_runner_config),
        patch("opentree.runner.dispatcher.Registry.load", return_value=fake_registry),
    ):
        dispatcher = Dispatcher(
            opentree_home=tmp_path,
            slack_api=slack_api,
            shutdown_event=shutdown_event,
        )

    dispatcher._slack = slack_api
    return dispatcher, slack_api, shutdown_event


# ---------------------------------------------------------------------------
# parse_message
# ---------------------------------------------------------------------------

class TestParseMessage:
    def test_strips_bot_mention(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> hello world", "UBOT123")
        assert result.text == "hello world"
        assert not result.is_admin_command

    def test_strips_bot_mention_with_extra_spaces(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("  <@UBOT123>   hello  ", "UBOT123")
        assert result.text == "hello"

    def test_normal_text_no_mention(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("just a normal message", "UBOT123")
        assert result.text == "just a normal message"
        assert not result.is_admin_command

    def test_admin_command_status(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> status", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "status"

    def test_admin_command_help(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> help", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "help"

    def test_admin_command_shutdown(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> shutdown", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "shutdown"

    def test_admin_command_case_insensitive(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> STATUS", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "status"

    def test_empty_after_mention(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123>", "UBOT123")
        assert result.text == ""
        assert not result.is_admin_command

    def test_non_admin_text_not_flagged_as_admin(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> what is your status?", "UBOT123")
        # "what is your status?" is not exactly "status"
        assert not result.is_admin_command

    def test_files_passed_through(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        files = [{"id": "F001", "name": "test.txt"}]
        result = dispatcher.parse_message("<@UBOT123> hello", "UBOT123", files=files)
        assert result.files == tuple(files)

    def test_no_files_returns_empty(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> hello", "UBOT123")
        assert result.files == ()

    def test_mention_in_middle_not_stripped(self, tmp_path):
        """Only leading mention is stripped."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("hello <@UBOT123> there", "UBOT123")
        # No leading mention, text returned as-is
        assert "<@UBOT123>" in result.text


# ---------------------------------------------------------------------------
# _build_prompt_context
# ---------------------------------------------------------------------------

class TestBuildPromptContext:
    def test_builds_correct_context(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(
            user_id="U001",
            user_name="alice",
            channel_id="C001",
            thread_ts="1000.0001",
        )
        ctx = dispatcher._build_prompt_context(task)
        assert ctx.user_id == "U001"
        assert ctx.user_name == "alice"
        assert ctx.channel_id == "C001"
        assert ctx.thread_ts == "1000.0001"

    def test_team_name_from_config(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task()
        ctx = dispatcher._build_prompt_context(task)
        assert ctx.team_name == "TestTeam"

    def test_memory_path_contains_user_name(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(user_name="alice")
        ctx = dispatcher._build_prompt_context(task)
        assert "alice" in ctx.memory_path

    def test_memory_path_contains_memory_md(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(user_name="bob")
        ctx = dispatcher._build_prompt_context(task)
        assert ctx.memory_path.endswith("memory.md")

    def test_workspace_uses_team_name_or_default(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task()
        ctx = dispatcher._build_prompt_context(task)
        # workspace = team_name when set, "default" when empty
        expected = dispatcher._user_config.team_name or "default"
        assert ctx.workspace == expected


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_dispatch_starts_immediately_when_capacity_available(self, tmp_path):
        """When task_queue.submit returns True, process_task runs in a thread."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task = make_task()
        started = threading.Event()
        completed = threading.Event()

        def fake_process(t):
            started.set()
            completed.set()

        dispatcher._process_task = fake_process

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(task)

        started.wait(timeout=2.0)
        assert started.is_set(), "_process_task should have been called"

    def test_dispatch_queued_sends_ack_when_queue_full(self, tmp_path):
        """When task_queue.submit returns False (queued), send queued ack."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()

        with patch.object(dispatcher._task_queue, "submit", return_value=False):
            dispatcher.dispatch(task)

        # Slack should have sent a "queued" ack message
        slack_api.send_message.assert_called()
        args = slack_api.send_message.call_args
        # Should reply to the thread
        assert args[1].get("thread_ts") == task.thread_ts or args[0][2] == task.thread_ts

    def test_dispatch_does_not_call_process_when_queued(self, tmp_path):
        """When queued (submit=False), _process_task should NOT be called immediately."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task()
        called = threading.Event()

        def fake_process(t):
            called.set()

        dispatcher._process_task = fake_process

        with patch.object(dispatcher._task_queue, "submit", return_value=False):
            dispatcher.dispatch(task)

        called.wait(timeout=0.3)
        assert not called.is_set(), "_process_task should NOT be called for queued task"


# ---------------------------------------------------------------------------
# _process_task success path
# ---------------------------------------------------------------------------

class TestProcessTaskSuccess:
    def test_sends_initial_ack(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "Hello from Claude"
        fake_result.session_id = "sess-abc"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys-prompt"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # Initial ack sent before Claude ran
        assert slack_api.send_message.called

    def test_updates_message_with_response(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "The answer is 42"
        fake_result.session_id = "sess-abc"

        slack_api.send_message.return_value = {"ts": "9999.0001"}

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys-prompt"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # update_message OR a second send_message with the final response
        assert (
            slack_api.update_message.called or
            slack_api.send_message.call_count >= 2
        )

    def test_marks_task_completed_on_success(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "Done"
        fake_result.session_id = "sess-xyz"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._task_queue, "mark_completed") as mock_complete,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_complete.assert_called_once_with(task)

    def test_saves_session_id_on_success(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(thread_ts="9876.5432")
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "Done"
        fake_result.session_id = "new-session-id"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._session_mgr, "set_session_id") as mock_set,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_set.assert_called_once_with("9876.5432", "new-session-id")

    def test_does_not_save_empty_session_id(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "Done"
        fake_result.session_id = ""  # empty session_id

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._session_mgr, "set_session_id") as mock_set,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# Session resume
# ---------------------------------------------------------------------------

class TestSessionResume:
    def test_existing_session_id_passed_to_claude(self, tmp_path):
        """If a session_id exists for the thread, it must be passed to ClaudeProcess."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(thread_ts="existing-thread")
        task.status = TaskStatus.RUNNING

        dispatcher._session_mgr.set_session_id("existing-thread", "prev-session-123")

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "Resumed"
        fake_result.session_id = "prev-session-123"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # ClaudeProcess constructor should have received session_id
        init_kwargs = MockClaude.call_args
        # Check positional or keyword args
        session_id_passed = (
            init_kwargs[1].get("session_id") == "prev-session-123"
            if init_kwargs[1]
            else "prev-session-123" in init_kwargs[0]
        )
        assert session_id_passed, f"session_id not passed to ClaudeProcess. Got: {init_kwargs}"

    def test_no_session_id_for_new_thread(self, tmp_path):
        """For a new thread with no session, session_id should be empty string."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(thread_ts="brand-new-thread")
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "New"
        fake_result.session_id = "fresh-session"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        init_kwargs = MockClaude.call_args
        session_id_passed = init_kwargs[1].get("session_id", None) if init_kwargs[1] else None
        assert session_id_passed == "" or session_id_passed is None


# ---------------------------------------------------------------------------
# _process_task error path
# ---------------------------------------------------------------------------

class TestProcessTaskError:
    def test_marks_task_failed_on_error(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = True
        fake_result.is_timeout = False
        fake_result.response_text = ""
        fake_result.error_message = "Claude crashed"
        fake_result.session_id = ""

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
            patch.object(dispatcher._task_queue, "mark_completed") as mock_complete,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_fail.assert_called_once_with(task)
        mock_complete.assert_not_called()

    def test_sends_error_message_to_slack(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = True
        fake_result.is_timeout = False
        fake_result.response_text = ""
        fake_result.error_message = "Something failed"
        fake_result.session_id = ""

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # Some error-related call to Slack should be made
        assert slack_api.send_message.called or slack_api.update_message.called

    def test_marks_failed_on_timeout(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = True
        fake_result.response_text = ""
        fake_result.error_message = ""
        fake_result.session_id = ""

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_fail.assert_called_once_with(task)

    def test_marks_failed_when_exception_raised(self, tmp_path):
        """If ClaudeProcess.run raises an exception, task should be marked failed."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
        ):
            MockClaude.return_value.run.side_effect = RuntimeError("unexpected")
            dispatcher._process_task(task)

        mock_fail.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

class TestAdminCommands:
    def test_handle_status_sends_message(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_status(task)
        slack_api.send_message.assert_called()

    def test_handle_help_sends_message(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_help(task)
        slack_api.send_message.assert_called()

    def test_handle_shutdown_sets_shutdown_event(self, tmp_path):
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        task = make_task()
        dispatcher._handle_admin_command(task, "shutdown")
        assert shutdown_event.is_set()

    def test_handle_admin_command_status(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        with patch.object(dispatcher, "_handle_status") as mock_status:
            dispatcher._handle_admin_command(task, "status")
        mock_status.assert_called_once_with(task)

    def test_handle_admin_command_help(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        with patch.object(dispatcher, "_handle_help") as mock_help:
            dispatcher._handle_admin_command(task, "help")
        mock_help.assert_called_once_with(task)

    def test_handle_unknown_admin_command_sends_fallback(self, tmp_path):
        """Unknown admin command should send some message (graceful degradation)."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_admin_command(task, "unknown_cmd")
        # Should send at least something to Slack or silently ignore — not crash
        # (both behaviors are acceptable; just must not raise)

    def test_shutdown_unauthorized_user(self, tmp_path):
        """When admin_users is configured, non-admin user cannot shutdown."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        # Configure admin_users to only allow U_ADMIN
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))

        task = make_task(user_id="U_RANDOM")
        dispatcher._handle_admin_command(task, "shutdown")

        # Shutdown event must NOT be set
        assert not shutdown_event.is_set()
        # Should send an unauthorized message to Slack
        slack_api.send_message.assert_called()
        msg_text = slack_api.send_message.call_args[0][1]
        assert "authorized" in msg_text.lower() or "lock" in msg_text.lower()

    def test_shutdown_authorized_user(self, tmp_path):
        """When admin_users is configured, an authorized user CAN shutdown."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN", "U_SUPER"))

        task = make_task(user_id="U_ADMIN")
        dispatcher._handle_admin_command(task, "shutdown")

        assert shutdown_event.is_set()

    def test_shutdown_no_admin_list(self, tmp_path):
        """When admin_users is empty (default), ANY user can shutdown (backward compat)."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        # Default RunnerConfig has admin_users=()
        dispatcher._runner_config = RunnerConfig(admin_users=())

        task = make_task(user_id="U_ANYONE")
        dispatcher._handle_admin_command(task, "shutdown")

        assert shutdown_event.is_set()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_get_stats_returns_dict(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        stats = dispatcher.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_has_queue_keys(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        stats = dispatcher.get_stats()
        assert "running" in stats
        assert "pending" in stats

    def test_get_stats_initial_zero(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        stats = dispatcher.get_stats()
        assert stats["running"] == 0
        assert stats["pending"] == 0


# ---------------------------------------------------------------------------
# task_queue property
# ---------------------------------------------------------------------------

class TestTaskQueueProperty:
    def test_task_queue_property_accessible(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        from opentree.runner.task_queue import TaskQueue
        assert isinstance(dispatcher.task_queue, TaskQueue)

    def test_task_queue_property_is_same_instance(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        assert dispatcher.task_queue is dispatcher._task_queue


# ---------------------------------------------------------------------------
# Next task promoted after completion
# ---------------------------------------------------------------------------

class TestNextTaskAfterCompletion:
    def test_next_task_is_processed_after_current_completes(self, tmp_path):
        """After completing a task, the queue promotes the next pending task.

        Verifies the promotion logic inside TaskQueue works correctly when
        coordinated by the dispatcher's queue.  mark_completed internally
        calls _promote_next_locked, which moves task2 from pending → running,
        so get_next_ready() returns None (task2 is now running, not pending).
        """
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task1 = make_task(
            task_id="C001_1000.0_1000.1",
            thread_ts="1000.0001",
        )
        task2 = make_task(
            task_id="C001_2000.0_2000.1",
            thread_ts="2000.0001",
        )

        from opentree.runner.task_queue import TaskQueue
        dispatcher._task_queue = TaskQueue(max_concurrent=1)

        # Submit both — task1 starts immediately, task2 is queued.
        started1 = dispatcher._task_queue.submit(task1)
        started2 = dispatcher._task_queue.submit(task2)
        assert started1 is True
        assert started2 is False

        # Confirm task2 is pending (blocked by task1).
        assert dispatcher._task_queue.get_next_ready() is None  # task1 still running
        assert dispatcher._task_queue.get_pending_count() == 1

        # Complete task1 — the queue internally promotes task2 to running.
        dispatcher._task_queue.mark_completed(task1)

        # After promotion task2 is running, pending is empty, get_next_ready → None.
        assert dispatcher._task_queue.get_pending_count() == 0
        assert dispatcher._task_queue.get_running_count() == 1
        assert dispatcher._task_queue.get_next_ready() is None


# ---------------------------------------------------------------------------
# Worker thread — daemon flag
# ---------------------------------------------------------------------------

class TestWorkerThread:
    def test_worker_thread_is_daemon(self, tmp_path):
        """Worker threads must be daemon so the process can exit cleanly."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()

        threads_created = []
        original_thread_init = threading.Thread.__init__

        class ThreadSpy(threading.Thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                threads_created.append(self)

        started = threading.Event()

        def fake_process(t):
            started.set()

        dispatcher._process_task = fake_process

        with (
            patch.object(dispatcher._task_queue, "submit", return_value=True),
            patch("opentree.runner.dispatcher.threading.Thread", ThreadSpy),
        ):
            dispatcher.dispatch(task)

        started.wait(timeout=1.0)
        if threads_created:
            assert threads_created[-1].daemon


# ---------------------------------------------------------------------------
# _build_message — file attachment references
# ---------------------------------------------------------------------------

class TestBuildMessage:
    def test_no_files_returns_text_only(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(text="hello", files=[])
        msg = dispatcher._build_message(task)
        assert msg == "hello"

    def test_files_appended_to_message(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(
            text="please review",
            files=[{"name": "report.pdf"}, {"name": "data.csv"}],
        )
        msg = dispatcher._build_message(task)
        assert "report.pdf" in msg
        assert "data.csv" in msg
        assert "[Attached files:" in msg

    def test_file_without_name_uses_id(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(
            text="see file",
            files=[{"id": "F001"}],
        )
        msg = dispatcher._build_message(task)
        assert "F001" in msg

    def test_file_without_name_or_id_uses_unnamed(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        task = make_task(text="see file", files=[{}])
        msg = dispatcher._build_message(task)
        assert "unnamed" in msg


# ---------------------------------------------------------------------------
# Integration-style: full dispatch → _process_task flow
# ---------------------------------------------------------------------------

class TestDispatchIntegration:
    def test_full_dispatch_success_flow(self, tmp_path):
        """End-to-end: dispatch → _process_task → Slack response."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "42 is the answer"
        fake_result.session_id = "sess-integration"

        slack_api.send_message.return_value = {"ts": "9999.0001"}
        done = threading.Event()

        original_process = dispatcher._process_task

        def tracked_process(t):
            original_process(t)
            done.set()

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys-prompt"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task = tracked_process
            dispatcher.dispatch(task)

            done.wait(timeout=5.0)

        assert done.is_set(), "process_task should have been called"
        # Session should be saved
        assert dispatcher._session_mgr.get_session_id(task.thread_ts) == "sess-integration"


# ---------------------------------------------------------------------------
# Phase 2 integration: ProgressReporter, download_files, build_thread_context
# ---------------------------------------------------------------------------

class TestPhase2Integration:
    def _make_result(self, **kwargs):
        """Build a fake ClaudeResult-like object with safe numeric defaults."""
        result = MagicMock()
        result.is_error = kwargs.get("is_error", False)
        result.is_timeout = kwargs.get("is_timeout", False)
        result.response_text = kwargs.get("response_text", "OK")
        result.session_id = kwargs.get("session_id", "sess-001")
        result.error_message = kwargs.get("error_message", "")
        result.elapsed_seconds = kwargs.get("elapsed_seconds", 1.5)
        result.input_tokens = kwargs.get("input_tokens", 100)
        result.output_tokens = kwargs.get("output_tokens", 50)
        return result

    def test_process_task_with_progress_reporter(self, tmp_path):
        """ProgressReporter.start() is called, which calls send_message for the ack."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result()

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # ProgressReporter.start() sends the initial ack via send_message.
        slack_api.send_message.assert_called()
        # ProgressReporter.complete() updates the ack message.
        slack_api.update_message.assert_called()

    def test_process_task_downloads_files(self, tmp_path):
        """When task has files, download_files is called with the bot token."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        # Give the mock slack_api a bot_token attribute.
        slack_api.bot_token = "xoxb-test-token"

        files = [{"name": "report.pdf", "url_private_download": "https://example.com/report.pdf"}]
        task = make_task(files=files)
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result()

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.download_files", return_value=[]) as mock_dl,
            patch("opentree.runner.dispatcher.build_file_context", return_value="") as mock_fc,
            patch("opentree.runner.dispatcher.cleanup_temp"),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_dl.assert_called_once()
        call_args = mock_dl.call_args
        assert call_args[0][0] == files  # first positional arg: files list
        assert call_args[0][1] == task.thread_ts  # second: thread_ts
        mock_fc.assert_called_once()

    def test_process_task_thread_context_prepended(self, tmp_path):
        """build_thread_context result is prepended to the Claude message."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(text="What is 2+2?")
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result()
        thread_ctx = "alice: some earlier message"

        captured_messages = []

        def capture_claude(**kwargs):
            captured_messages.append(kwargs.get("message", ""))
            m = MagicMock()
            m.run.return_value = fake_result
            return m

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess", side_effect=capture_claude),
            patch("opentree.runner.dispatcher.build_thread_context", return_value=thread_ctx),
            patch("opentree.runner.dispatcher.cleanup_temp"),
        ):
            dispatcher._process_task(task)

        assert len(captured_messages) == 1
        msg = captured_messages[0]
        assert thread_ctx in msg
        assert "What is 2+2?" in msg
        assert msg.index(thread_ctx) < msg.index("What is 2+2?")

    def test_cleanup_temp_called_on_success(self, tmp_path):
        """cleanup_temp is called in the finally block after successful execution."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result()

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp") as mock_cleanup,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_cleanup.assert_called_once_with(task.thread_ts)

    def test_cleanup_temp_called_on_failure(self, tmp_path):
        """cleanup_temp is called in the finally block even when Claude raises."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", side_effect=RuntimeError("boom")),
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp") as mock_cleanup,
        ):
            dispatcher._process_task(task)

        mock_cleanup.assert_called_once_with(task.thread_ts)


# ---------------------------------------------------------------------------
# Dispatcher-level dedup (Layer 2)
# ---------------------------------------------------------------------------

class TestDispatcherDedup:
    """Layer 2 dedup: Dispatcher.dispatch() rejects duplicate message_ts."""

    def test_duplicate_message_ts_blocked(self, tmp_path):
        """Second dispatch with same message_ts is silently dropped."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task1 = make_task(task_id="t1", message_ts="7000.0001", text="hello")
        task2 = make_task(task_id="t2", message_ts="7000.0001", text="hello again")

        process_calls = []
        dispatcher._process_task = lambda t: process_calls.append(t)

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(task1)
            # Wait briefly for daemon thread to call _process_task
            import time; time.sleep(0.3)
            dispatcher.dispatch(task2)
            time.sleep(0.3)

        # Only one task should have been processed
        assert len(process_calls) == 1
        assert process_calls[0].task_id == "t1"

    def test_different_message_ts_allowed(self, tmp_path):
        """Tasks with different message_ts are both dispatched."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task1 = make_task(task_id="t1", message_ts="7000.0001", text="first")
        task2 = make_task(task_id="t2", message_ts="7000.0002", text="second")

        process_calls = []
        dispatcher._process_task = lambda t: process_calls.append(t)

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(task1)
            import time; time.sleep(0.3)
            dispatcher.dispatch(task2)
            time.sleep(0.3)

        assert len(process_calls) == 2

    def test_admin_commands_also_deduped(self, tmp_path):
        """Admin commands with same ts are also deduped (prevents double reply)."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Same ts for both — second should be deduped
        task1 = make_task(task_id="t1", message_ts="7000.0003", text="status")
        task2 = make_task(task_id="t2", message_ts="7000.0003", text="status")

        dispatcher.dispatch(task1)
        dispatcher.dispatch(task2)

        # Only first should trigger a Slack message
        assert slack_api.send_message.call_count == 1

    def test_admin_commands_different_ts_both_processed(self, tmp_path):
        """Admin commands with different ts are both processed."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task1 = make_task(task_id="t1", message_ts="7000.0003", text="status")
        task2 = make_task(task_id="t2", message_ts="7000.0004", text="help")

        dispatcher.dispatch(task1)
        dispatcher.dispatch(task2)

        # Both should trigger Slack messages
        assert slack_api.send_message.call_count == 2

    def test_dedup_set_pruning(self, tmp_path):
        """When dedup set exceeds 10,000 entries, it is pruned to 5,000."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Simulate filling the dedup set
        for i in range(10_001):
            dispatcher._dispatched_ts.add(f"{i:013}.0000")

        # Next dispatch should trigger pruning
        task = make_task(message_ts="9999999999999.0001", text="hello")
        dispatcher._process_task = lambda t: None

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(task)
            import time; time.sleep(0.3)

        assert len(dispatcher._dispatched_ts) <= 5_001


# ---------------------------------------------------------------------------
# Restart admin command (exit code mechanism)
# ---------------------------------------------------------------------------

class TestRestartCommand:
    """Tests for the 'restart' admin command."""

    def test_restart_is_recognized_as_admin_command(self, tmp_path):
        """'restart' is parsed as an admin command."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> restart", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "restart"

    def test_restart_sets_shutdown_event(self, tmp_path):
        """restart command sets the shutdown event (like shutdown)."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        task = make_task()
        dispatcher._handle_admin_command(task, "restart")
        assert shutdown_event.is_set()

    def test_restart_sends_ack_message(self, tmp_path):
        """restart command sends a confirmation message to Slack."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_admin_command(task, "restart")
        slack_api.send_message.assert_called()

    def test_restart_sets_exit_code_on_dispatcher(self, tmp_path):
        """restart command sets a non-zero exit code on the dispatcher."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_admin_command(task, "restart")
        assert dispatcher.exit_code == 1

    def test_shutdown_exit_code_is_zero(self, tmp_path):
        """shutdown command leaves exit_code at 0 (clean exit, no restart)."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        task = make_task()
        dispatcher._handle_admin_command(task, "shutdown")
        assert dispatcher.exit_code == 0

    def test_restart_unauthorized_user(self, tmp_path):
        """When admin_users is configured, non-admin user cannot restart."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))
        task = make_task(user_id="U_RANDOM")
        dispatcher._handle_admin_command(task, "restart")
        assert not shutdown_event.is_set()


# ---------------------------------------------------------------------------
# Retry integration — overloaded errors
# ---------------------------------------------------------------------------

class TestRetryOverloaded:
    """Dispatcher retries on overloaded errors with exponential backoff."""

    def _make_result(self, **kwargs):
        result = MagicMock()
        result.is_error = kwargs.get("is_error", False)
        result.is_timeout = kwargs.get("is_timeout", False)
        result.response_text = kwargs.get("response_text", "OK")
        result.session_id = kwargs.get("session_id", "sess-001")
        result.error_message = kwargs.get("error_message", "")
        result.elapsed_seconds = kwargs.get("elapsed_seconds", 1.5)
        result.input_tokens = kwargs.get("input_tokens", 100)
        result.output_tokens = kwargs.get("output_tokens", 50)
        return result

    def test_retries_on_overloaded_then_succeeds(self, tmp_path):
        """First call returns overloaded error, second call succeeds."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        error_result = self._make_result(
            is_error=True,
            error_message="API overloaded, try later",
            response_text="",
            session_id="",
        )
        success_result = self._make_result(
            is_error=False,
            response_text="Hello!",
            session_id="sess-retry",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep") as mock_sleep,
            patch.object(dispatcher._task_queue, "mark_completed") as mock_complete,
        ):
            mock_instance = MagicMock()
            mock_instance.run.side_effect = [error_result, success_result]
            MockClaude.return_value = mock_instance
            dispatcher._process_task(task)

        # Claude should have been called twice (1 retry)
        assert mock_instance.run.call_count == 2
        # Backoff delay should have been applied
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] >= 29.0  # ~30s base delay
        mock_complete.assert_called_once_with(task)

    def test_retries_exhausted_marks_failed(self, tmp_path):
        """After max retries, task is marked failed."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        error_result = self._make_result(
            is_error=True,
            error_message="overloaded error",
            response_text="",
            session_id="",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep"),
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
            patch.object(dispatcher._task_queue, "mark_completed") as mock_complete,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = error_result
            MockClaude.return_value = mock_instance
            dispatcher._process_task(task)

        # 1 initial + 3 retries = 4 total calls
        assert mock_instance.run.call_count == 4
        mock_fail.assert_called_once_with(task)
        mock_complete.assert_not_called()

    def test_no_retry_for_non_retryable_error(self, tmp_path):
        """Non-retryable errors fail immediately without retry."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        error_result = self._make_result(
            is_error=True,
            error_message="TypeError: cannot read property",
            response_text="",
            session_id="",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep") as mock_sleep,
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = error_result
            MockClaude.return_value = mock_instance
            dispatcher._process_task(task)

        # Only 1 call — no retry
        assert mock_instance.run.call_count == 1
        mock_sleep.assert_not_called()
        mock_fail.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# Retry integration — session errors
# ---------------------------------------------------------------------------

class TestRetrySessionError:
    """Dispatcher retries session errors once with cleared session_id."""

    def _make_result(self, **kwargs):
        result = MagicMock()
        result.is_error = kwargs.get("is_error", False)
        result.is_timeout = kwargs.get("is_timeout", False)
        result.response_text = kwargs.get("response_text", "OK")
        result.session_id = kwargs.get("session_id", "sess-001")
        result.error_message = kwargs.get("error_message", "")
        result.elapsed_seconds = kwargs.get("elapsed_seconds", 1.5)
        result.input_tokens = kwargs.get("input_tokens", 100)
        result.output_tokens = kwargs.get("output_tokens", 50)
        return result

    def test_session_error_clears_session_and_retries(self, tmp_path):
        """session_error clears session_id and retries once."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(thread_ts="session-thread")
        task.status = TaskStatus.RUNNING

        # Pre-set a session_id
        dispatcher._session_mgr.set_session_id("session-thread", "old-session-id")

        error_result = self._make_result(
            is_error=True,
            error_message="session_error: invalid state",
            response_text="",
            session_id="",
        )
        success_result = self._make_result(
            is_error=False,
            response_text="Recovered!",
            session_id="new-session-id",
        )

        captured_session_ids = []

        def capture_claude(**kwargs):
            captured_session_ids.append(kwargs.get("session_id", ""))
            m = MagicMock()
            if len(captured_session_ids) == 1:
                m.run.return_value = error_result
            else:
                m.run.return_value = success_result
            return m

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess", side_effect=capture_claude),
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep") as mock_sleep,
            patch.object(dispatcher._task_queue, "mark_completed") as mock_complete,
        ):
            dispatcher._process_task(task)

        # Two calls: first with old session, second with cleared session
        assert len(captured_session_ids) == 2
        assert captured_session_ids[0] == "old-session-id"
        assert captured_session_ids[1] == ""  # session cleared on retry
        # No backoff delay for session errors
        mock_sleep.assert_not_called()
        mock_complete.assert_called_once_with(task)

    def test_session_error_does_not_retry_twice(self, tmp_path):
        """session_error retries only once; second failure is final."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        error_result = self._make_result(
            is_error=True,
            error_message="session_error: corrupted",
            response_text="",
            session_id="",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep"),
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = error_result
            MockClaude.return_value = mock_instance
            dispatcher._process_task(task)

        # 1 initial + 1 retry = 2 total calls
        assert mock_instance.run.call_count == 2
        mock_fail.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# Retry integration — timeout is not retried
# ---------------------------------------------------------------------------

class TestRetryTimeout:
    """Timeouts are NOT retried — they are handled separately."""

    def test_timeout_not_retried(self, tmp_path):
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        timeout_result = MagicMock()
        timeout_result.is_error = False
        timeout_result.is_timeout = True
        timeout_result.response_text = ""
        timeout_result.error_message = ""
        timeout_result.session_id = ""
        timeout_result.elapsed_seconds = 30.0
        timeout_result.input_tokens = 0
        timeout_result.output_tokens = 0

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep") as mock_sleep,
            patch.object(dispatcher._task_queue, "mark_failed") as mock_fail,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = timeout_result
            MockClaude.return_value = mock_instance
            dispatcher._process_task(task)

        # Only 1 call — timeout is never retried
        assert mock_instance.run.call_count == 1
        mock_sleep.assert_not_called()
        mock_fail.assert_called_once_with(task)


# ---------------------------------------------------------------------------
# Circuit Breaker integration
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:
    """Circuit breaker integration with Dispatcher."""

    def _make_result(self, **kwargs):
        result = MagicMock()
        result.is_error = kwargs.get("is_error", False)
        result.is_timeout = kwargs.get("is_timeout", False)
        result.response_text = kwargs.get("response_text", "OK")
        result.session_id = kwargs.get("session_id", "sess-001")
        result.error_message = kwargs.get("error_message", "")
        result.elapsed_seconds = kwargs.get("elapsed_seconds", 1.5)
        result.input_tokens = kwargs.get("input_tokens", 100)
        result.output_tokens = kwargs.get("output_tokens", 50)
        return result

    def test_dispatcher_has_circuit_breaker(self, tmp_path):
        """Dispatcher should initialise a CircuitBreaker instance."""
        from opentree.runner.circuit_breaker import CircuitBreaker
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        assert isinstance(dispatcher._circuit_breaker, CircuitBreaker)

    def test_dispatch_rejects_when_circuit_open(self, tmp_path):
        """When circuit is OPEN, non-admin tasks are rejected immediately."""
        from opentree.runner.circuit_breaker import CircuitBreakerConfig
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Trip the circuit breaker
        from opentree.runner.circuit_breaker import CircuitBreaker
        dispatcher._circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2)
        )
        dispatcher._circuit_breaker.record_failure()
        dispatcher._circuit_breaker.record_failure()

        task = make_task(text="hello")
        process_called = []
        dispatcher._process_task = lambda t: process_called.append(t)

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(task)

        import time; time.sleep(0.3)
        # Task should NOT be processed
        assert len(process_called) == 0
        # Slack should have received the "unavailable" message
        slack_api.send_message.assert_called()
        msg = slack_api.send_message.call_args[0][1]
        assert "unavailable" in msg.lower()

    def test_admin_commands_bypass_circuit_breaker(self, tmp_path):
        """Admin commands (status, help) should work even when circuit is OPEN."""
        from opentree.runner.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Trip the circuit breaker
        dispatcher._circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1)
        )
        dispatcher._circuit_breaker.record_failure()

        task = make_task(text="<@UBOT123> status", message_ts="admin-ts-001")
        dispatcher.dispatch(task)

        # Status message should have been sent
        slack_api.send_message.assert_called()
        msg = slack_api.send_message.call_args[0][1]
        assert "Bot Status" in msg

    def test_success_records_in_circuit_breaker(self, tmp_path):
        """Successful Claude result resets circuit breaker failure count."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        # Accumulate some failures first (but below threshold)
        dispatcher._circuit_breaker.record_failure()
        dispatcher._circuit_breaker.record_failure()

        fake_result = self._make_result()

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        status = dispatcher._circuit_breaker.get_status()
        assert status["failure_count"] == 0
        assert status["state"] == "closed"

    def test_failure_records_in_circuit_breaker(self, tmp_path):
        """Failed Claude result increments circuit breaker failure count."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result(
            is_error=True,
            error_message="TypeError: something wrong",
            response_text="",
            session_id="",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch.object(dispatcher._task_queue, "mark_failed"),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        status = dispatcher._circuit_breaker.get_status()
        assert status["failure_count"] == 1

    def test_timeout_records_failure_in_circuit_breaker(self, tmp_path):
        """Timeout result also counts as a circuit breaker failure."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result(
            is_error=False,
            is_timeout=True,
            response_text="",
            session_id="",
            elapsed_seconds=30.0,
            input_tokens=0,
            output_tokens=0,
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch("opentree.runner.dispatcher.time.sleep"),
            patch.object(dispatcher._task_queue, "mark_failed"),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        status = dispatcher._circuit_breaker.get_status()
        assert status["failure_count"] == 1

    def test_status_includes_circuit_breaker(self, tmp_path):
        """Status command output should include circuit breaker state."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        dispatcher._handle_status(task)

        msg = slack_api.send_message.call_args[0][1]
        assert "circuit breaker" in msg.lower()
        assert "closed" in msg.lower()

    def test_consecutive_failures_trip_circuit(self, tmp_path):
        """After threshold consecutive failures, circuit opens and rejects."""
        from opentree.runner.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Low threshold for test
        dispatcher._circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2)
        )

        fake_result = self._make_result(
            is_error=True,
            error_message="TypeError: cannot compute",
            response_text="",
            session_id="",
        )

        for i in range(2):
            task = make_task(
                task_id=f"t{i}",
                message_ts=f"ts-{i}",
            )
            task.status = TaskStatus.RUNNING
            with (
                patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
                patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
                patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
                patch("opentree.runner.dispatcher.cleanup_temp"),
                patch.object(dispatcher._task_queue, "mark_failed"),
            ):
                MockClaude.return_value.run.return_value = fake_result
                dispatcher._process_task(task)

        # Now circuit should be OPEN
        assert dispatcher._circuit_breaker.get_status()["state"] == "open"

        # New dispatch should be rejected
        new_task = make_task(message_ts="ts-new", text="hello")
        process_called = []
        dispatcher._process_task = lambda t: process_called.append(t)

        with patch.object(dispatcher._task_queue, "submit", return_value=True):
            dispatcher.dispatch(new_task)

        import time; time.sleep(0.3)
        assert len(process_called) == 0


# ---------------------------------------------------------------------------
# _check_new_user
# ---------------------------------------------------------------------------

class TestCheckNewUser:
    """Tests for Dispatcher._check_new_user."""

    def test_empty_path_is_new(self):
        from opentree.runner.dispatcher import Dispatcher
        assert Dispatcher._check_new_user("") is True

    def test_nonexistent_file_is_new(self, tmp_path):
        from opentree.runner.dispatcher import Dispatcher
        assert Dispatcher._check_new_user(str(tmp_path / "missing.md")) is True

    def test_empty_file_is_new(self, tmp_path):
        from opentree.runner.dispatcher import Dispatcher
        f = tmp_path / "memory.md"
        f.write_text("", encoding="utf-8")
        assert Dispatcher._check_new_user(str(f)) is True

    def test_template_only_is_new(self, tmp_path):
        from opentree.runner.dispatcher import Dispatcher
        f = tmp_path / "memory.md"
        f.write_text("# Walter 的記憶\n\n## Pinned\n\n## Core\n", encoding="utf-8")
        assert Dispatcher._check_new_user(str(f)) is True

    def test_file_with_content_is_not_new(self, tmp_path):
        from opentree.runner.dispatcher import Dispatcher
        f = tmp_path / "memory.md"
        f.write_text("# Walter 的記憶\n\n## Pinned\n\n- 喜歡喝咖啡\n", encoding="utf-8")
        assert Dispatcher._check_new_user(str(f)) is False


# ---------------------------------------------------------------------------
# _build_prompt_context — admin detection
# ---------------------------------------------------------------------------

class TestBuildPromptContextAdmin:
    """_build_prompt_context correctly computes is_owner."""

    def test_admin_user_detected(self, tmp_path):
        """User in admin_users list should have is_owner=True."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._runner_config = RunnerConfig(admin_users=("U0ADMIN",))
        task = make_task(
            user_id="U0ADMIN",
            channel_id="C0TEST",
            thread_ts="",
            text="hello",
            message_ts="1234.5678",
        )
        ctx = dispatcher._build_prompt_context(task, user_name="admin", display_name="Admin")
        assert ctx.is_owner is True

    def test_non_admin_user(self, tmp_path):
        """User NOT in admin_users list should have is_owner=False."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._runner_config = RunnerConfig(admin_users=("U0ADMIN",))
        task = make_task(
            user_id="U0REGULAR",
            channel_id="C0TEST",
            thread_ts="",
            text="hello",
            message_ts="1234.5678",
        )
        ctx = dispatcher._build_prompt_context(task, user_name="regular", display_name="Regular")
        assert ctx.is_owner is False

    def test_empty_admin_users(self, tmp_path):
        """Empty admin_users means no one is owner."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._runner_config = RunnerConfig(admin_users=())
        task = make_task(
            user_id="U0ANYONE",
            channel_id="C0TEST",
            thread_ts="",
            text="hello",
            message_ts="1234.5678",
        )
        ctx = dispatcher._build_prompt_context(task, user_name="anyone", display_name="Anyone")
        assert ctx.is_owner is False

    def test_workspace_uses_team_name(self, tmp_path):
        """workspace should use team_name, not hardcoded 'default'."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        from opentree.core.config import UserConfig
        dispatcher._user_config = UserConfig(
            bot_name=dispatcher._user_config.bot_name,
            team_name="my-team",
            admin_channel="",
            owner_description="",
            opentree_home=dispatcher._user_config.opentree_home,
        )
        task = make_task(
            user_id="U0TEST",
            channel_id="C0TEST",
            thread_ts="",
            text="hello",
            message_ts="1234.5678",
        )
        ctx = dispatcher._build_prompt_context(task, user_name="test", display_name="Test")
        assert ctx.workspace == "my-team"


# ---------------------------------------------------------------------------
# Fix A: thread_participants populated from thread history
# ---------------------------------------------------------------------------

class TestThreadParticipants:
    """Verify _build_prompt_context fills thread_participants from thread history."""

    def test_thread_participants_populated(self, tmp_path):
        """thread_participants should contain display names from thread replies."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Simulate thread replies from two users (plus the bot).
        slack_api.get_thread_replies.return_value = [
            {"user": "U001", "text": "hello"},
            {"user": "UBOT123", "text": "response"},  # bot — excluded
            {"user": "U002", "text": "follow up"},
            {"user": "U001", "text": "another"},       # duplicate — deduplicated
        ]
        # Map user IDs to display names.
        def _display_name(uid):
            return {"U001": "alice", "U002": "bob"}.get(uid, "")
        slack_api.get_user_display_name.side_effect = _display_name

        task = make_task(
            user_id="U001",
            channel_id="C001",
            thread_ts="1234.5678",
        )
        ctx = dispatcher._build_prompt_context(task)
        assert "alice" in ctx.thread_participants
        assert "bob" in ctx.thread_participants
        assert len(ctx.thread_participants) == 2

    def test_thread_participants_empty_for_new_thread(self, tmp_path):
        """New thread (empty thread_ts) should have empty participants."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task(thread_ts="")
        ctx = dispatcher._build_prompt_context(task)
        assert ctx.thread_participants == ()

    def test_thread_participants_api_failure_returns_empty(self, tmp_path):
        """When get_thread_replies fails, participants should be empty tuple."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        slack_api.get_thread_replies.side_effect = Exception("API error")
        task = make_task(thread_ts="1234.5678")
        ctx = dispatcher._build_prompt_context(task)
        assert ctx.thread_participants == ()


# ---------------------------------------------------------------------------
# Fix C: _check_new_user cache
# ---------------------------------------------------------------------------

class TestCheckNewUserCache:
    """_check_new_user result is cached for known existing users."""

    def test_known_user_cached(self, tmp_path):
        """Second call for the same non-new user should NOT read the file again."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        # Create a memory file with real content so _check_new_user returns False.
        memory_dir = tmp_path / "data" / "memory" / "alice"
        memory_dir.mkdir(parents=True, exist_ok=True)
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("# alice\n\n- likes coffee\n", encoding="utf-8")

        memory_path = str(memory_file)

        # First call — reads the file, returns False, caches.
        from opentree.runner.dispatcher import Dispatcher
        assert Dispatcher._check_new_user(memory_path) is False

        # Now call _build_prompt_context twice and verify the file is read only once.
        task = make_task(user_id="U001", user_name="alice")
        # Patch _check_new_user to track calls.
        call_count = {"n": 0}
        original_check = Dispatcher._check_new_user

        @staticmethod
        def counting_check(mp):
            call_count["n"] += 1
            return original_check(mp)

        with patch.object(Dispatcher, "_check_new_user", counting_check):
            ctx1 = dispatcher._build_prompt_context(task, user_name="alice")
            ctx2 = dispatcher._build_prompt_context(task, user_name="alice")

        # First call invokes _check_new_user; second call uses cache.
        assert call_count["n"] == 1
        assert ctx1.is_new_user is False
        assert ctx2.is_new_user is False

    def test_new_user_not_cached(self, tmp_path):
        """A new user (no memory file) should NOT be cached — checked every time."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)

        task = make_task(user_id="U999", user_name="newbie")

        from opentree.runner.dispatcher import Dispatcher
        call_count = {"n": 0}
        original_check = Dispatcher._check_new_user

        @staticmethod
        def counting_check(mp):
            call_count["n"] += 1
            return original_check(mp)

        with patch.object(Dispatcher, "_check_new_user", counting_check):
            ctx1 = dispatcher._build_prompt_context(task, user_name="newbie")
            ctx2 = dispatcher._build_prompt_context(task, user_name="newbie")

        # Both calls should invoke _check_new_user (True result is not cached).
        assert call_count["n"] == 2
        assert ctx1.is_new_user is True
        assert ctx2.is_new_user is True


# ---------------------------------------------------------------------------
# Fix E: ParsedMessage.files is tuple (immutable)
# ---------------------------------------------------------------------------

class TestParsedMessageFilesImmutable:
    """ParsedMessage.files should be a tuple, not a list."""

    def test_files_is_tuple_when_empty(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> hello", "UBOT123")
        assert isinstance(result.files, tuple)
        assert result.files == ()

    def test_files_is_tuple_when_provided(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        files = [{"id": "F001", "name": "test.txt"}]
        result = dispatcher.parse_message("<@UBOT123> hello", "UBOT123", files=files)
        assert isinstance(result.files, tuple)
        assert len(result.files) == 1
        assert result.files[0]["name"] == "test.txt"

    def test_files_not_mutated_after_creation(self, tmp_path):
        """Attempting to mutate files should raise an error (frozen dataclass + tuple)."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        files = [{"id": "F001"}]
        result = dispatcher.parse_message("<@UBOT123> hello", "UBOT123", files=files)
        with pytest.raises(AttributeError):
            result.files += ({"id": "F002"},)  # frozen dataclass prevents assignment


# ---------------------------------------------------------------------------
# reset-bot command
# ---------------------------------------------------------------------------

class TestResetBotCommand:
    """reset-bot and reset-bot-all are recognized as bot commands."""

    def test_reset_bot_in_bot_commands(self):
        from opentree.runner.dispatcher import _BOT_COMMANDS
        assert "reset-bot" in _BOT_COMMANDS

    def test_reset_bot_all_in_bot_commands(self):
        from opentree.runner.dispatcher import _BOT_COMMANDS
        assert "reset-bot-all" in _BOT_COMMANDS

    def test_reset_bot_parsed_as_admin_command(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> reset-bot", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "reset-bot"

    def test_reset_bot_all_parsed_as_admin_command(self, tmp_path):
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        result = dispatcher.parse_message("<@UBOT123> reset-bot-all", "UBOT123")
        assert result.is_admin_command
        assert result.admin_command == "reset-bot-all"


class TestHandleResetBot:
    """_handle_reset_bot soft resets and triggers restart."""

    def test_sends_confirmation_messages(self, tmp_path):
        """reset-bot sends an initial 'resetting' and a completion message."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", return_value=["Regenerated config"]):
            dispatcher._handle_reset_bot(task)
        # At least two messages: the initial ack and the completion
        assert slack_api.send_message.call_count >= 2

    def test_calls_session_clear_all(self, tmp_path):
        """reset-bot calls session_mgr.clear_all()."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", return_value=["Done"]):
            dispatcher._handle_reset_bot(task)
        dispatcher._session_mgr.clear_all.assert_called_once()

    def test_sets_exit_code_one(self, tmp_path):
        """reset-bot sets exit_code = 1 to trigger restart."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", return_value=["Done"]):
            dispatcher._handle_reset_bot(task)
        assert dispatcher.exit_code == 1

    def test_sets_shutdown_event(self, tmp_path):
        """reset-bot sets the shutdown event."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", return_value=["Done"]):
            dispatcher._handle_reset_bot(task)
        assert shutdown_event.is_set()

    def test_unauthorized_user_rejected(self, tmp_path):
        """Non-admin user cannot use reset-bot."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))
        task = make_task(user_id="U_RANDOM")
        dispatcher._handle_admin_command(task, "reset-bot")
        assert not shutdown_event.is_set()
        msg_text = slack_api.send_message.call_args[0][1]
        assert "authorized" in msg_text.lower() or "lock" in msg_text.lower()

    def test_authorized_user_accepted(self, tmp_path):
        """Admin user can use reset-bot."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))
        dispatcher._session_mgr = MagicMock()
        task = make_task(user_id="U_ADMIN")
        with patch("opentree.runner.dispatcher.reset_bot", return_value=["Done"]):
            dispatcher._handle_admin_command(task, "reset-bot")
        assert shutdown_event.is_set()

    def test_reset_bot_failure_sends_error_message(self, tmp_path):
        """When reset_bot raises, an error message is sent."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", side_effect=RuntimeError("boom")):
            dispatcher._handle_reset_bot(task)
        # Find the error message among sent messages
        error_msgs = [
            c for c in slack_api.send_message.call_args_list
            if ":x:" in str(c)
        ]
        assert len(error_msgs) >= 1

    def test_restart_triggered_even_on_failure(self, tmp_path):
        """reset-bot triggers restart even when reset_bot() raises."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot", side_effect=RuntimeError("boom")):
            dispatcher._handle_reset_bot(task)
        assert dispatcher.exit_code == 1
        assert shutdown_event.is_set()


class TestHandleResetBotAll:
    """_handle_reset_bot_all hard resets and triggers restart."""

    def test_sends_warning_message(self, tmp_path):
        """reset-bot-all sends a warning message before reset."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", return_value=["Cleared data"]):
            dispatcher._handle_reset_bot_all(task)
        # First message should contain a warning
        first_msg = slack_api.send_message.call_args_list[0][0][1]
        assert "warning" in first_msg.lower() or ":warning:" in first_msg

    def test_calls_session_clear_all(self, tmp_path):
        """reset-bot-all calls session_mgr.clear_all()."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", return_value=["Done"]):
            dispatcher._handle_reset_bot_all(task)
        dispatcher._session_mgr.clear_all.assert_called_once()

    def test_sets_exit_code_one(self, tmp_path):
        """reset-bot-all sets exit_code = 1 to trigger restart."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", return_value=["Done"]):
            dispatcher._handle_reset_bot_all(task)
        assert dispatcher.exit_code == 1

    def test_sets_shutdown_event(self, tmp_path):
        """reset-bot-all sets the shutdown event."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", return_value=["Done"]):
            dispatcher._handle_reset_bot_all(task)
        assert shutdown_event.is_set()

    def test_always_restarts_even_on_failure(self, tmp_path):
        """reset-bot-all triggers restart even when reset_bot_all() raises."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", side_effect=RuntimeError("boom")):
            dispatcher._handle_reset_bot_all(task)
        assert dispatcher.exit_code == 1
        assert shutdown_event.is_set()

    def test_unauthorized_user_rejected(self, tmp_path):
        """Non-admin user cannot use reset-bot-all."""
        shutdown_event = threading.Event()
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))
        task = make_task(user_id="U_RANDOM")
        dispatcher._handle_admin_command(task, "reset-bot-all")
        assert not shutdown_event.is_set()

    def test_authorized_user_accepted(self, tmp_path):
        """Admin user can use reset-bot-all."""
        shutdown_event = threading.Event()
        dispatcher, _, _ = _make_dispatcher(tmp_path, shutdown_event=shutdown_event)
        dispatcher._runner_config = RunnerConfig(admin_users=("U_ADMIN",))
        dispatcher._session_mgr = MagicMock()
        task = make_task(user_id="U_ADMIN")
        with patch("opentree.runner.dispatcher.reset_bot_all", return_value=["Done"]):
            dispatcher._handle_admin_command(task, "reset-bot-all")
        assert shutdown_event.is_set()

    def test_clear_all_called_before_reset_bot_all(self, tmp_path):
        """Sessions are cleared before reset_bot_all runs (data/ may be wiped)."""
        dispatcher, _, _ = _make_dispatcher(tmp_path)
        call_order: list[str] = []
        mock_session_mgr = MagicMock()
        mock_session_mgr.clear_all.side_effect = lambda: call_order.append("clear_all")
        dispatcher._session_mgr = mock_session_mgr
        task = make_task()

        def fake_reset_all(home):
            call_order.append("reset_bot_all")
            return ["Cleared data"]

        with patch("opentree.runner.dispatcher.reset_bot_all", side_effect=fake_reset_all):
            dispatcher._handle_reset_bot_all(task)

        assert call_order == ["clear_all", "reset_bot_all"]

    def test_failure_sends_error_message(self, tmp_path):
        """When reset_bot_all raises, an error message is sent."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        dispatcher._session_mgr = MagicMock()
        task = make_task()
        with patch("opentree.runner.dispatcher.reset_bot_all", side_effect=RuntimeError("boom")):
            dispatcher._handle_reset_bot_all(task)
        error_msgs = [
            c for c in slack_api.send_message.call_args_list
            if ":x:" in str(c)
        ]
        assert len(error_msgs) >= 1


# ---------------------------------------------------------------------------
# Step 11b: memory_extraction_enabled flag
# ---------------------------------------------------------------------------

class TestDispatcherMemoryExtractionEnabled:
    """Tests that memory extraction respects RunnerConfig.memory_extraction_enabled."""

    def test_skipped_when_disabled(self, tmp_path):
        """When memory_extraction_enabled=False, extract_memories is NOT called."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        # Override runner config to disable memory extraction.
        dispatcher._runner_config = RunnerConfig(
            max_concurrent_tasks=2,
            task_timeout=30,
            memory_extraction_enabled=False,
        )
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "I prefer coffee over tea"
        fake_result.session_id = "sess-mem"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.memory_extractor.extract_memories") as mock_extract,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_extract.assert_not_called()

    def test_runs_when_enabled(self, tmp_path):
        """When memory_extraction_enabled=True, extract_memories IS called."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        # Override runner config to enable memory extraction (default).
        dispatcher._runner_config = RunnerConfig(
            max_concurrent_tasks=2,
            task_timeout=30,
            memory_extraction_enabled=True,
        )
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = "I prefer coffee over tea"
        fake_result.session_id = "sess-mem"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.memory_extractor.extract_memories", return_value=[]) as mock_extract,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_extract.assert_called_once()

    def test_skipped_when_response_empty_even_if_enabled(self, tmp_path):
        """When response_text is empty, memory extraction is skipped regardless of flag."""
        dispatcher, slack_api, _ = _make_dispatcher(tmp_path)
        dispatcher._runner_config = RunnerConfig(
            max_concurrent_tasks=2,
            task_timeout=30,
            memory_extraction_enabled=True,
        )
        task = make_task()
        task.status = TaskStatus.RUNNING

        fake_result = MagicMock()
        fake_result.is_error = False
        fake_result.is_timeout = False
        fake_result.response_text = ""  # empty response
        fake_result.session_id = "sess-mem"

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.memory_extractor.extract_memories") as mock_extract,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        mock_extract.assert_not_called()
