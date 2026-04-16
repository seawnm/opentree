"""Tests for Codex StreamParser."""

from __future__ import annotations

import json

from opentree.runner.codex_stream_parser import Phase, ProgressState, StreamParser


def _line(obj: dict) -> str:
    """Serialize a dict to a JSON line as Codex CLI would emit."""
    return json.dumps(obj)


class TestProgressState:
    def test_default_values(self) -> None:
        state = ProgressState()
        assert state.phase == Phase.INITIALIZING
        assert state.tool_name == ""
        assert state.tool_input_preview == ""
        assert state.session_id == ""
        assert state.response_text == ""
        assert state.input_tokens == 0
        assert state.cached_input_tokens == 0
        assert state.output_tokens == 0
        assert state.is_error is False
        assert state.error_message == ""
        assert state.has_result_event is False


class TestThreadStarted:
    def test_extracts_thread_id_as_session_id(self) -> None:
        parser = StreamParser()
        phase = parser.parse_line(
            _line({"type": "thread.started", "thread_id": "019d9459-e5f1"})
        )
        assert phase == Phase.THINKING
        assert parser.state.phase == Phase.THINKING
        assert parser.state.session_id == "019d9459-e5f1"


class TestCommandExecution:
    def test_item_started_command_execution_enters_tool_use(self) -> None:
        parser = StreamParser()
        phase = parser.parse_line(
            _line(
                {
                    "type": "item.started",
                    "item": {"type": "command_execution", "command": "pytest tests/"},
                }
            )
        )
        assert phase == Phase.TOOL_USE
        assert parser.state.tool_name == "pytest tests/"
        assert parser.state.tool_input_preview == "pytest tests/"

    def test_item_completed_command_execution_returns_to_thinking(self) -> None:
        parser = StreamParser()
        parser.parse_line(
            _line(
                {
                    "type": "item.started",
                    "item": {"type": "command_execution", "command": "ls"},
                }
            )
        )
        phase = parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "ls",
                        "exit_code": 0,
                    },
                }
            )
        )
        assert phase == Phase.THINKING
        assert parser.state.phase == Phase.THINKING


class TestAgentMessage:
    def test_item_completed_agent_message_updates_response_and_phase(self) -> None:
        parser = StreamParser()
        phase = parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "First answer"},
                }
            )
        )
        assert phase == Phase.GENERATING
        assert parser.state.phase == Phase.GENERATING
        assert parser.state.response_text == "First answer"

    def test_last_agent_message_wins(self) -> None:
        parser = StreamParser()
        parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Draft answer"},
                }
            )
        )
        parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Final answer"},
                }
            )
        )
        assert parser.state.response_text == "Final answer"


class TestTurnCompleted:
    def test_turn_completed_extracts_usage_and_completes(self) -> None:
        parser = StreamParser()
        parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Final answer"},
                }
            )
        )
        phase = parser.parse_line(
            _line(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 38211,
                        "cached_input_tokens": 22400,
                        "output_tokens": 84,
                    },
                }
            )
        )
        assert phase == Phase.COMPLETED
        assert parser.state.phase == Phase.COMPLETED
        assert parser.state.has_result_event is True
        assert parser.state.input_tokens == 38211
        assert parser.state.cached_input_tokens == 22400
        assert parser.state.output_tokens == 84

    def test_turn_completed_without_agent_message_and_error_hint_enters_error(self) -> None:
        parser = StreamParser()
        parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "pytest",
                        "exit_code": 1,
                        "aggregated_output": "tests failed",
                    },
                }
            )
        )
        phase = parser.parse_line(_line({"type": "turn.completed", "usage": {}}))
        assert phase == Phase.ERROR
        assert parser.state.phase == Phase.ERROR
        assert parser.state.is_error is True
        assert parser.state.error_message == "tests failed"


class TestGetResult:
    def test_get_result_returns_expected_fields(self) -> None:
        parser = StreamParser()
        parser.parse_line(
            _line({"type": "thread.started", "thread_id": "thread-123"})
        )
        parser.parse_line(
            _line(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Done"},
                }
            )
        )
        parser.parse_line(
            _line(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "output_tokens": 5,
                    },
                }
            )
        )
        result = parser.get_result()
        assert result == {
            "session_id": "thread-123",
            "response_text": "Done",
            "input_tokens": 10,
            "cached_input_tokens": 3,
            "output_tokens": 5,
            "is_error": False,
            "error_message": "",
        }
