"""Tests for retry module — TDD Red phase (written before implementation).

Tests cover:
  - classify_error: overloaded, session, and non-retryable errors
  - calculate_delay: exponential backoff with cap
  - should_retry: decision logic for overloaded, session, and non-retryable
  - RetryConfig: immutability and defaults
"""
from __future__ import annotations

import pytest

from opentree.runner.retry import RetryConfig, calculate_delay, classify_error, should_retry


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------

class TestRetryConfig:
    def test_defaults(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 30.0
        assert config.max_delay == 120.0
        assert config.backoff_factor == 2.0

    def test_immutable(self):
        config = RetryConfig()
        with pytest.raises(AttributeError):
            config.max_attempts = 5  # type: ignore[misc]

    def test_custom_values(self):
        config = RetryConfig(max_attempts=5, base_delay=10.0, max_delay=60.0, backoff_factor=3.0)
        assert config.max_attempts == 5
        assert config.base_delay == 10.0
        assert config.max_delay == 60.0
        assert config.backoff_factor == 3.0


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_overloaded_keyword(self):
        assert classify_error("API is overloaded, try again") == "overloaded"

    def test_rate_limit_keyword(self):
        assert classify_error("rate_limit exceeded") == "overloaded"

    def test_529_status(self):
        assert classify_error("HTTP 529 response") == "overloaded"

    def test_503_status(self):
        assert classify_error("Service Unavailable 503") == "overloaded"

    def test_session_error_keyword(self):
        assert classify_error("session_error: invalid state") == "session"

    def test_invalid_session(self):
        assert classify_error("invalid session ID provided") == "session"

    def test_session_expired(self):
        assert classify_error("session expired, please restart") == "session"

    def test_none_for_unknown(self):
        assert classify_error("TypeError: cannot read property") == "none"

    def test_empty_string(self):
        assert classify_error("") == "none"

    def test_case_insensitive_overloaded(self):
        assert classify_error("OVERLOADED error from API") == "overloaded"

    def test_case_insensitive_session(self):
        assert classify_error("SESSION_ERROR encountered") == "session"

    def test_overloaded_takes_priority_over_session(self):
        """When message contains both patterns, overloaded wins (checked first)."""
        assert classify_error("overloaded and session_error") == "overloaded"


# ---------------------------------------------------------------------------
# calculate_delay
# ---------------------------------------------------------------------------

class TestCalculateDelay:
    def test_first_attempt(self):
        config = RetryConfig(base_delay=30.0, backoff_factor=2.0, max_delay=120.0)
        # attempt 0: 30 * (2^0) = 30
        assert calculate_delay(0, config) == 30.0

    def test_second_attempt(self):
        config = RetryConfig(base_delay=30.0, backoff_factor=2.0, max_delay=120.0)
        # attempt 1: 30 * (2^1) = 60
        assert calculate_delay(1, config) == 60.0

    def test_third_attempt(self):
        config = RetryConfig(base_delay=30.0, backoff_factor=2.0, max_delay=120.0)
        # attempt 2: 30 * (2^2) = 120
        assert calculate_delay(2, config) == 120.0

    def test_capped_at_max_delay(self):
        config = RetryConfig(base_delay=30.0, backoff_factor=2.0, max_delay=120.0)
        # attempt 3: 30 * (2^3) = 240 → capped to 120
        assert calculate_delay(3, config) == 120.0

    def test_custom_config(self):
        config = RetryConfig(base_delay=10.0, backoff_factor=3.0, max_delay=100.0)
        # attempt 1: 10 * (3^1) = 30
        assert calculate_delay(1, config) == 30.0

    def test_very_high_attempt_stays_capped(self):
        config = RetryConfig(base_delay=30.0, backoff_factor=2.0, max_delay=120.0)
        # attempt 10: 30 * (2^10) = 30720 → capped to 120
        assert calculate_delay(10, config) == 120.0


# ---------------------------------------------------------------------------
# should_retry
# ---------------------------------------------------------------------------

class TestShouldRetry:
    def test_overloaded_first_attempt(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("API overloaded", 0, config)
        assert retry is True
        assert delay == 30.0  # base_delay * 2^0
        assert "overloaded" in reason
        assert "1/3" in reason

    def test_overloaded_second_attempt(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("overloaded error", 1, config)
        assert retry is True
        assert delay == 60.0  # 30 * 2^1
        assert "2/3" in reason

    def test_overloaded_third_attempt(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("overloaded error", 2, config)
        assert retry is True
        assert delay == 120.0  # 30 * 2^2
        assert "3/3" in reason

    def test_overloaded_exhausted(self):
        """After max_attempts, no more retries."""
        config = RetryConfig()
        retry, delay, reason = should_retry("overloaded error", 3, config)
        assert retry is False

    def test_session_error_retries_once(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("session_error: bad state", 0, config)
        assert retry is True
        assert delay == 0.0  # session retry is immediate
        assert "session" in reason

    def test_session_error_no_second_retry(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("session_error: bad state", 1, config)
        assert retry is False

    def test_non_retryable_error(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("TypeError: null reference", 0, config)
        assert retry is False
        assert delay == 0.0
        assert reason == ""

    def test_empty_error(self):
        config = RetryConfig()
        retry, delay, reason = should_retry("", 0, config)
        assert retry is False

    def test_custom_max_attempts(self):
        config = RetryConfig(max_attempts=1)
        # attempt 0 → should retry
        retry, _, _ = should_retry("overloaded", 0, config)
        assert retry is True
        # attempt 1 → exhausted
        retry, _, _ = should_retry("overloaded", 1, config)
        assert retry is False
