"""Codex CLI subprocess manager for OpenTree bot runner."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from opentree.runner.claude_process import ClaudeResult
from opentree.runner.codex_stream_parser import StreamParser
from opentree.runner.config import RunnerConfig
from opentree.runner.sandbox_launcher import build_bwrap_args

logger = logging.getLogger(__name__)

# Environment variables safe to pass to Codex CLI.
# Only these are inherited from os.environ; extra_env is merged on top.
_ENV_WHITELIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TERM",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "SANDBOX_WORKSPACE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)

_AUTO_BEGIN = "<!-- OPENTREE:AUTO:BEGIN -->"
_AUTO_END = "<!-- OPENTREE:AUTO:END -->"
_OWNER_HINT = (
    "\n<!-- 以下為 Owner 自訂區塊，module 安裝/更新/refresh 不會覆蓋 -->\n"
)

# How long to wait after SIGTERM before escalating to SIGKILL.
_SIGTERM_WAIT_SECONDS = 10


def _build_safe_env(
    extra_env: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build a sanitised environment for the Codex CLI subprocess."""
    safe: dict[str, str] = {
        k: v for k, v in os.environ.items() if k in _ENV_WHITELIST
    }
    if extra_env:
        safe.update(extra_env)
    return safe


def _build_codex_args(
    config: RunnerConfig,
    system_prompt: str,
    cwd: str,
    session_id: str = "",
    message: str = "",
    sandboxed: bool = False,
) -> list[str]:
    """Build the Codex CLI command-line arguments.

    When running inside a bwrap sandbox (sandboxed=True) Codex must NOT
    try to create its own nested bwrap sandbox.  We therefore use
    ``--dangerously-bypass-approvals-and-sandbox`` instead of ``--full-auto``,
    and add ``--skip-git-repo-check`` so that the /workspace trust entry in
    config.toml is not required (the outer bwrap already enforces isolation).

    When running without an outer sandbox (sandboxed=False) we keep
    ``--full-auto`` so Codex uses its workspace-write sandbox for basic
    isolation, unless ``config.codex_sandbox == "danger-full-access"`` in
    which case we bypass all sandboxing for full filesystem access.
    """
    del system_prompt  # Written to AGENTS.md before the subprocess starts.

    if sandboxed or config.codex_sandbox == "danger-full-access":
        # Two cases share the same flags:
        # 1. sandboxed=True: outer bwrap handles isolation; skip Codex's inner sandbox.
        # 2. danger-full-access: intentionally no sandbox at all — full host access.
        exec_flag = "--dangerously-bypass-approvals-and-sandbox"
        extra_flags = ["--skip-git-repo-check"]
    else:
        exec_flag = "--full-auto"
        extra_flags = []

    if session_id:
        # codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]
        # --session-id flag was removed; SESSION_ID and PROMPT are positional.
        # -C/--cd is not available in the resume subcommand; cwd is handled by
        # bwrap --chdir /workspace (sandboxed) or the Popen cwd= argument.
        return [
            config.codex_command,
            "exec",
            "resume",
            "--json",
            exec_flag,
            *extra_flags,
            session_id,  # positional SESSION_ID
            message,     # positional PROMPT
        ]

    return [
        config.codex_command,
        "exec",
        "--json",
        exec_flag,
        *extra_flags,
        "-C",
        cwd,
        message,
    ]


def _wrap_with_markers(content: str) -> str:
    """Wrap generated AGENTS.md content with OpenTree auto markers."""
    return f"{_AUTO_BEGIN}\n{content}\n{_AUTO_END}\n{_OWNER_HINT}"


def _merge_with_preservation(existing_content: str | None, auto_content: str) -> str:
    """Preserve owner content outside the OpenTree auto block."""
    wrapped = _wrap_with_markers(auto_content)

    if existing_content is None:
        return wrapped

    begin_idx = existing_content.find(_AUTO_BEGIN)
    end_idx = existing_content.find(_AUTO_END, begin_idx) if begin_idx != -1 else -1

    if begin_idx == -1 or end_idx == -1:
        logger.warning(
            "AGENTS.md has no AUTO markers, treating entire content as owner content"
        )
        return wrapped + "\n" + existing_content

    owner_content = existing_content[end_idx + len(_AUTO_END) :]
    owner_content = owner_content.replace(_OWNER_HINT, "")

    if owner_content.strip():
        return wrapped + "\n" + owner_content
    return wrapped


def _write_agents_md(system_prompt: str, cwd: str) -> None:
    """Atomically write ``cwd/AGENTS.md`` preserving owner content."""
    agents_path = Path(cwd) / "AGENTS.md"

    try:
        existing_content = agents_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing_content = None

    content = _merge_with_preservation(existing_content, system_prompt)

    agents_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=agents_path.parent,
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name

    os.replace(tmp_path, agents_path)


