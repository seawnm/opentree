"""Logging configuration for OpenTree bot runner.

Sets up:
- Console handler (INFO level) with concise format
- Daily rotating file handler (DEBUG level) with detailed format
- Log files: $OPENTREE_HOME/data/logs/YYYY-MM-DD.log
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

# Format strings
_CONSOLE_FORMAT = "%(asctime)s %(levelname)-5s %(message)s"
_CONSOLE_DATE = "%H:%M:%S"
_FILE_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_FILE_DATE = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    max_days: int = 30,
) -> None:
    """Configure logging for the bot runner.

    Args:
        log_dir: Directory for log files (created if missing)
        level: Root logger level (DEBUG, INFO, WARNING, ERROR)
        max_days: Days to keep old log files (default 30)
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter

    # Remove any pre-existing handlers (avoid duplicates on re-init)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATE))
    root.addHandler(console)

    # File handler (daily rotation)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = TimedRotatingFileHandler(
        str(log_file),
        when="midnight",
        backupCount=max_days,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_FILE_DATE))
    root.addHandler(file_handler)


def get_log_path(log_dir: Path) -> Path:
    """Return the path to today's log file."""
    return log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
