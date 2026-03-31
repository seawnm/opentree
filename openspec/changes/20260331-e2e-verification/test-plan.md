# E2E Test Execution Plan: Bot_Walter (OpenTree)

> Date: 2026-03-31
> Target: OpenTree (Walter) instance running in Slack betaroom
> Estimated total: ~60 minutes (3 batches)

## Environment Reference

| Item | Value |
|------|-------|
| Bot home | `/mnt/e/develop/mydev/project/trees/bot_walter/` |
| Bot runtime | `opentree start --mode slack --home <bot_home>` via `uv run --directory <bot_home>/opentree` |
| Bot User ID | `U0APZ9MR997` |
| Bot mention | `<@U0APZ9MR997>` |
| Slack Channel (betaroom) | `C0AK78CNYBU` |
| Heartbeat file | `/mnt/e/develop/mydev/project/trees/bot_walter/data/bot.heartbeat` |
| Log file (today) | `/mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log` |
| Sessions file | `/mnt/e/develop/mydev/project/trees/bot_walter/data/sessions.json` |
| DOGI message-tool | `uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send` |
| DOGI slack-query-tool | `uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool` |

### Shorthand

Throughout this document:
- `$BOT_HOME` = `/mnt/e/develop/mydev/project/trees/bot_walter`
- `$DOGI_DIR` = `/mnt/e/develop/mydev/slack-bot`
- `$LOG` = `$BOT_HOME/data/logs/2026-03-31.log`
- `$CHANNEL` = `C0AK78CNYBU`
- `$BOT_MENTION` = `<@U0APZ9MR997>`

---

## Batch 1: Prerequisites + Quick Tests (~15 min)

### Test A0: Pre-check — Bot_Walter is alive

**Test ID**: A0
**Pre-conditions**: Bot_Walter was started before test session
**Quota impact**: None (no Claude API calls)

**Steps**:

```bash
# Step 1: Check heartbeat freshness (should be updated within last 120s)
stat /mnt/e/develop/mydev/project/trees/bot_walter/data/bot.heartbeat

# Step 2: Check process is running
pgrep -af "opentree start.*bot_walter"

# Step 3: Check log activity in last 5 minutes
tail -20 /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log
```

**Expected result**:
- Heartbeat file modified within last 120 seconds
- At least one `opentree start --mode slack` process visible
- Log shows recent activity (Socket Mode debug messages)

**Verification method**:
- Heartbeat: `$(date +%s) - $(stat -c %Y <heartbeat_file>)` < 120
- Process: `pgrep` returns at least 1 PID
- Logs: last entry timestamp within 5 minutes of current time

**Timeout**: 1 minute

**Pass criteria**: All 3 checks pass
**Fail action**: If bot is down, start it with:
```bash
cd /mnt/e/develop/mydev/project/trees/bot_walter && nohup bash bin/run.sh >> data/logs/wrapper.log 2>&1 &
```
Wait 30s, then re-check.

---

### Test A1-partial: CLAUDE_CONFIG_DIR Quick Check

**Test ID**: A1-partial
**Pre-conditions**: A0 passed (bot is alive)
**Quota impact**: 1 Claude API call (minimal — short response expected)

**Purpose**: Verify that Bot_Walter's Claude CLI is using the correct config directory (not the host user's `~/.claude/`). This is a partial check; the full A1 test is deferred to a deeper config audit.

**Steps**:

```bash
# Step 1: Check if opentree passes CLAUDE_CONFIG_DIR in env
grep -r "CLAUDE_CONFIG_DIR\|claude_config" /mnt/e/develop/mydev/project/trees/bot_walter/opentree/src/ 2>/dev/null | head -20

# Step 2: Check if there's a .claude/ dir in workspace or bot home
ls -la /mnt/e/develop/mydev/project/trees/bot_walter/.claude/ 2>/dev/null
ls -la /mnt/e/develop/mydev/project/trees/bot_walter/workspace/.claude/ 2>/dev/null

# Step 3: Send a lightweight message to trigger a Claude call and inspect logs
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> ping"
```

