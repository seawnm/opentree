"""Requirement module prompt hook: interview context detection.

Full implementation requires requirement data layer (future phase).
Currently returns empty list.
"""
from __future__ import annotations


def prompt_hook(context: dict) -> list[str]:
    """Return requirement-related system prompt fragments.

    Args:
        context: Dict containing user_id, channel_id, thread_ts, etc.

    Returns:
        List of prompt lines to inject into --system-prompt.
        Currently empty — full implementation in a future phase.
    """
    return []
