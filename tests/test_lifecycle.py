"""Tests for lifecycle commands (opentree stop) — Fix 5.

Tests cover:
  - _read_pid_file: valid, missing, invalid content
  - _process_alive: running, dead, permission error
  - _validate_process_identity: match, no /proc, mismatch
  - _cleanup_stale_files: removes all stale files
  - stop_command: normal stop, no PID file, stale PID, --force, not initialized
"""

from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from opentree.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_opentree_home(tmp_path: Path) -> Path:
    """Create a minimal initialized opentree home."""
    home = tmp_path / "opentree_home"
    (home / "data").mkdir(parents=True)
    (home / "config").mkdir(parents=True)
    # Minimal registry so _resolve_home recognizes it
    return home


def _write_pid(home: Path, filename: str, pid: int) -> Path:
    """Write a PID to a file in data/."""
    path = home / "data" / filename
    path.write_text(str(pid), encoding="utf-8")
    return path


# ===========================================================================
# _read_pid_file tests
# ===========================================================================


class TestReadPidFile:
    def test_read_pid_file_valid(self, tmp_path: Path) -> None:
        """Reads a valid PID from a file."""
        from opentree.cli.lifecycle import _read_pid_file

        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345\n", encoding="utf-8")
        assert _read_pid_file(pid_file) == 12345

    def test_read_pid_file_missing(self, tmp_path: Path) -> None:
        """Returns None when file does not exist."""
        from opentree.cli.lifecycle import _read_pid_file

        pid_file = tmp_path / "nonexistent.pid"
        assert _read_pid_file(pid_file) is None

    def test_read_pid_file_invalid(self, tmp_path: Path) -> None:
        """Returns None when file contains non-numeric content."""
        from opentree.cli.lifecycle import _read_pid_file

        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number\n", encoding="utf-8")
        assert _read_pid_file(pid_file) is None


# ===========================================================================
# _process_alive tests
# ===========================================================================


class TestProcessAlive:
    def test_process_alive_running(self) -> None:
        """Returns True for a running process."""
        from opentree.cli.lifecycle import _process_alive

        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None  # signal 0 succeeds
            assert _process_alive(12345) is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_process_alive_dead(self) -> None:
        """Returns False when process does not exist."""
        from opentree.cli.lifecycle import _process_alive

        with patch("os.kill", side_effect=ProcessLookupError):
            assert _process_alive(99999) is False

    def test_process_alive_permission_error(self) -> None:
        """Returns True when PermissionError (process exists but no perms)."""
        from opentree.cli.lifecycle import _process_alive

        with patch("os.kill", side_effect=PermissionError):
            assert _process_alive(12345) is True


# ===========================================================================
# _validate_process_identity tests
# ===========================================================================


class TestValidateProcessIdentity:
    def test_match(self, tmp_path: Path) -> None:
        """Returns True when /proc/cmdline contains expected keyword."""
        from opentree.cli.lifecycle import _validate_process_identity

        # Create fake /proc/<pid>/cmdline
        proc_dir = tmp_path / "proc" / "1234"
        proc_dir.mkdir(parents=True)
        cmdline_file = proc_dir / "cmdline"
        # /proc/cmdline uses null bytes as separators
        cmdline_file.write_bytes(b"/bin/bash\x00run.sh\x00--home\x00/opt")

        with patch(
            "opentree.cli.lifecycle._validate_process_identity"
        ) as mock_validate:
            # We can't easily mock /proc path, so test the logic directly
            pass

        # Direct test by calling with patched Path
        with patch("opentree.cli.lifecycle.Path") as mock_path_cls:
            cmdline_path = mock_path_cls.return_value
            cmdline_path.exists.return_value = True
            cmdline_path.read_bytes.return_value = (
                b"/bin/bash\x00run.sh\x00--home\x00/opt"
            )
            result = _validate_process_identity(1234, ("run.sh", "opentree"))
            assert result is True

    def test_no_proc(self) -> None:
        """Returns True (fallback) when /proc does not exist."""
        from opentree.cli.lifecycle import _validate_process_identity

        with patch("opentree.cli.lifecycle.Path") as mock_path_cls:
            cmdline_path = mock_path_cls.return_value
            cmdline_path.exists.return_value = False
            result = _validate_process_identity(1234, ("run.sh",))
            assert result is True

    def test_mismatch(self) -> None:
        """Returns False when /proc/cmdline does not contain expected keywords."""
        from opentree.cli.lifecycle import _validate_process_identity

        with patch("opentree.cli.lifecycle.Path") as mock_path_cls:
            cmdline_path = mock_path_cls.return_value
            cmdline_path.exists.return_value = True
            cmdline_path.read_bytes.return_value = (
                b"/usr/bin/python\x00some_other_script.py"
            )
            result = _validate_process_identity(1234, ("run.sh", "opentree"))
            assert result is False


# ===========================================================================
# _cleanup_stale_files tests
# ===========================================================================


class TestCleanupStaleFiles:
    def test_cleanup_stale_files(self, tmp_path: Path) -> None:
        """Removes all expected stale files."""
        from opentree.cli.lifecycle import _cleanup_stale_files

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
            (data_dir / name).write_text("stale", encoding="utf-8")

        _cleanup_stale_files(data_dir)

        for name in ("wrapper.pid", "bot.pid", ".stop_requested", "bot.heartbeat"):
            assert not (data_dir / name).exists(), f"{name} should be removed"

    def test_cleanup_missing_files_no_error(self, tmp_path: Path) -> None:
        """Does not error when files don't exist."""
        from opentree.cli.lifecycle import _cleanup_stale_files

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Should not raise
        _cleanup_stale_files(data_dir)


