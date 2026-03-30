"""Tests for StreamParser - written FIRST (TDD Red phase).

Tests the parsing of Claude CLI --output-format stream-json output.
"""

from __future__ import annotations

import json

import pytest

from opentree.runner.stream_parser import Phase, ProgressState, StreamParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(obj: dict) -> str:
    """Serialize a dict to a JSON line as Claude CLI would emit."""
    return json.dumps(obj)


# ---------------------------------------------------------------------------
# ProgressState tests
# ---------------------------------------------------------------------------

class TestProgressState:
    def test_default_values(self):
        state = ProgressState()
        assert state.phase == Phase.INITIALIZING
        assert state.tool_name == ""
        assert state.tool_input_preview == ""
        assert state.session_id == ""
        assert state.response_text == ""
        assert state.input_tokens == 0
        assert state.output_tokens == 0
        assert state.is_error is False
        assert state.error_message == ""


# ---------------------------------------------------------------------------
# StreamParser.parse_line tests
# ---------------------------------------------------------------------------

class TestParseSystemEvent:
    """test_parse_system_event: session_id extraction from system/init event."""

    def test_system_init_extracts_session_id(self):
        parser = StreamParser()
        line = _line({"type": "system", "subtype": "init", "session_id": "ses-abc123"})
        phase = parser.parse_line(line)
        assert parser.state.session_id == "ses-abc123"

    def test_system_init_transitions_to_thinking(self):
        parser = StreamParser()
        line = _line({"type": "system", "subtype": "init", "session_id": "ses-xyz"})
        phase = parser.parse_line(line)
        assert phase == Phase.THINKING
        assert parser.state.phase == Phase.THINKING

    def test_system_init_without_session_id_leaves_session_empty(self):
        parser = StreamParser()
        line = _line({"type": "system", "subtype": "init"})
        parser.parse_line(line)
        assert parser.state.session_id == ""

    def test_system_unknown_subtype_returns_none(self):
        parser = StreamParser()
        line = _line({"type": "system", "subtype": "hook_started"})
        result = parser.parse_line(line)
        assert result is None


class TestParseThinkingPhase:
    """test_parse_thinking_phase: content_block_start with thinking type."""

    def test_thinking_block_transitions_to_thinking(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "thinking"}
        })
        phase = parser.parse_line(line)
        assert phase == Phase.THINKING
        assert parser.state.phase == Phase.THINKING

    def test_thinking_block_returns_phase(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "thinking"}
        })
        phase = parser.parse_line(line)
        assert phase is not None


class TestParseToolUsePhase:
    """test_parse_tool_use_phase: content_block_start with tool_use type."""

    def test_tool_use_block_transitions_to_tool_use(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Bash"}
        })
        phase = parser.parse_line(line)
        assert phase == Phase.TOOL_USE
        assert parser.state.phase == Phase.TOOL_USE

    def test_tool_use_extracts_tool_name(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Read"}
        })
        parser.parse_line(line)
        assert parser.state.tool_name == "Read"

    def test_tool_use_with_input_preview(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": "ls -la"}
            }
        })
        parser.parse_line(line)
        assert "ls -la" in parser.state.tool_input_preview

    def test_tool_use_missing_name_uses_empty_string(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "tool_use"}
        })
        parser.parse_line(line)
        assert parser.state.tool_name == ""


class TestParseTextPhase:
    """test_parse_text_phase: content_block_start with text type."""

    def test_text_block_transitions_to_generating(self):
        parser = StreamParser()
        line = _line({
            "type": "content_block_start",
            "content_block": {"type": "text"}
        })
        phase = parser.parse_line(line)
        assert phase == Phase.GENERATING
        assert parser.state.phase == Phase.GENERATING


