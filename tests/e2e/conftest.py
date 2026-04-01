"""Shared fixtures for OpenTree Bot Runner E2E tests.

These fixtures orchestrate real Slack interactions via DOGI's message-tool
and slack-query-tool CLIs, then observe Bot_Walter's responses.

Prerequisites:
  - Bot_Walter must be running (via run.sh)
  - DOGI slack-bot must be accessible for message-tool / slack-query-tool
  - Slack channel (E2E_CHANNEL_ID env var, default ai-room) must be accessible to both bots
"""

from __future__ import annotations

import json
import os
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
CHANNEL_ID = os.environ.get("E2E_CHANNEL_ID", "C0APZHG71B8")  # default: ai-room (cc workspace)
BOT_USER_ID = "U0APZ9MR997"
BOT_MENTION = f"<@{BOT_USER_ID}>"

SUBPROCESS_TIMEOUT = 30  # seconds for CLI calls


# ---------------------------------------------------------------------------
# Helpers (not fixtures — used by fixtures)
# ---------------------------------------------------------------------------

def _extract_json(output: str) -> dict[str, Any]:
    """Extract JSON object from CLI output that may contain log lines.

    DOGI CLI tools (message-tool, slack-query-tool) may print log lines
    to stdout before the JSON result.  This helper finds the first ``{``
    and parses only the JSON portion.
    """
    # Try the whole string first (fast path)
    stripped = output.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    # Find the first '{' and parse from there
    idx = output.find("{")
    if idx >= 0:
        return json.loads(output[idx:])

    raise json.JSONDecodeError(
        f"No JSON object found in output: {output[:200]!r}", output, 0,
    )


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
    return _extract_json(result.stdout)


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
    return _extract_json(result.stdout)


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
def read_thread_raw() -> Callable[..., dict[str, Any]]:
    """Read thread with full Slack API response (including blocks).

    Unlike read_thread (which uses slack-query-tool that strips blocks),
    this fixture calls conversations.replies directly via slack_sdk.
    """
    from slack_sdk import WebClient
    from dotenv import dotenv_values

    # Load token without mutating os.environ
    token = None
    env_path = DOGI_DIR / ".env"
    if env_path.exists():
        values = dotenv_values(env_path)
        token = values.get("SLACK_BOT_TOKEN")

    if not token:
        for profile_env in sorted(DOGI_DIR.glob(".env.*")):
            values = dotenv_values(profile_env)
            token = values.get("SLACK_BOT_TOKEN")
            if token:
                break

    if not token:
        pytest.skip("SLACK_BOT_TOKEN not available for raw thread reading")

    client = WebClient(token=token)

    def _read(thread_ts: str, limit: int = 50) -> dict[str, Any]:
        response = client.conversations_replies(
            channel=CHANNEL_ID, ts=thread_ts, limit=limit,
        )
        return {"success": True, "messages": response.get("messages", [])}
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
                    # Bot_Walter's replies have its user ID
                    if msg.get("user") == BOT_USER_ID:
                        text = msg.get("text", "")
                        if ":hourglass_flowing_sand:" not in text:
                            return text
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Bot_Walter did not reply in thread {thread_ts} "
            f"within {timeout}s"
        )
    return _wait


@pytest.fixture()
def wait_for_nth_bot_reply() -> Callable[..., str]:
    """Poll a thread until Bot_Walter's Nth reply appears.

    Args:
        thread_ts: The thread to monitor.
        n: Which bot reply to wait for (1-indexed).
        timeout: Max seconds to wait (default 180).
        poll_interval: Seconds between polls (default 5).

    Returns:
        The text of Bot_Walter's Nth reply message.
    """
    def _wait(
        thread_ts: str,
        n: int = 1,
        timeout: int = 180,
        poll_interval: int = 5,
    ) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = _run_query_tool(
                "read-thread",
                channel=CHANNEL_ID,
                thread_ts=thread_ts,
                limit="100",
            )
            if data.get("success"):
                bot_replies = [
                    m.get("text", "")
                    for m in data.get("messages", [])
                    if m.get("user") == BOT_USER_ID
                ]
                if len(bot_replies) >= n:
                    reply_text = bot_replies[n - 1]
                    # Guard: skip if still an ack spinner
                    if ":hourglass_flowing_sand:" not in reply_text:
                        return reply_text
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Bot_Walter's reply #{n} not found in thread {thread_ts} within {timeout}s"
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
                if ts_match and ts_match.group(1).replace("T", " ") < after_ts.replace("T", " "):
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
