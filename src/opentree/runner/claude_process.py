"""Claude CLI subprocess manager for OpenTree bot runner."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from opentree.runner.config import RunnerConfig
from opentree.runner.stream_parser import StreamParser

logger = logging.getLogger(__name__)

# Environment variables safe to pass to Claude CLI.
# Only these are inherited from os.environ; extra_env is merged on top.
_ENV_WHITELIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TERM",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_USE_BEDROCK",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "CLAUDE_CONFIG_DIR",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)

# How long to wait after SIGTERM before escalating to SIGKILL.
_SIGTERM_WAIT_SECONDS = 10


@dataclass(frozen=True)
class ClaudeResult:
    """Immutable result of a Claude CLI execution."""

    session_id: str = ""
    response_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False
    error_message: str = ""
    is_timeout: bool = False
    exit_code: int = 0
    elapsed_seconds: float = 0.0


def _build_safe_env(
    extra_env: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build a sanitised environment for the Claude CLI subprocess.

    Only variables listed in :data:`_ENV_WHITELIST` are inherited from the
    current process environment.  ``extra_env`` values are merged on top
    without any whitelist filtering, giving callers explicit control over
    per-task injections.

    Args:
        extra_env: Additional variables to inject (not whitelist-filtered).

    Returns:
        A fresh dict suitable for passing as the ``env`` kwarg to
        :class:`subprocess.Popen`.
    """
    safe: dict[str, str] = {
        k: v for k, v in os.environ.items() if k in _ENV_WHITELIST
    }
    if extra_env:
        safe.update(extra_env)
    return safe


def _build_claude_args(
    config: RunnerConfig,
    system_prompt: str,
    cwd: str,
    session_id: str = "",
    message: str = "",
) -> list[str]:
    """Build the Claude CLI command-line arguments.

    The returned list always starts with the configured ``claude_command`` and
    includes the flags required for ``stream-json`` output.

    Args:
        config: Runner configuration.
        system_prompt: System prompt to inject via ``--system-prompt``.
        cwd: Working directory; passed to :class:`subprocess.Popen` as ``cwd``,
            not as a CLI flag (``--cwd`` is not a valid Claude CLI option).
        session_id: If non-empty, adds ``--resume <session_id>``.
        message: If non-empty, appended as a positional argument (batch mode).

    Returns:
        A list of strings ready for :class:`subprocess.Popen`.
    """
    args: list[str] = [
        config.claude_command,
        "--output-format",
        "stream-json",
        "--verbose",
        "--system-prompt",
        system_prompt,
    ]

    # Always use dontAsk — bypassPermissions is never used even for owner users
    # because it silently skips all allow/deny rules in settings.json.
    # (GitHub #12232: --allowedTools ignored; #27040: deny rules ignored)
    args += ["--permission-mode", "dontAsk"]

    args.append("--print")

    if session_id:
        args += ["--resume", session_id]

    if message:
        args.append(message)

    return args