# ===========================================================================
# stop_command integration tests (via CLI runner)
# ===========================================================================


class TestStopCommand:
    def test_stop_command_normal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normal stop: wrapper.pid exists and process is alive."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        _write_pid(home, "wrapper.pid", 1000)

        with (
            patch(
                "opentree.cli.lifecycle._process_alive", return_value=True
            ) as mock_alive,
            patch(
                "opentree.cli.lifecycle._validate_process_identity",
                return_value=True,
            ),
            patch("opentree.cli.lifecycle.os.kill") as mock_kill,
            patch(
                "opentree.cli.lifecycle._wait_for_exit", return_value=True
            ),
            patch("opentree.cli.lifecycle._cleanup_stale_files") as mock_cleanup,
        ):
            result = runner.invoke(app, ["stop", "--home", str(home)])

        assert result.exit_code == 0, result.output
        assert "stopped successfully" in result.output
        # SIGTERM should have been sent
        mock_kill.assert_called_once_with(1000, signal.SIGTERM)
        mock_cleanup.assert_called_once()
        # Stop flag should have been written
        stop_flag = home / "data" / ".stop_requested"
        assert stop_flag.exists()

    def test_stop_command_no_pid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No PID file — reports no running process."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        result = runner.invoke(app, ["stop", "--home", str(home)])

        assert result.exit_code == 1
        assert "No running OpenTree process found" in result.output

    def test_stop_command_stale_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PID file exists but process is dead — cleans up stale files."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        _write_pid(home, "wrapper.pid", 9999)

        with (
            patch(
                "opentree.cli.lifecycle._process_alive", return_value=False
            ),
            patch(
                "opentree.cli.lifecycle._cleanup_stale_files"
            ) as mock_cleanup,
        ):
            result = runner.invoke(app, ["stop", "--home", str(home)])

        assert result.exit_code == 1
        assert "stale" in result.output
        mock_cleanup.assert_called_once()

    def test_stop_command_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--force sends SIGKILL after timeout."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        _write_pid(home, "wrapper.pid", 2000)

        kill_calls = []

        def mock_kill_fn(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGKILL:
                return  # SIGKILL succeeds

        with (
            patch(
                "opentree.cli.lifecycle._process_alive"
            ) as mock_alive,
            patch(
                "opentree.cli.lifecycle._validate_process_identity",
                return_value=True,
            ),
            patch("opentree.cli.lifecycle.os.kill", side_effect=mock_kill_fn),
            patch(
                "opentree.cli.lifecycle._wait_for_exit", return_value=False
            ),
            patch("opentree.cli.lifecycle.time.sleep"),
            patch("opentree.cli.lifecycle._cleanup_stale_files"),
        ):
            # After SIGKILL, process should be dead
            mock_alive.side_effect = [
                True,   # initial check: wrapper alive
                False,  # after SIGKILL: dead
            ]
            result = runner.invoke(
                app, ["stop", "--home", str(home), "--force", "--timeout", "1"]
            )

        assert result.exit_code == 0, result.output
        assert "force-killed" in result.output
        # Should have sent SIGTERM then SIGKILL
        assert (2000, signal.SIGTERM) in kill_calls
        assert (2000, signal.SIGKILL) in kill_calls

    def test_stop_command_not_initialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop on uninitialized directory — reports error."""
        home = tmp_path / "empty_home"
        home.mkdir()
        # No data/ directory
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        result = runner.invoke(app, ["stop", "--home", str(home)])

        assert result.exit_code == 1
        assert "Data directory not found" in result.output

    def test_stop_command_fallback_to_bot_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to bot.pid when wrapper.pid is missing."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        # Only bot.pid, no wrapper.pid
        _write_pid(home, "bot.pid", 3000)

        with (
            patch(
                "opentree.cli.lifecycle._process_alive", return_value=True
            ),
            patch(
                "opentree.cli.lifecycle._validate_process_identity",
                return_value=True,
            ),
            patch("opentree.cli.lifecycle.os.kill"),
            patch(
                "opentree.cli.lifecycle._wait_for_exit", return_value=True
            ),
            patch("opentree.cli.lifecycle._cleanup_stale_files"),
        ):
            result = runner.invoke(app, ["stop", "--home", str(home)])

        assert result.exit_code == 0, result.output
        assert "wrapper.pid not found" in result.output
        assert "stopped successfully" in result.output

    def test_stop_command_timeout_no_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timeout without --force reports error and suggests --force."""
        home = _make_opentree_home(tmp_path)
        monkeypatch.setenv("OPENTREE_HOME", str(home))

        _write_pid(home, "wrapper.pid", 4000)

        with (
            patch(
                "opentree.cli.lifecycle._process_alive", return_value=True
            ),
            patch(
                "opentree.cli.lifecycle._validate_process_identity",
                return_value=True,
            ),
            patch("opentree.cli.lifecycle.os.kill"),
            patch(
                "opentree.cli.lifecycle._wait_for_exit", return_value=False
            ),
        ):
            result = runner.invoke(
                app, ["stop", "--home", str(home), "--timeout", "1"]
            )

        assert result.exit_code == 1
        assert "did not exit" in result.output
        assert "--force" in result.output
