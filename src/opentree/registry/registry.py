"""Registry CRUD operations for OpenTree modules.

All methods are static (pure functions, no instance state).
All mutation methods return NEW RegistryData instances — never mutate.
File writes use atomic pattern: write to .tmp, then os.replace().
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

if sys.platform != "win32":
    import fcntl as _fcntl
else:
    _fcntl = None  # type: ignore[assignment]

from opentree.registry.models import RegistryData, RegistryEntry

_SUPPORTED_VERSION = 1


class Registry:
    """Static methods for registry CRUD operations.

    The registry file is a JSON file tracking which modules are installed,
    stored at ``$OPENTREE_HOME/config/registry.json``.
    """

    @staticmethod
    @contextmanager
    def lock(registry_path: Path, *, timeout: float = 10.0) -> Iterator[None]:
        """Acquire exclusive file lock for registry operations.

        Uses ``fcntl.flock`` with ``LOCK_NB`` (non-blocking) for immediate
        feedback when another operation holds the lock.

        Args:
            registry_path: Path to registry.json (lock file derived from it).
            timeout: Unused in the non-blocking implementation; kept for
                future extension.

        Yields:
            Nothing — used as a context manager guard.

        Raises:
            TimeoutError: If the lock is already held by another process.

        Usage::

            with Registry.lock(registry_path):
                data = Registry.load(registry_path)
                data = Registry.register(data, ...)
                Registry.save(registry_path, data)
        """
        # Lock file in /tmp (native Linux fs) because flock does not work on DrvFs
        # (/mnt/ in WSL2). Hash the registry path to create a unique lock per instance.
        path_hash = hashlib.md5(str(registry_path).encode()).hexdigest()[:16]
        lock_path = Path(f"/tmp/opentree-registry-{path_hash}.lock")
        lock_file = open(lock_path, "w")  # noqa: SIM115
        locked = False
        try:
            if _fcntl is not None:
                try:
                    _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    lock_file.close()
                    msg = (
                        f"Another opentree operation is in progress (lock: {lock_path}). "
                        "Wait for it to complete or remove the lock file manually."
                    )
                    raise TimeoutError(msg)
            # On Windows: advisory lock only (no enforcement)
            yield
        finally:
            if _fcntl is not None and locked:
                _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)
            if not lock_file.closed:
                lock_file.close()

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
        # Crash recovery: if registry.json is missing but a valid .tmp exists,
        # promote the newest valid .tmp to registry.json.
        if not registry_path.exists():
            tmp_candidates = sorted(
                registry_path.parent.glob(f"{registry_path.stem}.*.tmp"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            ) if registry_path.parent.exists() else []
            recovered = False
            for tmp in tmp_candidates:
                try:
                    tmp_text = tmp.read_text(encoding="utf-8")
                    raw_tmp = json.loads(tmp_text)
                    if isinstance(raw_tmp, dict) and raw_tmp.get("version") == _SUPPORTED_VERSION:
                        os.replace(tmp, registry_path)
                        recovered = True
                        break
                except (json.JSONDecodeError, OSError):
                    tmp.unlink(missing_ok=True)
            if not recovered:
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
                    link_method=fields.get("link_method", "symlink"),
                    depends_on=tuple(fields.get("depends_on", ())),
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

        modules_dict: dict[str, dict[str, Any]] = {}
        for name, entry in data.modules:
            entry_dict: dict[str, Any] = {
                "name": entry.name,
                "version": entry.version,
                "module_type": entry.module_type,
                "installed_at": entry.installed_at,
                "source": entry.source,
                "link_method": entry.link_method,
            }
            if entry.depends_on:
                entry_dict["depends_on"] = list(entry.depends_on)
            modules_dict[name] = entry_dict

        payload: dict[str, Any] = {
            "version": data.version,
            "modules": modules_dict,
        }

        tmp_path = registry_path.with_name(f"{registry_path.stem}.{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, registry_path)

    @staticmethod
    def register(
        data: RegistryData,
        *,
        name: str,
        version: str,
        module_type: str,
        source: str = "bundled",
        link_method: str = "symlink",
        depends_on: tuple[str, ...] = (),
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
            link_method: How the module files were linked
                (``"symlink"``, ``"junction"``, or ``"copy"``).
            depends_on: Module names this entry depends on.

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
            link_method=link_method,
            depends_on=depends_on,
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
