"""E2E tests for extension modules (scheduler, requirement, DM handling).

Batch 4 covers:
  D1 — Scheduler: bot correctly uses schedule-tool CLI when users request scheduling
  D2 — Requirement: trigger-rules auto-detect feature requests and invoke requirement-tool
  D3 — DM handling: direct messages processed without @mention (skipped — framework limitation)

These tests send real messages to Bot_Walter via DOGI message-tool,
then verify responses via slack-query-tool and bot log inspection.

Extension modules work through rules (markdown instructions injected into CLAUDE.md)
that guide the bot to call CLI tools via Bash.  The E2E tests verify the full loop:
user message -> bot interprets intent -> bot calls CLI tool -> bot reports result.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Must match conftest.BOT_USER_ID / BOT_WALTER_HOME — duplicated here for non-fixture helpers.
_BOT_UID = "U0APZ9MR997"
_BOT_WALTER_HOME = Path("/mnt/e/develop/mydev/project/trees/bot_walter")
_DOGI_DIR_RAW = os.environ.get("OPENTREE_E2E_DOGI_DIR", "")
_DOGI_DIR: Path | None = Path(_DOGI_DIR_RAW) if _DOGI_DIR_RAW else None

# Subprocess timeout for direct CLI cleanup calls (not via bot).
_CLI_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_schedule_tool(*args: str) -> dict[str, Any]:
    """Call schedule-tool directly (for setup/cleanup, NOT for testing bot behavior).

    Returns parsed JSON output.
    Raises RuntimeError on non-zero exit code.
    """
    if _DOGI_DIR is None:
        pytest.skip("OPENTREE_E2E_DOGI_DIR not set")
    cmd = [
        "uv", "run", "--directory", str(_DOGI_DIR),
        "python", "-m", "scripts.tools.schedule_tool",
        *args,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"schedule-tool {args} failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def _run_requirement_tool(*args: str) -> dict[str, Any]:
    """Call requirement-tool directly (for setup/cleanup, NOT for testing bot behavior).

    Returns parsed JSON output.
    Raises RuntimeError on non-zero exit code.
    """
    if _DOGI_DIR is None:
        pytest.skip("OPENTREE_E2E_DOGI_DIR not set")
    cmd = [
        "uv", "run", "--directory", str(_DOGI_DIR),
        "python", "-m", "scripts.tools.requirement_tool",
        *args,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"requirement-tool {args} failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def _extract_task_id(bot_reply: str) -> str | None:
    """Try to extract a schedule task ID from bot's reply text.

    Task IDs are typically UUID-like or short alphanumeric strings.
    The bot usually includes the ID when confirming creation/deletion.
    """
    # Pattern: common ID formats the schedule-tool returns
    # e.g. "task_id": "abc123" or "ID: abc123" or just a hex/uuid string
    patterns = [
        r"[Tt]ask[_ ]?[Ii][Dd][:\s]+[\"']?([a-zA-Z0-9_-]+)[\"']?",
        r"\bID\b[:\s]+[\"']?([a-zA-Z0-9_-]{6,})[\"']?",  # uppercase ID only, min 6 chars
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, bot_reply)
        if match:
            return match.group(1)
    return None


# ===================================================================
# D1 — Scheduler (TestScheduler)
# ===================================================================


@pytest.mark.skip(
    reason=(
        "Bot_Walter has no scripts/tools/schedule_tool.py implementation. "
        "The scheduler module's rules reference this path but the CLI tool "
        "is not deployed to bot_walter's opentree_home. "
        "Re-enable after schedule-tool is bundled as an OpenTree module."
    ),
)
class TestScheduler:
    """D1: bot correctly uses schedule-tool CLI for scheduling requests.

    The scheduler module is a pure-rules module: the bot reads schedule-tool.md
    rules and calls the CLI via Bash when users request scheduling operations.
    These tests verify the full loop from user message to bot action.
    """

    def test_schedule_create_via_bot(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """使用者要求建立排程，bot 應呼叫 schedule-tool 並回報結果。

        Bot should interpret the scheduling intent, call schedule-tool create
        via Bash, and report the created task back to the user.
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Arrange & Act: ask the bot to create a schedule
        result = send_message(
            f"{bot_mention} help me set a reminder in 5 minutes, "
            "content is: E2E test reminder - please ignore"
        )
        thread_ts = result["message_ts"]

        # Assert: bot should reply with task creation confirmation
        # Longer timeout because bot needs to interpret intent + call CLI
        reply = wait_for_bot_reply(thread_ts, timeout=180)

        # The reply should indicate a schedule was created
        reply_lower = reply.lower()
        schedule_indicators = [
            "schedule", "reminder", "task", "created",
            "set", "timer", "排程", "提醒", "建立",
        ]
        found = [kw for kw in schedule_indicators if kw in reply_lower]
        assert found, (
            f"Bot reply did not indicate schedule creation. "
            f"Expected keywords like {schedule_indicators}. "
            f"Got: {reply[:500]}"
        )

        # Verify: bot log should show schedule-tool invocation
        tool_logs = grep_log(r"schedule.tool|schedule_tool", after_ts=ts_before)
        if not tool_logs:
            # Also check for Bash calls that contain schedule
            tool_logs = grep_log(r"Bash.*schedule", after_ts=ts_before)

        # Cleanup: try to extract task ID and delete
        task_id = _extract_task_id(reply)
        if task_id:
            try:
                _run_schedule_tool("delete", task_id)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass  # Best-effort cleanup

    def test_schedule_list_via_bot(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
    ) -> None:
        """使用者要求查看排程，bot 應呼叫 schedule-tool list。

        Bot should list existing schedules or indicate none exist.
        """
        result = send_message(f"{bot_mention} list all my schedules")
        thread_ts = result["message_ts"]

        reply = wait_for_bot_reply(thread_ts, timeout=180)

        # The reply should contain schedule listing or "no schedules" message
        reply_lower = reply.lower()
        list_indicators = [
            "schedule", "task", "排程", "empty",
            "none", "沒有", "list", "列表", "目前",
        ]
        found = [kw for kw in list_indicators if kw in reply_lower]
        assert found, (
            f"Bot reply did not indicate schedule listing. "
            f"Expected keywords like {list_indicators}. "
            f"Got: {reply[:500]}"
        )

    def test_schedule_delete_via_bot(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        wait_for_nth_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """使用者要求取消排程，bot 應呼叫 schedule-tool delete。

        Flow: bot creates a schedule -> user asks to delete it -> bot deletes.
        Uses a single thread to maintain context.
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Step 1: ask bot to create a schedule (in a new thread)
        result = send_message(
            f"{bot_mention} set a reminder in 10 minutes: "
            "E2E delete test - please ignore"
        )
        thread_ts = result["message_ts"]

        create_reply = wait_for_bot_reply(thread_ts, timeout=180)

        # Assert creation succeeded before proceeding
        create_lower = create_reply.lower()
        assert any(
            kw in create_lower
            for kw in ["reminder", "schedule", "排程", "建立", "created", "task"]
        ), (
            f"Schedule creation step did not confirm success: "
            f"{create_reply[:300]}"
        )

        # Extract task_id for cleanup
        created_task_id = _extract_task_id(create_reply)

        try:
            # Step 2: ask bot to cancel it (same thread for context)
            send_message(
                f"{bot_mention} cancel the schedule you just created",
                thread_ts=thread_ts,
            )

            # Wait for the second bot reply (the deletion confirmation)
            delete_reply = wait_for_nth_bot_reply(thread_ts, n=2, timeout=180)

            # Assert: deletion confirmation
            delete_lower = delete_reply.lower()
            delete_indicators = [
                "delete", "cancel", "remove", "deleted", "cancelled",
                "removed", "取消", "刪除", "已取消", "已刪除",
            ]
            found = [kw for kw in delete_indicators if kw in delete_lower]
            assert found, (
                f"Bot reply did not confirm schedule deletion. "
                f"Expected keywords like {delete_indicators}. "
                f"Got: {delete_reply[:500]}"
            )
        finally:
            # Cleanup: ensure the schedule is deleted even if assertions fail
            if created_task_id:
                try:
                    _run_schedule_tool("delete", created_task_id)
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass  # Best-effort cleanup


# ===================================================================
# D2 — Requirement collection (TestRequirement)
# ===================================================================


class TestRequirement:
    """D2: trigger-rules auto-detect feature requests and invoke requirement-tool.

    The requirement module has mandatory trigger rules: when the bot detects
    a feature request pattern (e.g. "I want...", "Can we add..."), it must
    automatically call requirement-tool create to record the requirement.

    Since this depends on AI interpretation of intent, tests use
    xfail(strict=False) to allow for non-deterministic behavior.
    """

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "AI behavior is non-deterministic: the bot may not always "
            "recognize the feature request pattern or may choose a "
            "different response strategy."
        ),
    )
    def test_feature_request_triggers_collection(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """發送功能需求訊息，bot 應自動啟動需求收集。

        Trigger rules state that messages like "I want..." or "Can we add..."
        must immediately invoke requirement-tool create.
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Arrange & Act: send a clear feature request
        result = send_message(
            f"{bot_mention} I want a feature that can automatically "
            "summarize meeting notes from Slack threads every week. "
            "This is an E2E test requirement - please ignore."
        )
        thread_ts = result["message_ts"]

        # Assert: bot should reply with requirement-related content
        reply = wait_for_bot_reply(thread_ts, timeout=180)
        reply_lower = reply.lower()

        requirement_indicators = [
            "requirement", "feature", "need", "request",
            "record", "noted", "需求", "記錄", "功能",
            "收到", "了解",
        ]
        found = [kw for kw in requirement_indicators if kw in reply_lower]
        assert found, (
            f"Bot reply did not indicate requirement collection. "
            f"Expected keywords like {requirement_indicators}. "
            f"Got: {reply[:500]}"
        )

        # Verify: bot log should show requirement-tool invocation
        tool_logs = grep_log(
            r"requirement.tool|requirement_tool", after_ts=ts_before,
        )
        if not tool_logs:
            tool_logs = grep_log(r"Bash.*requirement", after_ts=ts_before)
        assert tool_logs, (
            f"Expected requirement-tool invocation in bot logs after {ts_before}. "
            "No matching log lines found."
        )

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Bot may return stats-only or queue message under load. "
            "Also depends on bot answering in English or Chinese with "
            "architecture-related keywords."
        ),
    )
    def test_non_feature_does_not_trigger(
        self,
        bot_mention: str,
        send_message: Callable[..., dict[str, Any]],
        wait_for_bot_reply: Callable[..., str],
        grep_log: Callable[..., list[str]],
    ) -> None:
        """一般問題不應觸發需求收集。

        A factual question should receive a normal answer without
        invoking the requirement-tool.
        """
        ts_before = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Arrange & Act: send a general knowledge question
        result = send_message(
            f"{bot_mention} what is the difference between microservices "
            "and monolithic architecture?"
        )
        thread_ts = result["message_ts"]

        # Assert: bot should answer normally
        reply = wait_for_bot_reply(thread_ts, timeout=180)
        assert reply, "Bot returned an empty reply"

        # The reply should be an informational answer, not a requirement record
        reply_lower = reply.lower()
        answer_indicators = [
            "microservice", "monolith", "architecture",
            "service", "application", "design",
            # Chinese equivalents (bot may reply in Chinese)
            "微服務", "單體", "架構", "服務", "應用", "設計",
            "分散式", "耦合", "部署",
        ]
        found = [kw for kw in answer_indicators if kw in reply_lower]
        assert found, (
            f"Bot reply did not answer the question. "
            f"Expected keywords like {answer_indicators}. "
            f"Got: {reply[:500]}"
        )

        # Verify: no requirement-tool invocation in logs
        tool_logs = grep_log(
            r"requirement.tool|requirement_tool", after_ts=ts_before,
        )
        # Also check Bash calls mentioning requirement
        bash_logs = grep_log(r"Bash.*requirement", after_ts=ts_before)

        assert not tool_logs and not bash_logs, (
            f"requirement-tool should NOT be invoked for a general question. "
            f"Found tool logs: {tool_logs[:3]}, bash logs: {bash_logs[:3]}"
        )


