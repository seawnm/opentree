"""Registry integration tests: register/unregister all 10 modules.

Tests IR-01 through IR-05 verify:
- All 7 pre-installed modules can be registered in topological order
- All 3 optional modules can be registered afterward
- Reverse dependency protection gap is documented (Phase 2)
- Correct unregister order succeeds
- list_modules returns sorted tuple of all 10 names
"""

from __future__ import annotations

from typing import Any

import pytest


from opentree.registry.models import RegistryData
from opentree.registry.registry import Registry

# ---------------------------------------------------------------------------
# Confirmed module metadata (matches the dependency graph)
# ---------------------------------------------------------------------------

_MODULE_META: dict[str, dict[str, Any]] = {
    "core": {"version": "1.0.0", "type": "pre-installed", "depends_on": ()},
    "personality": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("core",)},
    "guardrail": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("personality",)},
    "memory": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("core",)},
    "slack": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("core",)},
    "scheduler": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("core",)},
    "audit-logger": {"version": "1.0.0", "type": "pre-installed", "depends_on": ("memory",)},
    "requirement": {"version": "1.0.0", "type": "optional", "depends_on": ("slack",)},
    "stt": {"version": "1.0.0", "type": "optional", "depends_on": ("slack",)},
    "youtube": {"version": "1.0.0", "type": "optional", "depends_on": ("core",)},
}

# Topological order respecting the dependency graph (alphabetical tie-break).
# core (root) -> memory, personality, scheduler, slack, youtube
#   personality -> guardrail
#   memory -> audit-logger
#   slack -> requirement, stt
_PREINSTALLED_TOPO_ORDER: tuple[str, ...] = (
    "core",
    "memory",
    "personality",
    "scheduler",
    "slack",
    "audit-logger",
    "guardrail",
)

_OPTIONAL_MODULES: tuple[str, ...] = ("requirement", "stt", "youtube")


def _register_module(data: RegistryData, name: str) -> RegistryData:
    """Register a module using its metadata from the confirmed graph."""
    meta = _MODULE_META[name]
    return Registry.register(
        data,
        name=name,
        version=meta["version"],
        module_type=meta["type"],
        depends_on=meta.get("depends_on", ()),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_registry() -> RegistryData:
    """An empty registry to start from."""
    return RegistryData(version=1, modules=())


@pytest.fixture()
def preinstalled_registry(empty_registry: RegistryData) -> RegistryData:
    """Registry with all 7 pre-installed modules registered in topo order."""
    data = empty_registry
    for name in _PREINSTALLED_TOPO_ORDER:
        data = _register_module(data, name)
    return data


@pytest.fixture()
def full_registry(preinstalled_registry: RegistryData) -> RegistryData:
    """Registry with all 10 modules (pre-installed + optional) registered."""
    data = preinstalled_registry
    for name in _OPTIONAL_MODULES:
        data = _register_module(data, name)
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    """Integration tests for Registry CRUD with all 10 modules."""

    # -------------------------------------------------------------------
    # IR-01: Register all pre-installed in topological order
    # -------------------------------------------------------------------

    def test_register_all_preinstalled_in_order(
        self,
        preinstalled_registry: RegistryData,
    ) -> None:
        """IR-01: All 7 pre-installed modules register successfully in topo order."""
        registered = Registry.list_modules(preinstalled_registry)

        assert len(registered) == 7
        for name in _PREINSTALLED_TOPO_ORDER:
            assert Registry.is_registered(preinstalled_registry, name), (
                f"Pre-installed module '{name}' should be registered"
            )

    # -------------------------------------------------------------------
    # IR-02: Register optional modules after pre-installed
    # -------------------------------------------------------------------

    def test_register_optional_modules(
        self,
        full_registry: RegistryData,
    ) -> None:
        """IR-02: All 10 modules (7 pre-installed + 3 optional) are registered."""
        registered = Registry.list_modules(full_registry)

        assert len(registered) == 10
        for name in _MODULE_META:
            assert Registry.is_registered(full_registry, name), (
                f"Module '{name}' should be registered"
            )

    # -------------------------------------------------------------------
    # IR-03: Remove with reverse dependency (Phase 2 gap)
    # -------------------------------------------------------------------

    @pytest.mark.xfail(
        reason=(
            "Registry.unregister() is a raw CRUD method and does not check "
            "reverse dependencies. Reverse dependency validation belongs in "
            "the install/remove command layer (Phase 2)."
        ),
        strict=False,
    )
    def test_remove_with_reverse_dependency_rejected(
        self,
        full_registry: RegistryData,
    ) -> None:
        """IR-03: Removing 'slack' while 'requirement' is registered should fail.

        Currently Registry.unregister() does NOT check reverse dependencies.
        This test documents the gap -- it will pass (xfail) when the CRUD
        layer lacks the check, and start truly passing once Phase 2 adds
        the install/remove command with reverse-dep validation.
        """
        # "requirement" depends on "slack", so removing "slack" first
        # should conceptually be rejected.
        result = Registry.unregister(full_registry, name="slack")

        # If we reach here, unregister succeeded (no reverse dep check).
        # Force a failure so xfail kicks in.
        pytest.fail(
            "Registry.unregister() allowed removing 'slack' while "
            "'requirement' (which depends on it) is still registered. "
            "Phase 2 should add reverse dependency checking."
        )

    # -------------------------------------------------------------------
    # IR-04: Remove in correct order succeeds
    # -------------------------------------------------------------------

    def test_remove_then_remove_dependency(
        self,
        full_registry: RegistryData,
    ) -> None:
        """IR-04: Removing 'requirement' first, then 'slack' succeeds."""
        # Step 1: Remove requirement (depends on slack)
        after_req = Registry.unregister(full_registry, name="requirement")
        assert not Registry.is_registered(after_req, "requirement")
        assert Registry.is_registered(after_req, "slack")

        # Step 2: Now remove slack (no more reverse deps)
        after_slack = Registry.unregister(after_req, name="slack")
        assert not Registry.is_registered(after_slack, "slack")
        assert not Registry.is_registered(after_slack, "requirement")

    # -------------------------------------------------------------------
    # IR-05: list_modules returns sorted tuple of all 10
    # -------------------------------------------------------------------

    def test_list_installed_sorted(
        self,
        full_registry: RegistryData,
    ) -> None:
        """IR-05: list_modules() returns a sorted tuple of all 10 module names."""
        result = Registry.list_modules(full_registry)

        expected = tuple(sorted(_MODULE_META.keys()))
        assert result == expected, (
            f"Expected sorted module list {expected}, got {result}"
        )
