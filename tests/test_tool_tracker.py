"""Tests for ToolTracker — written FIRST (TDD Red phase).

Tracks tool usage during Claude CLI execution and builds timeline summaries.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from opentree.runner.tool_tracker import ToolTracker, ToolUse


# ---------------------------------------------------------------------------
# ToolUse dataclass
# ---------------------------------------------------------------------------


class TestToolUse:
    """Tests for the ToolUse dataclass."""

    def test_default_started_at_is_current_time(self):
        """started_at defaults to approximately now."""
        before = time.time()
        tool = ToolUse(name="Bash")
        after = time.time()
        assert before <= tool.started_at <= after

    def test_default_ended_at_is_zero(self):
        """ended_at defaults to 0.0 (not yet ended)."""
        tool = ToolUse(name="Read")
        assert tool.ended_at == 0.0

    def test_default_input_preview_is_empty(self):
        """input_preview defaults to empty string."""
        tool = ToolUse(name="Write")
        assert tool.input_preview == ""

    def test_duration_while_running(self):
        """duration returns elapsed time when tool has not ended."""
        tool = ToolUse(name="Bash", started_at=100.0)
        with patch("opentree.runner.tool_tracker.time") as mock_time:
            mock_time.time.return_value = 105.0
            dur = tool.duration
            assert dur == pytest.approx(5.0)

    def test_duration_after_ended(self):
        """duration returns ended_at - started_at when tool has ended."""
        tool = ToolUse(name="Bash", started_at=100.0, ended_at=103.5)
        assert tool.duration == pytest.approx(3.5)

    def test_duration_zero_when_instant(self):
        """duration is 0 when started_at == ended_at."""
        tool = ToolUse(name="Bash", started_at=100.0, ended_at=100.0)
        assert tool.duration == pytest.approx(0.0)

    def test_name_stored(self):
        """name is stored correctly."""
        tool = ToolUse(name="Grep")
        assert tool.name == "Grep"

    def test_input_preview_stored(self):
        """input_preview is stored when provided."""
        tool = ToolUse(name="Bash", input_preview='{"command": "ls"}')
        assert tool.input_preview == '{"command": "ls"}'


# ---------------------------------------------------------------------------
# ToolTracker — basic operations
# ---------------------------------------------------------------------------


class TestToolTrackerInit:
    """Tests for ToolTracker initialization."""

    def test_empty_tracker_has_no_tools(self):
        """New tracker has empty tools list."""
        tracker = ToolTracker()
        assert tracker.tools == []

    def test_empty_tracker_total_time_is_zero(self):
        """New tracker reports 0 total tool time."""
        tracker = ToolTracker()
        assert tracker.total_tool_time == 0.0

    def test_empty_tracker_build_timeline_is_empty(self):
        """New tracker builds empty timeline string."""
        tracker = ToolTracker()
        assert tracker.build_timeline() == ""

    def test_empty_tracker_summary(self):
        """New tracker get_summary returns zeroed dict."""
        tracker = ToolTracker()
        summary = tracker.get_summary()
        assert summary["tool_count"] == 0
        assert summary["total_time"] == 0.0
        assert summary["tools"] == []


# ---------------------------------------------------------------------------
# ToolTracker — start_tool / end_tool
# ---------------------------------------------------------------------------


class TestToolTrackerStartEnd:
    """Tests for start_tool() and end_tool() lifecycle."""

    def test_start_then_end_adds_one_tool(self):
        """start_tool + end_tool produces exactly one recorded tool."""
        tracker = ToolTracker()
        tracker.start_tool("Bash")
        tracker.end_tool()
        assert len(tracker.tools) == 1
        assert tracker.tools[0].name == "Bash"

    def test_start_tool_with_input_preview(self):
        """start_tool stores input_preview on the tool."""
        tracker = ToolTracker()
        tracker.start_tool("Read", input_preview="/path/to/file")
        tracker.end_tool()
        assert tracker.tools[0].input_preview == "/path/to/file"

    def test_end_tool_sets_ended_at(self):
        """end_tool sets ended_at to a non-zero value."""
        tracker = ToolTracker()
        tracker.start_tool("Write")
        tracker.end_tool()
        assert tracker.tools[0].ended_at > 0

    def test_end_tool_without_start_is_noop(self):
        """end_tool without a prior start_tool does nothing."""
        tracker = ToolTracker()
        tracker.end_tool()  # must not raise
        assert tracker.tools == []

    def test_consecutive_start_auto_closes_previous(self):
        """Starting a new tool auto-closes the previous one."""
        tracker = ToolTracker()
        tracker.start_tool("Read")
        tracker.start_tool("Write")
        tracker.end_tool()
        assert len(tracker.tools) == 2
        assert tracker.tools[0].name == "Read"
        assert tracker.tools[0].ended_at > 0
        assert tracker.tools[1].name == "Write"

    def test_multiple_tools_sequence(self):
        """Three tools in sequence are all recorded."""
        tracker = ToolTracker()
        for name in ["Read", "Bash", "Write"]:
            tracker.start_tool(name)
            tracker.end_tool()
        assert len(tracker.tools) == 3
        assert [t.name for t in tracker.tools] == ["Read", "Bash", "Write"]

    def test_tools_returns_copy(self):
        """tools property returns a copy, not the internal list."""
        tracker = ToolTracker()
        tracker.start_tool("Bash")
        tracker.end_tool()
        tools = tracker.tools
        tools.clear()
        assert len(tracker.tools) == 1  # internal list unaffected


# ---------------------------------------------------------------------------
# ToolTracker — finish()
# ---------------------------------------------------------------------------


class TestToolTrackerFinish:
    """Tests for finish() which closes any open tool."""

    def test_finish_closes_open_tool(self):
        """finish() closes a tool that was started but not ended."""
        tracker = ToolTracker()
        tracker.start_tool("Bash")
        tracker.finish()
        assert len(tracker.tools) == 1
        assert tracker.tools[0].ended_at > 0

    def test_finish_noop_when_no_open_tool(self):
        """finish() is safe when no tool is open."""
        tracker = ToolTracker()
        tracker.finish()  # must not raise
        assert tracker.tools == []

    def test_finish_after_end_tool_is_noop(self):
        """finish() after end_tool does not duplicate the tool."""
        tracker = ToolTracker()
        tracker.start_tool("Read")
        tracker.end_tool()
        tracker.finish()
        assert len(tracker.tools) == 1


# ---------------------------------------------------------------------------
# ToolTracker — total_tool_time
# ---------------------------------------------------------------------------


class TestToolTrackerTotalTime:
    """Tests for total_tool_time property."""

    def test_total_time_single_tool(self):
        """total_tool_time for a single tool with known duration."""
        tracker = ToolTracker()
        tracker.start_tool("Bash")
        tracker.end_tool()
        # Manually set for deterministic test
        tracker._tools[0] = ToolUse(name="Bash", started_at=100.0, ended_at=105.0)
        assert tracker.total_tool_time == pytest.approx(5.0)

    def test_total_time_multiple_tools(self):
        """total_tool_time sums durations of all recorded tools."""
        tracker = ToolTracker()
        # Manually populate for deterministic timing
        tracker._tools = [
            ToolUse(name="Read", started_at=100.0, ended_at=102.0),
            ToolUse(name="Bash", started_at=103.0, ended_at=106.0),
            ToolUse(name="Write", started_at=107.0, ended_at=108.5),
        ]
        assert tracker.total_tool_time == pytest.approx(6.5)


# ---------------------------------------------------------------------------
# ToolTracker — build_timeline()
# ---------------------------------------------------------------------------


class TestToolTrackerBuildTimeline:
    """Tests for build_timeline() output formatting."""

    def test_timeline_empty_when_no_tools(self):
        """No tools -> empty string."""
        tracker = ToolTracker()
        assert tracker.build_timeline() == ""

    def test_timeline_single_tool(self):
        """Single tool appears in timeline."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Bash", started_at=100.0, ended_at=103.0),
        ]
        timeline = tracker.build_timeline()
        assert "Tool timeline:" in timeline
        assert "Bash" in timeline
        assert "3.0s" in timeline

    def test_timeline_multiple_tools(self):
        """Multiple tools appear in order."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Read", started_at=100.0, ended_at=101.0),
            ToolUse(name="Bash", started_at=102.0, ended_at=104.5),
        ]
        timeline = tracker.build_timeline()
        assert "Read" in timeline
        assert "Bash" in timeline
        # Read should appear before Bash in the output
        assert timeline.index("Read") < timeline.index("Bash")

    def test_timeline_max_entries_default(self):
        """Default max_entries=10 limits output to last 10 tools."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name=f"Tool{i}", started_at=float(i), ended_at=float(i + 1))
            for i in range(15)
        ]
        timeline = tracker.build_timeline()
        # Should show tools 5-14 (last 10)
        assert "Tool14" in timeline
        assert "Tool5" in timeline
        # First few tools should NOT appear (but the +N earlier message should)
        assert "Tool0" not in timeline
        assert "+5 earlier tools" in timeline

    def test_timeline_max_entries_custom(self):
        """Custom max_entries limits output."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name=f"T{i}", started_at=float(i), ended_at=float(i + 1))
            for i in range(5)
        ]
        timeline = tracker.build_timeline(max_entries=3)
        assert "T4" in timeline
        assert "T2" in timeline
        assert "T0" not in timeline
        assert "+2 earlier tools" in timeline

    def test_timeline_no_overflow_message_when_within_limit(self):
        """No overflow message when tools count <= max_entries."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Bash", started_at=100.0, ended_at=101.0),
        ]
        timeline = tracker.build_timeline(max_entries=10)
        assert "earlier tools" not in timeline

    def test_timeline_format_lines_indented(self):
        """Each tool line is indented with two spaces."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Bash", started_at=100.0, ended_at=101.0),
        ]
        timeline = tracker.build_timeline()
        lines = timeline.split("\n")
        # First line is header, remaining are tool lines
        tool_lines = [l for l in lines if l.startswith("  ")]
        assert len(tool_lines) >= 1


# ---------------------------------------------------------------------------
# ToolTracker — get_summary()
# ---------------------------------------------------------------------------


class TestToolTrackerGetSummary:
    """Tests for get_summary() dict output."""

    def test_summary_tool_count(self):
        """tool_count reflects number of recorded tools."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Read", started_at=100.0, ended_at=101.0),
            ToolUse(name="Bash", started_at=102.0, ended_at=103.0),
        ]
        summary = tracker.get_summary()
        assert summary["tool_count"] == 2

    def test_summary_total_time_rounded(self):
        """total_time is rounded to 1 decimal."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Bash", started_at=100.0, ended_at=102.333),
        ]
        summary = tracker.get_summary()
        assert summary["total_time"] == 2.3

    def test_summary_tools_list(self):
        """tools list contains name and duration for each tool."""
        tracker = ToolTracker()
        tracker._tools = [
            ToolUse(name="Read", started_at=100.0, ended_at=101.5),
            ToolUse(name="Write", started_at=102.0, ended_at=103.0),
        ]
        summary = tracker.get_summary()
        assert len(summary["tools"]) == 2
        assert summary["tools"][0]["name"] == "Read"
        assert summary["tools"][0]["duration"] == 1.5
        assert summary["tools"][1]["name"] == "Write"
        assert summary["tools"][1]["duration"] == 1.0

    def test_summary_keys_present(self):
        """Summary dict has required keys."""
        tracker = ToolTracker()
        summary = tracker.get_summary()
        assert set(summary.keys()) == {"tool_count", "total_time", "tools"}


# ---------------------------------------------------------------------------
# ToolTracker — _merge_same_type_groups (grouping helper)
# ---------------------------------------------------------------------------


class TestMergeSameTypeGroups:
    """Tests for _merge_same_type_groups() static method."""

    def test_three_web_searches_within_half_second_merged(self):
        """3 consecutive web searches within 0.5s → single group of 3."""
        t0 = 1000.0
        tools = [
            ToolUse(name="WebSearch", started_at=t0 + 0.0, ended_at=t0 + 0.3, category="web", input_preview="query1"),
            ToolUse(name="WebSearch", started_at=t0 + 0.2, ended_at=t0 + 0.5, category="web", input_preview="query2"),
            ToolUse(name="WebSearch", started_at=t0 + 0.4, ended_at=t0 + 0.7, category="web", input_preview="query3"),
        ]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_bash_then_web_within_half_second_not_merged(self):
        """bash then web within 0.5s → separate groups (different category)."""
        t0 = 1000.0
        tools = [
            ToolUse(name="Bash", started_at=t0 + 0.0, ended_at=t0 + 0.3, category="bash"),
            ToolUse(name="WebSearch", started_at=t0 + 0.2, ended_at=t0 + 0.5, category="web"),
        ]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 2
        assert groups[0][0].category == "bash"
        assert groups[1][0].category == "web"

    def test_same_category_beyond_one_second_not_merged(self):
        """Same category but >1s apart → separate groups."""
        t0 = 1000.0
        tools = [
            ToolUse(name="WebSearch", started_at=t0 + 0.0, ended_at=t0 + 0.3, category="web"),
            ToolUse(name="WebSearch", started_at=t0 + 2.0, ended_at=t0 + 2.3, category="web"),
        ]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 2

    def test_empty_input_returns_empty(self):
        """Empty tool list → empty group list."""
        assert ToolTracker._merge_same_type_groups([]) == []

    def test_single_tool_returns_single_group(self):
        """Single tool → one group containing that tool."""
        tools = [ToolUse(name="Bash", started_at=100.0, ended_at=101.0, category="bash")]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 1
        assert groups[0][0].name == "Bash"

    def test_exactly_one_second_apart_merged(self):
        """Tools exactly 1.0 second apart are still merged (boundary inclusive)."""
        t0 = 1000.0
        tools = [
            ToolUse(name="WebSearch", started_at=t0 + 0.0, category="web"),
            ToolUse(name="WebSearch", started_at=t0 + 1.0, category="web"),
        ]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 1

    def test_interleaved_categories_split_correctly(self):
        """bash-web-bash sequence → 3 separate groups."""
        t0 = 1000.0
        tools = [
            ToolUse(name="Bash", started_at=t0 + 0.0, category="bash"),
            ToolUse(name="WebSearch", started_at=t0 + 0.1, category="web"),
            ToolUse(name="Bash", started_at=t0 + 0.2, category="bash"),
        ]
        groups = ToolTracker._merge_same_type_groups(tools)
        assert len(groups) == 3


# ---------------------------------------------------------------------------
# ToolTracker — build_progress_timeline with grouping
# ---------------------------------------------------------------------------


class TestBuildProgressTimelineGrouping:
    """Tests for same-type grouping in build_progress_timeline()."""

    def test_three_web_searches_produce_single_entry_with_count(self):
        """3 consecutive web searches within 0.5s → single timeline entry mentioning count."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name="WebSearch", started_at=t0 + 0.0, ended_at=t0 + 0.3, category="web", input_preview="query1"),
            ToolUse(name="WebSearch", started_at=t0 + 0.2, ended_at=t0 + 0.5, category="web", input_preview="query2"),
            ToolUse(name="WebSearch", started_at=t0 + 0.4, ended_at=t0 + 0.7, category="web", input_preview="query3"),
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        # All 3 web searches should collapse into a single entry.
        web_entries = [e for e in entries if e.icon == "🌐"]
        assert len(web_entries) == 1
        # The label should mention the count of 3.
        assert "3" in web_entries[0].text

    def test_bash_then_web_within_half_second_produce_two_entries(self):
        """bash then web within 0.5s → two separate timeline entries."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name="Bash", started_at=t0 + 0.0, ended_at=t0 + 0.3, category="bash"),
            ToolUse(name="WebSearch", started_at=t0 + 0.2, ended_at=t0 + 0.5, category="web"),
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        assert len(entries) == 2
        assert entries[0].icon == "💻"
        assert entries[1].icon == "🌐"

    def test_two_bash_commands_grouped(self):
        """2 bash commands within 1s → single entry with count."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name="Bash", started_at=t0 + 0.0, ended_at=t0 + 0.4, category="bash"),
            ToolUse(name="Bash", started_at=t0 + 0.5, ended_at=t0 + 0.9, category="bash"),
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        bash_entries = [e for e in entries if e.icon == "💻"]
        assert len(bash_entries) == 1
        assert "2" in bash_entries[0].text


