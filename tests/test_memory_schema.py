"""Tests for memory_schema — TDD Red phase (written before implementation).

Tests cover:
  - parse: empty content, four sections, tags, title, unknown sections
  - serialize: roundtrip, empty sections have headers
  - add_item: adds to section, dedup exact, dedup case-insensitive, no dedup different
  - remove_item: removes matching, returns count
  - ensure_file: creates template, no-op if exists
  - _normalize_for_dedup: strips tags and dates, unicode normalization
  - _atomic_write: writes content correctly
"""
from __future__ import annotations

from pathlib import Path

from opentree.runner.memory_schema import (
    MemoryDocument,
    MemoryItem,
    MemorySchema,
    Section,
)


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

class TestParse:
    """Tests for MemorySchema.parse()."""

    def test_parse_empty(self) -> None:
        doc = MemorySchema.parse("")
        assert doc.title == ""
        for section in Section:
            assert doc.sections[section] == []

    def test_parse_four_sections(self) -> None:
        content = (
            "# Test\n\n"
            "## Pinned\n"
            "- item1 (2026-04-01)\n\n"
            "## Core\n"
            "- item2 (2026-04-02)\n\n"
            "## Episodes\n"
            "- item3 (2026-04-03)\n\n"
            "## Active\n"
            "- item4 (2026-04-04)\n"
        )
        doc = MemorySchema.parse(content)
        assert doc.title == "Test"
        assert len(doc.sections[Section.PINNED]) == 1
        assert doc.sections[Section.PINNED][0].content == "item1"
        assert doc.sections[Section.PINNED][0].date == "2026-04-01"
        assert len(doc.sections[Section.CORE]) == 1
        assert doc.sections[Section.CORE][0].content == "item2"
        assert len(doc.sections[Section.EPISODES]) == 1
        assert doc.sections[Section.EPISODES][0].content == "item3"
        assert len(doc.sections[Section.ACTIVE]) == 1
        assert doc.sections[Section.ACTIVE][0].content == "item4"

    def test_parse_with_tags(self) -> None:
        content = (
            "## Core\n"
            "- [explicit] tagged item (2026-04-01)\n"
            "- [inferred] another tagged (2026-04-02)\n"
        )
        doc = MemorySchema.parse(content)
        items = doc.sections[Section.CORE]
        assert len(items) == 2
        assert items[0].source_tag == "explicit"
        assert items[0].content == "tagged item"
        assert items[0].date == "2026-04-01"
        assert items[1].source_tag == "inferred"
        assert items[1].content == "another tagged"

    def test_parse_with_title(self) -> None:
        content = "# Walter 的記憶\n\n## Pinned\n- pin1 (2026-01-01)\n"
        doc = MemorySchema.parse(content)
        assert doc.title == "Walter 的記憶"
        assert len(doc.sections[Section.PINNED]) == 1

    def test_parse_unknown_section_ignored(self) -> None:
        content = (
            "## Unknown\n"
            "- should be ignored\n\n"
            "## Core\n"
            "- core item (2026-04-01)\n"
        )
        doc = MemorySchema.parse(content)
        assert len(doc.sections[Section.CORE]) == 1
        # Items under unknown section should not appear in any known section
        total = sum(len(items) for items in doc.sections.values())
        assert total == 1

    def test_parse_item_without_date(self) -> None:
        content = "## Active\n- no date item\n"
        doc = MemorySchema.parse(content)
        items = doc.sections[Section.ACTIVE]
        assert len(items) == 1
        assert items[0].content == "no date item"
        assert items[0].date == ""

    def test_parse_item_with_tag_no_date(self) -> None:
        content = "## Core\n- [semantic] tagged no date\n"
        doc = MemorySchema.parse(content)
        items = doc.sections[Section.CORE]
        assert len(items) == 1
        assert items[0].source_tag == "semantic"
        assert items[0].content == "tagged no date"
        assert items[0].date == ""


# ---------------------------------------------------------------------------
# serialize
# ---------------------------------------------------------------------------

