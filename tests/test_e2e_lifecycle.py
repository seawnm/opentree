"""End-to-end lifecycle tests for OpenTree.

Each test exercises the full pipeline: init -> module operations ->
start, using the real bundled modules directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentree.cli.main import app

runner = CliRunner()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUNDLE_DIR = _PROJECT_ROOT / "modules"


@pytest.fixture()
def opentree_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh OPENTREE_HOME with BUNDLE_DIR pointing to real modules."""
    home = tmp_path / "opentree_home"
    monkeypatch.setenv("OPENTREE_HOME", str(home))
    monkeypatch.setenv("OPENTREE_BUNDLE_DIR", str(_BUNDLE_DIR))
    return home


def _init(extra_args: list[str] | None = None) -> None:
    """Run init with standard flags; assert success."""
    args = ["init", "--non-interactive", "--bot-name", "TestBot", "--admin-users", "U0TEST123"]
    if extra_args:
        args.extend(extra_args)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


# ------------------------------------------------------------------
# Full lifecycle
# ------------------------------------------------------------------


class TestFullLifecycle:
    """init -> install optional -> remove optional -> start --dry-run."""

    def test_full_lifecycle(self, opentree_home: Path) -> None:
        # 1. Init
        _init()

        # 2. Install youtube (optional)
        result = runner.invoke(app, ["module", "install", "youtube"])
        assert result.exit_code == 0, result.output
        assert "Installed module 'youtube'" in result.output

        reg = json.loads(
            (opentree_home / "config" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        assert "youtube" in reg["modules"]

        # 3. Remove youtube
        result = runner.invoke(app, ["module", "remove", "youtube"])
        assert result.exit_code == 0, result.output

        reg = json.loads(
            (opentree_home / "config" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        assert "youtube" not in reg["modules"]

        # 4. start --dry-run
        result = runner.invoke(app, ["start", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "claude" in result.output


# ------------------------------------------------------------------
# Install all optional modules
# ------------------------------------------------------------------


class TestInstallAllOptional:
    """After init + all optionals, total rules = 28."""

    def test_init_then_install_all_optional(
        self, opentree_home: Path
    ) -> None:
        _init()

        # Install all 3 optional modules
        for name in ("youtube", "stt", "requirement"):
            result = runner.invoke(app, ["module", "install", name])
            assert result.exit_code == 0, result.output

        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        md_files = list(rules_dir.rglob("*.md"))
        assert len(md_files) == 28


# ------------------------------------------------------------------
# Refresh idempotency
# ------------------------------------------------------------------


class TestRefreshIdempotent:
    """Refresh after init does not change state."""

    def test_init_refresh_idempotent(self, opentree_home: Path) -> None:
        _init()

        # Capture state before refresh
        reg_before = (opentree_home / "config" / "registry.json").read_text(
            encoding="utf-8"
        )
        md_before = (opentree_home / "workspace" / "CLAUDE.md").read_text(
            encoding="utf-8"
        )

        # Refresh
        result = runner.invoke(app, ["module", "refresh"])
        assert result.exit_code == 0, result.output

        # Registry module set unchanged
        reg_after = json.loads(
            (opentree_home / "config" / "registry.json").read_text(
                encoding="utf-8"
            )
        )
        reg_before_parsed = json.loads(reg_before)
        assert set(reg_after["modules"].keys()) == set(
            reg_before_parsed["modules"].keys()
        )

        # CLAUDE.md content unchanged
        md_after = (opentree_home / "workspace" / "CLAUDE.md").read_text(
            encoding="utf-8"
        )
        assert md_after == md_before


# ------------------------------------------------------------------
# CLAUDE.md size constraints
# ------------------------------------------------------------------


class TestClaudeMdSize:
    """CLAUDE.md must stay compact."""

    def test_claude_md_under_200_lines(self, opentree_home: Path) -> None:
        _init()
        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        lines = claude_md.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 200, f"CLAUDE.md has {len(lines)} lines (max 200)"

    def test_token_reduction_vs_dogi(self, opentree_home: Path) -> None:
        """CLAUDE.md lines < 200 vs DOGI's ~991 => 80%+ reduction."""
        _init()
        claude_md = opentree_home / "workspace" / "CLAUDE.md"
        line_count = len(claude_md.read_text(encoding="utf-8").splitlines())
        dogi_lines = 991
        reduction = 1 - (line_count / dogi_lines)
        assert reduction >= 0.80, (
            f"Only {reduction:.0%} reduction "
            f"({line_count} lines vs {dogi_lines})"
        )


# ------------------------------------------------------------------
# settings.json permissions
# ------------------------------------------------------------------


class TestSettingsJson:
    """settings.json includes allowedTools and denyTools."""

    def test_settings_json_has_permissions(
        self, opentree_home: Path
    ) -> None:
        _init()
        settings = json.loads(
            (
                opentree_home / "workspace" / ".claude" / "settings.json"
            ).read_text(encoding="utf-8")
        )
        assert "allowedTools" in settings
        assert "denyTools" in settings
        # Slack deny rules should be present
        assert any("slack" in t.lower() for t in settings["denyTools"])


# ------------------------------------------------------------------
# No unresolved placeholders
# ------------------------------------------------------------------


class TestNoUnresolvedPlaceholders:
    """Workspace rules must not contain {{...}} tokens."""

    def test_no_unresolved_placeholders(self, opentree_home: Path) -> None:
        _init()
        rules_dir = opentree_home / "workspace" / ".claude" / "rules"
        pattern = re.compile(r"\{\{[a-z_]+\}\}")
        violations: list[str] = []
        for md_file in rules_dir.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            if matches:
                violations.append(
                    f"{md_file.name}: {', '.join(matches)}"
                )
        assert not violations, (
            "Unresolved placeholders found:\n" + "\n".join(violations)
        )


# ------------------------------------------------------------------
# prompt show integration
# ------------------------------------------------------------------


class TestPromptShow:
    """opentree prompt show works after init."""

    def test_init_then_prompt_show(self, opentree_home: Path) -> None:
        _init()
        result = runner.invoke(app, ["prompt", "show"])
        assert result.exit_code == 0, result.output
        # Should contain the bot name and path info
        assert "TestBot" in result.output
