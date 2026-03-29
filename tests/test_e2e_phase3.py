"""End-to-end tests for Phase 3: full install flow with placeholder resolution.

Simulates the complete install workflow using a temporary OPENTREE_HOME
with real module files copied from the project. Verifies that:
- Placeholders are resolved in installed rule files
- Symlinks are created for files without placeholders
- CLAUDE.md and settings.json are generated correctly
- Refresh is idempotent and picks up config changes
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from opentree.cli.main import app

runner = CliRunner()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MODULES_SRC = _PROJECT_ROOT / "modules"

# The 7 pre-installed modules
_PREINSTALLED = (
    "core", "personality", "guardrail", "memory",
    "slack", "scheduler", "audit-logger",
)

# The 3 optional modules
_OPTIONAL = ("requirement", "stt", "youtube")

# Installation order respecting dependency graph
_PREINSTALLED_INSTALL_ORDER = (
    "core", "personality", "memory", "slack",
    "guardrail", "scheduler", "audit-logger",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_manifest(home: Path, name: str) -> dict[str, Any]:
    """Read a module manifest."""
    path = home / "modules" / name / "opentree.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _install_module(home: Path, name: str) -> Any:
    """Run 'opentree module install <name>' and return the CLI result."""
    env_patch = {"OPENTREE_HOME": str(home)}
    result = runner.invoke(app, ["module", "install", name], env=env_patch)
    return result


def _count_rule_files(home: Path) -> int:
    """Count .md files under workspace/.claude/rules/."""
    rules_dir = home / "workspace" / ".claude" / "rules"
    if not rules_dir.exists():
        return 0
    return len(list(rules_dir.rglob("*.md")))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def opentree_home(tmp_path: Path) -> Path:
    """Create a temporary OPENTREE_HOME with real module files.

    Copies the entire modules/ directory from the project and creates
    a user config with test values.
    """
    home = tmp_path / "opentree_home"

    # Copy real modules
    shutil.copytree(_MODULES_SRC, home / "modules")

    # Create config directory and user.json
    config_dir = home / "config"
    config_dir.mkdir(parents=True)

    user_config = {
        "bot_name": "Groot",
        "team_name": "AI Team",
        "admin_channel": "C1234",
        "admin_description": "管理團隊",
    }
    (config_dir / "user.json").write_text(
        json.dumps(user_config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Create workspace directory structure
    (home / "workspace" / ".claude" / "rules").mkdir(parents=True)

    return home


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


class TestE2EPhase3:
    """End-to-end tests for the full install flow with placeholder resolution."""

    # 1. Install core, check workspace/.claude/rules/core/*.md exist
    #    with {{opentree_home}} resolved
    def test_install_core_creates_resolved_rules(
        self, opentree_home: Path
    ) -> None:
        """Installing core creates rule files with {{opentree_home}} resolved."""
        result = _install_module(opentree_home, "core")
        assert result.exit_code == 0, f"Install failed: {result.output}"

        core_rules = opentree_home / "workspace" / ".claude" / "rules" / "core"
        assert core_rules.exists(), "core rules directory not created"

        md_files = list(core_rules.glob("*.md"))
        assert len(md_files) >= 1, "No rule files created for core"

        # Check that opentree_home is resolved in files that use it
        home_str = str(opentree_home).replace("\\", "/")
        manifest = _get_manifest(opentree_home, "core")
        has_opentree_home_placeholder = "opentree_home" in manifest.get(
            "placeholders", {}
        )

        if has_opentree_home_placeholder:
            # At least one file should contain the resolved path
            # (or all should have no unresolved {{opentree_home}})
            for md_file in md_files:
                content = md_file.read_text(encoding="utf-8")
                assert "{{opentree_home}}" not in content, (
                    f"File {md_file.name} still has unresolved "
                    f"{{{{opentree_home}}}}"
                )

    # 2. Install personality, check {{bot_name}} resolved to "Groot"
    def test_install_personality_resolves_bot_name(
        self, opentree_home: Path
    ) -> None:
        """Installing personality resolves {{bot_name}} to 'Groot'."""
        # Install dependency first
        _install_module(opentree_home, "core")
        result = _install_module(opentree_home, "personality")
        assert result.exit_code == 0, f"Install failed: {result.output}"

        char_file = (
            opentree_home / "workspace" / ".claude" / "rules"
            / "personality" / "character.md"
        )
        assert char_file.exists(), "character.md not created"

        content = char_file.read_text(encoding="utf-8")
        assert "Groot" in content, (
            "character.md should contain resolved bot_name 'Groot'"
        )
        assert "{{bot_name}}" not in content, (
            "character.md still has unresolved {{bot_name}}"
        )

    # 3. Install all 7 pre-installed, verify 21 rule files
    def test_install_7_preinstalled_all_rules_present(
        self, opentree_home: Path
    ) -> None:
        """Installing all 7 pre-installed modules produces 21 rule files."""
        for name in _PREINSTALLED_INSTALL_ORDER:
            result = _install_module(opentree_home, name)
            assert result.exit_code == 0, (
                f"Install '{name}' failed: {result.output}"
            )

        count = _count_rule_files(opentree_home)
        assert count == 21, (
            f"Expected 21 rule files for 7 pre-installed modules, got {count}"
        )

    # 4. After install, no {{...}} in any file under workspace/.claude/rules/
    def test_resolved_files_no_placeholders(
        self, opentree_home: Path
    ) -> None:
        """After installing all pre-installed modules, no unresolved placeholders remain."""
        for name in _PREINSTALLED_INSTALL_ORDER:
            result = _install_module(opentree_home, name)
            assert result.exit_code == 0, (
                f"Install '{name}' failed: {result.output}"
            )

        placeholder_re = re.compile(r"\{\{[a-z_]+\}\}")
        rules_dir = opentree_home / "workspace" / ".claude" / "rules"

        for md_file in rules_dir.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            found = placeholder_re.findall(content)
            assert not found, (
                f"File {md_file.relative_to(rules_dir)} has unresolved "
                f"placeholder(s): {found}"
            )

    # 5. Files without placeholders are actual symlinks (on Linux)
    def test_symlink_files_are_symlinks(self, opentree_home: Path) -> None:
        """Files without placeholders are created as symlinks (on supported platforms)."""
        if os.name == "nt":
            pytest.skip("Symlink test not reliable on Windows")

        # Install core — some files may not have placeholders
        result = _install_module(opentree_home, "core")
        assert result.exit_code == 0, f"Install failed: {result.output}"

        rules_dir = opentree_home / "workspace" / ".claude" / "rules" / "core"

        # Read source files to find which have no placeholders
        source_dir = opentree_home / "modules" / "core" / "rules"
        has_symlink = False
        has_resolved = False

        for md_file in rules_dir.glob("*.md"):
            source_file = source_dir / md_file.name
            source_content = source_file.read_text(encoding="utf-8")

            if "{{" not in source_content:
                # Should be a symlink
                assert md_file.is_symlink(), (
                    f"{md_file.name} has no placeholders but is not a symlink"
                )
                has_symlink = True
            else:
                # Should be a resolved copy (not a symlink)
                assert not md_file.is_symlink(), (
                    f"{md_file.name} has placeholders but is a symlink "
                    f"(should be a resolved copy)"
                )
                has_resolved = True

        # At least verify we tested something
        assert has_symlink or has_resolved, (
            "No files were checked — core module has no rule files?"
        )

    # 6. workspace/CLAUDE.md exists and < 200 lines
    def test_claude_md_generated_under_200_lines(
        self, opentree_home: Path
    ) -> None:
        """CLAUDE.md is generated and stays under 200 lines."""
        for name in _PREINSTALLED_INSTALL_ORDER:
            _install_module(opentree_home, name)

        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        assert claude_md.exists(), "workspace/CLAUDE.md not generated"

        content = claude_md.read_text(encoding="utf-8")
        line_count = content.count("\n") + 1
        assert line_count < 200, (
            f"CLAUDE.md has {line_count} lines (expected < 200)"
        )

    # 7. workspace/.claude/settings.json has allowedTools/denyTools
    def test_settings_json_has_permissions(
        self, opentree_home: Path
    ) -> None:
        """settings.json is generated with allowedTools and denyTools."""
        for name in _PREINSTALLED_INSTALL_ORDER:
            _install_module(opentree_home, name)

        settings_path = (
            opentree_home / "workspace" / ".claude" / "settings.json"
        )
        assert settings_path.exists(), "settings.json not generated"

        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "allowedTools" in settings, (
            "settings.json missing 'allowedTools' key"
        )
        assert "denyTools" in settings, (
            "settings.json missing 'denyTools' key"
        )
        assert isinstance(settings["allowedTools"], list)
        assert isinstance(settings["denyTools"], list)

        # Slack module adds deny rules
        assert len(settings["denyTools"]) > 0, (
            "Expected at least one deny rule (from slack module)"
        )

    # 8. Refresh is idempotent — install all, refresh, verify same state
    def test_refresh_idempotent(self, opentree_home: Path) -> None:
        """Refreshing after install produces the same state."""
        env_patch = {"OPENTREE_HOME": str(opentree_home)}

        for name in _PREINSTALLED_INSTALL_ORDER:
            _install_module(opentree_home, name)

        # Snapshot state before refresh (exclude .trash/ directory)
        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        before_files = {
            str(f.relative_to(rules_dir)): f.read_text(encoding="utf-8")
            for f in rules_dir.rglob("*.md")
            if ".trash" not in f.relative_to(rules_dir).parts
        }
        before_settings = (
            (opentree_home / "workspace" / ".claude" / "settings.json")
            .read_text(encoding="utf-8")
        )

        # Refresh
        result = runner.invoke(app, ["module", "refresh"], env=env_patch)
        assert result.exit_code == 0, f"Refresh failed: {result.output}"

        # Snapshot state after refresh (exclude .trash/ directory)
        after_files = {
            str(f.relative_to(rules_dir)): f.read_text(encoding="utf-8")
            for f in rules_dir.rglob("*.md")
            if ".trash" not in f.relative_to(rules_dir).parts
        }
        after_settings = (
            (opentree_home / "workspace" / ".claude" / "settings.json")
            .read_text(encoding="utf-8")
        )

        # Compare: same files with same content
        assert set(before_files.keys()) == set(after_files.keys()), (
            f"File sets differ after refresh. "
            f"Before: {sorted(before_files.keys())} "
            f"After: {sorted(after_files.keys())}"
        )
        for filename in before_files:
            assert before_files[filename] == after_files[filename], (
                f"File content changed after refresh: {filename}"
            )
        assert before_settings == after_settings, (
            "settings.json content changed after refresh"
        )

    # 9. Change user.json bot_name, refresh, verify new value in rules
    def test_refresh_updates_resolved_values(
        self, opentree_home: Path
    ) -> None:
        """Refreshing after changing user.json updates resolved values."""
        env_patch = {"OPENTREE_HOME": str(opentree_home)}

        # Install core + personality
        _install_module(opentree_home, "core")
        _install_module(opentree_home, "personality")

        # Verify initial value
        char_file = (
            opentree_home / "workspace" / ".claude" / "rules"
            / "personality" / "character.md"
        )
        content_before = char_file.read_text(encoding="utf-8")
        assert "Groot" in content_before

        # Change bot_name in user.json
        config_path = opentree_home / "config" / "user.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["bot_name"] = "Rocket"
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Refresh
        result = runner.invoke(app, ["module", "refresh"], env=env_patch)
        assert result.exit_code == 0, f"Refresh failed: {result.output}"

        # Verify updated value
        content_after = char_file.read_text(encoding="utf-8")
        assert "Rocket" in content_after, (
            "character.md should contain new bot_name 'Rocket' after refresh"
        )
        assert "Groot" not in content_after, (
            "character.md still contains old bot_name 'Groot' after refresh"
        )

    # 10. Install optional youtube on top, verify 23 rule files total
    def test_install_optional_youtube(self, opentree_home: Path) -> None:
        """Installing youtube on top of pre-installed modules adds 2 more rule files."""
        # Install all pre-installed first
        for name in _PREINSTALLED_INSTALL_ORDER:
            result = _install_module(opentree_home, name)
            assert result.exit_code == 0, (
                f"Install '{name}' failed: {result.output}"
            )

        pre_count = _count_rule_files(opentree_home)
        assert pre_count == 21, (
            f"Expected 21 rules before youtube, got {pre_count}"
        )

        # Install youtube
        result = _install_module(opentree_home, "youtube")
        assert result.exit_code == 0, (
            f"Install youtube failed: {result.output}"
        )

        post_count = _count_rule_files(opentree_home)
        assert post_count == 23, (
            f"Expected 23 rules after youtube install, got {post_count}"
        )
