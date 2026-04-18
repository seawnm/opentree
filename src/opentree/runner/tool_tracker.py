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

TIMELINE_HEAD_COUNT = 3
TIMELINE_TAIL_COUNT = 3


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
        """Build timeline entries for the in-progress Slack panel.

        Applies two optimisations:
        1. Same-category grouping: consecutive tools with the same category
           whose ``started_at`` values are within ±1 second are merged into a
           single entry (with a count when > 1).
        2. Head/tail folding: when the entry count would exceed *max_entries*,
           the first ``TIMELINE_HEAD_COUNT`` and last ``TIMELINE_TAIL_COUNT``
           entries are kept and a "略過 N 個動作" separator is inserted in the
           middle instead of simply slicing off the tail.
        """
        entries: list[TimelineEntry] = []
        for kind, seconds in self._thinking_entries[-1:]:
            if kind == "deep_thinking":
                entries.append(TimelineEntry("🧠", f"深度思考 ({seconds} 秒)"))
            else:
                entries.append(TimelineEntry("🧠", f"思考 ({seconds} 秒)"))

        # Collect tools to display (include in-progress tool if any).
        tools: list[ToolUse] = list(self._tools)
        if self._current is not None:
            tools = tools + [self._current]

        # Group consecutive same-category tools within ±1 second.
        for group in self._merge_same_type_groups(tools):
            icon = _CATEGORY_ICON.get(group[0].category, "🔧")
            text = self._format_group(group)
            entries.append(TimelineEntry(icon, text))

        if self._thinking_started_at > 0:
            duration = int(time.time() - self._thinking_started_at)
            if duration >= self.THINKING_MIN_SECONDS:
                entries.append(TimelineEntry("🧠", f"思考中... ({duration} 秒)"))

        if self._generating:
            entries.append(TimelineEntry("📝", "生成回覆中..."))

        # Apply head/tail folding when entries exceed max_entries.
        # The folded output is always TIMELINE_HEAD_COUNT + 1 skip +
        # TIMELINE_TAIL_COUNT entries (= 7 by default), which may slightly
        # exceed max_entries — that is intentional.  Dynamic reduction of
        # head/tail only happens when max_entries is so small that even a
        # minimal 1+skip+1 fold wouldn't fit (pathological edge case).
        if len(entries) > max_entries:
            head = TIMELINE_HEAD_COUNT
            tail = TIMELINE_TAIL_COUNT
            # Minimum supported fold: 1 head + skip + 1 tail = 3.
            # Only reduce when max_entries cannot accommodate this minimum.
            if max_entries < 3:
                # Very constrained: reduce tail then head to fit within max_entries.
                while head + 1 + tail > max_entries and (head > 0 or tail > 0):
                    if tail > 0:
                        tail -= 1
                    elif head > 0:
                        head -= 1
            hidden = len(entries) - head - tail
            if hidden > 0:
                folded: list[TimelineEntry] = []
                folded.extend(entries[:head])
                folded.append(TimelineEntry("…", f"略過 {hidden} 個動作"))
                folded.extend(entries[len(entries) - tail:])
                entries = folded

        return entries

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
        category_previews: dict[str, list[str]] = {}
        for tool in self._tools:
            cat = tool.category
            category_counts[cat] = category_counts.get(cat, 0) + 1
            if tool.input_preview:
                preview = tool.input_preview.strip().replace("\n", " ")
                if preview:
                    category_previews.setdefault(cat, []).append(preview)

        def _pick_previews(cat: str, max_n: int = 2) -> list[str]:
            previews = category_previews.get(cat, [])
            # Deduplicate preserving order
            seen: set[str] = set()
            unique = []
            for p in previews:
                if p not in seen:
                    seen.add(p)
                    unique.append(p)
            return unique[:max_n]

        # --- expanded task subtask lines ---
        task_tools: list[ToolUse] = [t for t in self._tools if t.category == "task"]
        if self._current is not None and self._current.category == "task":
            task_tools = task_tools + [self._current]

        if task_tools:
            # Parent header line
            if len(task_tools) == 1 and task_tools[0].input_preview:
                raw = task_tools[0].input_preview.strip().replace("\n", " ")
                parent_desc = raw[:50] + "..." if len(raw) > 50 else raw
                items.append(f"🌟 {parent_desc}")
            else:
                items.append("🌟 子任務執行")
            # One indented line per task tool
            for t in task_tools:
                raw_preview = (t.input_preview or "").strip().replace("\n", " ")
                desc = raw_preview[:50] + "..." if len(raw_preview) > 50 else raw_preview
                if not desc:
                    desc = "子任務"
                dur_str = ToolTracker._format_duration(t.duration)
                if t.ended_at > 0:
                    items.append(f"  📋 {desc} ✅ {dur_str}")
                else:
                    items.append(f"  📋 {desc} (執行中 {dur_str})")

        if category_counts.get("bash"):
            count = category_counts["bash"]
            previews = _pick_previews("bash", 2)
            if previews:
                parts = []
                for p in previews:
                    parts.append(f"`{p[:40] + '...' if len(p) > 40 else p}`")
                suffix = f" 等 {count} 個" if count > len(parts) else ""
                items.append(f"💻 {', '.join(parts)}{suffix}")
            else:
                items.append(f"💻 執行指令 {count} 次")

        if category_counts.get("web"):
            count = category_counts["web"]
            previews = _pick_previews("web", 2)
            if previews:
                parts = []
                for p in previews:
                    parts.append(f'"{p[:30] + "..." if len(p) > 30 else p}"')
                suffix = f" 等 {count} 筆" if count > len(parts) else ""
                items.append(f"🌐 搜尋 {', '.join(parts)}{suffix}")
            else:
                items.append(f"🌐 搜尋網路 {count} 次")

        if category_counts.get("mcp"):
            count = category_counts["mcp"]
            previews = _pick_previews("mcp", 1)
            if previews:
                tool_names = list(dict.fromkeys(
                    t.name for t in self._tools if t.category == "mcp"
                ))[:2]
                items.append(f"🧩 {', '.join(tool_names)} 等 {count} 次" if count > 1 else f"🧩 {', '.join(tool_names)}")
            else:
                items.append(f"🧩 調用工具 {count} 次")

        other_count = category_counts.get("other", 0)
        if other_count:
            items.append(f"🔧 其他操作 {other_count} 次")

        return items

    def get_work_phase(self) -> str:
        """Return a coarse work-phase label for the live Slack panel."""
        if self._generating:
            return "📝 生成回覆中"

        recent_tools = self._tools[-4:]
        if self._current is not None:
            recent_tools = recent_tools + [self._current]

        if not recent_tools:
            return "🧠 思考中"

        category_counts: dict[str, int] = {}
        for tool in recent_tools:
            category_counts[tool.category] = category_counts.get(tool.category, 0) + 1

        max_count = max(category_counts.values())
        dominant_category = "other"
        for tool in reversed(recent_tools):
            if category_counts[tool.category] == max_count:
                dominant_category = tool.category
                break

        return _WORK_PHASE_LABEL.get(dominant_category, "🔧 處理中")

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

    @staticmethod
    def _merge_same_type_groups(tools: list[ToolUse]) -> list[list[ToolUse]]:
        """Split *tools* into groups of consecutive same-category items.

        Two adjacent tools belong to the same group when:
        - they share the same ``category``, **and**
        - their ``started_at`` values are within 1.0 second of each other.
        """
        groups: list[list[ToolUse]] = []
        for tool in tools:
            if (
                groups
                and groups[-1][0].category == tool.category
                and abs(tool.started_at - groups[-1][-1].started_at) <= 1.0
            ):
                groups[-1].append(tool)
            else:
                groups.append([tool])
        return groups

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into human-readable duration string."""
        if seconds >= 60:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"{m}m{s}s"
        else:
            return f"{int(seconds)}s"

    def _format_group(self, group: list[ToolUse]) -> str:
        """Format a merged group of same-category tools into a single label."""
        if len(group) == 1:
            tool = group[0]
            return self._format_tool_entry(tool)

        count = len(group)
        category = group[0].category

        if category == "web":
            first_preview = (group[0].input_preview or "").strip().replace("\n", " ")
            if first_preview:
                truncated = first_preview[:25] + "..." if len(first_preview) > 25 else first_preview
                return f"搜尋：{truncated} 等 {count} 筆"
            return f"搜尋 {count} 次"

        if category == "bash":
            return f"執行 {count} 個指令"

        if category == "task":
            return f"子任務 {count} 個"

        if category == "mcp":
            tool_names = list(dict.fromkeys(t.name for t in group))
            if len(tool_names) == 1:
                return f"{tool_names[0]} {count} 次"
            return f"調用工具 {count} 次"

        return f"操作 {count} 次"

    def _format_tool_entry(self, tool: ToolUse) -> str:
        preview = (tool.input_preview or "").strip().replace("\n", " ")
        if tool.ended_at > 0:
            dur = f" ({tool.duration:.1f}s)"
        else:
            elapsed = int(tool.duration)
            dur = f" (執行中 {elapsed}s)"

        if tool.category == "web":
            if preview:
                truncated = preview[:35] + "..." if len(preview) > 35 else preview
                return f"搜尋：{truncated}{dur}"
            return f"WebSearch{dur}"

        if tool.category == "bash":
            if preview:
                truncated = preview[:50] + "..." if len(preview) > 50 else preview
                return f"{truncated}{dur}"
            return f"執行指令{dur}"

        if tool.category == "mcp":
            label = tool.name
            if preview and len(preview) < 60:
                return f"{label}: {preview}{dur}"
            elif preview:
                return f"{label}: {preview[:30]}...{dur}"
            return f"{label}{dur}"

        if tool.category == "task":
            if preview:
                truncated = preview[:50] + "..." if len(preview) > 50 else preview
                return f"子任務 `{truncated}`{dur}"
            return f"子任務{dur}"

        # fallback (other)
        label = tool.name
        if preview:
            truncated = preview[:40] + "..." if len(preview) > 40 else preview
            return f"{label} `{truncated}`{dur}"
        return f"{label}{dur}"
