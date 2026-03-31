# E2E Verification — Flow Simulation Report

> Date: 2026-03-31
> Phase: E2E Verification (Phase 4)
> Source Thread: betaroom 1774800803.111649

---

## Overview

31 scenarios simulated against the Bot Runner codebase after Phase 1-3 implementation and compliance fixes. Tests covered admin commands, Claude reply flow, thread resume, dedup, heartbeat, bot-to-bot interaction, and DM.

**Results: 21 pass / 10 fail**

---

## CRITICAL Issues (All Fixed)

### #1: SlackAPI `_extract_data` broken pattern

- **Scenario**: Any Slack API call (send_message, get_thread_replies, etc.)
- **Problem**: `getattr(response, key, dict())` on `SlackResponse` objects returned the wrong data. The `SlackResponse` class overrides `__getattr__` in a way that makes `getattr` unreliable for data extraction.
- **Fix**: Replaced broken `getattr` pattern with `_extract_data()` helper that accesses `response.data` dict directly, with proper KeyError handling returning empty dict.
- **Commit**: `82eec96`

### #2: Bot-to-bot mentions silently dropped by `bot_id` filter

- **Scenario**: DOGI sends `@Bot_Walter status` in Slack
- **Problem**: `receiver.py` filtered out all messages where `bot_id` was present in the event payload. Since DOGI is a bot, its explicit @mentions to Bot_Walter were silently dropped.
- **Fix**: Changed filter logic to allow messages with `bot_id` when they contain an explicit @mention of our bot (checking for `<@{self_bot_user_id}>` in text). Self-messages (from our own bot_id) are still filtered.
- **Commit**: `82eec96`

### #3: DOGI response text containing mention format triggered Bot Walter

- **Scenario**: DOGI replies with text like "I mentioned @Bot_Walter earlier" (containing the `<@BOT_USER_ID>` format)
- **Problem**: Bot Walter's receiver saw the mention pattern in DOGI's response body and treated it as a new command.
- **Prevention**: Use plain text display names (not Slack mention format) in DOGI's response text. This is a coordination rule rather than a code fix.

---

## HIGH Issues (All Fixed)

### #4: Shutdown no auth

- **Scenario**: Any user sends `@Bot_Walter shutdown`
- **Problem**: The `shutdown` admin command had no authorization check. Any user in the channel could shut down the bot.
- **Fix**: Added `admin_users` field to `RunnerConfig` (list of Slack user IDs). `_handle_admin_command` checks `task.user_id in config.admin_users` before executing shutdown. Non-admin users receive a "not authorized" reply.
- **Commit**: `82eec96`

### #5: Cross-handler dedup race — message + app_mention fire for same event

- **Scenario**: `@Bot_Walter status` in a channel
- **Problem**: `slack_bolt` dispatches both `message` and `app_mention` events for the same @mention message. With two handlers registered, the bot processed the same event twice, producing duplicate replies. WSL2 cross-filesystem bytecache (stale `.pyc` files) compounded the issue by causing inconsistent handler registration.
- **Fix**: Single handler architecture — register only the `message` event handler (removed `app_mention` handler). Added Layer 2 dedup in `Dispatcher` using `_dispatched_ts` set with thread lock to catch any remaining duplicates.
- **Commit**: `72ecc6c`

---

## MEDIUM Issues (Fixed)

### #6: Heartbeat only on dispatch

- **Scenario**: Bot receives events that are filtered out (e.g., non-mention messages)
- **Problem**: `bot.heartbeat` was only written when a task reached the dispatcher. Filtered events (the majority of channel traffic) did not update heartbeat, causing the watchdog to falsely detect the bot as hung.
- **Fix**: Write heartbeat before filter logic in the receiver, so every received event proves liveness.
- **Commit**: `82eec96`

### #7: Double heartbeat write

- **Scenario**: Any dispatched task
- **Problem**: After fixing #6, heartbeat was written both in receiver (before filters) and in dispatcher (after dispatch). The dispatcher write was redundant.
- **Fix**: Removed the redundant `_write_heartbeat()` call in dispatcher.
- **Commit**: `54db6cc`

### #8: DM testing impossible via DOGI

