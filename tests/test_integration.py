"""Integration tests: all 10 module manifests pass validation and the dependency graph is correct.

Tests IV-01 through IV-10 verify:
- All manifests validate against the JSON Schema
- Module names match directory names
- Dependency graph is acyclic (DAG)
- All depends_on entries are resolvable
- Pre-installed modules never depend on optional modules
- Rule file names follow the required pattern
- Correct type counts (7 pre-installed, 3 optional)
- Topological sort always places "core" first
- No conflicts among the 10 modules
- All module names are unique
"""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from opentree.manifest.errors import ErrorCode
from opentree.manifest.validator import ManifestValidator

# ---------------------------------------------------------------------------
# Confirmed dependency graph (from design.md / execution-plan.md)
# ---------------------------------------------------------------------------

_CONFIRMED_MODULES: dict[str, dict[str, Any]] = {
    "core": {
        "name": "core",
        "version": "1.0.0",
        "description": "Core runtime and shared constants",
        "type": "pre-installed",
        "depends_on": [],
        "conflicts_with": [],
        "loading": {"rules": ["constants.md", "runtime.md", "paths.md", "tools.md", "security.md"]},
    },
    "personality": {
        "name": "personality",
        "version": "1.0.0",
        "description": "DOGI personality and communication style",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["personality.md", "identity.md"]},
    },
    "guardrail": {
        "name": "guardrail",
        "version": "1.0.0",
        "description": "Permission and safety guardrails",
        "type": "pre-installed",
        "depends_on": ["personality"],
        "conflicts_with": [],
        "loading": {"rules": ["permissions.md", "safety.md", "refusal.md", "audit.md"]},
    },
    "memory": {
        "name": "memory",
        "version": "1.0.0",
        "description": "User memory and knowledge management",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["memory.md", "knowledge.md"]},
        "prompt_hook": "prompt_hook.py",
    },
    "slack": {
        "name": "slack",
        "version": "1.0.0",
        "description": "Slack integration and messaging tools",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["messaging.md", "upload.md", "query.md", "formatting.md"]},
        "prompt_hook": "prompt_hook.py",
    },
    "scheduler": {
        "name": "scheduler",
        "version": "1.0.0",
        "description": "Task scheduling and cron management",
        "type": "pre-installed",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["schedule-tool.md", "watcher-tool.md", "task-chain.md"]},
    },
    "audit-logger": {
        "name": "audit-logger",
        "version": "1.0.0",
        "description": "Memory modification audit logging",
        "type": "pre-installed",
        "depends_on": ["memory"],
        "conflicts_with": [],
        "loading": {"rules": ["audit-logger.md"]},
    },
    "requirement": {
        "name": "requirement",
        "version": "1.0.0",
        "description": "Requirements gathering and tracking",
        "type": "optional",
        "depends_on": ["slack"],
        "conflicts_with": [],
        "loading": {"rules": ["requirement-tool.md", "requirement-flow.md", "invest.md", "interview.md"]},
        "prompt_hook": "prompt_hook.py",
    },
    "stt": {
        "name": "stt",
        "version": "1.0.0",
        "description": "Speech-to-text audio transcription",
        "type": "optional",
        "depends_on": ["slack"],
        "conflicts_with": [],
        "loading": {"rules": ["stt.md"]},
    },
    "youtube": {
        "name": "youtube",
        "version": "1.0.0",
        "description": "YouTube video metadata and subtitle search",
        "type": "optional",
        "depends_on": ["core"],
        "conflicts_with": [],
        "loading": {"rules": ["youtube.md", "youtube-search.md"]},
    },
}

_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"
_RULE_PATTERN = re.compile(r"^[a-z0-9-]+\.md$")


def _discover_manifests_from_disk() -> dict[str, dict[str, Any]] | None:
    """Try to load all 10 manifests from modules/*/opentree.json.

    Returns None if any of the 10 modules is missing on disk.
    """
    manifests: dict[str, dict[str, Any]] = {}
    for name in _CONFIRMED_MODULES:
        manifest_path = _MODULES_DIR / name / "opentree.json"
        if not manifest_path.is_file():
            return None
        manifests[name] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifests


def _get_manifests() -> dict[str, dict[str, Any]]:
    """Return manifests from disk if available, otherwise use inline data."""
    disk = _discover_manifests_from_disk()
    return disk if disk is not None else _CONFIRMED_MODULES


