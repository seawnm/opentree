# Flow Simulation: Permission Remediation

## Normal Flows

### Flow 1: Owner sends message

```
1. Slack event → Receiver → Dispatcher.dispatch(task)
2. Dispatcher.parse_message() → not admin command
3. Dispatcher._process_task(task)
4. admin_users = ("U_OWNER",), task.user_id = "U_OWNER"
   → is_owner = True
   → permission_mode = "owner"
5. ClaudeProcess(permission_mode="owner")
6. _build_claude_args() → args include "--dangerously-skip-permissions"
7. No settings.json check — all tools available
```

**Result**: Owner has unrestricted tool access. Claude can use Read, Write, Edit, Bash, WebSearch, etc. without any allowlist filtering.

**CLI args produced**:
```
claude --output-format stream-json --verbose --system-prompt <prompt> --dangerously-skip-permissions --print <message>
```

### Flow 2: Restricted user sends message

```
1. Slack event → Receiver → Dispatcher.dispatch(task)
2. Dispatcher.parse_message() → not admin command
3. Dispatcher._process_task(task)
4. admin_users = ("U_OWNER",), task.user_id = "U_USER"
   → is_owner = False
   → permission_mode = "restricted"
5. ClaudeProcess(permission_mode="restricted")
6. _build_claude_args() → args include "--permission-mode dontAsk"
7. Claude CLI reads workspace/.claude/settings.json
8. permissions.allow contains: [Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Task, Bash(uv run ...*schedule*), Bash(uv run ...*upload*), ...]
9. permissions.deny contains: [mcp__slack_send, mcp__slack_draft, mcp__slack_schedule]
10. Tool invocations auto-approved if in allow, auto-denied if not
```

**Result**: Restricted user can use baseline tools + module-specific tools. Denied tools silently blocked.

**CLI args produced**:
```
claude --output-format stream-json --verbose --system-prompt <prompt> --permission-mode dontAsk --print <message>
```

### Flow 3: Owner triggers memory write (needs Write tool)

```
1. Owner sends "remember that I like dark mode"
2. permission_mode = "owner" → --dangerously-skip-permissions
3. Claude decides to use Write tool on data/memory/owner/memory.md
4. Tool auto-approved (no permission check in skip mode)
5. Write succeeds
```

**Result**: Works. Owner bypass means Write is always available.

### Flow 4: Restricted user uses scheduler tool (needs Bash)

```
1. User sends "set a reminder in 5 minutes"
2. permission_mode = "restricted" → --permission-mode dontAsk
3. Claude reads scheduler module rules → knows to call:
   Bash(uv run --directory /path/to python -m scripts.tools.schedule_tool create ...)
4. Claude CLI checks settings.json:
   permissions.allow includes "Bash(uv run --directory *:*schedule_tool*)" → MATCH
5. Tool auto-approved
6. Bash executes schedule_tool
```

**Result**: Works. The scheduler module's allow pattern matches the actual CLI invocation.

### Flow 5: Owner does web search (needs WebSearch)

```
1. Owner sends "search for the latest Claude Code release notes"
2. permission_mode = "owner" → --dangerously-skip-permissions
3. Claude invokes WebSearch tool
4. Tool auto-approved (skip mode)
```

**Result**: Works. No permission check needed for Owner.

**What about restricted user doing web search?**:
```
1. permission_mode = "restricted" → --permission-mode dontAsk
2. Claude invokes WebSearch
3. settings.json permissions.allow includes "WebSearch" (from core module baseline)
4. Tool auto-approved
```

**Result**: Also works. Core baseline includes WebSearch.

---

## Edge Cases

### Edge 1: admin_users is empty tuple (backward compat)

```
Config: admin_users = ()  (default)

1. Any user sends message
2. is_owner = bool(() and user_id in ())
   → bool(False and ...) → False (short-circuit)
   → permission_mode = "restricted"
3. All users get --permission-mode dontAsk
4. All users rely on settings.json allow-list
5. Core baseline provides Read/Write/Edit/Glob/Grep/WebSearch/WebFetch/Task
6. Module-specific Bash patterns also in allow-list
```

**Result**: Safe default. All users are restricted but have full tool access through the core baseline + module permissions. This is BETTER than the old behavior (no flag = silent denial).

**Migration note**: Existing instances that relied on the (buggy) "no flag" behavior were already broken. Adding `--permission-mode dontAsk` + a proper allow-list fixes them.

### Edge 2: Module with empty permissions installed

```
Config: modules/memory/opentree.json has permissions.allow = [], permissions.deny = []

1. SettingsGenerator.add_module_permissions("memory", allow=[], deny=[])
2. permissions.json: {"modules": {"memory": {"allow": [], "deny": []}}}
3. generate_settings() aggregates: core's [Read,Write,...] + memory's [] = [Read,Write,...]
4. Memory module relies on Read/Write/Edit which are already in core baseline
```

**Result**: Works. Memory module needs Read/Write/Edit for memory files, which core baseline provides. Empty module permissions are fine when core covers the basics.

