"""Prompt hook stub for the slack module.

Real implementation will be added in Phase 2.
"""
from __future__ import annotations


def prompt_hook(context: dict) -> list[str]:
    """Return dynamic system prompt fragments.

    Args:
        context: Dict containing user_id, channel_id, thread_ts, etc.

    Returns:
        List of prompt lines to inject into --system-prompt.
    """
    return []
