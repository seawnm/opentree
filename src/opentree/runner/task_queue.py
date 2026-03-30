"""Task queue with concurrency control for OpenTree bot runner."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Task:
    """A single task in the queue.

    Thread-safety contract:
    - Immutable fields (task_id, channel_id, thread_ts, user_id, user_name,
      message_ts, files) are written once at creation and never mutated.
      Worker threads may read these without holding a lock.
    - Mutable fields (status, started_at, completed_at, text) are only written
      by TaskQueue methods that hold ``TaskQueue._lock``.  Worker threads must
      not write these fields directly.  CPython's GIL makes concurrent attribute
      reads safe, but callers should not rely on observing a consistent
      (status, started_at) pair without holding the lock.

    Note: A fully frozen dataclass + separate status dict would eliminate this
    GIL dependency.  That refactor is deferred; the above contract is sufficient
    for correctness in CPython.
    """

    task_id: str            # unique ID (e.g., f"{channel}_{thread_ts}_{ts}")
    channel_id: str
    thread_ts: str
    user_id: str
    user_name: str
    text: str
    message_ts: str         # the triggering message's ts
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    files: list[dict] = field(default_factory=list)  # attached files


class TaskQueue:
    """Concurrent task queue with per-thread serialization.

    - Global concurrency limit: max_concurrent tasks running at once.
    - Per-thread serialization: only 1 task per thread_ts at a time.
    - Tasks for the same thread_ts wait in FIFO order.
    """

    def __init__(self, max_concurrent: int = 2) -> None:
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._running: dict[str, Task] = {}     # task_id -> Task (running)
        self._pending: list[Task] = []            # FIFO queue
        self._thread_running: set[str] = set()   # thread_ts with running task
        self._completed_count: int = 0
        self._failed_count: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def submit(self, task: Task) -> bool:
        """Add a task to the queue.

        Returns True if task can start immediately, False if queued.
        """
        with self._lock:
            if self._can_start_locked(task):
                self._start_task_locked(task)
                logger.debug(
                    "task %s started immediately (running=%d)",
                    task.task_id,
                    len(self._running),
                )
                return True

            self._pending.append(task)
            logger.debug(
                "task %s queued (pending=%d, running=%d)",
                task.task_id,
                len(self._pending),
                len(self._running),
            )
            return False

    def can_start(self, task: Task) -> bool:
        """Check whether a task can start now.

        A task can start when:
        - The global running count is below max_concurrent, AND
        - No other task is already running for the same thread_ts.
        """
        with self._lock:
            return self._can_start_locked(task)

    def mark_running(self, task: Task) -> None:
        """Move task from pending to running."""
        with self._lock:
            # Remove from pending if present
            try:
                self._pending.remove(task)
            except ValueError:
                pass  # already removed or never was pending

            self._start_task_locked(task)

    def mark_completed(self, task: Task) -> None:
        """Mark task as completed and promote next eligible pending task."""
        with self._lock:
            self._finish_task_locked(task, TaskStatus.COMPLETED)
            self._completed_count += 1
            task.completed_at = time.time()
            self._promote_next_locked()

    def mark_failed(self, task: Task) -> None:
        """Mark task as failed and promote next eligible pending task."""
        with self._lock:
            self._finish_task_locked(task, TaskStatus.FAILED)
            self._failed_count += 1
            self._promote_next_locked()

    def get_next_ready(self) -> Optional[Task]:
        """Return the next pending task that can start, or None.

        Does NOT start the task — caller is responsible for calling
        mark_running() if they want to promote it.
        """
        with self._lock:
            for task in self._pending:
                if self._can_start_locked(task):
                    return task
            return None

    def get_running_count(self) -> int:
        """Number of currently running tasks."""
        with self._lock:
            return len(self._running)

    def get_pending_count(self) -> int:
        """Number of pending tasks."""
        with self._lock:
            return len(self._pending)

    def get_stats(self) -> dict:
        """Return queue statistics."""
        with self._lock:
            return {
                "running": len(self._running),
                "pending": len(self._pending),
                "completed": self._completed_count,
                "failed": self._failed_count,
                "max_concurrent": self._max_concurrent,
            }

    def wait_for_drain(self, timeout: float = 30.0) -> bool:
        """Wait for all running tasks to complete.

        Returns True if drained within timeout, False otherwise.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self._running:
                    return True
            time.sleep(0.05)
        with self._lock:
            return not self._running

    # ------------------------------------------------------------------
    # Private helpers (must be called with _lock held)
    # ------------------------------------------------------------------

    def _can_start_locked(self, task: Task) -> bool:
        """Internal: check start eligibility. Caller must hold _lock."""
        if len(self._running) >= self._max_concurrent:
            return False
        if task.thread_ts in self._thread_running:
            return False
        return True

    def _start_task_locked(self, task: Task) -> None:
        """Internal: unconditionally start a task. Caller must hold _lock."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self._running[task.task_id] = task
        self._thread_running.add(task.thread_ts)

    def _finish_task_locked(self, task: Task, status: TaskStatus) -> None:
        """Internal: remove a task from running state. Caller must hold _lock."""
        task.status = status
        self._running.pop(task.task_id, None)
        # Only clear the thread lock if this task was the one holding it
        if task.thread_ts in self._thread_running:
            # Verify no other running task owns this thread_ts
            still_running = any(
                t.thread_ts == task.thread_ts
                for t in self._running.values()
            )
            if not still_running:
                self._thread_running.discard(task.thread_ts)

    def _promote_next_locked(self) -> None:
        """Internal: start as many pending tasks as slots allow. Caller must hold _lock."""
        i = 0
        while i < len(self._pending):
            if len(self._running) >= self._max_concurrent:
                break
            candidate = self._pending[i]
            if self._can_start_locked(candidate):
                self._pending.pop(i)
                self._start_task_locked(candidate)
                logger.debug(
                    "task %s promoted from pending (running=%d)",
                    candidate.task_id,
                    len(self._running),
                )
                # Restart scan from beginning to find any newly eligible tasks
                i = 0
            else:
                i += 1
