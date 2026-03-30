"""Bot lifecycle manager for OpenTree bot runner."""
from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from typing import Optional

from opentree.runner.config import load_runner_config
from opentree.runner.dispatcher import Dispatcher
from opentree.runner.logging_config import setup_logging
from opentree.runner.receiver import Receiver
from opentree.runner.slack_api import SlackAPI

logger = logging.getLogger(__name__)


class Bot:
    """OpenTree Slack Bot — lifecycle manager.

    Startup sequence:
    1. Load .env (bot token, app token)
    2. Initialize SlackAPI + auth_test
    3. Initialize Dispatcher
    4. Initialize Receiver with dispatch_callback
    5. Register signal handlers (SIGTERM, SIGINT)
    6. Start Receiver (blocks until stopped)

    Shutdown sequence:
    1. Signal received -> shutdown_event.set()
    2. Receiver.stop() -> close WebSocket
    3. Dispatcher.task_queue.wait_for_drain(timeout)
    4. Cleanup (heartbeat remove)
    """

    def __init__(self, opentree_home: Path) -> None:
        self._home = opentree_home
        self._shutdown_event = threading.Event()
        self._start_time: float = 0.0
        self._heartbeat_path: Optional[Path] = None

        # Components (initialized in start())
        self._slack_api: Optional[SlackAPI] = None
        self._dispatcher: Optional[Dispatcher] = None
        self._receiver: Optional[Receiver] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the bot. Blocks until shutdown.

        Steps:
        1. _load_tokens() -> bot_token, app_token from .env
        2. SlackAPI(bot_token) + auth_test()
        3. Dispatcher(home, slack_api, shutdown_event)
        4. _setup_signal_handlers()
        5. Receiver(bot_token, app_token, bot_user_id, dispatcher.dispatch, heartbeat_path)
        6. Log startup info
        7. receiver.start() (blocks)
        8. On return/exception: _shutdown()
        """
        log_dir = self._home / "data" / "logs"
        setup_logging(log_dir)
        logger.info("OpenTree Bot starting (home: %s)", self._home)

        bot_token, app_token = self._load_tokens()

        # Step 2: initialize SlackAPI and verify credentials
        self._slack_api = SlackAPI(bot_token)
        auth_result = self._slack_api.auth_test()
        bot_user_id = self._slack_api.bot_user_id
        if not bot_user_id:
            raise RuntimeError(
                "auth_test did not return a bot user_id. "
                "Check that SLACK_BOT_TOKEN is valid."
            )

        logger.info("Bot authenticated as %s", bot_user_id)

        # Step 3: initialize Dispatcher
        self._dispatcher = Dispatcher(self._home, self._slack_api, self._shutdown_event)

        # Step 4: register signal handlers
        self._setup_signal_handlers()

        # Determine heartbeat path
        self._heartbeat_path = self._home / "data" / "bot.heartbeat"

        # Step 5: initialize Receiver
        self._receiver = Receiver(
            bot_token=bot_token,
            app_token=app_token,
            bot_user_id=bot_user_id,
            dispatch_callback=self._dispatcher.dispatch,
            heartbeat_path=self._heartbeat_path,
        )

        self._start_time = time.time()
        logger.info(
            "OpenTree bot starting — home=%s, bot_user_id=%s",
            self._home,
            bot_user_id,
        )

        try:
            # Step 7: start receiver (blocks until stopped)
            self._receiver.start()
        finally:
            # Step 8: graceful shutdown
            self._shutdown()

    # ------------------------------------------------------------------
    # Private: token loading
    # ------------------------------------------------------------------

    def _load_tokens(self) -> tuple[str, str]:
        """Load SLACK_BOT_TOKEN and SLACK_APP_TOKEN from .env file.

        Reads from $OPENTREE_HOME/config/.env
        Format: KEY=VALUE (one per line, # comments, empty lines ok)
        Quoted values (single or double quotes) are stripped.

        Raises:
            RuntimeError: If the .env file is missing or required tokens
                are absent.
        """
        env_path = self._home / "config" / ".env"
        if not env_path.exists():
            raise RuntimeError(
                f".env file not found at {env_path}. "
                "Create config/.env with SLACK_BOT_TOKEN and SLACK_APP_TOKEN."
            )

        tokens: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes (single or double)
            if len(value) >= 2 and value[0] in ('"', "'") and value[0] == value[-1]:
                value = value[1:-1]
            tokens[key] = value

        bot_token = tokens.get("SLACK_BOT_TOKEN", "")
        app_token = tokens.get("SLACK_APP_TOKEN", "")

        if not bot_token:
            raise RuntimeError(
                "SLACK_BOT_TOKEN is missing from config/.env"
            )
        if not app_token:
            raise RuntimeError(
                "SLACK_APP_TOKEN is missing from config/.env"
            )

        return bot_token, app_token

    # ------------------------------------------------------------------
    # Private: signal handling
    # ------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:  # type: ignore[type-arg]
        """Signal handler: set shutdown event and stop receiver.

        Designed to be called from the main thread signal handler context.
        Only sets an event and delegates to receiver.stop() which is
        safe to call from a signal handler.
        """
        logger.info("Received signal %s, initiating shutdown...", signum)
        self._shutdown_event.set()
        if self._receiver is not None:
            self._receiver.stop()

    # ------------------------------------------------------------------
    # Private: shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """Graceful shutdown: drain tasks, cleanup.

        1. Wait for running tasks to complete (drain_timeout from RunnerConfig)
        2. Remove heartbeat file
        3. Log shutdown
        """
        logger.info("Initiating graceful shutdown...")

        # Drain tasks if dispatcher is available
        if self._dispatcher is not None:
            runner_config = load_runner_config(self._home)
            drain_timeout = runner_config.drain_timeout
            drained = self._dispatcher.task_queue.wait_for_drain(timeout=drain_timeout)
            if not drained:
                logger.warning(
                    "Task drain timed out after %ss; some tasks may be incomplete.",
                    drain_timeout,
                )

        # Remove heartbeat file
        if self._heartbeat_path is not None:
            try:
                if self._heartbeat_path.exists():
                    self._heartbeat_path.unlink()
            except OSError as exc:
                logger.warning("Failed to remove heartbeat file: %s", exc)

        uptime = self.uptime_seconds
        logger.info("Bot shutdown complete. Uptime: %.1fs", uptime)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def uptime_seconds(self) -> float:
        """Seconds since bot started. Returns time.time() - _start_time."""
        if self._start_time == 0.0:
            return 0.0
        return time.time() - self._start_time

    @property
    def is_running(self) -> bool:
        """Whether the bot is currently running.

        True when start() has been called (_start_time > 0) and
        the shutdown event has not been set.
        """
        return self._start_time > 0.0 and not self._shutdown_event.is_set()