class CodexProcess:
    """Manages a Codex CLI subprocess with JSONL output."""

    def __init__(
        self,
        config: RunnerConfig,
        system_prompt: str,
        cwd: str,
        session_id: str = "",
        message: str = "",
        progress_callback: Optional[Callable] = None,
        extra_env: Optional[dict[str, str]] = None,
        sandboxed: bool = False,
        is_owner: bool = False,
    ) -> None:
        self._config = config
        self._system_prompt = system_prompt
        self._cwd = cwd
        self._session_id = session_id
        self._message = message
        self._progress_callback = progress_callback
        self._extra_env = extra_env
        self._sandboxed = sandboxed
        self._is_owner = is_owner

        self._parser = StreamParser()
        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._last_output_time: float = 0.0
        self._timed_out: bool = False

    def run(self) -> ClaudeResult:
        """Execute Codex CLI and return the result (blocking)."""
        start_time = time.monotonic()
        self._last_output_time = start_time
        self._timed_out = False

        try:
            _write_agents_md(self._system_prompt, self._cwd)
        except Exception as exc:
            logger.error("Failed to write AGENTS.md: %s", exc)
            return ClaudeResult(
                is_error=True,
                error_message=str(exc),
                elapsed_seconds=time.monotonic() - start_time,
            )

        if self._sandboxed:
            Path(self._cwd, ".codex").mkdir(exist_ok=True)

        cli_cwd = "/workspace" if self._sandboxed else self._cwd
        args = _build_codex_args(
            self._config,
            self._system_prompt,
            cli_cwd,
            session_id=self._session_id,
            message=self._message,
            sandboxed=self._sandboxed,
        )
        if self._sandboxed:
            memory_dir = str(Path(self._cwd).parent / "data" / "memory")
            args = build_bwrap_args(
                args,
                self._cwd,
                os.environ.get("HOME", str(Path.home())),
                owner=self._is_owner,
                memory_dir=memory_dir,
            )
        env = _build_safe_env(self._extra_env)

        logger.debug("Spawning Codex CLI: %s", args[0])

        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,  # prevent Codex from reading stdin / entering interactive mode
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                cwd=self._cwd,
            )
        except Exception as exc:
            logger.error("Failed to spawn Codex CLI: %s", exc)
            return ClaudeResult(
                is_error=True,
                error_message=str(exc),
                elapsed_seconds=time.monotonic() - start_time,
            )

        reader_thread = threading.Thread(
            target=self._read_output, name="codex-reader", daemon=True
        )
        monitor_thread = threading.Thread(
            target=self._monitor_timeout, name="codex-monitor", daemon=True
        )
        reader_thread.start()
        monitor_thread.start()

        reader_thread.join()

        self._stop_event.set()
        monitor_thread.join(timeout=2)

        exit_code = self._process.wait()
        elapsed = time.monotonic() - start_time

        if exit_code != 0 and self._process.stderr is not None:
            stderr_output = self._process.stderr.read()
            if stderr_output:
                logger.warning("Codex stderr: %s", stderr_output.strip())

        pid = self._process.pid if self._process is not None else None
        if not self._parser.state.has_result_event:
            logger.warning(
                "No result event received from Codex CLI stream "
                "(pid=%s, exit_code=%s, timed_out=%s)",
                pid,
                exit_code,
                self._timed_out,
            )
            # Treat missing result event as error — Codex exited without
            # completing the turn, so there is no response to deliver.
            if not self._parser.state.is_error:
                self._parser.state.is_error = True
                if not self._parser.state.error_message:
                    self._parser.state.error_message = (
                        f"Codex CLI exited without completing the turn "
                        f"(exit_code={exit_code}, pid={pid})."
                    )
        elif (
            self._parser.state.input_tokens == 0
            and self._parser.state.output_tokens == 0
        ):
            logger.warning(
                "Result event received but token counts are both zero "
                "(pid=%s, exit_code=%s)",
                pid,
                exit_code,
            )

        # Treat non-zero exit code as error even if parser didn't flag it.
        if exit_code != 0 and not self._parser.state.is_error:
            logger.warning(
                "Codex CLI exited with non-zero code %d but parser "
                "did not flag error (pid=%s, has_result=%s, response_len=%d)",
                exit_code,
                pid,
                self._parser.state.has_result_event,
                len(self._parser.state.response_text),
            )
            self._parser.state.is_error = True
            if not self._parser.state.error_message:
                self._parser.state.error_message = (
                    f"Codex CLI exited with code {exit_code}."
                )

        logger.info(
            "Codex CLI finished | pid=%s exit_code=%s elapsed=%.1fs "
            "has_result_event=%s response_len=%d is_error=%s "
            "session_id=%s input_tokens=%d output_tokens=%d timed_out=%s",
            pid,
            exit_code,
            elapsed,
            self._parser.state.has_result_event,
            len(self._parser.state.response_text),
            self._parser.state.is_error,
            self._parser.state.session_id or "(none)",
            self._parser.state.input_tokens,
            self._parser.state.output_tokens,
            self._timed_out,
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
        """Request graceful stop."""
        self._stop_event.set()
        self._terminate_process()

    def _read_output(self) -> None:
        """Read stdout line-by-line and feed each line to the parser."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        for raw_line in proc.stdout:
            self._last_output_time = time.monotonic()
            prev_seq = self._parser.state.event_seq
            self._parser.parse_line(raw_line)
            if (
                self._parser.state.event_seq != prev_seq
                and self._progress_callback is not None
            ):
                try:
                    self._progress_callback(self._parser.state)
                except Exception as exc:  # pragma: no cover
                    logger.warning("progress_callback raised: %s", exc)

    def _monitor_timeout(self) -> None:
        """Background thread: enforce task_timeout and heartbeat_timeout."""
        poll_interval = 0.5
        task_start = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            elapsed_total = now - task_start
            elapsed_since_output = now - self._last_output_time

            if elapsed_total >= self._config.task_timeout:
                logger.warning(
                    "Task timeout reached (%ss) — terminating Codex.",
                    self._config.task_timeout,
                )
                self._timed_out = True
                self._terminate_process()
                return

            if elapsed_since_output >= self._config.heartbeat_timeout:
                logger.warning(
                    "Heartbeat timeout reached (%ss without output) — terminating Codex.",
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
            return

        try:
            proc.wait(timeout=_SIGTERM_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not exit after SIGTERM — sending SIGKILL.")
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
