"""Tests for core prompt assembly (TDD — write tests first, implement after)."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from opentree.core.config import UserConfig
from opentree.core.prompt import (
    PromptContext,
    PromptHookCache,
    assemble_system_prompt,
    build_config_block,
    build_date_block,
    build_identity_block,
    build_paths_block,
    collect_module_prompts,
)
from opentree.registry.models import RegistryData, RegistryEntry


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


def _make_registry(*module_names: str) -> RegistryData:
    """Helper to build a RegistryData with module stubs."""
    entries = tuple(
        (
            name,
            RegistryEntry(
                name=name,
                version="1.0.0",
                module_type="pre-installed",
                installed_at="2026-01-01T00:00:00+00:00",
                source="bundled",
            ),
        )
        for name in sorted(module_names)
    )
    return RegistryData(version=1, modules=entries)


def _write_module_with_hook(
    home: Path,
    name: str,
    hook_code: str,
    *,
    manifest_extras: dict[str, Any] | None = None,
) -> None:
    """Create a module dir with opentree.json + prompt_hook.py."""
    mod_dir = home / "modules" / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "description": f"Test module {name}",
        "type": "pre-installed",
        "prompt_hook": "prompt_hook.py",
    }
    if manifest_extras:
        manifest.update(manifest_extras)
    (mod_dir / "opentree.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (mod_dir / "prompt_hook.py").write_text(hook_code, encoding="utf-8")


# ------------------------------------------------------------------ #
# PromptContext tests
# ------------------------------------------------------------------ #


class TestPromptContext:
    def test_prompt_context_frozen(self) -> None:
        ctx = PromptContext(user_id="U123")
        with pytest.raises(FrozenInstanceError):
            ctx.user_id = "U456"  # type: ignore[misc]

    def test_prompt_context_defaults(self) -> None:
        ctx = PromptContext()
        assert ctx.user_id == ""
        assert ctx.user_name == ""
        assert ctx.user_display_name == ""
        assert ctx.channel_id == ""
        assert ctx.thread_ts == ""
        assert ctx.workspace == ""
        assert ctx.team_name == ""
        assert ctx.memory_path == ""
        assert ctx.is_new_user is False
        assert ctx.thread_participants == ()
        assert ctx.opentree_home == ""

    def test_prompt_context_to_dict(self) -> None:
        ctx = PromptContext(user_id="U999", user_name="alice", is_new_user=True)
        d = ctx.to_dict()
        assert d["user_id"] == "U999"
        assert d["user_name"] == "alice"
        assert d["is_new_user"] is True
        assert isinstance(d, dict)
        # All keys present
        expected_keys = {
            "user_id",
            "user_name",
            "user_display_name",
            "channel_id",
            "thread_ts",
            "workspace",
            "team_name",
            "memory_path",
            "is_new_user",
            "thread_participants",
            "opentree_home",
        }
        assert set(d.keys()) == expected_keys

    def test_prompt_context_new_fields_defaults(self) -> None:
        """New fields have safe defaults."""
        ctx = PromptContext()
        assert ctx.thread_participants == ()
        assert ctx.opentree_home == ""

    def test_prompt_context_new_fields_in_dict(self) -> None:
        """New fields appear in to_dict output."""
        ctx = PromptContext(
            thread_participants=("Alice", "Bob"),
            opentree_home="/home/test/.opentree",
        )
        d = ctx.to_dict()
        assert d["thread_participants"] == ["Alice", "Bob"]
        assert d["opentree_home"] == "/home/test/.opentree"


# ------------------------------------------------------------------ #
# build_date_block
# ------------------------------------------------------------------ #


class TestBuildDateBlock:
    def test_build_date_block_taipei(self) -> None:
        lines = build_date_block()
        assert len(lines) == 2
        assert "Asia/Taipei" in lines[0]
        assert "Asia/Taipei" in lines[1]
        # Should contain today's date in Taipei timezone
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        assert now.strftime("%Y-%m-%d") in lines[0]

    def test_build_date_block_custom_tz(self) -> None:
        lines = build_date_block(timezone="America/New_York")
        assert "America/New_York" in lines[0]
        assert "America/New_York" in lines[1]


# ------------------------------------------------------------------ #
# build_config_block
# ------------------------------------------------------------------ #


class TestBuildConfigBlock:
    def test_build_config_block_with_bot_name(self) -> None:
        config = UserConfig(bot_name="DOGI", opentree_home="/home/test/.opentree")
        lines = build_config_block(config)
        assert any("DOGI" in line for line in lines)

    def test_build_config_block_default(self) -> None:
        config = UserConfig(opentree_home="/home/test/.opentree")
        lines = build_config_block(config)
        assert any("OpenTree" in line for line in lines)


# ------------------------------------------------------------------ #
# build_paths_block
# ------------------------------------------------------------------ #


class TestBuildPathsBlock:
    def test_build_paths_block_forward_slashes(self) -> None:
        config = UserConfig(opentree_home="C:\\Users\\test\\.opentree")
        lines = build_paths_block(config)
        for line in lines:
            assert "\\" not in line, f"Backslash found in: {line}"

    def test_build_paths_block_content(self) -> None:
        config = UserConfig(opentree_home="/home/user/.opentree")
        lines = build_paths_block(config)
        assert len(lines) == 4
        assert "OPENTREE_HOME" in lines[0]
        assert "/home/user/.opentree" in lines[0]
        assert "modules/" in lines[1]
        assert "workspace/" in lines[2]
        assert "data/" in lines[3]


# ------------------------------------------------------------------ #
# build_identity_block
# ------------------------------------------------------------------ #


class TestBuildIdentityBlock:
    def test_build_identity_full(self) -> None:
        ctx = PromptContext(
            user_id="U123",
            user_name="alice",
            user_display_name="Alice W.",
            memory_path="/mem/alice.md",
        )
        lines = build_identity_block(ctx)
        assert any("Alice W." in l and "alice" in l for l in lines)
        assert any("U123" in l for l in lines)
        assert any("/mem/alice.md" in l for l in lines)

    def test_build_identity_empty(self) -> None:
        ctx = PromptContext()
        lines = build_identity_block(ctx)
        assert lines == []

    def test_build_identity_with_memory_path(self) -> None:
        ctx = PromptContext(
            user_display_name="bob",
            memory_path="/data/bob/memory.md",
        )
        lines = build_identity_block(ctx)
        assert any("/data/bob/memory.md" in l for l in lines)

    def test_build_identity_same_name_no_duplicate(self) -> None:
        """When user_name == user_display_name, should not show duplicate."""
        ctx = PromptContext(
            user_name="walter",
            user_display_name="walter",
        )
        lines = build_identity_block(ctx)
        # Should not contain parentheses with duplicate
        assert len(lines) == 1
        assert "walter" in lines[0]
        assert "(" not in lines[0]


# ------------------------------------------------------------------ #
# collect_module_prompts
# ------------------------------------------------------------------ #


class TestCollectModulePrompts:
    def test_loads_hook(self, tmp_path: Path) -> None:
        """Should load and execute prompt_hook.py from a module."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return [f\"hello {context.get('user_name', 'world')}\"]\n"
        )
        _write_module_with_hook(tmp_path, "greet", hook_code)
        registry = _make_registry("greet")
        ctx = PromptContext(user_name="alice")
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == ["hello alice"]

    def test_skips_no_hook(self, tmp_path: Path) -> None:
        """Module without prompt_hook in manifest should be skipped."""
        mod_dir = tmp_path / "modules" / "nohook"
        mod_dir.mkdir(parents=True)
        manifest = {"name": "nohook", "version": "1.0.0"}
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        registry = _make_registry("nohook")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == []

    def test_error_resilient(self, tmp_path: Path) -> None:
        """Hook that raises should not crash; should add error line."""
        hook_code = (
            "def prompt_hook(context):\n" "    raise ValueError('boom')\n"
        )
        _write_module_with_hook(tmp_path, "broken", hook_code)
        registry = _make_registry("broken")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert len(lines) == 1
        assert "broken" in lines[0]
        assert "error" in lines[0].lower()

    def test_skips_missing_manifest(self, tmp_path: Path) -> None:
        """Module dir without opentree.json should be skipped."""
        (tmp_path / "modules" / "ghost").mkdir(parents=True)
        registry = _make_registry("ghost")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == []

    def test_skips_missing_hook_file(self, tmp_path: Path) -> None:
        """Manifest references prompt_hook but file doesn't exist."""
        mod_dir = tmp_path / "modules" / "missingfile"
        mod_dir.mkdir(parents=True)
        manifest = {
            "name": "missingfile",
            "version": "1.0.0",
            "prompt_hook": "prompt_hook.py",
        }
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        registry = _make_registry("missingfile")
        ctx = PromptContext()
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == []


