"""Migration integration tests: verify 28 rule files are correctly structured.

Tests that all migrated rule files across the 10 modules are:
- Present and matching their manifests
- Valid UTF-8 with balanced placeholders
- Using only known placeholder keys
- Free of hardcoded values that should be placeholders
- Within expected line-count ranges
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MODULES_DIR = _PROJECT_ROOT / "modules"

# Known placeholder keys used across all modules
_KNOWN_PLACEHOLDERS = frozenset({
    "{{bot_name}}",
    "{{team_name}}",
    "{{admin_channel}}",
    "{{admin_description}}",
    "{{owner_description}}",
    "{{opentree_home}}",
})

# 7 pre-installed modules
_PREINSTALLED = frozenset({
    "core", "personality", "guardrail", "memory",
    "slack", "scheduler", "audit-logger",
})

# 3 optional modules
_OPTIONAL = frozenset({"requirement", "stt", "youtube"})

_ALL_MODULES = _PREINSTALLED | _OPTIONAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_all_rule_files() -> list[Path]:
    """Return all .md rule files across all modules."""
    return sorted(_MODULES_DIR.rglob("rules/*.md"))


def _get_manifests() -> dict[str, dict[str, Any]]:
    """Load all manifests from modules/*/opentree.json."""
    if not _MODULES_DIR.exists():
        pytest.skip("modules/ directory not found")
    manifests: dict[str, dict[str, Any]] = {}
    for p in sorted(_MODULES_DIR.glob("*/opentree.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        manifests[p.parent.name] = data
    return manifests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def all_rule_files() -> list[Path]:
    """All .md rule files on disk."""
    files = _get_all_rule_files()
    if not files:
        pytest.skip("No rule files found")
    return files


