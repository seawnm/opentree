"""Thread context builder for OpenTree bot runner.

Reads thread history from Slack and formats it into a context string
that is prepended to the user's message for Claude.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum messages to include in context
DEFAULT_MAX_MESSAGES = 20
# Maximum total characters for context
DEFAULT_MAX_CHARS = 8000


def build_thread_context(
    slack_api,  # SlackAPI (duck-typed)
    channel: str,
    thread_ts: str,
    bot_user_id: str,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Build a context string from thread history.

    Reads the thread replies, formats each message as:
    [user_name]: message text

    Uses a sliding window: takes the most recent ``max_messages`` messages,
    then truncates from the oldest if total exceeds ``max_chars``.

    Excludes:
    - Bot's own messages (user == bot_user_id)
    - Messages with no text
    - The current (last) message (it's the user's new message)

    Returns empty string if thread has no useful history.
    """
    try:
        messages = slack_api.get_thread_replies(channel, thread_ts)
    except Exception as exc:
        logger.error(
            "build_thread_context: failed to fetch thread replies "
            "(channel=%s, thread_ts=%s): %s",
            channel,
            thread_ts,
            exc,
        )
        return ""

    # Nothing to build context from
    if not messages:
        return ""

    # Exclude the last (triggering) message
    history = messages[:-1]

    if not history:
        return ""

    # Apply sliding window: keep only the most recent max_messages messages
    if len(history) > max_messages:
        history = history[-max_messages:]

    # Format each message, skipping bot messages and empty texts
    formatted: list[str] = []
    for msg in history:
        line = _format_message(msg, slack_api, bot_user_id)
        if line is not None:
            formatted.append(line)

    if not formatted:
        return ""

    # Truncate from oldest when over the character limit
    formatted = _truncate_to_limit(formatted, max_chars)

    if not formatted:
        return ""

    return "\n".join(formatted)


def _format_message(msg: dict, slack_api, bot_user_id: str) -> Optional[str]:
    """Format a single Slack message for context.

    Returns ``"user_display_name: text"`` or ``None`` if the message should
    be skipped (bot message, empty text, or missing text key).
    """
    text = msg.get("text", "")
    if not text:
        return None

    user_id = msg.get("user", "")

    # Exclude the bot's own messages
    if user_id == bot_user_id:
        return None

    display_name = slack_api.get_user_display_name(user_id)
    label = display_name if display_name else user_id

    return f"{label}: {text}"


def _truncate_to_limit(messages: list[str], max_chars: int) -> list[str]:
    """Truncate from the oldest messages until total chars <= max_chars.

    Always preserves at least the last (newest) message even if it alone
    exceeds ``max_chars``.
    """
    if not messages:
        return []

    # Fast path: already within limit
    total = sum(len(m) for m in messages)
    if total <= max_chars:
        return list(messages)

    # Drop from the oldest end until we fit, keeping at least 1 message
    total = sum(len(m) for m in messages)
    i = 0
    while i < len(messages) - 1 and total > max_chars:
        total -= len(messages[i])
        i += 1
    return list(messages[i:])
