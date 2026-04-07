"""Tests for reset helpers — written FIRST (TDD Red phase).

Tests two reset levels:
- reset_bot(): Soft reset (regenerate settings/symlinks/CLAUDE.md; session clearing is caller's responsibility)
- reset_bot_all(): Hard reset (clear customizations + data, regenerate)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opentree.runner.reset import reset_bot, reset_bot_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_opentree_home(home: Path, *, with_manifest: bool = True) -> None:
    """Create minimal directory structure for an OpenTree instance."""
    # config/
    config_dir = home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # config/user.json
    user_config = {
        "bot_name": "TestBot",
        "team_name": "TestTeam",
        "admin_channel": "C12345",
        "owner_description": "Test owner",
    }
    (config_dir / "user.json").write_text(
        json.dumps(user_config), encoding="utf-8"
    )

    # config/registry.json
    registry = {
        "version": 1,
        "modules": {
            "test-mod": {
                "name": "test-mod",
                "version": "1.0.0",
                "module_type": "pre-installed",
                "installed_at": "2026-01-01T00:00:00+00:00",
                "source": "bundled",
                "link_method": "copy",
            }
        },
    }
    (config_dir / "registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )

    # modules/test-mod/
    mod_dir = home / "modules" / "test-mod"
    mod_dir.mkdir(parents=True, exist_ok=True)

    if with_manifest:
        manifest: dict[str, Any] = {
            "name": "test-mod",
            "version": "1.0.0",
            "description": "A test module",
            "type": "pre-installed",
            "loading": {"rules": ["rule.md"]},
            "permissions": {
                "allow": ["Bash(echo:*)"],
                "deny": [],
            },
        }
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        rules_dir = mod_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "rule.md").write_text("# Test Rule\n", encoding="utf-8")

    # workspace/.claude/
    workspace_claude = home / "workspace" / ".claude"
    workspace_claude.mkdir(parents=True, exist_ok=True)

    # data/
    data_dir = home / "data"
    data_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# TestResetBot
# ---------------------------------------------------------------------------

class TestResetBot:
    def test_regenerates_settings(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        actions = reset_bot(home)

        assert any("settings" in a.lower() for a in actions)
        # settings.json should exist (primary output of SettingsGenerator)
        assert (home / "workspace" / ".claude" / "settings.json").exists()
        # permissions.json should exist (created by SettingsGenerator)
        assert (home / "config" / "permissions.json").exists()

    def test_regenerates_claude_md_with_preservation(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        # Write existing CLAUDE.md with owner content
        claude_md_path = home / "workspace" / "CLAUDE.md"
        claude_md_path.write_text(
            "<!-- OPENTREE:AUTO:BEGIN -->\nold auto\n<!-- OPENTREE:AUTO:END -->\n"
            "\n## My Custom Notes\nKeep this!\n",
            encoding="utf-8",
        )

        actions = reset_bot(home)

        assert any("CLAUDE.md" in a for a in actions)
        content = claude_md_path.read_text(encoding="utf-8")
        # Owner content should be preserved
        assert "My Custom Notes" in content
        assert "Keep this!" in content
        # Auto block should be regenerated (no longer contains "old auto")
        assert "old auto" not in content

    def test_returns_action_list(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        actions = reset_bot(home)

        assert isinstance(actions, list)
        assert len(actions) > 0
        assert all(isinstance(a, str) for a in actions)

    def test_best_effort_on_failure(self, tmp_path: Path):
        """If one step fails, other steps still proceed."""
        home = tmp_path / "ot"
        _setup_opentree_home(home, with_manifest=False)

        # Even without a manifest, should not raise — best-effort
        actions = reset_bot(home)

        assert isinstance(actions, list)
        assert len(actions) > 0

    def test_raises_if_no_registry(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)
        # Delete registry
        (home / "config" / "registry.json").unlink()

        with pytest.raises(RuntimeError, match="Registry not found"):
            reset_bot(home)


# ---------------------------------------------------------------------------
# TestResetBotAll
# ---------------------------------------------------------------------------

class TestResetBotAll:
    def test_deletes_env_local(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)
        env_local = home / "config" / ".env.local"
        env_local.write_text("LOCAL_KEY=val\n", encoding="utf-8")

        reset_bot_all(home)

        assert not env_local.exists()

    def test_deletes_env_secrets(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)
        env_secrets = home / "config" / ".env.secrets"
        env_secrets.write_text("SECRET_KEY=val\n", encoding="utf-8")

        reset_bot_all(home)

        assert not env_secrets.exists()

    def test_preserves_env_defaults(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)
        env_defaults = home / "config" / ".env.defaults"
        env_defaults.write_text("DEFAULT_KEY=val\n", encoding="utf-8")

        reset_bot_all(home)

        assert env_defaults.exists()
        assert env_defaults.read_text(encoding="utf-8") == "DEFAULT_KEY=val\n"

    def test_clears_data_contents(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        # Create files and subdirs in data/
        (home / "data" / "sessions.json").write_text("{}", encoding="utf-8")
        sub = home / "data" / "memory"
        sub.mkdir()
        (sub / "notes.md").write_text("# Notes\n", encoding="utf-8")

        reset_bot_all(home)

        # data/ directory contents should be cleared
        remaining = list((home / "data").iterdir())
        assert remaining == []

    def test_preserves_data_directory(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        (home / "data" / "sessions.json").write_text("{}", encoding="utf-8")

        reset_bot_all(home)

        assert (home / "data").exists()
        assert (home / "data").is_dir()

    def test_regenerates_claude_md_without_preservation(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        claude_md_path = home / "workspace" / "CLAUDE.md"
        claude_md_path.write_text(
            "<!-- OPENTREE:AUTO:BEGIN -->\nold auto\n<!-- OPENTREE:AUTO:END -->\n"
            "\n## My Custom Notes\nOwner content\n",
            encoding="utf-8",
        )

        reset_bot_all(home)

        content = claude_md_path.read_text(encoding="utf-8")
        # Owner content should NOT be preserved in hard reset
        assert "My Custom Notes" not in content
        assert "Owner content" not in content
        # Auto block should be fresh
        assert "<!-- OPENTREE:AUTO:BEGIN -->" in content

    def test_returns_action_list(self, tmp_path: Path):
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        actions = reset_bot_all(home)

        assert isinstance(actions, list)
        assert len(actions) > 0
        assert all(isinstance(a, str) for a in actions)

    def test_handles_missing_env_files_gracefully(self, tmp_path: Path):
        """Should not fail if .env.local and .env.secrets don't exist."""
        home = tmp_path / "ot"
        _setup_opentree_home(home)

        # No .env.local or .env.secrets — should not raise
        actions = reset_bot_all(home)
        assert isinstance(actions, list)

    def test_handles_missing_registry(self, tmp_path: Path):
        """Without registry, should skip regeneration but not crash."""
        home = tmp_path / "ot"
        _setup_opentree_home(home)
        (home / "config" / "registry.json").unlink()

        actions = reset_bot_all(home)

        assert any("Registry not found" in a for a in actions)
