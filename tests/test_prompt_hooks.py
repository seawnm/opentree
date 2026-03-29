"""Tests for individual module prompt hooks (TDD)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# Helper: import hook from file path
# ------------------------------------------------------------------ #


def _import_hook(module_path: str):
    """Import a prompt_hook module from an absolute path."""
    p = Path(module_path)
    mod_name = f"test_hook_{p.parent.name}"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(p))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Resolve paths relative to this test file
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SLACK_HOOK = str(_REPO_ROOT / "modules" / "slack" / "prompt_hook.py")
_MEMORY_HOOK = str(_REPO_ROOT / "modules" / "memory" / "prompt_hook.py")
_REQ_HOOK = str(_REPO_ROOT / "modules" / "requirement" / "prompt_hook.py")


# ------------------------------------------------------------------ #
# Slack hook
# ------------------------------------------------------------------ #


class TestSlackHook:
    def test_full_context(self) -> None:
        mod = _import_hook(_SLACK_HOOK)
        ctx = {
            "channel_id": "C0AK78CNYBU",
            "thread_ts": "1739012345.123456",
            "team_name": "DOGI Team",
            "workspace": "beta-room",
        }
        lines = mod.prompt_hook(ctx)
        assert any("C0AK78CNYBU" in l for l in lines)
        assert any("1739012345.123456" in l for l in lines)
        assert any("DOGI Team" in l for l in lines)
        assert any("beta-room" in l for l in lines)

    def test_empty_context(self) -> None:
        mod = _import_hook(_SLACK_HOOK)
        lines = mod.prompt_hook({})
        assert lines == []

    def test_partial(self) -> None:
        mod = _import_hook(_SLACK_HOOK)
        ctx = {"channel_id": "C123"}
        lines = mod.prompt_hook(ctx)
        assert len(lines) == 1
        assert "C123" in lines[0]

    def test_team_fallback(self) -> None:
        """When team_name is missing, should use workspace."""
        mod = _import_hook(_SLACK_HOOK)
        ctx = {"workspace": "my-ws"}
        lines = mod.prompt_hook(ctx)
        assert any("my-ws" in l for l in lines)


# ------------------------------------------------------------------ #
# Memory hook
# ------------------------------------------------------------------ #


class TestMemoryHook:
    def test_new_user(self) -> None:
        mod = _import_hook(_MEMORY_HOOK)
        ctx = {"is_new_user": True, "user_display_name": "Alice"}
        lines = mod.prompt_hook(ctx)
        assert len(lines) > 0
        assert any("Alice" in l for l in lines)

    def test_existing_user(self) -> None:
        mod = _import_hook(_MEMORY_HOOK)
        ctx = {"is_new_user": False, "user_display_name": "Bob"}
        lines = mod.prompt_hook(ctx)
        assert lines == []

    def test_missing_fields(self) -> None:
        """is_new_user not set defaults to falsy -> empty."""
        mod = _import_hook(_MEMORY_HOOK)
        ctx = {"user_display_name": "Charlie"}
        lines = mod.prompt_hook(ctx)
        assert lines == []


# ------------------------------------------------------------------ #
# Requirement hook
# ------------------------------------------------------------------ #


class TestRequirementHook:
    def test_returns_empty(self) -> None:
        mod = _import_hook(_REQ_HOOK)
        ctx = {"user_id": "U123", "channel_id": "C456"}
        lines = mod.prompt_hook(ctx)
        assert lines == []
