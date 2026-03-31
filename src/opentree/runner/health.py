"""Lightweight disk health monitoring for the OpenTree bot runner.

Provides :func:`check_disk_usage` which returns a snapshot of disk
and data-directory usage suitable for periodic logging and the admin
``status`` command.
"""

from __future__ import annotations

import shutil
from pathlib import Path

_BYTES_PER_MB = 1024 * 1024


def _dir_size_bytes(path: Path) -> int:
    """Recursively sum file sizes under *path*.

    Returns 0 if *path* does not exist or is not a directory.
    Silently skips files that cannot be stat'd (e.g. broken symlinks).
    """
    if not path.is_dir():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def check_disk_usage(
    data_dir: Path,
    warn_threshold_mb: int = 500,
) -> dict:
    """Check disk and data-directory usage.

    Args:
        data_dir: The directory whose disk partition is checked and whose
            recursive size is reported as ``data_dir_mb``.
        warn_threshold_mb: Free-space threshold in MB below which
            ``warning`` is set to ``True``.

    Returns:
        A dict with keys ``total_mb``, ``used_mb``, ``free_mb``,
        ``data_dir_mb``, and ``warning``.
    """
    # Resolve to an existing ancestor so shutil.disk_usage works even
    # when data_dir itself hasn't been created yet.
    probe_path = data_dir
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent

    total, used, free = shutil.disk_usage(probe_path)
    data_dir_bytes = _dir_size_bytes(data_dir)

    return {
        "total_mb": total // _BYTES_PER_MB,
        "used_mb": used // _BYTES_PER_MB,
        "free_mb": free // _BYTES_PER_MB,
        "data_dir_mb": data_dir_bytes // _BYTES_PER_MB,
        "warning": (free // _BYTES_PER_MB) < warn_threshold_mb,
    }
