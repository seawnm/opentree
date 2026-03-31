"""Slack Web API wrapper for OpenTree bot runner.

SDK-only mode — no Legacy (xoxc/xoxd) support.
Requires: pip install opentree[slack]
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_data(result) -> dict:
    """Extract response data from a SlackResponse or dict.

    slack_sdk's SlackResponse has a ``.data`` property that returns the
    underlying dict. We also handle plain dicts for testing.

    The SlackResponse object itself is NOT safely convertible via ``dict()``
    because its ``__iter__`` yields paginated responses, not key-value pairs.
    """
    if isinstance(result, dict):
        return result
    # SlackResponse — access the .data property which returns a dict
    try:
        data = result.data
        if isinstance(data, dict):
            return data
        logger.warning("_extract_data: result.data is %s, not dict", type(data).__name__)
    except AttributeError:
        pass
    # No safe fallback — return empty dict rather than attempting dict(result)
    # which would fail for SlackResponse objects.
    return {}


def _check_slack_sdk() -> None:
    """Raise ImportError with helpful message if slack_sdk is not installed."""
    try:
        import slack_sdk  # noqa: F401
    except ImportError:
        raise ImportError(
            "slack_sdk is required for the bot runner. "
            "Install it with: pip install opentree[slack]"
        )


class SlackAPI:
    """Thin wrapper around slack_sdk.WebClient.

    Provides SDK-only Slack API access with:
    - User and channel name caching to reduce API calls.
    - Error isolation: all methods log errors but never raise.
    - Rate limit handling delegated to slack_sdk's built-in retry.

    Args:
        bot_token: A Slack Bot Token (xoxb-...).

    Raises:
        ImportError: If slack_sdk is not installed.
    """

    def __init__(self, bot_token: str) -> None:
        _check_slack_sdk()
        from slack_sdk import WebClient

        self._bot_token = bot_token
        self._client = WebClient(token=bot_token)
        self._user_cache: dict[str, str] = {}     # user_id -> display_name
        self._channel_cache: dict[str, str] = {}  # channel_id -> name
        self._bot_user_id: str = ""

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def auth_test(self) -> dict:
        """Verify the bot token and retrieve bot identity.

        Sets ``_bot_user_id`` on success.

        Returns:
            The raw API response dict, or ``{}`` on error.
        """
        try:
            result = self._client.auth_test()
            # SlackResponse is dict-like; access .data for the raw dict
            data = _extract_data(result)
            self._bot_user_id = data.get("user_id", "")
            return data
        except Exception as exc:
            logger.error("auth_test failed: %s", exc)
            return {}

    @property
    def bot_user_id(self) -> str:
        """The bot's own Slack user ID.

        Empty string until :meth:`auth_test` has been called successfully.
        """
        return self._bot_user_id

    @property
    def bot_token(self) -> str:
        """The Slack Bot Token used to authenticate this client."""
        return self._bot_token

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: str = "",
    ) -> dict:
        """Post a message to a channel or thread.

        Args:
            channel: Slack channel ID (e.g. ``C01234``).
            text: Message text.
            thread_ts: If non-empty, reply to this thread timestamp.

        Returns:
            The API response dict (contains ``ts`` on success), or ``{}`` on error.
        """
        try:
            kwargs: dict = {"channel": channel, "text": text}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            result = self._client.chat_postMessage(**kwargs)
            return _extract_data(result)
        except Exception as exc:
            logger.error("send_message failed (channel=%s): %s", channel, exc)
            return {}

    def update_message(
        self,
        channel: str,
        ts: str,
        text: str = "",
        blocks: Optional[list] = None,
    ) -> dict:
        """Update an existing message.

        Args:
            channel: Slack channel ID.
            ts: Timestamp of the message to update.
            text: New text content (optional if ``blocks`` provided).
            blocks: New Block Kit blocks (optional).

        Returns:
            The API response dict, or ``{}`` on error.
        """
        try:
            kwargs: dict = {"channel": channel, "ts": ts}
            if text:
                kwargs["text"] = text
            if blocks is not None:
                kwargs["blocks"] = blocks
            result = self._client.chat_update(**kwargs)
            return _extract_data(result)
        except Exception as exc:
            logger.error("update_message failed (channel=%s, ts=%s): %s", channel, ts, exc)
            return {}

    # ------------------------------------------------------------------
    # Thread
    # ------------------------------------------------------------------

    def get_thread_replies(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve all replies in a thread.

        Args:
            channel: Slack channel ID.
            thread_ts: Parent message timestamp.
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts, or ``[]`` on error.
        """
        try:
            result = self._client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=limit,
            )
            data = _extract_data(result)
            return data.get("messages", [])
        except Exception as exc:
            logger.error(
                "get_thread_replies failed (channel=%s, thread_ts=%s): %s",
                channel,
                thread_ts,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # User / Channel lookup (cached)
    # ------------------------------------------------------------------

    def get_user_display_name(self, user_id: str) -> str:
        """Return the display name for a user, cached after the first lookup.

        Args:
            user_id: Slack user ID (e.g. ``U01234``).

        Returns:
            Display name string, or ``""`` if unavailable.
        """
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        try:
            result = self._client.users_info(user=user_id)
            data = _extract_data(result)
            user = data.get("user", {})
            profile = user.get("profile", {})
            name = profile.get("display_name", "")
            self._user_cache[user_id] = name
            return name
        except Exception as exc:
            logger.error("get_user_display_name failed (user_id=%s): %s", user_id, exc)
            return ""

    def get_channel_name(self, channel_id: str) -> str:
        """Return the channel name for a channel ID, cached after the first lookup.

        Args:
            channel_id: Slack channel ID (e.g. ``C01234``).

        Returns:
            Channel name string (without ``#``), or ``""`` if unavailable.
        """
        if channel_id in self._channel_cache:
            return self._channel_cache[channel_id]

        try:
            result = self._client.conversations_info(channel=channel_id)
            data = _extract_data(result)
            name = data.get("channel", {}).get("name", "")
            self._channel_cache[channel_id] = name
            return name
        except Exception as exc:
            logger.error("get_channel_name failed (channel_id=%s): %s", channel_id, exc)
            return ""

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def get_team_info(self) -> dict:
        """Retrieve workspace (team) information.

        Returns:
            The API response dict, or ``{}`` on error.
        """
        try:
            result = self._client.team_info()
            return _extract_data(result)
        except Exception as exc:
            logger.error("get_team_info failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def upload_file(
        self,
        channel: str,
        file_path: str,
        thread_ts: str = "",
        title: str = "",
        comment: str = "",
    ) -> dict:
        """Upload a file to a Slack channel or thread.

        Args:
            channel: Slack channel ID.
            file_path: Absolute path to the local file.
            thread_ts: If non-empty, attach to this thread.
            title: Display title for the file (defaults to filename).
            comment: Initial comment attached alongside the file.

        Returns:
            The API response dict, or ``{}`` on error (including missing file).
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("upload_file: file does not exist: %s", file_path)
            return {}

        try:
            kwargs: dict = {
                "channel": channel,
                "file": file_path,
                "title": title or path.name,
            }
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            if comment:
                kwargs["initial_comment"] = comment

            result = self._client.files_upload_v2(**kwargs)
            return _extract_data(result)
        except Exception as exc:
            logger.error("upload_file failed (channel=%s, file=%s): %s", channel, file_path, exc)
            return {}

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def add_reaction(self, channel: str, ts: str, emoji: str) -> bool:
        """Add an emoji reaction to a message.

        Errors are swallowed (e.g. ``already_reacted``).

        Args:
            channel: Slack channel ID.
            ts: Message timestamp.
            emoji: Emoji name without colons (e.g. ``thumbsup``).

        Returns:
            ``True`` on success, ``False`` on any error.
        """
        try:
            self._client.reactions_add(
                channel=channel,
                timestamp=ts,
                name=emoji,
            )
            return True
        except Exception as exc:
            logger.warning("add_reaction failed (channel=%s, ts=%s, emoji=%s): %s", channel, ts, emoji, exc)
            return False