class TestParseResultCompleted:
    """test_parse_result_completed: result event with success."""

    def test_result_event_transitions_to_completed(self):
        parser = StreamParser()
        line = _line({"type": "result", "result": "Hello, world!"})
        phase = parser.parse_line(line)
        assert phase == Phase.COMPLETED
        assert parser.state.phase == Phase.COMPLETED

    def test_result_event_extracts_response_text(self):
        parser = StreamParser()
        line = _line({"type": "result", "result": "The answer is 42."})
        parser.parse_line(line)
        assert parser.state.response_text == "The answer is 42."

    def test_result_event_without_is_error_flag_not_error(self):
        parser = StreamParser()
        line = _line({"type": "result", "result": "ok"})
        parser.parse_line(line)
        assert parser.state.is_error is False
        assert parser.state.error_message == ""

    def test_result_event_extracts_session_id(self):
        parser = StreamParser()
        line = _line({"type": "result", "result": "done", "session_id": "ses-final"})
        parser.parse_line(line)
        assert parser.state.session_id == "ses-final"


class TestParseResultError:
    """test_parse_result_error: result event with is_error=True."""

    def test_error_result_sets_is_error(self):
        parser = StreamParser()
        line = _line({"type": "result", "is_error": True, "result": "Something went wrong"})
        phase = parser.parse_line(line)
        assert phase == Phase.ERROR
        assert parser.state.is_error is True
        assert parser.state.phase == Phase.ERROR

    def test_error_result_extracts_error_message(self):
        parser = StreamParser()
        line = _line({"type": "result", "is_error": True, "result": "Timeout exceeded"})
        parser.parse_line(line)
        assert parser.state.error_message == "Timeout exceeded"

    def test_error_false_is_not_error(self):
        parser = StreamParser()
        line = _line({"type": "result", "is_error": False, "result": "ok"})
        parser.parse_line(line)
        assert parser.state.is_error is False
        assert parser.state.phase == Phase.COMPLETED


class TestParseInvalidJson:
    """test_parse_invalid_json: non-JSON lines silently ignored."""

    def test_invalid_json_returns_none(self):
        parser = StreamParser()
        result = parser.parse_line("this is not json {{{")
        assert result is None

    def test_invalid_json_does_not_change_phase(self):
        parser = StreamParser()
        initial_phase = parser.state.phase
        parser.parse_line("definitely not json")
        assert parser.state.phase == initial_phase

    def test_partial_json_returns_none(self):
        parser = StreamParser()
        result = parser.parse_line('{"type": "result"')  # truncated
        assert result is None


