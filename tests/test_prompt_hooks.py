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

    def test_thread_participants_shown(self) -> None:
        """Thread participants are shown when others are present."""
        mod = _import_hook(_SLACK_HOOK)
        ctx = {
            "channel_id": "C123",
            "thread_ts": "1234.5678",
            "workspace": "test",
            "team_name": "TestTeam",
            "user_display_name": "Alice",
            "user_name": "alice",
            "thread_participants": ["Alice", "Bob", "Charlie"],
        }
        lines = mod.prompt_hook(ctx)
        participant_lines = [l for l in lines if "參與者" in l]
        assert len(participant_lines) == 1
        assert "Bob" in participant_lines[0]
        assert "Charlie" in participant_lines[0]
        assert "Alice" not in participant_lines[0]  # self excluded

    def test_thread_participants_excludes_self(self) -> None:
        """Current user is excluded from participant list."""
        mod = _import_hook(_SLACK_HOOK)
        ctx = {
            "channel_id": "C123",
            "thread_ts": "1234.5678",
            "workspace": "test",
            "team_name": "",
            "user_display_name": "Bob",
            "user_name": "bob",
            "thread_participants": ["Bob"],
        }
        lines = mod.prompt_hook(ctx)
        participant_lines = [l for l in lines if "參與者" in l]
        assert len(participant_lines) == 0  # only self, no reminder

    def test_thread_participants_empty(self) -> None:
        """No participant reminder when list is empty."""
        mod = _import_hook(_SLACK_HOOK)
        ctx = {
            "channel_id": "C123",
            "thread_ts": "1234.5678",
            "workspace": "test",
            "team_name": "",
            "user_display_name": "Alice",
            "user_name": "alice",
            "thread_participants": [],
        }
        lines = mod.prompt_hook(ctx)
        participant_lines = [l for l in lines if "參與者" in l]
        assert len(participant_lines) == 0

    def test_thread_participants_missing_key(self) -> None:
        """No crash when thread_participants key is absent."""
        mod = _import_hook(_SLACK_HOOK)
        ctx = {
            "channel_id": "C123",
            "thread_ts": "1234.5678",
            "workspace": "test",
            "team_name": "",
            "user_display_name": "Alice",
            "user_name": "alice",
        }
        lines = mod.prompt_hook(ctx)
        participant_lines = [l for l in lines if "參與者" in l]
        assert len(participant_lines) == 0


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

    def test_no_thread_ts_returns_empty(self) -> None:
        """Returns empty when thread_ts is missing."""
        mod = _import_hook(_REQ_HOOK)
        context = {"opentree_home": "/tmp/test", "thread_ts": ""}
        result = mod.prompt_hook(context)
        assert result == []

    def test_no_opentree_home_returns_empty(self) -> None:
        """Returns empty when opentree_home is missing."""
        mod = _import_hook(_REQ_HOOK)
        context = {"opentree_home": "", "thread_ts": "1234.5678"}
        result = mod.prompt_hook(context)
        assert result == []

    def test_no_requirements_dir_returns_empty(self, tmp_path) -> None:
        """Returns empty when requirements directory doesn't exist."""
        mod = _import_hook(_REQ_HOOK)
        context = {"opentree_home": str(tmp_path), "thread_ts": "1234.5678"}
        result = mod.prompt_hook(context)
        assert result == []

    def test_matching_thread_returns_context(self, tmp_path) -> None:
        """Returns interview context when thread_ts matches."""
        import yaml

        mod = _import_hook(_REQ_HOOK)

        # Create requirement directory structure
        req_dir = tmp_path / "data" / "requirements" / "CC-0001" / "interviews"
        req_dir.mkdir(parents=True)

        # Create interview YAML
        interview = {
            "interviewee": "Walter",
            "status": "in_progress",
            "threads": {"P1": "1234.5678"},
            "questions": [{"q": "問題1"}, {"q": "問題2"}],
            "notes": "使用者偏好簡潔回覆",
        }
        yaml_file = req_dir / "interview-01.yaml"
        yaml_file.write_text(
            yaml.dump(interview, allow_unicode=True), encoding="utf-8"
        )

        context = {"opentree_home": str(tmp_path), "thread_ts": "1234.5678"}
        result = mod.prompt_hook(context)

        assert len(result) == 4
        assert "CC-0001" in result[0]
        assert "Walter" in result[0]
        assert "P1" in result[1]
        assert "2 題" in result[1]
        assert "觀察筆記" in result[3]

    def test_no_matching_thread_returns_empty(self, tmp_path) -> None:
        """Returns empty when no thread matches."""
        import yaml

        mod = _import_hook(_REQ_HOOK)

        req_dir = tmp_path / "data" / "requirements" / "CC-0001" / "interviews"
        req_dir.mkdir(parents=True)

        interview = {
            "interviewee": "Walter",
            "status": "in_progress",
            "threads": {"P1": "9999.9999"},
            "questions": [],
        }
        yaml_file = req_dir / "interview-01.yaml"
        yaml_file.write_text(
            yaml.dump(interview, allow_unicode=True), encoding="utf-8"
        )

        context = {"opentree_home": str(tmp_path), "thread_ts": "1234.5678"}
        result = mod.prompt_hook(context)
        assert result == []

    def test_corrupt_yaml_returns_empty(self, tmp_path) -> None:
        """Corrupt YAML files don't crash, just return empty."""
        mod = _import_hook(_REQ_HOOK)

        req_dir = tmp_path / "data" / "requirements" / "CC-0001" / "interviews"
        req_dir.mkdir(parents=True)
        yaml_file = req_dir / "bad.yaml"
        yaml_file.write_text("{{{{invalid yaml!!", encoding="utf-8")

        context = {"opentree_home": str(tmp_path), "thread_ts": "1234.5678"}
        result = mod.prompt_hook(context)
        assert result == []

    def test_notes_truncated_at_200_chars(self, tmp_path) -> None:
        """Long notes are truncated to 200 characters."""
        import yaml

        mod = _import_hook(_REQ_HOOK)

        req_dir = tmp_path / "data" / "requirements" / "CC-0002" / "interviews"
        req_dir.mkdir(parents=True)

        long_notes = "A" * 300
        interview = {
            "interviewee": "Bob",
            "status": "active",
            "threads": {"P2": "5555.6666"},
            "questions": [],
            "notes": long_notes,
        }
        yaml_file = req_dir / "interview-01.yaml"
        yaml_file.write_text(
            yaml.dump(interview, allow_unicode=True), encoding="utf-8"
        )

        context = {"opentree_home": str(tmp_path), "thread_ts": "5555.6666"}
        result = mod.prompt_hook(context)

        notes_line = [line for line in result if "觀察筆記" in line]
        assert len(notes_line) == 1
        assert notes_line[0].endswith("...")
        # 200 chars + "..." + prefix
        assert len(long_notes[:200]) == 200


