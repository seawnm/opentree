"""Retry logic for transient Claude CLI errors."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryConfig:
    """Immutable retry configuration."""

    max_attempts: int = 3
    base_delay: float = 30.0  # seconds
    max_delay: float = 120.0  # seconds
    backoff_factor: float = 2.0


# Error patterns that trigger retry.
_OVERLOADED_PATTERNS: tuple[str, ...] = ("overloaded", "rate_limit", "529", "503")
_SESSION_PATTERNS: tuple[str, ...] = ("session_error", "invalid session", "session expired")


def classify_error(error_message: str) -> str:
    """Classify an error message into a retry category.

    Checks overloaded patterns first, then session patterns.

    Args:
        error_message: The error string from Claude CLI.

    Returns:
        ``"overloaded"``, ``"session"``, or ``"none"``.
    """
    lower = error_message.lower()
    for pattern in _OVERLOADED_PATTERNS:
        if pattern in lower:
            return "overloaded"
    for pattern in _SESSION_PATTERNS:
        if pattern in lower:
            return "session"
    return "none"


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate exponential backoff delay for a given attempt number.

    Args:
        attempt: Zero-based attempt index (0 = first retry).
        config: Retry configuration with base_delay, backoff_factor, max_delay.

    Returns:
        Delay in seconds, capped at ``config.max_delay``.
    """
    delay = config.base_delay * (config.backoff_factor ** attempt)
    return min(delay, config.max_delay)


def should_retry(
    error_message: str,
    attempt: int,
    config: RetryConfig,
) -> tuple[bool, float, str]:
    """Determine if a failed task should be retried.

    Args:
        error_message: The error string from Claude CLI.
        attempt: Zero-based attempt index (0 = first attempt that failed).
        config: Retry configuration.

    Returns:
        A tuple of ``(should_retry, delay_seconds, reason)``.
        When ``should_retry`` is False, delay is 0.0 and reason is ``""``.
    """
    category = classify_error(error_message)

    if category == "overloaded" and attempt < config.max_attempts:
        delay = calculate_delay(attempt, config)
        return (True, delay, f"overloaded (attempt {attempt + 1}/{config.max_attempts})")

    if category == "session" and attempt < 1:
        return (True, 0.0, "session error (clearing session)")

    return (False, 0.0, "")
