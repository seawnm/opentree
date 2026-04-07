"""Tests for run.sh template — Fix 4 (wrapper.pid + stop flag).

Validates that the run.sh template contains the expected shell constructs
for wrapper PID tracking and stop flag checking. Since run.sh is a bash
template rendered by ``opentree init``, we test via string inspection
rather than shell execution.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def run_sh_content() -> str:
    """Read the run.sh template from the package."""
    template = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "opentree"
        / "templates"
        / "run.sh"
    )
    assert template.is_file(), f"run.sh template not found at {template}"
    return template.read_text(encoding="utf-8")


class TestWrapperPid:
    """run.sh must define and manage WRAPPER_PID_FILE."""

    def test_defines_wrapper_pid_file(self, run_sh_content: str) -> None:
        """WRAPPER_PID_FILE variable is defined pointing to data dir."""
        assert 'WRAPPER_PID_FILE="$DATA_DIR/wrapper.pid"' in run_sh_content

    def test_writes_wrapper_pid(self, run_sh_content: str) -> None:
        """Wrapper writes its own PID to WRAPPER_PID_FILE after flock."""
        assert 'echo "$$" > "$WRAPPER_PID_FILE"' in run_sh_content

    def test_cleanup_removes_wrapper_pid(self, run_sh_content: str) -> None:
        """cleanup() function removes both PID_FILE and WRAPPER_PID_FILE."""
        assert '"$WRAPPER_PID_FILE"' in run_sh_content
        # The rm -f line in cleanup should contain both PID files
        assert 'rm -f "$PID_FILE" "$WRAPPER_PID_FILE"' in run_sh_content

    def test_exit_trap_removes_wrapper_pid(self, run_sh_content: str) -> None:
        """EXIT trap cleans up WRAPPER_PID_FILE."""
        # The EXIT trap should reference WRAPPER_PID_FILE
        assert 'rm -f "$WRAPPER_PID_FILE"' in run_sh_content


class TestStopFlag:
    """run.sh must define and check STOP_FLAG."""

    def test_defines_stop_flag(self, run_sh_content: str) -> None:
        """STOP_FLAG variable is defined."""
        assert 'STOP_FLAG="$DATA_DIR/.stop_requested"' in run_sh_content

    def test_checks_stop_flag_in_loop(self, run_sh_content: str) -> None:
        """while loop checks for stop flag before crash loop detection."""
        # The stop flag check should appear in the file
        assert 'if [ -f "$STOP_FLAG" ]' in run_sh_content

    def test_removes_stop_flag_on_detection(self, run_sh_content: str) -> None:
        """Stop flag is removed after detection."""
        assert 'rm -f "$STOP_FLAG"' in run_sh_content

    def test_stop_flag_before_crash_loop(self, run_sh_content: str) -> None:
        """Stop flag check appears BEFORE crash loop detection in the while loop."""
        stop_flag_pos = run_sh_content.index('if [ -f "$STOP_FLAG" ]')
        crash_loop_pos = run_sh_content.index(
            "Crash loop detection", stop_flag_pos - 200
        )
        # The stop flag check should appear before crash loop detection
        # But we need to find the stop flag check that's inside the while loop
        # Find the while true line
        while_pos = run_sh_content.index("while true; do")
        # Stop flag check should be after while true
        assert stop_flag_pos > while_pos
        # And before crash loop detection
        assert stop_flag_pos < crash_loop_pos
