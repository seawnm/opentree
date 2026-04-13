"""Tests for permission completeness across all bundled modules.

Verifies that:
- All module manifests have syntactically valid permission patterns.
- The core module declares baseline tools (Read, Write, Edit, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _modules_dir() -> Path:
    """Return the absolute path to the bundled modules directory."""
    # Navigate from tests/ -> project root -> modules/
    return Path(__file__).resolve().parent.parent / "modules"


def _load_all_manifests() -> dict[str, dict]:
    """Load all opentree.json manifests from modules/*/opentree.json.

    Returns:
        A dict mapping module name to parsed manifest.
    """
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


# ---------------------------------------------------------------------------
# Core module baseline
# ---------------------------------------------------------------------------

# These are the minimum tools Claude needs to be useful.
# All users (including admins) are subject to these allow rules via dontAsk mode.
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


class TestCoreModuleBaseline:
    """Verify the core module declares essential baseline tools."""

    def test_core_manifest_exists(self) -> None:
        """modules/core/opentree.json must exist."""
        core_manifest = _modules_dir() / "core" / "opentree.json"
        assert core_manifest.exists(), (
            f"Core module manifest not found at {core_manifest}"
        )

    def test_core_has_baseline_allow_tools(self) -> None:
        """Core module must include Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Task.

        Entries may be bare (e.g. ``"Glob"``) or path-scoped
        (e.g. ``"Read($OPENTREE_HOME/**)"``); both forms satisfy the check.
        """
        core_path = _modules_dir() / "core" / "opentree.json"
        manifest = json.loads(core_path.read_text(encoding="utf-8"))

        allow_list = manifest.get("permissions", {}).get("allow", [])

        for tool in _CORE_BASELINE_TOOLS:
            assert any(
                entry == tool or entry.startswith(f"{tool}(")
                for entry in allow_list
            ), (
                f"Core module missing baseline tool: {tool!r}. "
                f"Current allow list: {allow_list}"
            )

    def test_core_allow_list_not_empty(self) -> None:
        """Core permissions.allow must not be empty."""
        core_path = _modules_dir() / "core" / "opentree.json"
        manifest = json.loads(core_path.read_text(encoding="utf-8"))

        allow_list = manifest.get("permissions", {}).get("allow", [])
        assert len(allow_list) > 0, (
            "Core module permissions.allow is empty — no tools are allowed"
        )


# ---------------------------------------------------------------------------
# All modules — permission pattern validation
# ---------------------------------------------------------------------------

class TestModulePermissionPatterns:
    """Verify all module manifests have well-formed permission entries."""

    def test_all_manifests_have_permissions_key(self) -> None:
        """Every manifest should have a 'permissions' key."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            assert "permissions" in manifest, (
                f"Module {name!r} manifest is missing 'permissions' key"
            )

    def test_all_permissions_have_allow_and_deny(self) -> None:
        """Every permissions block should have 'allow' and 'deny' lists."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            perms = manifest.get("permissions", {})
            assert "allow" in perms, (
                f"Module {name!r} permissions missing 'allow'"
            )
            assert "deny" in perms, (
                f"Module {name!r} permissions missing 'deny'"
            )

    def test_allow_entries_are_strings(self) -> None:
        """All allow entries must be strings."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            allow = manifest.get("permissions", {}).get("allow", [])
            for i, entry in enumerate(allow):
                assert isinstance(entry, str), (
                    f"Module {name!r} permissions.allow[{i}] is not a string: {entry!r}"
                )

    def test_deny_entries_are_strings(self) -> None:
        """All deny entries must be strings."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            deny = manifest.get("permissions", {}).get("deny", [])
            for i, entry in enumerate(deny):
                assert isinstance(entry, str), (
                    f"Module {name!r} permissions.deny[{i}] is not a string: {entry!r}"
                )

    def test_allow_entries_are_nonempty(self) -> None:
        """No allow entry should be an empty string."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            allow = manifest.get("permissions", {}).get("allow", [])
            for i, entry in enumerate(allow):
                assert entry.strip(), (
                    f"Module {name!r} permissions.allow[{i}] is empty"
                )

    def test_deny_entries_are_nonempty(self) -> None:
        """No deny entry should be an empty string."""
        manifests = _load_all_manifests()

        for name, manifest in manifests.items():
            deny = manifest.get("permissions", {}).get("deny", [])
            for i, entry in enumerate(deny):
                assert entry.strip(), (
                    f"Module {name!r} permissions.deny[{i}] is empty"
                )
