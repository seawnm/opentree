"""Slack module prompt hook: inject channel/thread/workspace info."""
from __future__ import annotations


def prompt_hook(context: dict) -> list[str]:
    """Return Slack-specific system prompt fragments.

    Args:
        context: Dict containing channel_id, thread_ts, team_name,
                 workspace, etc.

    Returns:
        List of prompt lines to inject into --system-prompt.
    """
    parts: list[str] = []
    if context.get("channel_id"):
        parts.append(f"目前頻道 ID：{context['channel_id']}")
    if context.get("thread_ts"):
        parts.append(f"目前 Thread TS：{context['thread_ts']}")
    team = context.get("team_name") or context.get("workspace")
    if team:
        parts.append(f"目前 Workspace：{team}")
    if context.get("workspace"):
        parts.append(f"目前頻道工作區：{context['workspace']}")
    return parts