class ClaudeProcess:
    """Manages a Claude CLI subprocess with stream-json output.

    Lifecycle:

    1. :meth:`run` spawns the subprocess.
    2. A background reader thread consumes ``stdout`` line-by-line, feeding
       each line to :class:`~opentree.runner.stream_parser.StreamParser`.
    3. A background monitor thread enforces ``task_timeout`` and
       ``heartbeat_timeout``; both kill the subprocess when triggered.
    4. :meth:`run` blocks until the subprocess exits and returns a
       :class:`ClaudeResult`.

    The :meth:`stop` method can be called from another thread to request
    graceful termination (SIGTERM → wait 10 s → SIGKILL).
    """

    def __init__(
        self,
        config: RunnerConfig,
        system_prompt: str,
        cwd: str,
        session_id: str = "",
        message: str = "",
        progress_callback: Optional[Callable] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> None:
        self._config = config
        self._system_prompt = system_prompt
        self._cwd = cwd
        self._session_id = session_id
        self._message = message
        self._progress_callback = progress_callback
        self._extra_env = extra_env

        self._parser = StreamParser()
        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._last_output_time: float = 0.0
        self._timed_out: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> ClaudeResult:
        """Execute Claude CLI and return the result (blocking).

        Spawns the subprocess, starts reader and monitor threads, then waits
        for completion.  Returns a :class:`ClaudeResult` in all cases.
        """
        args = _build_claude_args(
            self._config,
            self._system_prompt,
            self._cwd,
            session_id=self._session_id,
            message=self._message,
        )
        env = _build_safe_env(self._extra_env)

        start_time = time.monotonic()
        self._last_output_time = start_time
        self._timed_out = False

        logger.debug("Spawning Claude CLI: %s", args[0])

        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                cwd=self._cwd,  # Set working directory via Popen, not CLI flag
            )
        except Exception as exc:
            logger.error("Failed to spawn Claude CLI: %s", exc)
            return ClaudeResult(
                is_error=True,
                error_message=str(exc),
                elapsed_seconds=time.monotonic() - start_time,
            )

        # Start background threads.
        reader_thread = threading.Thread(
            target=self._read_output, name="claude-reader", daemon=True
        )
        monitor_thread = threading.Thread(
            target=self._monitor_timeout, name="claude-monitor", daemon=True
        )
        reader_thread.start()
        monitor_thread.start()

        # Block until reader is done (process stdout closed).
        reader_thread.join()

        # Signal monitor to stop and let it exit.
        self._stop_event.set()
        monitor_thread.join(timeout=2)

        # Collect exit code.
        exit_code = self._process.wait()
        elapsed = time.monotonic() - start_time

        if exit_code != 0 and self._process.stderr is not None:
            stderr_output = self._process.stderr.read()
            if stderr_output:
                logger.warning("Claude stderr: %s", stderr_output.strip())

        pid = self._process.pid if self._process is not None else None
        if not self._parser.state.has_result_event:
            logger.warning(
                "No result event received from Claude CLI stream "
                "(pid=%s, exit_code=%s, timed_out=%s)",
                pid, exit_code, self._timed_out,
            )
        elif self._parser.state.input_tokens == 0 and self._parser.state.output_tokens == 0:
            logger.warning(
                "Result event received but token counts are both zero "
                "(pid=%s, exit_code=%s)",
                pid, exit_code,
            )

        result_dict = self._parser.get_result()

        return ClaudeResult(
            session_id=result_dict["session_id"],
            response_text=result_dict["response_text"],
            input_tokens=result_dict["input_tokens"],
            output_tokens=result_dict["output_tokens"],
            is_error=result_dict["is_error"],
            error_message=result_dict["error_message"],
            is_timeout=self._timed_out,
            exit_code=exit_code,
            elapsed_seconds=elapsed,
        )

    def stop(self) -> None:
        """Request graceful stop.

        Sends SIGTERM to the subprocess, waits up to 10 seconds, then sends
        SIGKILL if the process has not yet exited.  Safe to call even if the
        process has already finished.
        """
        self._stop_event.set()
        self._terminate_process()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_output(self) -> None:
        """Read stdout line-by-line and feed each line to the parser."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        for raw_line in proc.stdout:
            self._last_output_time = time.monotonic()
            new_phase = self._parser.parse_line(raw_line)
            if new_phase is not None and self._progress_callback is not None:
                try:
                    self._progress_callback(self._parser.state)
                except Exception as exc:  # pragma: no cover
                    logger.warning("progress_callback raised: %s", exc)

    def _monitor_timeout(self) -> None:
        """Background thread: enforce task_timeout and heartbeat_timeout."""
        poll_interval = 0.5  # seconds between checks
        task_start = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            elapsed_total = now - task_start
            elapsed_since_output = now - self._last_output_time

            # Check task timeout.
            if elapsed_total >= self._config.task_timeout:
                logger.warning(
                    "Task timeout reached (%ss) — terminating Claude.",
                    self._config.task_timeout,
                )
                self._timed_out = True
                self._terminate_process()
                return

            # Check heartbeat timeout.
            if elapsed_since_output >= self._config.heartbeat_timeout:
                logger.warning(
                    "Heartbeat timeout reached (%ss without output) — terminating Claude.",
                    self._config.heartbeat_timeout,
                )
                self._timed_out = True
                self._terminate_process()
                return

            self._stop_event.wait(timeout=poll_interval)

    def _terminate_process(self) -> None:
        """Send SIGTERM; escalate to SIGKILL if process does not exit in 10 s."""
        proc = self._process
        if proc is None:
            return

        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            return  # Process already gone.

        try:
            proc.wait(timeout=_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not exit after SIGTERM — sending SIGKILL.")
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass  # Process disappeared between the timeout and the kill.
