"""Shared fixtures for OpenTree Bot Runner E2E tests.

These fixtures orchestrate real Slack interactions via DOGI's message-tool
and slack-query-tool CLIs, then observe Bot_Walter's responses.

Prerequisites:
  - Bot_Walter must be running (via run.sh)
  - DOGI slack-bot must be accessible for message-tool / slack-query-tool
  - Slack channel C0AK78CNYBU must be accessible to both bots
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_WALTER_HOME = Path("/mnt/e/develop/mydev/project/trees/bot_walter")
BOT_LOG_DIR = BOT_WALTER_HOME / "data" / "logs"
BOT_HEARTBEAT_FILE = BOT_WALTER_HOME / "data" / "bot.heartbeat"
BOT_PID_FILE = BOT_WALTER_HOME / "data" / "bot.pid"

DOGI_DIR = Path("/mnt/e/develop/mydev/slack-bot")
CHANNEL_ID = "C0AK78CNYBU"
BOT_USER_ID = "U0APZ9MR997"
BOT_MENTION = f"<@{BOT_USER_ID}>"

SUBPROCESS_TIMEOUT = 30  # seconds for CLI calls


# ---------------------------------------------------------------------------
# Helpers (not fixtures — used by fixtures)
# ---------------------------------------------------------------------------

def _run_message_tool(
    text: str,
    channel: str,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Call DOGI message-tool and return parsed JSON output."""
    cmd = [
        "uv", "run", "--directory", str(DOGI_DIR),
        "python", "-m", "scripts.tools.message_tool", "send",
        "--channel", channel,
        "--text", text,
    ]
    if thread_ts is not None:
        cmd.extend(["--thread-ts", thread_ts])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"message-tool failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


def _run_query_tool(subcommand: str, **kwargs: str) -> dict[str, Any]:
    """Call DOGI slack-query-tool and return parsed JSON output."""
    cmd = [
        "uv", "run", "--directory", str(DOGI_DIR),
        "python", "-m", "scripts.tools.slack_query_tool",
        subcommand,
    ]
    for key, value in kwargs.items():
        cmd.extend([f"--{key.replace('_', '-')}", str(value)])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"slack-query-tool {subcommand} failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Pytest markers registration
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for E2E tests."""
    config.addinivalue_line("markers", "e2e: end-to-end tests against live bot")
    config.addinivalue_line("markers", "slow: tests that take >60 seconds")
    config.addinivalue_line("markers", "destructive: tests that kill/restart the bot")


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bot_home() -> Path:
    """Path to the bot_walter deployment root."""
    return BOT_WALTER_HOME


@pytest.fixture()
def bot_log_path() -> Path:
    """Path to today's log file."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return BOT_LOG_DIR / f"{today}.log"


@pytest.fixture()
def channel_id() -> str:
    """The betaroom Slack channel ID."""
    return CHANNEL_ID


@pytest.fixture()
def bot_user_id() -> str:
    """Bot_Walter's Slack user ID."""
    return BOT_USER_ID


@pytest.fixture()
def bot_mention() -> str:
    """Bot_Walter's Slack mention string."""
    return BOT_MENTION


@pytest.fixture()
def dogi_dir() -> Path:
    """Path to DOGI slack-bot project directory."""
    return DOGI_DIR


# ---------------------------------------------------------------------------
# Action fixtures (callables)
# ---------------------------------------------------------------------------

@pytest.fixture()
def send_message() -> Callable[..., dict[str, Any]]:
    """Send a Slack message via DOGI message-tool.

    Usage:
        result = send_message("hello")           # new thread in betaroom
        result = send_message("reply", ts)        # reply in existing thread

    Returns:
        Parsed JSON with at least ``message_ts`` on success.
    """
    def _send(text: str, thread_ts: str | None = None) -> dict[str, Any]:
        return _run_message_tool(text, channel=CHANNEL_ID, thread_ts=thread_ts)
    return _send


@pytest.fixture()
def read_thread() -> Callable[..., dict[str, Any]]:
    """Read a Slack thread via DOGI slack-query-tool.

    Usage:
        data = read_thread("1234567890.123456", limit=50)

    Returns:
        Parsed JSON containing thread messages.
    """
    def _read(thread_ts: str, limit: int = 50) -> dict[str, Any]:
        return _run_query_tool(
            "read-thread",
            channel=CHANNEL_ID,
            thread_ts=thread_ts,
            limit=str(limit),
        )
    return _read


@pytest.fixture()
def wait_for_bot_reply() -> Callable[..., str]:
    """Poll a thread until Bot_Walter posts a reply.

    Args:
        thread_ts: The thread to monitor.
        timeout: Max seconds to wait (default 120).
        poll_interval: Seconds between polls (default 5).

    Returns:
        The text of Bot_Walter's reply message.

    Raises:
        TimeoutError: If no reply arrives within the timeout.
    """
    def _wait(
        thread_ts: str,
        timeout: int = 120,
        poll_interval: int = 5,
    ) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = _run_query_tool(
                "read-thread",
                channel=CHANNEL_ID,
                thread_ts=thread_ts,
                limit="50",
            )
            if data.get("success"):
                messages = data.get("messages", [])
                for msg in messages:
                    # Bot_Walter's replies have its user ID or bot_id
                    if msg.get("user") == BOT_USER_ID:
                        return msg.get("text", "")
                    # Also check bot_profile for bot posts
                    bot_profile = msg.get("bot_profile", {})
                    if bot_profile and BOT_USER_ID in str(msg):
                        return msg.get("text", "")
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Bot_Walter did not reply in thread {thread_ts} "
            f"within {timeout}s"
        )
    return _wait


@pytest.fixture()
def grep_log() -> Callable[..., list[str]]:
    """Search today's bot log for lines matching a pattern.

    Args:
        pattern: Regex pattern to search for.
        after_ts: Only return lines after this ISO timestamp (optional).

    Returns:
        List of matching log lines.
    """
    def _grep(pattern: str, after_ts: str | None = None) -> list[str]:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_path = BOT_LOG_DIR / f"{today}.log"
        if not log_path.exists():
            return []

        compiled = re.compile(pattern)
        matches: list[str] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if after_ts is not None:
                # Attempt to extract timestamp from log line (ISO format prefix)
                ts_match = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
                if ts_match and ts_match.group(1) < after_ts:
                    continue
            if compiled.search(line):
                matches.append(line)
        return matches
    return _grep


@pytest.fixture()
def check_heartbeat() -> Callable[[], tuple[bool, float]]:
    """Check Bot_Walter's heartbeat file freshness.

    Returns:
        (is_fresh, age_seconds) — is_fresh is True if age < 120s.
    """
    def _check() -> tuple[bool, float]:
        if not BOT_HEARTBEAT_FILE.exists():
            return (False, float("inf"))
        mtime = BOT_HEARTBEAT_FILE.stat().st_mtime
        age = time.time() - mtime
        return (age < 120.0, age)
    return _check


@pytest.fixture()
def check_bot_alive() -> Callable[[], bool]:
    """Check if the bot process is running via pgrep.

    Returns:
        True if at least one matching process is found.
    """
    def _check() -> bool:
        result = subprocess.run(
            ["pgrep", "-f", "opentree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    return _check
