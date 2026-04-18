"""Smoke tests for 7 tool visibility improvements (Items 1-7).

Each test class covers one feature end-to-end through the public API.
"""
import time

import pytest

from opentree.runner.progress import build_progress_blocks
from opentree.runner.stream_parser import Phase, ProgressState
from opentree.runner.tool_tracker import DecisionPoint, ToolTracker


# ─── helpers ───────────────────────────────────────────────────────────────

def make_tool(tracker, category, preview, duration=1.0):
    """Add a completed tool to tracker."""
    tracker.start_tool("tool", preview, category)
    tracker._current.started_at = time.time() - duration
    tracker.end_tool()


def make_tool_at(tracker, category, preview, started_at):
    """Add a completed tool at a specific timestamp."""
    tracker.start_tool("tool", preview, category)
    tracker._current.started_at = started_at
    tracker._current.ended_at = started_at + 0.5
    tracker._tools.append(tracker._current)
    tracker._current = None


# ─── Item 1: Timeline same-type grouping ±1s ───────────────────────────────

class TestSmokeItem1Grouping:
    def test_three_web_searches_within_1s_merged(self):
        """3 web searches at nearly same time → single timeline entry with count."""
        tracker = ToolTracker()
        now = time.time()
        make_tool_at(tracker, "web", "query1", now)
        make_tool_at(tracker, "web", "query2", now + 0.3)
        make_tool_at(tracker, "web", "query3", now + 0.6)
        entries = tracker.build_progress_timeline(max_entries=10)
        # Should have only 1 entry for the 3 web tools (merged group)
        web_entries = [e for e in entries if e.icon == "🌐"]
        assert len(web_entries) == 1, (
            f"Expected 1 merged web entry, got {len(web_entries)}: {[e.text for e in web_entries]}"
        )
        assert "3" in web_entries[0].text or "筆" in web_entries[0].text, (
            f"Count not shown: {web_entries[0].text}"
        )

    def test_different_category_not_merged(self):
        """web then bash within 0.5s → separate entries."""
        tracker = ToolTracker()
        now = time.time()
        make_tool_at(tracker, "web", "search", now)
        make_tool_at(tracker, "bash", "ls -la", now + 0.2)
        entries = tracker.build_progress_timeline(max_entries=10)
        icons = [e.icon for e in entries]
        assert "🌐" in icons and "💻" in icons, f"Expected both icons, got {icons}"


# ─── Item 2: Timeline head/tail folding ────────────────────────────────────

class TestSmokeItem2Folding:
    def test_10_tools_with_max6_shows_fold_entry(self):
        """10 distinct tools with max_entries=6 → head + 略過 N + tail."""
        tracker = ToolTracker()
        now = time.time()
        for i in range(10):
            make_tool_at(tracker, "other", f"cmd{i}", now + (i * 2.0))
        entries = tracker.build_progress_timeline(max_entries=6)
        fold_entries = [e for e in entries if "略過" in e.text]
        assert len(fold_entries) == 1, (
            f"Expected exactly 1 fold entry, got {len(fold_entries)}: {[e.text for e in entries]}"
        )
        n = int("".join(c for c in fold_entries[0].text if c.isdigit()))
        assert n > 0, f"Hidden count should be > 0, got: {fold_entries[0].text}"

    def test_few_tools_no_fold(self):
        """5 tools with max_entries=6 → no fold entry."""
        tracker = ToolTracker()
        for i in range(5):
            make_tool(tracker, "other", f"cmd{i}", duration=0.1)
        entries = tracker.build_progress_timeline(max_entries=6)
        fold_entries = [e for e in entries if "略過" in e.text]
        assert len(fold_entries) == 0, f"Should not fold, but got: {[e.text for e in fold_entries]}"


# ─── Item 3: Work phase from recent 5 tools majority ───────────────────────

class TestSmokeItem3WorkPhase:
    def test_majority_web_returns_web_phase(self):
        """3 web + 1 bash → phase is web (majority)."""
        tracker = ToolTracker()
        for _ in range(3):
            make_tool(tracker, "web", "query")
        make_tool(tracker, "bash", "ls")
        phase = tracker.get_work_phase()
        assert "搜尋" in phase, f"Expected web phase, got: {phase}"

    def test_majority_bash_returns_bash_phase(self):
        """2 web + 3 bash → phase is bash."""
        tracker = ToolTracker()
        for _ in range(2):
            make_tool(tracker, "web", "query")
        for _ in range(3):
            make_tool(tracker, "bash", "cmd")
        phase = tracker.get_work_phase()
        assert "指令" in phase or "執行" in phase, f"Expected bash phase, got: {phase}"

    def test_generating_always_overrides(self):
        """Even with many tools, generating flag → 生成回覆中."""
        tracker = ToolTracker()
        for _ in range(5):
            make_tool(tracker, "web", "query")
        tracker.start_generating()
        phase = tracker.get_work_phase()
        assert "生成" in phase, f"Expected generating phase, got: {phase}"


# ─── Item 4: Task subtask expand ───────────────────────────────────────────

