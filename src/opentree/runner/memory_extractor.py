"""Extract and persist user memory from conversation transcripts.

Uses simple heuristic pattern matching to identify memorable content
(preferences, facts, decisions) — does NOT call an LLM.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from opentree.runner.memory_schema import MemorySchema, Section

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEntry:
    """A single extracted memory item."""

    content: str
    category: str = "general"  # general, preference, fact, decision, pinned
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

# The first pattern is the "remember" pattern — hits go to "pinned".
_REMEMBER_PATTERN = _REMEMBER_PATTERNS[0]


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

            # First pattern (remember/記住) → pinned, others → _classify
            if pattern is _REMEMBER_PATTERN:
                category = "pinned"
            else:
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


# ---------------------------------------------------------------------------
# Per-user locking for concurrent safety
# ---------------------------------------------------------------------------

_USER_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _get_user_lock(user_key: str) -> threading.Lock:
    with _LOCKS_LOCK:
        if user_key not in _USER_LOCKS:
            _USER_LOCKS[user_key] = threading.Lock()
        return _USER_LOCKS[user_key]


# Category → Section mapping
_CATEGORY_TO_SECTION: dict[str, Section] = {
    "pinned": Section.PINNED,
    "preference": Section.CORE,
    "decision": Section.CORE,
    "general": Section.ACTIVE,
}

# Regex for old-format lines: - [category] content (YYYY-MM-DD)
_OLD_FORMAT_RE = re.compile(
    r"^-\s+\[(\w+)\]\s+(.+?)(?:\s+\((\d{4}-\d{2}-\d{2})\))?\s*$"
)


def _is_old_format(content: str, doc) -> bool:
    """Detect old flat format: file has content but no section headers."""
    if not content.strip():
        return False
    # New format always has at least one "## <SectionName>" header
    has_section_headers = any(
        f"## {s.value}" in content for s in Section
    )
    total_items = sum(len(items) for items in doc.sections.values())
    return not has_section_headers and total_items == 0 and bool(content.strip())


def _migrate_old_format(content: str, doc) -> object:
    """Parse old '- [category] content (date)' lines into sections."""
    for line in content.splitlines():
        m = _OLD_FORMAT_RE.match(line.strip())
        if m:
            category, item_content, date = m.group(1), m.group(2), m.group(3) or ""
            section = _CATEGORY_TO_SECTION.get(category, Section.ACTIVE)
            MemorySchema.add_item(doc, section, item_content, date=date)
    migrated = sum(len(v) for v in doc.sections.values())
    if migrated:
        logger.info("Migrated %d old-format entries", migrated)
    return doc


def append_to_memory_file(
    memory_path: Path,
    entries: list[MemoryEntry],
    user_name: str = "",
) -> int:
    """Append memory entries to the user's memory.md file.

    Creates the file and parent directories if they don't exist.
    Uses four-section format (Pinned, Core, Episodes, Active).

    Args:
        memory_path: Path to the user's memory.md file.
        entries: List of memory entries to append.
        user_name: User's display name for file title.

    Returns:
        The number of entries written.
    """
    if not entries:
        return 0

    lock = _get_user_lock(str(memory_path))
    with lock:
        # Ensure file exists
        title = f"{user_name} 的記憶" if user_name else "記憶"
        MemorySchema.ensure_file(memory_path, title=title)

        # Parse existing
        content = memory_path.read_text(encoding="utf-8")
        doc = MemorySchema.parse(content)

        # Migration: detect old format
        if _is_old_format(content, doc):
            doc = _migrate_old_format(content, doc)

        # Add new entries
        added = 0
        today = datetime.now().strftime("%Y-%m-%d")
        for entry in entries:
            section = _CATEGORY_TO_SECTION.get(entry.category, Section.ACTIVE)
            date = entry.timestamp[:10] if entry.timestamp else today
            if MemorySchema.add_item(doc, section, entry.content, date=date):
                added += 1

        # Write
        MemorySchema._atomic_write(memory_path, MemorySchema.serialize(doc))
        if added:
            logger.info("Wrote %d memory entries to %s", added, memory_path)
        return added
