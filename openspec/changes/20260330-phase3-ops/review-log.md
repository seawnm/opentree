# Code Review: Phase 3 Operations

**Date**: 2026-03-30
**Reviewer**: code-reviewer agent (claude-sonnet-4-6)
**Scope**: logging_config.py, run.sh, bot.py (logging integration), cli/init.py (run.sh + .env generation), tests/test_logging_config.py

---

## Findings

---

### [HIGH] run.sh: BOT_CMD variable unquoted — word-splitting on path with spaces

**File**: `src/opentree/templates/run.sh:24, 211`

```bash
# Line 24 — variable defined without quoting the home path
BOT_CMD="opentree start --mode slack --home $OPENTREE_HOME"

# Line 211 — executed without quoting
$BOT_CMD &
```

`OPENTREE_HOME` is substituted at the time `BOT_CMD` is defined (line 24), so if the path contains spaces (e.g. `/home/user/my project/.opentree`) the string is split by the shell into multiple tokens when executed at line 211. The command will fail with "No such file or directory" or silently pass the wrong path as an argument.

The variable expansion also means `BOT_CMD` cannot safely carry arguments that themselves contain spaces.

**Fix**: Store the command as an array and expand it with `"${BOT_CMD[@]}"`, or execute directly:

```bash
# Option A — array (safest)
BOT_CMD=(opentree start --mode slack --home "$OPENTREE_HOME")
...
"${BOT_CMD[@]}" &

# Option B — inline execution (simpler, removes the variable)
opentree start --mode slack --home "$OPENTREE_HOME" &
BOT_PID=$!
```

---

### [HIGH] run.sh: `set -euo pipefail` conflicts with `wait` and `|| true` pattern

**File**: `src/opentree/templates/run.sh:19, 216`

```bash
set -euo pipefail          # line 19 — strict mode
...
wait $BOT_PID || true      # line 216
exit_code=$?               # line 217 — always captures 0 from `|| true`
```

When `set -e` is active and the `wait` returns the non-zero exit code of the bot (crash), the `|| true` swallows the failure but also means `exit_code` is **always 0**. This breaks the exit-code dispatch logic below (lines 229-243): crashes are never counted because `$exit_code` is never non-zero.

**Fix**: Capture the exit code directly before applying `|| true`:

```bash
wait "$BOT_PID"
exit_code=$?
BOT_PID=""
```

Remove `|| true`. `wait` for a background job does not cause `set -e` to abort the script — the `set -e` rule does not apply to a `wait` used to retrieve the exit status of a background process when that exit status is subsequently tested. However, to be safe and explicit, capture unconditionally:

```bash
set +e
wait "$BOT_PID"
exit_code=$?
set -e
BOT_PID=""
```

---

### [HIGH] bot.py: `setup_logging` called before token validation — exceptions logged to stderr only, not the file

**File**: `src/opentree/runner/bot.py:66-70`

```python
def start(self) -> None:
    log_dir = self._home / "data" / "logs"
    setup_logging(log_dir)             # line 67 — fine
    logger.info("OpenTree Bot starting ...")

    bot_token, app_token = self._load_tokens()   # line 70 — raises RuntimeError if missing
```

The ordering is correct (logging is established first), but the `RuntimeError` from `_load_tokens()` propagates to the caller of `start()` (`start_command` in `init.py`, line 379) without any catch. The exception traceback will be printed to stderr by Python's default handler, **not** to the log file, because the file handler is set up but the exception bubbles out before a `logger.exception()` call.

More importantly, if `log_dir` creation itself fails (e.g. disk full, permission denied), `setup_logging` raises `OSError` and the caller gets an uncaught exception with no user-friendly message.

**Fix**: Wrap the body of `start()` in a broad try/except that logs critical failures before re-raising, and add an explicit check for `setup_logging` errors:

```python
def start(self) -> None:
    log_dir = self._home / "data" / "logs"
    try:
        setup_logging(log_dir)
    except OSError as exc:
        # Fall back to stderr-only logging so subsequent errors are still visible
        logging.basicConfig(level=logging.DEBUG)
        logger.error("Failed to create log directory %s: %s", log_dir, exc)

    logger.info("OpenTree Bot starting (home: %s)", self._home)
    try:
        bot_token, app_token = self._load_tokens()
        ...
    except Exception:
        logger.exception("Fatal error during bot startup")
        raise
```

---

### [HIGH] bot.py: `_shutdown` calls `load_runner_config` again — reads disk during signal-driven teardown

**File**: `src/opentree/runner/bot.py:203`

```python
def _shutdown(self) -> None:
    if self._dispatcher is not None:
        runner_config = load_runner_config(self._home)   # file I/O during shutdown
        drain_timeout = runner_config.drain_timeout
```

