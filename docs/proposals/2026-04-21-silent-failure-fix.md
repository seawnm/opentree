# Silent-Failure Investigation & Improvement Proposal

**Date**: 2026-04-21
**Investigator**: Senior Debugging Engineer (automated analysis)
**Severity**: High — users receive "completed successfully" status for tasks that produced no reply
**Affected Component**: OpenTree runner pipeline (`codex_process.py` -> `codex_stream_parser.py` -> `dispatcher.py` -> `progress.py`)

---

## Section 1: Root Cause Summary

### Critical Finding: Both Cases Share the Same Root Cause

The initial report stated Case A had "NO WARNING or ERROR logs" while Case B did. **This is incorrect.** Log analysis reveals both cases are identical:

| Attribute | Case A (thread `1776726132`) | Case B (thread `1776726232`) |
|-----------|------------------------------|------------------------------|
| Codex stderr | `Reading additional input from stdin...` | `Reading additional input from stdin...` |
| Exit code | 1 | 1 |
| `has_result_event` | False | False |
| Warning logged | `No result event received from Codex CLI stream (pid=28927, exit_code=1, timed_out=False)` | `No result event received from Codex CLI stream (pid=29473, exit_code=1, timed_out=False)` |
| Duration | 56 sec | 56 sec |
| Progress display | "thinking" entire time | "thinking" entire time |
| Slack final status | "completed" with no reply | "completed" with no reply |

**Evidence from logs:**
- Line 3063: `2026-04-21 07:03:12 WARNING [opentree.runner.codex_process] Codex stderr: Reading additional input from stdin...`
- Line 3064: `2026-04-21 07:03:12 WARNING [opentree.runner.codex_process] No result event received from Codex CLI stream (pid=28927, exit_code=1, timed_out=False)`
- Line 3378: `2026-04-21 07:04:53 WARNING [opentree.runner.codex_process] Codex stderr: Reading additional input from stdin...`
- Line 3379: `2026-04-21 07:04:53 WARNING [opentree.runner.codex_process] No result event received from Codex CLI stream (pid=29473, exit_code=1, timed_out=False)`

### Root Cause: Codex CLI Enters Interactive Mode Despite `stdin=subprocess.DEVNULL`

1. **Codex CLI** is spawned with `stdin=subprocess.DEVNULL` (line 265 of `codex_process.py`), which provides EOF on stdin.
2. However, Codex CLI prints `"Reading additional input from stdin..."` to stderr, meaning it attempted to read from stdin for the prompt content — despite the prompt being passed as a positional argument.
3. This suggests a **Codex CLI bug or behavior change** where:
   - The positional PROMPT argument is consumed but Codex still tries to read additional input (similar to `cat` reading both a file argument and stdin)
   - OR Codex ignores the positional argument under certain conditions and falls back to stdin
4. Because `stdin=subprocess.DEVNULL`, Codex gets immediate EOF, emits the stderr warning, and **exits with code 1 without emitting any JSONL events** (no `thread.started`, no `turn.completed`, nothing).
5. The 56-second duration is **not** spent on Codex thinking — it is spent on the **pre-processing steps** (Slack API calls for thread context, user resolution, AGENTS.md generation, bwrap sandbox setup). Codex CLI itself likely ran for only a few seconds.

### The Silent-Failure Pipeline (How the Error Is Swallowed)

```
codex_process.py:304  ──  has_result_event=False  ──>  WARNING logged (NOT an error)
                          is_error=False, response_text=""
                              │
                              ▼
dispatcher.py:526-529  ──  result.is_error=False  ──>  circuit_breaker.record_success()  (BUG: counts as success!)
                              │
                              ▼
dispatcher.py:552-558  ──  reporter.complete(response_text="", is_error=False)
                              │
                              ▼
progress.py:299-304    ──  Updates Slack: "✅ 處理完成 | 已執行 56 秒"
progress.py:314        ──  `if not response_text.strip(): return`  ──>  SILENTLY EXITS (no reply sent!)
                              │
                              ▼
dispatcher.py:590      ──  task_queue.mark_completed(task)  (BUG: counts as completed!)
```

