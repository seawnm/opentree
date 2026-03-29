"""Tests for the OpenTree CLI (module install, remove, list, refresh).

Uses typer.testing.CliRunner with a temporary OPENTREE_HOME directory
containing sample module manifests and rule files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from opentree.cli.main import app

runner = CliRunner()


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _write_manifest(module_dir: Path, manifest: dict[str, Any]) -> None:
    """Write a manifest to <module_dir>/opentree.json."""
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "opentree.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _write_rules(module_dir: Path, rules: list[str]) -> None:
    """Create dummy rule files under <module_dir>/rules/."""
    rules_dir = module_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    for rule in rules:
        (rules_dir / rule).write_text(f"# {rule}\n", encoding="utf-8")


def _core_manifest() -> dict[str, Any]:
    return {
        "name": "core",
        "version": "1.0.0",
        "description": "Core routing and path conventions",
        "type": "pre-installed",
        "depends_on": [],
        "conflicts_with": [],
        "loading": {"rules": ["routing.md"]},
        "triggers": {
            "keywords": ["path", "config"],
            "description": "Core routing rules",
        },
        "permissions": {"allow": [], "deny": []},
    }


def _youtube_manifest() -> dict[str, Any]:
    return {
        "name": "youtube",
        "version": "1.0.0",
        "description": "YouTube video library",
        "type": "optional",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["youtube-tool.md"]},
        "triggers": {
            "keywords": ["YouTube"],
            "description": "YouTube search and fetch",
        },
        "permissions": {"allow": ["Bash(alloy youtube:*)"], "deny": []},
    }


def _slack_manifest() -> dict[str, Any]:
    return {
        "name": "slack",
        "version": "1.0.0",
        "description": "Slack integration",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["message-rules.md"]},
        "triggers": {
            "keywords": ["Slack"],
            "description": "Slack messaging",
        },
        "permissions": {
            "allow": ["Bash(uv run:*upload*)"],
            "deny": ["mcp__slack_send"],
        },
    }


def _requirement_manifest() -> dict[str, Any]:
    return {
        "name": "requirement",
        "version": "1.0.0",
        "description": "Requirement management",
        "type": "optional",
        "depends_on": ["slack"],
        "conflicts_with": [],
        "loading": {"rules": ["requirement-tool.md"]},
        "triggers": {
            "keywords": ["requirement"],
            "description": "Requirement CRUD",
        },
        "permissions": {"allow": [], "deny": []},
    }


@pytest.fixture()
def opentree_home(tmp_path: Path) -> Path:
    """Build a minimal OPENTREE_HOME with core + youtube + slack + requirement modules."""
    home = tmp_path / "opentree_home"

    # Directories
    (home / "config").mkdir(parents=True)
    (home / "workspace" / ".claude" / "rules").mkdir(parents=True)
    (home / "workspace" / ".claude").mkdir(parents=True, exist_ok=True)

    # User config
    user_config = {
        "bot_name": "TestBot",
        "team_name": "TestTeam",
        "admin_channel": "C123",
    }
    (home / "config" / "user.json").write_text(
        json.dumps(user_config), encoding="utf-8"
    )

    # Modules
    for name, manifest_fn, rules in [
        ("core", _core_manifest, ["routing.md"]),
        ("youtube", _youtube_manifest, ["youtube-tool.md"]),
        ("slack", _slack_manifest, ["message-rules.md"]),
        ("requirement", _requirement_manifest, ["requirement-tool.md"]),
    ]:
        mod_dir = home / "modules" / name
        _write_manifest(mod_dir, manifest_fn())
        _write_rules(mod_dir, rules)

    # Pre-install core and slack in registry (they are pre-installed)
    registry = {
        "version": 1,
        "modules": {
            "core": {
                "name": "core",
                "version": "1.0.0",
                "module_type": "pre-installed",
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "bundled",
                "link_method": "symlink",
                "depends_on": [],
            },
            "slack": {
                "name": "slack",
                "version": "1.0.0",
                "module_type": "pre-installed",
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "bundled",
                "link_method": "symlink",
                "depends_on": ["core"],
            },
        },
    }
    (home / "config" / "registry.json").write_text(
        json.dumps(registry, indent=2), encoding="utf-8"
    )

    return home


# ------------------------------------------------------------------
# Install tests
# ------------------------------------------------------------------


class TestInstall:
    """opentree module install tests."""

    def test_install_module(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Install an optional module succeeds and registers it."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "youtube"])

        assert result.exit_code == 0, result.output
        assert "Installed module 'youtube'" in result.output

        # Verify registered
        reg = json.loads(
            (opentree_home / "config" / "registry.json").read_text(encoding="utf-8")
        )
        assert "youtube" in reg["modules"]
        assert reg["modules"]["youtube"]["version"] == "1.0.0"
        assert reg["modules"]["youtube"]["depends_on"] == ["core"]

    def test_install_already_installed(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Installing an already-installed module errors out."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "core"])

        assert result.exit_code == 1
        assert "already installed" in result.output

    def test_install_missing_dependency(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Installing a module whose dependency is not installed fails."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Remove slack from registry so requirement's dep is missing
        reg_path = opentree_home / "config" / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        del reg["modules"]["slack"]
        reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        result = runner.invoke(app, ["module", "install", "requirement"])

        assert result.exit_code == 1
        assert "slack" in result.output
        assert "not installed" in result.output

    def test_install_invalid_manifest(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Installing a module with a schema-invalid manifest fails."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Create a broken manifest (missing required fields)
        bad_dir = opentree_home / "modules" / "broken"
        bad_dir.mkdir(parents=True)
        (bad_dir / "opentree.json").write_text(
            json.dumps({"name": "broken"}), encoding="utf-8"
        )
        (bad_dir / "rules").mkdir()

        result = runner.invoke(app, ["module", "install", "broken"])

        assert result.exit_code == 1
        assert "Invalid manifest" in result.output

    def test_install_creates_all_artifacts(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After install, CLAUDE.md + symlinks + settings.json all exist."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "youtube"])
        assert result.exit_code == 0, result.output

        # CLAUDE.md exists
        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text(encoding="utf-8")
        assert "youtube" in content

        # Symlink dir exists
        rules_dir = opentree_home / "workspace" / ".claude" / "rules" / "youtube"
        assert rules_dir.exists()

        # Settings.json exists with youtube permissions
        settings = json.loads(
            (opentree_home / "workspace" / ".claude" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert "Bash(alloy youtube:*)" in settings["allowedTools"]


# ------------------------------------------------------------------
# Remove tests
# ------------------------------------------------------------------


class TestRemove:
    """opentree module remove tests."""

    def test_remove_optional_module(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Remove an optional module succeeds."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Install youtube first
        runner.invoke(app, ["module", "install", "youtube"])

        result = runner.invoke(app, ["module", "remove", "youtube"])

        assert result.exit_code == 0, result.output
        assert "Removed module 'youtube'" in result.output

        # Verify unregistered
        reg = json.loads(
            (opentree_home / "config" / "registry.json").read_text(encoding="utf-8")
        )
        assert "youtube" not in reg["modules"]

    def test_remove_preinstalled_blocked(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Removing a pre-installed module is blocked."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "remove", "core"])

        assert result.exit_code == 1
        assert "pre-installed" in result.output

    def test_remove_with_reverse_deps(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cannot remove a module that other modules depend on."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Install requirement (depends on slack)
        runner.invoke(app, ["module", "install", "requirement"])

        result = runner.invoke(app, ["module", "remove", "slack", "--force"])

        assert result.exit_code == 1
        assert "requirement" in result.output
        assert "depend on it" in result.output

    def test_remove_not_installed(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Removing a module that is not installed fails."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "remove", "nonexistent"])

        assert result.exit_code == 1
        assert "not installed" in result.output


# ------------------------------------------------------------------
# List tests
# ------------------------------------------------------------------


class TestList:
    """opentree module list tests."""

    def test_list_modules(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """List shows all installed modules in a table."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "list"])

        assert result.exit_code == 0
        assert "core" in result.output
        assert "slack" in result.output
        assert "pre-installed" in result.output


