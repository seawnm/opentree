"""Data models for the module registry.

All dataclasses use frozen=True for immutability.
Mutation methods return new instances — never modify in place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegistryEntry:
    """A single module entry in the registry."""

    name: str
    version: str
    module_type: str  # "pre-installed" or "optional"
    installed_at: str  # ISO 8601 datetime string
    source: str  # "bundled" or git URL
    link_method: str = "symlink"  # "symlink" | "junction" | "copy"
    depends_on: tuple[str, ...] = ()  # module names this entry depends on


@dataclass(frozen=True)
class RegistryData:
    """The complete registry state.

    Immutable — mutation methods return new instances.
    Uses tuple of tuples instead of dict for true immutability
    in a frozen dataclass.
    """

    version: int  # schema version, always 1
    modules: tuple[tuple[str, RegistryEntry], ...]  # sorted (name, entry) pairs

    def get(self, name: str) -> RegistryEntry | None:
        """Look up a module by name."""
        for n, entry in self.modules:
            if n == name:
                return entry
        return None

    def names(self) -> tuple[str, ...]:
        """Return sorted tuple of module names."""
        return tuple(n for n, _ in self.modules)
