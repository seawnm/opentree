"""Tests for opentree init and start commands.

Uses typer.testing.CliRunner with a temporary OPENTREE_HOME and
OPENTREE_BUNDLE_DIR pointing to the project's real modules/ directory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
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
        assert "owner_description" in user_json

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


# ------------------------------------------------------------------
# init: command detection for run.sh
# ------------------------------------------------------------------


class TestInitCommandDetection:
    """opentree init detects source checkout vs installed package and adjusts BOT_CMD."""

    def test_init_uv_run_in_source_checkout(
        self, opentree_home: Path
    ) -> None:
        """In a source checkout (pyproject.toml exists, not on PATH), run.sh uses 'uv run --directory'."""
        # Tests always run from source checkout; mock shutil.which to return None
        # so auto mode falls through to pyproject.toml detection.
        with patch("opentree.cli.init.subprocess.run") as mock_run, \
             patch("opentree.cli.init.shutil.which", return_value=None):
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        run_sh = (opentree_home / "bin" / "run.sh").read_text(encoding="utf-8")
        bot_cmd_lines = [l for l in run_sh.splitlines() if "BOT_CMD=" in l and "start" in l]
        baked_line = [l for l in bot_cmd_lines if "$OPENTREE_CMD" not in l][0]
        assert "uv run --directory" in baked_line
        assert "opentree" in baked_line

    def test_init_bare_opentree_when_installed(
        self, opentree_home: Path
    ) -> None:
        """When not a source checkout (no pyproject.toml), run.sh uses bare 'opentree'."""
        with patch(
            "opentree.cli.init._resolve_opentree_cmd",
            return_value=("opentree", None),
        ):
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        run_sh = (opentree_home / "bin" / "run.sh").read_text(encoding="utf-8")
        # The else branch contains the baked-in command
        bot_cmd_lines = [l for l in run_sh.splitlines() if "BOT_CMD=" in l and "start" in l]
        # Find the else-branch line (not the OPENTREE_CMD override line)
        baked_line = [l for l in bot_cmd_lines if "$OPENTREE_CMD" not in l][0]
        assert "opentree start" in baked_line
        assert "uv run" not in baked_line

    def test_init_uv_run_includes_unquoted_project_root(
        self, opentree_home: Path
    ) -> None:
        """The uv run --directory path is NOT single-quoted (Issue #1 fix)."""
        with patch("opentree.cli.init.subprocess.run") as mock_run, \
             patch("opentree.cli.init.shutil.which", return_value=None):
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        run_sh = (opentree_home / "bin" / "run.sh").read_text(encoding="utf-8")
        bot_cmd_lines = [l for l in run_sh.splitlines() if "BOT_CMD=" in l and "start" in l]
        baked_line = [l for l in bot_cmd_lines if "$OPENTREE_CMD" not in l][0]
        # Path should NOT be single-quoted (flow sim Issue #1)
        assert "'" not in baked_line, (
            f"Expected no single-quotes in: {baked_line}"
        )
        match = re.search(r"--directory\s+(\S+)\s+opentree", baked_line)
        assert match is not None, f"Expected unquoted path in: {default_cmd_line}"
        project_dir = Path(match.group(1))
        assert (project_dir / "pyproject.toml").exists()

    def test_init_uv_sync_called_when_source_checkout(
        self, opentree_home: Path
    ) -> None:
        """In source checkout mode, init calls 'uv sync --extra slack'."""
        project_root = Path(__file__).resolve().parent.parent
        with patch("opentree.cli.init.subprocess.run") as mock_run, \
             patch("opentree.cli.init.shutil.which", return_value=None):
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Verify exact uv sync call
        assert any(
            call.args[0][:4] == ["uv", "sync", "--extra", "slack"]
            for call in mock_run.call_args_list
            if call.args
        ), f"Expected 'uv sync --extra slack' call, got: {mock_run.call_args_list}"

    def test_init_uv_sync_failure_warns_but_continues(
        self, opentree_home: Path
    ) -> None:
        """If uv sync fails, init should warn but not abort."""
        with patch("opentree.cli.init.subprocess.run", side_effect=Exception("network error")), \
             patch("opentree.cli.init.shutil.which", return_value=None), \
             patch("opentree.cli.init.logger") as mock_logger:
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        assert mock_logger.warning.called

    def test_init_no_uv_sync_when_installed(
        self, opentree_home: Path
    ) -> None:
        """When not a source checkout, uv sync should NOT be called."""
        with patch(
            "opentree.cli.init._resolve_opentree_cmd",
            return_value=("opentree", None),
        ), patch("opentree.cli.init.subprocess.run") as mock_run:
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        assert not mock_run.called, "uv sync should not be called in installed mode"


# ------------------------------------------------------------------
# Phase 2B: .env file generation
# ------------------------------------------------------------------


class TestInitEnvFiles:
    """opentree init generates .env.defaults + .env.local.example."""

    def test_generates_env_defaults(self, opentree_home: Path) -> None:
        """init should create config/.env.defaults."""
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        env_defaults = opentree_home / "config" / ".env.defaults"
        assert env_defaults.exists()
        content = env_defaults.read_text(encoding="utf-8")
        assert "SLACK_BOT_TOKEN" in content
        assert "SLACK_APP_TOKEN" in content

    def test_generates_env_local_example(self, opentree_home: Path) -> None:
        """init should create config/.env.local.example."""
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        env_local_example = opentree_home / "config" / ".env.local.example"
        assert env_local_example.exists()
        content = env_local_example.read_text(encoding="utf-8")
        assert "Owner" in content or "owner" in content.lower()
        assert ".env.local" in content

    def test_no_legacy_env_example(self, opentree_home: Path) -> None:
        """init should NOT create .env.example anymore."""
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        env_example = opentree_home / "config" / ".env.example"
        assert not env_example.exists()

    def test_force_removes_legacy_example(self, opentree_home: Path) -> None:
        """--force removes old .env.example if present."""
        # First init to set up directory structure
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Manually create legacy .env.example
        legacy_example = opentree_home / "config" / ".env.example"
        legacy_example.write_text("# old\n", encoding="utf-8")
        assert legacy_example.exists()

        # Re-init with --force
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--owner", "U0TEST123",
                ],
            )
        assert result.exit_code == 0, result.output
        assert not legacy_example.exists()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="File permissions not reliable on Windows",
    )
    def test_env_defaults_has_restrictive_permissions(
        self, opentree_home: Path
    ) -> None:
        """.env.defaults should have 0o600 permissions on Linux/Mac."""
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output
        env_defaults = opentree_home / "config" / ".env.defaults"
        mode = env_defaults.stat().st_mode & 0o777
        assert mode == 0o600


