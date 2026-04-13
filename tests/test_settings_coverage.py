"""Tests for end-to-end settings.json coverage.

Simulates installing all bundled modules and generating settings.json,
then verifies the generated output has correct structure and content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentree.generator.settings import SettingsGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _modules_dir() -> Path:
    """Return the absolute path to the bundled modules directory."""
    return Path(__file__).resolve().parent.parent / "modules"


def _load_all_manifests() -> dict[str, dict]:
    """Load all opentree.json manifests from modules/*/opentree.json."""
    modules_path = _modules_dir()
    manifests: dict[str, dict] = {}

    if not modules_path.exists():
        pytest.skip("modules/ directory not found")

    for manifest_path in sorted(modules_path.glob("*/opentree.json")):
        module_name = manifest_path.parent.name
        text = manifest_path.read_text(encoding="utf-8")
        manifests[module_name] = json.loads(text)

    if not manifests:
        pytest.skip("No module manifests found")

    return manifests


# Core baseline tools that MUST appear in the generated settings
_CORE_BASELINE_TOOLS = {
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Task",
}

# Slack deny entries expected from the slack module
_SLACK_DENY_ENTRIES = {
    "mcp__claude_ai_Slack__slack_send_message",
    "mcp__claude_ai_Slack__slack_send_message_draft",
    "mcp__claude_ai_Slack__slack_schedule_message",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def full_settings(tmp_path: Path) -> dict:
    """Install all bundled modules and generate settings.json content.

    Simulates the init flow: for each module in modules/, call
    add_module_permissions() with its manifest's permissions, then
    call generate_settings().
    """
    opentree_home = tmp_path / "opentree_home"
    (opentree_home / "config").mkdir(parents=True)
    (opentree_home / "workspace").mkdir(parents=True)

    gen = SettingsGenerator(opentree_home)
    manifests = _load_all_manifests()

    for module_name, manifest in sorted(manifests.items()):
        perms = manifest.get("permissions", {})
        allow = perms.get("allow", [])
        deny = perms.get("deny", [])
        gen.add_module_permissions(module_name, allow=allow, deny=deny)

    return gen.generate_settings()


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------

class TestSettingsFormat:
    """Verify generated settings uses the correct top-level structure."""

    def test_has_permissions_key(self, full_settings: dict) -> None:
        """Generated settings must have 'permissions' as the top-level key."""

        assert "permissions" in full_settings, (
            "Generated settings missing 'permissions' key. "
            f"Top-level keys: {list(full_settings.keys())}"
        )

    def test_no_legacy_keys(self, full_settings: dict) -> None:
        """Generated settings must NOT have legacy 'allowedTools'/'denyTools' keys."""

        assert "allowedTools" not in full_settings, (
            "Generated settings still uses legacy 'allowedTools' key"
        )
        assert "denyTools" not in full_settings, (
            "Generated settings still uses legacy 'denyTools' key"
        )

    def test_permissions_has_allow_and_deny(self, full_settings: dict) -> None:
        """permissions block must contain 'allow' and 'deny' lists."""

        perms = full_settings["permissions"]
        assert "allow" in perms
        assert "deny" in perms
        assert isinstance(perms["allow"], list)
        assert isinstance(perms["deny"], list)


# ---------------------------------------------------------------------------
# Content coverage tests
# ---------------------------------------------------------------------------

class TestSettingsContentCoverage:
    """Verify generated settings contain expected tool permissions."""

    def test_core_baseline_tools_present(self, full_settings: dict) -> None:
        """Core baseline tools (Read, Write, Edit, etc.) must be in allow list.

        Entries may be bare (e.g. ``"Glob"``) or path-scoped
        (e.g. ``"Read($OPENTREE_HOME/**)"``); both forms satisfy the check.
        """
        allow_list = full_settings["permissions"]["allow"]

        for tool in _CORE_BASELINE_TOOLS:
            assert any(
                entry == tool or entry.startswith(f"{tool}(")
                for entry in allow_list
            ), (
                f"Core baseline tool {tool!r} missing from generated "
                f"settings.permissions.allow. Got: {allow_list}"
            )

    def test_slack_deny_entries_present(self, full_settings: dict) -> None:
        """Slack MCP send tools must be in deny list."""
        deny_list = full_settings["permissions"]["deny"]

        for entry in _SLACK_DENY_ENTRIES:
            assert entry in deny_list, (
                f"Expected deny entry {entry!r} missing from generated "
                f"settings.permissions.deny. Got: {deny_list}"
            )

    def test_minimum_allow_count(self, full_settings: dict) -> None:
        """Total allow count should be >= core baseline + at least some module tools."""

        allow_list = full_settings["permissions"]["allow"]

        # Core baseline (8) + at least a few module-specific entries
        # (slack has 2, scheduler has 2, etc.)
        minimum_expected = len(_CORE_BASELINE_TOOLS) + 2
        assert len(allow_list) >= minimum_expected, (
            f"Expected at least {minimum_expected} allow entries, "
            f"got {len(allow_list)}: {allow_list}"
        )

    def test_no_duplicate_allow_entries(self, full_settings: dict) -> None:
        """No duplicates in the generated allow list."""

        allow_list = full_settings["permissions"]["allow"]

        seen: set[str] = set()
        duplicates: list[str] = []
        for entry in allow_list:
            if entry in seen:
                duplicates.append(entry)
            seen.add(entry)

        assert not duplicates, (
            f"Duplicate entries in settings.permissions.allow: {duplicates}"
        )

    def test_no_duplicate_deny_entries(self, full_settings: dict) -> None:
        """No duplicates in the generated deny list."""

        deny_list = full_settings["permissions"]["deny"]

        seen: set[str] = set()
        duplicates: list[str] = []
        for entry in deny_list:
            if entry in seen:
                duplicates.append(entry)
            seen.add(entry)

        assert not duplicates, (
            f"Duplicate entries in settings.permissions.deny: {duplicates}"
        )

    def test_module_specific_tools_present(self, full_settings: dict) -> None:
        """Module-specific Bash patterns from slack/scheduler/etc. must appear."""

        allow_list = full_settings["permissions"]["allow"]

        # At minimum, slack module contributes these patterns
        assert any("upload_tool" in entry for entry in allow_list), (
            "Slack module's upload_tool pattern not found in allow list"
        )
        assert any("slack_query_tool" in entry for entry in allow_list), (
            "Slack module's slack_query_tool pattern not found in allow list"
        )