# ===========================================================================
# Personality prompt hook tests
# ===========================================================================

import json as _json

_PERSONALITY_HOOK = str(_REPO_ROOT / "modules" / "personality" / "prompt_hook.py")


def _make_registry(tmp_path, module_names: list) -> None:
    """Write minimal registry.json to tmp_path."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        _json.dumps({"modules": {name: {} for name in module_names}}),
        encoding="utf-8",
    )


def _make_settings(tmp_path, allow: list) -> None:
    """Write minimal settings.json to tmp_path/workspace/.claude/."""
    settings_dir = tmp_path / "workspace" / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        _json.dumps({"permissions": {"allow": allow, "deny": []}}),
        encoding="utf-8",
    )


class TestIsModuleAvailable:
    """Tests for _is_module_available() — Strategy C core logic."""

    def _fn(self, tmp_path):
        mod = _import_hook(_PERSONALITY_HOOK)
        return mod._is_module_available

    def test_memory_always_true(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("memory", [], tmp_path) is True

    def test_requirement_always_true(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("requirement", [], tmp_path) is True

    def test_youtube_always_true(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("youtube", [], tmp_path) is True

    def test_scheduler_with_matching_rule(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        allow = ["Read($HOME/**)", "Bash(uv run * schedule_tool *)"]
        assert fn("scheduler", allow, tmp_path) is True

    def test_scheduler_without_matching_rule(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("scheduler", ["Bash(echo *)", "Read"], tmp_path) is False

    def test_scheduler_empty_allowed(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("scheduler", [], tmp_path) is False

    def test_slack_with_matching_rule(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("slack", ["Bash(uv run * slack_query_tool *)"], tmp_path) is True

    def test_slack_without_matching_rule(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        # Has Bash but keyword doesn't match
        assert fn("slack", ["Bash(uv run * schedule_tool *)"], tmp_path) is False

    def test_stt_with_matching_rule(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("stt", ["Bash(alloy stt transcribe *)"], tmp_path) is True

    def test_unknown_module_returns_true(self, tmp_path) -> None:
        fn = self._fn(tmp_path)
        assert fn("new_future_module", [], tmp_path) is True


class TestLoadInstalledModules:
    """Tests for _load_installed_modules()."""

    def _fn(self):
        return _import_hook(_PERSONALITY_HOOK)._load_installed_modules

    def test_dict_format(self, tmp_path) -> None:
        _make_registry(tmp_path, ["memory", "slack"])
        result = self._fn()(tmp_path)
        assert set(result) == {"memory", "slack"}

    def test_list_format(self, tmp_path) -> None:
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            _json.dumps({"modules": [{"name": "memory"}, {"name": "slack"}]}),
            encoding="utf-8",
        )
        result = self._fn()(tmp_path)
        assert set(result) == {"memory", "slack"}

    def test_no_registry_file(self, tmp_path) -> None:
        assert self._fn()(tmp_path) == []

    def test_empty_modules(self, tmp_path) -> None:
        (tmp_path / "registry.json").write_text('{"modules": {}}', encoding="utf-8")
        assert self._fn()(tmp_path) == []

    def test_missing_modules_key(self, tmp_path) -> None:
        (tmp_path / "registry.json").write_text('{"version": 1}', encoding="utf-8")
        assert self._fn()(tmp_path) == []

    def test_list_with_missing_name(self, tmp_path) -> None:
        (tmp_path / "registry.json").write_text(
            _json.dumps({"modules": [{"name": "a"}, {}, {"name": "c"}]}),
            encoding="utf-8",
        )
        result = self._fn()(tmp_path)
        assert "a" in result
        assert "c" in result


class TestLoadAllowedTools:
    """Tests for _load_allowed_tools()."""

    def _fn(self):
        return _import_hook(_PERSONALITY_HOOK)._load_allowed_tools

    def test_normal_allow_list(self, tmp_path) -> None:
        _make_settings(tmp_path, ["Bash(schedule_tool)", "Read"])
        result = self._fn()(tmp_path)
        assert result == ["Bash(schedule_tool)", "Read"]

    def test_no_settings_file(self, tmp_path) -> None:
        assert self._fn()(tmp_path) == []

    def test_empty_permissions(self, tmp_path) -> None:
        settings_dir = tmp_path / "workspace" / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text('{"permissions": {}}', encoding="utf-8")
        assert self._fn()(tmp_path) == []

    def test_missing_permissions_key(self, tmp_path) -> None:
        settings_dir = tmp_path / "workspace" / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text('{"other": "data"}', encoding="utf-8")
        assert self._fn()(tmp_path) == []

    def test_allow_not_list(self, tmp_path) -> None:
        settings_dir = tmp_path / "workspace" / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text(
            '{"permissions": {"allow": "invalid"}}', encoding="utf-8"
        )
        assert self._fn()(tmp_path) == []


class TestBuildCapabilityLines:
    """Tests for _build_capability_lines()."""

    def _fn(self):
        return _import_hook(_PERSONALITY_HOOK)._build_capability_lines

    def test_no_installed_modules(self, tmp_path) -> None:
        assert self._fn()([], [], tmp_path) == []

    def test_installed_but_not_in_capability_map(self, tmp_path) -> None:
        assert self._fn()(["unknown_module"], [], tmp_path) == []

    def test_single_core_module(self, tmp_path) -> None:
        result = self._fn()(["memory"], [], tmp_path)
        assert len(result) == 3
        assert "記憶管理" in result[1]

    def test_bash_module_allowed(self, tmp_path) -> None:
        result = self._fn()(["scheduler"], ["Bash(schedule_tool)"], tmp_path)
        assert any("排程" in l for l in result)

    def test_bash_module_blocked(self, tmp_path) -> None:
        assert self._fn()(["scheduler"], [], tmp_path) == []

    def test_output_order_follows_capability_map(self, tmp_path) -> None:
        allow = ["Bash(schedule_tool)", "Bash(stt)"]
        result = self._fn()(["stt", "memory", "scheduler"], allow, tmp_path)
        items = [l for l in result if l.startswith("- ")]
        memory_idx = next(i for i, l in enumerate(items) if "記憶" in l)
        scheduler_idx = next(i for i, l in enumerate(items) if "排程" in l)
        assert memory_idx < scheduler_idx


class TestPersonalityPromptHook:
    """Integration tests for the top-level prompt_hook()."""

    def test_empty_context(self) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        assert mod.prompt_hook({}) == []

    def test_missing_opentree_home(self) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        assert mod.prompt_hook({"user_id": "U123"}) == []

    def test_empty_opentree_home(self) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        assert mod.prompt_hook({"opentree_home": ""}) == []

    def test_nonexistent_path(self, tmp_path) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        fake = str(tmp_path / "does_not_exist")
        result = mod.prompt_hook({"opentree_home": fake})
        assert result == []

    def test_full_setup_all_modules(self, tmp_path) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        _make_registry(tmp_path, ["memory", "scheduler", "slack", "requirement", "youtube", "stt"])
        _make_settings(tmp_path, [
            "Bash(uv run * schedule_tool *)",
            "Bash(uv run * slack_query_tool *)",
            "Bash(alloy stt transcribe *)",
        ])
        result = mod.prompt_hook({"opentree_home": str(tmp_path)})
        assert result[0] == "## 目前可用功能"
        assert result[-1].startswith("（以上功能")
        capability_lines = [l for l in result if l.startswith("- ")]
        assert len(capability_lines) == 6

    def test_partial_modules(self, tmp_path) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        _make_registry(tmp_path, ["memory", "scheduler"])
        _make_settings(tmp_path, ["Bash(uv run * schedule_tool *)"])
        result = mod.prompt_hook({"opentree_home": str(tmp_path)})
        assert any("記憶管理" in l for l in result)
        assert any("排程" in l for l in result)
        assert not any("Slack" in l for l in result)

    def test_exception_in_registry_returns_empty(self, tmp_path) -> None:
        mod = _import_hook(_PERSONALITY_HOOK)
        (tmp_path / "registry.json").write_text("{{invalid json!!", encoding="utf-8")
        result = mod.prompt_hook({"opentree_home": str(tmp_path)})
        assert result == []