`load_runner_config` reads `config/runner.json` from disk every time it is called. This is redundant (config was already loaded during `start()` if needed) and introduces a failure mode: if the config directory is unavailable at shutdown (e.g. network filesystem), drain_timeout falls back to the dataclass default silently. There is also a subtle TOCTOU if the config file is replaced between startup and shutdown.

**Fix**: Load `RunnerConfig` once during `start()` and store it as an instance attribute, then reuse it in `_shutdown()`:

```python
def start(self) -> None:
    ...
    self._runner_config = load_runner_config(self._home)
    ...

def _shutdown(self) -> None:
    if self._dispatcher is not None:
        drain_timeout = self._runner_config.drain_timeout
        ...
```

---

### [MEDIUM] run.sh: `cleanup` trap removes PID file but does not set `BOT_PID=""` — double-`wait` risk

**File**: `src/opentree/templates/run.sh:153-167`

```bash
cleanup() {
    log "Received shutdown signal, forwarding to bot..."
    if [ -n "${BOT_PID:-}" ] && kill -0 "$BOT_PID" 2>/dev/null; then
        kill -TERM "$BOT_PID" 2>/dev/null || true
        wait "$BOT_PID" 2>/dev/null || true
    fi
    stop_watchdog
    rm -f "$PID_FILE"
    log "Shutdown complete"
    exit 0
}
```

After `cleanup` calls `wait "$BOT_PID"`, the main loop's `wait $BOT_PID` (line 216) will execute for the same PID. POSIX specifies that a second `wait` for an already-reaped PID returns immediately with exit code 127. This is mostly harmless, but the `exit_code` captured at line 217 would be 127 and then classified as a crash, triggering restart logic before `exit 0` is reached. The `exit 0` at the end of `cleanup` terminates the script before the loop iterates, so no actual spurious restart occurs — but the log message "Crash detected (1/5 within window). Restarting in 5s..." would fire before the exit.

**Fix**: Set `BOT_PID=""` after the wait in `cleanup` to make the guard at line 216 skip the second wait:

```bash
cleanup() {
    ...
    if [ -n "${BOT_PID:-}" ] && kill -0 "$BOT_PID" 2>/dev/null; then
        kill -TERM "$BOT_PID" 2>/dev/null || true
        wait "$BOT_PID" 2>/dev/null || true
        BOT_PID=""
    fi
    ...
}
```

---

### [MEDIUM] run.sh: `stat -c %Y` is Linux-only — not portable to macOS

**File**: `src/opentree/templates/run.sh` — not used, but the template uses `date +%s` and `cat` to read the heartbeat epoch. This is fine.

However, the proposal listed this as a known risk. Confirming: `stat -c %Y` does **not** appear in the current run.sh (the heartbeat mechanism writes epoch directly and reads it with `cat`). **No action needed** — the approach chosen avoids the portability issue entirely. This is the correct design.

---

### [MEDIUM] run.sh: `check_network` uses `host` command — may be absent in minimal containers

**File**: `src/opentree/templates/run.sh:59`

```bash
while ! host "$DNS_HOST" >/dev/null 2>&1; do
```

`host` is part of `bind-utils` / `dnsutils` and is not present in all minimal Docker base images (e.g. `python:3.12-slim`, Alpine). The script silently treats a missing `host` as a DNS failure and waits `DNS_TIMEOUT` seconds on every restart cycle.

**Fix**: Prefer `getent hosts` (part of glibc, present on all glibc-based Linux systems) with a fallback to `host`, and add a detection step:

```bash
_dns_check() {
    if command -v getent >/dev/null 2>&1; then
        getent hosts "$1" >/dev/null 2>&1
    elif command -v host >/dev/null 2>&1; then
        host "$1" >/dev/null 2>&1
    else
        # No DNS tool available; assume network is up
        return 0
    fi
}

check_network() {
    local elapsed=0
    while ! _dns_check "$DNS_HOST"; do
        ...
    done
}
```

This is consistent with the risk noted in the proposal.

---

### [MEDIUM] run.sh: Watchdog PID variable leaks between loop iterations

**File**: `src/opentree/templates/run.sh:140, 176, 207`

`WATCHDOG_PID` is declared at line 176 (before the main loop) as `""`. `start_watchdog` sets it at line 140. `stop_watchdog` clears it at line 148. This is correct for the normal flow.

However, if `check_network` returns failure (line 200-204), the loop `continue`s without calling `start_watchdog`. On the **next** iteration, `start_watchdog` is called again. If the previous `stop_watchdog` call was skipped (e.g. because the watchdog background process was never started on a network-failure iteration), `WATCHDOG_PID` is still `""` and `stop_watchdog` is a no-op — correct. This path is actually safe.