# ------------------------------------------------------------------
# Phase 2A: CLAUDE.md marker tests in init
# ------------------------------------------------------------------

from opentree.generator.claude_md import _AUTO_BEGIN, _AUTO_END


class TestInitClaudeMdMarkers:
    """init generates CLAUDE.md with AUTO markers."""

    def test_init_generates_markers(self, opentree_home: Path) -> None:
        """init should produce CLAUDE.md with AUTO:BEGIN and AUTO:END markers."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        assert _AUTO_BEGIN in content
        assert _AUTO_END in content

    def test_force_init_preserves_owner_content(
        self, opentree_home: Path
    ) -> None:
        """force re-init should preserve owner-written content below END marker."""
        # First init
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        # Append owner content after the auto block
        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        original = claude_md.read_text(encoding="utf-8")
        owner_block = "\n## Owner Custom Rules\n\nDo not delete this.\n"
        claude_md.write_text(original + owner_block, encoding="utf-8")

        # Force re-init
        result = runner.invoke(
            app,
            [
                "init", "--non-interactive", "--force",
                "--bot-name", "NewBot", "--admin-users", "U0TEST123",
            ],
        )
        assert result.exit_code == 0, result.output

        content = claude_md.read_text(encoding="utf-8")
        # New bot name should be present
        assert "NewBot" in content
        # Owner content should be preserved
        assert "## Owner Custom Rules" in content
        assert "Do not delete this." in content


class TestBackupStateIncludesClaudeMd:
    """_backup_state should include CLAUDE.md in the backup."""

    def test_backup_includes_claude_md(self, opentree_home: Path) -> None:
        """_backup_state should back up CLAUDE.md when it exists."""
        # First init to create CLAUDE.md
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output

        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists()

        # Call _backup_state directly
        from opentree.cli.init import _backup_state
        backup_dir = _backup_state(opentree_home)

        assert backup_dir is not None
        backup_claude_md = backup_dir / "workspace" / "CLAUDE.md"
        assert backup_claude_md.exists()
        assert backup_claude_md.read_text(encoding="utf-8") == claude_md.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# _resolve_opentree_cmd() unit tests
# ------------------------------------------------------------------


class TestResolveOpentreeCmd:
    """Unit tests for _resolve_opentree_cmd() with cmd_mode parameter."""

    def test_resolve_opentree_cmd_bare_mode(self) -> None:
        """bare mode always returns ('opentree', None)."""
        from opentree.cli.init import _resolve_opentree_cmd

        cmd, root = _resolve_opentree_cmd("bare")
        assert cmd == "opentree"
        assert root is None

    def test_resolve_opentree_cmd_auto_source_checkout(self) -> None:
        """auto mode returns uv run in a source checkout (pyproject.toml takes priority)."""
        from opentree.cli.init import _resolve_opentree_cmd

        # We are in a source checkout, so pyproject.toml exists → uv run
        cmd, root = _resolve_opentree_cmd("auto")
        assert "uv run --directory" in cmd
        assert root is not None
        assert (root / "pyproject.toml").is_file()

    def test_resolve_opentree_cmd_auto_no_source_with_which(self) -> None:
        """auto mode falls back to shutil.which when no pyproject.toml."""
        import opentree.cli.init as init_mod

        project_root = Path(init_mod.__file__).resolve().parent.parent.parent.parent
        pyproject = project_root / "pyproject.toml"
        backup = project_root / "pyproject.toml.bak"
        renamed = False
        if pyproject.exists():
            pyproject.rename(backup)
            renamed = True
        try:
            with patch("opentree.cli.init.shutil.which", return_value="/usr/bin/opentree"):
                cmd, root = init_mod._resolve_opentree_cmd("auto")
        finally:
            if renamed:
                backup.rename(pyproject)
        assert cmd == "opentree"
        assert root is None

    def test_resolve_opentree_cmd_auto_no_source_no_which(self) -> None:
        """auto mode falls back to bare when no pyproject.toml and no which."""
        import opentree.cli.init as init_mod

        project_root = Path(init_mod.__file__).resolve().parent.parent.parent.parent
        pyproject = project_root / "pyproject.toml"
        backup = project_root / "pyproject.toml.bak"
        renamed = False
        if pyproject.exists():
            pyproject.rename(backup)
            renamed = True
        try:
            with patch("opentree.cli.init.shutil.which", return_value=None):
                cmd, root = init_mod._resolve_opentree_cmd("auto")
        finally:
            if renamed:
                backup.rename(pyproject)
        assert cmd == "opentree"
        assert root is None

    def test_resolve_opentree_cmd_uv_run_with_source(self) -> None:
        """uv-run mode returns uv run command when pyproject.toml exists."""
        from opentree.cli.init import _resolve_opentree_cmd

        cmd, root = _resolve_opentree_cmd("uv-run")
        # We are in a source checkout
        assert "uv run --directory" in cmd
        assert root is not None
        assert (root / "pyproject.toml").is_file()

    def test_resolve_opentree_cmd_uv_run_no_source(self) -> None:
        """uv-run mode falls back to bare when no pyproject.toml."""
        import opentree.cli.init as init_mod

        project_root = Path(init_mod.__file__).resolve().parent.parent.parent.parent
        pyproject = project_root / "pyproject.toml"
        backup = project_root / "pyproject.toml.bak"
        renamed = False
        if pyproject.exists():
            pyproject.rename(backup)
            renamed = True
        try:
            cmd, root = init_mod._resolve_opentree_cmd("uv-run")
        finally:
            if renamed:
                backup.rename(pyproject)
        assert cmd == "opentree"
        assert root is None

    def test_resolve_opentree_cmd_invalid_mode(self) -> None:
        """Invalid cmd_mode raises typer.BadParameter."""
        from opentree.cli.init import _resolve_opentree_cmd

        with pytest.raises(typer.BadParameter, match="Invalid --cmd-mode"):
            _resolve_opentree_cmd("invalid")

    def test_resolve_opentree_cmd_no_quotes_in_uv_run(self) -> None:
        """uv-run mode should NOT include single-quotes in the returned command string."""
        from opentree.cli.init import _resolve_opentree_cmd

        with patch("opentree.cli.init.shutil.which", return_value=None):
            cmd, _ = _resolve_opentree_cmd("auto")
        # If we're in source checkout, cmd will contain "uv run --directory"
        if "uv run" in cmd:
            assert "'" not in cmd, f"No single-quotes expected in: {cmd}"

        cmd2, _ = _resolve_opentree_cmd("uv-run")
        if "uv run" in cmd2:
            assert "'" not in cmd2, f"No single-quotes expected in: {cmd2}"


# ------------------------------------------------------------------
# Fix 1: init creates data/logs/ directory
# ------------------------------------------------------------------


class TestInitDataLogs:
    """init should create data/logs/ directory."""

    def test_init_creates_data_logs_directory(
        self, opentree_home: Path
    ) -> None:
        """init creates data/logs/ directory."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
        )
        assert result.exit_code == 0, result.output
        assert (opentree_home / "data" / "logs").is_dir()