The 4-occurrence count of `Reading additional input from stdin` in the log file (vs 3 occurrences of `No result event`) suggests this is a systemic Codex CLI compatibility issue, not a one-time transient failure.

### Common Underlying Cause

Both cases fail because the OpenTree runner treats **absence of a result event** as a non-error condition. The `codex_stream_parser.py` only sets `is_error=True` when it receives a `turn.completed` event AND `_saw_error_hint=True` AND `_saw_agent_message=False`. When Codex exits without emitting **any** events at all, the parser returns `is_error=False` with empty `response_text`.

---

## Section 2: Code Fixes (Ranked by Impact)

### Fix 1: Treat "no result event + non-zero exit code" as an error in `codex_process.py`

**Impact**: Highest — this is the primary escape hatch that allows all silent failures.

**File**: `src/opentree/runner/codex_process.py`
**Lines**: 303-311 (after the "No result event" warning)

**Current code** (line 303-322):
```python
        pid = self._process.pid if self._process is not None else None
        if not self._parser.state.has_result_event:
            logger.warning(
                "No result event received from Codex CLI stream "
                "(pid=%s, exit_code=%s, timed_out=%s)",
                pid,
                exit_code,
                self._timed_out,
            )
        elif (
            self._parser.state.input_tokens == 0
            and self._parser.state.output_tokens == 0
        ):
            logger.warning(
                "Result event received but token counts are both zero "
                "(pid=%s, exit_code=%s)",
                pid,
                exit_code,
            )

        result_dict = self._parser.get_result()

        return ClaudeResult(
            session_id=result_dict["session_id"],
            response_text=result_dict["response_text"],
            input_tokens=result_dict["input_tokens"],
            output_tokens=result_dict["output_tokens"],
            is_error=result_dict["is_error"],
            error_message=result_dict["error_message"],
            is_timeout=self._timed_out,
            exit_code=exit_code,
            elapsed_seconds=elapsed,
        )
```

**Proposed code**:
```python
        pid = self._process.pid if self._process is not None else None
        if not self._parser.state.has_result_event:
            logger.warning(
                "No result event received from Codex CLI stream "
                "(pid=%s, exit_code=%s, timed_out=%s)",
                pid,
                exit_code,
                self._timed_out,
            )
            # Treat missing result event as error — Codex exited without
            # completing the turn, so there is no response to deliver.
            if not self._parser.state.is_error:
                self._parser.state.is_error = True
                if not self._parser.state.error_message:
                    self._parser.state.error_message = (
                        f"Codex CLI exited without completing the turn "
                        f"(exit_code={exit_code}, pid={pid})."
                    )
        elif (
            self._parser.state.input_tokens == 0
            and self._parser.state.output_tokens == 0
        ):
            logger.warning(
                "Result event received but token counts are both zero "
                "(pid=%s, exit_code=%s)",
                pid,
                exit_code,
            )

        # Treat non-zero exit code as error even if parser didn't flag it
        if exit_code != 0 and not self._parser.state.is_error:
            logger.warning(
                "Codex CLI exited with non-zero code %d but parser "
                "did not flag error (pid=%s, has_result=%s, response_len=%d)",
                exit_code,
                pid,
                self._parser.state.has_result_event,
                len(self._parser.state.response_text),
            )
            self._parser.state.is_error = True
            if not self._parser.state.error_message:
                self._parser.state.error_message = (
                    f"Codex CLI exited with code {exit_code}."
                )

        result_dict = self._parser.get_result()

        return ClaudeResult(
            session_id=result_dict["session_id"],
            response_text=result_dict["response_text"],
            input_tokens=result_dict["input_tokens"],
            output_tokens=result_dict["output_tokens"],
            is_error=result_dict["is_error"],
            error_message=result_dict["error_message"],
            is_timeout=self._timed_out,
            exit_code=exit_code,
            elapsed_seconds=elapsed,
        )
```

