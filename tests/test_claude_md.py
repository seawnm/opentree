"""Tests for ClaudeMdGenerator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentree.core.config import UserConfig
from opentree.generator.claude_md import ClaudeMdGenerator, ModuleInfo
from opentree.registry.models import RegistryData, RegistryEntry


def _make_entry(name: str, version: str = "1.0.0") -> RegistryEntry:
    """Helper to create a RegistryEntry for testing."""
    return RegistryEntry(
        name=name,
        version=version,
        module_type="pre-installed",
        installed_at="2026-03-29T00:00:00+00:00",
        source="bundled",
    )


def _make_registry(*names: str) -> RegistryData:
    """Helper to create a RegistryData with the given module names."""
    modules = tuple((n, _make_entry(n)) for n in sorted(names))
    return RegistryData(version=1, modules=modules)


def _write_manifest(
    opentree_home: Path,
    name: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    triggers: dict | None = None,
) -> None:
    """Helper to write a module manifest on disk."""
    mod_dir = opentree_home / "modules" / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "name": name,
        "version": version,
        "description": description,
        "type": "pre-installed",
        "loading": {"rules": ["rule.md"]},
    }
    if triggers is not None:
        data["triggers"] = triggers
    (mod_dir / "opentree.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Pre-installed 7 modules (Scenario A from design doc)
# ---------------------------------------------------------------------------
PRE_INSTALLED_7 = (
    "audit-logger",
    "core",
    "guardrail",
    "memory",
    "personality",
    "scheduler",
    "slack",
)

ALL_10 = PRE_INSTALLED_7 + ("requirement", "stt", "youtube")


class TestGenerate7Modules:
    """test_generate_7_modules — 7 pre-installed, output < 200 lines."""

    def test_output_under_200_lines(self, tmp_path: Path) -> None:
        for name in PRE_INSTALLED_7:
            _write_manifest(
                tmp_path,
                name,
                description=f"{name} module",
                triggers={"keywords": ["kw"], "description": f"{name} desc"},
            )
        registry = _make_registry(*PRE_INSTALLED_7)
        config = UserConfig(bot_name="Groot", opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert result.count("\n") < 200
        assert "## 已安裝模組" in result
        assert "## 模組觸發索引" in result


class TestGenerate10Modules:
    """test_generate_10_modules — all 10, output < 200 lines."""

    def test_output_under_200_lines(self, tmp_path: Path) -> None:
        for name in ALL_10:
            _write_manifest(
                tmp_path,
                name,
                description=f"{name} module",
                triggers={"keywords": ["kw"], "description": f"{name} desc"},
            )
        registry = _make_registry(*ALL_10)
        config = UserConfig(bot_name="Groot", opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert result.count("\n") < 200


class TestGenerateEmptyRegistryRaises:
    """test_generate_empty_registry_raises — RuntimeError."""

    def test_raises_runtime_error(self, tmp_path: Path) -> None:
        registry = RegistryData(version=1, modules=())
        config = UserConfig(opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        with pytest.raises(RuntimeError, match="Registry is empty"):
            gen.generate(tmp_path, registry, config)


class TestGenerateSingleModule:
    """test_generate_single_module — minimal output structure."""

    def test_has_all_sections(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path,
            "core",
            description="Core module",
            triggers={"keywords": ["路徑"], "description": "路由規則"},
        )
        registry = _make_registry("core")
        config = UserConfig(bot_name="TestBot", opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "# TestBot 的工作區" in result
        assert "## 路徑慣例" in result
        assert "## 已安裝模組" in result
        assert "## 模組觸發索引" in result
        assert "## 注意事項" in result


class TestHeaderContainsBotName:
    """test_header_contains_bot_name — header uses config.bot_name."""

    def test_custom_bot_name_in_header(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        config = UserConfig(bot_name="大樹", opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "# 大樹 的工作區" in result

    def test_default_bot_name(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        config = UserConfig(opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "# OpenTree 的工作區" in result


class TestPathsSectionNormalized:
    """test_paths_section_normalized — Windows backslash -> forward slash."""

    def test_windows_paths_normalized(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        # Simulate Windows-style path
        config = UserConfig(
            opentree_home="C:\\Users\\test\\.opentree",
        )
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "C:/Users/test/.opentree" in result
        assert "C:\\Users" not in result


class TestModuleListAllPresent:
    """test_module_list_all_present — every registered module in the list."""

    def test_all_modules_listed(self, tmp_path: Path) -> None:
        names = ("alpha", "bravo", "charlie")
        for name in names:
            _write_manifest(tmp_path, name, description=f"{name} desc")
        registry = _make_registry(*names)
        config = UserConfig(opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        for name in names:
            assert f"**{name}**" in result


class TestTriggerTableFormat:
    """test_trigger_table_format — proper markdown table format."""

    def test_table_has_header_and_separator(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path,
            "core",
            description="Core",
            triggers={"keywords": ["路徑", "設定"], "description": "路由規則"},
        )
        registry = _make_registry("core")
        config = UserConfig(opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "| 模組 | 觸發關鍵字 | 說明 |" in result
        assert "|------|-----------|------|" in result
        assert "| core | 路徑, 設定 | 路由規則 |" in result


class TestTriggerTableMissingTriggers:
    """test_trigger_table_missing_triggers — renders dash for missing triggers."""

    def test_dash_for_no_triggers(self, tmp_path: Path) -> None:
        # Write a manifest WITHOUT triggers field
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        config = UserConfig(opentree_home=str(tmp_path))
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        # Should render "—" (em dash) for missing triggers
        lines = result.split("\n")
        trigger_rows = [
            line for line in lines if line.startswith("| core")
        ]
        assert len(trigger_rows) == 1
        # Both keywords and description should be "—"
        assert "\u2014" in trigger_rows[0]  # em dash


class TestPlaceholderSubstitution:
    """test_placeholder_substitution — {{bot_name}} replaced."""

    def test_no_raw_placeholders_in_output(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        config = UserConfig(
            bot_name="Groot",
            team_name="MyTeam",
            admin_channel="C999",
            opentree_home=str(tmp_path),
        )
        gen = ClaudeMdGenerator()

        result = gen.generate(tmp_path, registry, config)

        assert "{{bot_name}}" not in result
        assert "{{team_name}}" not in result
        assert "{{admin_channel}}" not in result
        assert "{{opentree_home}}" not in result


class TestPlaceholderBackslashSafe:
    """test_placeholder_backslash_safe — Windows path in opentree_home."""

    def test_backslash_in_path_no_crash(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "core", description="Core")
        registry = _make_registry("core")
        config = UserConfig(
            opentree_home="E:\\develop\\opentree",
        )
        gen = ClaudeMdGenerator()

        # Should not raise (re.sub would fail on backslashes)
        result = gen.generate(tmp_path, registry, config)

        assert "E:/develop/opentree" in result


class TestGenerateWithDiskManifests:
    """test_generate_with_disk_manifests — uses actual modules/ directory."""

    OPENTREE_ROOT = Path("/mnt/e/develop/mydev/opentree")

    @pytest.mark.skipif(
        not Path("/mnt/e/develop/mydev/opentree/modules").exists(),
        reason="Requires actual OpenTree modules on disk",
    )
    def test_with_real_modules(self) -> None:
        opentree_home = self.OPENTREE_ROOT
        modules_dir = opentree_home / "modules"

        # Build registry from actual modules on disk
        names = sorted(p.name for p in modules_dir.iterdir() if p.is_dir())
        assert len(names) == 10, f"Expected 10 modules, got {len(names)}: {names}"

        registry = _make_registry(*names)
        config = UserConfig(
            bot_name="Groot",
            opentree_home=str(opentree_home),
        )
        gen = ClaudeMdGenerator()

        result = gen.generate(opentree_home, registry, config)

        # Verify structure
        assert "# Groot 的工作區" in result
        assert result.count("\n") < 200

        # Verify all 10 modules present
        for name in names:
            assert f"**{name}**" in result

        # Verify trigger table has rows for all modules
        lines = result.split("\n")
        table_rows = [
            line
            for line in lines
            if line.startswith("|") and not line.startswith("| 模組") and not line.startswith("|--")
        ]
        assert len(table_rows) == 10
