"""Bot lifecycle manager for OpenTree bot runner."""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from opentree.runner.config import load_runner_config
from opentree.runner.dispatcher import Dispatcher
from opentree.runner.health import check_disk_usage
from opentree.runner.logging_config import setup_logging
from opentree.runner.receiver import Receiver
from opentree.runner.sandbox_launcher import check_bwrap_or_raise
from opentree.runner.slack_api import SlackAPI

logger = logging.getLogger(__name__)

# Prefixes that indicate a .env.example placeholder value rather than a real token.
# SYNC WITH: src/opentree/cli/init.py::_PLACEHOLDER_PREFIXES
# If you add a prefix here, you MUST add it there too (and vice versa).
_PLACEHOLDER_PREFIXES = (
    "xoxb-your-",
    "xapp-your-",
    "your-",
    "xoxb-xxx",
    "xapp-xxx",
)


def _is_placeholder(value: str) -> bool:
    """Return True if *value* looks like a .env.example placeholder."""
    return any(value.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES)


def _validate_not_placeholder(value: str, name: str) -> None:
    """Raise RuntimeError if *value* looks like a .env.example placeholder."""
    if _is_placeholder(value):
        matched = next(
            (p for p in _PLACEHOLDER_PREFIXES if value.startswith(p)),
            "<unknown prefix>",
        )
        raise RuntimeError(
            f"{name} appears to be a placeholder (starts with '{matched}'). "
            "Update your .env file."
        )


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

    # Interval (seconds) between periodic disk health checks.
    _HEALTH_CHECK_INTERVAL: int = 3600  # 1 hour

    def __init__(self, opentree_home: Path) -> None:
        self._home = opentree_home
        self._shutdown_event = threading.Event()
        self._start_time: float = 0.0
        self._heartbeat_path: Optional[Path] = None
        self._exit_code: int = 0
        self._health_timer: Optional[threading.Timer] = None
        self._last_health: Optional[dict] = None

        # Components (initialized in start())
        self._slack_api: Optional[SlackAPI] = None
        self._dispatcher: Optional[Dispatcher] = None
        self._receiver: Optional[Receiver] = None
        self._runner_config = None

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
        file_logging_active = setup_logging(log_dir)
        if not file_logging_active:
            logger.warning(
                "File logging unavailable (log_dir: %s); running in console-only mode",
                log_dir,
            )
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
        # Skip bwrap check when danger-full-access is configured — this mode
        # intentionally runs without any sandbox for full host filesystem access.
        _runner_config_precheck = load_runner_config(self._home)
        if _runner_config_precheck.codex_sandbox != "danger-full-access":
            check_bwrap_or_raise()
        self._dispatcher = Dispatcher(self._home, self._slack_api, self._shutdown_event)
        self._runner_config = _runner_config_precheck

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

        # Run initial health check and schedule periodic checks
        self._run_health_check()

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
            # Propagate exit code from dispatcher (restart=1, shutdown=0)
            if self._dispatcher is not None:
                self._exit_code = self._dispatcher.exit_code
            self._shutdown()
            if self._exit_code != 0:
                sys.exit(self._exit_code)

    # ------------------------------------------------------------------
    # Private: token loading
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_env_file(path: Path) -> dict[str, str]:
        """Parse a .env file into a dict of key-value pairs.

        Format: KEY=VALUE (one per line, # comments, empty lines ok)
        Quoted values (single or double quotes) are stripped.
        """
        tokens: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
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
        return tokens

    def _load_tokens(self) -> tuple[str, str]:
        """Load SLACK_BOT_TOKEN and SLACK_APP_TOKEN from layered .env files.

        Three-layer merge (highest priority last):
        1. config/.env.defaults — bot-level defaults
        2. config/.env.local   — owner customization / overrides
        3. config/.env.secrets — deployment secrets (highest priority)

        Fallback: if only config/.env exists (legacy), use it with a WARNING.

        Raises:
            RuntimeError: If no .env file is found or required tokens
                are absent.
        """
        config_dir = self._home / "config"
        defaults_path = config_dir / ".env.defaults"
        local_path = config_dir / ".env.local"
        secrets_path = config_dir / ".env.secrets"
        legacy_path = config_dir / ".env"

        tokens: dict[str, str] = {}
        loaded_any = False

        if defaults_path.exists():
            tokens.update(self._parse_env_file(defaults_path))
            loaded_any = True
            if local_path.exists():
                tokens.update(self._parse_env_file(local_path))
            if secrets_path.exists():
                tokens.update(self._parse_env_file(secrets_path))

            # Fallback: if tokens are still placeholders and legacy .env exists,
            # try loading from legacy .env (handles --force re-init scenario).
            bot_val = tokens.get("SLACK_BOT_TOKEN", "")
            app_val = tokens.get("SLACK_APP_TOKEN", "")
            if (
                legacy_path.exists()
                and (_is_placeholder(bot_val) or _is_placeholder(app_val))
            ):
                logger.warning(
                    "Tokens in .env.defaults are placeholders; "
                    "falling back to legacy config/.env at %s. "
                    "Run 'opentree init --force' to migrate.",
                    legacy_path,
                )
                legacy_tokens = self._parse_env_file(legacy_path)
                # Only override placeholder values, preserve real tokens
                for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
                    if _is_placeholder(tokens.get(key, "")) and key in legacy_tokens:
                        tokens[key] = legacy_tokens[key]

        elif legacy_path.exists():
            logger.warning(
                "Legacy config/.env detected at %s. "
                "Consider migrating to .env.defaults + .env.local.",
                legacy_path,
            )
            tokens.update(self._parse_env_file(legacy_path))
            loaded_any = True

        if not loaded_any:
            raise RuntimeError(
                "No .env file found. "
                "Create config/.env.defaults (or config/.env for legacy mode) "
                "with SLACK_BOT_TOKEN and SLACK_APP_TOKEN."
            )

        bot_token = tokens.get("SLACK_BOT_TOKEN", "")
        app_token = tokens.get("SLACK_APP_TOKEN", "")

        if not bot_token:
            raise RuntimeError(
                "SLACK_BOT_TOKEN is missing. "
                "Set it in config/.env.defaults or config/.env.local."
            )
        if not app_token:
            raise RuntimeError(
                "SLACK_APP_TOKEN is missing. "
                "Set it in config/.env.defaults or config/.env.local."
            )

        # Reject .env.example placeholder values
        _validate_not_placeholder(bot_token, "SLACK_BOT_TOKEN")
        _validate_not_placeholder(app_token, "SLACK_APP_TOKEN")

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
    # Private: health monitoring
    # ------------------------------------------------------------------

    def _schedule_health_check(self) -> None:
        """Schedule the next periodic health check (daemon timer)."""
        if self._shutdown_event.is_set():
            return
        self._health_timer = threading.Timer(
            self._HEALTH_CHECK_INTERVAL,
            self._run_health_check,
        )
        self._health_timer.daemon = True
        self._health_timer.start()

    def _run_health_check(self) -> None:
        """Execute a health check and log a warning if disk is low."""
        data_dir = self._home / "data"
        try:
            result = check_disk_usage(data_dir)
            self._last_health = result
            if result["warning"]:
                logger.warning(
                    "Low disk space: %d MB free (data_dir: %d MB)",
                    result["free_mb"],
                    result["data_dir_mb"],
                )
            else:
                logger.debug(
                    "Health check OK: %d MB free (data_dir: %d MB)",
                    result["free_mb"],
                    result["data_dir_mb"],
                )
        except OSError as exc:
            logger.warning("Health check failed: %s", exc)
        finally:
            self._schedule_health_check()

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

        # Cancel health check timer
        if self._health_timer is not None:
            self._health_timer.cancel()

        # Drain tasks if dispatcher is available
        if self._dispatcher is not None:
            runner_config = self._runner_config if self._runner_config is not None else load_runner_config(self._home)
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
    def exit_code(self) -> int:
        """The exit code to use when the bot process terminates.

        0 = clean shutdown (wrapper will NOT restart).
        Non-zero = crash/restart signal (wrapper WILL restart).
        """
        return self._exit_code

    @property
    def uptime_seconds(self) -> float:
        """Seconds since bot started. Returns time.time() - _start_time."""
        if self._start_time == 0.0:
            return 0.0
        return time.time() - self._start_time

    @property
    def health_status(self) -> Optional[dict]:
        """Most recent health check result, or ``None`` if not yet run."""
        return self._last_health

    @property
    def is_running(self) -> bool:
        """Whether the bot is currently running.

        True when start() has been called (_start_time > 0) and
        the shutdown event has not been set.
        """
        return self._start_time > 0.0 and not self._shutdown_event.is_set()