class TestParseEmptyLine:
    """test_parse_empty_line: empty and whitespace-only lines silently ignored."""

    def test_empty_string_returns_none(self):
        parser = StreamParser()
        result = parser.parse_line("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        parser = StreamParser()
        result = parser.parse_line("   \t  \n  ")
        assert result is None

    def test_empty_does_not_change_state(self):
        parser = StreamParser()
        parser.parse_line("")
        assert parser.state.phase == Phase.INITIALIZING


class TestTokenCounting:
    """test_token_counting: token extraction from result event."""

    def test_result_event_extracts_input_tokens(self):
        parser = StreamParser()
        line = _line({
            "type": "result",
            "result": "done",
            "usage": {"input_tokens": 150, "output_tokens": 42}
        })
        parser.parse_line(line)
        assert parser.state.input_tokens == 150

    def test_result_event_extracts_output_tokens(self):
        parser = StreamParser()
        line = _line({
            "type": "result",
            "result": "done",
            "usage": {"input_tokens": 100, "output_tokens": 75}
        })
        parser.parse_line(line)
        assert parser.state.output_tokens == 75

    def test_result_event_without_usage_keeps_zero(self):
        parser = StreamParser()
        line = _line({"type": "result", "result": "done"})
        parser.parse_line(line)
        assert parser.state.input_tokens == 0
        assert parser.state.output_tokens == 0

    def test_partial_usage_dict(self):
        parser = StreamParser()
        line = _line({
            "type": "result",
            "result": "done",
            "usage": {"input_tokens": 50}
        })
        parser.parse_line(line)
        assert parser.state.input_tokens == 50
        assert parser.state.output_tokens == 0


class TestPhaseTransitions:
    """test_phase_transitions: full lifecycle sequence."""

    def test_full_lifecycle_phases(self):
        """Simulate a complete Claude CLI run: init -> thinking -> tool -> generating -> completed."""
        parser = StreamParser()

        # 1. System init
        parser.parse_line(_line({"type": "system", "subtype": "init", "session_id": "s1"}))
        assert parser.state.phase == Phase.THINKING

        # 2. Content block: tool use
        parser.parse_line(_line({
            "type": "content_block_start",
            "content_block": {"type": "tool_use", "name": "Bash"}
        }))
        assert parser.state.phase == Phase.TOOL_USE
        assert parser.state.tool_name == "Bash"

        # 3. Content block: text generation
        parser.parse_line(_line({
            "type": "content_block_start",
            "content_block": {"type": "text"}
        }))
        assert parser.state.phase == Phase.GENERATING

        # 4. Result
        parser.parse_line(_line({"type": "result", "result": "Final answer"}))
        assert parser.state.phase == Phase.COMPLETED
        assert parser.state.response_text == "Final answer"

    def test_thinking_then_result(self):
        """Minimal run: init -> thinking -> completed."""
        parser = StreamParser()
        parser.parse_line(_line({"type": "system", "subtype": "init", "session_id": "s2"}))
        parser.parse_line(_line({"type": "result", "result": "Quick answer"}))
        assert parser.state.phase == Phase.COMPLETED
        assert parser.state.response_text == "Quick answer"

    def test_multiple_tool_uses(self):
        """Multiple tool calls in sequence."""
        parser = StreamParser()
        parser.parse_line(_line({"type": "system", "subtype": "init", "session_id": "s3"}))

        for tool in ["Read", "Write", "Bash"]:
            parser.parse_line(_line({
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": tool}
            }))
            assert parser.state.tool_name == tool

        parser.parse_line(_line({"type": "result", "result": "done"}))
        assert parser.state.phase == Phase.COMPLETED

    def test_unknown_event_type_returns_none(self):
        parser = StreamParser()
        result = parser.parse_line(_line({"type": "ping"}))
        assert result is None


class TestGetResult:
    """test_get_result: final result dictionary."""

    def test_get_result_after_completed(self):
        parser = StreamParser()
        parser.parse_line(_line({"type": "system", "subtype": "init", "session_id": "s-res"}))
        parser.parse_line(_line({
            "type": "result",
            "result": "My response",
            "session_id": "s-res",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }))
        result = parser.get_result()
        assert result["session_id"] == "s-res"
        assert result["response_text"] == "My response"
        assert result["input_tokens"] == 10
        assert result["output_tokens"] == 5
        assert result["is_error"] is False
        assert result["error_message"] == ""

    def test_get_result_on_error(self):
        parser = StreamParser()
        parser.parse_line(_line({"type": "result", "is_error": True, "result": "fatal"}))
        result = parser.get_result()
        assert result["is_error"] is True
        assert result["error_message"] == "fatal"

    def test_get_result_initial_state(self):
        """get_result before any lines returns safe defaults."""
        parser = StreamParser()
        result = parser.get_result()
        assert result["session_id"] == ""
        assert result["response_text"] == ""
        assert result["is_error"] is False

    def test_get_result_keys_present(self):
        parser = StreamParser()
        result = parser.get_result()
        required_keys = {"session_id", "response_text", "input_tokens", "output_tokens", "is_error", "error_message"}
        assert required_keys == set(result.keys())

    def test_assistant_event_accumulates_text(self):
        """Assistant message event extracts text into response_text."""
        parser = StreamParser()
        line = _line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "I found the answer."}
                ]
            }
        })
        parser.parse_line(line)
        assert "I found the answer." in parser.state.response_text

    def test_assistant_event_with_multiple_text_blocks(self):
        parser = StreamParser()
        line = _line({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "First part."},
                    {"type": "text", "text": "Second part."}
                ]
            }
        })
        parser.parse_line(line)
        assert "First part." in parser.state.response_text
        assert "Second part." in parser.state.response_text
