"""Tests for the SettingsGenerator.

Covers:
- Add module permissions: single / multiple modules
- Remove module permissions: existing / nonexistent (idempotent)
- Generate settings: aggregate / deduplicate / deny / empty / user_custom
- Placeholder resolution: $OPENTREE_HOME / backslash normalization
- Write settings: atomic / auto-create dirs
- Output format: settings["permissions"]["allow"] / settings["permissions"]["deny"]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentree.generator.settings import PermissionSet, SettingsGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def opentree_home(tmp_path: Path) -> Path:
    """Create a temporary OPENTREE_HOME directory structure."""
    (tmp_path / "config").mkdir()
    (tmp_path / "workspace").mkdir()
    return tmp_path


@pytest.fixture()
def generator(opentree_home: Path) -> SettingsGenerator:
    """Create a SettingsGenerator with a temporary OPENTREE_HOME."""
    return SettingsGenerator(opentree_home)


# ---------------------------------------------------------------------------
# Add module permissions
# ---------------------------------------------------------------------------

class TestAddModulePermissions:
    """SettingsGenerator.add_module_permissions() tests."""

    def test_add_module_permissions(
        self, generator: SettingsGenerator, opentree_home: Path
    ) -> None:
        """Adding a module records its allow/deny in permissions.json."""
        generator.add_module_permissions(
            "slack",
            allow=["Bash(uv run:*upload*)"],
            deny=["mcp__slack_send"],
        )

        perm_path = opentree_home / "config" / "permissions.json"
        assert perm_path.exists()
        data = json.loads(perm_path.read_text(encoding="utf-8"))
        assert "slack" in data["modules"]
        assert data["modules"]["slack"]["allow"] == ["Bash(uv run:*upload*)"]
        assert data["modules"]["slack"]["deny"] == ["mcp__slack_send"]

    def test_add_multiple_modules(
        self, generator: SettingsGenerator, opentree_home: Path
    ) -> None:
        """Two modules coexist in permissions.json without interfering."""
        generator.add_module_permissions(
            "slack",
            allow=["Bash(uv run:*upload*)"],
            deny=["mcp__slack_send"],
        )
        generator.add_module_permissions(
            "scheduler",
            allow=["Bash(uv run:*schedule*)"],
            deny=[],
        )

        perm_path = opentree_home / "config" / "permissions.json"
        data = json.loads(perm_path.read_text(encoding="utf-8"))
        assert "slack" in data["modules"]
        assert "scheduler" in data["modules"]
        assert data["modules"]["slack"]["allow"] == ["Bash(uv run:*upload*)"]
        assert data["modules"]["scheduler"]["allow"] == ["Bash(uv run:*schedule*)"]


# ---------------------------------------------------------------------------
# Remove module permissions
# ---------------------------------------------------------------------------

class TestRemoveModulePermissions:
    """SettingsGenerator.remove_module_permissions() tests."""

    def test_remove_module_permissions(
        self, generator: SettingsGenerator, opentree_home: Path
    ) -> None:
        """Removing a module deletes only that module's entry."""
        generator.add_module_permissions(
            "slack", allow=["Bash(uv run:*upload*)"], deny=[]
        )
        generator.add_module_permissions(
            "scheduler", allow=["Bash(uv run:*schedule*)"], deny=[]
        )

        generator.remove_module_permissions("slack")

        perm_path = opentree_home / "config" / "permissions.json"
        data = json.loads(perm_path.read_text(encoding="utf-8"))
        assert "slack" not in data["modules"]
        assert "scheduler" in data["modules"]

    def test_remove_nonexistent_module(self, generator: SettingsGenerator) -> None:
        """Removing a module that was never added does not raise (idempotent)."""
        # Should not raise
        generator.remove_module_permissions("nonexistent")


# ---------------------------------------------------------------------------
# Generate settings
# ---------------------------------------------------------------------------

