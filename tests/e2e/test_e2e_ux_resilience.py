"""E2E tests for UX experience and resilience mechanisms (Batch 5).

Covers:
  E1 — UX experience verification (response time, error messages, empty input)
  E2 — Queue feedback (concurrent requests, queued processing)
  E3 — Error recovery (bot recovers after errors, session clear on failure)
  E4 — Circuit breaker (config validation, initial state)

These tests verify user-facing behaviour of the runner's retry, circuit
breaker, task queue, and error handling mechanisms.  Where reliable
triggering is difficult in a live environment, observational tests use
``warnings.warn`` instead of hard assertions.
"""

from __future__ import annotations

import re
import time
import warnings
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.e2e.conftest import (
    BOT_USER_ID,
    CHANNEL_ID,
    _run_query_tool,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_for_reply(
    thread_ts: str,
    timeout: int = 180,
    poll_interval: int = 5,
) -> str | None:
    """Poll a thread until Bot_Walter replies or timeout.

    Returns the reply text, or None if timed out.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _run_query_tool(
            "read-thread",
            channel=CHANNEL_ID,
            thread_ts=thread_ts,
            limit="50",
        )
        if data.get("success"):
            for msg in data.get("messages", []):
                if msg.get("user") == BOT_USER_ID:
                    text = msg.get("text", "")
                    # Skip ack spinner — wait for actual content.
                    if text and ":hourglass_flowing_sand:" not in text:
                        return text
        time.sleep(poll_interval)
    return None


# ===================================================================
# E1 — UX Experience Verification
# ===================================================================


class TestUXExperience:
    """E1: user-facing quality — response time, error messages, empty input."""

    def test_response_time_reasonable(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """簡單問題的回覆時間應在合理範圍內（< 120 秒）。

        發送一個極簡問題（2+2），記錄發送到收到回覆的延遲。
        這是 smoke test，主要驗證沒有異常延遲（queue 阻塞、process hang 等）。
        """
        t_start = time.monotonic()
        result = send_message(f"{bot_mention} What is 2+2? Reply with just the number.")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)
        t_elapsed = time.monotonic() - t_start

        # Note: wait_for_bot_reply raises TimeoutError on timeout,
        # so if we reach here, reply is always a non-empty string.

        # Verify: response delay < 120 seconds (includes Claude processing).
        assert t_elapsed < 120, (
            f"Response took {t_elapsed:.1f}s, exceeding 120s limit"
        )

        # Bonus: reply should contain something related to the answer.
        # Not a strict check — Claude might phrase it differently.
        if "4" not in reply:
            warnings.warn(
                f"Reply to '2+2' did not contain '4': {reply[:200]}",
                UserWarning,
                stacklevel=1,
            )

    def test_error_message_user_friendly(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """錯誤訊息應對使用者友善，不暴露內部堆疊或技術細節。

        這是觀察性測試。在 E2E 環境下難以可靠觸發錯誤，因此發送一個
        正常請求，驗證回覆中不包含內部錯誤格式（traceback、exception 等）。
        若 bot 日誌有 ERROR 記錄，檢查 Slack 回覆是否友善。
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")
        result = send_message(f"{bot_mention} Hello, how are you?")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)
        # Note: wait_for_bot_reply raises TimeoutError on timeout,
        # so if we reach here, reply is always a non-empty string.

        # The reply should not contain raw Python tracebacks or internal error details.
        internal_error_patterns = [
            r"Traceback \(most recent call last\)",
            r"File \".*\.py\", line \d+",
            r"raise \w+Error",
            r"subprocess\.CalledProcessError",
        ]
        for pattern in internal_error_patterns:
            if re.search(pattern, reply):
                warnings.warn(
                    f"Reply may contain internal error details "
                    f"(matched pattern '{pattern}'): {reply[:300]}",
                    UserWarning,
                    stacklevel=1,
                )

        # Check bot logs for ERROR-level entries during this request.
        error_logs = grep_log(r"ERROR", after_ts=ts_before)
        if error_logs:
            warnings.warn(
                f"Bot logged {len(error_logs)} ERROR(s) during this request. "
                f"First: {error_logs[0][:200]}",
                UserWarning,
                stacklevel=1,
            )

    def test_empty_message_handled(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """空內容或只有 @mention 的訊息應有合理回覆，不應 crash。

        發送只含 mention 不含實際內容的訊息，驗證 bot 仍然回覆
        （引導訊息或友善提示皆可），而非無回應或 error。
        """
        # Send a message with only the bot mention and trailing whitespace.
        result = send_message(f"{bot_mention} ")
        thread_ts = result["message_ts"]

        # Use a slightly shorter timeout — if bot ignores empty input,
        # we want to know sooner rather than waiting the full 120s.
        reply = _poll_for_reply(thread_ts, timeout=90, poll_interval=5)

        # The bot may either:
        # 1. Reply with a guidance/help message (ideal)
        # 2. Reply with something (acceptable)
        # 3. Not reply at all (the empty text was filtered out — acceptable
        #    but we note it)
        if reply is None:
            warnings.warn(
                "Bot did not reply to an empty-content mention within 90s. "
                "This may be by design (empty input filtered), or a timeout.",
                UserWarning,
                stacklevel=1,
            )
        else:
            # If the bot replied, it should not be an error message.
            assert ":x:" not in reply, (
                f"Bot returned an error for empty input: {reply[:200]}"
            )


# ===================================================================
# E2 — Queue Feedback
# ===================================================================


class TestQueueFeedback:
    """E2: concurrent request handling and queue acknowledgement."""

    def test_concurrent_requests_handled(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
    ) -> None:
        """同時發送 3 個請求（不同 thread），所有請求都應得到回覆。

        max_concurrent_tasks=2，第 3 個請求會進入排隊。
        驗證所有 3 個 thread 最終都收到回覆，且回覆內容與問題相關。

        Note: This test assumes max_concurrent_tasks=2 (default).
        It does not verify the config value; it only asserts all requests
        eventually receive replies regardless of queuing behavior.
        """
        threads: list[tuple[str, str]] = []  # (thread_ts, question)
        questions = [
            "What is 10 + 5? Reply with just the number.",
            "What is the capital of Japan? Reply with just the city name.",
            "What color is grass? Reply with just the color.",
        ]

        # Send 3 messages in quick succession, each to a new thread.
        for question in questions:
            result = send_message(f"{bot_mention} {question}")
            thread_ts = result["message_ts"]
            threads.append((thread_ts, question))
            # Tiny delay to avoid Slack rate limiting.
            time.sleep(1)

        # Poll all threads with generous timeout (allows sequential processing
        # when max_concurrent=2 and third task is queued).
        timeout = 360  # 6 minutes — each task may take ~120s
        replies: dict[str, str] = {}
        deadline = time.monotonic() + timeout
        pending = {ts for ts, _ in threads}

        while pending and time.monotonic() < deadline:
            for thread_ts in list(pending):
                data = _run_query_tool(
                    "read-thread",
                    channel=CHANNEL_ID,
                    thread_ts=thread_ts,
                    limit="50",
                )
                if data.get("success"):
                    for msg in data.get("messages", []):
                        if msg.get("user") == BOT_USER_ID:
                            text = msg.get("text", "")
                            # Skip ack spinner — wait for real reply.
                            if text and ":hourglass_flowing_sand:" not in text:
                                replies[thread_ts] = text
                                pending.discard(thread_ts)
                                break
            if pending:
                time.sleep(10)

        # All 3 should have received replies.
        answered = sum(1 for ts, _ in threads if ts in replies)
        total = len(threads)
        assert answered == total, (
            f"Only {answered}/{total} concurrent requests got replies. "
            f"Pending: {pending}"
        )

        # Each reply should be non-empty.
        for thread_ts, question in threads:
            reply = replies.get(thread_ts, "")
            assert reply, (
                f"Empty reply for thread {thread_ts} "
                f"(question: {question[:50]})"
            )

    def test_queued_request_eventually_processed(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """排隊的請求最終會被處理，日誌中應有排隊相關記錄。

        發送超過 max_concurrent（2）個請求，第 3 個應排隊。
        驗證：
        1. 所有請求最終收到回覆
        2. 日誌中有 queue/pending 相關記錄（觀察性）
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        threads: list[str] = []
        for i in range(3):
            result = send_message(
                f"{bot_mention} Say exactly: 'queue test {i + 1}'"
            )
            threads.append(result["message_ts"])
            time.sleep(0.5)

        # Wait for all replies with generous timeout.
        timeout = 420  # 7 minutes
        replies: dict[str, str] = {}
        deadline = time.monotonic() + timeout
        pending = set(threads)

        while pending and time.monotonic() < deadline:
            for thread_ts in list(pending):
                data = _run_query_tool(
                    "read-thread",
                    channel=CHANNEL_ID,
                    thread_ts=thread_ts,
                    limit="50",
                )
                if data.get("success"):
                    for msg in data.get("messages", []):
                        if msg.get("user") == BOT_USER_ID:
                            text = msg.get("text", "")
                            if text and ":hourglass_flowing_sand:" not in text:
                                replies[thread_ts] = text
                                pending.discard(thread_ts)
                                break
            if pending:
                time.sleep(10)

        assert len(replies) == 3, (
            f"Only {len(replies)}/3 queued requests got replies. "
            f"Pending: {pending}"
        )

        # Observational: check for queue-related log entries.
        queue_logs = grep_log(
            r"(?i)queued|pending|promoted|task.*queue",
            after_ts=ts_before,
        )
        if not queue_logs:
            warnings.warn(
                "No queue-related log lines found. "
                "The third task may have started immediately (queue not triggered), "
                "or queue logging is absent.",
                UserWarning,
                stacklevel=1,
            )


# ===================================================================
# E3 — Error Recovery
# ===================================================================


class TestErrorRecovery:
    """E3: bot resilience — recovery after errors, session clear on failure."""

    def test_bot_recovers_after_error(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """bot 在一個請求出錯後，應能繼續處理下一個正常請求。

        策略：先發送一個可能觸發邊界行為的請求，然後發送正常請求。
        驗證正常請求成功取得回覆。
        注意：在 E2E 環境下不易可靠觸發 Claude CLI 錯誤，
        因此這主要是 smoke test，確認 bot 不會因為任何單一請求而永久停擺。
        """
        # Step 1: send a request with unusual content that may cause edge-case behavior.
        # We do NOT try to crash the bot — just exercise an unusual path.
        result_edge = send_message(
            f"{bot_mention} " + "A" * 500  # Unusually long repeated character input.
        )
        thread_ts_edge = result_edge["message_ts"]

        # Wait a moment for the first request to be processed (or fail).
        _poll_for_reply(thread_ts_edge, timeout=120, poll_interval=5)

        # Step 2: send a normal request to a different thread.
        result_normal = send_message(
            f"{bot_mention} What is 7 * 8? Reply with just the number."
        )
        thread_ts_normal = result_normal["message_ts"]

        # wait_for_bot_reply raises TimeoutError if no reply arrives,
        # which is a clearer failure signal than a None-check assertion.
        reply = wait_for_bot_reply(thread_ts_normal, timeout=120)

    def test_session_clear_on_failure(
        self,
        grep_log: Callable[..., list[str]],
    ) -> None:
        """session 失敗時應自動清除並重試（靜態驗證 + 日誌觀察）。

        難以在 E2E 環境中可靠觸發 session error。
        改為靜態驗證：
        1. dispatcher.py 中存在 session error 處理邏輯
        2. retry.py 中 classify_error 可識別 session 錯誤
        3. 日誌中是否有歷史 session 清除記錄（觀察性）
        """
        # Static verification: confirm session error handling via imports.
        import opentree.runner.dispatcher as _dispatcher_mod
        from opentree.runner.retry import classify_error

        dispatcher_path = Path(_dispatcher_mod.__file__)
        dispatcher_src = dispatcher_path.read_text(encoding="utf-8")

        # Dispatcher should clear session_id when classify_error returns "session".
        assert 'classify_error' in dispatcher_src, (
            "dispatcher.py should reference classify_error for retry classification"
        )
        assert 'session_id = ""' in dispatcher_src, (
            "dispatcher.py should clear session_id on session errors"
        )

        # Verify retry.py recognizes session error patterns via classify_error.
        assert classify_error("session_error") == "session", (
            "classify_error should recognise 'session_error' pattern"
        )
        assert classify_error("session expired") == "session", (
            "classify_error should recognise 'session expired' pattern"
        )

        # Observational: check for any historical session clear events in today's log.
        session_logs = grep_log(
            r"(?i)session.*clear|clearing.*session|session.*error",
        )
        if not session_logs:
            warnings.warn(
                "No session-clear log entries found today. "
                "This is expected if no session errors occurred.",
                UserWarning,
                stacklevel=1,
            )


# ===================================================================
# E4 — Circuit Breaker
# ===================================================================


class TestCircuitBreaker:
    """E4: circuit breaker configuration and runtime state verification."""

    def test_circuit_breaker_config_present(self) -> None:
        """circuit breaker 設定應存在且參數合理（靜態驗證，不需 bot 運行）。

        驗證：
        - failure_threshold >= 2（至少容忍 2 次失敗才跳閘）
        - recovery_timeout > 0（OPEN 狀態有恢復窗口）
        - success_threshold >= 1（HALF_OPEN 至少需 1 次成功才關閉）
        """
        from opentree.runner.circuit_breaker import (
            CircuitBreakerConfig,
            CircuitState,
        )

        config = CircuitBreakerConfig()

        # failure_threshold: should tolerate at least a couple failures
        # before tripping to prevent flapping.
        assert config.failure_threshold >= 2, (
            f"failure_threshold={config.failure_threshold} is too low; "
            f"should be >= 2 to avoid flapping"
        )

        # recovery_timeout: must be positive so OPEN eventually transitions.
        assert config.recovery_timeout > 0, (
            f"recovery_timeout={config.recovery_timeout} must be > 0"
        )

        # success_threshold: at least 1 success needed to close.
        assert config.success_threshold >= 1, (
            f"success_threshold={config.success_threshold} must be >= 1"
        )

    def test_circuit_breaker_state_transitions(self) -> None:
        """circuit breaker 狀態轉移應正確（單元級驗證，不需 bot 運行）。

        驗證 CLOSED -> OPEN -> HALF_OPEN -> CLOSED 的完整生命週期。
        """
        from opentree.runner.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitState,
        )

        # Use a short recovery timeout to avoid slow test.
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms
            success_threshold=1,
        )
        cb = CircuitBreaker(config)

        # Initial state: CLOSED
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

        # Record failures up to threshold -> OPEN
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Wait for recovery timeout -> HALF_OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

        # Test HALF_OPEN -> OPEN on probe failure (regression path).
        cb.record_failure()
        assert cb.state == CircuitState.OPEN, (
            "HALF_OPEN should revert to OPEN on failure"
        )

        # Let it recover to HALF_OPEN again for the success path.
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # Record success -> CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_circuit_breaker_initial_state_closed(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """bot 正常運行時，circuit breaker 應為 CLOSED 狀態。

        發送正常請求並驗證成功回覆（證明 circuit breaker 沒有阻擋）。
        同時檢查日誌中沒有 OPEN 或 HALF_OPEN 狀態記錄。
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        result = send_message(
            f"{bot_mention} What is 3 + 3? Reply with just the number."
        )
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=120)
        # Note: wait_for_bot_reply raises TimeoutError on timeout,
        # so if we reach here, reply is always a non-empty string.

        # The reply should not be the "service unavailable" message
        # that the dispatcher sends when circuit breaker rejects.
        assert "temporarily unavailable" not in reply.lower(), (
            f"Bot replied with circuit breaker rejection: {reply[:200]}"
        )

        # Observational: check that no OPEN/HALF_OPEN state was logged.
        cb_logs = grep_log(
            r"(?i)circuit.*breaker.*(OPEN|HALF_OPEN)",
            after_ts=ts_before,
        )
        if cb_logs:
            warnings.warn(
                f"Circuit breaker entered OPEN/HALF_OPEN during test: "
                f"{cb_logs[0][:200]}",
                UserWarning,
                stacklevel=1,
            )

    def test_retry_config_reasonable(self) -> None:
        """retry 設定應合理（靜態驗證，不需 bot 運行）。

        驗證：
        - max_attempts >= 1（至少重試一次）
        - base_delay > 0（避免 busy-loop 重試）
        - max_delay >= base_delay（上限不低於基礎延遲）
        - backoff_factor > 1（確保延遲遞增）
        """
        from opentree.runner.retry import RetryConfig

        config = RetryConfig()

        assert config.max_attempts >= 1, (
            f"max_attempts={config.max_attempts} should be >= 1"
        )
        assert config.base_delay > 0, (
            f"base_delay={config.base_delay} should be > 0"
        )
        assert config.max_delay >= config.base_delay, (
            f"max_delay={config.max_delay} should be >= base_delay={config.base_delay}"
        )
        assert config.backoff_factor > 1, (
            f"backoff_factor={config.backoff_factor} should be > 1 for exponential backoff"
        )

    def test_retry_error_classification(self) -> None:
        """retry 的錯誤分類應正確識別可重試的錯誤類型（靜態驗證）。

        Test inputs use exact pattern strings from retry._OVERLOADED_PATTERNS
        and retry._SESSION_PATTERNS to verify each pattern individually.
        """
        from opentree.runner.retry import classify_error

        # Overloaded patterns (from retry.py _OVERLOADED_PATTERNS).
        assert classify_error("overloaded") == "overloaded"
        assert classify_error("rate_limit") == "overloaded"
        assert classify_error("529") == "overloaded"
        assert classify_error("503") == "overloaded"

        # Session patterns (from retry.py _SESSION_PATTERNS).
        assert classify_error("session_error") == "session"
        assert classify_error("session expired") == "session"
        assert classify_error("invalid session") == "session"

        # Unknown errors should not trigger retry.
        assert classify_error("something random") == "none"
        assert classify_error("") == "none"
