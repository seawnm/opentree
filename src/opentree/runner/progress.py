"""Slack progress reporting aligned with the legacy slack-bot UX."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from opentree.runner.stream_parser import Phase, ProgressState
from opentree.runner.tool_tracker import DecisionPoint, TimelineEntry

logger = logging.getLogger(__name__)

_PHASE_LABEL = {
    Phase.INITIALIZING: "初始化中",
    Phase.THINKING: "思考中",
    Phase.TOOL_USE: "處理中",
    Phase.GENERATING: "生成回覆中",
    Phase.COMPLETED: "處理完成",
    Phase.ERROR: "處理失敗",
}


def build_initial_ack_blocks() -> list[dict]:
    """Build the initial acknowledgement blocks."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⏳ 收到！正在處理...",
                "emoji": True,
            },
        }
    ]


def build_progress_blocks(
    state: ProgressState,
    elapsed: float,
    timeline: Optional[list[TimelineEntry]] = None,
    work_phase: str = "",
    decision: Optional["DecisionPoint"] = None,
) -> list[dict]:
    """Build Block Kit blocks for in-progress updates."""
    label = _PHASE_LABEL.get(state.phase, "處理中")
    context_text = f"已執行 {_format_duration(elapsed)}"
    if work_phase:
        context_text += f" · {work_phase}"
    elif state.phase == Phase.TOOL_USE and state.tool_name:
        context_text += f" · {state.tool_name}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"⏳ {label}",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context_text}],
        },
    ]

    if timeline:
        blocks.append({"type": "divider"})
        for entry in timeline:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"{entry.icon} {entry.text}"}],
                }
            )

    if decision:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"💡 _{decision.text}_"
            }
        })

    return blocks


def build_completion_blocks(
    elapsed: float,
    is_error: bool = False,
    error_message: str = "",
    completion_items: Optional[list[str]] = None,
) -> list[dict]:
    """Build Block Kit blocks for the final progress message."""
    if is_error:
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "❌ 處理失敗",
                    "emoji": True,
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": error_message or "發生未預期錯誤"}],
            },
        ]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "✅ 處理完成",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"已執行 {_format_duration(elapsed)}"}],
        },
    ]

    if completion_items:
        blocks.append({"type": "divider"})
        for item in completion_items:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": item}],
                }
            )

    return blocks


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    if minutes > 0:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


class ProgressReporter:
    """Background thread that updates one Slack progress message."""

    def __init__(
        self,
        slack_api,
        channel: str,
        thread_ts: str,
        interval: float = 10.0,
    ) -> None:
        self._slack = slack_api
        self._channel = channel
        self._thread_ts = thread_ts
        self._interval = interval

        self._message_ts: str = ""
        self._state = ProgressState()
        self._timeline: list[TimelineEntry] = []
        self._work_phase: str = ""
        self._decision: Optional[DecisionPoint] = None
        self._start_time = time.time()
        self._stop_event = threading.Event()
        self._update_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._completed = False
        self._tick_count = 0

    def start(self) -> str:
        """Send the initial acknowledgement message and start the loop."""
        self._start_time = time.time()
        self._stop_event.clear()

        blocks = build_initial_ack_blocks()
        result = self._slack.send_message(
            channel=self._channel,
            text="⏳ 收到！正在處理...",
            thread_ts=self._thread_ts,
            blocks=blocks,
        )
        self._message_ts = result.get("ts", "") if result else ""
        logger.info(
            "[ProgressReporter.start] channel=%s thread_ts=%s message_ts=%s",
            self._channel, self._thread_ts, self._message_ts,
        )

        self._update_thread = threading.Thread(
            target=self._update_loop,
            daemon=True,
            name="progress-reporter",
        )
        self._update_thread.start()
        return self._message_ts

    def update(
        self,
        state: ProgressState,
        timeline: Optional[list[TimelineEntry]] = None,
        work_phase: str = "",
        decision: Optional[DecisionPoint] = None,
    ) -> None:
        """Update the current live state used by the next Slack refresh."""
        with self._lock:
            self._state = state
            self._timeline = list(timeline or [])
            self._work_phase = work_phase
            self._decision = decision

    def complete(
        self,
        response_text: str,
        elapsed: float,
        is_error: bool = False,
        error_message: str = "",
        completion_items: Optional[list[str]] = None,
    ) -> None:
        """Finalize the progress message and send the actual thread reply."""
        self._stop_event.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=2.0)
        self._completed = True

        if not self._message_ts:
            return

        progress_blocks = build_completion_blocks(
            elapsed=elapsed,
            is_error=is_error,
            error_message=error_message,
            completion_items=completion_items,
        )
        progress_fallback = (
            f"❌ 處理失敗 | {error_message or '發生未預期錯誤'}"
            if is_error
            else f"✅ 處理完成 | 已執行 {_format_duration(elapsed)}"
        )
        self._slack.update_message(
            channel=self._channel,
            ts=self._message_ts,
            text=progress_fallback,
            blocks=progress_blocks,
        )

        if is_error:
            self._slack.send_message(
                channel=self._channel,
                text=f"❌ 處理失敗：{error_message or '發生未預期錯誤'}",
                thread_ts=self._thread_ts,
            )
            return

        if not response_text.strip():
            return

        reply_text = f"{response_text}\n\n_✅ 完成 (耗時 {_format_duration(elapsed)})_"
        self._slack.send_message(
            channel=self._channel,
            text=reply_text,
            thread_ts=self._thread_ts,
        )

    def stop(self) -> None:
        """Stop the background update thread."""
        self._stop_event.set()
        if self._update_thread is not None:
            self._update_thread.join(timeout=2.0)

    @property
    def message_ts(self) -> str:
        """The ts of the progress message."""
        return self._message_ts

    def _update_loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._push_progress()

    def _push_progress(self) -> None:
        if not self._message_ts or self._completed:
            return

        elapsed = time.time() - self._start_time
        with self._lock:
            state = self._state
            timeline = list(self._timeline)
            work_phase = self._work_phase
            decision = self._decision

        self._tick_count += 1
        blocks = build_progress_blocks(
            state=state,
            elapsed=elapsed,
            timeline=timeline,
            work_phase=work_phase,
            decision=decision,
        )
        fallback = f"⏳ {work_phase or _PHASE_LABEL.get(state.phase, '處理中')} | 已執行 {_format_duration(elapsed)}"
        try:
            self._slack.update_message(
                channel=self._channel,
                ts=self._message_ts,
                text=fallback,
                blocks=blocks,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Progress update failed: %s", exc)
