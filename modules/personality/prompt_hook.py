"""Personality module prompt hook: inject dynamic capability summary.

At runtime, reads the installed module registry and the workspace
settings.json to determine which capabilities are *actually* available,
then injects a capability summary so the bot only advertises what works.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module → human-readable capability mapping
# Each key is a module directory name; value is the Chinese capability label
# shown when that module is active.
# ---------------------------------------------------------------------------
_MODULE_CAPABILITIES: dict[str, str] = {
    "memory":      "記憶管理（記住偏好、跨 Thread 保留）",
    "scheduler":   "排程與提醒（一次性、週期性、任務鏈）",
    "slack":       "Slack 查詢（頻道、Thread、使用者資訊）",
    "requirement": "需求管理（收集、訪談、追蹤）",
    "youtube":     "YouTube 搜尋（影片資訊、字幕查詢）",
    "stt":         "語音轉文字（m4a/mp3 音訊轉錄）",
}

# Core capabilities that are always present when core module is installed
# (they rely on core's Read/Write/Grep/Glob allow grants, not module-specific tools)
_CORE_DEPENDENT_MODULES = {"memory", "requirement", "youtube"}

# Modules that require module-specific Bash patterns to function
# Maps module name → a substring that must appear in some allowed Bash rule
_BASH_DEPENDENT_MODULES: dict[str, str] = {
    "scheduler": "schedule_tool",
    "slack":     "slack_query_tool",
    "stt":       "stt",
}


def prompt_hook(context: dict[str, Any]) -> list[str]:
    """Inject a capability summary based on runtime module + permission state.

    Args:
        context: PromptContext.to_dict() output, includes opentree_home.

    Returns:
        A list of prompt lines describing actually-available capabilities,
        or an empty list on any error (fail-open: better to omit than crash).
    """
    opentree_home = context.get("opentree_home", "")
    if not opentree_home:
        return []

    home = Path(opentree_home).resolve()

    try:
        installed = _load_installed_modules(home)
        allowed_tools = _load_allowed_tools(home)
        return _build_capability_lines(installed, allowed_tools, home)
    except Exception as exc:
        _log.warning("[personality] prompt_hook failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def _load_installed_modules(home: Path) -> list[str]:
    """Return list of installed module names from registry.json."""
    registry_path = home / "registry.json"
    if not registry_path.is_file():
        return []
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    # registry.json format: {"modules": {"name": {...}, ...}} or list
    modules = data.get("modules", {})
    if isinstance(modules, dict):
        return list(modules.keys())
    if isinstance(modules, list):
        return [m.get("name", "") for m in modules if isinstance(m, dict)]
    return []


def _load_allowed_tools(home: Path) -> list[str]:
    """Return the allow list from workspace/.claude/settings.json."""
    settings_path = home / "workspace" / ".claude" / "settings.json"
    if not settings_path.is_file():
        return []
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    perms = data.get("permissions", {})
    allow = perms.get("allow", [])
    return allow if isinstance(allow, list) else []


# ---------------------------------------------------------------------------
# Core decision: is a module's capability actually available?
# ---------------------------------------------------------------------------


def _is_module_available(
    module_name: str,
    allowed_tools: list[str],
    home: Path,
) -> bool:
    """Determine if a module's capability is actually usable at runtime.

    This is the key design decision: a module is "installed" in the registry,
    but its tools might be blocked by settings.json or missing entirely.

    The challenge:
    - Core-dependent modules (memory, requirement) rely on Read/Write from
      core's allow grants — not their own permissions.allow.
    - Bash-dependent modules (scheduler, slack) need specific Bash patterns
      that MUST appear in the runtime allow list to work.

    Strategy C (optimistic default):
    - Bash-dependent modules: require a matching keyword substring in allowed_tools.
    - Everything else (core-dependent or unknown): assume available (return True).
    """
    if module_name in _BASH_DEPENDENT_MODULES:
        keyword = _BASH_DEPENDENT_MODULES[module_name]
        return any(keyword in rule for rule in allowed_tools)
    return True


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------


def _build_capability_lines(
    installed: list[str],
    allowed_tools: list[str],
    home: Path,
) -> list[str]:
    """Build the capability summary lines for system prompt injection."""
    available: list[str] = []

    for module_name, label in _MODULE_CAPABILITIES.items():
        if module_name not in installed:
            continue
        if _is_module_available(module_name, allowed_tools, home):
            available.append(f"- {label}")

    if not available:
        return []

    return [
        "## 目前可用功能",
        *available,
        "（以上功能目前可正常使用；若某項功能失敗，請主動告知使用者原因）",
    ]