**Rationale**: A Codex process that exits without emitting `turn.completed` has failed by definition. Similarly, a non-zero exit code should always be treated as an error. This fix ensures the error signal propagates to the dispatcher, which then sends the error to Slack and triggers the circuit breaker.

---

### Fix 2: Eliminate silent return on empty `response_text` in `progress.py`

**Impact**: High — this is the final guard that silently swallows the empty response.

**File**: `src/opentree/runner/progress.py`
**Lines**: 314 (in `ProgressReporter.complete()`)

**Current code** (line 306-316):
```python
        if is_error:
            self._slack.send_message(
                channel=self._channel,
                text=f"❌ 處理失敗：{error_message or '發生未預期錯誤'}",
                thread_ts=self._thread_ts,
            )
            return

        if not response_text.strip():
            return

        reply_text = f"{response_text}\n\n_✅ 完成 (耗時 {_format_duration(elapsed)})_"
```

**Proposed code**:
```python
        if is_error:
            self._slack.send_message(
                channel=self._channel,
                text=f"❌ 處理失敗：{error_message or '發生未預期錯誤'}",
                thread_ts=self._thread_ts,
            )
            return

        if not response_text.strip():
            logger.warning(
                "[ProgressReporter.complete] Empty response_text with "
                "is_error=False — sending fallback error to user | "
                "channel=%s thread_ts=%s elapsed=%.1f",
                self._channel,
                self._thread_ts,
                elapsed,
            )
            self._slack.send_message(
                channel=self._channel,
                text="⚠️ 處理完成但未產生回覆。這可能是暫時性問題，請重新嘗試。",
                thread_ts=self._thread_ts,
            )
            return

        reply_text = f"{response_text}\n\n_✅ 完成 (耗時 {_format_duration(elapsed)})_"
```

**Rationale**: Even if Fix 1 correctly marks the result as an error, we should never silently drop an empty response. This serves as defense-in-depth: if any code path reaches `complete()` with `is_error=False` and empty text, the user still receives feedback. The previous silent `return` made it impossible for users to know something went wrong.

---

### Fix 3: Circuit breaker should count empty-response-without-error as failure

**Impact**: Medium — prevents cascading failures when Codex CLI has systemic issues.

**File**: `src/opentree/runner/dispatcher.py`
**Lines**: 526-529

**Current code**:
```python
            if result.is_error or result.is_timeout:
                self._circuit_breaker.record_failure()
            else:
                self._circuit_breaker.record_success()
```

**Proposed code**:
```python
            # Treat empty response (without error flag) as a failure for
            # circuit breaker purposes — the user received no reply.
            is_effective_failure = (
                result.is_error
                or result.is_timeout
                or (not result.response_text and not result.is_error)
            )
            if is_effective_failure:
                self._circuit_breaker.record_failure()
                if not result.is_error and not result.is_timeout:
                    logger.warning(
                        "Task %s: empty response without error flag — "
                        "recording as circuit breaker failure | "
                        "exit_code=%s session_id=%s",
                        task.task_id,
                        result.exit_code,
                        result.session_id or "(none)",
                    )
            else:
                self._circuit_breaker.record_success()
```

**Rationale**: With Fix 1 in place, this condition should rarely trigger for new cases. But it provides defense-in-depth: if somehow a task completes with `is_error=False` and empty response, the circuit breaker correctly counts it as a failure. Without this, 5 consecutive silent failures would not trip the circuit breaker, allowing a broken Codex CLI to silently eat all incoming requests.

---

### Fix 4: Mark `task_queue` correctly for empty-response cases

**Impact**: Medium — ensures queue stats accurately reflect failure count.

**File**: `src/opentree/runner/dispatcher.py`
**Lines**: 560-591

