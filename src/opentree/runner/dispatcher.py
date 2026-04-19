"""Task dispatcher — coordinates event processing for OpenTree bot runner."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from opentree.core.config import UserConfig, load_user_config
from opentree.core.prompt import PromptContext, assemble_system_prompt
from opentree.registry.models import RegistryData
from opentree.registry.registry import Registry
from opentree.runner.circuit_breaker import CircuitBreaker
from opentree.runner.claude_process import ClaudeResult
from opentree.runner.codex_process import CodexProcess
from opentree.runner.codex_stream_parser import Phase
from opentree.runner.config import RunnerConfig, load_runner_config
from opentree.runner.reset import reset_bot, reset_bot_all
from opentree.runner.retry import RetryConfig, classify_error, should_retry
from opentree.runner.file_handler import build_file_context, cleanup_temp, download_files
from opentree.runner.progress import ProgressReporter
from opentree.runner.session import SessionManager
from opentree.runner.slack_api import SlackAPI
from opentree.runner.task_queue import Task, TaskQueue
from opentree.runner.thread_context import build_thread_context
from opentree.runner.tool_tracker import ToolTracker

logger = logging.getLogger(__name__)

# Bot commands recognised by the dispatcher.
# "status" and "help" are public (available to all users).
# "shutdown" requires admin authorization (see RunnerConfig.admin_users).
_BOT_COMMANDS: frozenset[str] = frozenset({
    "status", "help", "shutdown", "restart", "reset-bot", "reset-bot-all"
})

# Matches a leading Slack user mention: <@UXXXXXXX>
_MENTION_RE = re.compile(r"^<@[A-Z0-9]+>")

# Help text shown in response to the "help" bot command.
_HELP_TEXT = (
    "Available commands:\n"
    "  *status*        — show bot status and queue stats\n"
    "  *help*          — show this help message\n"
    "  *restart*       — restart the bot (Owner only)\n"
    "  *shutdown*      — gracefully stop the bot (Owner only)\n"
    "  *reset-bot*     — soft reset: regenerate config, clear sessions (Owner only)\n"
    "  *reset-bot-all* — hard reset: clear all data and customizations (Owner only)\n"
)


@dataclass(frozen=True)
class ParsedMessage:
    """Immutable result of parsing a Slack message."""

    text: str
    is_admin_command: bool = False
    admin_command: str = ""
    files: tuple = ()


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

        # Circuit breaker: stops sending requests to Claude CLI when it
        # fails consecutively, preventing cascading failures.
        self._circuit_breaker = CircuitBreaker()

        # Layer 2 dedup: prevents duplicate dispatch even if Receiver
        # layer misses due to concurrent handler execution.
        self._dispatched_ts: set[str] = set()
        self._dispatched_ts_lock = threading.Lock()

        # Exit code: 0 = clean shutdown, non-zero = restart requested.
        self._exit_code: int = 0

        # Cache: memory paths confirmed to belong to existing (non-new) users.
        # Once _check_new_user returns False for a path, the result is stable
        # (content only grows), so we skip subsequent file reads.
        self._known_existing_users: set[str] = set()

        # Working directory passed to Claude CLI via --cwd.
        self._workspace_dir = str(opentree_home / "workspace")

        # Start queue watchdog: monitors pending tasks for stale waiting.
        self._queue_watchdog_thread = threading.Thread(
            target=self._queue_watchdog,
            name="queue-watchdog",
            daemon=True,
        )
        self._queue_watchdog_thread.start()

    # ------------------------------------------------------------------
    # Queue watchdog: cancel tasks that wait too long in the queue
    # ------------------------------------------------------------------

    def _queue_watchdog(self) -> None:
        """Background thread: scan pending queue and expire stale tasks.

        A task that has been waiting in the queue for longer than
        ``task_timeout`` (default 1800s) is considered stale — the user
        has likely moved on.  We cancel it and send a notification so
        they know to retry later.

        This prevents silent task loss when the bot restarts or when the
        queue is saturated for an extended period.
        """
        poll_interval = 30.0  # seconds between scans
        while not self._shutdown.is_set():
            self._shutdown.wait(timeout=poll_interval)
            if self._shutdown.is_set():
                break
            try:
                self._expire_stale_pending_tasks()
            except Exception as exc:
                logger.warning("queue_watchdog error: %s", exc)

    def _expire_stale_pending_tasks(self) -> None:
        """Cancel pending tasks that have waited beyond task_timeout."""
        now = time.time()
        queue_timeout = getattr(self._runner_config, "task_timeout", 1800)

        with self._task_queue._lock:  # noqa: SLF001  (necessary for atomic drain)
            stale: list[Task] = [
                t for t in self._task_queue._pending  # noqa: SLF001
                if (now - t.created_at) >= queue_timeout
            ]
            for t in stale:
                try:
                    self._task_queue._pending.remove(t)  # noqa: SLF001
                except ValueError:
                    pass  # already removed by another path

        for task in stale:
            logger.warning(
                "Queue watchdog: task %s expired after %.0fs waiting (thread_ts=%s)",
                task.task_id,
                now - task.created_at,
                task.thread_ts,
            )
            try:
                if task.queued_ack_ts:
                    try:
                        self._slack.delete_message(task.channel_id, task.queued_ack_ts)
                    except Exception:
                        pass  # best-effort
                self._slack.send_message(
                    task.channel_id,
                    (
                        "⚠️ 你的請求在佇列中等待太久（超過 30 分鐘），已自動取消。"
                        " 系統現在比較忙，請稍後再重新發送。"
                    ),
                    thread_ts=task.thread_ts,
                )
            except Exception as exc:
                logger.warning(
                    "queue_watchdog: failed to notify task %s: %s",
                    task.task_id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_message(
        self,
        text: str,
        bot_user_id: str,
        files: list | None = None,
    ) -> ParsedMessage:
        """Parse a Slack message: strip leading @bot mention, detect admin commands.

        Args:
            text: Raw Slack message text (may contain ``<@BOT_USER_ID>``).
            bot_user_id: The bot's Slack user ID (used to identify the mention).
            files: List of Slack file attachment dicts, or None.

        Returns:
            A frozen :class:`ParsedMessage` instance.
        """
        files_tuple = tuple(files) if files else ()

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
                files=files_tuple,
            )

        return ParsedMessage(text=cleaned, files=files_tuple)

    def dispatch(self, task: Task) -> None:
        """Main dispatch entry point — called for each incoming Slack event.

        Parses the message first.  If it is an admin command, handles it
        immediately and returns.  Otherwise submits the task to the queue.
        If the task can start immediately, spawns a daemon worker thread.
        If the queue is full, sends a "queued" acknowledgement back to Slack.

        Args:
            task: The incoming task to process.
        """
        # Layer 2 dedup: prevents duplicate dispatch even if Receiver
        # layer misses due to concurrent handler execution.
        # Applies to ALL dispatches including admin commands.
        with self._dispatched_ts_lock:
            if task.message_ts in self._dispatched_ts:
                logger.debug(
                    "Skipping duplicate dispatch: message_ts=%s",
                    task.message_ts,
                )
                return
            self._dispatched_ts.add(task.message_ts)
            if len(self._dispatched_ts) > 10_000:
                keep = 5_000
                self._dispatched_ts = set(
                    sorted(self._dispatched_ts)[-keep:]
                )

        parsed = self.parse_message(task.text, self._slack.bot_user_id, files=task.files)
        if parsed.is_admin_command:
            self._handle_admin_command(task, parsed.admin_command)
            return

        # Circuit breaker: reject non-admin tasks when Claude CLI is unhealthy.
        if not self._circuit_breaker.allow_request():
            self._slack.send_message(
                task.channel_id,
                ":warning: Service temporarily unavailable. Please try again later.",
                thread_ts=task.thread_ts,
            )
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
            # Task was queued; send acknowledgement and store ts for cleanup.
            ack_result = self._slack.send_message(
                task.channel_id,
                "Your request is queued and will be processed shortly.",
                thread_ts=task.thread_ts,
            )
            ack_ts = ack_result.get("ts", "")
            if ack_ts:
                task.queued_ack_ts = ack_ts

    def _spawn_promoted(self, promoted: list[Task]) -> None:
        """Spawn worker threads for tasks promoted from the pending queue.

        Called after mark_completed/mark_failed to ensure promoted tasks
        actually get processed (fixes the stuck-slot bug where promoted
        tasks occupied a running slot without a worker thread).
        """
        for ptask in promoted:
            thread = threading.Thread(
                target=self._process_task,
                args=(ptask,),
                daemon=True,
                name=f"dispatcher-worker-{ptask.task_id}",
            )
            thread.start()
            logger.info(
                "Spawned worker for promoted task %s (thread_ts=%s)",
                ptask.task_id,
                ptask.thread_ts,
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
        9. Run :class:`~opentree.runner.codex_process.CodexProcess` with
           progress callback.
        10. Send final result via ProgressReporter.complete().
        11. Persist session_id on success.
        12. Mark task completed or failed.
        13. Cleanup temp files in a finally block.

        Args:
            task: The task to execute.
        """
        # Clean up "queued" ack message if task was promoted from pending.
        if task.queued_ack_ts:
            self._slack.delete_message(task.channel_id, task.queued_ack_ts)
            task.queued_ack_ts = ""

        reporter = ProgressReporter(
            slack_api=self._slack,
            channel=task.channel_id,
            thread_ts=task.thread_ts,
            interval=self._runner_config.progress_interval,
        )

        # Tool tracker — records tool invocations for timeline display.
        tracker = ToolTracker()

        def _tracking_callback(state) -> None:
            """Progress callback that also feeds the tool tracker."""
            if state.last_event == "thinking_started":
                tracker.start_thinking()
            elif state.last_event == "thinking_completed":
                tracker.end_thinking()
            elif state.last_event == "tool_started":
                tracker.end_thinking()
                tracker.start_tool(
                    state.tool_name,
                    state.tool_input_preview,
                    category=getattr(state, "tool_category", "other"),
                )
            elif state.last_event == "tool_completed":
                tracker.end_tool()
                tracker.start_thinking()
            elif state.last_event == "response_started":
                tracker.end_tool()
                tracker.end_thinking()
                tracker.start_generating()
                if state.response_text:
                    tracker.track_text(state.response_text)

            reporter.update(
                state,
                timeline=tracker.build_progress_timeline(),
                work_phase=tracker.get_work_phase(),
                decision=tracker.get_latest_decision(),
            )

        try:
            # Step 1: send initial ack via ProgressReporter.
            reporter.start()

            # Step 2: resolve user_name from Slack; sanitize for path safety.
            display_name = self._slack.get_user_display_name(task.user_id) or ""
            resolved_name = display_name
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
            context = self._build_prompt_context(
                task, user_name=resolved_name, display_name=display_name,
            )
            is_owner = context.is_owner

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

            # Step 9: run Claude with retry loop for transient errors.
            retry_config = RetryConfig()
            result: ClaudeResult | None = None

            for attempt in range(retry_config.max_attempts + 1):
                claude = CodexProcess(
                    config=self._runner_config,
                    system_prompt=system_prompt,
                    cwd=self._workspace_dir,
                    session_id=session_id,
                    message=message,
                    progress_callback=_tracking_callback,
                    sandboxed=(self._runner_config.codex_sandbox != "danger-full-access"),
                    is_owner=is_owner,
                )
                result = claude.run()

                # Timeout: allow one automatic retry (heartbeat may have
                # been triggered by a transient slow tool call, not a true
                # infinite hang).  Second timeout → give up.
                if result.is_timeout:
                    if attempt == 0 and retry_config.max_attempts > 0:
                        logger.warning(
                            "Task %s timed out on attempt %d — retrying once (session cleared).",
                            task.task_id,
                            attempt + 1,
                        )
                        session_id = ""  # Clear session to avoid resuming broken state
                        time.sleep(5)
                        continue
                    break

                # Check if error is retryable.
                if result.is_error:
                    do_retry, delay, reason = should_retry(
                        result.error_message or "", attempt, retry_config,
                    )
                    if do_retry:
                        logger.warning(
                            "Retrying task %s: %s (delay=%.0fs)",
                            task.task_id,
                            reason,
                            delay,
                        )
                        # Clear session_id for session errors.
                        if classify_error(result.error_message or "") == "session":
                            session_id = ""
                        if delay > 0:
                            time.sleep(delay)
                        continue

                # Success or non-retryable error — stop loop.
                break

            # Step 10: finalize tool tracker and record circuit breaker result.
            assert result is not None  # loop always executes at least once
            if result.thinking_text:
                tracker.add_thinking_text(result.thinking_text)
            tracker.finish()
            if result.is_error or result.is_timeout:
                self._circuit_breaker.record_failure()
            else:
                self._circuit_breaker.record_success()

            completion_items = tracker.build_completion_summary()

            # Step 11: send final result via ProgressReporter.
            try:
                elapsed = float(result.elapsed_seconds)
            except (TypeError, ValueError):
                elapsed = 0.0
            if result.is_timeout:
                reporter.complete(
                    response_text="",
                    elapsed=elapsed,
                    is_error=True,
                    error_message=(
                        "任務執行超時（已自動重試一次仍失敗）。"
                        " 這通常表示任務過於複雜或網路暫時不穩定。"
                        " 建議把任務拆成較小的步驟再重新嘗試。"
                    ),
                    completion_items=completion_items,
                )
                self._task_queue.mark_failed(task)
                return
            reporter.complete(
                response_text=result.response_text or "",
                elapsed=elapsed,
                is_error=result.is_error,
                error_message=result.error_message or "",
                completion_items=completion_items,
            )

            if result.is_error:
                self._task_queue.mark_failed(task)
                return

            # Step 11: persist session_id.
            if result.session_id:
                self._session_mgr.set_session_id(task.thread_ts, result.session_id)

            # Step 11b: extract and persist memories from the response.
            if result.response_text and self._runner_config.memory_extraction_enabled:
                try:
                    from opentree.runner.memory_extractor import (
                        append_to_memory_file,
                        extract_memories,
                    )

                    memories = extract_memories(
                        task.text,
                        user_name=resolved_name,
                        thread_ts=task.thread_ts,
                    )
                    if memories:
                        memory_path = (
                            self._home / "data" / "memory" / resolved_name / "memory.md"
                        )
                        append_to_memory_file(memory_path, memories, user_name=resolved_name)
                except Exception as exc:
                    logger.warning("Memory extraction failed: %s", exc)

            # Step 12: mark completed and spawn threads for promoted tasks.
            promoted = self._task_queue.mark_completed(task)
            self._spawn_promoted(promoted)

        except Exception:
            logger.exception("Unexpected error while processing task %s", task.task_id)
            promoted = self._task_queue.mark_failed(task)
            self._spawn_promoted(promoted)
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

    @staticmethod
    def _check_new_user(memory_path: str) -> bool:
        """Check if user is new (no memory file or empty/template-only content)."""
        if not memory_path:
            return True
        path = Path(memory_path)
        if not path.exists():
            return True
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return True
            # Template-only: just has section headers like "# xxx 的記憶" or "## Pinned"
            lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
            if not lines:
                return True
        except OSError:
            return True
        return False

    def _extract_thread_participants(
        self, channel_id: str, thread_ts: str,
    ) -> list[str]:
        """Extract unique participant display names from thread history.

        Excludes the bot itself. Returns an empty list if thread_ts is
        empty or the API call fails.
        """
        if not thread_ts:
            return []
        try:
            messages = self._slack.get_thread_replies(
                channel_id, thread_ts, limit=50,
            )
        except Exception:
            logger.debug("Failed to fetch thread replies for participants")
            return []
        seen: set[str] = set()
        names: list[str] = []
        for msg in messages:
            uid = msg.get("user", "")
            if uid and uid != self._slack.bot_user_id and uid not in seen:
                seen.add(uid)
                name = self._slack.get_user_display_name(uid) or uid
                names.append(name)
        return names

    def _build_prompt_context(
        self,
        task: Task,
        user_name: str = "",
        display_name: str = "",
    ) -> PromptContext:
        """Build a per-request :class:`~opentree.core.prompt.PromptContext`.

        Each task gets its own context so that user_id, channel_id, and
        thread_ts are always accurate for the current Slack event.

        Args:
            task: The task for which to build a context.
            user_name: Pre-resolved and sanitized user display name.  Must
                match ``^[a-zA-Z0-9_-]+$`` or be the user_id fallback so it
                is safe to embed in a filesystem path.  Defaults to
                ``task.user_name`` when not provided (test-only path).
            display_name: Original Slack display name (human-readable,
                before filesystem sanitization).

        Returns:
            A frozen :class:`PromptContext` instance.
        """
        name = user_name or task.user_name
        memory_path = str(
            self._home / "data" / "memory" / name / "memory.md"
        )
        # Determine owner status from runner config.
        is_owner = bool(
            self._runner_config.admin_users
            and task.user_id in self._runner_config.admin_users
        )

        # Extract thread participant display names.
        participants = self._extract_thread_participants(
            task.channel_id, task.thread_ts,
        )

        # Workspace: use team_name when available, fall back to "default".
        workspace = self._user_config.team_name or "default"

        # Use cache to avoid repeated file reads for known existing users.
        if memory_path in self._known_existing_users:
            is_new = False
        else:
            is_new = self._check_new_user(memory_path)
            if not is_new:
                self._known_existing_users.add(memory_path)

        # Ensure memory directory exists for first-time users
        if is_new and memory_path:
            try:
                Path(memory_path).parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass  # Best-effort; Claude's Write tool may create it anyway

        return PromptContext(
            user_id=task.user_id,
            user_name=name,
            user_display_name=display_name or name,
            channel_id=task.channel_id,
            thread_ts=task.thread_ts,
            workspace=workspace,
            team_name=self._user_config.team_name,
            memory_path=memory_path,
            is_new_user=is_new,
            is_owner=is_owner,
            is_sandboxed=(self._runner_config.codex_sandbox != "danger-full-access"),
            thread_participants=tuple(participants),
            opentree_home=str(self._home),
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
        elif command in ("shutdown", "restart", "reset-bot", "reset-bot-all"):
            if (
                self._runner_config.admin_users
                and task.user_id not in self._runner_config.admin_users
            ):
                self._slack.send_message(
                    task.channel_id,
                    f":lock: Only authorized admins can use the {command} command.",
                    thread_ts=task.thread_ts,
                )
                return
            if command == "restart":
                self._handle_restart(task)
            elif command == "shutdown":
                self._handle_shutdown(task)
            elif command == "reset-bot":
                self._handle_reset_bot(task)
            elif command == "reset-bot-all":
                self._handle_reset_bot_all(task)
        else:
            logger.warning("Unknown admin command: %s", command)

    def _handle_status(self, task: Task) -> None:
        """Send bot status info to Slack.

        Args:
            task: The task for routing the reply.
        """
        stats = self.get_stats()
        cb_status = self._circuit_breaker.get_status()
        lines = [
            "*Bot Status*",
            f"Running tasks: {stats.get('running', 0)}",
            f"Pending tasks: {stats.get('pending', 0)}",
            f"Completed tasks: {stats.get('completed', 0)}",
            f"Failed tasks: {stats.get('failed', 0)}",
            f"Max concurrent: {stats.get('max_concurrent', 0)}",
            f"Circuit breaker: {cb_status['state']} (failures: {cb_status['failure_count']}/{cb_status['threshold']})",
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
        Exit code stays 0, so the wrapper script will NOT restart.

        Args:
            task: The task for routing the reply.
        """
        self._slack.send_message(
            task.channel_id,
            ":wave: Shutting down gracefully...",
            thread_ts=task.thread_ts,
        )
        self._shutdown.set()

    def _handle_restart(self, task: Task) -> None:
        """Request bot restart.

        Sets exit code to 1 (non-zero causes wrapper to restart) and
        triggers shutdown.

        Args:
            task: The task for routing the reply.
        """
        self._exit_code = 1
        self._slack.send_message(
            task.channel_id,
            ":arrows_counterclockwise: Restarting...",
            thread_ts=task.thread_ts,
        )
        self._shutdown.set()

    def _handle_reset_bot(self, task: Task) -> None:
        """Soft reset: regenerate settings/symlinks/CLAUDE.md, clear sessions.

        Calls :func:`~opentree.runner.reset.reset_bot` and then
        :meth:`SessionManager.clear_all`.  Always triggers a restart
        afterwards (even on failure, since state may be partial).

        Args:
            task: The task for routing the reply.
        """
        self._slack.send_message(
            task.channel_id,
            ":arrows_counterclockwise: Resetting bot configuration...",
            thread_ts=task.thread_ts,
        )

        try:
            actions = reset_bot(self._home)
            self._session_mgr.clear_all()
            actions.append("Cleared sessions")

            summary = "\n".join(f"\u2022 {a}" for a in actions)
            self._slack.send_message(
                task.channel_id,
                f":white_check_mark: Reset complete. Restarting...\n{summary}",
                thread_ts=task.thread_ts,
            )
        except Exception as exc:
            logger.error("Reset failed: %s", exc, exc_info=True)
            self._slack.send_message(
                task.channel_id,
                f":x: Reset failed: {exc}",
                thread_ts=task.thread_ts,
            )

        # Trigger restart
        self._exit_code = 1
        self._shutdown.set()

    def _handle_reset_bot_all(self, task: Task) -> None:
        """Hard reset: clear all data and customizations.

        Clears in-memory sessions first (before ``reset_bot_all`` may
        wipe ``data/``), then calls
        :func:`~opentree.runner.reset.reset_bot_all`.  Always triggers a
        restart afterwards (even on failure, since state may be partial).

        Args:
            task: The task for routing the reply.
        """
        self._slack.send_message(
            task.channel_id,
            ":warning: Performing full reset. All memories, sessions, "
            "and custom configurations will be cleared. "
            "Bot will restart with default settings...",
            thread_ts=task.thread_ts,
        )

        try:
            # Clear in-memory sessions first (before data/ cleanup)
            self._session_mgr.clear_all()

            actions = reset_bot_all(self._home)
            actions.insert(0, "Cleared sessions")

            summary = "\n".join(f"\u2022 {a}" for a in actions)
            self._slack.send_message(
                task.channel_id,
                f":white_check_mark: Full reset complete. Restarting...\n{summary}",
                thread_ts=task.thread_ts,
            )
        except Exception as exc:
            logger.error("Full reset failed: %s", exc, exc_info=True)
            self._slack.send_message(
                task.channel_id,
                f":x: Full reset failed: {exc}",
                thread_ts=task.thread_ts,
            )

        # Always trigger restart (even on failure, state may be partial)
        self._exit_code = 1
        self._shutdown.set()

    # ------------------------------------------------------------------
    # Stats / properties
    # ------------------------------------------------------------------

    @property
    def exit_code(self) -> int:
        """Exit code to propagate to Bot / wrapper.

        0 = clean shutdown (no restart), non-zero = restart requested.
        """
        return self._exit_code

    def get_stats(self) -> dict:
        """Return dispatcher statistics (delegates to TaskQueue).

        Returns:
            A dict with keys: running, pending, completed, failed, max_concurrent.
        """
        return self._task_queue.get_stats()

    def cancel_pending_tasks(self) -> int:
        """Cancel all pending tasks and notify users via Slack.

        Called during graceful shutdown before wait_for_drain().
        For each pending task:
        - Deletes the "queued" ack message (queued_ack_ts) if present
        - Sends a cancellation notice to the task's thread

        Returns:
            Number of tasks that were cancelled.
        """
        pending = self._task_queue.drain_pending()
        if not pending:
            return 0

        for task in pending:
            try:
                # Remove the "queued" ack message to avoid confusion
                if task.queued_ack_ts:
                    try:
                        self._slack.delete_message(task.channel_id, task.queued_ack_ts)
                    except Exception:
                        pass  # best-effort

                # Notify user that task was cancelled
                self._slack.send_message(
                    task.channel_id,
                    "⚠️ Bot 正在重啟，你的請求已取消。重啟完成後請重新發送。",
                    thread_ts=task.thread_ts,
                )
            except Exception as exc:
                logger.warning("Failed to notify pending task %s: %s", task.task_id, exc)

        logger.info("Cancelled %d pending tasks with user notification", len(pending))
        return len(pending)

    @property
    def task_queue(self) -> TaskQueue:
        """Expose the task queue for external use (e.g. graceful shutdown).

        Returns:
            The internal :class:`~opentree.runner.task_queue.TaskQueue` instance.
        """
        return self._task_queue
