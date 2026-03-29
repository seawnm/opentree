"""Memory module prompt hook: inject FTUE guidance for new users."""
from __future__ import annotations


def prompt_hook(context: dict) -> list[str]:
    """Return memory-related system prompt fragments.

    For new users (``is_new_user=True``), returns first-time user
    experience (FTUE) guidance lines.  For existing users, returns
    an empty list.

    Args:
        context: Dict containing is_new_user, user_display_name, etc.

    Returns:
        List of prompt lines to inject into --system-prompt.
    """
    if not context.get("is_new_user"):
        return []
    name = context.get("user_display_name", "使用者")
    return [
        f"這是 {name} 的第一次互動。",
        "請用友善的語氣歡迎，簡短說明你能做什麼。",
        "引導使用者說「記住我喜歡...」來建立個人記憶。",
    ]