class TestSmokeItem4SubtaskExpand:
    def test_completed_task_shows_individual_line_with_duration(self):
        """Single completed task → 🌟 header + indented 📋 with ✅ and duration."""
        tracker = ToolTracker()
        make_tool(tracker, "task", "write tests", duration=10.0)
        items = tracker.build_completion_summary()
        text = "\n".join(items)
        assert "🌟" in text, f"Missing 🌟 header: {items}"
        assert "📋" in text, f"Missing 📋 subtask line: {items}"
        assert "✅" in text, f"Missing ✅: {items}"
        # Should show duration (e.g. "10s" or "0m10s")
        assert any(c.isdigit() and "s" in line for line in items for c in line), (
            f"No duration found: {items}"
        )

    def test_multiple_tasks_each_gets_own_line(self):
        """Two tasks → 🌟 header + 2 indented 📋 lines."""
        tracker = ToolTracker()
        make_tool(tracker, "task", "step one", duration=5.0)
        make_tool(tracker, "task", "step two", duration=8.0)
        items = tracker.build_completion_summary()
        subtask_lines = [l for l in items if "📋" in l]
        assert len(subtask_lines) == 2, f"Expected 2 subtask lines, got {len(subtask_lines)}: {items}"

    def test_inprogress_task_shows_running(self):
        """In-progress task (no end_time) → shows '執行中'."""
        tracker = ToolTracker()
        tracker.start_tool("task_tool", "long running", "task")
        items = tracker.build_completion_summary()
        text = "\n".join(items)
        assert "執行中" in text, f"Missing '執行中' for in-progress task: {items}"


# ─── Item 5: In-progress duration in timeline ──────────────────────────────

class TestSmokeItem5InProgressDuration:
    def test_current_tool_shows_executing_duration(self):
        """Tool started but not ended → timeline shows '執行中 Xs'."""
        tracker = ToolTracker()
        tracker.start_tool("WebSearch", "python tutorial", "web")
        tracker._current.started_at = time.time() - 5  # simulate 5s elapsed
        entries = tracker.build_progress_timeline(max_entries=10)
        web_entries = [e for e in entries if e.icon == "🌐"]
        assert len(web_entries) >= 1, f"No web entries: {entries}"
        assert "執行中" in web_entries[-1].text, f"Missing '執行中': {web_entries[-1].text}"

    def test_completed_tool_shows_float_duration(self):
        """Completed tool → timeline shows 'X.Xs' (no '執行中')."""
        tracker = ToolTracker()
        make_tool(tracker, "bash", "git status", duration=2.5)
        entries = tracker.build_progress_timeline(max_entries=10)
        bash_entries = [e for e in entries if e.icon == "💻"]
        assert len(bash_entries) >= 1, "No bash entries"
        assert "執行中" not in bash_entries[-1].text, (
            f"Should not show '執行中' for completed: {bash_entries[-1].text}"
        )
        assert "s)" in bash_entries[-1].text or "s" in bash_entries[-1].text, (
            f"No duration: {bash_entries[-1].text}"
        )


# ─── Item 6: Thinking excerpt ──────────────────────────────────────────────

class TestSmokeItem6ThinkingExcerpt:
    def test_thinking_excerpt_appears_after_thinking_line(self):
        """add_thinking_text() → completion summary includes 💭 excerpt."""
        tracker = ToolTracker()
        tracker._thinking_entries = [("thinking", 12)]
        tracker.add_thinking_text("We should check the database schema first before writing queries.")
        items = tracker.build_completion_summary()
        text = "\n".join(items)
        assert "🧠" in text, f"Missing 🧠 line: {items}"
        assert "💭" in text, f"Missing 💭 excerpt: {items}"

    def test_long_thinking_truncated_at_80(self):
        """Thinking text > 80 chars → truncated with '...'."""
        tracker = ToolTracker()
        tracker._thinking_entries = [("thinking", 20)]
        long_text = "A" * 100
        tracker.add_thinking_text(long_text)
        items = tracker.build_completion_summary()
        excerpt_lines = [l for l in items if "💭" in l]
        assert len(excerpt_lines) == 1
        # The excerpt content should be <= 80 chars + "..."
        content = excerpt_lines[0].replace("  💭 ", "")
        assert len(content) <= 84, f"Not truncated: {len(content)} chars: {content}"
        assert content.endswith("..."), f"Should end with '...': {content}"

    def test_no_thinking_text_no_excerpt(self):
        """No add_thinking_text() call → no 💭 line."""
        tracker = ToolTracker()
        tracker._thinking_entries = [("thinking", 8)]
        items = tracker.build_completion_summary()
        assert not any("💭" in l for l in items), f"Should not have 💭: {items}"


# ─── Item 7: Decision point block ──────────────────────────────────────────

class TestSmokeItem7DecisionPoint:
    def test_track_text_detects_decision(self):
        """Text matching a pattern → get_latest_decision() returns DecisionPoint."""
        tracker = ToolTracker()
        tracker.track_text("根據我的分析發現這裡需要修改三個地方")
        dp = tracker.get_latest_decision()
        assert dp is not None, "Should detect a decision point"
        assert len(dp.text) > 0

    def test_no_match_returns_none(self):
        """Non-matching text → get_latest_decision() returns None."""
        tracker = ToolTracker()
        tracker.track_text("Let me read this file first")
        assert tracker.get_latest_decision() is None

    def test_build_progress_blocks_with_decision_has_lightbulb_block(self):
        """build_progress_blocks(decision=dp) → blocks contain 💡 section."""
        state = ProgressState()
        state.phase = Phase.THINKING
        dp = DecisionPoint(text="根據分析發現需要重構這個模組", decision_type="analysis")
        blocks = build_progress_blocks(state=state, elapsed=10.0, decision=dp)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section" and "text" in b
        ]
        assert any("💡" in t for t in section_texts), f"No 💡 block found: {section_texts}"

    def test_build_progress_blocks_without_decision_no_lightbulb(self):
        """build_progress_blocks() without decision → no 💡 block."""
        state = ProgressState()
        state.phase = Phase.THINKING
        blocks = build_progress_blocks(state=state, elapsed=5.0)
        section_texts = [
            b["text"]["text"]
            for b in blocks
            if b.get("type") == "section" and "text" in b
        ]
        assert not any("💡" in t for t in section_texts), f"Should not have 💡: {section_texts}"