# ------------------------------------------------------------------
# Refresh tests
# ------------------------------------------------------------------


class TestRefresh:
    """opentree module refresh tests."""

    def test_refresh_regenerates(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refresh regenerates all artifacts."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Create initial symlinks for pre-installed modules
        # (In real usage, init would do this; here we set up manually)
        # First, set up permissions so settings.json exists
        settings_gen = __import__(
            "opentree.generator.settings", fromlist=["SettingsGenerator"]
        ).SettingsGenerator(opentree_home)
        settings_gen.add_module_permissions("core", allow=[], deny=[])
        settings_gen.add_module_permissions(
            "slack",
            allow=["Bash(uv run:*upload*)"],
            deny=["mcp__slack_send"],
        )
        settings_gen.write_settings()

        result = runner.invoke(app, ["module", "refresh"])

        assert result.exit_code == 0, result.output
        assert "Refresh complete" in result.output

        # Verify CLAUDE.md regenerated
        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists()

        # Verify settings.json exists
        settings_path = opentree_home / "workspace" / ".claude" / "settings.json"
        assert settings_path.exists()

        # Verify symlinks recreated
        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        assert (rules_dir / "core").exists()
        assert (rules_dir / "slack").exists()


# ------------------------------------------------------------------
# OPENTREE_HOME env var test
# ------------------------------------------------------------------


class TestOpentreeHome:
    """OPENTREE_HOME environment variable resolution."""

    def test_opentree_home_from_env(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPENTREE_HOME env var directs CLI to the correct directory."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "list"])

        assert result.exit_code == 0
        # The modules from our fixture should appear
        assert "core" in result.output


# ------------------------------------------------------------------
# Path traversal prevention tests (Fix 1)
# ------------------------------------------------------------------


class TestPathTraversal:
    """Module name validation rejects path traversal attempts."""

    def test_install_path_traversal_rejected(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install rejects names containing path traversal sequences."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "../../../evil"])

        assert result.exit_code == 1
        assert "Invalid module name" in result.output

    def test_remove_path_traversal_rejected(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """remove rejects names containing path traversal sequences."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "remove", "../../../evil"])

        assert result.exit_code == 1
        assert "Invalid module name" in result.output

    def test_install_rejects_uppercase(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install rejects names with uppercase letters."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "Evil"])

        assert result.exit_code == 1
        assert "Invalid module name" in result.output

    def test_install_rejects_trailing_hyphen(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install rejects names ending with a hyphen."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        result = runner.invoke(app, ["module", "install", "bad-"])

        assert result.exit_code == 1
        assert "Invalid module name" in result.output


# ------------------------------------------------------------------
# Refresh clears stale permissions test (Fix 4)
# ------------------------------------------------------------------


class TestRefreshStalePermissions:
    """refresh clears permissions for modules no longer in registry."""

    def test_refresh_clears_stale_permissions(
        self, opentree_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale module permissions are removed on refresh."""
        monkeypatch.setenv("OPENTREE_HOME", str(opentree_home))

        # Install youtube (adds permissions)
        result = runner.invoke(app, ["module", "install", "youtube"])
        assert result.exit_code == 0, result.output

        # Verify youtube permissions exist
        perms_path = opentree_home / "config" / "permissions.json"
        perms = json.loads(perms_path.read_text(encoding="utf-8"))
        assert "youtube" in perms["modules"]

        # Manually remove youtube from registry only (simulate stale state)
        reg_path = opentree_home / "config" / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        del reg["modules"]["youtube"]
        reg_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        # Run refresh
        result = runner.invoke(app, ["module", "refresh"])
        assert result.exit_code == 0, result.output

        # Verify youtube permissions are gone
        perms = json.loads(perms_path.read_text(encoding="utf-8"))
        assert "youtube" not in perms["modules"]

        # Verify core and slack permissions still exist
        assert "core" in perms["modules"]
        assert "slack" in perms["modules"]
