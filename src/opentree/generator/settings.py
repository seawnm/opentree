"""Settings generator for OpenTree workspace.

Manages ``workspace/.claude/settings.json`` by aggregating module permissions
from a source-of-truth file (``config/permissions.json``).

Architecture::

    install module  -> add_module_permissions()  -> update permissions.json
    remove module   -> remove_module_permissions() -> update permissions.json
    either          -> write_settings()           -> regenerate settings.json

All file writes use atomic pattern: write to .tmp, fsync, os.replace().
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PERMISSIONS_VERSION = 1


@dataclass(frozen=True)
class PermissionSet:
    """Aggregated permissions from all modules."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()


class SettingsGenerator:
    """Manages .claude/settings.json from module permissions.

    The source of truth is ``config/permissions.json`` which tracks
    per-module allow/deny patterns. ``settings.json`` is a derived
    artifact that is regenerated on every change.

    Args:
        opentree_home: Path to the OPENTREE_HOME directory.
    """

    def __init__(self, opentree_home: Path) -> None:
        self._home = opentree_home
        self._permissions_path = opentree_home / "config" / "permissions.json"
        self._settings_path = (
            opentree_home / "workspace" / ".claude" / "settings.json"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_module_permissions(
        self,
        module_name: str,
        allow: Sequence[str],
        deny: Sequence[str],
    ) -> None:
        """Record a module's permissions in permissions.json.

        If the module already exists, its entry is replaced.

        Args:
            module_name: The module identifier (e.g. ``"slack"``).
            allow: Permission allow patterns.
            deny: Permission deny patterns.
        """
        data = self._load_permissions()
        data["modules"][module_name] = {
            "allow": list(allow),
            "deny": list(deny),
        }
        self._save_permissions(data)

    def remove_module_permissions(self, module_name: str) -> None:
        """Remove a module's permissions from permissions.json.

        Idempotent: does nothing if the module is not present.

        Args:
            module_name: The module identifier to remove.
        """
        data = self._load_permissions()
        data["modules"].pop(module_name, None)
        self._save_permissions(data)

    def reset_module_permissions(self) -> None:
        """Clear all module permissions, preserving user_custom.

        Used by ``refresh`` to wipe stale entries before rebuilding
        from the current registry.
        """
        data = self._load_permissions()
        data["modules"] = {}
        self._save_permissions(data)

    def generate_settings(self) -> dict[str, Any]:
        """Generate settings.json content from permissions.json.

        Steps:
            1. Load permissions.json
            2. Aggregate all allow + deny across modules
            3. Resolve ``$OPENTREE_HOME`` placeholders
            4. Deduplicate (preserving order)
            5. Return settings dict

        Returns:
            A dict suitable for writing as ``settings.json``.
        """
        data = self._load_permissions()

        all_allow: list[str] = []
        all_deny: list[str] = []

        for _module_name, entry in sorted(data["modules"].items()):
            all_allow.extend(entry.get("allow", []))
            all_deny.extend(entry.get("deny", []))

        # Also include user_custom permissions
        user_custom = data.get("user_custom", {})
        all_allow.extend(user_custom.get("allow", []))
        all_deny.extend(user_custom.get("deny", []))

        all_allow = self._resolve_placeholders(all_allow)
        all_deny = self._resolve_placeholders(all_deny)

        all_allow = self._deduplicate(all_allow)
        all_deny = self._deduplicate(all_deny)

        return {
            "allowedTools": all_allow,
            "denyTools": all_deny,
        }

    def write_settings(self) -> None:
        """Generate and atomically write settings.json.

        Creates the ``.claude/`` directory if it does not exist.
        """
        settings = self.generate_settings()
        _atomic_write_json(self._settings_path, settings)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_permissions(self) -> dict[str, Any]:
        """Load permissions.json. Returns empty structure if missing."""
        if not self._permissions_path.exists():
            return _empty_permissions()
        text = self._permissions_path.read_text(encoding="utf-8")
        data: dict[str, Any] = json.loads(text)
        return data

    def _save_permissions(self, data: dict[str, Any]) -> None:
        """Atomically write permissions.json."""
        _atomic_write_json(self._permissions_path, data)

    def _resolve_placeholders(self, patterns: list[str]) -> list[str]:
        """Replace $OPENTREE_HOME with actual path in permission patterns.

        Backslashes are normalized to forward slashes to ensure
        consistent patterns across platforms.
        """
        home_str = str(self._home).replace("\\", "/")
        return [
            p.replace("$OPENTREE_HOME", home_str)
            for p in patterns
        ]

    def _deduplicate(self, items: list[str]) -> list[str]:
        """Deduplicate while preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _empty_permissions() -> dict[str, Any]:
    """Return an empty permissions.json structure."""
    return {
        "version": _PERMISSIONS_VERSION,
        "modules": {},
        "user_custom": {
            "allow": [],
            "deny": [],
        },
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic JSON write with fsync.

    Creates parent directories if needed. Writes to a temporary file
    in the same directory, then uses ``os.replace()`` for atomic swap.

    Args:
        path: Target file path.
        data: JSON-serializable dict to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    # Create temp file in same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
