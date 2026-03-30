"""Progress reporting for OpenTree bot runner.

Periodically updates a Slack message showing the current state of
Claude CLI execution: phase (thinking/tool_use/generating), elapsed time,
and a spinner animation.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from opentree.runner.stream_parser import Phase, ProgressState

logger = logging.getLogger(__name__)

# Phase display mapping
_PHASE_EMOJI = {
    Phase.INITIALIZING: ":hourglass_flowing_sand:",
    Phase.THINKING: ":brain:",
    Phase.TOOL_USE: ":hammer_and_wrench:",
    Phase.GENERATING: ":writing_hand:",
    Phase.COMPLETED: ":white_check_mark:",
    Phase.ERROR: ":x:",
}

_PHASE_LABEL = {
    Phase.INITIALIZING: "Initializing",
    Phase.THINKING: "Thinking",
    Phase.TOOL_USE: "Using tools",
    Phase.GENERATING: "Writing response",
    Phase.COMPLETED: "Done",
    Phase.ERROR: "Error",
}

_SPINNER = ["◐", "◓", "◑", "◒"]


def build_progress_blocks(state: ProgressState, elapsed: float) -> list[dict]:
    """Build Block Kit blocks for progress display.

    Returns a list of Block Kit block dicts:
    - Header section: phase emoji + label + spinner
    - Context: elapsed time, tool name if in tool_use phase
    """
    spinner = _SPINNER[int(elapsed) % len(_SPINNER)]
    emoji = _PHASE_EMOJI.get(state.phase, ":gear:")
    label = _PHASE_LABEL.get(state.phase, str(state.phase.value))

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{label}* {spinner}",
            },
        }
    ]

    # Context elements
    context_parts = [f":clock1: {int(elapsed)}s"]
    if state.phase == Phase.TOOL_USE and state.tool_name:
        context_parts.append(f":wrench: `{state.tool_name}`")

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " | ".join(context_parts)}],
        }
    )

    return blocks


def build_completion_blocks(
    response_text: str,
    elapsed: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    is_error: bool = False,
    error_message: str = "",
) -> list[dict]:
    """Build Block Kit blocks for the final response.

    - Success: response text + token stats
    - Error: error message with :x: prefix
    - Empty response: warning indicator
    """
    if is_error:
        text = f":x: *Error*\n{error_message or 'An error occurred.'}"
    elif not response_text:
        text = ":warning: _(no response)_"
    else:
        text = response_text

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text[:3000]},  # Slack limit
        }
    ]

    # Stats context (only on success with token counts)
    if not is_error and (input_tokens or output_tokens):
        stats = f":clock1: {elapsed:.1f}s"
        if input_tokens:
            stats += f" | :inbox_tray: {input_tokens:,}"
        if output_tokens:
            stats += f" | :outbox_tray: {output_tokens:,}"
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": stats}],
            }
        )

    return blocks


class ProgressReporter:
    """Background thread that periodically updates a Slack message.

    Usage::

        reporter = ProgressReporter(slack_api, channel, thread_ts, interval=10)
        reporter.start()          # sends initial ack message
        reporter.update(state)    # called on each phase change
        reporter.complete(result) # sends final response, stops updates
        reporter.stop()           # cleanup
    """

    def __init__(
        self,
        slack_api,  # SlackAPI instance (duck-typed to avoid import cycle)
        channel: str,
        thread_ts: str,
        interval: float = 10.0,
    ) -> None:
        self._slack = slack_api
        self._channel = channel
        self._thread_ts = thread_ts
        self._interval = interval

        self._message_ts: str = ""       # ts of the progress message
        self._state = ProgressState()
        self._start_time = time.time()
        self._stop_event = threading.Event()
        self._update_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> str:
        """Send initial ack message and start background update thread.

        Returns the message_ts of the ack message.
        """
        self._start_time = time.time()
        self._stop_event.clear()

        # Send the initial acknowledgement message
        result = self._slack.send_message(
            channel=self._channel,
            text=":hourglass_flowing_sand: Processing…",
            thread_ts=self._thread_ts,
        )
        self._message_ts = result.get("ts", "") if result else ""

        # Start background update loop
        self._update_thread = threading.Thread(
            target=self._update_loop,
            daemon=True,
            name="progress-reporter",
        )
        self._update_thread.start()

        return self._message_ts

    def update(self, state: ProgressState) -> None:
        """Update the current state (called from ClaudeProcess progress_callback)."""
        with self._lock:
            self._state = state

    def complete(
        self,
        response_text: str,
        elapsed: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        is_error: bool = False,
        error_message: str = "",
    ) -> None:
        """Send final response and stop background updates."""
        # Stop loop first so it does not race against our final update
        self._stop_event.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=2.0)

        if not self._message_ts:
            return

        blocks = build_completion_blocks(
            response_text=response_text,
            elapsed=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_error=is_error,
            error_message=error_message,
        )

        # Build a short fallback text for notification previews
        if is_error:
            fallback = f":x: Error: {error_message or 'An error occurred.'}"
        elif not response_text:
            fallback = ":warning: (no response)"
        else:
            fallback = response_text[:200]

        self._slack.update_message(
            channel=self._channel,
            ts=self._message_ts,
            text=fallback,
            blocks=blocks,
        )

    def stop(self) -> None:
        """Stop the background update thread."""
        self._stop_event.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=2.0)

    @property
    def message_ts(self) -> str:
        """The ts of the progress/response message."""
        return self._message_ts

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _update_loop(self) -> None:
        """Background loop: update Slack message every `interval` seconds."""
        while not self._stop_event.wait(self._interval):
            # stop_event.wait() returns True when set, False on timeout
            self._push_progress()

    def _push_progress(self) -> None:
        """Build current progress blocks and push to Slack."""
        if not self._message_ts:
            return

        elapsed = time.time() - self._start_time

        with self._lock:
            state = self._state

        blocks = build_progress_blocks(state, elapsed=elapsed)
        fallback = f":clock1: {int(elapsed)}s"

        self._slack.update_message(
            channel=self._channel,
            ts=self._message_ts,
            text=fallback,
            blocks=blocks,
        )