class TestSerialize:
    """Tests for MemorySchema.serialize()."""

    def test_roundtrip(self) -> None:
        original = (
            "# Test Title\n\n"
            "## Pinned\n"
            "- pin item (2026-04-01)\n\n"
            "## Core\n"
            "- [explicit] core item (2026-04-02)\n\n"
            "## Episodes\n\n"
            "## Active\n"
            "- active item (2026-04-03)\n"
        )
        doc = MemorySchema.parse(original)
        result = MemorySchema.serialize(doc)
        # Re-parse to verify
        doc2 = MemorySchema.parse(result)
        assert doc2.title == "Test Title"
        assert len(doc2.sections[Section.PINNED]) == 1
        assert doc2.sections[Section.PINNED][0].content == "pin item"
        assert len(doc2.sections[Section.CORE]) == 1
        assert doc2.sections[Section.CORE][0].source_tag == "explicit"
        assert len(doc2.sections[Section.EPISODES]) == 0
        assert len(doc2.sections[Section.ACTIVE]) == 1

    def test_empty_sections_have_headers(self) -> None:
        doc = MemoryDocument(title="Empty")
        result = MemorySchema.serialize(doc)
        assert "## Pinned" in result
        assert "## Core" in result
        assert "## Episodes" in result
        assert "## Active" in result

    def test_serialize_with_tag(self) -> None:
        doc = MemoryDocument(title="Test")
        doc.sections[Section.CORE].append(
            MemoryItem(content="tagged", source_tag="explicit", date="2026-04-01")
        )
        result = MemorySchema.serialize(doc)
        assert "[explicit] tagged (2026-04-01)" in result

    def test_serialize_without_tag(self) -> None:
        doc = MemoryDocument(title="Test")
        doc.sections[Section.ACTIVE].append(
            MemoryItem(content="plain item", date="2026-04-01")
        )
        result = MemorySchema.serialize(doc)
        assert "- plain item (2026-04-01)" in result
        # Should NOT have empty brackets
        assert "[] " not in result

    def test_serialize_without_date(self) -> None:
        doc = MemoryDocument(title="Test")
        doc.sections[Section.ACTIVE].append(
            MemoryItem(content="no date item")
        )
        result = MemorySchema.serialize(doc)
        assert "- no date item" in result
        # Should not have trailing empty parens
        assert "()" not in result


# ---------------------------------------------------------------------------
# add_item
# ---------------------------------------------------------------------------

class TestAddItem:
    """Tests for MemorySchema.add_item()."""

    def test_adds_to_section(self) -> None:
        doc = MemoryDocument()
        added = MemorySchema.add_item(doc, Section.CORE, "new item", date="2026-04-01")
        assert added is True
        assert len(doc.sections[Section.CORE]) == 1
        assert doc.sections[Section.CORE][0].content == "new item"

    def test_dedup_exact_match(self) -> None:
        doc = MemoryDocument()
        MemorySchema.add_item(doc, Section.CORE, "duplicate item")
        added = MemorySchema.add_item(doc, Section.CORE, "duplicate item")
        assert added is False
        assert len(doc.sections[Section.CORE]) == 1

    def test_dedup_case_insensitive(self) -> None:
        doc = MemoryDocument()
        MemorySchema.add_item(doc, Section.CORE, "Prefer Dark Mode")
        added = MemorySchema.add_item(doc, Section.CORE, "prefer dark mode")
        assert added is False
        assert len(doc.sections[Section.CORE]) == 1

    def test_no_dedup_different_content(self) -> None:
        doc = MemoryDocument()
        MemorySchema.add_item(doc, Section.CORE, "item one")
        added = MemorySchema.add_item(doc, Section.CORE, "item two")
        assert added is True
        assert len(doc.sections[Section.CORE]) == 2

    def test_dedup_ignores_tags_and_dates(self) -> None:
        """Items that differ only in tag/date should still be considered duplicates."""
        doc = MemoryDocument()
        doc.sections[Section.CORE].append(
            MemoryItem(content="same item", source_tag="explicit", date="2026-01-01")
        )
        # Add same content but without tag/date
        added = MemorySchema.add_item(doc, Section.CORE, "same item")
        assert added is False


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------

