"""System prompt assembly for OpenTree.

Builds the ``--system-prompt`` string that is passed to Claude CLI.
Each ``build_*`` function returns a list of lines; ``assemble_system_prompt``
joins them with blank-line separators.

Module hooks are loaded dynamically from each registered module's
``prompt_hook.py`` (as declared in the module's ``opentree.json``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opentree.core.config import UserConfig
from opentree.registry.models import RegistryData


@dataclass(frozen=True)
class PromptContext:
    """Context for prompt assembly.  All fields have safe defaults."""

    user_id: str = ""
    user_name: str = ""
    user_display_name: str = ""
    channel_id: str = ""
    thread_ts: str = ""
    workspace: str = ""
    team_name: str = ""
    memory_path: str = ""
    is_new_user: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for passing to module hooks."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "user_display_name": self.user_display_name,
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "workspace": self.workspace,
            "team_name": self.team_name,
            "memory_path": self.memory_path,
            "is_new_user": self.is_new_user,
        }


# ------------------------------------------------------------------ #
# Block builders
# ------------------------------------------------------------------ #


def build_date_block(timezone: str = "Asia/Taipei") -> list[str]:
    """Return date lines for the given *timezone*."""
    now = datetime.now(ZoneInfo(timezone))
    weekday_map = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}
    return [
        f"今日日期（{timezone}）：{now.strftime('%Y-%m-%d')}（星期{weekday_map[now.weekday()]}）",
        f"此日期為 {timezone} 時區，以此為準。",
    ]


def build_config_block(config: UserConfig) -> list[str]:
    """System config summary."""
    bot = config.bot_name or "OpenTree"
    return [f"Bot：{bot}"]


def build_paths_block(config: UserConfig) -> list[str]:
    """Unified path block (always forward slashes)."""
    home = config.opentree_home.replace("\\", "/")
    return [
        f"OPENTREE_HOME：{home}",
        f"模組目錄：{home}/modules/",
        f"工作區目錄：{home}/workspace/",
        f"資料目錄：{home}/data/",
    ]


def build_identity_block(context: PromptContext) -> list[str]:
    """User identity block."""
    parts: list[str] = []
    if context.user_display_name:
        if context.user_name and context.user_name != context.user_display_name:
            parts.append(
                f"使用者：{context.user_display_name}（{context.user_name}）"
            )
        else:
            parts.append(f"使用者：{context.user_display_name}")
    if context.user_id:
        parts.append(f"使用者 ID：{context.user_id}")
    if context.memory_path:
        parts.append(f"記憶檔案：{context.memory_path}")
    return parts


# ------------------------------------------------------------------ #
# Module hook collection
# ------------------------------------------------------------------ #


def collect_module_prompts(
    opentree_home: Path,
    registry: RegistryData,
    context: PromptContext,
) -> list[str]:
    """Load and execute ``prompt_hook`` from each registered module.

    Each module's ``opentree.json`` may declare a ``"prompt_hook"`` field
    pointing to a Python file.  That file must define a callable
    ``prompt_hook(context: dict) -> list[str]``.

    Errors in individual hooks are caught and reported as comment lines
    rather than propagated, so one broken module cannot break the entire
    prompt.
    """
    results: list[str] = []
    context_dict = context.to_dict()

    for name, _entry in registry.modules:
        manifest_path = opentree_home / "modules" / name / "opentree.json"
        if not manifest_path.is_file():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        hook_file = manifest.get("prompt_hook")
        if not hook_file:
            continue

        hook_path = opentree_home / "modules" / name / hook_file
        if not hook_path.is_file():
            continue

        try:
            # Use a unique module name to avoid collisions in sys.modules
            mod_key = f"opentree_hook_{name}"
            if mod_key in sys.modules:
                del sys.modules[mod_key]

            spec = importlib.util.spec_from_file_location(mod_key, str(hook_path))
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            hook_fn = getattr(mod, "prompt_hook", None)
            if callable(hook_fn):
                lines = hook_fn(context_dict)
                if isinstance(lines, list):
                    results.extend(lines)
        except Exception as exc:
            results.append(f"# [{name}] prompt_hook error: {exc}")

    return results


# ------------------------------------------------------------------ #
# Top-level assembly
# ------------------------------------------------------------------ #


def assemble_system_prompt(
    opentree_home: Path,
    registry: RegistryData,
    config: UserConfig,
    context: PromptContext,
) -> str:
    """Assemble the complete ``--system-prompt`` string.

    Collects core blocks (date, config, paths, identity) and module
    hooks, then joins them with blank-line separators.

    Returns:
        A string ending with a single newline.
    """
    blocks: list[list[str]] = [
        build_date_block(),
        build_config_block(config),
        build_paths_block(config),
        build_identity_block(context),
        collect_module_prompts(opentree_home, registry, context),
    ]

    lines: list[str] = []
    for block in blocks:
        if block:
            lines.extend(block)
            lines.append("")  # blank line separator

    return "\n".join(lines).strip() + "\n"
