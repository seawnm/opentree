"""Tests for memory_extractor — TDD Red phase (written before implementation).

Tests cover:
  - extract_memories: "remember" pattern (English + Chinese)
  - extract_memories: preference patterns ("I prefer", "I like", "always", "never")
  - extract_memories: empty / no-match text returns []
  - extract_memories: trivially short matches (<= 3 chars) are skipped
  - extract_memories: source field populated from thread_ts
  - extract_memories: remember/記住 → pinned category
  - _classify: categories (preference, decision, general)
  - append_to_memory_file: new file creation with four-section format
  - append_to_memory_file: append to existing file (four-section format)
  - append_to_memory_file: empty entries returns 0 and does nothing
  - append_to_memory_file: creates parent directories
  - append_to_memory_file: old format migration
  - append_to_memory_file: concurrent safety
  - Integration: full extract + append flow
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from opentree.runner.memory_extractor import (
    MemoryEntry,
    append_to_memory_file,
    extract_memories,
    _classify,
)


# ---------------------------------------------------------------------------
# extract_memories — "remember" patterns
# ---------------------------------------------------------------------------

class TestExtractRememberPatterns:
    """Tests for explicit 'remember' keyword patterns."""

    def test_remember_that_english(self) -> None:
        text = "Please remember that I work at Acme Corp"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "Acme Corp" in entries[0].content

    def test_remember_chinese(self) -> None:
        text = "DOGI 記住我喜歡用 Python 寫程式"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "Python" in entries[0].content

    def test_remember_chinese_jide(self) -> None:
        text = "記得我的名字是 Walter"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "Walter" in entries[0].content

    def test_remember_chinese_jixia(self) -> None:
        text = "記下這件事：每週五要交報告"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "每週五" in entries[0].content


# ---------------------------------------------------------------------------
# extract_memories — "remember" → pinned category
# ---------------------------------------------------------------------------

class TestExtractRememberPinned:
    """Tests that remember/記住 patterns produce category='pinned'."""

    def test_remember_english_is_pinned(self) -> None:
        text = "remember that I work at Acme Corp"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert entries[0].category == "pinned"

    def test_remember_chinese_is_pinned(self) -> None:
        text = "記住我喜歡用 Python 寫程式"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert entries[0].category == "pinned"

    def test_remember_jide_is_pinned(self) -> None:
        text = "記得我的名字是 Walter"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert entries[0].category == "pinned"

    def test_remember_jixia_is_pinned(self) -> None:
        text = "記下這件事：每週五要交報告"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert entries[0].category == "pinned"


# ---------------------------------------------------------------------------
# extract_memories — preference patterns
# ---------------------------------------------------------------------------

class TestExtractPreferencePatterns:
    """Tests for preference declaration patterns."""

    def test_i_prefer(self) -> None:
        text = "I prefer dark mode for all editors"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "dark mode" in entries[0].content
        assert entries[0].category == "preference"

    def test_i_like(self) -> None:
        text = "I like using vim keybindings"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "vim" in entries[0].content

    def test_i_use(self) -> None:
        text = "I use zsh as my shell"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "zsh" in entries[0].content

    def test_always_pattern(self) -> None:
        text = "Always use TypeScript for frontend projects"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "TypeScript" in entries[0].content
        assert entries[0].category == "preference"

    def test_never_pattern(self) -> None:
        text = "Never use var in JavaScript"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "var" in entries[0].content
        assert entries[0].category == "preference"

    def test_my_name_is(self) -> None:
        text = "my name is Walter"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "Walter" in entries[0].content

    def test_my_favorite_is(self) -> None:
        text = "My favorite language is Rust"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "Rust" in entries[0].content


# ---------------------------------------------------------------------------
# extract_memories — edge cases
# ---------------------------------------------------------------------------

class TestExtractEdgeCases:
    """Tests for empty, no-match, and short-match edge cases."""

    def test_empty_text(self) -> None:
        assert extract_memories("") == []

    def test_no_match(self) -> None:
        text = "How do I sort a list in Python?"
        assert extract_memories(text) == []

    def test_short_match_skipped(self) -> None:
        """Matches with content <= 3 chars should be skipped."""
        text = "remember xy"
        assert extract_memories(text) == []

    def test_source_from_thread_ts(self) -> None:
        text = "remember that meetings are on Tuesday"
        entries = extract_memories(text, thread_ts="1234.5678")
        assert len(entries) == 1
        assert entries[0].source == "thread:1234.5678"

    def test_source_empty_when_no_thread_ts(self) -> None:
        text = "remember that meetings are on Tuesday"
        entries = extract_memories(text, thread_ts="")
        assert len(entries) == 1
        assert entries[0].source == ""

    def test_multiple_matches(self) -> None:
        text = (
            "remember that I work remote.\n"
            "I prefer async communication.\n"
            "Also, my name is Bob."
        )
        entries = extract_memories(text)
        assert len(entries) >= 3

    def test_case_insensitive(self) -> None:
        text = "REMEMBER that my timezone is UTC+8"
        entries = extract_memories(text)
        assert len(entries) == 1
        assert "UTC+8" in entries[0].content


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    """Tests for the _classify helper."""

    def test_preference_prefer(self) -> None:
        assert _classify("I prefer dark mode") == "preference"

    def test_preference_always(self) -> None:
        assert _classify("always use immutable data") == "preference"

    def test_preference_never(self) -> None:
        assert _classify("never use mutation") == "preference"

    def test_preference_like(self) -> None:
        assert _classify("I like functional programming") == "preference"

    def test_preference_favorite(self) -> None:
        assert _classify("my favorite editor is vim") == "preference"

    def test_decision_decided(self) -> None:
        assert _classify("we decided to use PostgreSQL") == "decision"

    def test_decision_chose(self) -> None:
        assert _classify("chose React over Vue") == "decision"

    def test_decision_selected(self) -> None:
        assert _classify("selected the second option") == "decision"

    def test_general_fallback(self) -> None:
        assert _classify("meetings are on Tuesday") == "general"


# ---------------------------------------------------------------------------
# append_to_memory_file — new file with four-section format
# ---------------------------------------------------------------------------

class TestAppendNewFile:
    """Tests for creating a new memory file with four-section format."""

    def test_creates_file_with_header(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="I work at Acme", category="general")
        count = append_to_memory_file(mem_path, [entry])
        assert count == 1
        text = mem_path.read_text(encoding="utf-8")
        # New format: four-section headers
        assert "## Pinned" in text
        assert "## Core" in text
        assert "## Episodes" in text
        assert "## Active" in text
        assert "I work at Acme" in text

    def test_creates_file_with_user_name_title(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="fact", category="general")
        append_to_memory_file(mem_path, [entry], user_name="Alice")
        text = mem_path.read_text(encoding="utf-8")
        assert "Alice" in text

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "data" / "memory" / "bob" / "memory.md"
        entry = MemoryEntry(content="some fact", category="general")
        count = append_to_memory_file(mem_path, [entry])
        assert count == 1
        assert mem_path.exists()

    def test_entry_format_has_date(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(
            content="dark mode preferred",
            category="preference",
            timestamp="2026-04-01T12:00:00",
        )
        append_to_memory_file(mem_path, [entry])
        text = mem_path.read_text(encoding="utf-8")
        assert "dark mode preferred" in text
        # Date should be in the output
        assert "2026-04" in text


# ---------------------------------------------------------------------------
# append_to_memory_file — existing file (four-section format)
# ---------------------------------------------------------------------------

class TestAppendExistingFile:
    """Tests for appending to an existing four-section memory file."""

    def test_append_preserves_existing(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        mem_path.write_text(
            "# Test\n\n"
            "## Pinned\n\n"
            "## Core\n\n"
            "## Episodes\n\n"
            "## Active\n"
            "- old entry (2026-01-01)\n",
            encoding="utf-8",
        )
        entry = MemoryEntry(content="new entry", category="general")
        count = append_to_memory_file(mem_path, [entry])
        assert count == 1
        text = mem_path.read_text(encoding="utf-8")
        assert "old entry" in text
        assert "new entry" in text

    def test_multiple_entries(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entries = [
            MemoryEntry(content="fact one", category="general"),
            MemoryEntry(content="fact two", category="preference"),
        ]
        count = append_to_memory_file(mem_path, entries)
        assert count == 2
        text = mem_path.read_text(encoding="utf-8")
        assert "fact one" in text
        assert "fact two" in text

    def test_preference_goes_to_core(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="dark mode preferred", category="preference")
        append_to_memory_file(mem_path, [entry])
        text = mem_path.read_text(encoding="utf-8")
        # Parse to verify it's in Core section
        from opentree.runner.memory_schema import MemorySchema, Section
        doc = MemorySchema.parse(text)
        assert len(doc.sections[Section.CORE]) == 1
        assert "dark mode" in doc.sections[Section.CORE][0].content

    def test_decision_goes_to_core(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="chose React", category="decision")
        append_to_memory_file(mem_path, [entry])
        text = mem_path.read_text(encoding="utf-8")
        from opentree.runner.memory_schema import MemorySchema, Section
        doc = MemorySchema.parse(text)
        assert len(doc.sections[Section.CORE]) == 1

    def test_general_goes_to_active(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="general fact", category="general")
        append_to_memory_file(mem_path, [entry])
        text = mem_path.read_text(encoding="utf-8")
        from opentree.runner.memory_schema import MemorySchema, Section
        doc = MemorySchema.parse(text)
        assert len(doc.sections[Section.ACTIVE]) == 1


# ---------------------------------------------------------------------------
# append_to_memory_file — pinned category (remember/記住)
# ---------------------------------------------------------------------------

class TestAppendPinned:
    """Tests that pinned category entries go to Pinned section."""

    def test_remember_goes_to_pinned(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        entry = MemoryEntry(content="I work at Acme Corp", category="pinned")
        append_to_memory_file(mem_path, [entry])
        text = mem_path.read_text(encoding="utf-8")
        from opentree.runner.memory_schema import MemorySchema, Section
        doc = MemorySchema.parse(text)
        assert len(doc.sections[Section.PINNED]) == 1
        assert "Acme Corp" in doc.sections[Section.PINNED][0].content


# ---------------------------------------------------------------------------
# append_to_memory_file — old format migration
# ---------------------------------------------------------------------------

class TestMigrationOldFormat:
    """Tests for migrating old flat format to four-section format."""

    def test_migration_old_format(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        # Old format: flat list with [category] tags, no section headers
        mem_path.write_text(
            "# Memories\n\n"
            "- [general] old entry one (2026-01-01)\n"
            "- [preference] dark mode preferred (2026-01-02)\n"
            "- [decision] chose React (2026-01-03)\n",
            encoding="utf-8",
        )
        # Append a new entry which should trigger migration
        entry = MemoryEntry(content="new fact", category="general")
        count = append_to_memory_file(mem_path, [entry])
        assert count == 1
        text = mem_path.read_text(encoding="utf-8")
        # After migration, should have four-section format
        assert "## Pinned" in text
        assert "## Core" in text
        assert "## Episodes" in text
        assert "## Active" in text
        # Old entries should be migrated
        assert "old entry one" in text
        assert "dark mode preferred" in text
        assert "chose React" in text
        # New entry should be added
        assert "new fact" in text


# ---------------------------------------------------------------------------
# append_to_memory_file — concurrent safety
# ---------------------------------------------------------------------------

class TestConcurrentAppend:
    """Tests for concurrent append safety with per-user locking."""

    def test_concurrent_append_safe(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                entry = MemoryEntry(content=f"concurrent item {i}", category="general")
                append_to_memory_file(mem_path, [entry])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent append: {errors}"
        text = mem_path.read_text(encoding="utf-8")
        # All 10 items should be present (dedup won't trigger because content differs)
        for i in range(10):
            assert f"concurrent item {i}" in text


# ---------------------------------------------------------------------------
# append_to_memory_file — empty entries
# ---------------------------------------------------------------------------

class TestAppendEmptyEntries:
    """Tests for empty entries edge case."""

    def test_returns_zero(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        assert append_to_memory_file(mem_path, []) == 0

    def test_does_not_create_file(self, tmp_path: Path) -> None:
        mem_path = tmp_path / "memory.md"
        append_to_memory_file(mem_path, [])
        assert not mem_path.exists()


# ---------------------------------------------------------------------------
# Integration: extract + append round-trip
# ---------------------------------------------------------------------------

class TestIntegration:
    """Full extract -> append round-trip."""

    def test_extract_and_append(self, tmp_path: Path) -> None:
        conversation = (
            "User: remember that my timezone is Asia/Taipei\n"
            "Bot: Got it!\n"
            "User: I prefer using uv over pip\n"
            "Bot: Noted.\n"
        )
        entries = extract_memories(
            conversation,
            user_name="walter",
            thread_ts="9999.0001",
        )
        assert len(entries) >= 2

        mem_path = tmp_path / "data" / "memory" / "walter" / "memory.md"
        count = append_to_memory_file(mem_path, entries, user_name="walter")
        assert count == len(entries)

        text = mem_path.read_text(encoding="utf-8")
        # Four-section format
        assert "## Pinned" in text
        assert "## Core" in text
        assert "## Active" in text
        assert "Asia/Taipei" in text
        assert "uv" in text

    def test_no_match_no_file(self, tmp_path: Path) -> None:
        conversation = "User: How do I sort a list?\nBot: Use sorted()."
        entries = extract_memories(conversation)
        assert entries == []
        mem_path = tmp_path / "memory.md"
        count = append_to_memory_file(mem_path, entries)
        assert count == 0
        assert not mem_path.exists()


# ---------------------------------------------------------------------------
# MemoryEntry dataclass
# ---------------------------------------------------------------------------

class TestMemoryEntry:
    """Tests for the MemoryEntry frozen dataclass."""

    def test_frozen(self) -> None:
        entry = MemoryEntry(content="test")
        with pytest.raises(AttributeError):
            entry.content = "modified"  # type: ignore[misc]

    def test_defaults(self) -> None:
        entry = MemoryEntry(content="test")
        assert entry.category == "general"
        assert entry.source == ""
        assert entry.timestamp  # non-empty default


# ---------------------------------------------------------------------------
# Dispatcher integration: memory extraction after successful task
# ---------------------------------------------------------------------------

class TestDispatcherMemoryIntegration:
    """Verify that Dispatcher._process_task calls memory extraction on success."""

    def _make_dispatcher(self, tmp_path: Path):
        """Create a minimal Dispatcher with mocked dependencies."""
        import threading
        from unittest.mock import MagicMock, patch

        from opentree.core.config import UserConfig
        from opentree.registry.models import RegistryData
        from opentree.runner.config import RunnerConfig
        from opentree.runner.dispatcher import Dispatcher

        slack_api = MagicMock()
        slack_api.send_message.return_value = {"ts": "9999.0001"}
        slack_api.update_message.return_value = {"ts": "9999.0001"}
        slack_api.bot_user_id = "UBOT123"
        slack_api.get_user_display_name.return_value = "alice"

        shutdown_event = threading.Event()

        fake_user_config = UserConfig(
            bot_name="TestBot",
            team_name="TestTeam",
            opentree_home=str(tmp_path),
        )
        fake_runner_config = RunnerConfig(
            max_concurrent_tasks=2,
            task_timeout=30,
        )
        fake_registry = RegistryData(version=1, modules=())

        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "workspace").mkdir(exist_ok=True)
        (tmp_path / "config").mkdir(exist_ok=True)

        with (
            patch("opentree.runner.dispatcher.load_user_config", return_value=fake_user_config),
            patch("opentree.runner.dispatcher.load_runner_config", return_value=fake_runner_config),
            patch("opentree.runner.dispatcher.Registry.load", return_value=fake_registry),
        ):
            dispatcher = Dispatcher(
                opentree_home=tmp_path,
                slack_api=slack_api,
                shutdown_event=shutdown_event,
            )

        dispatcher._slack = slack_api
        return dispatcher

    def _make_result(self, **kwargs):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.is_error = kwargs.get("is_error", False)
        result.is_timeout = kwargs.get("is_timeout", False)
        result.response_text = kwargs.get("response_text", "OK")
        result.session_id = kwargs.get("session_id", "sess-001")
        result.error_message = kwargs.get("error_message", "")
        result.elapsed_seconds = kwargs.get("elapsed_seconds", 1.5)
        result.input_tokens = kwargs.get("input_tokens", 100)
        result.output_tokens = kwargs.get("output_tokens", 50)
        return result

    def test_memories_extracted_on_success(self, tmp_path: Path) -> None:
        """When Claude response contains memorable content, it is written to memory file."""
        from unittest.mock import patch

        from opentree.runner.task_queue import Task, TaskStatus

        dispatcher = self._make_dispatcher(tmp_path)
        task = Task(
            task_id="C001_1000.0_1000.1",
            channel_id="C001",
            thread_ts="1000.0001",
            user_id="U001",
            user_name="alice",
            text="remember that I work at Acme Corp",
            message_ts="1000.0002",
        )
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result(
            response_text="I'll remember that you work at Acme Corp",
        )

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch(
                "opentree.runner.memory_extractor.extract_memories",
                wraps=extract_memories,
            ) as mock_extract,
            patch(
                "opentree.runner.memory_extractor.append_to_memory_file",
                wraps=append_to_memory_file,
            ) as mock_append,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # extract_memories was called with response text.
        mock_extract.assert_called_once()
        call_kwargs = mock_extract.call_args
        assert fake_result.response_text in call_kwargs[0][0]

    def test_no_memory_on_error(self, tmp_path: Path) -> None:
        """Memory extraction is skipped when Claude returns an error."""
        from unittest.mock import patch

        from opentree.runner.task_queue import Task, TaskStatus

        dispatcher = self._make_dispatcher(tmp_path)
        task = Task(
            task_id="C001_1000.0_1000.1",
            channel_id="C001",
            thread_ts="1000.0001",
            user_id="U001",
            user_name="alice",
            text="remember something",
            message_ts="1000.0002",
        )
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result(is_error=True, error_message="Claude failed")

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch(
                "opentree.runner.memory_extractor.extract_memories",
            ) as mock_extract,
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # extract_memories should NOT be called when result is error.
        mock_extract.assert_not_called()

    def test_memory_extraction_failure_does_not_break_task(self, tmp_path: Path) -> None:
        """If memory extraction raises, the task still completes successfully."""
        from unittest.mock import patch

        from opentree.runner.task_queue import Task, TaskStatus

        dispatcher = self._make_dispatcher(tmp_path)
        task = Task(
            task_id="C001_1000.0_1000.1",
            channel_id="C001",
            thread_ts="1000.0001",
            user_id="U001",
            user_name="alice",
            text="hello",
            message_ts="1000.0002",
        )
        task.status = TaskStatus.RUNNING

        fake_result = self._make_result(response_text="remember that sky is blue")

        def _exploding_extract(*args, **kwargs):
            raise RuntimeError("boom")

        with (
            patch("opentree.runner.dispatcher.assemble_system_prompt", return_value="sys"),
            patch("opentree.runner.dispatcher.ClaudeProcess") as MockClaude,
            patch("opentree.runner.dispatcher.build_thread_context", return_value=""),
            patch("opentree.runner.dispatcher.cleanup_temp"),
            patch(
                "opentree.runner.memory_extractor.extract_memories",
                side_effect=_exploding_extract,
            ),
        ):
            MockClaude.return_value.run.return_value = fake_result
            dispatcher._process_task(task)

        # Task should still be completed, not failed.
        assert task.status == TaskStatus.COMPLETED