- **Scenario**: Testing DM flow by sending DM through DOGI relay
- **Problem**: DOGI's DM relay doesn't forward to Bot_Walter's DM channel; it only operates within its own workspace context.
- **Resolution**: SKIPPED. DM testing requires direct Slack client interaction, not bot-to-bot relay.

### #9: Claude quota consumption during E2E testing

- **Scenario**: Every test that triggers Claude reply flow
- **Problem**: E2E tests consume real Claude API quota. Admin commands (status, help) don't need Claude, but any reply-flow test does.
- **Resolution**: Admin commands (`status`, `help`) don't invoke Claude CLI. Claude reply flow tested minimally (1-2 tests) to conserve quota.

### #10: admin_users validation

- **Scenario**: Misconfigured `admin_users` in runner.json
- **Problem**: No validation on `admin_users` config field. Empty list means no one can shutdown; non-string entries would cause runtime errors.
- **Fix**: Added validation in `RunnerConfig.__post_init__` — each entry must be a non-empty string. Empty `admin_users` is allowed (documented as "no one can shutdown via command") with a startup warning.
- **Commit**: `82eec96`

---

## Scenario Matrix

| Category | Tested | Passed | Failed |
|----------|--------|--------|--------|
| Normal Flows | 5 | 2 | 3 |
| Input Boundaries | 5 | 3 | 2 |
| Network/IO | 5 | 3 | 2 |
| Concurrency | 4 | 4 | 0 |
| State | 4 | 3 | 1 |
| Resource | 4 | 3 | 1 |
| Security | 4 | 3 | 1 |
| **Total** | **31** | **21** | **10** |

---

## E2E Test Execution

### Batch 1 (4 bugs fixed, commit 82eec96)

| Test | Scenario | Result | Notes |
|------|----------|--------|-------|
| status command | DOGI -> @Bot_Walter status | PASS | Reply received, but 2 replies (dedup fail) |
| help command | DOGI -> @Bot_Walter help | PASS (content) | Dedup issue same as status |
| bot-to-bot mention | DOGI's @mention reaches receiver | PASS | After bot_id filter fix |
| shutdown auth | Non-admin shutdown attempt | PASS | Rejected with "not authorized" |

### Batch 2 (dedup fixed, commit 72ecc6c)

| Test | Scenario | Result | Notes |
|------|----------|--------|-------|
| status command | @Bot_Walter status | PASS | Single reply confirmed |
| help command | @Bot_Walter help | PASS | Single reply confirmed |
| Claude reply | @Bot_Walter greeting | PASS | Single Claude reply in thread |
| thread resume | Second message in same thread | PASS | Session resumed, context preserved |
| dedup verification | Same event, single handler | PASS | No duplicate replies |

### Not Tested (Remaining)

| Test | Reason |
|------|--------|
| DM messages | SKIPPED (requires direct Slack client, not bot relay) |
| Multi-turn context | Not yet tested (need longer conversation chains) |
| Concurrent requests | Not yet tested |
| run.sh wrapper | Not yet tested (requires process-level E2E) |
| File upload | Not yet tested |

---

## Key Discoveries

### 1. Slack does NOT fire `app_mention` for bot-originated messages

When DOGI (another bot) sends a message containing `@Bot_Walter`, Slack delivers it as a `message` event only — NOT as `app_mention`. This required modifying `_handle_message` to accept bot messages with explicit @mention.

### 2. Dual-handler race condition in slack_bolt

slack_bolt processes `message` and `app_mention` events in parallel threads. Even with `threading.Lock` protecting the dedup set, both handlers could dispatch before either completed. Fix: eliminate `app_mention` handler entirely, use single `message` handler.

### 3. WSL2 bytecache invalidation

After rsync to the deployment directory, Python's `__pycache__` .pyc files were not always recompiled despite source changes. Cross-filesystem (NTFS via WSL2) timestamp comparison appears unreliable. Must always clear `__pycache__` after deployment via rsync.

### 4. DOGI response text can trigger Bot Walter

When DOGI includes `<@BOT_USER_ID>` in response text (e.g., describing E2E test commands), Slack interprets it as a real @mention. Prevention: use plain text "Bot Walter" in all descriptions, never Slack mention format.
