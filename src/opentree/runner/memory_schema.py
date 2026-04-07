"""Structured four-section memory storage for OpenTree."""
from __future__ import annotations

import enum
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class Section(enum.Enum):
    PINNED = "Pinned"
    CORE = "Core"
    EPISODES = "Episodes"
    ACTIVE = "Active"


# Reverse lookup: section header text -> Section enum
_HEADER_TO_SECTION: dict[str, Section] = {s.value.lower(): s for s in Section}


@dataclass
class MemoryItem:
    content: str
    source_tag: str = ""  # [explicit], [inferred], [semantic]
    date: str = ""  # YYYY-MM-DD


@dataclass
class MemoryDocument:
    title: str = ""
    sections: dict[Section, list[MemoryItem]] = field(
        default_factory=lambda: {s: [] for s in Section}
    )


# Regex for parsing item lines:
#   - [tag] content (YYYY-MM-DD)
#   - [tag] content
#   - content (YYYY-MM-DD)
#   - content
_ITEM_RE = re.compile(
    r"^-\s+"
    r"(?:\[(\w+)\]\s+)?"          # optional [tag]
    r"(.+?)"                      # content (non-greedy)
    r"(?:\s+\((\d{4}-\d{2}-\d{2})\))?"  # optional (date)
    r"\s*$"
)

_TITLE_RE = re.compile(r"^#\s+(.+)$")
_SECTION_RE = re.compile(r"^##\s+(.+)$")


class MemorySchema:
    """Parse, manipulate, and serialize four-section memory.md files."""

    @staticmethod
    def parse(content: str) -> MemoryDocument:
        """Parse markdown into MemoryDocument.

        Lines starting with '- ' under a section header are items.
        Lines with ## Header map to Section enum values.
        """
        doc = MemoryDocument()
        current_section: Section | None = None

        for line in content.splitlines():
            # Title line
            title_m = _TITLE_RE.match(line)
            if title_m:
                doc.title = title_m.group(1).strip()
                continue

            # Section header
            section_m = _SECTION_RE.match(line)
            if section_m:
                header = section_m.group(1).strip().lower()
                current_section = _HEADER_TO_SECTION.get(header)
                continue

            # Item line (only if we're inside a known section)
            if current_section is not None:
                item_m = _ITEM_RE.match(line)
                if item_m:
                    tag = item_m.group(1) or ""
                    item_content = item_m.group(2).strip()
                    date = item_m.group(3) or ""
                    doc.sections[current_section].append(
                        MemoryItem(content=item_content, source_tag=tag, date=date)
                    )

        return doc

    @staticmethod
    def serialize(doc: MemoryDocument) -> str:
        """Serialize MemoryDocument back to markdown."""
        lines: list[str] = []

        # Title
        title = doc.title or "記憶"
        lines.append(f"# {title}")
        lines.append("")

        for section in Section:
            lines.append(f"## {section.value}")
            items = doc.sections.get(section, [])
            for item in items:
                parts: list[str] = ["-"]
                if item.source_tag:
                    parts.append(f"[{item.source_tag}]")
                parts.append(item.content)
                if item.date:
                    parts.append(f"({item.date})")
                lines.append(" ".join(parts))
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def add_item(
        doc: MemoryDocument,
        section: Section,
        content: str,
        source_tag: str = "",
        date: str = "",
    ) -> bool:
        """Add item if not duplicate. Returns True if added."""
        normalized_new = MemorySchema._normalize_for_dedup(content)
        for existing in doc.sections[section]:
            if MemorySchema._normalize_for_dedup(existing.content) == normalized_new:
                return False  # duplicate
        doc.sections[section].append(
            MemoryItem(content=content, source_tag=source_tag, date=date)
        )
        return True

    @staticmethod
    def remove_item(doc: MemoryDocument, section: Section, keyword: str) -> int:
        """Remove items containing keyword. Returns count removed."""
        items = doc.sections[section]
        original_len = len(items)
        doc.sections[section] = [
            item for item in items if keyword not in item.content
        ]
        return original_len - len(doc.sections[section])

    @staticmethod
    def ensure_file(path: Path, title: str = "") -> None:
        """Create memory.md with four-section template if not exists."""
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = MemoryDocument(title=title or "記憶")
        MemorySchema._atomic_write(path, MemorySchema.serialize(doc))

    @staticmethod
    def _normalize_for_dedup(text: str) -> str:
        """Unicode NFKC + strip tags + strip dates + lowercase."""
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"\[\w+\]", "", text)  # remove [tag]
        text = re.sub(r"\(\d{4}-\d{2}-\d{2}\)", "", text)  # remove (date)
        return text.strip().lower()

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write atomically via tempfile + os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".memory_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