class TestGenerateSettings:
    """SettingsGenerator.generate_settings() tests."""

    def test_generate_settings_top_level_key_is_permissions(
        self, generator: SettingsGenerator
    ) -> None:
        """generate_settings() returns {"permissions": {"allow": [...], "deny": [...]}}."""
        generator.add_module_permissions(
            "slack", allow=["Bash(uv run:*upload*)"], deny=["mcp__slack_send"]
        )

        settings = generator.generate_settings()

        assert "permissions" in settings, (
            "Top-level key must be 'permissions', not 'allowedTools'/'denyTools'"
        )
        assert "allow" in settings["permissions"]
        assert "deny" in settings["permissions"]
        # Old keys must NOT be present
        assert "allowedTools" not in settings
        assert "denyTools" not in settings

    def test_generate_settings_aggregates(self, generator: SettingsGenerator) -> None:
        """Merges allow patterns from two modules into a single list."""
        generator.add_module_permissions(
            "slack", allow=["Bash(uv run:*upload*)"], deny=[]
        )
        generator.add_module_permissions(
            "scheduler", allow=["Bash(uv run:*schedule*)"], deny=[]
        )

        settings = generator.generate_settings()

        assert "Bash(uv run:*upload*)" in settings["permissions"]["allow"]
        assert "Bash(uv run:*schedule*)" in settings["permissions"]["allow"]

    def test_generate_settings_deduplicates(self, generator: SettingsGenerator) -> None:
        """Same pattern from two modules appears only once."""
        generator.add_module_permissions(
            "slack", allow=["Bash(echo:*)"], deny=[]
        )
        generator.add_module_permissions(
            "scheduler", allow=["Bash(echo:*)"], deny=[]
        )

        settings = generator.generate_settings()

        assert settings["permissions"]["allow"].count("Bash(echo:*)") == 1

    def test_generate_settings_deny_included(self, generator: SettingsGenerator) -> None:
        """Deny patterns appear in settings["permissions"]["deny"]."""
        generator.add_module_permissions(
            "slack",
            allow=["Bash(uv run:*upload*)"],
            deny=["mcp__slack_send", "mcp__slack_draft"],
        )

        settings = generator.generate_settings()

        assert "mcp__slack_send" in settings["permissions"]["deny"]
        assert "mcp__slack_draft" in settings["permissions"]["deny"]

    def test_generate_empty_permissions(self, generator: SettingsGenerator) -> None:
        """No modules installed produces empty arrays in permissions."""
        settings = generator.generate_settings()

        assert settings["permissions"]["allow"] == []
        assert settings["permissions"]["deny"] == []

    def test_generate_user_custom_in_permissions(
        self, generator: SettingsGenerator, opentree_home: Path
    ) -> None:
        """user_custom entries appear in settings["permissions"]."""
        # Pre-populate permissions.json with user_custom entries
        perm_path = opentree_home / "config" / "permissions.json"
        import json as _json
        perm_data = {
            "version": 1,
            "modules": {},
            "user_custom": {
                "allow": ["Bash(custom:*)"],
                "deny": ["mcp__dangerous"],
            },
        }
        perm_path.write_text(_json.dumps(perm_data), encoding="utf-8")

        settings = generator.generate_settings()

        assert "Bash(custom:*)" in settings["permissions"]["allow"]
        assert "mcp__dangerous" in settings["permissions"]["deny"]


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------

class TestPlaceholderResolution:
    """Placeholder substitution in permission patterns."""

    def test_resolve_opentree_home_placeholder(
        self, opentree_home: Path
    ) -> None:
        """$OPENTREE_HOME in patterns is replaced with the actual path."""
        gen = SettingsGenerator(opentree_home)
        gen.add_module_permissions(
            "slack",
            allow=["Bash(uv run --directory $OPENTREE_HOME/bin:*upload*)"],
            deny=[],
        )

        settings = gen.generate_settings()

        expected = f"Bash(uv run --directory {opentree_home}/bin:*upload*)"
        assert expected in settings["permissions"]["allow"]
        assert "$OPENTREE_HOME" not in settings["permissions"]["allow"][0]

    def test_resolve_backslash_normalized(self, tmp_path: Path) -> None:
        r"""Windows-style backslashes in opentree_home are normalized to forward slashes."""
        fake_home = tmp_path / "fake_home"
        (fake_home / "config").mkdir(parents=True)
        (fake_home / "workspace").mkdir(parents=True)

        gen = SettingsGenerator(fake_home)
        gen.add_module_permissions(
            "slack",
            allow=["Bash(uv run --directory $OPENTREE_HOME/bin:*upload*)"],
            deny=[],
        )

        settings = gen.generate_settings()

        # No backslashes in the resolved path
        for pattern in settings["permissions"]["allow"]:
            assert "\\" not in pattern


# ---------------------------------------------------------------------------
# Write settings
# ---------------------------------------------------------------------------

class TestWriteSettings:
    """SettingsGenerator.write_settings() tests."""

    def test_write_settings_atomic(
        self, generator: SettingsGenerator, opentree_home: Path
    ) -> None:
        """settings.json is written with no leftover .tmp files."""
        generator.add_module_permissions(
            "slack", allow=["Bash(uv run:*upload*)"], deny=["mcp__slack_send"]
        )

        generator.write_settings()

        settings_path = opentree_home / "workspace" / ".claude" / "settings.json"
        assert settings_path.exists()
        content = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "Bash(uv run:*upload*)" in content["permissions"]["allow"]
        assert "mcp__slack_send" in content["permissions"]["deny"]

        # No leftover .tmp files
        tmp_files = list(settings_path.parent.glob("*.tmp"))
        assert tmp_files == []

    def test_write_settings_creates_dirs(
        self, opentree_home: Path
    ) -> None:
        """.claude/ directory is auto-created if it does not exist."""
        claude_dir = opentree_home / "workspace" / ".claude"
        assert not claude_dir.exists()

        gen = SettingsGenerator(opentree_home)
        gen.write_settings()

        assert claude_dir.exists()
        settings_path = claude_dir / "settings.json"
        assert settings_path.exists()


# ---------------------------------------------------------------------------
# PermissionSet
# ---------------------------------------------------------------------------

class TestPermissionSet:
    """PermissionSet frozen dataclass tests."""

    def test_permission_set_frozen(self) -> None:
        """PermissionSet is immutable (frozen=True)."""
        ps = PermissionSet(allow=("a", "b"), deny=("c",))
        with pytest.raises(AttributeError):
            ps.allow = ("x",)  # type: ignore[misc]

    def test_permission_set_defaults(self) -> None:
        """Default PermissionSet has empty tuples."""
        ps = PermissionSet()
        assert ps.allow == ()
        assert ps.deny == ()
