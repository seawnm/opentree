"""Track tool usage during Claude CLI execution."""
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

    @property
    def duration(self) -> float:
        """Return elapsed seconds for this tool use.

        If the tool has not ended yet (ended_at <= 0), returns the time
        elapsed since started_at.  Otherwise returns the closed duration.
        """
        if self.ended_at <= 0:
            return time.time() - self.started_at
        return self.ended_at - self.started_at


class ToolTracker:
    """Tracks tool usage during a Claude CLI session.

    Usage::

        tracker = ToolTracker()
        tracker.start_tool("Bash", input_preview='{"command": "ls"}')
        # ... tool executes ...
        tracker.end_tool()
        tracker.finish()          # close any open tool
        print(tracker.build_timeline())
    """

    def __init__(self) -> None:
        self._tools: list[ToolUse] = []
        self._current: Optional[ToolUse] = None

    def start_tool(self, name: str, input_preview: str = "") -> None:
        """Record start of a tool use.

        If a previous tool is still open, it is auto-closed first.
        """
        if self._current is not None:
            self._current.ended_at = time.time()
            self._tools.append(self._current)
        self._current = ToolUse(name=name, input_preview=input_preview)

    def end_tool(self) -> None:
        """Record end of the current tool use."""
        if self._current is not None:
            self._current.ended_at = time.time()
            self._tools.append(self._current)
            self._current = None

    def finish(self) -> None:
        """Close any open tool and finalize tracking."""
        self.end_tool()

    @property
    def tools(self) -> list[ToolUse]:
        """Return a copy of the recorded tool list."""
        return list(self._tools)

    @property
    def total_tool_time(self) -> float:
        """Return total duration across all recorded tools."""
        return sum(t.duration for t in self._tools)

    def build_timeline(self, max_entries: int = 10) -> str:
        """Build a human-readable timeline string.

        Args:
            max_entries: Maximum number of tool entries to display.
                If there are more tools, an overflow indicator is shown.

        Returns:
            A formatted string, or empty string if no tools were recorded.
        """
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

    def get_summary(self) -> dict:
        """Return summary dict for status/logging.

        Returns:
            Dict with keys: tool_count, total_time, tools.
        """
        return {
            "tool_count": len(self._tools),
            "total_time": round(self.total_tool_time, 1),
            "tools": [
                {"name": t.name, "duration": round(t.duration, 1)}
                for t in self._tools
            ],
        }