# ---------------------------------------------------------------------------
# ToolTracker — build_progress_timeline with head/tail folding
# ---------------------------------------------------------------------------


class TestBuildProgressTimelineFolding:
    """Tests for head/tail folding in build_progress_timeline()."""

    def test_ten_entries_with_max_six_folds_correctly(self):
        """10 distinct tools with max_entries=6 → head(3) + skip + tail(3) = 7 entries.

        The folded output is head+skip+tail = 7 entries, which may slightly
        exceed max_entries.  max_entries only controls the trigger for folding,
        not the size of the folded output.
        """
        tracker = ToolTracker()
        t0 = 1000.0
        # Use widely spaced timestamps so no grouping occurs.
        tracker._tools = [
            ToolUse(name=f"Tool{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(10)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        # head(3) + "略過" + tail(3) = 7 entries
        assert len(entries) == 7

    def test_ten_entries_skip_entry_mentions_hidden_count(self):
        """Skip entry text includes the correct hidden count."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name=f"Tool{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(10)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        skip_entries = [e for e in entries if "略過" in e.text]
        assert len(skip_entries) == 1
        assert "4" in skip_entries[0].text  # 10 - 3 - 3 = 4 hidden

    def test_folded_head_entries_are_first_tools(self):
        """After folding, first 3 entries correspond to the first 3 tools."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name=f"T{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(10)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        # First 3 entries should reference T0, T1, T2
        for i, entry in enumerate(entries[:3]):
            assert f"T{i}" in entry.text

    def test_folded_tail_entries_are_last_tools(self):
        """After folding, last 3 entries correspond to the last 3 tools."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name=f"T{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(10)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        # Last 3 entries should reference T7, T8, T9
        for i, entry in enumerate(entries[-3:], start=7):
            assert f"T{i}" in entry.text

    def test_no_folding_when_within_max_entries(self):
        """No skip entry when tool count <= max_entries."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name=f"T{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(4)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        skip_entries = [e for e in entries if "略過" in e.text]
        assert skip_entries == []

    def test_skip_entry_icon_is_ellipsis(self):
        """Skip (fold) entry has the '…' icon."""
        tracker = ToolTracker()
        t0 = 1000.0
        tracker._tools = [
            ToolUse(name=f"T{i}", started_at=t0 + i * 10.0, ended_at=t0 + i * 10.0 + 1.0, category="other")
            for i in range(10)
        ]
        entries = tracker.build_progress_timeline(max_entries=6)
        skip_entries = [e for e in entries if "略過" in e.text]
        assert skip_entries[0].icon == "…"