The subtle issue: after `check_network` fails and `continue` is executed, the code flow goes back to the loop top and calls `start_watchdog` **before** checking crash loop state on the next iteration, meaning a watchdog is started even before the bot is launched. If the crash loop cooldown fires (`sleep $COOLDOWN`), the watchdog started at the top of the **prior** loop iteration's successful path is already stopped. This is safe.

However, there is a real edge case: if `check_network` fails on the **first** iteration (before any watchdog is started) and then succeeds on the **second** iteration, `start_watchdog` is called but `WATCHDOG_PID` may still be the value from a previous successful iteration's watchdog that was cleaned up. This is fine because `stop_watchdog` already cleared `WATCHDOG_PID=""`.

**Reduced severity**: The actual issue is that `start_watchdog` is called **on every loop iteration before network check succeeds** — but since the network check is earlier in the loop body (lines 200-204) and `start_watchdog` is at line 207 (after the network check), the watchdog is only started after a successful network check. This is correct ordering.

After deeper analysis, this is a low-risk finding. The variable lifecycle is correctly managed. **Noting for awareness only.**

---

### [MEDIUM] run.sh: Watchdog `break` does not trigger a restart — exits silently

**File**: `src/opentree/templates/run.sh:93-95, 135-136`

```bash
# If bot process is gone, watchdog exits
if ! kill -0 "$bot_pid" 2>/dev/null; then
    break
fi
```

and after sending SIGKILL:

```bash
break
```

When the watchdog detects the bot is gone (first `break`) or after it sends SIGKILL (second `break`), the watchdog subshell exits. This is fine — the main loop's `wait $BOT_PID` will unblock because the bot process has ended, and the restart logic will proceed normally.

However, in the SIGKILL path (line 133-136): the watchdog sends `SIGKILL` and then `break`s. The bot process is forcibly killed, so `wait $BOT_PID` in the main loop unblocks. Exit code from a SIGKILL'd process is 128+9 = 137. This is non-zero and non-42, so it will be classified as a crash and restarted — which is the intended behavior. The logic is correct.

**No action needed** — noting this was verified.

---

### [MEDIUM] logging_config.py: `root.handlers.clear()` does not close open file handles

**File**: `src/opentree/runner/logging_config.py:41`

```python
root.handlers.clear()
```

`list.clear()` removes references without calling `handler.close()`. If `setup_logging` is called more than once (e.g. in tests or a future restart path), the `TimedRotatingFileHandler` from the first call keeps its file descriptor open. On Linux this does not prevent the file from being written, but it does leak file descriptors and can cause issues with log rotation (the rotated file may still be held open by the old handler).

The test's `teardown_method` calls `h.close()` explicitly (line 210) to work around this, which is a signal that the production code has a gap.

**Fix**:

```python
for handler in root.handlers[:]:
    handler.close()
root.handlers.clear()
```

---

### [MEDIUM] cli/init.py: `shutil.rmtree` on existing module directory without confirmation — destructive on re-init

**File**: `src/opentree/cli/init.py:226-227`

```python
if target.exists():
    shutil.rmtree(target)
shutil.copytree(child, target)
```

When `--force` is passed, existing module directories are deleted without warning. Any customizations a user made inside their installed module directory (e.g. edited prompts, local overrides) are silently destroyed. This is particularly risky because `shutil.rmtree` is irreversible.

**Fix**: Warn the user when overwriting existing modules, or skip modules that have not changed (compare version from registry). At minimum, log what is being overwritten:

```python
if target.exists():
    typer.echo(f"  Overwriting module '{child.name}' ...")
    shutil.rmtree(target)
```

For a future iteration, consider diffing the installed version against the bundled version and only overwriting if the version changed.

---

### [MEDIUM] cli/init.py: `init_command` not fully idempotent — partial failure leaves inconsistent state

**File**: `src/opentree/cli/init.py:252-294`

The module installation loop (inside `Registry.lock`) installs modules one at a time. If installation of the third module fails (e.g. manifest validation error), the first two modules are already installed and their symlinks/permissions are written. The registry is not saved (line 284 is not reached), but `settings.json` may have been partially updated (depends on whether `settings_gen.write_settings()` was called).