### Edge 3: Module refresh after permission format change

```
Before fix: settings.json = {"allowedTools": [...], "denyTools": [...]}
After fix: settings.json = {"permissions": {"allow": [...], "deny": [...]}}

Scenario: User runs `opentree module refresh`
1. SettingsGenerator.reset_module_permissions() clears all modules
2. For each installed module: add_module_permissions(name, allow, deny)
3. write_settings() generates NEW format: {"permissions": {"allow": [...], "deny": [...]}}
4. Old {"allowedTools": ...} format completely replaced
```

**Result**: Works. `write_settings()` does atomic replace of the entire file. No merge with old format.

**What if user does NOT run refresh?**
```
1. Old settings.json still has {"allowedTools": [...]}
2. Claude CLI reads it but ignores unrecognized keys
3. permissions.allow is missing → no tools auto-approved
4. Owner: unaffected (--dangerously-skip-permissions)
5. Restricted: all tools denied (same as current broken behavior)
```

**Mitigation**: Document that `opentree module refresh` is required after upgrading. Consider auto-refresh on bot startup (reset-bot already does this).

### Edge 4: settings.json missing (first install before any modules)

```
1. Fresh OpenTree install
2. No modules installed yet → no permissions.json
3. SettingsGenerator.write_settings() called
4. _load_permissions() returns _empty_permissions() (no modules)
5. generate_settings() → {"permissions": {"allow": [], "deny": []}}
6. Written to workspace/.claude/settings.json
```

**Result for Owner**: Works — `--dangerously-skip-permissions` bypasses empty allow-list.

**Result for Restricted**: No tools available. But this is correct — no modules installed means no functionality.

**After first module install (e.g. `opentree init`)**:
```
1. init installs core + other modules
2. SettingsGenerator adds each module's permissions
3. write_settings() regenerates with core baseline + module tools
4. settings.json now has full allow-list
```

**Result**: Works. The init flow handles this naturally.

### Edge 5: Owner upgrades from old allowedTools to new permissions.allow

```
Timeline:
1. v0.5.0 deployed → settings.json has {"allowedTools": [...], "denyTools": [...]}
2. All features broken (no --permission-mode flag + wrong keys)
3. Upgrade to v0.6.0 (this fix)
4. Bot restarts
5. First message from Owner:
   - permission_mode = "owner" → --dangerously-skip-permissions
   - settings.json format irrelevant (bypass mode)
   - Owner works immediately
6. First message from Restricted user:
   - permission_mode = "restricted" → --permission-mode dontAsk
   - Claude CLI reads settings.json → {"allowedTools": ...} → unrecognized key
   - No tools auto-approved → all tools denied
   - USER IMPACT: restricted user still broken until refresh
7. Owner runs `reset-bot` or `opentree module refresh`
   - settings.json regenerated with new format
   - Restricted users now work
```

**Mitigation options (pick one)**:
- **A. Auto-refresh on startup**: Bot startup checks settings.json format, triggers refresh if old format detected. Low risk, recommended.
- **B. Document in CHANGELOG**: Require manual `opentree module refresh` after upgrade. Simple but error-prone.
- **C. Dual-format output**: Generate both `allowedTools` and `permissions.allow`. Rejected — adds complexity and may confuse Claude Code if it reads both.

**Recommendation**: Option A. Add a format check in bot startup or dispatcher init:

```python
# In Dispatcher.__init__ or Bot.start():
settings_path = opentree_home / "workspace" / ".claude" / "settings.json"
if settings_path.exists():
    data = json.loads(settings_path.read_text())
    if "allowedTools" in data and "permissions" not in data:
        logger.warning("Detected old settings.json format, triggering refresh")
        settings_gen = SettingsGenerator(opentree_home)
        # re-add all installed module permissions from registry
        for name, entry in registry.modules:
            manifest = load_manifest(opentree_home / "modules" / name)
            perms = manifest.get("permissions", {})
            settings_gen.add_module_permissions(name, perms.get("allow", []), perms.get("deny", []))
        settings_gen.write_settings()
```

This auto-migration runs once, is idempotent, and eliminates the manual refresh requirement.

---

## Summary Matrix

| Scenario | Owner | Restricted | Notes |
|----------|-------|------------|-------|
| Normal message | OK | OK | Core baseline covers all basic tools |
| admin_users empty | restricted (safe) | restricted (safe) | Better than current (broken) |
| Empty module perms | OK | OK | Core baseline sufficient |
| After refresh | OK | OK | New format applied |
| Before refresh (upgrade) | OK | BROKEN | Auto-migration recommended |
| settings.json missing | OK | No tools | Expected for fresh install |
| scheduler Bash tool | OK (bypass) | OK (pattern match) | Module allow pattern works |
| memory Write tool | OK (bypass) | OK (core baseline) | Core provides Write |
| web search | OK (bypass) | OK (core baseline) | Core provides WebSearch |
