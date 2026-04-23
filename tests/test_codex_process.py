"""Tests for CodexProcess error-handling logic (no subprocess spawned)."""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from opentree.runner.codex_process import CodexProcess
from opentree.runner.codex_stream_parser import ProgressState, StreamParser
from opentree.runner.config import RunnerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config() -> RunnerConfig:
    """Return a minimal RunnerConfig suitable for unit tests."""
    return RunnerConfig(
        codex_command="codex",
        task_timeout=300,
        heartbeat_timeout=60,
    )


def _make_process(exit_code: int, stdout_lines: list[str] | None = None) -> MagicMock:
    """Build a mock subprocess.Popen that returns *exit_code* and emits *stdout_lines*."""
    stdout_lines = stdout_lines or []
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.pid = 99999
    mock_proc.stdout = iter(stdout_lines)
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = ""
    mock_proc.wait.return_value = exit_code
    return mock_proc


def _make_codex_process(config: RunnerConfig | None = None) -> CodexProcess:
    """Instantiate a CodexProcess with minimal arguments."""
    if config is None:
        config = _make_config()
    return CodexProcess(
        config=config,
        system_prompt="test system prompt",
        cwd="/tmp",
        message="test message",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoResultEventSetsIsError:
    """CodexProcess.run() must mark the result as an error when Codex exits
    without emitting a turn.completed event (has_result_event=False)."""

    def test_no_result_event_exit_one_sets_is_error(self) -> None:
        """has_result_event=False + exit_code=1 → is_error=True."""
        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=1, stdout_lines=[])

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is True
        assert result.exit_code == 1
        assert "Codex CLI exited without completing the turn" in result.error_message
        assert "exit_code=1" in result.error_message

    def test_no_result_event_exit_zero_sets_is_error(self) -> None:
        """has_result_event=False + exit_code=0 → is_error=True.

        Even a clean exit is an error if no turn.completed was received,
        because the user would get a silent success with no response.
        """
        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=0, stdout_lines=[])

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is True
        assert "Codex CLI exited without completing the turn" in result.error_message

    def test_no_result_event_preserves_existing_parser_error_message(self) -> None:
        """When the parser already flagged is_error=True, don't overwrite it."""
        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=1, stdout_lines=[])

        # Pre-seed the parser state with an existing error from stream parsing.
        cp._parser.state.is_error = True
        cp._parser.state.error_message = "Parser-detected error"

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is True
        # The pre-existing message must be preserved.
        assert result.error_message == "Parser-detected error"


class TestNonzeroExitWithResultSetsIsError:
    """CodexProcess.run() must also mark errors when exit_code != 0 even if
    turn.completed was received and is_error was not set by the parser."""

    def test_nonzero_exit_with_result_sets_is_error(self) -> None:
        """exit_code=1 + has_result_event=True + parser is_error=False → is_error=True."""
        import json

        turn_completed_line = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 0,
                    "output_tokens": 20,
                },
            }
        )
        agent_message_line = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "some response"},
            }
        )
        stdout_lines = [agent_message_line, turn_completed_line]

        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=1, stdout_lines=stdout_lines)

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is True
        assert result.exit_code == 1
        assert "exit_code=1" in result.error_message or "code 1" in result.error_message

    def test_zero_exit_with_result_is_not_error(self) -> None:
        """exit_code=0 + has_result_event=True + parser is_error=False → success."""
        import json

        turn_completed_line = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 50,
                    "cached_input_tokens": 0,
                    "output_tokens": 10,
                },
            }
        )
        agent_message_line = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "hello"},
            }
        )
        stdout_lines = [agent_message_line, turn_completed_line]

        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=0, stdout_lines=stdout_lines)

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is False
        assert result.response_text == "hello"

    def test_nonzero_exit_with_result_preserves_existing_parser_error_message(
        self,
    ) -> None:
        """When the parser already set is_error=True, the defensive check must
        not overwrite the error message."""
        import json

        # Simulate a turn.completed that itself triggered an error in the parser
        # (e.g. command failed + no agent_message).
        cmd_failed_line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "bad_cmd",
                    "exit_code": 1,
                    "aggregated_output": "command not found",
                },
            }
        )
        turn_completed_line = json.dumps({"type": "turn.completed", "usage": {}})
        stdout_lines = [cmd_failed_line, turn_completed_line]

        cp = _make_codex_process()
        mock_proc = _make_process(exit_code=1, stdout_lines=stdout_lines)

        with (
            patch.object(cp, "_process", mock_proc),
            patch("opentree.runner.codex_process._write_agents_md"),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = cp.run()

        assert result.is_error is True
        # Parser already set the message; the defensive block must not overwrite it.
        assert result.error_message == "command not found"
