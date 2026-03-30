"""Task dispatcher — coordinates event processing for OpenTree bot runner."""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from opentree.core.config import UserConfig, load_user_config
from opentree.core.prompt import PromptContext, assemble_system_prompt
from opentree.registry.models import RegistryData
from opentree.registry.registry import Registry
from opentree.runner.claude_process import ClaudeProcess, ClaudeResult
from opentree.runner.config import RunnerConfig, load_runner_config
from opentree.runner.session import SessionManager
from opentree.runner.slack_api import SlackAPI
from opentree.runner.task_queue import Task, TaskQueue, TaskStatus

logger = logging.getLogger(__name__)

# Admin commands recognised by the dispatcher.
_ADMIN_COMMANDS: frozenset[str] = frozenset({"status", "help", "shutdown"})

# Matches a leading Slack user mention: <@UXXXXXXX>
_MENTION_RE = re.compile(r"^<@[A-Z0-9]+>")

# Help text shown in response to the "help" admin command.
_HELP_TEXT = (
    "Available admin commands:\n"
    "  *status*   — show bot status and queue stats\n"
    "  *help*     — show this help message\n"
    "  *shutdown* — gracefully stop the bot\n"
)


@dataclass(frozen=True)
class ParsedMessage:
    """Immutable result of parsing a Slack message."""

    text: str
    is_admin_command: bool = False
    admin_command: str = ""
    files: list = field(default_factory=list)


