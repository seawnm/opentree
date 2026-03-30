"""SessionManager: maps thread_ts -> session_id with JSON persistence.

Design decisions:
- Atomic save via write-to-.tmp-then-rename prevents partial writes from
  corrupting the sessions file.
- A threading.Lock protects concurrent in-process access.
- The data_dir must already exist; missing dir raises on first save so callers
  discover misconfiguration early.
- Corrupt or non-dict JSON files are silently treated as empty (graceful recovery).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SessionInfo:
    """Immutable record for a single thread -> session mapping."""

    session_id: str
    created_at: str    # ISO 8601 format
    last_used_at: str  # ISO 8601 format


class SessionManager:
    """Maps Slack thread_ts to Claude session_id with JSON persistence.

    The backing file is ``data_dir/sessions.json``.  It is written atomically
    (write to ``.tmp`` then ``Path.rename``) so a crash mid-write can never
    leave a partially-written file behind.

    Thread safety: a single ``threading.Lock`` serialises all mutations and
    the associated disk writes.  Reads are lock-free (Python GIL protects
    dict iteration for simple lookups).
    """

    def __init__(self, data_dir: Path) -> None:
        """Initialise the session manager.

        Args:
            data_dir: Directory where ``sessions.json`` will be stored.
                      Typically ``$OPENTREE_HOME/data/``.  The directory must
                      already exist; it is *not* created automatically so that
                      callers discover misconfiguration promptly.
        """
        self._data_dir = data_dir
        self._path = data_dir / "sessions.json"
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_session_id(self, thread_ts: str) -> Optional[str]:
        """Return the session_id for *thread_ts*, or ``None`` if not found."""
        info = self._sessions.get(thread_ts)
        return info.session_id if info is not None else None

    def set_session_id(self, thread_ts: str, session_id: str) -> None:
        """Create or update the session mapping for *thread_ts*.

        Persists the change to disk immediately.
        """
        now = datetime.now().isoformat()
        with self._lock:
            existing = self._sessions.get(thread_ts)
            if existing is not None:
                # Preserve original created_at; only bump last_used_at
                updated = SessionInfo(
                    session_id=session_id,
                    created_at=existing.created_at,
                    last_used_at=now,
                )
            else:
                updated = SessionInfo(
                    session_id=session_id,
                    created_at=now,
                    last_used_at=now,
                )
            # Build a new dict (immutability principle: never mutate existing objects)
            self._sessions = {**self._sessions, thread_ts: updated}
            self._save()

    def remove(self, thread_ts: str) -> None:
        """Remove the session mapping for *thread_ts*.

        No-op if the thread is not found.  Persists if a change was made.
        """
        with self._lock:
            if thread_ts not in self._sessions:
                return
            self._sessions = {k: v for k, v in self._sessions.items() if k != thread_ts}
            self._save()

    def cleanup_expired(self, max_age_days: int = 180) -> int:
        """Remove sessions whose ``last_used_at`` is older than *max_age_days*.

        Returns the number of sessions removed.
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(days=max_age_days)
            to_remove: list[str] = []

            for thread_ts, info in self._sessions.items():
                try:
                    last_used = datetime.fromisoformat(info.last_used_at)
                except ValueError:
                    continue
                if last_used < cutoff:
                    to_remove.append(thread_ts)

            if not to_remove:
                return 0

            self._sessions = {k: v for k, v in self._sessions.items() if k not in to_remove}
            self._save()

        return len(to_remove)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load sessions from the JSON file.

        Gracefully handles:
        - Missing file (treated as empty)
        - Invalid / corrupt JSON (treated as empty)
        - Valid JSON that is not a dict (treated as empty)
        """
        if not self._path.exists():
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupt or unreadable file — start fresh
            return

        if not isinstance(data, dict):
            return

        sessions: dict[str, SessionInfo] = {}
        for thread_ts, record in data.items():
            if not isinstance(record, dict):
                continue
            session_id = record.get("session_id", "")
            created_at = record.get("created_at", "")
            last_used_at = record.get("last_used_at", "")
            if session_id:
                sessions[thread_ts] = SessionInfo(
                    session_id=session_id,
                    created_at=created_at,
                    last_used_at=last_used_at,
                )

        self._sessions = sessions

    def _save(self) -> None:
        """Atomically write the current sessions to disk.

        Strategy: serialise to a ``.tmp`` file then ``Path.rename()`` over the
        target.  On POSIX systems ``rename`` is atomic; on Windows it is
        best-effort (Python replaces the destination file).

        Must be called while ``self._lock`` is held.
        """
        data = {
            thread_ts: {
                "session_id": info.session_id,
                "created_at": info.created_at,
                "last_used_at": info.last_used_at,
            }
            for thread_ts, info in self._sessions.items()
        }

        tmp_path = self._path.with_suffix(".tmp")
        # Will raise if data_dir does not exist — intentional (fail-fast)
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.rename(self._path)