```bash
# Step 4: Wait 30s, then check logs for CLAUDE_CONFIG_DIR or config path references
sleep 30 && grep -i "claude_config\|config_dir\|CLAUDE_HOME" \
  /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log | tail -10
```

```bash
# Step 5: Read the Slack thread response
# (use the message_ts from Step 3's JSON output)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <message_ts_from_step3>
```

**Expected result**:
- Bot responds to "ping" in the thread (confirms basic message handling)
- Source code or logs reveal CLAUDE_CONFIG_DIR points to bot-specific path (not `~/.claude/`)
- OR: workspace `.claude/` directory exists with bot-specific settings

**Verification method**:
- Step 3 returns `{"success": true, "message_ts": "..."}` — record this `message_ts`
- Step 5 shows a bot reply in the thread (any response = pass for ping)
- Step 1/2/4 reveal config path isolation

**Timeout**: 90 seconds (30s for Claude response + 60s buffer)

**Notes**:
- If source grep reveals nothing about CLAUDE_CONFIG_DIR, check the opentree CLI's runner module for how it invokes Claude
- This test doubles as a basic "bot responds to mention" smoke test

---

### Test A2: Admin Commands — status and help

**Test ID**: A2
**Pre-conditions**: A0 passed, A1-partial's ping confirmed bot responds
**Quota impact**: 2 Claude API calls

**Steps**:

```bash
# Step 1: Send "status" command
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> status"
```

```bash
# Step 2: Wait 45s, read the thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <status_message_ts>
```

```bash
# Step 3: Send "help" command (new thread)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> help"
```

```bash
# Step 4: Wait 45s, read the thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <help_message_ts>
```

**Expected result**:
- **status**: Bot replies with operational info (uptime, version, or similar status block)
- **help**: Bot replies with available commands or usage guide

