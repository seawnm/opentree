"""Tests for AGENTS.md generation and Codex trust config updates."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

if "jsonschema" not in sys.modules:
    sys.modules["jsonschema"] = types.ModuleType("jsonschema")

from opentree.cli.init import _write_codex_config_trust
from opentree.core.config import UserConfig
from opentree.generator.claude_md import generate_agents_md
from opentree.registry.models import RegistryData, RegistryEntry


def _make_entry(name: str, version: str = "1.0.0") -> RegistryEntry:
    """Create a registry entry for tests."""
    return RegistryEntry(
        name=name,
        version=version,
        module_type="pre-installed",
        installed_at="2026-03-29T00:00:00+00:00",
        source="bundled",
    )


def _make_registry(*names: str) -> RegistryData:
    """Create a registry with sorted module entries."""
    modules = tuple((name, _make_entry(name)) for name in sorted(names))
    return RegistryData(version=1, modules=modules)


def _write_manifest(
    opentree_home: Path,
    name: str,
    *,
    version: str = "1.0.0",
    description: str = "",
) -> None:
    """Write a minimal manifest used by the generator."""
    mod_dir = opentree_home / "modules" / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "version": version,
        "description": description,
        "type": "pre-installed",
        "loading": {"rules": ["rule.md"]},
        "triggers": {"keywords": ["kw"], "description": "trigger desc"},
    }
    (mod_dir / "opentree.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _make_home_with_core(tmp_path: Path) -> tuple[RegistryData, UserConfig]:
    """Prepare an OpenTree home with one installed module."""
    _write_manifest(tmp_path, "core", description="Core module")
    registry = _make_registry("core")
    config = UserConfig(bot_name="TestBot", opentree_home=str(tmp_path))
    return registry, config


def test_generate_agents_md_uses_plain_markers(tmp_path: Path) -> None:
    """AGENTS.md uses Codex-compatible plain markdown markers."""
    registry, config = _make_home_with_core(tmp_path)

    result = generate_agents_md(tmp_path, registry, config)

    assert result.startswith("# OPENTREE:AUTO:BEGIN\n")
    assert "# OPENTREE:AUTO:END" in result
    assert "# (auto-generated — edit below this line)\n" in result


def test_generate_agents_md_preserves_owner_content(tmp_path: Path) -> None:
    """Owner content below the AUTO block should be preserved."""
    registry, config = _make_home_with_core(tmp_path)
    existing = (
        "# OPENTREE:AUTO:BEGIN\nold\n# OPENTREE:AUTO:END\n"
        "# (auto-generated — edit below this line)\n"
        "\n## Owner Notes\n\nKeep this.\n"
    )

    result = generate_agents_md(tmp_path, registry, config, existing)

    assert "## Owner Notes" in result
    assert "Keep this." in result
    assert result.count("# (auto-generated — edit below this line)") == 1


def test_generate_agents_md_without_existing_content_is_fresh(tmp_path: Path) -> None:
    """None existing content should produce a fresh generated file."""
    registry, config = _make_home_with_core(tmp_path)

    result = generate_agents_md(tmp_path, registry, config, None)

    assert "# TestBot 的工作區" in result
    assert "## Owner Notes" not in result


def test_write_codex_config_trust_creates_file_if_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing ~/.codex/config.toml should be created."""
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(Path, "home", lambda: home)

    _write_codex_config_trust(workspace)

    config_path = home / ".codex" / "config.toml"
    assert config_path.exists()
    assert f'[projects."{workspace.resolve()}"]' in config_path.read_text(
        encoding="utf-8"
    )


def test_write_codex_config_trust_does_not_duplicate_entries(
    tmp_path: Path, monkeypatch
) -> None:
    """Repeated writes should not duplicate the same trust block."""
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(Path, "home", lambda: home)

    _write_codex_config_trust(workspace)
    _write_codex_config_trust(workspace)

    content = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert content.count(f'[projects."{workspace.resolve()}"]') == 1
    assert content.count('trust_level = "trusted"') == 1


def test_write_codex_config_trust_appends_without_overwriting(
    tmp_path: Path, monkeypatch
) -> None:
    """Existing config entries should be preserved when appending trust."""
    home = tmp_path / "home"
    config_dir = home / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    existing = (
        '[projects."/existing/workspace"]\n'
        'trust_level = "trusted"\n\n'
        "[ui]\n"
        'theme = "dark"\n'
    )
    config_path.write_text(existing, encoding="utf-8")
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(Path, "home", lambda: home)

    _write_codex_config_trust(workspace)

    content = config_path.read_text(encoding="utf-8")
    assert '[projects."/existing/workspace"]' in content
    assert '[ui]\ntheme = "dark"\n' in content
    assert f'[projects."{workspace.resolve()}"]' in content
    assert content.count('trust_level = "trusted"') == 2