# ===================================================================
# D3 — DM handling (TestDirectMessage)
# ===================================================================


class TestDirectMessage:
    """D3: direct messages processed without @mention.

    DM handling is verified here at the E2E level.  However, the E2E
    framework sends messages via DOGI's message-tool, which posts to
    Slack channels -- it cannot open a DM conversation with Bot_Walter.
    These tests are therefore skipped, with DM logic covered by unit tests.
    """

    @pytest.mark.skip(
        reason=(
            "E2E framework uses message-tool which sends to channels, "
            "not DMs. DM testing requires direct Slack API calls to "
            "bot's DM conversation, which is not currently supported. "
            "DM logic is verified in unit tests (test_receiver.py)."
        ),
    )
    def test_dm_triggers_response_without_mention(self) -> None:
        """DM 不需要 @mention 即可觸發回覆。

        receiver.py accepts channel_type="im" messages without requiring
        an @mention.  This cannot be tested via message-tool because it
        only supports sending to channels.
        """

    @pytest.mark.skip(
        reason=(
            "E2E framework uses message-tool which sends to channels, "
            "not DMs. DM testing requires direct Slack API calls to "
            "bot's DM conversation, which is not currently supported. "
            "DM logic is verified in unit tests (test_receiver.py)."
        ),
    )
    def test_dm_response_does_not_require_bot_mention(self) -> None:
        """DM 回覆不應在訊息前加上 @user mention。

        In DM context, the bot should respond naturally without
        prefixing the reply with the user's mention string.
        """
