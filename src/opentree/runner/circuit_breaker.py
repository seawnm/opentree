"""Circuit breaker for Claude CLI health protection.

Prevents cascading failures by tracking consecutive CLI errors and
temporarily rejecting new requests when the failure threshold is reached.

State machine::

    CLOSED  --[failures >= threshold]--> OPEN
    OPEN    --[recovery_timeout elapsed]--> HALF_OPEN
    HALF_OPEN --[success]--> CLOSED
    HALF_OPEN --[failure]--> OPEN
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Possible states of the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Immutable configuration for :class:`CircuitBreaker`.

    Attributes:
        failure_threshold: Number of consecutive failures before tripping to OPEN.
        recovery_timeout: Seconds to wait in OPEN before transitioning to HALF_OPEN.
        success_threshold: Successes needed in HALF_OPEN to close the circuit.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 1


class CircuitBreaker:
    """Thread-safe circuit breaker for outbound service calls.

    Usage::

        cb = CircuitBreaker()

        if not cb.allow_request():
            # reject with "service unavailable"
            return

        result = call_service()
        if result.is_error:
            cb.record_failure()
        else:
            cb.record_success()

    Args:
        config: Optional configuration. Uses defaults when ``None``.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state (may transition OPEN -> HALF_OPEN lazily)."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self._config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(
                        "Circuit breaker HALF_OPEN (recovery timeout %.1fs elapsed)",
                        self._config.recovery_timeout,
                    )
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through.

        Returns:
            ``True`` if the circuit is CLOSED or HALF_OPEN (probe allowed),
            ``False`` if OPEN.
        """
        current = self.state
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return True
        return False

    def record_success(self) -> None:
        """Record a successful request.

        In HALF_OPEN, transitions to CLOSED.
        In any state, resets the failure counter.
        """
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("Circuit breaker CLOSED (probe succeeded)")
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed request.

        Increments the failure counter.  When the counter reaches the
        configured threshold, transitions to OPEN.  In HALF_OPEN state,
        a single failure immediately reopens the circuit.
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen immediately
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker OPEN (probe failed, count=%d)",
                    self._failure_count,
                )
            elif self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker OPEN after %d consecutive failures",
                    self._failure_count,
                )

    def get_status(self) -> dict:
        """Return status dict for admin / monitoring.

        Returns:
            A dict with ``state``, ``failure_count``, and ``threshold`` keys.
        """
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "threshold": self._config.failure_threshold,
        }
