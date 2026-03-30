# Code Review: OpenTree Slack Bot Runner

**Reviewed by**: code-reviewer agent  
**Date**: 2026-03-30  
**Scope**: `src/opentree/runner/` (10 new files), `core/prompt.py`, `cli/init.py`, `pyproject.toml`

---

## Findings

### [HIGH] Admin command pipeline is dead code — commands are never dispatched

**File**: `src/opentree/runner/dispatcher.py`  
**Lines**: `dispatch()` (L125–151), `parse_message()` (L90–123), `_handle_admin_command()` (L311–325)

`parse_message()` and `_handle_admin_command()` exist and are correct in isolation, but `dispatch()` never calls either of them. Every message — including `status`, `help`, and `shutdown` — goes directly into the task queue and is sent to Claude as a plain prompt. The `shutdown` command in particular is documented as a graceful stop mechanism but has no runtime effect.

**Evidence**: Grepping the entire `src/` tree confirms `parse_message` and `_handle_admin_command` are defined but never called from production code paths.

**Fix**: `dispatch()` must parse the message before submitting to the queue:

```python
def dispatch(self, task: Task) -> None:
    parsed = self.parse_message(task.text, self._slack.bot_user_id, files=task.files)
    if parsed.is_admin_command:
        self._handle_admin_command(task, parsed.admin_command)
        return
    # rewrite task.text to the stripped version
    # ... then submit to queue
```

Note: because `Task` is not frozen, `task.text` can be updated in-place with the stripped text before queuing; or `ParsedMessage.text` can be passed through a replacement task.

---

### [HIGH] `user_name` is always empty string, causing silent wrong memory path

**File**: `src/opentree/runner/receiver.py:231`, `src/opentree/runner/dispatcher.py:294–295`

`Receiver._build_task()` sets `user_name=""` with a comment "resolved later by the runner if needed". The runner never resolves it. `Dispatcher._build_prompt_context()` then constructs:

```python
self._home / "data" / "memory" / task.user_name / "memory.md"
# resolves to: $OPENTREE_HOME/data/memory/memory.md  (no user directory)
```

Every user gets the same memory path. If the file exists, all users share one memory blob. If it doesn't exist, the identity block emits a path that Claude cannot read.

**Fix**: Resolve `user_name` from `user_id` via `SlackAPI.get_user_display_name()` in `Receiver._build_task()` or at the start of `Dispatcher._process_task()`. Alternatively pass `user_id` as the directory key (it is already unique and safe).

---

### [HIGH] `user_name` used in path with no path-traversal validation

**File**: `src/opentree/runner/dispatcher.py:294–295`

Even once `user_name` is resolved, it is used directly in a filesystem path without sanitization:

```python
memory_path = str(
    self._home / "data" / "memory" / task.user_name / "memory.md"
)
```

A Slack display name can contain `..`, `/`, or other characters. A crafted display name of `../../config` would cause Claude to receive a `memory_path` pointing outside `data/memory/`.

`core/prompt.py` already has `_is_safe_name()` using `^[a-zA-Z0-9_-]+$`. The same guard must be applied here before constructing the path. If the name is unsafe, fall back to `user_id` (which is always `[A-Z0-9]+` from Slack).

---

### [MEDIUM] `cleanup_expired()` reads `_sessions` outside the lock — TOCTOU race

**File**: `src/opentree/runner/session.py:103–126`

```python
def cleanup_expired(self, max_age_days: int = 180) -> int:
    cutoff = datetime.now() - timedelta(days=max_age_days)
    to_remove: list[str] = []

    for thread_ts, info in self._sessions.items():   # ← no lock held
        ...

    with self._lock:
        self._sessions = {k: v ...}   # ← lock acquired here
        self._save()
```

Between the unlocked iteration and the locked deletion, a concurrent `set_session_id()` call can add a session that was not present during iteration. That newly-added entry can then be incorrectly excluded from the rebuilt dict if its key happened to be in `to_remove` from a previous run (unlikely in practice but possible if keys are reused).

More concretely: the unlocked dict iteration is safe in CPython (GIL) but is not safe in general. The design comment in `session.py` says "Reads are lock-free (Python GIL protects dict iteration for simple lookups)" — this is acceptable for `get_session_id()` which is a single-key lookup, but a full `items()` iteration during `cleanup_expired()` is a different situation since the dict may be replaced (not mutated) by a concurrent write, invalidating the iterator.

**Fix**: Acquire `self._lock` at the start of `cleanup_expired()` to cover the entire scan-and-delete operation.

---

### [MEDIUM] `stderr=subprocess.DEVNULL` silently discards Claude CLI error output

**File**: `src/opentree/runner/claude_process.py:211`

Claude CLI writes startup errors, authentication failures, and some fatal errors to `stderr`. With `stderr=subprocess.DEVNULL`, none of this reaches the log. If `ClaudeProcess.run()` gets an empty `stdout` (exit code non-zero, no stream-json output), the returned `ClaudeResult` will have `is_error=False`, `response_text=""`, `exit_code=N`. The bot then sends `"(no response)"` to the user with no actionable diagnostics in the log.

**Fix**: Capture `stderr=subprocess.PIPE` and log it (at WARNING level) when `exit_code != 0` or when the stream produces no events. Alternatively use `stderr=subprocess.STDOUT` to interleave it but that would corrupt the stream-json output.

```python
self._process = subprocess.Popen(
    args,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,   # capture, not discard
    ...
)
```

Then in `run()`, after `process.wait()`:
```python
if exit_code != 0:
    stderr_output = self._process.stderr.read()
    if stderr_output:
        logger.warning("Claude stderr: %s", stderr_output.decode(errors="replace"))
```

