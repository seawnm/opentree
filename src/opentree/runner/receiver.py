"""Socket Mode event receiver for OpenTree bot runner.

Requires: pip install opentree[slack]
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from opentree.runner.task_queue import Task

logger = logging.getLogger(__name__)


def _check_slack_bolt() -> None:
    """Raise ImportError with helpful message if slack_bolt is not installed."""
    try:
        import slack_bolt  # noqa: F401
    except ImportError:
        raise ImportError(
            "slack_bolt is required for the bot runner. "
            "Install it with: pip install opentree[slack]"
        )


# These names are imported lazily inside start() but declared here so tests
# can patch them at the module level.
try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError:  # pragma: no cover
    App = None  # type: ignore[assignment,misc]
    SocketModeHandler = None  # type: ignore[assignment,misc]


class Receiver:
    """Socket Mode event receiver.

    Listens for @mention and DM events, deduplicates, and calls the
    dispatch_callback for each new event.

    Args:
        bot_token: Slack Bot Token (xoxb-...).
        app_token: Slack App-Level Token (xapp-...) for Socket Mode.
        bot_user_id: The bot's own Slack user ID (used to ignore self-messages).
        dispatch_callback: Called with a :class:`Task` for each accepted event.
        heartbeat_path: Optional path to write a heartbeat timestamp after each
            processed event. Parent directories are created automatically.
    """

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        bot_user_id: str,
        dispatch_callback: Callable,  # Callable[[Task], None]
        heartbeat_path: Optional[Path] = None,
    ) -> None:
        _check_slack_bolt()
        self._bot_token = bot_token
        self._app_token = app_token
        self._bot_user_id = bot_user_id
        self._dispatch = dispatch_callback
        self._heartbeat_path = heartbeat_path

        self._processed_ts: set[str] = set()
        self._processed_lock = threading.Lock()
        self._max_processed = 10_000  # limit memory growth

        self._app = None      # slack_bolt.App — created in start()
        self._handler = None  # SocketModeHandler — created in start()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Initialize bolt App and start Socket Mode handler (blocking).

        Creates a :class:`slack_bolt.App`, registers event handlers, then
        starts a :class:`SocketModeHandler` — which blocks until stopped.
        """
        self._app = App(token=self._bot_token)
        self._register_handlers()
        self._handler = SocketModeHandler(self._app, self._app_token)
        self._handler.start()

    def stop(self) -> None:
        """Stop the Socket Mode handler gracefully."""
        if self._handler is not None:
            self._handler.close()
            self._handler = None

    # ------------------------------------------------------------------
    # Private: event registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Register event handlers on the bolt App.

        - ``app_mention``: triggered when @bot is mentioned in any channel.
        - ``message``: triggered for direct messages (and other message events).
        """
        @self._app.event("app_mention")
        def handle_mention(event: dict, say: Callable) -> None:
            self._handle_app_mention(event, say)

        @self._app.event("message")
        def handle_message(event: dict, say: Callable) -> None:
            self._handle_message(event, say)

    # ------------------------------------------------------------------
    # Private: event handlers
    # ------------------------------------------------------------------

    def _handle_app_mention(self, event: dict, say: Callable) -> None:
        """Handle @mention events.

        Steps:
        1. Dedup check on event ``ts``.
        2. Extract fields and build a :class:`Task`.
        3. Call ``dispatch_callback(task)``.
        4. Write heartbeat.
        """
        ts = event.get("ts", "")
        if self._is_duplicate(ts):
            logger.debug("Skipping duplicate app_mention: ts=%s", ts)
            return

        task = self._build_task(event)
        self._dispatch(task)
        self._write_heartbeat()

    def _handle_message(self, event: dict, say: Callable) -> None:
        """Handle DM, thread reply, and bot-to-bot @mention events.

        Accepts:
        - Direct messages (channel_type == "im") from humans.
        - Messages from other bots that explicitly @mention this bot
          (Slack does not fire ``app_mention`` for bot-originated messages).

        Ignores:
        - Messages from this bot itself (prevents self-loop).
        - Messages with no text.
        - Non-DM channel messages without an explicit @mention of this bot.
        - Duplicate message timestamps.
        """
        # Always refresh heartbeat on any received event, even if the
        # message will be filtered out below.  This prevents the watchdog
        # from killing the bot during quiet periods when only bot traffic
        # or non-DM channel messages are arriving.
        self._write_heartbeat()

        # Ignore this bot's OWN messages (prevent self-loop)
        if event.get("user") == self._bot_user_id:
            return

        # Ignore messages without text
        text = event.get("text", "")
        if not text:
            return

        # Check if this bot is explicitly @mentioned in the message text.
        # Slack does NOT fire app_mention for bot-originated messages, so
        # other bots that @mention us arrive here as regular messages.
        has_bot_mention = f"<@{self._bot_user_id}>" in text

        # For messages from other bots: only process if they @mention us.
        if event.get("bot_id"):
            if not has_bot_mention:
                return
            # Bot @mentioned us — process it (fall through to dispatch).

        # For human messages: accept DMs or explicit @mentions.
        elif not has_bot_mention:
            channel_type = event.get("channel_type", "")
            if channel_type != "im":
                return

        ts = event.get("ts", "")
        if self._is_duplicate(ts):
            logger.debug("Skipping duplicate message: ts=%s", ts)
            return

        task = self._build_task(event)
        self._dispatch(task)
        # Heartbeat already written at top of method; no redundant write.

    # ------------------------------------------------------------------
    # Private: helpers
    # ------------------------------------------------------------------

    def _is_duplicate(self, ts: str) -> bool:
        """Thread-safe dedup check.

        Returns ``True`` if ``ts`` was already processed; ``False`` otherwise.
        Adds ``ts`` to the processed set on first call.

        When the set exceeds ``_max_processed``, the oldest half of entries
        (by lexicographic sort — Slack timestamps are chronologically sortable)
        are pruned.
        """
        with self._processed_lock:
            if ts in self._processed_ts:
                return True
            self._processed_ts.add(ts)
            if len(self._processed_ts) > self._max_processed:
                # Keep the newest half; Slack ts strings sort chronologically.
                keep = self._max_processed // 2
                self._processed_ts = set(sorted(self._processed_ts)[-keep:])
            return False

    def _write_heartbeat(self) -> None:
        """Write the current Unix timestamp to the heartbeat file.

        No-op when ``heartbeat_path`` was not provided. Parent directories are
        created automatically.
        """
        if self._heartbeat_path is None:
            return
        try:
            self._heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self._heartbeat_path.write_text(str(int(time.time())))
        except OSError as exc:
            logger.warning("Heartbeat write failed (%s): %s", self._heartbeat_path, exc)

    def _build_task(self, event: dict) -> Task:
        """Build a :class:`Task` from a Slack event dict.

        ``thread_ts`` is used when present so that replies are grouped with
        their thread root. If absent, ``ts`` is used as the thread root.
        """
        ts = event.get("ts", "")
        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts") or ts
        user_id = event.get("user", "")
        text = event.get("text", "")
        files = event.get("files", [])

        task_id = f"{channel_id}_{thread_ts}_{ts}"

        return Task(
            task_id=task_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_name="",  # resolved later by the runner if needed
            text=text,
            message_ts=ts,
            files=list(files),
        )
