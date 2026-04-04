"""StreamParser: parses Claude CLI --output-format stream-json output line by line.

Handles these event types emitted by Claude CLI:
- system / init       -> extract session_id, transition to THINKING
- content_block_start -> transition to THINKING / TOOL_USE / GENERATING based on block type
- assistant           -> extract response text from content blocks
- result              -> transition to COMPLETED or ERROR, extract final text and token counts
- (all others)        -> silently ignored

Non-JSON lines and empty lines are also silently ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Phase(str, Enum):
    INITIALIZING = "initializing"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    GENERATING = "generating"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ProgressState:
    """Mutable state tracking Claude's execution progress."""

    phase: Phase = Phase.INITIALIZING
    tool_name: str = ""
    tool_input_preview: str = ""
    session_id: str = ""
    response_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False
    error_message: str = ""
    has_result_event: bool = False


class StreamParser:
    """Parses Claude CLI stream-json events line by line.

    Usage::

        parser = StreamParser()
        for raw_line in process.stdout:
            new_phase = parser.parse_line(raw_line)
            if new_phase is not None:
                # phase changed — update UI / logging
                ...
        result = parser.get_result()
    """

    def __init__(self) -> None:
        self._state = ProgressState()

    @property
    def state(self) -> ProgressState:
        """Read-only view of the current progress state."""
        return self._state

    def parse_line(self, line: str) -> Optional[Phase]:
        """Parse a single line of stream-json output.

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

        if event_type == "system":
            return self._handle_system(data)

        if event_type == "content_block_start":
            return self._handle_content_block_start(data)

        if event_type == "assistant":
            return self._handle_assistant(data)

        if event_type == "result":
            return self._handle_result(data)

        return None

    # ------------------------------------------------------------------
    # Private event handlers
    # ------------------------------------------------------------------

    def _handle_system(self, data: dict) -> Optional[Phase]:
        subtype = data.get("subtype")
        if subtype == "init":
            session_id = data.get("session_id") or ""
            self._state.session_id = session_id
            return self._set_phase(Phase.THINKING)
        return None

    def _handle_content_block_start(self, data: dict) -> Optional[Phase]:
        block = data.get("content_block")
        if not isinstance(block, dict):
            return None

        block_type = block.get("type")

        if block_type == "thinking":
            return self._set_phase(Phase.THINKING)

        if block_type == "tool_use":
            self._state.tool_name = block.get("name") or ""
            # Best-effort input preview: serialize the input dict if present
            raw_input = block.get("input")
            if raw_input is not None:
                try:
                    self._state.tool_input_preview = json.dumps(raw_input, ensure_ascii=False)
                except (TypeError, ValueError):
                    self._state.tool_input_preview = str(raw_input)
            else:
                self._state.tool_input_preview = ""
            return self._set_phase(Phase.TOOL_USE)

        if block_type == "text":
            return self._set_phase(Phase.GENERATING)

        return None

    def _handle_assistant(self, data: dict) -> Optional[Phase]:
        message = data.get("message", {})
        if not isinstance(message, dict):
            return None

        content = message.get("content", [])
        if not isinstance(content, list):
            return None

        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    text_parts.append(text)

        if text_parts:
            combined = " ".join(text_parts)
            # Append to any previously accumulated text
            if self._state.response_text:
                self._state.response_text = self._state.response_text + "\n" + combined
            else:
                self._state.response_text = combined
            return None  # assistant events do not trigger a phase change

        return None

    def _handle_result(self, data: dict) -> Optional[Phase]:
        self._state.has_result_event = True
        result_text = data.get("result") or ""
        is_error = bool(data.get("is_error", False))

        # Update session_id if provided in result event
        result_session = data.get("session_id") or ""
        if result_session:
            self._state.session_id = result_session

        # Token counts
        usage = data.get("usage") or {}
        if isinstance(usage, dict):
            self._state.input_tokens = int(usage.get("input_tokens") or 0)
            self._state.output_tokens = int(usage.get("output_tokens") or 0)

        if is_error:
            self._state.is_error = True
            self._state.error_message = result_text
            return self._set_phase(Phase.ERROR)

        # Successful completion: prefer result event text as final response
        # (it is the cleanest single-segment text)
        if result_text:
            self._state.response_text = result_text

        return self._set_phase(Phase.COMPLETED)

    def _set_phase(self, new_phase: Phase) -> Phase:
        """Update internal phase and return the new phase."""
        self._state.phase = new_phase
        return new_phase

    # ------------------------------------------------------------------
    # Public result accessor
    # ------------------------------------------------------------------

    def get_result(self) -> dict:
        """Return the final result as a dict.

        Keys: session_id, response_text, input_tokens, output_tokens,
              is_error, error_message.
        """
        return {
            "session_id": self._state.session_id,
            "response_text": self._state.response_text,
            "input_tokens": self._state.input_tokens,
            "output_tokens": self._state.output_tokens,
            "is_error": self._state.is_error,
            "error_message": self._state.error_message,
        }
