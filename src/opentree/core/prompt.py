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
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opentree.core.config import UserConfig
from opentree.registry.models import RegistryData

# Lock that serialises the critical section inside collect_module_prompts
# where sys.modules is mutated.  One lock is sufficient because the
# thread-unique key already prevents functional collisions; the lock adds
# an extra layer of safety for the del/exec_module sequence.
_hook_lock = threading.Lock()

# Pattern for safe module names: letters, digits, hyphens, underscores only.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ------------------------------------------------------------------ #
# Hook cache (P2 perf fix: exec_module once, reuse on every request)
# ------------------------------------------------------------------ #


class PromptHookCache:
    """Cache for prompt_hook callables loaded from module hook files.

    Without caching, ``collect_module_prompts`` calls ``exec_module`` on
    every request, re-parsing each hook script and creating fresh module
    objects that accumulate in memory.  ``PromptHookCache`` loads each
    hook exactly once and returns the cached callable on subsequent calls.

    Thread safety is provided by a dedicated lock; concurrent callers
    block briefly during the first load but afterwards read from the
    dict without contention.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, Any] = {}  # module_name -> callable
        self._lock = threading.Lock()

    def get(self, name: str) -> Any | None:
        """Return cached hook callable, or ``None`` if not cached."""
        return self._hooks.get(name)

    def put(self, name: str, hook_fn: Any) -> None:
        """Store a hook callable."""
        with self._lock:
            self._hooks[name] = hook_fn

    def __contains__(self, name: str) -> bool:
        return name in self._hooks

    def __len__(self) -> int:
        return len(self._hooks)


def _is_safe_name(name: str) -> bool:
    """Return True iff *name* is a safe module-directory component.

    A safe name matches ``^[a-zA-Z0-9_-]+$`` — no dots, slashes, spaces,
    or other characters that could be used for path traversal.
    """
    if not name:
        return False
    return bool(_SAFE_NAME_RE.match(name))


def _is_safe_hook_path(hook_path: Path, modules_dir: Path) -> bool:
    """Return True iff the *resolved* ``hook_path`` is strictly inside
    *modules_dir*.

    Uses ``Path.resolve()`` so that any ``..`` components are eliminated
    before the comparison.  The hook path must be *strictly* inside
    ``modules_dir`` — equal to it is not acceptable.
    """
    try:
        resolved_hook = hook_path.resolve()
        resolved_modules = modules_dir.resolve()
    except (OSError, ValueError):
        return False

    # is_relative_to is available on Python 3.9+; we also exclude exact equality.
    try:
        return (
            resolved_hook.is_relative_to(resolved_modules)
            and resolved_hook != resolved_modules
        )
    except AttributeError:
        # Fallback for Python < 3.9 (should not occur in practice)
        try:
            resolved_hook.relative_to(resolved_modules)
            return resolved_hook != resolved_modules
        except ValueError:
            return False


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
    is_owner: bool = False
    thread_participants: tuple[str, ...] = ()
    opentree_home: str = ""

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
            "is_owner": self.is_owner,
            "is_admin": self.is_owner,  # backward compat alias
            "thread_participants": list(self.thread_participants),
            "opentree_home": self.opentree_home,
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
    if context.is_owner:
        parts.append("權限等級：Owner")
    else:
        parts.append("權限等級：一般使用者")
    if context.memory_path:
        parts.append(f"記憶檔案：{context.memory_path}")
        parts.append("如需了解此使用者的偏好和習慣，請使用 Read 工具讀取上述檔案。")
    return parts


def build_channel_block(context: PromptContext) -> list[str]:
    """Build channel and workspace context block.

    Mirrors DOGI's ``build_channel_block`` so that Claude can reference
    channel_id and thread_ts when invoking tools.
    """
    parts: list[str] = []
    if context.channel_id:
        parts.append(f"目前頻道 ID：{context.channel_id}")
    if context.thread_ts:
        parts.append(f"目前 Thread TS：{context.thread_ts}")
    if context.team_name:
        parts.append(f"目前 Workspace：{context.team_name}")
    if context.workspace and context.workspace != context.team_name:
        parts.append(f"目前工作區：{context.workspace}")
    return parts


# ------------------------------------------------------------------ #
# Module hook collection
# ------------------------------------------------------------------ #


def collect_module_prompts(
    opentree_home: Path,
    registry: RegistryData,
    context: PromptContext,
    *,
    hook_cache: PromptHookCache | None = None,
) -> list[str]:
    """Load and execute ``prompt_hook`` from each registered module.

    Each module's ``opentree.json`` may declare a ``"prompt_hook"`` field
    pointing to a Python file.  That file must define a callable
    ``prompt_hook(context: dict) -> list[str]``.

    Errors in individual hooks are caught and reported as comment lines
    rather than propagated, so one broken module cannot break the entire
    prompt.

    Parameters
    ----------
    hook_cache:
        Optional :class:`PromptHookCache`.  When provided, hook callables
        are loaded once via ``exec_module`` and then reused on every
        subsequent call — eliminating per-request re-parsing and the
        module-object accumulation that caused a memory leak.

    Thread safety
    -------------
    Each invocation uses a key that embeds the current thread id so that
    concurrent calls never share a ``sys.modules`` entry.  The module is
    removed from ``sys.modules`` after execution so that entries do not
    accumulate.  A module-level lock (``_hook_lock``) serialises the
    mutation window for extra safety.

    Security
    --------
    Both the module *name* (from the registry) and the *hook_file* value
    from the manifest are validated before use:

    * ``name`` must match ``^[a-zA-Z0-9_-]+$``.
    * ``hook_file`` must not contain any directory separator or ``..``
      component.
    * The resolved ``hook_path`` must lie strictly inside
      ``opentree_home / "modules"``.
    """
    results: list[str] = []
    context_dict = context.to_dict()
    modules_dir = opentree_home / "modules"
    thread_id = threading.get_ident()

    for name, _entry in registry.modules:
        # --- Cache hit: skip all validation & loading -----------------------
        if hook_cache is not None:
            cached_fn = hook_cache.get(name)
            if cached_fn is not None:
                try:
                    lines = cached_fn(context_dict)
                    if isinstance(lines, list):
                        results.extend(lines)
                except Exception as exc:
                    results.append(f"# [{name}] prompt_hook error: {exc}")
                continue

        # --- Security: validate module name ---------------------------------
        if not _is_safe_name(name):
            continue

        manifest_path = modules_dir / name / "opentree.json"
        if not manifest_path.is_file():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        hook_file = manifest.get("prompt_hook")
        if not hook_file:
            continue

        # --- Security: validate hook_file -----------------------------------
        # Must be a plain filename with no directory separators or traversal.
        if "/" in hook_file or "\\" in hook_file or ".." in hook_file:
            continue

        hook_path = modules_dir / name / hook_file

        # --- Security: resolved path must stay inside modules_dir -----------
        if not _is_safe_hook_path(hook_path, modules_dir):
            continue

        if not hook_path.is_file():
            continue

        # --- Thread-safe dynamic import -------------------------------------
        # Use a thread-unique key so concurrent calls cannot collide in
        # sys.modules.  Wrap the mutation window with _hook_lock.
        mod_key = f"opentree_hook_{name}_{thread_id}"

        try:
            with _hook_lock:
                if mod_key in sys.modules:
                    del sys.modules[mod_key]

                spec = importlib.util.spec_from_file_location(
                    mod_key, str(hook_path)
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_key] = mod  # register before exec so relative imports work
                spec.loader.exec_module(mod)

            # Call the hook outside the lock — the module object is local
            hook_fn = getattr(mod, "prompt_hook", None)
            if callable(hook_fn):
                lines = hook_fn(context_dict)
                if isinstance(lines, list):
                    results.extend(lines)
                # Cache the callable for future calls
                if hook_cache is not None:
                    hook_cache.put(name, hook_fn)
        except Exception as exc:
            results.append(f"# [{name}] prompt_hook error: {exc}")
        finally:
            # Always clean up the thread-local sys.modules entry
            with _hook_lock:
                sys.modules.pop(mod_key, None)

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
        build_channel_block(context),
        collect_module_prompts(opentree_home, registry, context),
    ]

    lines: list[str] = []
    for block in blocks:
        if block:
            lines.extend(block)
            lines.append("")  # blank line separator

    return "\n".join(lines).strip() + "\n"