**Current code**:
```python
            if result.is_error:
                self._task_queue.mark_failed(task)
                return

            # Step 11: persist session_id.
            if result.session_id:
                self._session_mgr.set_session_id(task.thread_ts, result.session_id)
            ...
            # Step 12: mark completed and spawn threads for promoted tasks.
            promoted = self._task_queue.mark_completed(task)
```

**Proposed code**:
```python
            if result.is_error:
                promoted = self._task_queue.mark_failed(task)
                self._spawn_promoted(promoted)
                return

            # Defense-in-depth: treat empty response as failure for queue tracking
            if not result.response_text:
                logger.warning(
                    "Task %s completed with empty response (not flagged as error) "
                    "— marking as failed | exit_code=%s",
                    task.task_id,
                    result.exit_code,
                )
                promoted = self._task_queue.mark_failed(task)
                self._spawn_promoted(promoted)
                return

            # Step 11: persist session_id.
            if result.session_id:
                self._session_mgr.set_session_id(task.thread_ts, result.session_id)
            ...
            # Step 12: mark completed and spawn threads for promoted tasks.
            promoted = self._task_queue.mark_completed(task)
```

**Rationale**: The current code at line 560-562 calls `mark_failed` but does not call `_spawn_promoted` on the return value, which means promoted tasks from the pending queue don't get worker threads. The empty-response guard adds defense-in-depth.

**Note**: There are TWO pre-existing bugs where `mark_failed` doesn't spawn promoted tasks. Compare with line 590-591 (`mark_completed` does call `_spawn_promoted`) and line 595-596 (exception handler correctly spawns promoted). These must also be fixed:

**Bug 1 — File**: `src/opentree/runner/dispatcher.py`, line 550 (timeout path)

**Current**:
```python
                self._task_queue.mark_failed(task)
                return
```

**Proposed**:
```python
                promoted = self._task_queue.mark_failed(task)
                self._spawn_promoted(promoted)
                return
```

**Bug 2 — File**: `src/opentree/runner/dispatcher.py`, line 560-562 (error path)

**Current**:
```python
            if result.is_error:
                self._task_queue.mark_failed(task)
                return
```

**Proposed**:
```python
            if result.is_error:
                promoted = self._task_queue.mark_failed(task)
                self._spawn_promoted(promoted)
                return
```

**Impact**: When these paths are taken while tasks are queued, promoted tasks get stuck in the queue forever without worker threads. They would only be cleaned up by the queue watchdog after 30 minutes.

---

### Fix 5: Update completion blocks to show error when response is empty

**Impact**: Low-Medium — cosmetic but important for user experience.

**File**: `src/opentree/runner/dispatcher.py`
**Lines**: 552-558

**Current code**:
```python
            reporter.complete(
                response_text=result.response_text or "",
                elapsed=elapsed,
                is_error=result.is_error,
                error_message=result.error_message or "",
                completion_items=completion_items,
            )
```

With Fix 1 in place, `result.is_error` will be `True` for these cases, so the progress banner will correctly show "❌ 處理失敗" instead of "✅ 處理完成". No additional change needed here — Fix 1 cascades correctly through this path.

---

## Section 3: Observability Additions (Priority Order)

### Log Addition 1 — Final ClaudeResult Summary (HIGHEST PRIORITY)

**FILE**: `src/opentree/runner/codex_process.py`
**LOCATION**: After line 322 (just before `result_dict = self._parser.get_result()`), OR after line 335 (just before `return ClaudeResult(...)`)
**LOG_LEVEL**: INFO
**LOG_FORMAT**:
```python
logger.info(
    "Codex CLI finished | pid=%s exit_code=%s elapsed=%.1fs "
    "has_result_event=%s response_len=%d is_error=%s "
    "session_id=%s input_tokens=%d output_tokens=%d "
    "saw_agent_message=%s event_seq=%d timed_out=%s",
    pid,
    exit_code,
    elapsed,
    self._parser.state.has_result_event,
    len(self._parser.state.response_text),
    self._parser.state.is_error,
    self._parser.state.session_id or "(none)",
    self._parser.state.input_tokens,
    self._parser.state.output_tokens,
    self._parser._saw_agent_message,
    self._parser.state.event_seq,
    self._timed_out,
)
```
**PURPOSE**: Answers ALL four observability questions in a single log line: Did Codex produce turn.completed? Did it produce any agent_message? What was the final state? The current code only logs warnings for specific edge cases but never logs a complete summary.