class Dispatcher:
    """Coordinates event → Claude → Slack reply flow.

    Responsibilities:
    - Parse incoming Slack messages (strip mention, detect admin commands).
    - Build per-request :class:`~opentree.core.prompt.PromptContext`.
    - Submit tasks to :class:`~opentree.runner.task_queue.TaskQueue`.
    - Spawn worker threads for immediate tasks.
    - Send ack / result messages back through :class:`~opentree.runner.slack_api.SlackAPI`.
    - Manage Claude session continuity via :class:`~opentree.runner.session.SessionManager`.
    """

    def __init__(
        self,
        opentree_home: Path,
        slack_api: SlackAPI,
        shutdown_event: threading.Event,
    ) -> None:
        self._home = opentree_home
        self._slack = slack_api
        self._shutdown = shutdown_event

        # Load static configuration (user config, runner config).
        self._user_config: UserConfig = load_user_config(opentree_home)
        self._runner_config: RunnerConfig = load_runner_config(opentree_home)

        # Load module registry (used for system prompt assembly).
        self._registry: RegistryData = Registry.load(
            opentree_home / "config" / "registry.json"
        )

        # Session and task management.
        self._session_mgr = SessionManager(opentree_home / "data")
        self._task_queue = TaskQueue(self._runner_config.max_concurrent_tasks)

        # Working directory passed to Claude CLI via --cwd.
        self._workspace_dir = str(opentree_home / "workspace")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_message(
        self,
        text: str,
        bot_user_id: str,
        files: Optional[list] = None,
    ) -> ParsedMessage:
        """Parse a Slack message: strip leading @bot mention, detect admin commands.

        Args:
            text: Raw Slack message text (may contain ``<@BOT_USER_ID>``).
            bot_user_id: The bot's Slack user ID (used to identify the mention).
            files: List of Slack file attachment dicts, or None.

        Returns:
            A frozen :class:`ParsedMessage` instance.
        """
        files = files or []

        # Strip leading mention (only if it appears at the very start,
        # possibly preceded by whitespace).
        mention_pattern = re.compile(rf"^\s*<@{re.escape(bot_user_id)}>")
        cleaned = mention_pattern.sub("", text).strip()

        # Detect admin commands (exact match, case-insensitive).
        lower = cleaned.lower()
        if lower in _ADMIN_COMMANDS:
            return ParsedMessage(
                text=cleaned,
                is_admin_command=True,
                admin_command=lower,
                files=files,
            )

        return ParsedMessage(text=cleaned, files=files)

    def dispatch(self, task: Task) -> None:
        """Main dispatch entry point — called for each incoming Slack event.

        Parses the message first.  If it is an admin command, handles it
        immediately and returns.  Otherwise submits the task to the queue.
        If the task can start immediately, spawns a daemon worker thread.
        If the queue is full, sends a "queued" acknowledgement back to Slack.

        Args:
            task: The incoming task to process.
        """
        parsed = self.parse_message(task.text, self._slack.bot_user_id, files=task.files)
        if parsed.is_admin_command:
            self._handle_admin_command(task, parsed.admin_command)
            return

        # Update task text to the stripped (mention-removed) version.
        task.text = parsed.text

        can_start = self._task_queue.submit(task)

        if can_start:
            thread = threading.Thread(
                target=self._process_task,
                args=(task,),
                daemon=True,
                name=f"dispatcher-worker-{task.task_id}",
            )
            thread.start()
        else:
            # Task was queued; send acknowledgement.
            self._slack.send_message(
                task.channel_id,
                "Your request is queued and will be processed shortly.",
                thread_ts=task.thread_ts,
            )

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _process_task(self, task: Task) -> None:
        """Process a single task (runs in a worker thread).

        Steps:
        1. Send initial "thinking" ack to Slack.
        2. Resolve user_name from Slack API; sanitize for filesystem safety.
        3. Build :class:`~opentree.core.prompt.PromptContext` from task fields.
        4. Assemble system prompt.
        5. Look up existing session_id for thread continuity.
        6. Build message text (include file references if any).
        7. Run :class:`~opentree.runner.claude_process.ClaudeProcess`.
        8. Send result to Slack (update ack or new message).
        9. Persist session_id on success.
        10. Mark task completed or failed.

        Args:
            task: The task to execute.
        """
        ack_ts: str = ""

        try:
            # Step 1: send initial ack.
            ack_resp = self._slack.send_message(
                task.channel_id,
                ":hourglass_flowing_sand: Processing...",
                thread_ts=task.thread_ts,
            )
            ack_ts = ack_resp.get("ts", "") if isinstance(ack_resp, dict) else ""

            # Step 2: resolve user_name from Slack; sanitize for path safety.
            resolved_name = self._slack.get_user_display_name(task.user_id)
            if not resolved_name or not re.match(r"^[a-zA-Z0-9_-]+$", resolved_name):
                # Fallback to user_id which is always safe ([A-Z0-9]+).
                resolved_name = task.user_id

            # Step 3: build PromptContext.
            context = self._build_prompt_context(task, user_name=resolved_name)

            # Step 3: assemble system prompt.
            system_prompt = assemble_system_prompt(
                self._home,
                self._registry,
                self._user_config,
                context,
            )

            # Step 4: look up existing session_id.
            session_id: str = self._session_mgr.get_session_id(task.thread_ts) or ""

            # Step 5: build message text.
            message = self._build_message(task)

            # Step 6: run Claude.
            claude = ClaudeProcess(
                config=self._runner_config,
                system_prompt=system_prompt,
                cwd=self._workspace_dir,
                session_id=session_id,
                message=message,
            )
            result: ClaudeResult = claude.run()

            # Step 7: send result to Slack.
            if result.is_timeout:
                self._send_result(
                    task,
                    ack_ts,
                    ":clock1: Request timed out. Please try again.",
                )
                self._task_queue.mark_failed(task)
                return

            if result.is_error:
                error_text = (
                    f":x: Error: {result.error_message}"
                    if result.error_message
                    else ":x: An unexpected error occurred."
                )
                self._send_result(task, ack_ts, error_text)
                self._task_queue.mark_failed(task)
                return

            # Success path.
            self._send_result(task, ack_ts, result.response_text or "(no response)")

            # Step 8: persist session_id.
            if result.session_id:
                self._session_mgr.set_session_id(task.thread_ts, result.session_id)

            # Step 9: mark completed.
            self._task_queue.mark_completed(task)

        except Exception:
            logger.exception("Unexpected error while processing task %s", task.task_id)
            self._task_queue.mark_failed(task)

    def _build_message(self, task: Task) -> str:
        """Build the message text to pass to Claude CLI.

        Appends brief file references when the task has attached files.

        Args:
            task: The task whose text and files are used.

        Returns:
            A string message for Claude.
        """
        parts: list[str] = [task.text]
        if task.files:
            file_refs = ", ".join(
                f.get("name", f.get("id", "unnamed")) for f in task.files
            )
            parts.append(f"[Attached files: {file_refs}]")
        return "\n".join(parts)

    def _send_result(self, task: Task, ack_ts: str, text: str) -> None:
        """Update the ack message with the final result, or send a new one.

        Args:
            task: The originating task (for channel/thread info).
            ack_ts: Timestamp of the ack message to update (may be empty).
            text: The text to send.
        """
        if ack_ts:
            self._slack.update_message(task.channel_id, ack_ts, text=text)
        else:
            self._slack.send_message(task.channel_id, text, thread_ts=task.thread_ts)

    # ------------------------------------------------------------------
    # PromptContext builder
    # ------------------------------------------------------------------

    def _build_prompt_context(self, task: Task, user_name: str = "") -> PromptContext:
        """Build a per-request :class:`~opentree.core.prompt.PromptContext`.

        Each task gets its own context so that user_id, channel_id, and
        thread_ts are always accurate for the current Slack event.

        Args:
            task: The task for which to build a context.
            user_name: Pre-resolved and sanitized user display name.  Must
                match ``^[a-zA-Z0-9_-]+$`` or be the user_id fallback so it
                is safe to embed in a filesystem path.  Defaults to
                ``task.user_name`` when not provided (test-only path).

        Returns:
            A frozen :class:`PromptContext` instance.
        """
        name = user_name or task.user_name
        memory_path = str(
            self._home / "data" / "memory" / name / "memory.md"
        )
        return PromptContext(
            user_id=task.user_id,
            user_name=name,
            channel_id=task.channel_id,
            thread_ts=task.thread_ts,
            workspace="default",
            team_name=self._user_config.team_name,
            memory_path=memory_path,
        )

    # ------------------------------------------------------------------
    # Admin command handlers
    # ------------------------------------------------------------------

    def _handle_admin_command(self, task: Task, command: str) -> None:
        """Dispatch an admin command to the appropriate handler.

        Args:
            task: The task that triggered the admin command.
            command: Normalised (lowercase) command string.
        """
        if command == "status":
            self._handle_status(task)
        elif command == "help":
            self._handle_help(task)
        elif command == "shutdown":
            self._handle_shutdown(task)
        else:
            logger.warning("Unknown admin command: %s", command)

    def _handle_status(self, task: Task) -> None:
        """Send bot status info to Slack.

        Args:
            task: The task for routing the reply.
        """
        stats = self.get_stats()
        lines = [
            "*Bot Status*",
            f"Running tasks: {stats.get('running', 0)}",
            f"Pending tasks: {stats.get('pending', 0)}",
            f"Completed tasks: {stats.get('completed', 0)}",
            f"Failed tasks: {stats.get('failed', 0)}",
            f"Max concurrent: {stats.get('max_concurrent', 0)}",
        ]
        self._slack.send_message(
            task.channel_id,
            "\n".join(lines),
            thread_ts=task.thread_ts,
        )

    def _handle_help(self, task: Task) -> None:
        """Send help text to Slack.

        Args:
            task: The task for routing the reply.
        """
        self._slack.send_message(
            task.channel_id,
            _HELP_TEXT,
            thread_ts=task.thread_ts,
        )

    def _handle_shutdown(self, task: Task) -> None:
        """Request graceful bot shutdown.

        Sets the shared shutdown event and notifies the user.

        Args:
            task: The task for routing the reply.
        """
        self._slack.send_message(
            task.channel_id,
            ":wave: Shutting down gracefully...",
            thread_ts=task.thread_ts,
        )
        self._shutdown.set()

    # ------------------------------------------------------------------
    # Stats / properties
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return dispatcher statistics (delegates to TaskQueue).

        Returns:
            A dict with keys: running, pending, completed, failed, max_concurrent.
        """
        return self._task_queue.get_stats()

    @property
    def task_queue(self) -> TaskQueue:
        """Expose the task queue for external use (e.g. graceful shutdown).

        Returns:
            The internal :class:`~opentree.runner.task_queue.TaskQueue` instance.
        """
        return self._task_queue
