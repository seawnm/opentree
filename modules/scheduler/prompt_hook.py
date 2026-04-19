"""Scheduler module prompt hook: inject scheduling rules into system prompt.

These rules are critical for Codex CLI (AGENTS.md) because the static
rules/*.md files are only available to Claude CLI via .claude/rules/ symlinks.
"""

from __future__ import annotations

from typing import Any


def prompt_hook(context: dict[str, Any]) -> list[str]:
    """Inject scheduling-specific rules into the system prompt.

    These rules cover BUG-06 issues:
    - Tool path failure recovery (don't give up on ModuleNotFoundError)
    - Workspace name validation (must not use "default")
    - Chain task intermediate result path conventions

    Args:
        context: PromptContext.to_dict() output.

    Returns:
        List of prompt lines to inject into AGENTS.md (via system_prompt).
    """
    opentree_home = context.get("opentree_home", "")
    if not opentree_home:
        return []

    return [
        "## 排程工具使用規則",
        "",
        "**工具執行失敗時的處理順序（不可第一步失敗就放棄）：**",
        f"1. 先嘗試：`uv run --directory {opentree_home} python -m scripts.tools.schedule_tool ...`",
        f"2. 若失敗，嘗試：`{opentree_home}/.venv/bin/python -m scripts.tools.schedule_tool ...`",
        f"3. 若仍失敗，用 `find {opentree_home} -name 'schedule_tool.py'` 確認檔案存在",
        "4. 確認路徑後再嘗試不同模組路徑（如 `opentree.tools.schedule_tool`）",
        "5. 以上全部失敗才告知使用者工具不可用",
        "",
        "**`--workspace` 參數規則：**",
        "- 必須使用 system prompt 中「目前頻道工作區」的實際值（如 `ai-room`、`beta-room`）",
        "- 禁止使用 `default` 作為 workspace 名稱，`default` 是設定預設值的佔位符，不是真實工作區名稱",
        "- 若 system prompt 顯示「目前頻道工作區：default」，須先向使用者確認實際頻道名稱",
        "",
        "**鏈式任務中間結果路徑慣例：**",
        "- Step 1 prompt：「搜尋後儲存到 /tmp/opentree/chains/{chain-name}/step1.md」",
        "- Step 2 prompt：「先讀取 /tmp/opentree/chains/{chain-name}/step1.md，再整理成報告...」",
        "- chain-name 使用描述性名稱（如 `weekly-ai-report`），不用時間戳記",
    ]
