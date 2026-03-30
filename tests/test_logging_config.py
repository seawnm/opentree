"""Tests for logging_config.py — written FIRST (TDD Red phase).

Tests cover:
  - setup_logging creates the log directory if missing
  - setup_logging adds exactly two handlers (console + file)
  - setup_logging is idempotent (calling twice doesn't duplicate handlers)
  - setup_logging respects the custom level argument
  - A log message at DEBUG level actually creates the log file on disk
  - get_log_path returns today's date in YYYY-MM-DD.log format
  - Console handler uses the concise format (no [name] bracket)
  - File handler uses the detailed format (includes [name] bracket)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_module():
    """Import logging_config — deferred so the Red phase shows ImportError."""
    from opentree.runner import logging_config  # noqa: PLC0415
    return logging_config


# ---------------------------------------------------------------------------
# Test: directory creation
# ---------------------------------------------------------------------------

class TestSetupLoggingCreatesDir:
    def test_creates_missing_log_dir(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "nested" / "logs"
        assert not log_dir.exists()

        mod.setup_logging(log_dir)

        assert log_dir.is_dir()

    def test_existing_log_dir_does_not_raise(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        # Must not raise even if directory already exists
        mod.setup_logging(log_dir)

        assert log_dir.is_dir()


# ---------------------------------------------------------------------------
# Test: handlers are added
# ---------------------------------------------------------------------------

class TestSetupLoggingAddsHandlers:
    def test_adds_exactly_two_handlers(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        assert len(root.handlers) == 2

    def test_adds_console_handler(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        stream_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) == 1

    def test_adds_file_handler(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1

    def teardown_method(self, method):
        """Reset root logger handlers after each test to avoid cross-test pollution."""
        logging.getLogger().handlers.clear()


# ---------------------------------------------------------------------------
# Test: idempotency (no duplicate handlers)
# ---------------------------------------------------------------------------

class TestSetupLoggingNoDuplicates:
    def test_calling_twice_keeps_exactly_two_handlers(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)
        mod.setup_logging(log_dir)

        root = logging.getLogger()
        assert len(root.handlers) == 2

    def teardown_method(self, method):
        logging.getLogger().handlers.clear()


# ---------------------------------------------------------------------------
# Test: custom level
# ---------------------------------------------------------------------------

class TestSetupLoggingCustomLevel:
    def test_console_handler_respects_warning_level(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir, level="WARNING")

        root = logging.getLogger()
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.WARNING

    def test_console_handler_defaults_to_info(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert console_handlers[0].level == logging.INFO

    def test_file_handler_always_debug(self, tmp_path):
        """File handler should always be DEBUG regardless of console level."""
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir, level="ERROR")

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert file_handlers[0].level == logging.DEBUG

    def teardown_method(self, method):
        logging.getLogger().handlers.clear()


# ---------------------------------------------------------------------------
# Test: log file is created when a message is written
# ---------------------------------------------------------------------------

class TestLogFileCreatedOnWrite:
    def test_log_file_created_after_debug_message(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        logger = logging.getLogger("opentree.test")
        logger.debug("hello from test")

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.log"
        assert log_file.exists()

    def test_log_file_contains_written_message(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        logger = logging.getLogger("opentree.test")
        logger.debug("unique-sentinel-abc123")

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.log"
        content = log_file.read_text(encoding="utf-8")
        assert "unique-sentinel-abc123" in content

    def teardown_method(self, method):
        # Close file handlers to avoid PermissionError on Windows / cleanup
        root = logging.getLogger()
        for h in list(root.handlers):
            h.close()
        root.handlers.clear()


# ---------------------------------------------------------------------------
# Test: get_log_path format
# ---------------------------------------------------------------------------

class TestGetLogPathFormat:
    def test_returns_path_in_log_dir(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        result = mod.get_log_path(log_dir)

        assert result.parent == log_dir

    def test_filename_matches_yyyy_mm_dd_pattern(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        result = mod.get_log_path(log_dir)

        # Filename must be YYYY-MM-DD.log
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
        assert pattern.match(result.name), f"Unexpected filename: {result.name}"

    def test_filename_matches_today(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        result = mod.get_log_path(log_dir)

        today = datetime.now().strftime("%Y-%m-%d")
        assert result.name == f"{today}.log"

    def test_returns_path_object(self, tmp_path):
        mod = _import_module()
        log_dir = tmp_path / "logs"

        result = mod.get_log_path(log_dir)

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Test: format strings
# ---------------------------------------------------------------------------

class TestConsoleFormat:
    def test_console_handler_format_excludes_name_bracket(self, tmp_path):
        """Console format must NOT contain [%(name)s] — concise output only."""
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        fmt_str = console_handlers[0].formatter._fmt  # type: ignore[union-attr]
        assert "%(name)s" not in fmt_str

    def teardown_method(self, method):
        logging.getLogger().handlers.clear()


class TestFileFormat:
    def test_file_handler_format_includes_name_bracket(self, tmp_path):
        """File format MUST contain %(name)s for detailed tracing."""
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.FileHandler)
        ]
        fmt_str = file_handlers[0].formatter._fmt  # type: ignore[union-attr]
        assert "%(name)s" in fmt_str

    def teardown_method(self, method):
        root = logging.getLogger()
        for h in list(root.handlers):
            h.close()
        root.handlers.clear()


# ---------------------------------------------------------------------------
# Test: max_days / backupCount
# ---------------------------------------------------------------------------

class TestMaxDays:
    def test_default_backup_count_is_30(self, tmp_path):
        """TimedRotatingFileHandler backupCount defaults to max_days=30."""
        from logging.handlers import TimedRotatingFileHandler
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir)

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].backupCount == 30

    def test_custom_max_days_sets_backup_count(self, tmp_path):
        from logging.handlers import TimedRotatingFileHandler
        mod = _import_module()
        log_dir = tmp_path / "logs"

        mod.setup_logging(log_dir, max_days=7)

        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, TimedRotatingFileHandler)
        ]
        assert file_handlers[0].backupCount == 7

    def teardown_method(self, method):
        root = logging.getLogger()
        for h in list(root.handlers):
            h.close()
        root.handlers.clear()
