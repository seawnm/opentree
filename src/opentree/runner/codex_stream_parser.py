"""StreamParser: parses Codex CLI --json JSONL output line by line.

Handles these event types emitted by Codex CLI:
- thread.started                 -> extract session_id, transition to THINKING
- item.started                   -> transition to TOOL_USE for command execution
- item.completed (command)       -> transition back to THINKING
- item.completed (agent_message) -> extract response text, transition to GENERATING
- turn.completed                 -> transition to COMPLETED or ERROR, extract token counts
- (all others)                   -> silently ignored

Non-JSON lines and empty lines are also silently ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class Phase(str, Enum):
    INITIALIZING = "initializing"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    GENERATING = "generating"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ProgressState:
    """Mutable state tracking Codex's execution progress."""

    phase: Phase = Phase.INITIALIZING
    tool_name: str = ""
    tool_input_preview: str = ""
    tool_category: str = "other"
    session_id: str = ""
    response_text: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False
    error_message: str = ""
    has_result_event: bool = False
    last_event: str = ""
    event_seq: int = 0


class StreamParser:
    """Parses Codex CLI JSONL events line by line.

    Usage::

        parser = StreamParser()
        for raw_line in process.stdout:
            new_phase = parser.parse_line(raw_line)
            if new_phase is not None:
                # phase changed - update UI / logging
                ...
        result = parser.get_result()
    """

    def __init__(self) -> None:
        self._state = ProgressState()
        self._saw_agent_message = False
        self._saw_error_hint = False

    @property
    def state(self) -> ProgressState:
        """Read-only view of the current progress state."""
        return self._state

    def parse_line(self, line: str) -> Optional[Phase]:
        """Parse a single line of JSONL output.

        Returns the new Phase if the phase changed, None otherwise.
        Non-JSON lines and empty/whitespace-only lines are silently ignored.
        """
        stripped = line.strip()
        if not stripped:
            return None

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        event_type = data.get("type")
        if not isinstance(event_type, str):
            return None

        if event_type == "thread.started":
            return self._handle_thread_started(data)

        if event_type == "item.started":
            return self._handle_item_started(data)

        if event_type == "item.completed":
            return self._handle_item_completed(data)

        if event_type == "turn.completed":
            return self._handle_turn_completed(data)

        if event_type.endswith(".failed") or event_type == "error":
            self._mark_error_hint(data)

        return None

    # ------------------------------------------------------------------
    # Private event handlers
    # ------------------------------------------------------------------

    def _handle_thread_started(self, data: dict[str, Any]) -> Optional[Phase]:
        thread_id = data.get("thread_id")
        if isinstance(thread_id, str):
            self._state.session_id = thread_id
        self._mark_event("thinking_started")
        return self._set_phase(Phase.THINKING)

    def _handle_item_started(self, data: dict[str, Any]) -> Optional[Phase]:
        item = data.get("item")
        if not isinstance(item, dict):
            return None

        item_type = item.get("type")
        if item_type == "reasoning":
            self._mark_event("thinking_started")
            return self._set_phase(Phase.THINKING)

        if item_type not in {
            "command_execution",
            "mcp_tool_call",
            "web_search",
            "collab_tool_call",
        }:
            return None

        tool_name, tool_preview, tool_category = self._extract_tool_details(item, item_type)
        self._state.tool_name = tool_name
        self._state.tool_input_preview = tool_preview
        self._state.tool_category = tool_category
        self._mark_event("tool_started")
        return self._set_phase(Phase.TOOL_USE)

    def _handle_item_completed(self, data: dict[str, Any]) -> Optional[Phase]:
        item = data.get("item")
        if not isinstance(item, dict):
            return None

        item_type = item.get("type")

        if item_type == "reasoning":
            self._mark_event("thinking_completed")
            return self._set_phase(Phase.THINKING)

        if item_type == "command_execution":
            self._update_error_hint_from_command(item)
            self._mark_event("tool_completed")
            self._state.tool_category = "bash"
            return self._set_phase(Phase.THINKING)

        if item_type in {"mcp_tool_call", "web_search", "collab_tool_call"}:
            tool_name, tool_preview, tool_category = self._extract_tool_details(item, item_type)
            self._state.tool_name = tool_name
            self._state.tool_input_preview = tool_preview
            self._state.tool_category = tool_category
            self._mark_event("tool_completed")
            return self._set_phase(Phase.THINKING)

        if item_type == "agent_message":
            text = self._extract_agent_message_text(item)
            if text:
                self._saw_agent_message = True
                self._state.response_text = text
            self._mark_event("response_started")
            return self._set_phase(Phase.GENERATING)

        return None

    def _handle_turn_completed(self, data: dict[str, Any]) -> Optional[Phase]:
        self._state.has_result_event = True

        usage = data.get("usage")
        if isinstance(usage, dict):
            self._state.input_tokens = self._coerce_int(usage.get("input_tokens"))
            self._state.cached_input_tokens = self._coerce_int(
                usage.get("cached_input_tokens")
            )
            self._state.output_tokens = self._coerce_int(usage.get("output_tokens"))

        if not self._saw_agent_message and self._saw_error_hint:
            self._state.is_error = True
            if not self._state.error_message:
                self._state.error_message = "Codex turn completed without an agent_message."
            self._mark_event("turn_completed")
            return self._set_phase(Phase.ERROR)

        self._mark_event("turn_completed")
        return self._set_phase(Phase.COMPLETED)

    def _extract_tool_details(
        self,
        item: dict[str, Any],
        item_type: str,
    ) -> tuple[str, str, str]:
        if item_type == "command_execution":
            command = item.get("command") or ""
            if not isinstance(command, str):
                command = str(command)
            return "Bash", command, "bash"

        if item_type == "web_search":
            query = item.get("query") or item.get("search_query") or ""
            if not isinstance(query, str):
                query = str(query)
            return "WebSearch", query, "web"

        if item_type == "collab_tool_call":
            description = (
                item.get("description")
                or item.get("task")
                or item.get("name")
                or ""
            )
            if not isinstance(description, str):
                description = str(description)
            return "Task", description, "task"

        server = item.get("server")
        tool_name = item.get("name") or item.get("tool_name") or "MCP"
        if not isinstance(tool_name, str):
            tool_name = str(tool_name)
        if isinstance(server, str) and server:
            tool_name = f"{server}.{tool_name}"

        arguments = item.get("arguments") or item.get("input") or ""
        if isinstance(arguments, dict):
            preview = json.dumps(arguments, ensure_ascii=False)
        elif isinstance(arguments, str):
            preview = arguments
        else:
            preview = str(arguments)
        return tool_name, preview, "mcp"

    def _extract_agent_message_text(self, item: dict[str, Any]) -> str:
        text = item.get("text")
        if isinstance(text, str) and text:
            return text

        content = item.get("content")
        if not isinstance(content, list):
            return ""

        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_text = part.get("text")
            if isinstance(part_text, str) and part_text:
                text_parts.append(part_text)

        return "\n".join(text_parts)

    def _update_error_hint_from_command(self, item: dict[str, Any]) -> None:
        exit_code = item.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            self._saw_error_hint = True

            aggregated_output = item.get("aggregated_output")
            if isinstance(aggregated_output, str) and aggregated_output:
                self._state.error_message = aggregated_output
            elif not self._state.error_message:
                self._state.error_message = f"Command failed with exit code {exit_code}."

    def _mark_error_hint(self, data: dict[str, Any]) -> None:
        self._saw_error_hint = True

        message = data.get("message")
        if isinstance(message, str) and message:
            self._state.error_message = message
            return

        error = data.get("error")
        if isinstance(error, str) and error:
            self._state.error_message = error

    def _mark_event(self, event: str) -> None:
        self._state.last_event = event
        self._state.event_seq += 1

    def _set_phase(self, new_phase: Phase) -> Phase:
        """Update internal phase and return the new phase."""
        self._state.phase = new_phase
        return new_phase

    def _coerce_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # Public result accessor
    # ------------------------------------------------------------------

    def get_result(self) -> dict[str, object]:
        """Return the final result as a dict.

        Keys: session_id, response_text, input_tokens, cached_input_tokens,
              output_tokens, is_error, error_message.
        """
        return {
            "session_id": self._state.session_id,
            "response_text": self._state.response_text,
            "input_tokens": self._state.input_tokens,
            "cached_input_tokens": self._state.cached_input_tokens,
            "output_tokens": self._state.output_tokens,
            "is_error": self._state.is_error,
            "error_message": self._state.error_message,
        }
