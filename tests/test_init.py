"""Tests for opentree init and start commands.

Uses typer.testing.CliRunner with a temporary OPENTREE_HOME and
OPENTREE_BUNDLE_DIR pointing to the project's real modules/ directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from opentree.cli.main import app

runner = CliRunner()

# The real bundled modules directory (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUNDLE_DIR = _PROJECT_ROOT / "modules"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def opentree_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a fresh tmp dir as OPENTREE_HOME with BUNDLE_DIR set."""
    home = tmp_path / "opentree_home"
    monkeypatch.setenv("OPENTREE_HOME", str(home))
    monkeypatch.setenv("OPENTREE_BUNDLE_DIR", str(_BUNDLE_DIR))
    return home


# ------------------------------------------------------------------
# init: directory structure
# ------------------------------------------------------------------


class TestInitDirectoryStructure:
    """opentree init creates the expected directory tree."""

    def test_init_creates_directory_structure(
        self, opentree_home: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        assert (opentree_home / "modules").is_dir()
        assert (opentree_home / "workspace" / ".claude" / "rules").is_dir()
        assert (opentree_home / "data").is_dir()
        assert (opentree_home / "config").is_dir()

    def test_init_writes_user_json(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            [
                "init",
                "--non-interactive",
                "--bot-name", "MyBot",
                "--team-name", "MyTeam",
                "--admin-users", "U0TEST999",
            ],
        )
        assert result.exit_code == 0, result.output

        user_json = json.loads(
            (opentree_home / "config" / "user.json").read_text(encoding="utf-8")
        )
        assert user_json["bot_name"] == "MyBot"
        assert user_json["team_name"] == "MyTeam"
        assert user_json["admin_channel"] == ""  # deprecated, always empty

    def test_init_non_interactive_defaults(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        user_json = json.loads(
            (opentree_home / "config" / "user.json").read_text(encoding="utf-8")
        )
        assert user_json["bot_name"] == "TestBot"


# ------------------------------------------------------------------
# init: module copying and installation
# ------------------------------------------------------------------


class TestInitModules:
    """opentree init copies bundled modules and installs pre-installed set."""

    def test_init_copies_bundled_modules(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        copied = sorted(
            d.name
            for d in (opentree_home / "modules").iterdir()
            if d.is_dir() and (d / "opentree.json").is_file()
        )
        assert len(copied) == 10

    def test_init_installs_7_preinstalled(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        reg = json.loads(
            (opentree_home / "config" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        assert len(reg["modules"]) == 7
        expected = {
            "core", "memory", "personality", "scheduler",
            "slack", "guardrail", "audit-logger",
        }
        assert set(reg["modules"].keys()) == expected

    def test_init_creates_21_rules(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        md_files = list(rules_dir.rglob("*.md"))
        assert len(md_files) == 21

    def test_init_generates_claude_md(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists()
        lines = claude_md.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 200


# ------------------------------------------------------------------
# init: re-initialization
# ------------------------------------------------------------------


class TestInitReinit:
    """opentree init --force and duplicate guard."""

    def test_init_already_initialized_fails(
        self, opentree_home: Path
    ) -> None:
        # First init
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Second init without --force
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 1
        assert "Already initialized" in result.output

    def test_init_force_reinitializes(self, opentree_home: Path) -> None:
        # First init
        runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        # Second init with --force
        result = runner.invoke(
            app,
            [
                "init", "--non-interactive", "--force",
                "--admin-users", "U0TEST123", "--bot-name", "NewBot",
            ],
        )
        assert result.exit_code == 0, result.output

        user_json = json.loads(
            (opentree_home / "config" / "user.json").read_text(encoding="utf-8")
        )
        assert user_json["bot_name"] == "NewBot"


# ------------------------------------------------------------------
# init: pre-flight validation
# ------------------------------------------------------------------


class TestInitPreflight:
    """Pre-flight placeholder validation (Option C: fail ALL)."""

    def test_init_fails_without_required_params(
        self, opentree_home: Path
    ) -> None:
        """init requires --bot-name and --admin-users."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive"],
        )
        assert result.exit_code != 0

    def test_init_fails_with_invalid_admin_user_id(
        self, opentree_home: Path
    ) -> None:
        """admin user IDs must start with 'U'."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "X_INVALID"],
        )
        assert result.exit_code != 0

    def test_init_creates_runner_json_with_admin_users(
        self, opentree_home: Path
    ) -> None:
        """init should create runner.json with admin_users."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123,U0TEST456"],
        )
        assert result.exit_code == 0, result.output
        runner_json = json.loads(
            (opentree_home / "config" / "runner.json").read_text(encoding="utf-8")
        )
        assert runner_json["admin_users"] == ["U0TEST123", "U0TEST456"]


# ------------------------------------------------------------------
# start command
# ------------------------------------------------------------------


class TestStart:
    """opentree start tests."""

    def test_start_dry_run(self, opentree_home: Path) -> None:
        """--dry-run prints the claude command without executing."""
        # Init first
        runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )

        result = runner.invoke(app, ["start", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "claude" in result.output
        assert "--system-prompt" in result.output
        assert "--cwd" in result.output

    def test_start_not_initialized(self, opentree_home: Path) -> None:
        """start without init gives a clear error."""
        result = runner.invoke(app, ["start", "--dry-run"])
        assert result.exit_code == 1
        assert "Not initialized" in result.output

    def test_start_isolate_sets_env(
        self,
        opentree_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--isolate includes CLAUDE_CONFIG_DIR in output."""
        runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        result = runner.invoke(app, ["start", "--dry-run", "--isolate"])
        assert result.exit_code == 0, result.output
        assert "CLAUDE_CONFIG_DIR" in result.output


# ------------------------------------------------------------------
# Issue 5: --force warns about directories to be deleted
# ------------------------------------------------------------------


class TestInitForceWarning:
    """--force should log a WARNING listing directories that will be deleted."""

    def test_force_logs_warning_about_existing_dirs(
        self, opentree_home: Path
    ) -> None:
        """--force on already-initialized home should warn about dirs to delete."""
        # First init
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Verify modules exist before re-init
        modules_dir = opentree_home / "modules"
        existing_dirs = [d for d in modules_dir.iterdir() if d.is_dir()]
        assert len(existing_dirs) > 0

        # Re-init with --force: should log warning about existing dirs
        with patch("opentree.cli.init.logger") as mock_logger:
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
            )
            assert result.exit_code == 0, result.output

            # Check that logger.warning was called with info about dirs
            warning_calls = [
                call for call in mock_logger.warning.call_args_list
                if "--force will delete" in str(call)
            ]
            assert len(warning_calls) > 0, (
                "Expected a WARNING about directories to be deleted"
            )

    def test_force_on_fresh_home_no_warning(
        self, opentree_home: Path
    ) -> None:
        """--force on a fresh home (no existing modules) should not warn."""
        with patch("opentree.cli.init.logger") as mock_logger:
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
            )
            assert result.exit_code == 0, result.output

            # No warning about deletion expected
            warning_calls = [
                call for call in mock_logger.warning.call_args_list
                if "--force will delete" in str(call)
            ]
            assert len(warning_calls) == 0

    def test_force_interactive_prompts_for_confirmation(
        self, opentree_home: Path
    ) -> None:
        """In interactive mode (tty), --force should prompt before deleting."""
        # First init
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Re-init with --force WITHOUT --non-interactive, simulating tty
        # The user confirms with "y"
        with patch("opentree.cli.init._is_interactive", return_value=True):
            result = runner.invoke(
                app,
                [
                    "init", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
                input="y\n",
            )
            assert result.exit_code == 0, result.output

    def test_force_interactive_abort_on_no(
        self, opentree_home: Path
    ) -> None:
        """In interactive mode, answering 'n' should abort re-init."""
        # First init
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Re-init with --force, user says "n"
        with patch("opentree.cli.init._is_interactive", return_value=True):
            result = runner.invoke(
                app,
                [
                    "init", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
                input="n\n",
            )
            assert result.exit_code == 1


# ------------------------------------------------------------------
# Issue 6: init module install is transactional
# ------------------------------------------------------------------


class TestInitTransactionalInstall:
    """Module installation should be transactional: all-or-nothing."""

    def test_partial_failure_rolls_back_registry(
        self, opentree_home: Path
    ) -> None:
        """If a module fails to install, registry should be rolled back
        to its pre-install state."""
        # First init succeeds
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Snapshot the original registry
        reg_before = json.loads(
            (opentree_home / "config" / "registry.json").read_text(encoding="utf-8")
        )
        assert len(reg_before["modules"]) == 7

        # Force re-init, but make _install_single_module fail on "slack"
        import opentree.cli.init as init_mod
        original_install = init_mod._install_single_module

        def failing_install(home, module_name, *args, **kwargs):
            if module_name == "slack":
                raise RuntimeError("Simulated install failure")
            return original_install(home, module_name, *args, **kwargs)

        with patch.object(
            init_mod, "_install_single_module", side_effect=failing_install
        ):
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
            )
            # Should fail
            assert result.exit_code != 0

        # The registry should have been rolled back to the original state
        reg_after = json.loads(
            (opentree_home / "config" / "registry.json").read_text(encoding="utf-8")
        )
        assert len(reg_after["modules"]) == 7
        assert set(reg_after["modules"].keys()) == set(reg_before["modules"].keys())

    def test_successful_init_no_backup_dirs_left(
        self, opentree_home: Path
    ) -> None:
        """After successful init, no backup directories should remain."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # No _install_backup or similar temp dirs under opentree_home
        backup_dir = opentree_home / "_install_backup"
        assert not backup_dir.exists()

    def test_failed_init_no_backup_dirs_left(
        self, opentree_home: Path
    ) -> None:
        """Even after failed init, backup dir should be cleaned up."""
        # First init succeeds
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        import opentree.cli.init as init_mod
        original_install = init_mod._install_single_module

        def failing_install(home, module_name, *args, **kwargs):
            if module_name == "guardrail":
                raise RuntimeError("Simulated failure")
            return original_install(home, module_name, *args, **kwargs)

        with patch.object(
            init_mod, "_install_single_module", side_effect=failing_install
        ):
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--admin-users", "U0TEST123",
                ],
            )
            assert result.exit_code != 0

        # Backup dir should be cleaned up even after failure
        backup_dir = opentree_home / "_install_backup"
        assert not backup_dir.exists()
