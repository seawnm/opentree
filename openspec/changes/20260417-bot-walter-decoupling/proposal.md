# Proposal: bot_walter Instance Decoupling

## Background
bot_walter was originally launched via `uv run --directory /mnt/e/develop/mydev/opentree`,
coupling it directly to the source tree. Any code change to opentree source immediately
affected the running bot — which is unsafe in production.

## Change
Switch bot_walter to use its own dedicated virtualenv with a non-editable install of opentree.

## Scope
- `/mnt/e/develop/mydev/project/trees/bot_walter/bin/run.sh` — BOT_CMD updated (already done)
- `/mnt/e/develop/mydev/project/trees/bot_walter/.venv/` — dedicated venv (new)

## Impact
- bot_walter now runs a fixed snapshot of opentree v0.6.0
- Source code changes to opentree do NOT affect the running bot
- To deploy a new version: `pip install --force-reinstall /path/to/opentree` + restart
- Multiple bot instances can be deployed with different opentree versions simultaneously

## Deployment procedure (after this change)
1. Make code changes in `/mnt/e/develop/mydev/opentree`
2. Run tests: `uv run pytest tests/`
3. Deploy: `<bot_home>/.venv/bin/pip install --force-reinstall /mnt/e/develop/mydev/opentree`
4. Restart bot: pkill or `@bot restart`

## Additional Change: bwrap Sandbox .codex Path Redesign

Discovered and fixed during smoke testing after the non-editable install deployment.

### Problem
The original sandbox design bound `workspace/.codex → /workspace/.codex` inside bwrap.
Codex never reads `/workspace/.codex`; it always reads `HOME/.codex` = `/home/codex/.codex`.
This caused two distinct failures:
- **401 Unauthorized** on every request (auth.json not found at HOME/.codex)
- **`thread/resume failed: no rollout found`** on every second turn (session state written to
  ephemeral tmpfs HOME, not persisted between bwrap invocations)

### Fix (final design)
Bind `workspace/.codex → HOME/.codex` (RW, persistent), then overlay `~/.codex/auth.json`
RO on top via `--ro-bind-try`:

```
--bind workspace/.codex /home/codex/.codex
--ro-bind-try ~/.codex/auth.json /home/codex/.codex/auth.json
```

This makes `workspace/.codex` the single persistent directory for both auth and session state.
Per-instance isolation is maintained because each bot instance has its own workspace directory.

### Additional sandbox fixes in the same session
- `--new-session` flag added to bwrap args (`setsid(2)`) — prevents Codex from detecting a
  controlling TTY and entering interactive stdin mode inside the sandbox
- `stdin=subprocess.DEVNULL` added to `Popen` call — defence-in-depth against interactive mode
- `codex exec resume SESSION_ID` — SESSION_ID is now a positional arg (was `--session-id`)
- `CodexProcess.run()` pre-creates `workspace/.codex/` on host before bwrap launch

### Scope additions
- `src/opentree/runner/sandbox_launcher.py` — `.codex` binding redesign + `--new-session`
- `src/opentree/runner/codex_process.py` — pre-create workspace/.codex, resume positional arg,
  stdin=DEVNULL
- `workspace/AGENTS.md` — Traditional Chinese language preference added to owner block

## Additional Change: Cross-Thread Memory Fix

Discovered and fixed during smoke testing: long-term memory was not persisting
across Slack threads.

### Root Cause A (Critical): bwrap sandbox cannot read memory.md

The system prompt injects `記憶檔案：{opentree_home}/data/memory/{user_id}/memory.md`
but the bwrap sandbox only bind-mounted `workspace/ → /workspace`. The host path
`/mnt/e/develop/mydev/...` does not exist inside bwrap, so Codex's Read tool always
failed silently — memory was never injected into the conversation.

Fix: `build_bwrap_args()` now accepts an optional `memory_dir` parameter. When
provided and the directory exists on the host, it is bound read-only at the same
absolute path (`--ro-bind {memory_dir} {memory_dir}`), so the path in the system
prompt resolves correctly inside the sandbox.

### Root Cause B (Medium): memory_extractor scanned bot response, not user message

`dispatcher.py` called `extract_memories(result.response_text, ...)` — scanning the
BOT's own reply text. Bot confirmation phrases like "了，在這段對話裡我會用這兩點："
matched the 記住/remember regex, filling memory.md with garbage pinned entries
instead of real user preferences.

Fix: Changed to `extract_memories(task.text, ...)` so only the user's explicit
"記住…" commands trigger memory extraction.

### Scope additions
- `src/opentree/runner/sandbox_launcher.py` — `memory_dir` RO bind parameter
- `src/opentree/runner/codex_process.py` — derives and passes `memory_dir`
- `src/opentree/runner/dispatcher.py` — scan `task.text` instead of `result.response_text`
- `workspace/SMOKE_TEST_SOP.md` — TC-09 cross-thread memory test case added
