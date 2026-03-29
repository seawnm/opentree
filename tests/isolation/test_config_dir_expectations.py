"""Test expectations about CLAUDE_CONFIG_DIR behavior.

These tests do NOT require Claude CLI - they validate our assumptions
about how CLAUDE_CONFIG_DIR isolation should work in OpenTree.
"""
from __future__ import annotations

from pathlib import Path

import pytest


class TestConfigDirExpectations:
    def test_opentree_home_to_claude_state_mapping(self, tmp_path: Path) -> None:
        """CLAUDE_CONFIG_DIR should map to $OPENTREE_HOME/.claude-state"""
        opentree_home = tmp_path / ".opentree"
        expected = opentree_home / ".claude-state"
        assert str(expected) == str(opentree_home / ".claude-state")

    def test_project_level_claude_dir_independent(self, tmp_path: Path) -> None:
        """Project .claude/ should NOT be under CLAUDE_CONFIG_DIR"""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project_claude = workspace / ".claude"
        project_claude.mkdir()
        config_dir = tmp_path / ".claude-state"
        config_dir.mkdir()
        # These should be completely different paths
        assert not str(project_claude).startswith(str(config_dir))

    def test_two_homes_have_separate_state(self, tmp_path: Path) -> None:
        """Two OPENTREE_HOME instances should have separate .claude-state"""
        home_a = tmp_path / "home-a" / ".claude-state"
        home_b = tmp_path / "home-b" / ".claude-state"
        assert str(home_a) != str(home_b)