class TestRemoveItem:
    """Tests for MemorySchema.remove_item()."""

    def test_removes_matching(self) -> None:
        doc = MemoryDocument()
        doc.sections[Section.ACTIVE].append(MemoryItem(content="remove me"))
        doc.sections[Section.ACTIVE].append(MemoryItem(content="keep me"))
        removed = MemorySchema.remove_item(doc, Section.ACTIVE, "remove")
        assert removed == 1
        assert len(doc.sections[Section.ACTIVE]) == 1
        assert doc.sections[Section.ACTIVE][0].content == "keep me"

    def test_returns_count(self) -> None:
        doc = MemoryDocument()
        doc.sections[Section.ACTIVE].append(MemoryItem(content="python is great"))
        doc.sections[Section.ACTIVE].append(MemoryItem(content="python rocks"))
        doc.sections[Section.ACTIVE].append(MemoryItem(content="java is ok"))
        removed = MemorySchema.remove_item(doc, Section.ACTIVE, "python")
        assert removed == 2
        assert len(doc.sections[Section.ACTIVE]) == 1

    def test_returns_zero_if_no_match(self) -> None:
        doc = MemoryDocument()
        doc.sections[Section.ACTIVE].append(MemoryItem(content="something"))
        removed = MemorySchema.remove_item(doc, Section.ACTIVE, "nomatch")
        assert removed == 0
        assert len(doc.sections[Section.ACTIVE]) == 1


# ---------------------------------------------------------------------------
# ensure_file
# ---------------------------------------------------------------------------

class TestEnsureFile:
    """Tests for MemorySchema.ensure_file()."""

    def test_creates_with_template(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "user" / "memory.md"
        MemorySchema.ensure_file(mem_path, title="Alice 的記憶")
        assert mem_path.exists()
        content = mem_path.read_text(encoding="utf-8")
        assert "# Alice 的記憶" in content
        assert "## Pinned" in content
        assert "## Core" in content
        assert "## Episodes" in content
        assert "## Active" in content

    def test_no_op_if_exists(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        mem_path.write_text("# Existing\n\n## Pinned\n", encoding="utf-8")
        MemorySchema.ensure_file(mem_path, title="New Title")
        content = mem_path.read_text(encoding="utf-8")
        # Should NOT overwrite
        assert "# Existing" in content
        assert "New Title" not in content

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "a" / "b" / "c" / "memory.md"
        MemorySchema.ensure_file(mem_path)
        assert mem_path.exists()

    def test_default_title(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        MemorySchema.ensure_file(mem_path)
        content = mem_path.read_text(encoding="utf-8")
        # Default title when none provided
        assert content.startswith("# ")


# ---------------------------------------------------------------------------
# _normalize_for_dedup
# ---------------------------------------------------------------------------

class TestNormalize:
    """Tests for MemorySchema._normalize_for_dedup()."""

    def test_strips_tags_and_dates(self) -> None:
        result = MemorySchema._normalize_for_dedup("[explicit] some content (2026-04-01)")
        assert "[explicit]" not in result
        assert "(2026-04-01)" not in result
        assert "some content" in result

    def test_unicode_normalization(self) -> None:
        # Full-width vs half-width
        normal = MemorySchema._normalize_for_dedup("Python")
        fullwidth = MemorySchema._normalize_for_dedup("\uff30\uff59\uff54\uff48\uff4f\uff4e")  # Ｐｙｔｈｏｎ
        assert normal == fullwidth

    def test_case_insensitive(self) -> None:
        assert MemorySchema._normalize_for_dedup("ABC") == MemorySchema._normalize_for_dedup("abc")

    def test_strips_whitespace(self) -> None:
        result = MemorySchema._normalize_for_dedup("  hello world  ")
        assert result == "hello world"


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    """Tests for MemorySchema._atomic_write()."""

    def test_writes_content(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        MemorySchema._atomic_write(path, "hello world\n")
        assert path.read_text(encoding="utf-8") == "hello world\n"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        path.write_text("old content", encoding="utf-8")
        MemorySchema._atomic_write(path, "new content")
        assert path.read_text(encoding="utf-8") == "new content"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "dir" / "test.md"
        MemorySchema._atomic_write(path, "content")
        assert path.read_text(encoding="utf-8") == "content"
