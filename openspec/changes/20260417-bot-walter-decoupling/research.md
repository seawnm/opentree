# Research: Bot Instance Decoupling Options

## Options Considered

### Option A: uv run --directory (current, being replaced)
- Pros: always runs latest source, zero deployment step
- Cons: source changes immediately affect production bot; no version pinning;
  multiple instances share the same code, cannot have different versions

### Option B: pip install -e (editable, intermediate step)
- Pros: has own venv/executable; venv path is independent
- Cons: still points back to source tree via .pth file; `pip show` shows
  "Editable project location"; source changes still affect bot

### Option C: pip install (non-editable) ← CHOSEN
- Pros: full snapshot of code at install time; source changes do NOT affect bot;
  multiple instances can have different versions; clear deployment boundary
- Cons: must explicitly reinstall to pick up changes (this is a feature, not a bug)

## Decision
Option C chosen. The explicit "install to deploy" pattern is standard practice
and matches the project's goal of per-instance isolation.

---

## Appendix: bwrap Sandbox auth.json Path Bug (discovered during smoke tests)

### Root Cause
During E2E smoke testing after decoupling, all Codex requests returned `401 Unauthorized`.

**Two `.codex` directories serve different purposes:**

| Directory | Purpose | Expected path inside sandbox |
|-----------|---------|------------------------------|
| `/workspace/.codex` | Codex **state/session** dir (rollout files, thread state) | `/workspace/.codex` |
| `~/.codex` | Codex **config/auth** dir (reads `auth.json` for credentials) | `/home/codex/.codex` |

### Bug
The original design mounted `auth.json` at `/workspace/.codex/auth.json` (state dir).  
But Codex reads auth credentials from `HOME/.codex/auth.json` = `/home/codex/.codex/auth.json`.  
Since `/home` is a tmpfs inside the sandbox, there was no `/home/codex/.codex/` directory, so Codex found no credentials and tried OpenAI API without auth → 401.

### Fix (Iteration 1 — auth only)
Used `--dir /home/codex/.codex` to pre-create directory on tmpfs HOME, then  
`--ro-bind-try ~/.codex/auth.json /home/codex/.codex/auth.json`.  
TC-01/TC-08 passed, but TC-02/TC-03 (multi-turn) still failed with  
`thread/resume failed: no rollout found`.

### Root Cause of Multi-Turn Failure
Codex writes session state (`state_5.sqlite`, `sessions/`, rollout files) to `HOME/.codex`.  
With Iteration 1, only auth.json was bind-mounted; the rest of `HOME/.codex` was tmpfs  
(ephemeral per bwrap invocation). On Turn 2, rollout from Turn 1 was gone.

### Fix (Iteration 2 — final)
Bind `workspace/.codex → HOME/.codex` (RW, persistent), then overlay `auth.json` RO on top.

```
--bind workspace/.codex /home/codex/.codex        # persistent state
--ro-bind-try ~/.codex/auth.json /home/codex/.codex/auth.json  # RO auth overlay
```

This makes `workspace/.codex` the single persistent directory for both auth and state,  
per-instance isolation is maintained since each bot instance has its own workspace.

Verified: TC-01, TC-02, TC-03, TC-04, TC-08 all PASS after Iteration 2.
