"""Track tool and thinking activity during Codex execution."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolUse:
    """Record of a single tool invocation."""

    name: str
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    input_preview: str = ""
    category: str = "other"

    @property
    def duration(self) -> float:
        """Return elapsed seconds for this tool use."""
        if self.ended_at <= 0:
            return time.time() - self.started_at
        return self.ended_at - self.started_at


@dataclass(frozen=True)
class TimelineEntry:
    """Compact timeline entry used for Slack progress display."""

    icon: str
    text: str


_CATEGORY_ICON = {
    "bash": "💻",
    "web": "🌐",
    "task": "📋",
    "mcp": "🧩",
    "other": "🔧",
}

_WORK_PHASE_LABEL = {
    "bash": "💻 執行指令中",
    "web": "🌐 搜尋網路中",
    "task": "📋 子任務中",
    "mcp": "🧩 調用工具中",
    "other": "🔧 處理中",
}


class ToolTracker:
    """Tracks tool usage and coarse thinking activity for Slack summaries."""

    THINKING_MIN_SECONDS = 5

    def __init__(self) -> None:
        self._tools: list[ToolUse] = []
        self._current: Optional[ToolUse] = None
        self._thinking_started_at: float = 0.0
        self._thinking_entries: list[tuple[str, int]] = []
        self._generating: bool = False

    def start_tool(
        self,
        name: str,
        input_preview: str = "",
        category: str = "other",
    ) -> None:
        """Record start of a tool use.

        If a previous tool is still open, it is auto-closed first.
        """
        if self._current is not None:
            self._current.ended_at = time.time()
            self._tools.append(self._current)
        self._current = ToolUse(
            name=name,
            input_preview=input_preview,
            category=category,
        )
        self._generating = False

    def end_tool(self) -> None:
        """Record end of the current tool use."""
        if self._current is not None:
            self._current.ended_at = time.time()
            self._tools.append(self._current)
            self._current = None

    def start_thinking(self, deep: bool = False) -> None:
        """Mark the start of a thinking period."""
        if self._thinking_started_at <= 0:
            self._thinking_started_at = time.time()
        elif deep and self._thinking_entries and self._thinking_entries[-1][0] == "thinking":
            self._thinking_entries[-1] = ("deep_thinking", self._thinking_entries[-1][1])
        self._generating = False

    def end_thinking(self, deep: bool = False) -> None:
        """Close the current thinking period if it exceeded the display threshold."""
        if self._thinking_started_at <= 0:
            return
        duration = int(time.time() - self._thinking_started_at)
        self._thinking_started_at = 0.0
        if duration < self.THINKING_MIN_SECONDS:
            return
        kind = "deep_thinking" if deep else "thinking"
        self._thinking_entries.append((kind, duration))

    def start_generating(self) -> None:
        """Mark that the model is writing the final response."""
        self._generating = True

    def finish(self) -> None:
        """Close any open activity and finalize tracking."""
        self.end_tool()
        self.end_thinking()

    @property
    def tools(self) -> list[ToolUse]:
        """Return a copy of the recorded tool list."""
        return list(self._tools)

    @property
    def total_tool_time(self) -> float:
        """Return total duration across all recorded tools."""
        return sum(t.duration for t in self._tools)

    def build_timeline(self, max_entries: int = 10) -> str:
        """Build a human-readable timeline string."""
        if not self._tools:
            return ""

        lines: list[str] = []
        visible = self._tools[-max_entries:]

        for tool in visible:
            dur = f"{tool.duration:.1f}s"
            lines.append(f"  {tool.name} ({dur})")

        if len(self._tools) > max_entries:
            overflow = len(self._tools) - max_entries
            lines.insert(0, f"  ... +{overflow} earlier tools")

        return "Tool timeline:\n" + "\n".join(lines)

    def build_progress_timeline(self, max_entries: int = 6) -> list[TimelineEntry]:
        """Build timeline entries for the in-progress Slack panel."""
        entries: list[TimelineEntry] = []
        for kind, seconds in self._thinking_entries[-1:]:
            if kind == "deep_thinking":
                entries.append(TimelineEntry("🧠", f"深度思考 ({seconds} 秒)"))
            else:
                entries.append(TimelineEntry("🧠", f"思考 ({seconds} 秒)"))

        tools = self._tools[-max_entries:]
        if self._current is not None:
            tools = (tools + [self._current])[-max_entries:]

        for tool in tools:
            icon = _CATEGORY_ICON.get(tool.category, "🔧")
            text = self._format_tool_entry(tool, include_duration=tool.ended_at > 0)
            entries.append(TimelineEntry(icon, text))

        if self._thinking_started_at > 0:
            duration = int(time.time() - self._thinking_started_at)
            if duration >= self.THINKING_MIN_SECONDS:
                entries.append(TimelineEntry("🧠", f"思考中... ({duration} 秒)"))

        if self._generating:
            entries.append(TimelineEntry("📝", "生成回覆中..."))

        return entries[-max_entries:]

    def build_completion_summary(self) -> list[str]:
        """Build summary lines for the completion progress message."""
        items: list[str] = []
        if self._thinking_entries:
            if len(self._thinking_entries) == 1:
                kind, seconds = self._thinking_entries[0]
                label = "深度思考" if kind == "deep_thinking" else "思考"
                items.append(f"🧠 {label} {seconds} 秒")
            else:
                parts = []
                for kind, seconds in self._thinking_entries:
                    label = "深度思考" if kind == "deep_thinking" else "思考"
                    parts.append(f"{label} {seconds} 秒")
                items.append(f"🧠 {' + '.join(parts)}")

        category_counts: dict[str, int] = {}
        for tool in self._tools:
            category_counts[tool.category] = category_counts.get(tool.category, 0) + 1

        if category_counts.get("task"):
            items.append(f"📋 子任務 {category_counts['task']} 次")
        if category_counts.get("bash"):
            items.append(f"💻 執行指令 {category_counts['bash']} 次")
        if category_counts.get("web"):
            items.append(f"🌐 搜尋網路 {category_counts['web']} 次")
        if category_counts.get("mcp"):
            items.append(f"🧩 調用工具 {category_counts['mcp']} 次")
        other_count = category_counts.get("other", 0)
        if other_count:
            items.append(f"🔧 其他操作 {other_count} 次")

        return items

    def get_work_phase(self) -> str:
        """Return a coarse work-phase label for the live Slack panel."""
        if self._current is not None:
            return _WORK_PHASE_LABEL.get(self._current.category, "🔧 處理中")
        if self._generating:
            return "📝 生成回覆中"
        if self._thinking_started_at > 0:
            return "🧠 思考中"
        if self._tools:
            return _WORK_PHASE_LABEL.get(self._tools[-1].category, "🔧 處理中")
        return "🧠 思考中"

    def get_summary(self) -> dict:
        """Return summary dict for status/logging."""
        return {
            "tool_count": len(self._tools),
            "total_time": round(self.total_tool_time, 1),
            "tools": [
                {"name": t.name, "duration": round(t.duration, 1)}
                for t in self._tools
            ],
        }

    def _format_tool_entry(self, tool: ToolUse, include_duration: bool) -> str:
        label = tool.name
        preview = (tool.input_preview or "").strip()
        if preview:
            preview = preview.replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            label = f"{label} `{preview}`"
        if include_duration:
            return f"{label} ({tool.duration:.1f}s)"
        return label
