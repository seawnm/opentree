"""Tests for CircuitBreaker — TDD Red phase (written before implementation).

Tests cover:
  - Initial state is CLOSED
  - State transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
  - allow_request for each state
  - Failure counting and threshold
  - Recovery timeout triggers HALF_OPEN
  - record_success in HALF_OPEN transitions to CLOSED
  - record_failure in HALF_OPEN transitions back to OPEN
  - get_status returns correct dict
  - Thread safety under concurrent access
  - Custom config values
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from opentree.runner.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    """CircuitBreaker should start in CLOSED state with zero failures."""

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_is_zero(self) -> None:
        cb = CircuitBreaker()
        status = cb.get_status()
        assert status["failure_count"] == 0

    def test_initial_allows_requests(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow_request() is True


# ---------------------------------------------------------------------------
# CLOSED state behaviour
# ---------------------------------------------------------------------------


class TestClosedState:
    """In CLOSED state, requests pass through and failures are counted."""

    def test_allows_requests(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_single_failure_stays_closed(self) -> None:
        cb = CircuitBreaker()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_failures_below_threshold_stay_closed(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(config)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(config)
        for _ in range(3):
            cb.record_failure()
        cb.record_success()
        status = cb.get_status()
        assert status["failure_count"] == 0

    def test_success_after_partial_failures_stays_closed(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(config)
        for _ in range(4):
            cb.record_failure()
        cb.record_success()
        # Need full threshold again to trip
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# CLOSED -> OPEN transition
# ---------------------------------------------------------------------------


class TestClosedToOpen:
    """Circuit should trip OPEN after reaching failure threshold."""

    def test_trips_at_threshold(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_rejects_requests_when_open(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)
        for _ in range(3):
            cb.record_failure()
        assert cb.allow_request() is False

    def test_additional_failures_stay_open(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(config)
        for _ in range(10):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_default_threshold_is_five(self) -> None:
        cb = CircuitBreaker()
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# OPEN -> HALF_OPEN transition (recovery timeout)
# ---------------------------------------------------------------------------


class TestOpenToHalfOpen:
    """After recovery_timeout elapses, state should transition to HALF_OPEN."""

    def test_transitions_after_timeout(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_allows_probe_request_in_half_open(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        assert cb.allow_request() is True

    def test_stays_open_before_timeout(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=10.0)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()
        # No sleep — timeout hasn't elapsed
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_transition_uses_mocked_time(self) -> None:
        """Test OPEN -> HALF_OPEN with mocked time to avoid real sleeps."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60.0)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Advance time past recovery_timeout
        with patch("opentree.runner.circuit_breaker.time") as mock_time:
            mock_time.time.return_value = time.time() + 61.0
            assert cb.state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# HALF_OPEN -> CLOSED (recovery)
# ---------------------------------------------------------------------------


class TestHalfOpenToClosed:
    """A success in HALF_OPEN should close the circuit."""

    def test_success_closes_circuit(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_failure_count_resets_after_recovery(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        cb.record_success()

        status = cb.get_status()
        assert status["failure_count"] == 0


# ---------------------------------------------------------------------------
# HALF_OPEN -> OPEN (probe fails)
# ---------------------------------------------------------------------------


class TestHalfOpenToOpen:
    """A failure in HALF_OPEN should trip the circuit back to OPEN."""

    def test_failure_reopens_circuit(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """get_status should return a dict with state, failure_count, threshold."""

    def test_closed_status(self) -> None:
        cb = CircuitBreaker()
        status = cb.get_status()
        assert status == {
            "state": "closed",
            "failure_count": 0,
            "threshold": 5,
        }

    def test_open_status(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker(config)
        cb.record_failure()
        cb.record_failure()
        status = cb.get_status()
        assert status["state"] == "open"
        assert status["failure_count"] == 2
        assert status["threshold"] == 2

    def test_custom_threshold_in_status(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=10)
        cb = CircuitBreaker(config)
        status = cb.get_status()
        assert status["threshold"] == 10


# ---------------------------------------------------------------------------
# Custom config
# ---------------------------------------------------------------------------


class TestCustomConfig:
    """CircuitBreakerConfig should accept custom values."""

    def test_custom_failure_threshold(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=10)
        cb = CircuitBreaker(config)
        for _ in range(9):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_custom_recovery_timeout(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.05)
        cb = CircuitBreaker(config)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_default_config_values(self) -> None:
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60.0
        assert config.success_threshold == 1

    def test_frozen_config(self) -> None:
        config = CircuitBreakerConfig()
        with pytest.raises(AttributeError):
            config.failure_threshold = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Concurrent access should not corrupt state."""

    def test_concurrent_failures(self) -> None:
        """Many threads recording failures should not miss counts."""
        config = CircuitBreakerConfig(failure_threshold=1000)
        cb = CircuitBreaker(config)
        num_threads = 10
        failures_per_thread = 100
        barrier = threading.Barrier(num_threads)

        def worker() -> None:
            barrier.wait()
            for _ in range(failures_per_thread):
                cb.record_failure()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        status = cb.get_status()
        assert status["failure_count"] == num_threads * failures_per_thread

    def test_concurrent_mixed_operations(self) -> None:
        """Interleaved successes and failures should not crash."""
        config = CircuitBreakerConfig(failure_threshold=5, recovery_timeout=0.01)
        cb = CircuitBreaker(config)
        errors: list[Exception] = []

        def worker(do_fail: bool) -> None:
            try:
                for _ in range(50):
                    if do_fail:
                        cb.record_failure()
                    else:
                        cb.record_success()
                    cb.allow_request()
                    cb.get_status()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i % 2 == 0,))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        # State should be valid
        assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """End-to-end: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""

    def test_full_cycle(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=0.1)
        cb = CircuitBreaker(config)

        # Phase 1: CLOSED — requests allowed
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

        # Phase 2: accumulate failures -> OPEN
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Phase 3: wait for recovery -> HALF_OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

        # Phase 4: probe succeeds -> CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True
        assert cb.get_status()["failure_count"] == 0

    def test_full_cycle_with_failed_probe(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
        cb = CircuitBreaker(config)

        # Trip to OPEN
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait -> HALF_OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # Probe fails -> back to OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Wait again -> HALF_OPEN -> success -> CLOSED
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
