"""Lifecycle commands for OpenTree (stop, etc.).

``opentree stop`` gracefully terminates a running OpenTree instance
by sending SIGTERM to the wrapper process and waiting for exit.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Annotated, Optional

import typer

from opentree.cli.init import _resolve_home


def _read_pid_file(path: Path) -> int | None:
    """Read a PID from a file, returning None if missing or invalid."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return int(text)
    except (OSError, ValueError):
        pass
    return None


def _process_alive(pid: int) -> bool:
    """Return True if process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it
        return True
    except OSError:
        return False


def _validate_process_identity(pid: int, expected_keywords: tuple[str, ...]) -> bool:
    """Verify that *pid* belongs to an OpenTree process via /proc/cmdline.

    Falls back to True (skip validation) on platforms without /proc.
    """
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if not cmdline_path.exists():
        # /proc not available (macOS, some containers) -- skip validation
        return True
    try:
        cmdline = cmdline_path.read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace"
        )
        return any(kw in cmdline for kw in expected_keywords)
    except OSError:
        # Permission denied or race (process exited between check and read)
        return True


def _cleanup_stale_files(data_dir: Path) -> None:
    """Remove stale PID/heartbeat/flag files."""
    for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
        path = data_dir / name
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _wait_for_exit(pid: int, timeout: int) -> bool:
    """Poll until *pid* exits or *timeout* seconds elapse.

    Returns True if process exited, False if still alive after timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(1)
    return not _process_alive(pid)


def stop_command(
    home: Annotated[
        Optional[str],
        typer.Option("--home", help="Path to OPENTREE_HOME"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Send SIGKILL after timeout"),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds to wait for graceful exit"),
    ] = 60,
) -> None:
    """Stop a running OpenTree instance.

    Reads the wrapper PID from data/wrapper.pid, writes a stop flag
    to prevent wrapper restart, then sends SIGTERM and waits for exit.

    With --force, sends SIGKILL if the process does not exit within
    the timeout period.
    """
    opentree_home = _resolve_home(home)
    data_dir = opentree_home / "data"

    # Guard: data/ must exist (instance must be initialized)
    if not data_dir.is_dir():
        typer.echo(
            f"Error: Data directory not found at {data_dir}. "
            "Is this an initialized OpenTree instance?",
            err=True,
        )
        raise typer.Exit(code=1)

    wrapper_pid_file = data_dir / "wrapper.pid"
    bot_pid_file = data_dir / "bot.pid"
    stop_flag = data_dir / ".stop_requested"

    # Step 1: Determine target PID
    target_pid: int | None = None
    target_source: str = ""
    is_wrapper = False

    wrapper_pid = _read_pid_file(wrapper_pid_file)
    if wrapper_pid is not None and _process_alive(wrapper_pid):
        # Validate it's actually an OpenTree wrapper (run.sh)
        if _validate_process_identity(wrapper_pid, ("run.sh", "opentree")):
            target_pid = wrapper_pid
            target_source = "wrapper"
            is_wrapper = True
        else:
            typer.echo(
                f"Warning: wrapper.pid contains PID {wrapper_pid}, "
                "but it does not appear to be an OpenTree process. "
                "PID file may be stale.",
                err=True,
            )

    if target_pid is None:
        # Fallback: try bot.pid
        bot_pid = _read_pid_file(bot_pid_file)
        if bot_pid is not None and _process_alive(bot_pid):
            if _validate_process_identity(bot_pid, ("opentree", "python")):
                target_pid = bot_pid
                target_source = "bot"
                typer.echo(
                    "Warning: wrapper.pid not found or stale. "
                    "Sending signal to bot process directly. "
                    "The wrapper (if running) may restart the bot.",
                    err=True,
                )
            else:
                typer.echo(
                    f"Warning: bot.pid contains PID {bot_pid}, "
                    "but it does not appear to be an OpenTree process.",
                    err=True,
                )

    if target_pid is None:
        # No live process found -- check for stale PID files
        has_stale = wrapper_pid_file.exists() or bot_pid_file.exists()
        if has_stale:
            typer.echo(
                "No running OpenTree process found (PID files are stale). "
                "Cleaning up.",
                err=True,
            )
            _cleanup_stale_files(data_dir)
        else:
            typer.echo("No running OpenTree process found.", err=True)
        raise typer.Exit(code=1)

    # Step 2: Write stop flag (prevent wrapper from restarting bot)
    if is_wrapper:
        try:
            stop_flag.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as exc:
            typer.echo(
                f"Warning: Could not write stop flag: {exc}. "
                "Wrapper may restart the bot after SIGTERM.",
                err=True,
            )

    # Step 3: Send SIGTERM
    typer.echo(
        f"Sending SIGTERM to {target_source} process (PID {target_pid})..."
    )
    try:
        os.kill(target_pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.echo(f"Process {target_pid} already exited.")
        _cleanup_stale_files(data_dir)
        return
    except PermissionError:
        typer.echo(
            f"Error: Permission denied sending signal to PID {target_pid}. "
            "Try running with sudo.",
            err=True,
        )
        # Clean up stop flag since we failed
        try:
            if stop_flag.exists():
                stop_flag.unlink()
        except OSError:
            pass
        raise typer.Exit(code=1)

    # Step 4: Wait for exit
    typer.echo(f"Waiting for exit (timeout: {timeout}s)...")
    exited = _wait_for_exit(target_pid, timeout)

    if exited:
        typer.echo(f"OpenTree {target_source} stopped successfully.")
        _cleanup_stale_files(data_dir)
        return

    # Step 5: Timeout handling
    if not force:
        typer.echo(
            f"Error: Process {target_pid} did not exit within {timeout}s. "
            "Use --force to send SIGKILL.",
            err=True,
        )
        raise typer.Exit(code=1)

    # --force: SIGKILL
    typer.echo(
        f"Timeout exceeded. Sending SIGKILL to PID {target_pid}..."
    )
    try:
        os.kill(target_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Exited between check and kill
    except PermissionError:
        typer.echo(
            f"Error: Permission denied sending SIGKILL to PID {target_pid}.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Brief wait for SIGKILL to take effect
    time.sleep(2)
    if _process_alive(target_pid):
        typer.echo(
            f"Error: Process {target_pid} still alive after SIGKILL. "
            "Manual intervention required.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"OpenTree {target_source} force-killed.")
    _cleanup_stale_files(data_dir)
