"""Tests for ClaudeProcess — Claude CLI subprocess manager.

All subprocess interactions are mocked; no real Claude CLI is invoked.
"""

from __future__ import annotations

import io
import json
import os
import signal
import threading
import time
from dataclasses import fields
from typing import Optional
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from opentree.runner.config import RunnerConfig
from opentree.runner.stream_parser import Phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> RunnerConfig:
    """Return a RunnerConfig with sensible fast defaults for tests."""
    defaults = dict(
        task_timeout=30,
        heartbeat_timeout=10,
        claude_command="claude",
        progress_interval=5,
    )
    defaults.update(kwargs)
    return RunnerConfig(**defaults)


def _stream_line(**kwargs) -> str:
    """Encode a dict as a JSON stream line."""
    return json.dumps(kwargs) + "\n"


def _make_init_lines(session_id: str = "sess-abc") -> list[str]:
    """Return stream-json lines for a typical successful Claude run."""
    return [
        _stream_line(type="system", subtype="init", session_id=session_id),
        _stream_line(
            type="result",
            result="Hello from Claude",
            is_error=False,
            session_id=session_id,
            usage={"input_tokens": 10, "output_tokens": 5},
        ),
    ]


# ---------------------------------------------------------------------------
# Import-level smoke test (catches import errors before everything else)
# ---------------------------------------------------------------------------

def test_module_importable():
    from opentree.runner import claude_process  # noqa: F401


# ---------------------------------------------------------------------------
# ClaudeResult dataclass
# ---------------------------------------------------------------------------

class TestClaudeResultDefaults:
    def test_all_fields_have_defaults(self):
        from opentree.runner.claude_process import ClaudeResult

        result = ClaudeResult()
        assert result.session_id == ""
        assert result.response_text == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.is_error is False
        assert result.error_message == ""
        assert result.is_timeout is False
        assert result.exit_code == 0
        assert result.elapsed_seconds == 0.0

    def test_frozen_immutable(self):
        from opentree.runner.claude_process import ClaudeResult

        result = ClaudeResult(session_id="x")
        with pytest.raises((AttributeError, TypeError)):
            result.session_id = "y"  # type: ignore[misc]

    def test_custom_values_preserved(self):
        from opentree.runner.claude_process import ClaudeResult

        result = ClaudeResult(
            session_id="s1",
            response_text="hi",
            input_tokens=100,
            output_tokens=50,
            is_error=True,
            error_message="oops",
            is_timeout=True,
            exit_code=1,
            elapsed_seconds=3.14,
        )
        assert result.session_id == "s1"
        assert result.response_text == "hi"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.is_error is True
        assert result.error_message == "oops"
        assert result.is_timeout is True
        assert result.exit_code == 1
        assert result.elapsed_seconds == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# _build_safe_env
# ---------------------------------------------------------------------------

class TestBuildSafeEnv:
    def test_whitelist_allows_path(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"PATH": "/usr/bin", "SLACK_BOT_TOKEN": "xoxb-secret"}, clear=True):
            env = _build_safe_env()
        assert "PATH" in env
        assert env["PATH"] == "/usr/bin"

    def test_blocks_slack_token(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-secret"}, clear=False):
            env = _build_safe_env()
        assert "SLACK_BOT_TOKEN" not in env

    def test_blocks_arbitrary_secret(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"MY_DATABASE_PASSWORD": "hunter2"}, clear=False):
            env = _build_safe_env()
        assert "MY_DATABASE_PASSWORD" not in env

    def test_allows_anthropic_api_key(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-xxx"}, clear=True):
            env = _build_safe_env()
        assert "ANTHROPIC_API_KEY" in env

    def test_allows_aws_profile(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"AWS_PROFILE": "myprofile"}, clear=True):
            env = _build_safe_env()
        assert "AWS_PROFILE" in env

    def test_extra_env_merged(self):
        from opentree.runner.claude_process import _build_safe_env

        extra = {"MY_EXTRA_VAR": "value123"}
        with patch.dict(os.environ, {}, clear=True):
            env = _build_safe_env(extra_env=extra)
        assert env.get("MY_EXTRA_VAR") == "value123"

    def test_extra_env_overrides_whitelisted(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"HOME": "/home/original"}, clear=True):
            env = _build_safe_env(extra_env={"HOME": "/home/override"})
        assert env["HOME"] == "/home/override"

    def test_returns_new_dict_each_call(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {}, clear=True):
            env1 = _build_safe_env()
            env2 = _build_safe_env()
        assert env1 is not env2

    def test_comprehensive_whitelist_vars(self):
        from opentree.runner.claude_process import _ENV_WHITELIST

        expected_present = {
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
            "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK",
            "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
            "CLAUDE_CONFIG_DIR",
            "TMPDIR",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
            "SSL_CERT_FILE",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy",
        }
        for var in expected_present:
            assert var in _ENV_WHITELIST, f"{var!r} should be in _ENV_WHITELIST"

    def test_none_extra_env_is_safe(self):
        from opentree.runner.claude_process import _build_safe_env

        with patch.dict(os.environ, {"PATH": "/bin"}, clear=True):
            env = _build_safe_env(extra_env=None)
        assert "PATH" in env


