"""Bot runner configuration for an OpenTree instance.

Loads configuration from ``config/runner.json`` under the OpenTree home
directory. Falls back to sensible defaults when the file is missing, empty,
or contains malformed JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunnerConfig:
    """Frozen configuration for the OpenTree bot runner.

    All fields are immutable (frozen dataclass). Values are validated by
    :func:`load_runner_config` before construction.

    Attributes:
        progress_interval: Seconds between Slack progress updates.
        claude_command: Name or path of the Claude CLI binary.
        task_timeout: Maximum execution time per task, in seconds.
        heartbeat_timeout: Stream idle timeout, in seconds.
        max_concurrent_tasks: Maximum number of parallel tasks.
        session_expiry_days: Number of days before a session expires.
        drain_timeout: Graceful shutdown drain timeout, in seconds.
    """

    progress_interval: int = 10
    claude_command: str = "claude"
    task_timeout: int = 1800
    heartbeat_timeout: int = 900
    max_concurrent_tasks: int = 2
    session_expiry_days: int = 180
    drain_timeout: int = 30


def _validate(data: dict) -> None:
    """Raise ValueError for any invalid field values.

    Args:
        data: Parsed JSON dict (may be partial).

    Raises:
        ValueError: If any validated field has an invalid value.
    """
    positive_int_fields = (
        "task_timeout",
        "heartbeat_timeout",
        "drain_timeout",
        "progress_interval",
        "session_expiry_days",
    )
    for field in positive_int_fields:
        if field in data and data[field] <= 0:
            raise ValueError(
                f"RunnerConfig: '{field}' must be > 0, got {data[field]}"
            )

    if "max_concurrent_tasks" in data and data["max_concurrent_tasks"] < 1:
        raise ValueError(
            f"RunnerConfig: 'max_concurrent_tasks' must be >= 1, "
            f"got {data['max_concurrent_tasks']}"
        )


def load_runner_config(opentree_home: Path) -> RunnerConfig:
    """Load runner config from ``config/runner.json``.

    Returns defaults if the file is missing, empty, or contains malformed
    JSON. Raises :exc:`ValueError` if the file contains structurally valid
    JSON but has invalid field values.

    Args:
        opentree_home: Root directory of the OpenTree installation.

    Returns:
        A frozen :class:`RunnerConfig` instance.

    Raises:
        ValueError: If a field value fails validation (e.g. non-positive
            timeout, or ``max_concurrent_tasks < 1``).
    """
    config_path = opentree_home / "config" / "runner.json"

    if not config_path.exists():
        return RunnerConfig()

    raw = config_path.read_text(encoding="utf-8").strip()
    if not raw:
        return RunnerConfig()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return RunnerConfig()

    _validate(data)

    return RunnerConfig(
        progress_interval=data.get("progress_interval", 10),
        claude_command=data.get("claude_command", "claude"),
        task_timeout=data.get("task_timeout", 1800),
        heartbeat_timeout=data.get("heartbeat_timeout", 900),
        max_concurrent_tasks=data.get("max_concurrent_tasks", 2),
        session_expiry_days=data.get("session_expiry_days", 180),
        drain_timeout=data.get("drain_timeout", 30),
    )
