"""Tests for ProgressReporter and block-building helpers.

Written FIRST (TDD Red phase) before implementing progress.py.
All Slack API calls are mocked — no real network access.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

from opentree.runner.stream_parser import Phase, ProgressState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slack_mock(send_ts: str = "1111.0001") -> MagicMock:
    """Return a mock SlackAPI whose send_message returns a ts."""
    slack = MagicMock()
    slack.send_message.return_value = {"ok": True, "ts": send_ts}
    slack.update_message.return_value = {"ok": True, "ts": send_ts}
    return slack


# ---------------------------------------------------------------------------
# build_progress_blocks
# ---------------------------------------------------------------------------

class TestBuildProgressBlocks:
    """Tests for the pure build_progress_blocks() helper."""

    def _import(self):
        from opentree.runner.progress import build_progress_blocks
        return build_progress_blocks

    def test_build_progress_blocks_initializing(self):
        """INITIALIZING phase: section contains hourglass emoji and label."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.INITIALIZING)
        blocks = build_progress_blocks(state, elapsed=0.0)

        assert len(blocks) >= 2
        # First block is section with phase info
        section = blocks[0]
        assert section["type"] == "section"
        text = section["text"]["text"]
        assert ":hourglass_flowing_sand:" in text
        assert "Initializing" in text

    def test_build_progress_blocks_thinking(self):
        """THINKING phase: section contains brain emoji and label."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.THINKING)
        blocks = build_progress_blocks(state, elapsed=5.0)

        section = blocks[0]
        text = section["text"]["text"]
        assert ":brain:" in text
        assert "Thinking" in text

    def test_build_progress_blocks_tool_use_with_name(self):
        """TOOL_USE phase: context block shows tool name."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.TOOL_USE, tool_name="Bash")
        blocks = build_progress_blocks(state, elapsed=3.0)

        # Find context block
        context_block = next(b for b in blocks if b["type"] == "context")
        context_text = context_block["elements"][0]["text"]
        assert "Bash" in context_text
        assert ":wrench:" in context_text

    def test_build_progress_blocks_tool_use_no_name(self):
        """TOOL_USE phase without tool name: wrench not shown."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.TOOL_USE, tool_name="")
        blocks = build_progress_blocks(state, elapsed=2.0)

        context_block = next(b for b in blocks if b["type"] == "context")
        context_text = context_block["elements"][0]["text"]
        # No tool name means no wrench entry beyond time
        assert ":wrench:" not in context_text

    def test_build_progress_blocks_generating(self):
        """GENERATING phase: section contains writing_hand emoji."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.GENERATING)
        blocks = build_progress_blocks(state, elapsed=10.0)

        section = blocks[0]
        text = section["text"]["text"]
        assert ":writing_hand:" in text
        assert "Writing response" in text

    def test_build_progress_blocks_spinner_rotation(self):
        """Spinner cycles through 4 chars based on int(elapsed) % 4."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.THINKING)

        spinners = set()
        for elapsed in [0.0, 1.0, 2.0, 3.0]:
            blocks = build_progress_blocks(state, elapsed=elapsed)
            text = blocks[0]["text"]["text"]
            # Extract last character(s) — spinner is appended after label
            spinners.add(text[-1])

        # All 4 elapsed values should produce different spinner chars
        assert len(spinners) == 4

    def test_build_progress_blocks_elapsed_in_context(self):
        """Context block shows elapsed seconds."""
        build_progress_blocks = self._import()
        state = ProgressState(phase=Phase.THINKING)
        blocks = build_progress_blocks(state, elapsed=42.7)

        context_block = next(b for b in blocks if b["type"] == "context")
        context_text = context_block["elements"][0]["text"]
        assert "42s" in context_text

    def test_build_progress_blocks_returns_list(self):
        """Returns a list of dicts."""
        build_progress_blocks = self._import()
        state = ProgressState()
        blocks = build_progress_blocks(state, elapsed=0.0)
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)


# ---------------------------------------------------------------------------
# build_completion_blocks
# ---------------------------------------------------------------------------

class TestBuildCompletionBlocks:
    """Tests for the pure build_completion_blocks() helper."""

    def _import(self):
        from opentree.runner.progress import build_completion_blocks
        return build_completion_blocks

    def test_build_completion_blocks_success(self):
        """Success: response text appears in section block."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("Hello world", elapsed=5.0)

        section = blocks[0]
        assert section["type"] == "section"
        assert "Hello world" in section["text"]["text"]

    def test_build_completion_blocks_with_tokens(self):
        """Token counts appear in context block when provided."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks(
            "Response", elapsed=3.2,
            input_tokens=100, output_tokens=50,
        )

        context_block = next((b for b in blocks if b["type"] == "context"), None)
        assert context_block is not None
        context_text = context_block["elements"][0]["text"]
        assert "100" in context_text
        assert "50" in context_text

    def test_build_completion_blocks_no_tokens_no_context(self):
        """Without tokens, no stats context block is added."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("Response", elapsed=1.0)

        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert len(context_blocks) == 0

    def test_build_completion_blocks_error(self):
        """Error case: :x: prefix and error message shown."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks(
            "", elapsed=2.0,
            is_error=True, error_message="Timeout occurred",
        )

        section = blocks[0]
        text = section["text"]["text"]
        assert ":x:" in text
        assert "Timeout occurred" in text

    def test_build_completion_blocks_error_default_message(self):
        """Error without explicit message shows generic error text."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("", elapsed=1.0, is_error=True)

        section = blocks[0]
        text = section["text"]["text"]
        assert ":x:" in text
        assert "error" in text.lower()

    def test_build_completion_blocks_empty_response(self):
        """Empty (non-error) response: warning indicator shown."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("", elapsed=1.0)

        section = blocks[0]
        text = section["text"]["text"]
        assert ":warning:" in text

    def test_build_completion_blocks_long_text_truncated(self):
        """Text longer than 3000 chars is truncated to fit Slack limit."""
        build_completion_blocks = self._import()
        long_text = "A" * 4000
        blocks = build_completion_blocks(long_text, elapsed=1.0)

        section = blocks[0]
        text = section["text"]["text"]
        assert len(text) <= 3000

    def test_build_completion_blocks_elapsed_in_stats(self):
        """Elapsed time appears in stats context when tokens are provided."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks(
            "ok", elapsed=7.5, input_tokens=10, output_tokens=5
        )
        context_block = next(b for b in blocks if b["type"] == "context")
        assert "7.5s" in context_block["elements"][0]["text"]

    def test_build_completion_blocks_returns_list(self):
        """Returns a list of dicts."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("text", elapsed=1.0)
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)


class TestBuildCompletionBlocksMultiSection:
    """Tests for multi-section splitting when response exceeds 3000 chars."""

    def _import(self):
        from opentree.runner.progress import build_completion_blocks
        return build_completion_blocks

    def test_short_text_single_section(self):
        """Text <= 3000 chars produces exactly one section block."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks("Short text", elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) == 1

    def test_medium_text_split_into_multiple_sections(self):
        """Text > 3000 chars is split into multiple section blocks."""
        build_completion_blocks = self._import()
        text = "A" * 5000
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) == 2
        # Each section must be <= 3000 chars
        for sb in section_blocks:
            assert len(sb["text"]["text"]) <= 3000

    def test_split_preserves_all_content(self):
        """Split sections together contain the full original text."""
        build_completion_blocks = self._import()
        text = "B" * 7500
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        combined = "".join(sb["text"]["text"] for sb in section_blocks)
        assert combined == text

    def test_exactly_3000_no_split(self):
        """Text of exactly 3000 chars is not split."""
        build_completion_blocks = self._import()
        text = "C" * 3000
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) == 1

    def test_3001_chars_splits_into_two(self):
        """Text of 3001 chars splits into two sections."""
        build_completion_blocks = self._import()
        text = "D" * 3001
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) == 2

    def test_truncation_indicator_for_very_long_text(self):
        """Text > 12000 chars adds a truncation indicator."""
        build_completion_blocks = self._import()
        text = "E" * 15000
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        # Last section should indicate truncation
        last_section_text = section_blocks[-1]["text"]["text"]
        assert "(truncated)" in last_section_text

    def test_no_truncation_indicator_under_12000(self):
        """Text <= 12000 chars does NOT have truncation indicator."""
        build_completion_blocks = self._import()
        text = "F" * 9000
        blocks = build_completion_blocks(text, elapsed=1.0)
        section_blocks = [b for b in blocks if b["type"] == "section"]
        all_text = "".join(sb["text"]["text"] for sb in section_blocks)
        assert "(truncated)" not in all_text

    def test_error_not_split(self):
        """Error messages are NOT split (they use the old single-section path)."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks(
            "", elapsed=1.0, is_error=True, error_message="X" * 5000,
        )
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) == 1

    def test_stats_context_after_all_sections(self):
        """Token stats context block appears after all section blocks."""
        build_completion_blocks = self._import()
        text = "G" * 5000
        blocks = build_completion_blocks(
            text, elapsed=2.0, input_tokens=100, output_tokens=50,
        )
        # Find index of last section and the context block
        section_indices = [i for i, b in enumerate(blocks) if b["type"] == "section"]
        context_indices = [i for i, b in enumerate(blocks) if b["type"] == "context"]
        assert len(context_indices) == 1
        assert context_indices[0] > max(section_indices)


# ---------------------------------------------------------------------------
# build_completion_blocks — tool_timeline parameter
# ---------------------------------------------------------------------------


class TestBuildCompletionBlocksToolTimeline:
    """Tests for tool_timeline parameter in build_completion_blocks."""

    def _import(self):
        from opentree.runner.progress import build_completion_blocks
        return build_completion_blocks

    def test_timeline_appears_as_context_block(self):
        """tool_timeline adds a context block with the timeline text."""
        build_completion_blocks = self._import()
        timeline = "Tool timeline:\n  Bash (2.5s)\n  Read (1.0s)"
        blocks = build_completion_blocks(
            "Response text", elapsed=5.0, tool_timeline=timeline,
        )
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert len(context_blocks) == 1
        assert "Bash" in context_blocks[0]["elements"][0]["text"]

    def test_timeline_not_shown_on_error(self):
        """tool_timeline is suppressed when is_error is True."""
        build_completion_blocks = self._import()
        timeline = "Tool timeline:\n  Bash (2.5s)"
        blocks = build_completion_blocks(
            "", elapsed=5.0,
            is_error=True, error_message="fail",
            tool_timeline=timeline,
        )
        context_blocks = [b for b in blocks if b["type"] == "context"]
        # Error blocks do not get timeline or stats context
        assert len(context_blocks) == 0

    def test_empty_timeline_no_extra_block(self):
        """Empty tool_timeline does not add a context block."""
        build_completion_blocks = self._import()
        blocks = build_completion_blocks(
            "Response", elapsed=3.0, tool_timeline="",
        )
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert len(context_blocks) == 0

    def test_timeline_before_stats_context(self):
        """Timeline context appears before stats context when both present."""
        build_completion_blocks = self._import()
        timeline = "Tool timeline:\n  Bash (1.0s)"
        blocks = build_completion_blocks(
            "ok", elapsed=5.0,
            input_tokens=100, output_tokens=50,
            tool_timeline=timeline,
        )
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert len(context_blocks) == 2
        # First context = timeline, second context = stats
        assert "Bash" in context_blocks[0]["elements"][0]["text"]
        assert "100" in context_blocks[1]["elements"][0]["text"]

    def test_timeline_with_long_response(self):
        """Timeline works correctly with multi-section long responses."""
        build_completion_blocks = self._import()
        timeline = "Tool timeline:\n  Write (0.5s)"
        text = "H" * 5000
        blocks = build_completion_blocks(
            text, elapsed=2.0,
            input_tokens=10, output_tokens=5,
            tool_timeline=timeline,
        )
        section_blocks = [b for b in blocks if b["type"] == "section"]
        context_blocks = [b for b in blocks if b["type"] == "context"]
        assert len(section_blocks) == 2  # 5000 chars -> 2 sections
        assert len(context_blocks) == 2  # timeline + stats


# ---------------------------------------------------------------------------
# ProgressReporter
# ---------------------------------------------------------------------------

class TestProgressReporterStart:
    """Tests for ProgressReporter.start()."""

    def test_reporter_start_sends_ack(self):
        """start() sends an initial ack message and returns its ts."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="9999.0001")
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            ts = reporter.start()
            assert ts == "9999.0001"
            slack.send_message.assert_called_once()
            # Must be sent to the right channel and thread
            call_kwargs = slack.send_message.call_args
            args, kwargs = call_kwargs
            # channel is either positional or keyword
            called_channel = kwargs.get("channel") or args[0]
            assert called_channel == "C001"
        finally:
            reporter.stop()

    def test_reporter_start_saves_message_ts(self):
        """start() stores the returned ts in message_ts property."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="8888.0001")
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            assert reporter.message_ts == "8888.0001"
        finally:
            reporter.stop()

    def test_reporter_start_spawns_background_thread(self):
        """start() launches a background update thread."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            assert reporter._update_thread is not None
            assert reporter._update_thread.is_alive()
        finally:
            reporter.stop()

    def test_reporter_start_ack_sent_to_thread(self):
        """start() sends the ack message inside the thread."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "thread.001", interval=60.0)

        try:
            reporter.start()
            call_kwargs = slack.send_message.call_args
            args, kwargs = call_kwargs
            called_thread = kwargs.get("thread_ts") or (args[1] if len(args) > 1 else None)
            assert called_thread == "thread.001"
        finally:
            reporter.stop()


class TestProgressReporterUpdate:
    """Tests for ProgressReporter.update()."""

    def test_reporter_update_state(self):
        """update() stores the new ProgressState internally."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            new_state = ProgressState(phase=Phase.THINKING)
            reporter.update(new_state)
            assert reporter._state.phase == Phase.THINKING
        finally:
            reporter.stop()

    def test_reporter_update_replaces_state(self):
        """Successive update() calls replace the previous state."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            reporter.update(ProgressState(phase=Phase.THINKING))
            reporter.update(ProgressState(phase=Phase.TOOL_USE, tool_name="Read"))
            assert reporter._state.phase == Phase.TOOL_USE
            assert reporter._state.tool_name == "Read"
        finally:
            reporter.stop()


class TestProgressReporterComplete:
    """Tests for ProgressReporter.complete()."""

    def test_reporter_complete_updates_message(self):
        """complete() calls update_message with the response text."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="1000.0001")
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            reporter.complete("Great answer", elapsed=3.0)

            # update_message should have been called with the message ts
            assert slack.update_message.called
            call_kwargs = slack.update_message.call_args
            args, kwargs = call_kwargs
            called_ts = kwargs.get("ts") or args[1]
            assert called_ts == "1000.0001"
        finally:
            reporter.stop()

    def test_reporter_complete_stops_thread(self):
        """complete() stops the background update thread."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        reporter.start()
        assert reporter._update_thread is not None
        alive_before = reporter._update_thread.is_alive()

        reporter.complete("done", elapsed=1.0)

        # Give thread a moment to exit
        reporter._update_thread.join(timeout=2.0)
        assert not reporter._update_thread.is_alive()

    def test_reporter_complete_error_path(self):
        """complete() with is_error=True still calls update_message."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            reporter.complete(
                "", elapsed=1.0,
                is_error=True, error_message="Something broke"
            )
            assert slack.update_message.called
        finally:
            reporter.stop()

    def test_reporter_complete_passes_blocks(self):
        """complete() passes blocks to update_message, not just text."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            reporter.complete("Answer text", elapsed=2.5)
            call_kwargs = slack.update_message.call_args
            _, kwargs = call_kwargs
            assert "blocks" in kwargs
            assert isinstance(kwargs["blocks"], list)
        finally:
            reporter.stop()

    def test_reporter_complete_with_tool_timeline(self):
        """complete() with tool_timeline includes timeline in blocks."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

        try:
            reporter.start()
            reporter.complete(
                "Answer", elapsed=5.0,
                input_tokens=100, output_tokens=50,
                tool_timeline="Tool timeline:\n  Bash (2.0s)",
            )
            call_kwargs = slack.update_message.call_args
            _, kwargs = call_kwargs
            blocks = kwargs["blocks"]
            context_blocks = [b for b in blocks if b["type"] == "context"]
            # Should have 2 context blocks: timeline + stats
            assert len(context_blocks) == 2
            timeline_text = context_blocks[0]["elements"][0]["text"]
            assert "Bash" in timeline_text
        finally:
            reporter.stop()