# ------------------------------------------------------------------ #
# assemble_system_prompt
# ------------------------------------------------------------------ #


class TestAssembleSystemPrompt:
    def test_all_blocks(self, tmp_path: Path) -> None:
        """Full assembly with a hook module."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['## Module Hook Output']\n"
        )
        _write_module_with_hook(tmp_path, "test-mod", hook_code)
        registry = _make_registry("test-mod")
        config = UserConfig(bot_name="TestBot", opentree_home=str(tmp_path))
        ctx = PromptContext(
            user_id="U123",
            user_display_name="Alice",
            channel_id="C456",
        )
        result = assemble_system_prompt(tmp_path, registry, config, ctx)
        # Should contain date block
        assert "Asia/Taipei" in result
        # Should contain config block
        assert "TestBot" in result
        # Should contain paths block
        assert "OPENTREE_HOME" in result
        # Should contain identity block
        assert "Alice" in result
        assert "U123" in result
        # Should contain module hook output
        assert "Module Hook Output" in result
        # Should end with newline
        assert result.endswith("\n")

    def test_empty_registry(self, tmp_path: Path) -> None:
        """Assembly with no modules should still produce core blocks."""
        registry = RegistryData(version=1, modules=())
        config = UserConfig(bot_name="EmptyBot", opentree_home=str(tmp_path))
        ctx = PromptContext()
        result = assemble_system_prompt(tmp_path, registry, config, ctx)
        assert "EmptyBot" in result
        assert "OPENTREE_HOME" in result
        assert "Asia/Taipei" in result
        assert result.endswith("\n")


# ------------------------------------------------------------------ #
# PromptHookCache tests
# ------------------------------------------------------------------ #


class TestPromptHookCache:
    """Tests for cached hook loading (P2 perf fix: exec_module once)."""

    def test_hooks_loaded_once_on_first_call(self, tmp_path: Path) -> None:
        """exec_module should be called exactly once per hook, not on every request."""
        hook_code = (
            "call_count = 0\n"
            "def prompt_hook(context):\n"
            "    global call_count\n"
            "    call_count += 1\n"
            "    return [f'count={call_count}']\n"
        )
        _write_module_with_hook(tmp_path, "counter", hook_code)
        registry = _make_registry("counter")

        cache = PromptHookCache()
        ctx = PromptContext(user_name="alice")

        # First call — loads the hook (exec_module runs once)
        lines1 = collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)
        assert lines1 == ["count=1"]

        # Second call — reuses cached callable, same module object
        lines2 = collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)
        # call_count increments because same function object is reused
        assert lines2 == ["count=2"]

    def test_cached_hooks_reused_on_subsequent_calls(self, tmp_path: Path) -> None:
        """The cached callable must be the exact same object across calls."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['cached']\n"
        )
        _write_module_with_hook(tmp_path, "stable", hook_code)
        registry = _make_registry("stable")

        cache = PromptHookCache()
        ctx = PromptContext()

        # Load hooks
        collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)

        # The cache should contain one entry
        assert len(cache) == 1

        # Grab the cached callable
        cached_fn = cache.get("stable")
        assert cached_fn is not None

        # Call again
        collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)

        # Same function object (not re-imported)
        assert cache.get("stable") is cached_fn

    def test_cache_not_populated_for_hookless_modules(self, tmp_path: Path) -> None:
        """Modules without prompt_hook should not appear in cache."""
        mod_dir = tmp_path / "modules" / "plain"
        mod_dir.mkdir(parents=True)
        manifest = {"name": "plain", "version": "1.0.0"}
        (mod_dir / "opentree.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        registry = _make_registry("plain")

        cache = PromptHookCache()
        ctx = PromptContext()
        collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)

        assert len(cache) == 0

    def test_no_exec_module_on_second_call(self, tmp_path: Path) -> None:
        """Verify exec_module is NOT called on the second invocation."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['ok']\n"
        )
        _write_module_with_hook(tmp_path, "traced", hook_code)
        registry = _make_registry("traced")

        cache = PromptHookCache()
        ctx = PromptContext()

        # First call populates cache
        collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)

        # Patch exec_module to detect if it would be called again
        with patch("opentree.core.prompt.importlib.util") as mock_util:
            lines = collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)
            # exec_module should NOT have been called — hook is cached
            mock_util.spec_from_file_location.assert_not_called()

        assert lines == ["ok"]

    def test_backward_compatible_without_cache(self, tmp_path: Path) -> None:
        """collect_module_prompts without hook_cache should still work (no caching)."""
        hook_code = (
            "def prompt_hook(context):\n"
            "    return ['compat']\n"
        )
        _write_module_with_hook(tmp_path, "legacy", hook_code)
        registry = _make_registry("legacy")
        ctx = PromptContext()

        # Call without hook_cache — original behaviour
        lines = collect_module_prompts(tmp_path, registry, ctx)
        assert lines == ["compat"]

    def test_error_hook_not_cached(self, tmp_path: Path) -> None:
        """A hook that fails to load should not be cached."""
        hook_code = "raise SyntaxError('bad hook')\n"
        _write_module_with_hook(tmp_path, "bad", hook_code)
        registry = _make_registry("bad")

        cache = PromptHookCache()
        ctx = PromptContext()

        lines = collect_module_prompts(tmp_path, registry, ctx, hook_cache=cache)
        assert any("error" in l.lower() for l in lines)
        # Should NOT cache the broken hook
        assert cache.get("bad") is None
