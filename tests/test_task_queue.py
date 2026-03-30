"""Tests for TaskQueue — written FIRST (TDD Red phase).

Tests cover:
  - Task dataclass defaults
  - submit: starts immediately vs queued
  - Per-thread serialization
  - Different threads run in parallel
  - mark_completed / mark_failed triggers next task
  - get_next_ready respects thread lock
  - FIFO ordering
  - get_stats
  - wait_for_drain (success + timeout)
  - Thread safety under concurrent access
"""
from __future__ import annotations

import threading
import time
from dataclasses import fields

import pytest

from opentree.runner.task_queue import Task, TaskQueue, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(
    task_id: str = "ch_ts_msg",
    channel_id: str = "C001",
    thread_ts: str = "1000.0001",
    user_id: str = "U001",
    user_name: str = "alice",
    text: str = "hello",
    message_ts: str = "1000.0002",
) -> Task:
    return Task(
        task_id=task_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        user_name=user_name,
        text=text,
        message_ts=message_ts,
    )


# ---------------------------------------------------------------------------
# test_task_dataclass_defaults
# ---------------------------------------------------------------------------

class TestTaskDataclass:
    def test_status_defaults_to_queued(self):
        t = make_task()
        assert t.status == TaskStatus.QUEUED

    def test_created_at_is_float(self):
        t = make_task()
        assert isinstance(t.created_at, float)
        assert t.created_at > 0

    def test_started_at_defaults_to_zero(self):
        t = make_task()
        assert t.started_at == 0.0

    def test_completed_at_defaults_to_zero(self):
        t = make_task()
        assert t.completed_at == 0.0

    def test_files_defaults_to_empty_list(self):
        t = make_task()
        assert t.files == []

    def test_files_are_independent_per_instance(self):
        """Each Task gets its own files list (no shared mutable default)."""
        t1 = make_task(task_id="t1")
        t2 = make_task(task_id="t2")
        t1.files.append({"name": "x.txt"})
        assert t2.files == []

    def test_task_status_enum_values(self):
        assert TaskStatus.QUEUED == "queued"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.TIMEOUT == "timeout"


# ---------------------------------------------------------------------------
# test_submit_starts_immediately
# ---------------------------------------------------------------------------