---

### [MEDIUM] `start_command` silently falls through on unknown `--mode` values

**File**: `src/opentree/cli/init.py:342–373`

```python
if mode == "slack":
    ...
    return

# --- interactive mode (default) ---
```

Any value other than `"slack"` (e.g. `opentree start --mode typo`) silently launches the interactive path. The user gets no error and no indication their flag was ignored.

**Fix**: Add explicit validation:

```python
VALID_MODES = {"slack", "interactive"}
if mode not in VALID_MODES:
    typer.echo(f"Error: unknown mode '{mode}'. Choose from: {', '.join(sorted(VALID_MODES))}", err=True)
    raise typer.Exit(code=1)
```

---

### [MEDIUM] `Task` dataclass is mutable but shared across threads

**File**: `src/opentree/runner/task_queue.py:22–37`, `_start_task_locked()` (L180–185), `_finish_task_locked()` (L187–199), `mark_completed()` (L106–112)

`Task` is a plain `@dataclass` (not frozen). `TaskQueue` mutates `task.status`, `task.started_at`, and `task.completed_at` while holding `_lock`. However, the worker thread in `Dispatcher._process_task()` also holds a reference to the same `Task` object and reads `task.channel_id`, `task.thread_ts`, etc. concurrently without any lock.

In CPython this is safe for attribute reads due to the GIL, but it violates the immutability principle stated in project coding style (`NEVER mutate existing objects`). It also means a reader can observe partially-updated state across a `status`/`started_at` pair.

**Fix**: Either freeze the dataclass and have the queue maintain status in its own `dict[str, TaskStatus]`, or document the GIL dependency explicitly and accept the deviation. Given the project convention, the frozen + separate status dict approach is preferred.

---

### [LOW] `config.py` does not validate string field types — integer-typed values accepted without type check

**File**: `src/opentree/runner/config.py:57–61`

`_validate()` checks numeric bounds but not types. If `runner.json` contains `"task_timeout": "1800"` (a string), `RunnerConfig` will be constructed with a string value for an `int` field; `frozen=True` does not enforce types, and Python dataclasses don't validate field types by default. The first comparison `data[field] <= 0` will raise `TypeError` for string input rather than giving a clear error.

**Fix**: Add type coercion or an explicit type check before the bounds check:

```python
if field in data:
    value = data[field]
    if not isinstance(value, int):
        raise ValueError(f"RunnerConfig: '{field}' must be an integer, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(...)
```

---

### [LOW] `Receiver._processed_ts` pruning uses `set(sorted(...)[-keep:])` — O(n log n) on every overflow

**File**: `src/opentree/runner/receiver.py:191–194`

```python
if len(self._processed_ts) > self._max_processed:
    keep = self._max_processed // 2
    self._processed_ts = set(sorted(self._processed_ts)[-keep:])
```

This sorts the entire 10,000-entry set each time the cap is exceeded. Slack `ts` values are already monotonically increasing string timestamps so this works correctly, but the cost is O(n log n) on the hot path (every even-numbered message after the cap). A `collections.deque` with `maxlen=10_000` would give O(1) eviction.

This is a minor performance concern, not a correctness issue.

---

### [LOW] `Bot._shutdown()` re-reads `runner.json` instead of using the already-loaded config

**File**: `src/opentree/runner/bot.py:198`

```python
runner_config = load_runner_config(self._home)
drain_timeout = runner_config.drain_timeout
```

`Dispatcher.__init__()` already loads the runner config and stores it as `self._runner_config`. The `Bot` re-reads the file during shutdown. In most cases this is harmless, but it creates a discrepancy if the file changes between startup and shutdown, and it adds unnecessary I/O on the shutdown path.

**Fix**: Expose `drain_timeout` via `Dispatcher` or pass the config through.

---

### [LOW] No test coverage for `user_name`-empty memory path or admin command dead code

**Files**: `tests/test_dispatcher.py`, `tests/test_receiver.py`

`test_memory_path_contains_user_name` (L198) passes `user_name="alice"` directly into `make_task()`, so it never exercises the real path where `user_name` comes from the receiver as `""`. There are no tests asserting that admin commands (`status`, `help`, `shutdown`) actually execute when a user sends them via the full `dispatch()` → `_process_task()` pipeline — because the wiring is missing, the tests that do exist only call `_handle_admin_command` directly.

---

## Review Summary

| Severity | Count | Items |
|----------|-------|-------|
| CRITICAL | 0     | — |
| HIGH     | 3     | Admin command dead code; empty user_name wrong memory path; user_name path traversal |
| MEDIUM   | 4     | cleanup_expired TOCTOU; stderr discarded; unknown mode silent fallthrough; Task mutable across threads |
| LOW      | 4     | Type validation in config; O(n log n) dedup pruning; redundant config reload in shutdown; missing test coverage |

**Verdict: BLOCK on HIGH issues — these must be fixed before the runner is production-ready.**

The three HIGH findings interact: the `user_name` is always empty (finding #2), which currently prevents the path traversal (finding #3) from being exploitable — but once `user_name` resolution is added to fix #2, finding #3 becomes immediately exploitable. Both must be fixed together. The admin command dead code (finding #1) means the `shutdown` command does not work at all in the current implementation.

No hardcoded secrets, no DOGI imports, no circular imports, no files exceeding 800 lines. Token handling is correct (`.env` file, no logging of token values). `subprocess.Popen` uses a list argument so there is no shell injection risk from user-controlled message text. The `core/prompt.py` security fixes (path traversal guards, thread-safe hook loading) are correctly implemented and well-tested.
