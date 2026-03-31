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
from opentree.runner.file_handler import build_file_context, cleanup_temp, download_files
from opentree.runner.progress import ProgressReporter, build_completion_blocks
from opentree.runner.session import SessionManager
from opentree.runner.slack_api import SlackAPI
from opentree.runner.task_queue import Task, TaskQueue, TaskStatus
from opentree.runner.thread_context import build_thread_context

logger = logging.getLogger(__name__)

# Bot commands recognised by the dispatcher.
# "status" and "help" are public (available to all users).
# "shutdown" requires admin authorization (see RunnerConfig.admin_users).
_BOT_COMMANDS: frozenset[str] = frozenset({"status", "help", "shutdown"})

# Matches a leading Slack user mention: <@UXXXXXXX>
_MENTION_RE = re.compile(r"^<@[A-Z0-9]+>")

# Help text shown in response to the "help" bot command.
_HELP_TEXT = (
    "Available commands:\n"
    "  *status*   — show bot status and queue stats\n"
    "  *help*     — show this help message\n"
    "  *shutdown* — gracefully stop the bot (admin only)\n"
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
        if lower in _BOT_COMMANDS:
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
        1. Create ProgressReporter and send initial "thinking" ack to Slack.
        2. Resolve user_name from Slack API; sanitize for filesystem safety.
        3. Download attached files (if any) and build file context string.
        4. Build thread context from thread history.
        5. Build :class:`~opentree.core.prompt.PromptContext` from task fields.
        6. Assemble system prompt.
        7. Look up existing session_id for thread continuity.
        8. Build message text (prepend thread context and file context).
        9. Run :class:`~opentree.runner.claude_process.ClaudeProcess` with
           progress callback.
        10. Send final result via ProgressReporter.complete().
        11. Persist session_id on success.
        12. Mark task completed or failed.
        13. Cleanup temp files in a finally block.

        Args:
            task: The task to execute.
        """
        reporter = ProgressReporter(
            slack_api=self._slack,
            channel=task.channel_id,
            thread_ts=task.thread_ts,
            interval=self._runner_config.progress_interval,
        )

        try:
            # Step 1: send initial ack via ProgressReporter.
            reporter.start()

            # Step 2: resolve user_name from Slack; sanitize for path safety.
            resolved_name = self._slack.get_user_display_name(task.user_id)
            if not resolved_name or not re.match(r"^[a-zA-Z0-9_-]+$", resolved_name):
                # Fallback to user_id which is always safe ([A-Z0-9]+).
                resolved_name = task.user_id

            # Step 3: download attached files and build file context.
            file_context: str = ""
            if task.files:
                bot_token: str = getattr(self._slack, "bot_token", "")
                downloaded = download_files(task.files, task.thread_ts, bot_token)
                file_context = build_file_context(downloaded)

            # Step 4: build thread context from history.
            thread_context: str = build_thread_context(
                self._slack,
                task.channel_id,
                task.thread_ts,
                self._slack.bot_user_id,
            )

            # Step 5: build PromptContext.
            context = self._build_prompt_context(task, user_name=resolved_name)

            # Step 6: assemble system prompt.
            system_prompt = assemble_system_prompt(
                self._home,
                self._registry,
                self._user_config,
                context,
            )

            # Step 7: look up existing session_id.
            session_id: str = self._session_mgr.get_session_id(task.thread_ts) or ""

            # Step 8: build message text with optional thread/file context prepended.
            message = self._build_message(task, thread_context=thread_context, file_context=file_context)

            # Step 9: run Claude with progress callback.
            claude = ClaudeProcess(
                config=self._runner_config,
                system_prompt=system_prompt,
                cwd=self._workspace_dir,
                session_id=session_id,
                message=message,
                progress_callback=reporter.update,
            )
            result: ClaudeResult = claude.run()

            # Step 10: send final result via ProgressReporter.
            try:
                elapsed = float(result.elapsed_seconds)
            except (TypeError, ValueError):
                elapsed = 0.0
            if result.is_timeout:
                reporter.complete(
                    response_text="",
                    elapsed=elapsed,
                    is_error=True,
                    error_message="Request timed out. Please try again.",
                )
                self._task_queue.mark_failed(task)
                return

            try:
                input_tokens = int(result.input_tokens)
            except (TypeError, ValueError):
                input_tokens = 0
            try:
                output_tokens = int(result.output_tokens)
            except (TypeError, ValueError):
                output_tokens = 0
            reporter.complete(
                response_text=result.response_text or "",
                elapsed=elapsed,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                is_error=result.is_error,
                error_message=result.error_message or "",
            )

            if result.is_error:
                self._task_queue.mark_failed(task)
                return

            # Step 11: persist session_id.
            if result.session_id:
                self._session_mgr.set_session_id(task.thread_ts, result.session_id)

            # Step 12: mark completed.
            self._task_queue.mark_completed(task)

        except Exception:
            logger.exception("Unexpected error while processing task %s", task.task_id)
            self._task_queue.mark_failed(task)
            if not reporter.message_ts:
                try:
                    self._slack.send_message(
                        task.channel_id,
                        ":x: An error occurred.",
                        thread_ts=task.thread_ts,
                    )
                except Exception:
                    pass

        finally:
            reporter.stop()
            # Step 13: always clean up temp files.
            cleanup_temp(task.thread_ts)

    def _build_message(
        self,
        task: Task,
        thread_context: str = "",
        file_context: str = "",
    ) -> str:
        """Build the message text to pass to Claude CLI.

        Prepends thread history context and file context (when available),
        then appends the user's message text.  When ``file_context`` is not
        provided (empty string) but ``task.files`` is non-empty, falls back to
        appending a brief file-reference list so the old call signature still
        works as before.

        Args:
            task: The task whose text is used.
            thread_context: Formatted thread history string (may be empty).
            file_context: Formatted file attachment string (may be empty).

        Returns:
            A string message for Claude.
        """
        parts: list[str] = []
        if thread_context:
            parts.append(thread_context)
        if file_context:
            parts.append(file_context)
        parts.append(task.text)
        # Fallback: include bare file refs when no rich file_context was given.
        if not file_context and task.files:
            file_refs = ", ".join(
                f.get("name", f.get("id", "unnamed")) for f in task.files
            )
            parts.append(f"[Attached files: {file_refs}]")
        return "\n".join(parts)

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
            if (
                self._runner_config.admin_users
                and task.user_id not in self._runner_config.admin_users
            ):
                self._slack.send_message(
                    task.channel_id,
                    ":lock: Only authorized admins can use the shutdown command.",
                    thread_ts=task.thread_ts,
                )
                return
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