---

### Log Addition 2 — Codex Spawn Details (HIGH PRIORITY)

**FILE**: `src/opentree/runner/codex_process.py`
**LOCATION**: Line 260, replace the existing `logger.debug("Spawning Codex CLI: %s", args[0])` with more detail
**LOG_LEVEL**: INFO
**LOG_FORMAT**:
```python
logger.info(
    "Spawning Codex CLI | cmd=%s cwd=%s sandboxed=%s "
    "session_id=%s message_len=%d",
    args[0],
    self._cwd,
    self._sandboxed,
    self._session_id or "(new)",
    len(self._message),
)
```
**PURPOSE**: Correlates spawn with completion. Current log only shows `Spawning Codex CLI: codex` with no context.

---

### Log Addition 3 — Empty Response Explicit Reason (HIGH PRIORITY)

**FILE**: `src/opentree/runner/progress.py`
**LOCATION**: Line 314 (replacing the silent `return`)
**LOG_LEVEL**: WARNING
**LOG_FORMAT**: (already included in Fix 2 above)
```python
logger.warning(
    "[ProgressReporter.complete] Empty response_text with "
    "is_error=False — sending fallback error to user | "
    "channel=%s thread_ts=%s elapsed=%.1f",
    self._channel,
    self._thread_ts,
    elapsed,
)
```
**PURPOSE**: Explicitly answers "Why was no reply sent?" — currently the silent `return` leaves zero trace in logs.

---

### Log Addition 4 — Dispatcher Task Result Summary (MEDIUM PRIORITY)

**FILE**: `src/opentree/runner/dispatcher.py`
**LOCATION**: After line 525 (`tracker.finish()`), before the circuit breaker decision
**LOG_LEVEL**: INFO
**LOG_FORMAT**:
```python
logger.info(
    "Task %s result | thread_ts=%s is_error=%s is_timeout=%s "
    "exit_code=%s response_len=%d session_id=%s "
    "elapsed=%.1fs",
    task.task_id,
    task.thread_ts,
    result.is_error,
    result.is_timeout,
    result.exit_code,
    len(result.response_text or ""),
    result.session_id or "(none)",
    result.elapsed_seconds,
)
```
**PURPOSE**: Provides a task-level summary that connects the Codex process result to the Slack thread. Essential for correlating incidents by thread_ts.

---

### Log Addition 5 — Circuit Breaker Decision (LOW PRIORITY)

**FILE**: `src/opentree/runner/dispatcher.py`
**LOCATION**: After the circuit breaker `record_success()`/`record_failure()` call
**LOG_LEVEL**: DEBUG
**LOG_FORMAT**:
```python
logger.debug(
    "Circuit breaker decision for task %s: %s | "
    "state=%s failure_count=%d",
    task.task_id,
    "failure" if is_effective_failure else "success",
    self._circuit_breaker.get_status()["state"],
    self._circuit_breaker.get_status()["failure_count"],
)
```
**PURPOSE**: Makes circuit breaker state transitions traceable per-task.

---

### Log Addition 6 — Parser Event Trace (DEBUG, optional)

**FILE**: `src/opentree/runner/codex_stream_parser.py`
**LOCATION**: Inside `_mark_event()` (line 404)
**LOG_LEVEL**: DEBUG
**LOG_FORMAT**:
```python
logger.debug(
    "StreamParser event=%s seq=%d phase=%s",
    event,
    self._state.event_seq,
    self._state.phase.value,
)
```
**PURPOSE**: For deep debugging only — traces every parser state transition. When `event_seq=0` at completion, we know Codex emitted zero parseable events (confirming the "no output at all" scenario).

