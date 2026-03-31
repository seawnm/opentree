"""Extract and persist user memory from conversation transcripts.

Uses simple heuristic pattern matching to identify memorable content
(preferences, facts, decisions) — does NOT call an LLM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEntry:
    """A single extracted memory item."""

    content: str
    category: str = "general"  # general, preference, fact, decision
    source: str = ""  # thread_ts or task description
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# Patterns that suggest memorable content.
# Each pattern must have exactly one capture group for the memorable text.
_REMEMBER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:remember|記住|記得|記下)\s*(?:that\s+|這件事：)?(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:my\s+(?:name|preference|favorite|habit)(?:\s+\w+)*\s+is)\s+(.+)", re.IGNORECASE),
    re.compile(r"(?:I\s+(?:prefer|like|want|need|use))\s+(.+)", re.IGNORECASE),
    re.compile(r"(?:always|never)\s+(.+)", re.IGNORECASE),
]


def extract_memories(
    conversation_text: str,
    user_name: str = "",
    thread_ts: str = "",
) -> list[MemoryEntry]:
    """Extract memorable content from conversation text.

    Uses pattern matching to find explicit "remember" requests and
    preference declarations.  Does NOT use LLM -- pure heuristic.

    Args:
        conversation_text: Full conversation transcript.
        user_name: User's display name (unused currently, reserved).
        thread_ts: Thread timestamp for sourcing.

    Returns:
        List of extracted memory entries (may be empty).
    """
    entries: list[MemoryEntry] = []
    seen: set[str] = set()

    for pattern in _REMEMBER_PATTERNS:
        for match in pattern.finditer(conversation_text):
            content = match.group(1).strip()
            # Skip trivially short matches.
            if not content or len(content) <= 3:
                continue
            # Deduplicate identical content from overlapping patterns.
            if content in seen:
                continue
            seen.add(content)

            category = _classify(match.group(0))
            source = f"thread:{thread_ts}" if thread_ts else ""
            entries.append(
                MemoryEntry(
                    content=content,
                    category=category,
                    source=source,
                )
            )

    return entries


def _classify(text: str) -> str:
    """Classify a memory entry into a category.

    Args:
        text: The memory content to classify.

    Returns:
        One of "preference", "decision", or "general".
    """
    lower = text.lower()
    if any(w in lower for w in ("prefer", "like", "favorite", "always", "never")):
        return "preference"
    if any(w in lower for w in ("decide", "chose", "picked", "selected")):
        return "decision"
    return "general"


def append_to_memory_file(
    memory_path: Path,
    entries: list[MemoryEntry],
) -> int:
    """Append memory entries to the user's memory.md file.

    Creates the file and parent directories if they don't exist.

    Args:
        memory_path: Path to the user's memory.md file.
        entries: List of memory entries to append.

    Returns:
        The number of entries written.
    """
    if not entries:
        return 0

    memory_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for entry in entries:
        date = entry.timestamp[:10]  # YYYY-MM-DD
        lines.append(f"- [{entry.category}] {entry.content} ({date})")

    text = "\n".join(lines) + "\n"

    # Append to existing file or create new with header.
    if memory_path.exists():
        existing = memory_path.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            text = "\n" + text
        memory_path.write_text(existing + text, encoding="utf-8")
    else:
        header = "# Memories\n\n"
        memory_path.write_text(header + text, encoding="utf-8")

    logger.info("Wrote %d memory entries to %s", len(entries), memory_path)
    return len(entries)
