"""Tests for the Slack-facing progress reporter UX."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from opentree.runner.progress import (
    ProgressReporter,
    build_completion_blocks,
    build_initial_ack_blocks,
    build_progress_blocks,
)
from opentree.runner.stream_parser import Phase, ProgressState
from opentree.runner.tool_tracker import TimelineEntry


def _make_slack_mock(send_ts: str = "1111.0001") -> MagicMock:
    slack = MagicMock()
    slack.send_message.return_value = {"ok": True, "ts": send_ts}
    slack.update_message.return_value = {"ok": True, "ts": send_ts}
    return slack


def test_build_initial_ack_blocks_uses_header() -> None:
    blocks = build_initial_ack_blocks()
    assert blocks[0]["type"] == "header"
    assert "收到！正在處理" in blocks[0]["text"]["text"]


def test_build_progress_blocks_include_elapsed_and_timeline() -> None:
    blocks = build_progress_blocks(
        ProgressState(phase=Phase.THINKING),
        elapsed=12.0,
        timeline=[TimelineEntry("🧠", "思考 (8 秒)"), TimelineEntry("💻", "Bash `pytest`")],
        work_phase="💻 執行指令中",
    )

    assert blocks[0]["type"] == "header"
    assert "思考中" in blocks[0]["text"]["text"]
    assert "已執行 12 秒" in blocks[1]["elements"][0]["text"]
    assert "執行指令中" in blocks[1]["elements"][0]["text"]
    assert any("Bash `pytest`" in b["elements"][0]["text"] for b in blocks if b["type"] == "context")


def test_build_progress_blocks_falls_back_to_tool_name_for_tool_use() -> None:
    blocks = build_progress_blocks(
        ProgressState(phase=Phase.TOOL_USE, tool_name="Bash"),
        elapsed=3.0,
    )
    assert "Bash" in blocks[1]["elements"][0]["text"]


def test_build_completion_blocks_success_summary_only() -> None:
    blocks = build_completion_blocks(
        elapsed=65.0,
        completion_items=["🧠 思考 12 秒", "💻 執行指令 3 次"],
    )

    assert blocks[0]["type"] == "header"
    assert "處理完成" in blocks[0]["text"]["text"]
    assert "1 分 5 秒" in blocks[1]["elements"][0]["text"]
    assert any("執行指令 3 次" in b["elements"][0]["text"] for b in blocks if b["type"] == "context")


def test_build_completion_blocks_error() -> None:
    blocks = build_completion_blocks(
        elapsed=2.0,
        is_error=True,
        error_message="boom",
    )
    assert "處理失敗" in blocks[0]["text"]["text"]
    assert "boom" in blocks[1]["elements"][0]["text"]


def test_reporter_start_sends_block_kit_ack() -> None:
    slack = _make_slack_mock()
    reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

    try:
        reporter.start()
    finally:
        reporter.stop()

    _, kwargs = slack.send_message.call_args
    assert kwargs["channel"] == "C001"
    assert kwargs["thread_ts"] == "1234.5678"
    assert kwargs["blocks"][0]["type"] == "header"


def test_reporter_complete_updates_progress_then_replies() -> None:
    slack = _make_slack_mock()
    reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

    try:
        reporter.start()
        reporter.complete(
            response_text="最終答案",
            elapsed=5.0,
            completion_items=["🧠 思考 5 秒", "💻 執行指令 2 次"],
        )
    finally:
        reporter.stop()

    assert slack.update_message.call_count >= 1
    update_kwargs = slack.update_message.call_args.kwargs
    assert "處理完成" in update_kwargs["text"]
    assert any("思考 5 秒" in block["elements"][0]["text"] for block in update_kwargs["blocks"] if block["type"] == "context")

    assert slack.send_message.call_count >= 2
    reply_kwargs = slack.send_message.call_args.kwargs
    assert reply_kwargs["thread_ts"] == "1234.5678"
    assert "最終答案" in reply_kwargs["text"]
    assert "完成 (耗時 5 秒)" in reply_kwargs["text"]


def test_reporter_complete_error_sends_error_reply() -> None:
    slack = _make_slack_mock()
    reporter = ProgressReporter(slack, "C001", "1234.5678", interval=60.0)

    try:
        reporter.start()
        reporter.complete(
            response_text="",
            elapsed=2.0,
            is_error=True,
            error_message="Request timed out.",
        )
    finally:
        reporter.stop()

    reply_kwargs = slack.send_message.call_args.kwargs
    assert "處理失敗" in reply_kwargs["text"]
    assert "Request timed out." in reply_kwargs["text"]


def test_reporter_update_loop_uses_latest_state() -> None:
    slack = _make_slack_mock(send_ts="3333.0001")
    reporter = ProgressReporter(slack, "C001", "1234.5678", interval=0.05)

    try:
        reporter.start()
        reporter.update(ProgressState(phase=Phase.TOOL_USE, tool_name="Bash"))
        time.sleep(0.2)
    finally:
        reporter.stop()

    assert any(
        "Bash" in kwargs.get("text", "") or any(
            "Bash" in element.get("text", "")
            for block in kwargs.get("blocks", [])
            for element in block.get("elements", [])
        )
        for _, kwargs in slack.update_message.call_args_list
    )


def test_build_progress_blocks_with_decision_shows_lightbulb_section() -> None:
    """build_progress_blocks with a DecisionPoint adds a 💡 section block."""
    from opentree.runner.tool_tracker import DecisionPoint
    dp = DecisionPoint(text="根據分析發現需要修改三個檔案", decision_type="analysis")
    blocks = build_progress_blocks(
        ProgressState(phase=Phase.THINKING),
        elapsed=5.0,
        decision=dp,
    )
    section_blocks = [b for b in blocks if b["type"] == "section"]
    assert len(section_blocks) == 1
    assert "💡" in section_blocks[0]["text"]["text"]
    assert "根據分析發現需要修改三個檔案" in section_blocks[0]["text"]["text"]


def test_build_progress_blocks_without_decision_has_no_lightbulb() -> None:
    """build_progress_blocks without a DecisionPoint has no 💡 section."""
    blocks = build_progress_blocks(
        ProgressState(phase=Phase.THINKING),
        elapsed=5.0,
    )
    lightbulb_blocks = [b for b in blocks if b["type"] == "section" and "💡" in str(b)]
    assert lightbulb_blocks == []