---

## Section 4: Testing Recommendations

### Unit Tests

1. **`test_codex_process_no_result_event_sets_error`**
   - Mock Codex subprocess that exits with code 1 and emits no JSONL
   - Assert `ClaudeResult.is_error == True`
   - Assert `ClaudeResult.error_message` contains "exit_code=1"

2. **`test_codex_process_nonzero_exit_no_result_sets_error`**
   - Mock Codex subprocess that emits `thread.started` but no `turn.completed`, exits with code 1
   - Assert `ClaudeResult.is_error == True`

3. **`test_codex_process_nonzero_exit_with_result_preserves_error`**
   - Mock Codex subprocess that emits `turn.completed` with `is_error=True`, exits with code 1
   - Assert `ClaudeResult.is_error == True` and `error_message` from the result event

4. **`test_progress_reporter_empty_response_sends_fallback`**
   - Call `ProgressReporter.complete(response_text="", is_error=False)`
   - Assert `send_message` is called with the fallback warning text

5. **`test_progress_reporter_empty_response_with_error_sends_error`**
   - Call `ProgressReporter.complete(response_text="", is_error=True, error_message="...")`
   - Assert `send_message` is called with the error text (not the fallback)

6. **`test_dispatcher_empty_response_marks_failed`**
   - Mock `CodexProcess.run()` to return `ClaudeResult(is_error=False, response_text="")`
   - Assert `task_queue.mark_failed()` is called, NOT `mark_completed()`

7. **`test_dispatcher_circuit_breaker_counts_empty_response_as_failure`**
   - Same setup as above
   - Assert `circuit_breaker.record_failure()` is called, NOT `record_success()`

8. **`test_codex_stream_parser_no_events_returns_empty_state`**
   - Create a `StreamParser`, call `get_result()` without any `parse_line()` calls
   - Assert `has_result_event=False`, `is_error=False`, `response_text=""`
   - (This documents the current behavior that Fix 1 addresses at the process level)

9. **`test_dispatcher_mark_failed_spawns_promoted`**
   - Verify that `mark_failed()` return value is passed to `_spawn_promoted()`
   - (Regression test for the pre-existing bug in Fix 4)

### Integration Tests

1. **`test_end_to_end_codex_exit_code_1_shows_error`**
   - Start a real dispatcher with a mock Slack API
   - Submit a task where `codex exec` will exit with code 1 (e.g., bad OPENAI_API_KEY)
   - Assert: Slack receives "❌ 處理失敗" (not "✅ 處理完成")
   - Assert: A reply message is sent to the thread (not silent)
   - Assert: Circuit breaker failure count incremented

2. **`test_end_to_end_codex_stdin_blocked_shows_error`**
   - Create a wrapper script that prints `"Reading additional input from stdin..."` to stderr and exits with code 1
   - Configure it as `codex_command` in RunnerConfig
   - Submit a task and verify the full error pipeline

3. **`test_stress_consecutive_silent_failures_trip_circuit_breaker`**
   - Submit 5 tasks that all produce empty responses
   - Assert circuit breaker transitions to OPEN state
   - Assert 6th task is rejected with "service temporarily unavailable"

---

## Appendix: All Silent-Failure Escape Paths (Task 2 Results)

### Scenario A: No result event, non-zero exit code (Cases A & B)

- **Condition**: Codex exits with code 1 before emitting `turn.completed`
- **Parser state**: `has_result_event=False`, `is_error=False`, `response_text=""`
- **Current detection**: WARNING logged at `codex_process.py:305-311`, but `is_error` remains `False`
- **Observability gap**: The WARNING is logged but not actionable — no downstream component acts on it
- **Fix**: Fix 1 (set `is_error=True` when `has_result_event=False`)

