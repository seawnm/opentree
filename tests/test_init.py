"""Tests for opentree init and start commands.

Uses typer.testing.CliRunner with a temporary OPENTREE_HOME and
OPENTREE_BUNDLE_DIR pointing to the project's real modules/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

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
            ["init", "--non-interactive", "--admin-channel", "C123"],
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
                "--admin-channel", "C999",
            ],
        )
        assert result.exit_code == 0, result.output

        user_json = json.loads(
            (opentree_home / "config" / "user.json").read_text(encoding="utf-8")
        )
        assert user_json["bot_name"] == "MyBot"
        assert user_json["team_name"] == "MyTeam"
        assert user_json["admin_channel"] == "C999"

    def test_init_non_interactive_defaults(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        assert result.exit_code == 0, result.output

        user_json = json.loads(
            (opentree_home / "config" / "user.json").read_text(encoding="utf-8")
        )
        assert user_json["bot_name"] == "OpenTree"


# ------------------------------------------------------------------
# init: module copying and installation
# ------------------------------------------------------------------


class TestInitModules:
    """opentree init copies bundled modules and installs pre-installed set."""

    def test_init_copies_bundled_modules(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
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
            ["init", "--non-interactive", "--admin-channel", "C123"],
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
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        assert result.exit_code == 0, result.output

        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        md_files = list(rules_dir.rglob("*.md"))
        assert len(md_files) == 21

    def test_init_generates_claude_md(self, opentree_home: Path) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
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
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        assert result.exit_code == 0, result.output

        # Second init without --force
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        assert result.exit_code == 1
        assert "Already initialized" in result.output

    def test_init_force_reinitializes(self, opentree_home: Path) -> None:
        # First init
        runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        # Second init with --force
        result = runner.invoke(
            app,
            [
                "init", "--non-interactive", "--force",
                "--admin-channel", "C123", "--bot-name", "NewBot",
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

    def test_init_preflight_fails_without_admin_channel(
        self, opentree_home: Path
    ) -> None:
        """guardrail requires admin_channel; omitting it fails pre-flight."""
        result = runner.invoke(
            app,
            ["init", "--non-interactive"],
        )
        assert result.exit_code == 1
        assert "guardrail" in result.output
        assert "admin_channel" in result.output

    def test_init_with_admin_channel_succeeds(
        self, opentree_home: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        assert result.exit_code == 0, result.output
        assert "Initialized" in result.output


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
            ["init", "--non-interactive", "--admin-channel", "C123"],
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
            ["init", "--non-interactive", "--admin-channel", "C123"],
        )
        result = runner.invoke(app, ["start", "--dry-run", "--isolate"])
        assert result.exit_code == 0, result.output
        assert "CLAUDE_CONFIG_DIR" in result.output
