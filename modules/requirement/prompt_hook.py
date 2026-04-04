"""Requirement module prompt hook.

Detects if the current thread is a requirement interview thread
and injects interview context into the system prompt.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def prompt_hook(context: dict[str, Any]) -> list[str]:
    """Inject interview context when current thread matches an interview.

    Scans requirement interview YAML files to find if the current
    thread_ts matches any active interview. If so, returns context
    lines to guide the AI's interview behavior.

    Args:
        context: PromptContext.to_dict() output.

    Returns:
        List of prompt lines (empty if no match or yaml unavailable).
    """
    if yaml is None:
        return []

    thread_ts = context.get("thread_ts", "")
    opentree_home = context.get("opentree_home", "")
    if not thread_ts or not opentree_home:
        return []

    req_dir = Path(opentree_home) / "data" / "requirements"
    if not req_dir.is_dir():
        return []

    try:
        return _scan_interviews(req_dir, thread_ts)
    except Exception:
        return []


def _scan_interviews(req_dir: Path, thread_ts: str) -> list[str]:
    """Scan interview YAML files for a matching thread_ts.

    Args:
        req_dir: Path to the requirements data directory.
        thread_ts: Thread timestamp to match against.

    Returns:
        Context lines if match found, empty list otherwise.
    """
    pattern = str(req_dir / "*" / "interviews" / "*.yaml")
    for filepath in glob.glob(pattern):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        match = _match_thread(data, thread_ts)
        if match is not None:
            return _build_context_lines(data, match, filepath)

    return []


def _match_thread(data: dict, thread_ts: str) -> str | None:
    """Check if any thread in the interview data matches thread_ts.

    Args:
        data: Parsed YAML interview data.
        thread_ts: Thread timestamp to find.

    Returns:
        The phase key (e.g., "P1", "P2") if matched, None otherwise.
    """
    threads = data.get("threads", {})
    if not isinstance(threads, dict):
        return None
    for phase_key, ts_value in threads.items():
        if str(ts_value) == thread_ts:
            return str(phase_key)
    return None


def _build_context_lines(
    data: dict, phase: str, filepath: str
) -> list[str]:
    """Build prompt context lines for a matched interview.

    Args:
        data: Parsed YAML interview data.
        phase: Matched phase key.
        filepath: Path to the YAML file (for extracting req_id).

    Returns:
        List of prompt lines describing the interview context.
    """
    # Extract requirement ID from directory name
    req_id = Path(filepath).parent.parent.name

    # Gather interview metadata
    interviewee = data.get("interviewee", "unknown")
    status = data.get("status", "unknown")
    question_count = len(data.get("questions", []))

    lines = [
        f"此 thread 是 {req_id} 的需求訪談（受訪者：{interviewee}）",
        f"目前階段：{phase}（狀態：{status}），已問 {question_count} 題。",
        "每次回覆後必須更新狀態檔。",
    ]

    # Add observer notes preview (truncated)
    notes = data.get("notes", "")
    if notes:
        preview = str(notes)[:200]
        if len(str(notes)) > 200:
            preview += "..."
        lines.append(f"訪談者觀察筆記：{preview}")

    return lines