class TestSubmitStartsImmediately:
    def test_submit_under_limit_returns_true(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        result = q.submit(t)
        assert result is True

    def test_submitted_task_is_running(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        assert q.get_running_count() == 1

    def test_no_pending_after_immediate_start(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        assert q.get_pending_count() == 0

    def test_submit_two_different_threads_both_start(self):
        q = TaskQueue(max_concurrent=2)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        assert q.submit(t1) is True
        assert q.submit(t2) is True
        assert q.get_running_count() == 2


# ---------------------------------------------------------------------------
# test_submit_queued_at_limit
# ---------------------------------------------------------------------------

class TestSubmitQueuedAtLimit:
    def test_submit_at_limit_returns_false(self):
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        result = q.submit(t2)
        assert result is False

    def test_submit_at_limit_adds_to_pending(self):
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        q.submit(t2)
        assert q.get_pending_count() == 1
        assert q.get_running_count() == 1

    def test_multiple_tasks_queued_beyond_limit(self):
        q = TaskQueue(max_concurrent=2)
        for i in range(5):
            q.submit(make_task(task_id=f"t{i}", thread_ts=f"{i}000.0001"))
        assert q.get_running_count() == 2
        assert q.get_pending_count() == 3


# ---------------------------------------------------------------------------
# test_per_thread_serialization
# ---------------------------------------------------------------------------

class TestPerThreadSerialization:
    def test_same_thread_second_task_is_queued(self):
        """Even under global limit, same thread_ts must wait."""
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        q.submit(t1)
        result = q.submit(t2)
        assert result is False

    def test_same_thread_second_task_in_pending(self):
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        q.submit(t1)
        q.submit(t2)
        assert q.get_pending_count() == 1
        assert q.get_running_count() == 1

    def test_three_tasks_same_thread_only_one_running(self):
        q = TaskQueue(max_concurrent=10)
        for i in range(3):
            q.submit(make_task(task_id=f"t{i}", thread_ts="1000.0001"))
        assert q.get_running_count() == 1
        assert q.get_pending_count() == 2


# ---------------------------------------------------------------------------
# test_different_threads_parallel
# ---------------------------------------------------------------------------

class TestDifferentThreadsParallel:
    def test_different_threads_run_in_parallel(self):
        q = TaskQueue(max_concurrent=5)
        threads = ["t1", "t2", "t3"]
        for i, ts in enumerate(threads):
            result = q.submit(make_task(task_id=f"task{i}", thread_ts=ts))
            assert result is True, f"Task for thread {ts} should start immediately"
        assert q.get_running_count() == 3

    def test_global_limit_respected_across_different_threads(self):
        q = TaskQueue(max_concurrent=2)
        for i in range(4):
            q.submit(make_task(task_id=f"t{i}", thread_ts=f"{i}000.0001"))
        assert q.get_running_count() == 2
        assert q.get_pending_count() == 2


# ---------------------------------------------------------------------------
# test_mark_completed_starts_next
# ---------------------------------------------------------------------------

class TestMarkCompletedStartsNext:
    def test_completed_task_removed_from_running(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_completed(t)
        assert q.get_running_count() == 0

    def test_completed_starts_pending_global(self):
        """Completing a task should promote next pending (different thread)."""
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        q.submit(t2)
        assert q.get_pending_count() == 1
        q.mark_completed(t1)
        assert q.get_running_count() == 1
        assert q.get_pending_count() == 0

    def test_completed_starts_pending_same_thread(self):
        """Completing a task should promote same-thread pending."""
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        q.submit(t1)
        q.submit(t2)
        q.mark_completed(t1)
        assert q.get_running_count() == 1
        assert q.get_pending_count() == 0

    def test_completed_increments_completed_count(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_completed(t)
        stats = q.get_stats()
        assert stats["completed"] == 1

    def test_completed_task_status_updated(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_completed(t)
        assert t.status == TaskStatus.COMPLETED

    def test_completed_at_timestamp_set(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        before = time.time()
        q.mark_completed(t)
        after = time.time()
        assert before <= t.completed_at <= after


# ---------------------------------------------------------------------------
# test_mark_failed_starts_next
# ---------------------------------------------------------------------------

class TestMarkFailedStartsNext:
    def test_failed_task_removed_from_running(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_failed(t)
        assert q.get_running_count() == 0

    def test_failed_starts_next_pending(self):
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        q.submit(t2)
        q.mark_failed(t1)
        assert q.get_running_count() == 1
        assert q.get_pending_count() == 0

    def test_failed_increments_failed_count(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_failed(t)
        stats = q.get_stats()
        assert stats["failed"] == 1

    def test_failed_task_status_updated(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_failed(t)
        assert t.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# test_get_next_ready_respects_thread_lock
# ---------------------------------------------------------------------------

class TestGetNextReady:
    def test_no_pending_returns_none(self):
        q = TaskQueue(max_concurrent=2)
        assert q.get_next_ready() is None

    def test_pending_task_returned_when_slot_available(self):
        """A pending task for a free thread should be returned."""
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        q.submit(t2)
        # t1 running, t2 pending — slot is full so next_ready is None
        assert q.get_next_ready() is None

    def test_same_thread_pending_not_returned_while_running(self):
        """Same thread_ts pending must not be returned if that thread is running."""
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        q.submit(t1)
        q.submit(t2)
        # t1 running, t2 pending same thread — get_next_ready must return None
        assert q.get_next_ready() is None

    def test_different_thread_pending_returned_when_slot_free(self):
        """A different-thread pending task should be returned when a slot opens."""
        q = TaskQueue(max_concurrent=2)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        t3 = make_task(task_id="t3", thread_ts="3000.0003")
        q.submit(t1)
        q.submit(t2)
        q.submit(t3)  # pending (different thread, but global limit hit)
        # t1 and t2 running; complete t1 → slot opens → t3 can run
        q.mark_completed(t1)
        assert q.get_running_count() == 2  # t2 + t3
        assert q.get_pending_count() == 0


# ---------------------------------------------------------------------------
# test_get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_initial_stats(self):
        q = TaskQueue(max_concurrent=3)
        stats = q.get_stats()
        assert stats["running"] == 0
        assert stats["pending"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0
        assert stats["max_concurrent"] == 3

    def test_stats_after_submit(self):
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        q.submit(t2)
        stats = q.get_stats()
        assert stats["running"] == 1
        assert stats["pending"] == 1

    def test_stats_after_completion(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_completed(t)
        stats = q.get_stats()
        assert stats["running"] == 0
        assert stats["completed"] == 1

    def test_stats_after_failure(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        q.mark_failed(t)
        stats = q.get_stats()
        assert stats["running"] == 0
        assert stats["failed"] == 1


# ---------------------------------------------------------------------------
# test_fifo_order
# ---------------------------------------------------------------------------

class TestFifoOrder:
    def test_pending_tasks_start_in_fifo_order(self):
        """Tasks waiting in the global queue should start in submission order."""
        q = TaskQueue(max_concurrent=1)
        runner = make_task(task_id="runner", thread_ts="0000.0001")
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        t3 = make_task(task_id="t3", thread_ts="3000.0003")
        q.submit(runner)
        q.submit(t1)
        q.submit(t2)
        q.submit(t3)

        started_order: list[str] = []

        def complete_and_track(task: Task) -> None:
            started_order.append(task.task_id)

        # complete runner → t1 should start next
        q.mark_completed(runner)
        # find which task is now running
        next_t = q.get_next_ready()  # should be None (t1 already promoted)
        # Check running dict contains t1
        with q._lock:
            running_ids = list(q._running.keys())
        assert "t1" in running_ids

    def test_same_thread_pending_fifo(self):
        """Same-thread pending tasks must be served in FIFO order."""
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        t3 = make_task(task_id="t3", thread_ts="1000.0001")
        q.submit(t1)  # starts immediately
        q.submit(t2)  # pending
        q.submit(t3)  # pending

        q.mark_completed(t1)
        # t2 should be promoted (FIFO)
        with q._lock:
            running_ids = list(q._running.keys())
        assert "t2" in running_ids


# ---------------------------------------------------------------------------
# test_wait_for_drain_success
# ---------------------------------------------------------------------------

class TestWaitForDrainSuccess:
    def test_drain_no_tasks(self):
        q = TaskQueue(max_concurrent=2)
        result = q.wait_for_drain(timeout=1.0)
        assert result is True

    def test_drain_completes_when_tasks_finish(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)

        def complete_after_delay():
            time.sleep(0.1)
            q.mark_completed(t)

        threading.Thread(target=complete_after_delay, daemon=True).start()
        result = q.wait_for_drain(timeout=2.0)
        assert result is True


# ---------------------------------------------------------------------------
# test_wait_for_drain_timeout
# ---------------------------------------------------------------------------

class TestWaitForDrainTimeout:
    def test_drain_times_out_when_task_never_finishes(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        q.submit(t)
        # Don't complete the task — drain should time out
        start = time.time()
        result = q.wait_for_drain(timeout=0.3)
        elapsed = time.time() - start
        assert result is False
        # Should have waited roughly the timeout (allow generous 0.5s window)
        assert elapsed >= 0.25


# ---------------------------------------------------------------------------
# test_can_start
# ---------------------------------------------------------------------------

class TestCanStart:
    def test_can_start_when_empty(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        assert q.can_start(t) is True

    def test_cannot_start_when_at_global_limit(self):
        q = TaskQueue(max_concurrent=1)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        assert q.can_start(t2) is False

    def test_cannot_start_when_same_thread_running(self):
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="1000.0001")
        q.submit(t1)
        assert q.can_start(t2) is False

    def test_can_start_different_thread_under_limit(self):
        q = TaskQueue(max_concurrent=5)
        t1 = make_task(task_id="t1", thread_ts="1000.0001")
        t2 = make_task(task_id="t2", thread_ts="2000.0002")
        q.submit(t1)
        assert q.can_start(t2) is True


# ---------------------------------------------------------------------------
# test_mark_running
# ---------------------------------------------------------------------------

class TestMarkRunning:
    def test_mark_running_moves_task_to_running(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        # Manually place in pending, then mark_running
        with q._lock:
            q._pending.append(t)
        q.mark_running(t)
        assert q.get_running_count() == 1
        assert q.get_pending_count() == 0

    def test_mark_running_sets_status(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        with q._lock:
            q._pending.append(t)
        q.mark_running(t)
        assert t.status == TaskStatus.RUNNING

    def test_mark_running_sets_started_at(self):
        q = TaskQueue(max_concurrent=2)
        t = make_task()
        with q._lock:
            q._pending.append(t)
        before = time.time()
        q.mark_running(t)
        after = time.time()
        assert before <= t.started_at <= after


# ---------------------------------------------------------------------------
# test_thread_safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_submit_and_complete(self):
        """10 threads submit tasks concurrently; queue must remain consistent."""
        q = TaskQueue(max_concurrent=3)
        errors: list[Exception] = []
        completed_count = 0
        lock = threading.Lock()

        def worker(i: int) -> None:
            nonlocal completed_count
            try:
                t = make_task(
                    task_id=f"t{i}",
                    thread_ts=f"{i}000.{i:04d}",
                )
                started = q.submit(t)
                if started:
                    time.sleep(0.01)
                    q.mark_completed(t)
                    with lock:
                        completed_count += 1
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5.0)

        assert errors == [], f"Errors in threads: {errors}"
        stats = q.get_stats()
        total = (
            stats["running"]
            + stats["pending"]
            + stats["completed"]
            + stats["failed"]
        )
        assert total == 10

    def test_running_count_never_exceeds_max_concurrent(self):
        """Running count must never exceed max_concurrent even under contention."""
        max_c = 3
        q = TaskQueue(max_concurrent=max_c)
        violations: list[int] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            t = make_task(task_id=f"t{i}", thread_ts=f"{i}000.{i:04d}")
            q.submit(t)
            count = q.get_running_count()
            if count > max_c:
                with lock:
                    violations.append(count)
            time.sleep(0.005)
            if t.status == TaskStatus.RUNNING:
                q.mark_completed(t)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10.0)

        assert violations == [], f"Running count exceeded max: {violations}"