### Scenario B: Result event received but response_text is empty

- **Condition**: Codex emits `turn.completed` but never emits `item.completed` with `type=agent_message`
- **Parser state**: `has_result_event=True`, `is_error=True` (only if `_saw_error_hint=True`), `response_text=""`
- **Sub-case B1**: `_saw_error_hint=True` -> `is_error=True` -> `Phase.ERROR` -> correctly reported as error
- **Sub-case B2**: `_saw_error_hint=False` -> `is_error=False` -> `Phase.COMPLETED` -> **SILENT FAILURE**
  - This happens when Codex completes a turn without producing an agent message and without any error hint
  - Example: Codex's internal reasoning decides there is nothing to say (unlikely but possible)
- **Current detection**: Not detected at all for sub-case B2
- **Observability gap**: No log distinguishes "completed with response" from "completed without response"
- **Fix**: Fix 1 (non-zero exit code check) catches some cases; Fix 2 (progress.py fallback) catches the rest; Fix 3 (circuit breaker) provides systemic protection

### Scenario C: Result event with response, but response only contains whitespace

- **Condition**: Codex produces an `agent_message` with text like `" "` or `"\n"`
- **Parser state**: `has_result_event=True`, `is_error=False`, `response_text="  \n  "`
- **Downstream**: `progress.py:314` — `if not response_text.strip(): return` — silently drops it
- **Current detection**: None
- **Observability gap**: No log, no user notification
- **Fix**: Fix 2 (progress.py sends fallback message instead of silent return)

### Scenario D: Codex times out with non-empty partial response

- **Condition**: Codex emits `agent_message` with partial text, then gets killed by heartbeat/task timeout
- **Parser state**: `response_text` may be non-empty, `has_result_event=False`, `is_error=False`
- **Downstream**: `is_timeout=True` is set, BUT `is_error` remains `False` in the parser
- **Current detection**: Timeout path in `dispatcher.py:538-551` correctly handles this (sends timeout error)
- **Observability gap**: Minor — the partial response text is lost (not logged)
- **Fix**: Not needed for the error path, but Log Addition 1 would capture the partial response length

### Scenario E: Exception in progress_callback prevents state update

- **Condition**: `_tracking_callback` raises an exception
- **Parser state**: Correct, but `reporter.update()` never called
- **Current detection**: `codex_process.py:358-359` catches and logs the exception
- **Downstream**: Progress display may be stale, but final result is unaffected
- **Fix**: Not needed — existing exception handling is adequate

---

## Summary of Priority Actions

| Priority | Action | File | Impact |
|----------|--------|------|--------|
| P0 | Fix 1: Treat no-result-event as error | `codex_process.py` | Stops all silent failures at source |
| P0 | Fix 2: Send fallback on empty response | `progress.py` | Defense-in-depth: user always gets feedback |
| P1 | Log 1: Final result summary | `codex_process.py` | Single-line diagnosis for any future incident |
| P1 | Fix 3: Circuit breaker counts empty as failure | `dispatcher.py` | Prevents cascading silent failures |
| P1 | Fix 4: Mark failed + spawn promoted | `dispatcher.py` | Correct queue tracking + pre-existing bug fix |
| P2 | Log 4: Task result summary | `dispatcher.py` | Thread-ts correlation for incidents |
| P2 | Log 2: Spawn details | `codex_process.py` | Spawn-to-completion correlation |
| P3 | Log 3: Empty response reason | `progress.py` | Already covered by Fix 2 warning log |
| P3 | Log 5-6: Circuit breaker + parser trace | Various | Deep debugging only |

### Upstream Issue to Track

The `"Reading additional input from stdin..."` behavior from Codex CLI should be reported upstream. Even with `stdin=/dev/null`, Codex CLI should not attempt to read stdin when a positional PROMPT argument is provided. This may be a regression in a recent Codex CLI update.
