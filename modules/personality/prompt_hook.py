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
    """Inject capability summary and critical conversation rules into system prompt.

    Args:
        context: PromptContext.to_dict() output, includes opentree_home.

    Returns:
        A list of prompt lines, or an empty list on any error.
    """
    opentree_home = context.get("opentree_home", "")
    if not opentree_home:
        return []

    home = Path(opentree_home).resolve()

    try:
        installed = _load_installed_modules(home)
        allowed_tools = _load_allowed_tools(home)
        capability_lines = _build_capability_lines(installed, allowed_tools, home)
        conversation_lines = _build_conversation_rules()
        return capability_lines + ([""] if capability_lines and conversation_lines else []) + conversation_lines
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


def _build_conversation_rules() -> list[str]:
    """Build critical conversation behavior rules for system prompt injection.

    These rules are injected into the system prompt (higher priority than
    static CLAUDE.md rules) to ensure consistent behavior.
    """
    return [
        "## 🔴 對話強制規則（不可違反）",
        "",
        "**需求釐清：每次回覆最多只能問 1 個問題，絕對禁止在單一回覆中問多個問題。**",
        "- 違反條件：回覆中出現 2 個以上問號（?？）即為違反",
        "- 正確做法：先問最關鍵的一個問題，等使用者回答後再問下一個",
        "- 使用 TEDW 順序：先問「你目前是怎麼做這件事的？」",
        "",
        "**輸出品質：回覆前必須確認數量達標、格式正確、檔案已上傳。**",
        "- 若使用者要求「至少 N 則」，必須確保數量 ≥ N，不足則繼續蒐集",
        "- 產生檔案後必須用 upload-tool 上傳到 Slack，不可只回覆本機路徑",
        "- 產生 HTML/Markdown 文件時，必須清理所有 <URL|text> 格式為 [text](URL)",
        "",
        "**技術可行性：遇到不合理約束（如 5 秒完成耗時任務），必須先說明再協商，不可靜默 timeout。**",
        "",
        "**檔案交付：產生任何檔案後，必須呼叫 upload-tool 上傳到 Slack thread，不可只回覆本機路徑。**",
        "- Owner/Admin：檔案存 <OPENTREE_HOME>/workspace/files/<thread_ts>/（持久化）",
        "- 一般使用者：檔案存 /tmp/opentree/<thread_ts>/（暫存）",
        "- 無論哪種使用者，產檔後都必須執行上傳",
    ]