# ------------------------------------------------------------------
# Fix 2: init migrates legacy .env -> .env.local
# ------------------------------------------------------------------


class TestEnvHasRealTokens:
    """Unit tests for _env_has_real_tokens helper."""

    def test_real_tokens_returns_true(self, tmp_path: Path) -> None:
        """File with real tokens returns True."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / ".env"
        env.write_text(
            "SLACK_BOT_TOKEN=xoxb-1234567890-abcdef\n"
            "SLACK_APP_TOKEN=xapp-1-abc-def\n",
            encoding="utf-8",
        )
        assert _env_has_real_tokens(env) is True

    def test_placeholder_tokens_returns_false(self, tmp_path: Path) -> None:
        """File with only placeholder tokens returns False."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / ".env"
        env.write_text(
            "SLACK_BOT_TOKEN=xoxb-your-bot-token\n"
            "SLACK_APP_TOKEN=xapp-your-app-token\n",
            encoding="utf-8",
        )
        assert _env_has_real_tokens(env) is False

    def test_empty_file_returns_false(self, tmp_path: Path) -> None:
        """Empty file returns False."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / ".env"
        env.write_text("", encoding="utf-8")
        assert _env_has_real_tokens(env) is False

    def test_comments_only_returns_false(self, tmp_path: Path) -> None:
        """File with only comments returns False."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / ".env"
        env.write_text("# just a comment\n# another one\n", encoding="utf-8")
        assert _env_has_real_tokens(env) is False

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        """Non-existent file returns False."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / "nonexistent"
        assert _env_has_real_tokens(env) is False

    def test_mixed_real_and_placeholder(self, tmp_path: Path) -> None:
        """One real + one placeholder -> True (at least one real)."""
        from opentree.cli.init import _env_has_real_tokens

        env = tmp_path / ".env"
        env.write_text(
            "SLACK_BOT_TOKEN=xoxb-1234-real\n"
            "SLACK_APP_TOKEN=xapp-your-app-token\n",
            encoding="utf-8",
        )
        assert _env_has_real_tokens(env) is True


class TestInitLegacyEnvMigration:
    """init should migrate legacy .env -> .env.local when real tokens present."""

    def test_init_migrates_legacy_env_to_env_local(
        self, opentree_home: Path
    ) -> None:
        """Legacy .env with real tokens is copied to .env.local."""
        # First init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Place a legacy .env with real tokens
        legacy_env = opentree_home / "config" / ".env"
        legacy_env.write_text(
            "SLACK_BOT_TOKEN=xoxb-1234-real-token\n"
            "SLACK_APP_TOKEN=xapp-5678-real-token\n",
            encoding="utf-8",
        )

        # Force re-init triggers migration
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--owner", "U0TEST123",
                ],
            )
        assert result.exit_code == 0, result.output

        env_local = opentree_home / "config" / ".env.local"
        assert env_local.exists()
        content = env_local.read_text(encoding="utf-8")
        assert "xoxb-1234-real-token" in content
        assert "xapp-5678-real-token" in content

    def test_init_does_not_overwrite_existing_env_local(
        self, opentree_home: Path
    ) -> None:
        """.env.local already exists -> no overwrite, warning emitted."""
        # First init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Place legacy .env with real tokens
        legacy_env = opentree_home / "config" / ".env"
        legacy_env.write_text(
            "SLACK_BOT_TOKEN=xoxb-1234-real\nSLACK_APP_TOKEN=xapp-5678-real\n",
            encoding="utf-8",
        )
        # Pre-existing .env.local
        env_local = opentree_home / "config" / ".env.local"
        env_local.write_text("SLACK_BOT_TOKEN=xoxb-existing\n", encoding="utf-8")

        # Force re-init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--owner", "U0TEST123",
                ],
            )
        assert result.exit_code == 0, result.output

        # .env.local should NOT be overwritten
        content = env_local.read_text(encoding="utf-8")
        assert "xoxb-existing" in content
        assert "xoxb-1234-real" not in content
        # Warning should appear in stderr output
        assert "WARNING" in result.output or "already exists" in result.output

    def test_init_does_not_migrate_placeholder_env(
        self, opentree_home: Path
    ) -> None:
        """Legacy .env with placeholder tokens is NOT migrated."""
        # First init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Place legacy .env with placeholder tokens
        legacy_env = opentree_home / "config" / ".env"
        legacy_env.write_text(
            "SLACK_BOT_TOKEN=xoxb-your-bot-token\n"
            "SLACK_APP_TOKEN=xapp-your-app-token\n",
            encoding="utf-8",
        )

        # Force re-init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--owner", "U0TEST123",
                ],
            )
        assert result.exit_code == 0, result.output

        env_local = opentree_home / "config" / ".env.local"
        assert not env_local.exists()

    def test_init_migrates_env_on_force_reinit(
        self, opentree_home: Path
    ) -> None:
        """--force re-init also triggers migration."""
        # First init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--bot-name", "TestBot", "--owner", "U0TEST123"],
            )
        assert result.exit_code == 0, result.output

        # Create legacy .env with real tokens
        legacy_env = opentree_home / "config" / ".env"
        legacy_env.write_text(
            "SLACK_BOT_TOKEN=xoxb-force-test\nSLACK_APP_TOKEN=xapp-force-test\n",
            encoding="utf-8",
        )

        # Force re-init
        with patch("opentree.cli.init.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            result = runner.invoke(
                app,
                [
                    "init", "--non-interactive", "--force",
                    "--bot-name", "TestBot", "--owner", "U0TEST123",
                ],
            )
        assert result.exit_code == 0, result.output

        env_local = opentree_home / "config" / ".env.local"
        assert env_local.exists()
        content = env_local.read_text(encoding="utf-8")
        assert "xoxb-force-test" in content


# ------------------------------------------------------------------
# _bundled_modules_dir() dual-path tests
# ------------------------------------------------------------------


class TestBundledModulesDir:
    """Unit tests for _bundled_modules_dir() with installed + dev fallback."""

    def test_bundled_modules_dir_env_override(self, tmp_path: Path) -> None:
        """OPENTREE_BUNDLE_DIR set to a valid directory is used."""
        from opentree.cli.init import _bundled_modules_dir

        with patch.dict(os.environ, {"OPENTREE_BUNDLE_DIR": str(tmp_path)}):
            result = _bundled_modules_dir()
        assert result == tmp_path.resolve()

    def test_bundled_modules_dir_env_invalid(self, tmp_path: Path) -> None:
        """OPENTREE_BUNDLE_DIR pointing to nonexistent dir raises FileNotFoundError."""
        from opentree.cli.init import _bundled_modules_dir

        bad_path = str(tmp_path / "no_such_dir")
        with patch.dict(os.environ, {"OPENTREE_BUNDLE_DIR": bad_path}):
            with pytest.raises(FileNotFoundError, match="OPENTREE_BUNDLE_DIR"):
                _bundled_modules_dir()

    def test_bundled_modules_dir_installed_path(self, tmp_path: Path) -> None:
        """When bundled_modules/ exists in pkg_root, it is returned."""
        from opentree.cli.init import _bundled_modules_dir

        # Create a fake bundled_modules dir at pkg_root level
        pkg_root = Path(__file__).resolve().parent.parent / "src" / "opentree"
        bundled = pkg_root / "bundled_modules"
        bundled.mkdir(exist_ok=True)
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENTREE_BUNDLE_DIR", None)
                result = _bundled_modules_dir()
            assert result == bundled
        finally:
            bundled.rmdir()

    def test_bundled_modules_dir_dev_fallback(self) -> None:
        """When bundled_modules/ does not exist but modules/ does, dev fallback is used."""
        from opentree.cli.init import _bundled_modules_dir

        # In our source checkout, bundled_modules/ does not exist but modules/ does
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENTREE_BUNDLE_DIR", None)
            result = _bundled_modules_dir()
        expected = Path(__file__).resolve().parent.parent / "modules"
        assert result == expected

    def test_bundled_modules_dir_not_found(self, tmp_path: Path) -> None:
        """When neither bundled_modules/ nor modules/ exist, FileNotFoundError is raised."""
        import opentree.cli.init as init_mod

        # Place __file__ in a temp location where neither candidate exists
        fake_file = tmp_path / "src" / "opentree" / "cli" / "init.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.touch()

        original_file = init_mod.__file__
        try:
            init_mod.__file__ = str(fake_file)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENTREE_BUNDLE_DIR", None)
                with pytest.raises(FileNotFoundError, match="Cannot find bundled modules"):
                    init_mod._bundled_modules_dir()
        finally:
            init_mod.__file__ = original_file


# ------------------------------------------------------------------
# _resolve_opentree_cmd() auto mode with installed package
# ------------------------------------------------------------------


class TestResolveCmdAutoInstalled:
    """When bundled_modules/ exists, auto mode returns bare command."""

    def test_resolve_cmd_auto_installed(self) -> None:
        """bundled_modules/ exists -> auto returns bare command, no pyproject.toml probe."""
        from opentree.cli.init import _resolve_opentree_cmd

        # Create a fake bundled_modules dir next to the package
        pkg_root = Path(__file__).resolve().parent.parent / "src" / "opentree"
        bundled = pkg_root / "bundled_modules"
        bundled.mkdir(exist_ok=True)
        try:
            with patch("opentree.cli.init.shutil.which", return_value="/usr/local/bin/opentree"):
                cmd, root = _resolve_opentree_cmd("auto")
            assert cmd == "opentree"
            assert root is None
        finally:
            bundled.rmdir()