class TestProgressReporterStop:
    """Tests for ProgressReporter.stop()."""

    def test_reporter_stop_idempotent(self):
        """stop() can be called multiple times without error."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)
        reporter.start()

        reporter.stop()
        reporter.stop()  # second call must not raise

    def test_reporter_stop_sets_event(self):
        """stop() sets the internal stop event."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)
        reporter.start()
        reporter.stop()

        assert reporter._stop_event.is_set()

    def test_reporter_stop_without_start(self):
        """stop() before start() does not raise."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)
        reporter.stop()  # must not raise


class TestProgressReporterUpdateLoop:
    """Tests for the background _update_loop behaviour."""

    def test_reporter_update_loop_interval(self):
        """Background loop calls update_message after each interval fires."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="2222.0001")
        # Use a very short interval so the loop fires quickly in tests
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=0.05)

        try:
            reporter.start()
            # Wait for at least one loop cycle
            time.sleep(0.3)
        finally:
            reporter.stop()

        # update_message should have been called at least once by the loop
        assert slack.update_message.call_count >= 1

    def test_reporter_update_loop_uses_current_state(self):
        """Loop encodes the latest state into the Slack update."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="3333.0001")
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=0.05)

        try:
            reporter.start()
            reporter.update(ProgressState(phase=Phase.TOOL_USE, tool_name="Bash"))
            time.sleep(0.3)
        finally:
            reporter.stop()

        # At least one update_message call should reference Bash in blocks
        any_bash = False
        for c in slack.update_message.call_args_list:
            _, kwargs = c
            blocks = kwargs.get("blocks", [])
            for block in blocks:
                if block.get("type") == "context":
                    for elem in block.get("elements", []):
                        if "Bash" in elem.get("text", ""):
                            any_bash = True
        assert any_bash, "Expected at least one update_message call with Bash tool in blocks"

    def test_reporter_loop_stops_after_stop(self):
        """Loop terminates cleanly after stop() is called."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678", interval=0.05)
        reporter.start()
        reporter.stop()

        thread = reporter._update_thread
        if thread is not None:
            thread.join(timeout=2.0)
            assert not thread.is_alive()


class TestProgressReporterMessageTsProperty:
    """Tests for the message_ts property."""

    def test_reporter_message_ts_property_empty_before_start(self):
        """message_ts is empty string before start() is called."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock()
        reporter = ProgressReporter(slack, "C001", "1234.5678")
        assert reporter.message_ts == ""

    def test_reporter_message_ts_property_set_after_start(self):
        """message_ts reflects the ts returned by send_message after start()."""
        from opentree.runner.progress import ProgressReporter

        slack = _make_slack_mock(send_ts="7777.0001")
        reporter = ProgressReporter(slack, "C001", "1234.5678")

        try:
            reporter.start()
            assert reporter.message_ts == "7777.0001"
        finally:
            reporter.stop()

    def test_reporter_message_ts_send_failure(self):
        """message_ts remains empty if send_message returns no ts."""
        from opentree.runner.progress import ProgressReporter

        slack = MagicMock()
        slack.send_message.return_value = {}  # No 'ts' key

        reporter = ProgressReporter(slack, "C001", "1234.5678")

        try:
            reporter.start()
            assert reporter.message_ts == ""
        finally:
            reporter.stop()