If the user fixes the problem and re-runs `opentree init` without `--force`, the guard at line 185 (`reg_path.exists()`) catches the already-initialized state only if `registry.json` was written. Since the lock was never released (the exception propagates through `Registry.lock`'s context manager), and `registry.json` was never written, the second run proceeds as a fresh init — which may conflict with the partially-written symlinks.

**Fix**: Either make the installation transactional (write to a temp directory, atomically rename) or clean up on failure. A simpler mitigation is to check for existing symlinks in a pre-flight pass before modifying anything.

---

### [LOW] run.sh: `log()` output goes only to stdout — not to the log file

**File**: `src/opentree/templates/run.sh:51-53`

```bash
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}
```

The wrapper's own log messages go to stdout only. When run as `nohup bash run.sh >> wrapper.log 2>&1 &`, they are redirected to `wrapper.log` — which is correct if the operator uses the documented invocation. However, the Python bot logs go to `data/logs/`, while wrapper events go to `wrapper.log`, meaning two separate files must be consulted to diagnose issues. This is a minor operational inconvenience, not a defect.

**Suggestion**: Document in the generated run.sh header that wrapper logs go to the redirect target, not to the bot's log directory.

---

### [LOW] run.sh: `sleep $DNS_CHECK_INTERVAL` uses unquoted variable — cosmetic

**File**: `src/opentree/templates/run.sh:65`

```bash
sleep $DNS_CHECK_INTERVAL
```

All numeric constants in the script should be quoted for consistency with `set -u`. Because `DNS_CHECK_INTERVAL` is always set at the top of the script, this is not a real risk — but quoting should be applied uniformly:

```bash
sleep "$DNS_CHECK_INTERVAL"
```

This applies to: `sleep $WATCHDOG_INTERVAL`, `sleep $WATCHDOG_INIT_DELAY`, `sleep $COOLDOWN`, `sleep 30`, `sleep 2`, `sleep 5`.

---

### [LOW] bot.py: duplicate log message at startup

**File**: `src/opentree/runner/bot.py:68, 103-107`

```python
logger.info("OpenTree Bot starting (home: %s)", self._home)   # line 68

...

logger.info(
    "OpenTree bot starting — home=%s, bot_user_id=%s",        # line 103
    self._home,
    bot_user_id,
)
```

Two "starting" messages are logged. The second one (line 103) is more informative (includes `bot_user_id`). The first one (line 68) is redundant.

**Fix**: Remove line 68 or demote it to `logger.debug`.

---

### [LOW] test_logging_config.py: tests share global root logger state — potential ordering dependency

**File**: `tests/test_logging_config.py`

The test classes use `teardown_method` to clear root logger handlers. This is correct, but if a test is interrupted (e.g. by a `KeyboardInterrupt` or pytest-xdist crash), the teardown may not run and subsequent tests may see leftover handlers. The `TestSetupLoggingAddsHandlers` class clears handlers but does not close them (unlike `TestLogFileCreatedOnWrite` which does call `h.close()`).

**Fix**: Use a pytest fixture with `autouse=True` scope that closes and clears handlers at the module level:

```python
@pytest.fixture(autouse=True)
def reset_root_logger():
    yield
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
    root.handlers.clear()
```

This replaces all `teardown_method` calls and is more robust.

---

### [LOW] cli/init.py: generated `.env.example` uses placeholder token format that could pass basic validation

**File**: `src/opentree/cli/init.py:314-317`

```python
env_example.write_text(
    "SLACK_BOT_TOKEN=xoxb-your-bot-token\n"
    "SLACK_APP_TOKEN=xapp-your-app-token\n",
    ...
)
```

If a user copies `.env.example` to `.env` without filling in real values, `bot.py._load_tokens()` will load `xoxb-your-bot-token` as the token. The validation at line 156 (`if not bot_token`) only checks for an empty string — the placeholder value passes through and the bot will fail at `auth_test()` with a Slack API error rather than a clear "you forgot to fill in the token" message.

**Fix**: Add a simple sentinel check in `_load_tokens()`:

```python
for placeholder in ("xoxb-your-", "xapp-your-"):
    if bot_token.startswith(placeholder) or app_token.startswith(placeholder):
        raise RuntimeError(
            "config/.env still contains placeholder values. "
            "Copy config/.env.example to config/.env and fill in real tokens."
        )
```

---

## Review Summary

| Severity | Count | Issues |
|----------|-------|--------|
| CRITICAL | 0     | — |
| HIGH     | 4     | BOT_CMD unquoted, `wait \|\| true` masks exit code, setup_logging error unhandled, load_runner_config called at shutdown |
| MEDIUM   | 5     | cleanup BOT_PID leak, `host` portability, handler.close() missing, rmtree without warning, init non-transactional |
| LOW      | 4     | log() to stdout only, unquoted sleep variables, duplicate startup log, test global state, .env placeholder validation |

**Verdict: WARNING — 4 HIGH issues should be resolved before production deployment.**

The two most impactful issues are:

1. **`wait $BOT_PID || true` always capturing exit_code=0** — this silently disables the entire crash detection and restart logic in run.sh. The bot will never count crashes and will either loop forever or exit cleanly when it should restart.

2. **`$BOT_CMD` unquoted** — any deployment path with spaces will silently fail to start the bot. Since `opentree init` generates the path from user-provided input (which may include spaces), this is a real risk.

Both are in the generated `run.sh` template and cannot be patched at runtime without regenerating the file.