**Verification method**:
- Thread has a reply from `U0APZ9MR997` (or the bot's `bot_id`)
- Reply text contains status-related keywords (version, uptime, running, modules) for status
- Reply text contains command-related keywords (help, commands, usage) for help
- No error messages in logs for these interactions

**Timeout**: 60 seconds per command (120s total)

**Pass criteria**: Both commands receive meaningful, non-error replies

---

**Batch 1 checkpoint**: Pause here. Report results to user. Confirm before proceeding to Batch 2.

**Batch 1 API quota consumed**: ~3 Claude API calls

---

## Batch 2: Core Functionality (~20 min)

### Test A7: Multi-turn Conversation (Context Retention)

**Test ID**: A7
**Pre-conditions**: Batch 1 passed
**Quota impact**: 5-6 Claude API calls (one per turn)

**Purpose**: Verify that Bot_Walter retains context across 5+ exchanges in the same Slack thread.

**Steps**:

```bash
# Step 1: Start a new thread with context-setting message
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> Let's test your memory. My favorite color is blue. Please remember that."
```

Record `<thread_ts>` from the response JSON.

```bash
# Step 2: Wait 60s for response, then send follow-up in same thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --thread-ts <thread_ts> \
  --text "<@U0APZ9MR997> And my favorite number is 42. Got it?"
```

```bash
# Step 3: Wait 60s, send turn 3
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --thread-ts <thread_ts> \
  --text "<@U0APZ9MR997> Now tell me: what are my two favorites I just told you?"
```

```bash
# Step 4: Wait 60s, send turn 4 (topic shift)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --thread-ts <thread_ts> \
  --text "<@U0APZ9MR997> Great. Now a different topic: what is 17 * 23?"
```

```bash
# Step 5: Wait 60s, send turn 5 (recall original context)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --thread-ts <thread_ts> \
  --text "<@U0APZ9MR997> Going back to the beginning - remind me what color I said was my favorite?"
```

```bash
# Step 6: Wait 60s, read entire thread to evaluate
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <thread_ts> \
  --limit 20
```

**Expected result**:
- Turn 3: Bot correctly recalls "blue" (color) and "42" (number)
- Turn 4: Bot computes 391 (or close)
- Turn 5: Bot recalls "blue" even after topic shift, demonstrating context persistence

**Verification method**:
- Parse thread JSON for bot replies
- Turn 3 reply contains both "blue" and "42"
- Turn 5 reply contains "blue"
- Check `sessions.json` to confirm same session_id used across all turns

```bash
# Verify session continuity
cat /mnt/e/develop/mydev/project/trees/bot_walter/data/sessions.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
thread_ts = '<thread_ts>'
for key, val in data.items():
    if thread_ts in key:
        print(f'Session: {val}')
        break
else:
    print('No session found for thread')
"
```

**Timeout**: 6 minutes total (60s per turn + 60s final read)

**Pass criteria**:
- [x] Bot replies to all 5 turns
- [x] Turn 3 correctly recalls both facts
- [x] Turn 5 correctly recalls color after topic shift
- [x] Same session ID used throughout (session continuity)

---

### Test A5: Concurrent Requests (Queue Behavior)

**Test ID**: A5
**Pre-conditions**: Batch 1 passed
**Quota impact**: 3 Claude API calls

**Purpose**: Send 3 @mentions rapidly in separate threads and verify the bot queues/processes them without crashes.

**Steps**:

```bash
# Step 1: Send 3 messages rapidly (within 5 seconds)
# Message 1
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> Concurrent test 1: What is the capital of France?"

# Message 2 (immediately after)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> Concurrent test 2: What is the capital of Japan?"

# Message 3 (immediately after)
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> Concurrent test 3: What is the capital of Brazil?"
```

Record all 3 `message_ts` values.

```bash
# Step 2: Wait 3 minutes (bot may queue and process sequentially)
# Then read all 3 threads
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU --thread-ts <msg1_ts>

uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU --thread-ts <msg2_ts>

uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU --thread-ts <msg3_ts>
```

```bash
# Step 3: Check logs for queue behavior
grep -E "queue|concurrent|enqueue|dequeue|task.*start|task.*complete" \
  /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log | tail -30
```

**Expected result**:
- All 3 messages eventually get replies (may take up to 3 min if processed serially)
- No crash or unhandled exception in logs
- Log shows queuing behavior (tasks enqueued, then processed sequentially or with concurrency limit)
- Replies contain correct answers: Paris, Tokyo, Brasilia

**Verification method**:
- All 3 threads have a bot reply
- No ERROR-level entries in logs during this time window
- Queue entries visible in logs

**Timeout**: 4 minutes (accounting for serial processing of 3 tasks)

**Pass criteria**:
- [x] All 3 messages receive replies (no message dropped)
- [x] No crash in logs
- [x] Replies are correct (Paris, Tokyo, Brasilia)

---

### Test A3: DM Test (Direct Message)

**Test ID**: A3
**Pre-conditions**: Bot is alive (A0 passed)
**Quota impact**: 1 Claude API call

**Purpose**: Verify Bot_Walter responds to direct messages (not just channel mentions).

**Important note**: The DOGI `message-tool` targets channels. For DM testing, we need the bot's DM channel ID.

**Steps**:

```bash
# Step 1: Look up Bot_Walter's DM channel via Slack API
# Use slack-query-tool to find conversations with the bot
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool list-channels \
  --types "im" --limit 200
```

```bash
# Step 2: Identify the DM channel for Bot_Walter (U0APZ9MR997)
# From the list, find the channel with user = U0APZ9MR997
# If no existing DM channel, we need to open one via Slack API:
# This may require using slack_client directly or the Slack Web API
```

```bash
# Step 3: If DM channel found, send a message
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel <dm_channel_id> \
  --text "Hello, this is a DM test. Can you hear me?"
```

```bash
# Step 4: Wait 60s, read DM thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-channel \
  --channel <dm_channel_id> \
  --limit 5
```

**Expected result**:
- Bot replies in the DM channel
- Reply is contextually appropriate (not a "channel only" error)

**Verification method**:
- DM channel shows a bot reply after our message
- Check logs for DM event handling

**Timeout**: 90 seconds

**Fallback**: If DM channel cannot be opened via existing tools, **mark this test as SKIPPED** with reason "DM channel setup requires interactive Slack API call not available in current tooling." Revisit in manual testing phase.

**Pass criteria**:
- [x] Bot responds to DM
- OR: Documented as SKIPPED with clear reason

---

**Batch 2 checkpoint**: Pause here. Report results to user. Confirm before proceeding to Batch 3.

**Batch 2 API quota consumed**: ~9-10 Claude API calls

---

## Batch 3: File & Wrapper (~25 min)

### Test A4: File Upload + Processing

**Test ID**: A4
**Pre-conditions**: Batch 1 passed
**Quota impact**: 1 Claude API call

**Purpose**: Verify Bot_Walter can handle a message accompanied by a file upload.

**Steps**:

```bash
# Step 1: Create a small test file
mkdir -p /tmp/slack-bot/e2e-test/
cat > /tmp/slack-bot/e2e-test/test-data.txt << 'FILEEOF'
OpenTree E2E Test File
======================
Line 1: Alpha
Line 2: Beta
Line 3: Gamma

Question: How many Greek letter names are in this file?
FILEEOF
```

```bash
# Step 2: Upload the file to betaroom channel with a mention
# Use DOGI's upload-tool to send the file, then mention bot in that thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.upload_tool upload \
  /tmp/slack-bot/e2e-test/test-data.txt \
  --channel C0AK78CNYBU \
  --comment "<@U0APZ9MR997> Please read this file and answer the question inside it."
```

Record the `thread_ts` from the upload response.

```bash
# Step 3: If upload-tool doesn't trigger the bot (because the mention is in the
# comment, not a threaded message), send a follow-up mention in the file's thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --thread-ts <file_thread_ts> \
  --text "<@U0APZ9MR997> Please read the file above and answer the question in it."
```

```bash
# Step 4: Wait 90s, then read the thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <file_thread_ts> \
  --limit 10
```

```bash
# Step 5: Check logs for file download activity
grep -iE "file|download|upload" \
  /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log | tail -15
```

**Expected result**:
- Bot replies in the thread
- Reply references the file content (mentions "3 Greek letter names" or lists Alpha/Beta/Gamma)
- Logs show file download attempt

**Verification method**:
- Thread has a bot reply containing reference to file content
- Log entries show file processing
- Answer should be "3" (Alpha, Beta, Gamma)

**Timeout**: 2 minutes

**Pass criteria**:
- [x] Bot acknowledges the file
- [x] Bot's answer references actual file content (not a generic response)
- [x] Log shows file download/processing activity

**Known risk**: If Bot_Walter doesn't support file handling, the bot may respond to the text only and ignore the file. This is a valid finding (document as partial pass).

---

### Test A6: run.sh Wrapper — Crash Recovery

**Test ID**: A6
**Pre-conditions**: A0 passed (bot is alive and managed by wrapper)
**Quota impact**: 1 Claude API call (post-recovery verification)

**Purpose**: Verify that killing the bot process triggers automatic restart by the wrapper (run.sh).

**CAUTION**: This test temporarily takes the bot offline. Ensure no other tests are running.

**Steps**:

```bash
# Step 1: Record current PIDs
echo "=== Pre-kill state ==="
pgrep -af "opentree start.*bot_walter"
stat /mnt/e/develop/mydev/project/trees/bot_walter/data/bot.heartbeat
```

```bash
# Step 2: Identify the wrapper (run.sh) and bot (opentree) processes
# The wrapper should be the parent. We kill the bot, NOT the wrapper.
# Find the Python process (the actual bot), not the uv runner
BOT_PID=$(pgrep -f "opentree/.venv/bin/opentree start --mode slack" | head -1)
echo "Bot PID to kill: $BOT_PID"
```

```bash
# Step 3: Kill the bot process with SIGTERM (graceful)
kill $BOT_PID
echo "SIGTERM sent to $BOT_PID at $(date)"
```

```bash
# Step 4: Wait 10s, check if process is gone
sleep 10
echo "=== Post-kill check (10s) ==="
pgrep -af "opentree start.*bot_walter" || echo "Bot process is down (expected)"
```

```bash
# Step 5: Wait another 30s for wrapper to restart
sleep 30
echo "=== Recovery check (40s total) ==="
pgrep -af "opentree start.*bot_walter"
stat /mnt/e/develop/mydev/project/trees/bot_walter/data/bot.heartbeat
```

```bash
# Step 6: If not recovered by 40s, wait another 30s (total 70s)
sleep 30
echo "=== Recovery check (70s total) ==="
pgrep -af "opentree start.*bot_walter"
```

```bash
# Step 7: Verify bot is functional by sending a message
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AK78CNYBU \
  --text "<@U0APZ9MR997> Post-recovery test: are you back online?"
```

```bash
# Step 8: Wait 60s, read the thread
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AK78CNYBU \
  --thread-ts <recovery_message_ts>
```

```bash
# Step 9: Check logs for restart evidence
grep -iE "restart|recover|start|shutdown|signal|SIGTERM" \
  /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log | tail -20
```

**Expected result**:
- Bot process terminates after SIGTERM (Step 4)
- Wrapper automatically restarts the bot within 60-90 seconds (Step 5 or 6)
- Heartbeat file gets updated again after restart
- Bot responds to the post-recovery message (Step 8)

**Verification method**:
- Step 4: `pgrep` returns no results (bot is down)
- Step 5 or 6: `pgrep` returns new PID(s) (bot restarted)
- Step 8: Thread has a bot reply
- Step 9: Logs show restart sequence

**Timeout**: 3 minutes (kill + wait + recovery + verification)

**Pass criteria**:
- [x] Bot process stops after SIGTERM
- [x] Wrapper restarts bot within 90 seconds
- [x] Bot responds to post-recovery message
- [x] Logs show restart sequence

**Fail action**: If wrapper does not restart within 90 seconds:
1. Check if wrapper process (run.sh/bash) is still running: `pgrep -af "run.sh"`
2. Check wrapper logs: `tail -20 /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/wrapper.log`
3. Manually restart: `cd /mnt/e/develop/mydev/project/trees/bot_walter && nohup bash bin/run.sh >> data/logs/wrapper.log 2>&1 &`
4. Mark test as FAILED with root cause

**IMPORTANT**: If the wrapper itself is not running (bot was started directly without wrapper), this test should be **SKIPPED** and noted. Check with:
```bash
pgrep -af "run.sh.*bot_walter"
```

---

**Batch 3 checkpoint**: Report final results to user.

**Batch 3 API quota consumed**: ~2 Claude API calls

---

## Summary: API Quota Budget

| Batch | Tests | Claude API Calls | Time |
|-------|-------|-----------------|------|
| Batch 1 | A0, A1-partial, A2 | ~3 | ~15 min |
| Batch 2 | A7, A5, A3 | ~9-10 | ~20 min |
| Batch 3 | A4, A6 | ~2 | ~25 min |
| **Total** | **7 tests** | **~14-15** | **~60 min** |

## Execution Constraints

1. **Max 2 agents running concurrently** — Tests within each batch can be parallelized in pairs, but never more than 2 at once
2. **Batch gating** — Do NOT proceed to next batch without user confirmation
3. **Parallel opportunities within batches**:
   - Batch 1: A0 first (prereq), then A1-partial and A2 in parallel
   - Batch 2: A7 and A5 in parallel (different threads, independent), then A3
   - Batch 3: A4 first, then A6 (A6 kills bot, must be last)
4. **A6 must be the last test** — It kills the bot process; ensure all other tests are complete
5. **Record all message_ts values** — Needed for thread reads and post-hoc analysis
6. **Log snapshots** — Before each batch, note the last log line number to isolate batch-specific entries

## Result Template

Use this template to record results per test:

```
### Test [ID]: [Name]
- **Status**: PASS / FAIL / PARTIAL / SKIPPED
- **Start time**: HH:MM
- **End time**: HH:MM
- **Thread TS**: (for Slack-based tests)
- **Observations**: 
- **Log evidence**: (relevant log lines)
- **Issues found**:
```

## Post-Test Cleanup

After all batches complete:

```bash
# 1. Verify bot is alive and healthy (especially after A6)
pgrep -af "opentree start.*bot_walter"
stat /mnt/e/develop/mydev/project/trees/bot_walter/data/bot.heartbeat

# 2. Clean up test artifacts
rm -rf /tmp/slack-bot/e2e-test/

# 3. Collect final log snapshot
tail -50 /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/2026-03-31.log > /tmp/e2e-final-log-snapshot.txt
```