@pytest.fixture()
def all_manifests() -> dict[str, dict[str, Any]]:
    return _get_manifests()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMigrationIntegration:
    """Verify the 28 rule files are correctly structured post-migration."""

    # 1. Each of 10 modules has at least 1 .md in rules/
    def test_all_modules_have_rule_files(self) -> None:
        """Each of the 10 modules has at least one .md file under rules/."""
        for module_name in _ALL_MODULES:
            rules_dir = _MODULES_DIR / module_name / "rules"
            md_files = list(rules_dir.glob("*.md"))
            assert len(md_files) >= 1, (
                f"Module '{module_name}' has no .md files under {rules_dir}"
            )

    # 2. Exactly 28 .md files across all modules
    def test_total_rule_file_count(self, all_rule_files: list[Path]) -> None:
        """There are exactly 28 .md rule files across all modules."""
        assert len(all_rule_files) == 28, (
            f"Expected 28 rule files, got {len(all_rule_files)}: "
            f"{[f.name for f in all_rule_files]}"
        )

    # 3. Each file can be read as UTF-8
    def test_all_rules_valid_utf8(self, all_rule_files: list[Path]) -> None:
        """Every rule file can be read as valid UTF-8."""
        for rule_file in all_rule_files:
            try:
                rule_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pytest.fail(f"File is not valid UTF-8: {rule_file}")

    # 4. No {{ without matching }}
    def test_no_partial_placeholders(self, all_rule_files: list[Path]) -> None:
        """No file contains {{ without a matching }}."""
        # Find {{ that is NOT followed by word chars + }}
        partial_re = re.compile(r"\{\{(?![a-z_]+\}\})")
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            matches = partial_re.findall(content)
            assert not matches, (
                f"File {rule_file.name} has unmatched '{{{{': "
                f"found {len(matches)} partial placeholder(s)"
            )

    # 5. All {{...}} are from the known set
    def test_known_placeholders_only(self, all_rule_files: list[Path]) -> None:
        """All {{key}} placeholders in files are from the known set."""
        placeholder_re = re.compile(r"\{\{[a-z_]+\}\}")
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            found = set(placeholder_re.findall(content))
            unknown = found - _KNOWN_PLACEHOLDERS
            assert not unknown, (
                f"File {rule_file.name} contains unknown placeholder(s): {unknown}"
            )

    # 6. No file contains literal "DOGI"
    def test_no_dogi_hardcoded(self, all_rule_files: list[Path]) -> None:
        """No rule file contains the hardcoded string 'DOGI'."""
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            assert "DOGI" not in content, (
                f"File {rule_file.name} contains hardcoded 'DOGI' "
                f"(should use {{{{bot_name}}}})"
            )

    # 7. No file contains "<BOT_ROOT>"
    def test_no_hardcoded_bot_root(self, all_rule_files: list[Path]) -> None:
        """No rule file contains the literal '<BOT_ROOT>' placeholder."""
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            assert "<BOT_ROOT>" not in content, (
                f"File {rule_file.name} contains hardcoded '<BOT_ROOT>' "
                f"(should use {{{{opentree_home}}}})"
            )

    # 8. No file contains hardcoded channel IDs outside code examples
    def test_no_hardcoded_channel_id(self, all_rule_files: list[Path]) -> None:
        """No rule file contains known hardcoded Slack channel IDs outside examples.

        Channel IDs appearing inside fenced code blocks (```...```) are
        tolerated as documentation examples.
        """
        hardcoded_ids = {"C0AK78CNYBU", "C0AEED4BNTA"}
        # Regex to strip fenced code blocks before checking
        code_block_re = re.compile(r"```.*?```", re.DOTALL)
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            # Remove fenced code blocks — IDs in examples are acceptable
            content_no_code = code_block_re.sub("", content)
            for cid in hardcoded_ids:
                assert cid not in content_no_code, (
                    f"File {rule_file.name} contains hardcoded channel ID "
                    f"'{cid}' outside code examples "
                    f"(should use {{{{admin_channel}}}} or config)"
                )

    # 9. Each manifest's loading.rules matches actual files on disk
    def test_manifest_rules_match_disk(
        self, all_manifests: dict[str, dict[str, Any]]
    ) -> None:
        """Each manifest's loading.rules list matches the actual files on disk."""
        for name, data in all_manifests.items():
            rules_dir = _MODULES_DIR / name / "rules"
            manifest_rules = set(data.get("loading", {}).get("rules", []))
            disk_files = {f.name for f in rules_dir.glob("*.md")} if rules_dir.exists() else set()

            # Manifest rules must be a subset of disk files
            missing_on_disk = manifest_rules - disk_files
            assert not missing_on_disk, (
                f"Module '{name}': manifest lists {missing_on_disk} "
                f"but file(s) not found on disk"
            )

            # Disk files must be a subset of manifest rules (no orphans)
            orphan_files = disk_files - manifest_rules
            assert not orphan_files, (
                f"Module '{name}': file(s) {orphan_files} on disk "
                f"but not listed in manifest"
            )

    # 10. 7 pre-installed modules' rules total ~500-900 lines
    def test_preinstalled_total_lines(self, all_rule_files: list[Path]) -> None:
        """Pre-installed modules' rules total between 500 and 900 lines."""
        total = 0
        for rule_file in all_rule_files:
            if rule_file.parent.parent.name in _PREINSTALLED:
                content = rule_file.read_text(encoding="utf-8")
                total += content.count("\n")
        assert 500 <= total <= 900, (
            f"Pre-installed modules' rules total {total} lines "
            f"(expected 500-900)"
        )

    # 11. All 10 modules total ~800-1200 lines
    def test_all_modules_total_lines(self, all_rule_files: list[Path]) -> None:
        """All 10 modules' rules total between 800 and 1200 lines."""
        total = 0
        for rule_file in all_rule_files:
            content = rule_file.read_text(encoding="utf-8")
            total += content.count("\n")
        assert 800 <= total <= 1200, (
            f"All modules' rules total {total} lines (expected 800-1200)"
        )

    # 12. Core has expected files
    def test_core_has_expected_files(self) -> None:
        """Core module has identity.md, routing.md, path-conventions.md, etc."""
        rules_dir = _MODULES_DIR / "core" / "rules"
        expected = {"identity.md", "routing.md", "path-conventions.md",
                    "design-principles.md", "environment.md"}
        actual = {f.name for f in rules_dir.glob("*.md")}
        missing = expected - actual
        assert not missing, (
            f"Core module missing expected files: {missing}"
        )

    # 13. personality/character.md contains {{bot_name}}
    def test_personality_has_placeholders(self) -> None:
        """personality/character.md contains the {{bot_name}} placeholder."""
        char_file = _MODULES_DIR / "personality" / "rules" / "character.md"
        content = char_file.read_text(encoding="utf-8")
        assert "{{bot_name}}" in content, (
            "personality/character.md should contain {{bot_name}}"
        )

    # 14. scheduler/schedule-tool.md contains "uv run"
    def test_scheduler_has_cli_examples(self) -> None:
        """scheduler/schedule-tool.md contains CLI examples with 'uv run'."""
        tool_file = _MODULES_DIR / "scheduler" / "rules" / "schedule-tool.md"
        content = tool_file.read_text(encoding="utf-8")
        assert "uv run" in content, (
            "scheduler/schedule-tool.md should contain 'uv run' CLI examples"
        )

    # 15. No .md file is 0 bytes
    def test_no_empty_rule_files(self, all_rule_files: list[Path]) -> None:
        """No rule .md file is empty (0 bytes)."""
        for rule_file in all_rule_files:
            size = rule_file.stat().st_size
            assert size > 0, (
                f"Rule file is empty (0 bytes): {rule_file}"
            )
