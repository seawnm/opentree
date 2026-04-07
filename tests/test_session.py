"""Tests for SessionManager - written FIRST (TDD Red phase).

Tests thread_ts -> session_id mapping with JSON persistence.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from opentree.runner.session import SessionInfo, SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory."""
    return tmp_path


@pytest.fixture()
def manager(data_dir: Path) -> SessionManager:
    """SessionManager backed by a fresh tmp directory."""
    return SessionManager(data_dir)


# ---------------------------------------------------------------------------
# test_empty_sessions
# ---------------------------------------------------------------------------

class TestEmptySessions:
    def test_get_on_empty_returns_none(self, manager: SessionManager):
        assert manager.get_session_id("1234567890.123456") is None

    def test_initial_sessions_dict_is_empty(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        assert len(mgr._sessions) == 0

    def test_no_sessions_file_created_until_write(self, data_dir: Path):
        SessionManager(data_dir)
        assert not (data_dir / "sessions.json").exists()


# ---------------------------------------------------------------------------
# test_set_and_get
# ---------------------------------------------------------------------------

class TestSetAndGet:
    def test_set_then_get_returns_session_id(self, manager: SessionManager):
        manager.set_session_id("ts-001", "session-abc")
        result = manager.get_session_id("ts-001")
        assert result == "session-abc"

    def test_get_unknown_thread_returns_none(self, manager: SessionManager):
        manager.set_session_id("ts-known", "session-x")
        assert manager.get_session_id("ts-unknown") is None

    def test_set_overwrites_existing(self, manager: SessionManager):
        manager.set_session_id("ts-update", "old-session")
        manager.set_session_id("ts-update", "new-session")
        assert manager.get_session_id("ts-update") == "new-session"

    def test_set_updates_last_used_at(self, manager: SessionManager):
        before = datetime.now().isoformat()
        manager.set_session_id("ts-time", "ses-t")
        info = manager._sessions["ts-time"]
        assert info.last_used_at >= before

    def test_set_preserves_created_at_on_update(self, manager: SessionManager):
        manager.set_session_id("ts-create", "ses-v1")
        created = manager._sessions["ts-create"].created_at
        time.sleep(0.01)
        manager.set_session_id("ts-create", "ses-v2")
        assert manager._sessions["ts-create"].created_at == created

    def test_multiple_threads_independent(self, manager: SessionManager):
        manager.set_session_id("ts-a", "ses-a")
        manager.set_session_id("ts-b", "ses-b")
        assert manager.get_session_id("ts-a") == "ses-a"
        assert manager.get_session_id("ts-b") == "ses-b"


# ---------------------------------------------------------------------------
# test_persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_data_survives_reload(self, data_dir: Path):
        mgr1 = SessionManager(data_dir)
        mgr1.set_session_id("ts-persist", "ses-persist")

        mgr2 = SessionManager(data_dir)
        assert mgr2.get_session_id("ts-persist") == "ses-persist"

    def test_sessions_file_is_created_on_set(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-file", "ses-file")
        assert (data_dir / "sessions.json").exists()

    def test_sessions_file_is_valid_json(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-json", "ses-json")
        content = (data_dir / "sessions.json").read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_multiple_sessions_persisted(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-1", "ses-1")
        mgr.set_session_id("ts-2", "ses-2")
        mgr.set_session_id("ts-3", "ses-3")

        mgr2 = SessionManager(data_dir)
        assert mgr2.get_session_id("ts-1") == "ses-1"
        assert mgr2.get_session_id("ts-2") == "ses-2"
        assert mgr2.get_session_id("ts-3") == "ses-3"


# ---------------------------------------------------------------------------
# test_remove
# ---------------------------------------------------------------------------

class TestRemove:
    def test_remove_existing_session(self, manager: SessionManager):
        manager.set_session_id("ts-remove", "ses-x")
        manager.remove("ts-remove")
        assert manager.get_session_id("ts-remove") is None

    def test_remove_nonexistent_does_not_raise(self, manager: SessionManager):
        manager.remove("ts-never-existed")  # should not raise

    def test_remove_persists(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-del", "ses-del")
        mgr.remove("ts-del")

        mgr2 = SessionManager(data_dir)
        assert mgr2.get_session_id("ts-del") is None

    def test_remove_does_not_affect_other_sessions(self, manager: SessionManager):
        manager.set_session_id("ts-keep", "ses-keep")
        manager.set_session_id("ts-drop", "ses-drop")
        manager.remove("ts-drop")
        assert manager.get_session_id("ts-keep") == "ses-keep"


# ---------------------------------------------------------------------------
# test_cleanup_expired
# ---------------------------------------------------------------------------

class TestCleanupExpired:
    def _old_sessions_json(self, data_dir: Path, old_ts: str) -> None:
        """Write sessions.json with an old last_used_at timestamp."""
        data = {
            "ts-old": {
                "session_id": "ses-old",
                "created_at": old_ts,
                "last_used_at": old_ts,
            }
        }
        (data_dir / "sessions.json").write_text(json.dumps(data), encoding="utf-8")

    def test_cleanup_removes_expired(self, data_dir: Path):
        old = (datetime.now() - timedelta(days=200)).isoformat()
        self._old_sessions_json(data_dir, old)

        mgr = SessionManager(data_dir)
        removed = mgr.cleanup_expired(max_age_days=180)
        assert removed == 1
        assert mgr.get_session_id("ts-old") is None

    def test_cleanup_keeps_fresh_sessions(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-fresh", "ses-fresh")
        removed = mgr.cleanup_expired(max_age_days=180)
        assert removed == 0
        assert mgr.get_session_id("ts-fresh") == "ses-fresh"

    def test_cleanup_returns_count(self, data_dir: Path):
        old = (datetime.now() - timedelta(days=365)).isoformat()
        # Write 3 old sessions
        data = {
            f"ts-old-{i}": {
                "session_id": f"ses-old-{i}",
                "created_at": old,
                "last_used_at": old,
            }
            for i in range(3)
        }
        (data_dir / "sessions.json").write_text(json.dumps(data), encoding="utf-8")

        mgr = SessionManager(data_dir)
        removed = mgr.cleanup_expired(max_age_days=180)
        assert removed == 3

    def test_cleanup_empty_sessions(self, manager: SessionManager):
        removed = manager.cleanup_expired(max_age_days=180)
        assert removed == 0

    def test_cleanup_persists_removal(self, data_dir: Path):
        old = (datetime.now() - timedelta(days=200)).isoformat()
        self._old_sessions_json(data_dir, old)

        mgr = SessionManager(data_dir)
        mgr.cleanup_expired(max_age_days=180)

        mgr2 = SessionManager(data_dir)
        assert mgr2.get_session_id("ts-old") is None


# ---------------------------------------------------------------------------
# test_corrupt_file_recovery
# ---------------------------------------------------------------------------

class TestCorruptFileRecovery:
    def test_corrupt_json_loads_empty(self, data_dir: Path):
        (data_dir / "sessions.json").write_text("NOT JSON {{{{", encoding="utf-8")
        mgr = SessionManager(data_dir)
        assert len(mgr._sessions) == 0

    def test_corrupt_file_allows_subsequent_set(self, data_dir: Path):
        (data_dir / "sessions.json").write_text("corrupt", encoding="utf-8")
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-after-corrupt", "ses-ok")
        assert mgr.get_session_id("ts-after-corrupt") == "ses-ok"

    def test_non_dict_json_loads_empty(self, data_dir: Path):
        """JSON that is valid but not a dict (e.g., a list) should recover."""
        (data_dir / "sessions.json").write_text('["unexpected", "list"]', encoding="utf-8")
        mgr = SessionManager(data_dir)
        assert len(mgr._sessions) == 0


# ---------------------------------------------------------------------------
# test_missing_file
# ---------------------------------------------------------------------------

class TestMissingFile:
    def test_missing_file_starts_empty(self, data_dir: Path):
        assert not (data_dir / "sessions.json").exists()
        mgr = SessionManager(data_dir)
        assert len(mgr._sessions) == 0

    def test_missing_file_does_not_raise(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        assert mgr.get_session_id("ts-any") is None

    def test_missing_parent_dir_raises_on_save(self, tmp_path: Path):
        """If data_dir doesn't exist, saving should raise or be handled."""
        nonexistent = tmp_path / "no-such-dir"
        mgr = SessionManager(nonexistent)
        with pytest.raises(Exception):
            mgr.set_session_id("ts-fail", "ses-fail")


# ---------------------------------------------------------------------------
# test_atomic_save
# ---------------------------------------------------------------------------

class TestAtomicSave:
    def test_tmp_file_not_left_behind(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-atom", "ses-atom")
        tmp_files = list(data_dir.glob("*.tmp"))
        assert tmp_files == [], f"Unexpected .tmp files: {tmp_files}"

    def test_sessions_file_exists_after_save(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-exists", "ses-exists")
        assert (data_dir / "sessions.json").exists()

    def test_file_content_is_not_empty_after_save(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-content", "ses-content")
        content = (data_dir / "sessions.json").read_text(encoding="utf-8").strip()
        assert content != ""


# ---------------------------------------------------------------------------
# test_concurrent_access
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    def test_concurrent_writes_do_not_corrupt_data(self, data_dir: Path):
        """Basic thread safety: concurrent set_session_id calls should not corrupt the file."""
        mgr = SessionManager(data_dir)
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                mgr.set_session_id(f"ts-thread-{idx}", f"ses-thread-{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent writes: {errors}"

        # All written sessions should be readable
        for i in range(10):
            val = mgr.get_session_id(f"ts-thread-{i}")
            assert val == f"ses-thread-{i}", f"Missing session for ts-thread-{i}"

    def test_concurrent_reads_are_safe(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-read", "ses-read")
        results: list[str | None] = []
        errors: list[Exception] = []

        def reader() -> None:
            try:
                results.append(mgr.get_session_id("ts-read"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert all(r == "ses-read" for r in results)


# ---------------------------------------------------------------------------
# SessionInfo tests
# ---------------------------------------------------------------------------

class TestSessionInfo:
    def test_session_info_is_frozen(self):
        info = SessionInfo(session_id="s", created_at="2026-01-01", last_used_at="2026-01-02")
        with pytest.raises((AttributeError, TypeError)):
            info.session_id = "mutated"  # type: ignore[misc]

    def test_session_info_fields(self):
        info = SessionInfo(session_id="abc", created_at="2026-01-01T00:00:00", last_used_at="2026-01-02T12:00:00")
        assert info.session_id == "abc"
        assert info.created_at == "2026-01-01T00:00:00"
        assert info.last_used_at == "2026-01-02T12:00:00"


# ---------------------------------------------------------------------------
# test_clear_all
# ---------------------------------------------------------------------------

class TestClearAll:
    def test_clears_in_memory_sessions(self, manager: SessionManager):
        manager.set_session_id("ts-a", "ses-a")
        manager.set_session_id("ts-b", "ses-b")

        manager.clear_all()

        assert manager.get_session_id("ts-a") is None
        assert manager.get_session_id("ts-b") is None
        assert len(manager._sessions) == 0

    def test_clears_on_disk_sessions(self, data_dir: Path):
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-persist", "ses-persist")

        mgr.clear_all()

        # Reload from disk — should be empty
        mgr2 = SessionManager(data_dir)
        assert mgr2.get_session_id("ts-persist") is None
        assert len(mgr2._sessions) == 0

    def test_disk_file_exists_after_clear(self, data_dir: Path):
        """After clear_all, sessions.json should exist but contain empty dict."""
        mgr = SessionManager(data_dir)
        mgr.set_session_id("ts-x", "ses-x")
        mgr.clear_all()

        content = json.loads(
            (data_dir / "sessions.json").read_text(encoding="utf-8")
        )
        assert content == {}

    def test_clear_all_on_empty_is_noop(self, manager: SessionManager):
        """Clearing an already-empty manager should not raise."""
        manager.clear_all()
        assert len(manager._sessions) == 0

    def test_thread_safe(self, data_dir: Path):
        """Concurrent clear_all + set_session_id should not corrupt data."""
        mgr = SessionManager(data_dir)
        errors: list[Exception] = []

        def writer(idx: int) -> None:
            try:
                mgr.set_session_id(f"ts-{idx}", f"ses-{idx}")
            except Exception as e:
                errors.append(e)

        def clearer() -> None:
            try:
                mgr.clear_all()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        threads.append(threading.Thread(target=clearer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
