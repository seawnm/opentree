"""Tests for PlaceholderEngine."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentree.core.config import UserConfig
from opentree.core.placeholders import PlaceholderEngine, ResolveResult


def _make_config(**overrides: str) -> UserConfig:
    """Create a UserConfig with sensible defaults, allowing overrides."""
    defaults = {
        "bot_name": "TestBot",
        "team_name": "TestTeam",
        "admin_channel": "C999",
        "owner_description": "Admin desc",
        "opentree_home": "/opt/opentree",
    }
    defaults.update(overrides)
    return UserConfig(**defaults)


class TestReplacementsMap:
    """test_replacements_map_has_all_keys -- verify all expected keys exist."""

    def test_has_all_keys(self) -> None:
        engine = PlaceholderEngine(_make_config())
        keys = engine.replacements

        assert "{{bot_name}}" in keys
        assert "{{team_name}}" in keys
        assert "{{admin_channel}}" in keys
        assert "{{owner_description}}" in keys
        assert "{{admin_description}}" in keys  # backward compat alias
        assert "{{opentree_home}}" in keys
        assert len(keys) == 6


class TestResolveContentReplacesBotName:
    """test_resolve_content_replaces_bot_name -- single placeholder."""

    def test_replaces_bot_name(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name="DOGI"))
        result = engine.resolve_content("Hello {{bot_name}}")

        assert result == "Hello DOGI"


class TestResolveContentReplacesMultiple:
    """test_resolve_content_replaces_multiple -- several placeholders in one string."""

    def test_replaces_multiple(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name="DOGI", team_name="Alpha"))
        content = "{{bot_name}} belongs to {{team_name}}"
        result = engine.resolve_content(content)

        assert result == "DOGI belongs to Alpha"


class TestResolveContentNoPlaceholders:
    """test_resolve_content_no_placeholders_unchanged -- plain text stays the same."""

    def test_unchanged(self) -> None:
        engine = PlaceholderEngine(_make_config())
        content = "No placeholders here."
        result = engine.resolve_content(content)

        assert result == content


class TestResolveFileWithPlaceholders:
    """test_resolve_file_with_placeholders_writes_target -- file is written when placeholders exist."""

    def test_writes_target(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "template.md"
        source.parent.mkdir(parents=True)
        source.write_text("Bot is {{bot_name}}", encoding="utf-8")

        target = tmp_path / "out" / "resolved.md"

        engine = PlaceholderEngine(_make_config(bot_name="DOGI"))
        result = engine.resolve_file(source, target)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Bot is DOGI"
        assert result.had_placeholders is True
        assert result.source == str(source)
        assert result.target == str(target)


class TestResolveFileWithoutPlaceholders:
    """test_resolve_file_without_placeholders_no_write -- no write when content is unchanged."""

    def test_no_write(self, tmp_path: Path) -> None:
        source = tmp_path / "template.md"
        source.write_text("Plain text, no placeholders.", encoding="utf-8")

        target = tmp_path / "out" / "resolved.md"

        engine = PlaceholderEngine(_make_config())
        result = engine.resolve_file(source, target)

        assert not target.exists()
        assert result.had_placeholders is False


class TestResolveFileCreatesParentDirs:
    """test_resolve_file_creates_parent_dirs -- deeply nested target dirs are created."""

    def test_creates_dirs(self, tmp_path: Path) -> None:
        source = tmp_path / "template.md"
        source.write_text("Home: {{opentree_home}}", encoding="utf-8")

        target = tmp_path / "a" / "b" / "c" / "resolved.md"

        engine = PlaceholderEngine(_make_config())
        engine.resolve_file(source, target)

        assert target.exists()


class TestResolveResultFrozen:
    """test_resolve_file_result_frozen -- ResolveResult is immutable."""

    def test_frozen(self) -> None:
        result = ResolveResult(
            source="/a", target="/b", had_placeholders=True
        )
        with pytest.raises(AttributeError):
            result.source = "/c"  # type: ignore[misc]


class TestHasPlaceholdersTrue:
    """test_has_placeholders_true -- detects known placeholders."""

    def test_true(self) -> None:
        engine = PlaceholderEngine(_make_config())
        assert engine.has_placeholders("Use {{bot_name}} here") is True


class TestHasPlaceholdersFalse:
    """test_has_placeholders_false -- plain text returns False."""

    def test_false(self) -> None:
        engine = PlaceholderEngine(_make_config())
        assert engine.has_placeholders("No placeholders at all") is False


class TestScanUnresolvedFindsUnknown:
    """test_scan_unresolved_finds_unknown -- detects placeholders not in the map."""

    def test_finds_unknown(self) -> None:
        engine = PlaceholderEngine(_make_config())
        result = engine.scan_unresolved(
            "Hello {{bot_name}} and {{unknown_field}}"
        )

        assert "{{unknown_field}}" in result
        assert "{{bot_name}}" not in result


class TestScanUnresolvedEmptyWhenAllKnown:
    """test_scan_unresolved_empty_when_all_known -- no unknowns returns empty tuple."""

    def test_empty(self) -> None:
        engine = PlaceholderEngine(_make_config())
        result = engine.scan_unresolved("Hello {{bot_name}} and {{team_name}}")

        assert result == ()


class TestValidateRequiredPresentOk:
    """test_validate_required_present_ok -- required placeholder with value passes."""

    def test_ok(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name="DOGI"))
        errors = engine.validate_module_placeholders({"bot_name": "required"})

        assert errors == []


class TestValidateRequiredMissingError:
    """test_validate_required_missing_error -- required placeholder with empty value fails."""

    def test_error(self) -> None:
        engine = PlaceholderEngine(_make_config(team_name=""))
        errors = engine.validate_module_placeholders({"team_name": "required"})

        assert len(errors) == 1
        assert "team_name" in errors[0]


class TestValidateOptionalMissingOk:
    """test_validate_optional_missing_ok -- optional with empty value is fine."""

    def test_ok(self) -> None:
        engine = PlaceholderEngine(_make_config(team_name=""))
        errors = engine.validate_module_placeholders({"team_name": "optional"})

        assert errors == []


class TestValidateAutoAlwaysOk:
    """test_validate_auto_always_ok -- auto mode never errors."""

    def test_ok(self) -> None:
        engine = PlaceholderEngine(_make_config())
        errors = engine.validate_module_placeholders(
            {"opentree_home": "auto"}
        )

        assert errors == []


class TestBotNameDefaultFallback:
    """test_bot_name_default_fallback -- empty bot_name falls back to 'OpenTree'."""

    def test_fallback(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name=""))
        assert engine.replacements["{{bot_name}}"] == "OpenTree"


class TestWindowsBackslashNormalization:
    """test_windows_backslash_normalization -- backslashes in opentree_home become forward slashes."""

    def test_normalization(self) -> None:
        engine = PlaceholderEngine(
            _make_config(opentree_home="C:\\Users\\test\\opentree")
        )
        assert engine.replacements["{{opentree_home}}"] == "C:/Users/test/opentree"


class TestChineseBotName:
    """test_chinese_bot_name -- CJK characters work correctly."""

    def test_chinese(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name="大樹"))
        result = engine.resolve_content("我是 {{bot_name}}")

        assert result == "我是 大樹"


class TestEmptyContent:
    """test_empty_content -- empty string resolves to empty string."""

    def test_empty(self) -> None:
        engine = PlaceholderEngine(_make_config())
        assert engine.resolve_content("") == ""
        assert engine.has_placeholders("") is False
        assert engine.scan_unresolved("") == ()


# ===========================================================================
# Issue 3: User config containing {{ must not break PlaceholderEngine
# ===========================================================================


class TestUnknownDoubleBraceLeftIntact:
    """Unknown {{...}} patterns must pass through unchanged."""

    def test_unknown_placeholder_left_as_is(self) -> None:
        engine = PlaceholderEngine(_make_config())
        content = "value = {{some_template_var}}"
        result = engine.resolve_content(content)
        assert result == "value = {{some_template_var}}"

    def test_known_resolved_unknown_left(self) -> None:
        engine = PlaceholderEngine(_make_config(bot_name="DOGI"))
        content = "Bot: {{bot_name}}, Template: {{unknown_var}}"
        result = engine.resolve_content(content)
        assert result == "Bot: DOGI, Template: {{unknown_var}}"

    def test_code_snippet_with_double_braces(self) -> None:
        """A config value like a Jinja template must not be mangled."""
        engine = PlaceholderEngine(_make_config())
        content = "{% for item in list %}{{item.name}}{% endfor %}"
        result = engine.resolve_content(content)
        assert result == "{% for item in list %}{{item.name}}{% endfor %}"

    def test_nested_braces_left_intact(self) -> None:
        engine = PlaceholderEngine(_make_config())
        content = "{{{not_a_placeholder}}}"
        result = engine.resolve_content(content)
        assert result == "{{{not_a_placeholder}}}"

    def test_empty_double_braces(self) -> None:
        engine = PlaceholderEngine(_make_config())
        content = "empty: {{}}"
        result = engine.resolve_content(content)
        assert result == "empty: {{}}"

    def test_resolve_file_leaves_unknown_placeholders(self, tmp_path: Path) -> None:
        source = tmp_path / "template.md"
        source.write_text(
            "Bot: {{bot_name}}, Custom: {{my_custom}}",
            encoding="utf-8",
        )
        target = tmp_path / "out" / "resolved.md"

        engine = PlaceholderEngine(_make_config(bot_name="DOGI"))
        result = engine.resolve_file(source, target)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Bot: DOGI, Custom: {{my_custom}}"
        assert result.had_placeholders is True

    def test_scan_unresolved_ignores_non_identifier_braces(self) -> None:
        """scan_unresolved only flags {{lowercase_underscore}} patterns."""
        engine = PlaceholderEngine(_make_config())
        content = "{{item.name}} and {{UPPER}} and {{unknown_field}}"
        result = engine.scan_unresolved(content)
        # Only {{unknown_field}} matches [a-z_]+ pattern
        assert "{{unknown_field}}" in result
        assert "{{item.name}}" not in result
        assert "{{UPPER}}" not in result

    def test_has_placeholders_false_for_unknown_only(self) -> None:
        """has_placeholders returns False when only unknown patterns exist."""
        engine = PlaceholderEngine(_make_config())
        assert engine.has_placeholders("{{unknown_thing}}") is False

    def test_multiple_unknown_all_preserved(self) -> None:
        engine = PlaceholderEngine(_make_config())
        content = "{{foo}} and {{bar}} and {{baz}}"
        result = engine.resolve_content(content)
        assert result == "{{foo}} and {{bar}} and {{baz}}"

    def test_resolved_value_containing_placeholder_syntax_not_double_replaced(
        self,
    ) -> None:
        """If a config value contains {{...}} syntax, it must NOT be resolved
        again in a second pass (no double-replacement vulnerability).

        The str.replace loop iterates dict keys in insertion order; if
        ``admin_description`` is resolved first and its value contains
        ``{{bot_name}}``, the subsequent ``bot_name`` replacement must NOT
        expand it.  This test patches _replacements to control ordering.
        """
        engine = PlaceholderEngine(
            _make_config(
                bot_name="DOGI",
                owner_description="Use {{bot_name}} in templates",
            )
        )
        # Force owner_description to be resolved BEFORE bot_name by
        # rebuilding the dict with owner_description first.
        reordered = {}
        reordered["{{owner_description}}"] = engine._replacements["{{owner_description}}"]
        for k, v in engine._replacements.items():
            if k != "{{owner_description}}":
                reordered[k] = v
        engine._replacements = reordered

        content = "Desc: {{owner_description}}"
        result = engine.resolve_content(content)
        # Must NOT produce "Desc: Use DOGI in templates" (double-replacement).
        assert result == "Desc: Use {{bot_name}} in templates"