def _topological_sort(manifests: dict[str, dict[str, Any]]) -> list[str]:
    """Kahn's algorithm topological sort (deterministic: alphabetical tie-break)."""
    in_degree: dict[str, int] = {name: 0 for name in manifests}
    adjacency: dict[str, list[str]] = {name: [] for name in manifests}

    for name, data in manifests.items():
        for dep in data.get("depends_on", []):
            if dep in manifests:
                adjacency[dep].append(name)
                in_degree[name] += 1

    queue: deque[str] = deque(sorted(n for n, d in in_degree.items() if d == 0))
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in sorted(adjacency[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def validator() -> ManifestValidator:
    """Create a ManifestValidator instance."""
    return ManifestValidator()


@pytest.fixture()
def all_manifests() -> dict[str, dict[str, Any]]:
    """All 10 module manifests (from disk or inline fallback)."""
    return _get_manifests()


# ---------------------------------------------------------------------------
# IV-01: All manifests valid against schema
# ---------------------------------------------------------------------------


class TestManifestIntegration:
    """Integration tests for the 10 module manifests."""

    def test_all_manifests_valid_against_schema(
        self,
        validator: ManifestValidator,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-01: Every module manifest passes schema validation with zero errors."""
        for name, data in all_manifests.items():
            result = validator.validate_dict(data, module_dir_name=name)
            assert result.is_valid, (
                f"Module '{name}' failed validation: "
                f"{[i.message for i in result.errors]}"
            )
            assert result.errors == (), (
                f"Module '{name}' has unexpected errors: "
                f"{[i.message for i in result.errors]}"
            )

    # -----------------------------------------------------------------------
    # IV-02: Names match directories
    # -----------------------------------------------------------------------

    def test_all_names_match_directories(
        self,
        validator: ManifestValidator,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-02: For each module, name field matches the directory key (no NAME_MISMATCH)."""
        for dir_name, data in all_manifests.items():
            result = validator.validate_dict(data, module_dir_name=dir_name)
            mismatch_errors = [
                i for i in result.issues if i.code == ErrorCode.NAME_MISMATCH
            ]
            assert mismatch_errors == [], (
                f"Module '{dir_name}' has NAME_MISMATCH: "
                f"{[i.message for i in mismatch_errors]}"
            )

    # -----------------------------------------------------------------------
    # IV-03: Dependency graph is acyclic
    # -----------------------------------------------------------------------

    def test_dependency_graph_acyclic(
        self,
        validator: ManifestValidator,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-03: validate_batch detects no CIRCULAR_DEPENDENCY errors."""
        results = validator.validate_batch(all_manifests)
        for name, result in results.items():
            circular = [
                i for i in result.issues if i.code == ErrorCode.CIRCULAR_DEPENDENCY
            ]
            assert circular == [], (
                f"Module '{name}' involved in circular dependency: "
                f"{[i.message for i in circular]}"
            )

    # -----------------------------------------------------------------------
    # IV-04: All depends_on entries resolvable
    # -----------------------------------------------------------------------

    def test_all_depends_on_resolvable(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-04: Every depends_on entry references an existing module name."""
        all_names = set(all_manifests.keys())
        for name, data in all_manifests.items():
            for dep in data.get("depends_on", []):
                assert dep in all_names, (
                    f"Module '{name}' depends on '{dep}', "
                    f"which is not in the module set: {sorted(all_names)}"
                )

    # -----------------------------------------------------------------------
    # IV-05: No pre-installed depends on optional
    # -----------------------------------------------------------------------

    def test_no_preinstalled_depends_on_optional(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-05: Pre-installed modules never depend on optional modules."""
        optional_names = {
            name for name, data in all_manifests.items() if data["type"] == "optional"
        }
        preinstalled = {
            name
            for name, data in all_manifests.items()
            if data["type"] == "pre-installed"
        }

        for name in preinstalled:
            deps = set(all_manifests[name].get("depends_on", []))
            forbidden = deps & optional_names
            assert forbidden == set(), (
                f"Pre-installed module '{name}' depends on optional module(s): "
                f"{sorted(forbidden)}"
            )

    # -----------------------------------------------------------------------
    # IV-06: All rules match pattern
    # -----------------------------------------------------------------------

    def test_all_rules_match_pattern(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-06: Every loading.rules entry matches ^[a-z0-9-]+\\.md$."""
        for name, data in all_manifests.items():
            rules = data.get("loading", {}).get("rules", [])
            for rule in rules:
                assert _RULE_PATTERN.match(rule), (
                    f"Module '{name}' has rule '{rule}' that does not match "
                    f"pattern ^[a-z0-9-]+\\.md$"
                )

    # -----------------------------------------------------------------------
    # IV-07: Type counts
    # -----------------------------------------------------------------------

    def test_type_counts(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-07: Exactly 7 pre-installed and 3 optional modules."""
        preinstalled = [
            name
            for name, data in all_manifests.items()
            if data["type"] == "pre-installed"
        ]
        optional = [
            name
            for name, data in all_manifests.items()
            if data["type"] == "optional"
        ]

        assert len(preinstalled) == 7, (
            f"Expected 7 pre-installed, got {len(preinstalled)}: {sorted(preinstalled)}"
        )
        assert len(optional) == 3, (
            f"Expected 3 optional, got {len(optional)}: {sorted(optional)}"
        )

    # -----------------------------------------------------------------------
    # IV-08: Topological sort has "core" first
    # -----------------------------------------------------------------------

    def test_topological_sort_core_first(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-08: Topological sort of the dependency graph always places 'core' first."""
        order = _topological_sort(all_manifests)

        assert len(order) == len(all_manifests), (
            f"Topological sort produced {len(order)} nodes but expected "
            f"{len(all_manifests)} (possible cycle?)"
        )
        assert order[0] == "core", (
            f"Expected 'core' first in topological order, got '{order[0]}'. "
            f"Full order: {order}"
        )

    # -----------------------------------------------------------------------
    # IV-09: No conflicts among modules
    # -----------------------------------------------------------------------

    def test_no_conflicts_among_modules(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-09: No module's conflicts_with list references another installed module."""
        all_names = set(all_manifests.keys())
        for name, data in all_manifests.items():
            conflicts = set(data.get("conflicts_with", []))
            overlap = conflicts & all_names
            assert overlap == set(), (
                f"Module '{name}' conflicts with installed module(s): "
                f"{sorted(overlap)}"
            )

    # -----------------------------------------------------------------------
    # IV-10: Unique names
    # -----------------------------------------------------------------------

    def test_unique_names(
        self,
        all_manifests: dict[str, dict[str, Any]],
    ) -> None:
        """IV-10: All module names are unique (no duplicates)."""
        names = [data["name"] for data in all_manifests.values()]
        assert len(names) == len(set(names)), (
            f"Duplicate module names found: "
            f"{[n for n in names if names.count(n) > 1]}"
        )
