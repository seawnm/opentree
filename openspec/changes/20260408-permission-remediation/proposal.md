# Proposal: Permission Architecture Remediation

## Problem

OpenTree v0.5.0 deployed with three permission defects that cause ALL features to silently fail:

1. **Wrong settings.json key names**: `SettingsGenerator` outputs `{"allowedTools": [...], "denyTools": [...]}` but Claude Code reads `{"permissions": {"allow": [...], "deny": [...]}}`
2. **No permission-mode CLI flag**: `_build_claude_args()` omits `--permission-mode` entirely; in `--print` mode Claude CLI defaults to denying all tool use
3. **Empty core baseline**: `modules/core/opentree.json` has `permissions.allow: []` — no Read/Write/Edit/Glob/Grep even for Owner

## Evidence

DOGI production (working) uses:
- settings.json: `{"permissions": {"allow": [...], "deny": [...]}}`
- Admin: `--dangerously-skip-permissions`
- Restricted: `--permission-mode dontAsk` + settings.json allow-list

OpenTree current (broken):
- settings.json: `{"allowedTools": [...], "denyTools": [...]}`
- All users: no permission flag at all
- Core module: zero baseline tools

## Design

### Change 1: Fix settings.json format

**File**: `src/opentree/generator/settings.py` — `generate_settings()`

```python
# BEFORE (line 136-139)
return {
    "allowedTools": all_allow,
    "denyTools": all_deny,
}

# AFTER
return {
    "permissions": {
        "allow": all_allow,
        "deny": all_deny,
    }
}
```

### Change 2: Add permission_mode to ClaudeProcess

**File**: `src/opentree/runner/claude_process.py`

Add `permission_mode` parameter to `_build_claude_args()`:

```python
def _build_claude_args(
    config: RunnerConfig,
    system_prompt: str,
    cwd: str,
    session_id: str = "",
    message: str = "",
    permission_mode: str = "restricted",  # NEW
) -> list[str]:
    args: list[str] = [
        config.claude_command,
        "--output-format",
        "stream-json",
        "--verbose",
        "--system-prompt",
        system_prompt,
    ]

    # Permission mode (NEW)
    if permission_mode == "owner":
        args.append("--dangerously-skip-permissions")
    else:
        args += ["--permission-mode", "dontAsk"]

    args.append("--print")

    if session_id:
        args += ["--resume", session_id]
    if message:
        args.append(message)
    return args
```

Add `permission_mode` parameter to `ClaudeProcess.__init__()`:

```python
def __init__(
    self,
    config: RunnerConfig,
    system_prompt: str,
    cwd: str,
    session_id: str = "",
    message: str = "",
    progress_callback: Optional[Callable] = None,
    extra_env: Optional[dict[str, str]] = None,
    permission_mode: str = "restricted",  # NEW
) -> None:
    # ... existing fields ...
    self._permission_mode = permission_mode
```

Update `run()` to pass it through:

```python
args = _build_claude_args(
    self._config,
    self._system_prompt,
    self._cwd,
    session_id=self._session_id,
    message=self._message,
    permission_mode=self._permission_mode,  # NEW
)
```

### Change 3: Dispatcher passes is_owner as permission_mode

**File**: `src/opentree/runner/dispatcher.py`

Dispatcher already computes `is_owner` in `_build_prompt_context()`. We need to also compute it at the `_process_task` level and pass to `ClaudeProcess`.

```python
# In _process_task(), after building PromptContext (step 5):
is_owner = bool(
    self._runner_config.admin_users
    and task.user_id in self._runner_config.admin_users
)
permission_mode = "owner" if is_owner else "restricted"

# Step 9: pass permission_mode to ClaudeProcess
claude = ClaudeProcess(
    config=self._runner_config,
    system_prompt=system_prompt,
    cwd=self._workspace_dir,
    session_id=session_id,
    message=message,
    progress_callback=_tracking_callback,
    permission_mode=permission_mode,  # NEW
)
```

Note: when `admin_users` is empty tuple (backward compat default), `is_owner` is False, so all users get `--permission-mode dontAsk`. This is safer than the current behavior (no flag = silent denial). Instances that want Owner bypass must set `admin_users` in `config/runner.json`.

### Change 4: Core module baseline permissions

**File**: `modules/core/opentree.json`

```json
"permissions": {
    "allow": [
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "Task"
    ],
    "deny": []
}
```

These are the minimum tools Claude needs to be useful. Module-specific tools (e.g. `Bash(uv run ...)`) are added by each module. Owner mode bypasses all of this via `--dangerously-skip-permissions`.

### Change 5: Test updates

**File**: `tests/test_settings.py`

All assertions change from `settings["allowedTools"]` / `settings["denyTools"]` to `settings["permissions"]["allow"]` / `settings["permissions"]["deny"]`.

## Backward Compatibility

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| Existing instances with old settings.json | Settings ignored by Claude Code | `opentree module refresh` regenerates settings.json |
| admin_users empty (default) | All users get restricted mode | Set admin_users in runner.json, or accept restricted mode with full tool access via core baseline |
| Modules with empty permissions | No change — core baseline covers them | N/A |

## Files Changed

| File | Change | Risk |
|------|--------|------|
| `src/opentree/generator/settings.py` | Fix output keys | High — all permission behavior |
| `src/opentree/runner/claude_process.py` | Add permission_mode param | High — CLI invocation |
| `src/opentree/runner/dispatcher.py` | Pass is_owner → permission_mode | Medium |
| `modules/core/opentree.json` | Add baseline allow list | Medium |
| `tests/test_settings.py` | Update key assertions | Low |