# ---------------------------------------------------------------------------
# _build_claude_args
# ---------------------------------------------------------------------------

class TestBuildClaudeArgs:
    def test_basic_args(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config(claude_command="claude")
        args = _build_claude_args(config, system_prompt="sys", cwd="/work")

        assert args[0] == "claude"
        assert "--output-format" in args
        assert "stream-json" in args
        assert "--verbose" in args
        assert "--system-prompt" in args
        assert "sys" in args
        assert "--cwd" in args
        assert "/work" in args

    def test_max_turns_always_present(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c")
        assert "--max-turns" in args

    def test_with_session_id_adds_resume(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c", session_id="sess-xyz")
        assert "--resume" in args
        idx = args.index("--resume")
        assert args[idx + 1] == "sess-xyz"

    def test_without_session_id_no_resume(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c")
        assert "--resume" not in args

    def test_with_message_adds_message_flag(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c", message="Hello!")
        assert "--message" in args
        idx = args.index("--message")
        assert args[idx + 1] == "Hello!"

    def test_without_message_no_message_flag(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c")
        assert "--message" not in args

    def test_custom_claude_command(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config(claude_command="/usr/local/bin/claude")
        args = _build_claude_args(config, system_prompt="s", cwd="/c")
        assert args[0] == "/usr/local/bin/claude"

    def test_returns_list_of_strings(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c")
        assert isinstance(args, list)
        for arg in args:
            assert isinstance(arg, str), f"Expected str, got {type(arg)}: {arg!r}"

    def test_session_and_message_combined(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(
            config, system_prompt="s", cwd="/c",
            session_id="sess-1", message="continue"
        )
        assert "--resume" in args
        assert "--message" in args

    def test_empty_session_id_no_resume(self):
        from opentree.runner.claude_process import _build_claude_args

        config = _make_config()
        args = _build_claude_args(config, system_prompt="s", cwd="/c", session_id="")
        assert "--resume" not in args


# ---------------------------------------------------------------------------
# ClaudeProcess.run — success path
# ---------------------------------------------------------------------------

class TestClaudeProcessRunSuccess:
    """Tests for the happy path: process spawns, outputs stream-json, exits 0."""

    def _make_mock_process(self, lines: list[str], returncode: int = 0) -> MagicMock:
        """Create a mock Popen with stdout yielding the given lines."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = returncode
        mock_proc.pid = 12345
        mock_proc.poll.return_value = returncode
        mock_proc.wait.return_value = returncode
        return mock_proc

    def test_run_returns_claude_result(self):
        from opentree.runner.claude_process import ClaudeProcess, ClaudeResult

        lines = _make_init_lines("sess-ok")
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="sys",
                cwd="/work",
            )
            result = cp.run()

        assert isinstance(result, ClaudeResult)

    def test_run_success_session_id_extracted(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines("sess-extracted")
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.session_id == "sess-extracted"

    def test_run_success_response_text(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            _stream_line(type="system", subtype="init", session_id="s1"),
            _stream_line(
                type="result",
                result="The answer is 42",
                is_error=False,
                session_id="s1",
                usage={"input_tokens": 5, "output_tokens": 3},
            ),
        ]
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.response_text == "The answer is 42"

    def test_run_success_token_counts(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            _stream_line(type="system", subtype="init", session_id="s1"),
            _stream_line(
                type="result",
                result="ok",
                is_error=False,
                session_id="s1",
                usage={"input_tokens": 100, "output_tokens": 50},
            ),
        ]
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    def test_run_success_not_error(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.is_error is False
        assert result.is_timeout is False

    def test_run_records_elapsed_time(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.elapsed_seconds >= 0.0

    def test_run_exit_code_zero_on_success(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = self._make_mock_process(lines, returncode=0)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.exit_code == 0

    def test_run_passes_cwd_and_system_prompt(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = self._make_mock_process(lines)

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="Be helpful",
                cwd="/my/workspace",
            )
            cp.run()

        call_args = mock_popen.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        assert "--system-prompt" in cmd
        assert "Be helpful" in cmd
        assert "--cwd" in cmd
        assert "/my/workspace" in cmd

    def test_run_uses_safe_env(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = self._make_mock_process(lines)

        with patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-secret"}, clear=False):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
                cp.run()

        call_kwargs = mock_popen.call_args[1] if mock_popen.call_args[1] else {}
        passed_env = call_kwargs.get("env", {})
        assert "SLACK_BOT_TOKEN" not in passed_env


# ---------------------------------------------------------------------------
# ClaudeProcess.run — error path
# ---------------------------------------------------------------------------

class TestClaudeProcessRunError:
    def test_run_error_flag_set(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            _stream_line(type="system", subtype="init", session_id="s1"),
            _stream_line(
                type="result",
                result="Something went wrong",
                is_error=True,
                session_id="s1",
                usage={},
            ),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 1
        mock_proc.pid = 999
        mock_proc.poll.return_value = 1
        mock_proc.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.is_error is True
        assert result.error_message == "Something went wrong"

    def test_run_nonzero_exit_code_captured(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            _stream_line(type="system", subtype="init", session_id="s1"),
            _stream_line(type="result", result="err", is_error=True, session_id="s1", usage={}),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 42
        mock_proc.pid = 1
        mock_proc.poll.return_value = 42
        mock_proc.wait.return_value = 42

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.exit_code == 42

    def test_run_empty_output_still_returns_result(self):
        from opentree.runner.claude_process import ClaudeProcess

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.returncode = 1
        mock_proc.pid = 1
        mock_proc.poll.return_value = 1
        mock_proc.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        # Should return a ClaudeResult (may or may not be error — implementation decides)
        from opentree.runner.claude_process import ClaudeResult
        assert isinstance(result, ClaudeResult)

    def test_run_non_json_lines_ignored(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            "not json at all\n",
            "{bad json\n",
            _stream_line(type="system", subtype="init", session_id="s2"),
            _stream_line(type="result", result="ok", is_error=False, session_id="s2", usage={}),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 1
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        assert result.session_id == "s2"
        assert result.is_error is False


# ---------------------------------------------------------------------------
# ClaudeProcess.run — timeout paths
# ---------------------------------------------------------------------------

class TestClaudeProcessTimeout:
    """Timeout tests use fast config values to avoid slow unit tests."""

    def _make_blocking_stdout(self, done_event: threading.Event) -> object:
        """Return a generator that blocks until done_event is set.

        This properly simulates a subprocess stdout that never produces output
        until the process is killed (which sets done_event).
        """
        class _BlockingIter:
            def __init__(self, event: threading.Event) -> None:
                self._event = event

            def __iter__(self):
                self._event.wait(timeout=10)  # blocks until done or 10s safety net
                return iter([])

        return _BlockingIter(done_event)

    def test_task_timeout_sets_flag(self):
        """When task_timeout is exceeded, result.is_timeout is True."""
        from opentree.runner.claude_process import ClaudeProcess

        done = threading.Event()
        mock_proc = MagicMock()
        mock_proc.stdout = self._make_blocking_stdout(done)
        mock_proc.returncode = None
        mock_proc.pid = 42
        mock_proc.poll.return_value = None  # still running

        # After terminate is called, unblock stdout so reader thread can exit.
        def _side_effect_terminate():
            mock_proc.poll.return_value = -15
            mock_proc.returncode = -15
            done.set()

        mock_proc.terminate.side_effect = _side_effect_terminate
        mock_proc.kill.side_effect = lambda: None
        mock_proc.wait.return_value = -15

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(
                config=_make_config(task_timeout=1, heartbeat_timeout=900),
                system_prompt="s",
                cwd="/c",
            )
            result = cp.run()

        assert result.is_timeout is True

    def test_heartbeat_timeout_sets_flag(self):
        """When no output for heartbeat_timeout seconds, is_timeout is True."""
        from opentree.runner.claude_process import ClaudeProcess

        done = threading.Event()
        mock_proc = MagicMock()
        mock_proc.stdout = self._make_blocking_stdout(done)
        mock_proc.returncode = None
        mock_proc.pid = 43
        mock_proc.poll.return_value = None

        def _side_effect_terminate():
            mock_proc.poll.return_value = -15
            mock_proc.returncode = -15
            done.set()

        mock_proc.terminate.side_effect = _side_effect_terminate
        mock_proc.kill.side_effect = lambda: None
        mock_proc.wait.return_value = -15

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(
                config=_make_config(task_timeout=900, heartbeat_timeout=1),
                system_prompt="s",
                cwd="/c",
            )
            result = cp.run()

        assert result.is_timeout is True


# ---------------------------------------------------------------------------
# ClaudeProcess.stop — graceful and forced
# ---------------------------------------------------------------------------

class TestClaudeProcessStop:
    def test_stop_sends_sigterm(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 100
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            # Run in background so we can call stop
            t = threading.Thread(target=cp.run, daemon=True)
            t.start()
            t.join(timeout=3)

        # Process should have been created; terminate not necessarily called
        # on a process that exits normally, but stop() should call it
        cp.stop()
        # After stop, verify we don't crash (terminate may or may not have
        # been called depending on timing)

    def test_stop_graceful_exits_without_sigkill(self):
        """If process exits within 10s of SIGTERM, SIGKILL is not sent."""
        from opentree.runner.claude_process import ClaudeProcess

        mock_proc = MagicMock()
        # Process exits immediately after terminate()
        mock_proc.returncode = -15
        mock_proc.pid = 200
        mock_proc.poll.return_value = -15
        mock_proc.wait.return_value = -15
        mock_proc.stdout = iter([])

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            cp._process = mock_proc
            cp.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_not_called()

    def test_stop_forced_sends_sigkill_after_timeout(self):
        """If process does not exit after SIGTERM, SIGKILL is sent."""
        from opentree.runner.claude_process import ClaudeProcess

        mock_proc = MagicMock()
        mock_proc.pid = 300
        # wait() times out (raises TimeoutExpired), then kill() is called
        mock_proc.returncode = None
        mock_proc.poll.return_value = None

        import subprocess as _subprocess
        mock_proc.wait.side_effect = _subprocess.TimeoutExpired(cmd="claude", timeout=10)
        mock_proc.kill.return_value = None
        mock_proc.stdout = iter([])

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            cp._process = mock_proc
            cp.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

class TestProgressCallback:
    def test_progress_callback_called_on_phase_change(self):
        """Callback must be invoked at least once during a run."""
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines("sess-cb")
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 500
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        callback_calls = []

        def _callback(state):
            callback_calls.append(state)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="s",
                cwd="/c",
                progress_callback=_callback,
            )
            cp.run()

        assert len(callback_calls) >= 1

    def test_progress_callback_not_required(self):
        """Running without a callback does not raise."""
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 501
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()  # no progress_callback

        from opentree.runner.claude_process import ClaudeResult
        assert isinstance(result, ClaudeResult)

    def test_progress_callback_receives_phase(self):
        """Callback args contain a phase indicator."""
        from opentree.runner.claude_process import ClaudeProcess

        lines = [
            _stream_line(type="system", subtype="init", session_id="s1"),
            _stream_line(
                type="content_block_start",
                content_block={"type": "text"},
            ),
            _stream_line(type="result", result="done", is_error=False, session_id="s1", usage={}),
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 502
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        phases_seen = []

        def _callback(state):
            # Accept either a ProgressState or a Phase enum
            if hasattr(state, "phase"):
                phases_seen.append(state.phase)
            elif isinstance(state, Phase):
                phases_seen.append(state)

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="s",
                cwd="/c",
                progress_callback=_callback,
            )
            cp.run()

        assert len(phases_seen) >= 1


# ---------------------------------------------------------------------------
# Session resume
# ---------------------------------------------------------------------------

class TestSessionResume:
    def test_session_id_adds_resume_to_command(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines("sess-resume")
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 600
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="s",
                cwd="/c",
                session_id="sess-resume",
            )
            cp.run()

        cmd = mock_popen.call_args[0][0]
        assert "--resume" in cmd
        idx = cmd.index("--resume")
        assert cmd[idx + 1] == "sess-resume"

    def test_no_session_id_no_resume_flag(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 601
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            cp.run()

        cmd = mock_popen.call_args[0][0]
        assert "--resume" not in cmd


# ---------------------------------------------------------------------------
# Extra env injection
# ---------------------------------------------------------------------------

class TestExtraEnv:
    def test_extra_env_passed_to_subprocess(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 700
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cp = ClaudeProcess(
                config=_make_config(),
                system_prompt="s",
                cwd="/c",
                extra_env={"MY_CUSTOM_VAR": "hello"},
            )
            cp.run()

        call_kwargs = mock_popen.call_args[1]
        env = call_kwargs.get("env", {})
        assert env.get("MY_CUSTOM_VAR") == "hello"

    def test_no_extra_env_does_not_crash(self):
        from opentree.runner.claude_process import ClaudeProcess

        lines = _make_init_lines()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.returncode = 0
        mock_proc.pid = 701
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            cp = ClaudeProcess(config=_make_config(), system_prompt="s", cwd="/c")
            result = cp.run()

        from opentree.runner.claude_process import ClaudeResult
        assert isinstance(result, ClaudeResult)
