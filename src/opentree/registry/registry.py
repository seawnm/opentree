"""Registry CRUD operations for OpenTree modules.

All methods are static (pure functions, no instance state).
All mutation methods return NEW RegistryData instances — never mutate.
File writes use atomic pattern: write to .tmp, then os.replace().
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opentree.registry.models import RegistryData, RegistryEntry

_SUPPORTED_VERSION = 1


class Registry:
    """Static methods for registry CRUD operations.

    The registry file is a JSON file tracking which modules are installed,
    stored at ``$OPENTREE_HOME/config/registry.json``.
    """

    @staticmethod
    def load(registry_path: Path) -> RegistryData:
        """Load registry data from a JSON file.

        Args:
            registry_path: Path to registry.json.

        Returns:
            RegistryData parsed from the file, or an empty RegistryData
            (version=1, modules=()) if the file does not exist.

        Raises:
            ValueError: If the file contains malformed JSON or an
                unsupported schema version.
        """
        if not registry_path.exists():
            return RegistryData(version=_SUPPORTED_VERSION, modules=())

        text = registry_path.read_text(encoding="utf-8")

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            msg = f"Registry file is malformed JSON: {exc}"
            raise ValueError(msg) from exc

        if not isinstance(raw, dict):
            msg = "Registry file is malformed JSON: expected a JSON object"
            raise ValueError(msg)

        version = raw.get("version")
        if version != _SUPPORTED_VERSION:
            msg = f"Unsupported registry version: {version} (expected {_SUPPORTED_VERSION})"
            raise ValueError(msg)

        raw_modules: dict[str, Any] = raw.get("modules", {})
        entries: list[tuple[str, RegistryEntry]] = []
        for name, fields in sorted(raw_modules.items()):
            try:
                entry = RegistryEntry(
                    name=fields.get("name", name),
                    version=fields["version"],
                    module_type=fields["module_type"],
                    installed_at=fields["installed_at"],
                    source=fields["source"],
                )
            except KeyError as exc:
                msg = f"Registry entry for '{name}' is missing required field {exc}"
                raise ValueError(msg) from exc
            entries.append((name, entry))

        return RegistryData(version=_SUPPORTED_VERSION, modules=tuple(entries))

    @staticmethod
    def save(registry_path: Path, data: RegistryData) -> None:
        """Save registry data to a JSON file atomically.

        Creates parent directories if they do not exist.
        Writes to a temporary file first, then uses ``os.replace()``
        for atomic swap.

        Args:
            registry_path: Path to registry.json.
            data: The RegistryData to persist.
        """
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        modules_dict: dict[str, dict[str, str]] = {}
        for name, entry in data.modules:
            modules_dict[name] = {
                "name": entry.name,
                "version": entry.version,
                "module_type": entry.module_type,
                "installed_at": entry.installed_at,
                "source": entry.source,
            }

        payload = {
            "version": data.version,
            "modules": modules_dict,
        }

        tmp_path = registry_path.with_name(f"{registry_path.stem}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, registry_path)

    @staticmethod
    def register(
        data: RegistryData,
        *,
        name: str,
        version: str,
        module_type: str,
        source: str = "bundled",
    ) -> RegistryData:
        """Register a module, returning a new RegistryData.

        If a module with the same name already exists, it is replaced
        (updated). The original ``data`` is never mutated.

        Args:
            data: Current registry state.
            name: Module name (must be non-empty).
            version: Semver version string.
            module_type: ``"pre-installed"`` or ``"optional"``.
            source: ``"bundled"`` or a git URL.

        Returns:
            A new RegistryData with the module added or updated.

        Raises:
            ValueError: If ``name`` is empty.
        """
        if not name:
            msg = "Module name must not be empty"
            raise ValueError(msg)

        installed_at = datetime.now(timezone.utc).isoformat()
        new_entry = RegistryEntry(
            name=name,
            version=version,
            module_type=module_type,
            installed_at=installed_at,
            source=source,
        )

        # Build new modules list, replacing existing entry if present
        existing = [(n, e) for n, e in data.modules if n != name]
        existing.append((name, new_entry))
        existing.sort(key=lambda pair: pair[0])

        return RegistryData(version=data.version, modules=tuple(existing))

    @staticmethod
    def unregister(data: RegistryData, *, name: str) -> RegistryData:
        """Remove a module from the registry, returning a new RegistryData.

        The original ``data`` is never mutated.

        Args:
            data: Current registry state.
            name: Module name to remove.

        Returns:
            A new RegistryData without the specified module.

        Raises:
            KeyError: If the module is not registered.
        """
        found = any(n == name for n, _ in data.modules)
        if not found:
            msg = f"Module '{name}' is not registered"
            raise KeyError(msg)

        remaining = tuple((n, e) for n, e in data.modules if n != name)
        return RegistryData(version=data.version, modules=remaining)

    @staticmethod
    def is_registered(data: RegistryData, name: str) -> bool:
        """Check whether a module is registered.

        Args:
            data: Current registry state.
            name: Module name to check.

        Returns:
            True if the module is in the registry, False otherwise.
        """
        return data.get(name) is not None

    @staticmethod
    def list_modules(data: RegistryData) -> tuple[str, ...]:
        """Return a sorted tuple of registered module names.

        Args:
            data: Current registry state.

        Returns:
            Sorted tuple of module name strings.
        """
        return data.names()
