# Proposal: OpenTree Bot Runner E2E Verification

## Background

OpenTree Bot Runner is deployed at `/mnt/e/develop/mydev/project/trees/bot_walter/` and running in Slack as Bot_Walter (Bot User ID: `U0APZ9MR997`). The project targets a v0.2.0 release and requires comprehensive production verification before shipping.

## Original Request

> "A, use ecc feature workspace skill by muti-agent (please add E2E test)"

## Problem

Bot Runner currently has **795 unit/integration tests** providing solid internal coverage, but only **2 E2E scenarios** have been verified in production:

1. @mention triggers reply
2. Thread resume works

The following critical features remain **untested in production**:

| Feature | Unit/Integration Coverage | E2E Coverage |
|---------|--------------------------|--------------|
| @mention reply | Yes | Verified |
| Thread resume | Yes | Verified |
| Admin commands (shutdown, status) | Yes | **Not verified** |
| Direct Message (DM) | Yes | **Not verified** |
| File upload handling | Yes | **Not verified** |
| Concurrency (parallel tasks) | Yes | **Not verified** |
| Wrapper (restart, watchdog) | Yes | **Not verified** |
| Multi-turn conversation | Yes | **Not verified** |
| Error handling (timeout, crash) | Yes | **Not verified** |

Without E2E verification, we cannot confirm that these features work correctly through the full Slack integration path (message reception, Claude CLI execution, response delivery).

## Solution

Build an automated E2E test suite that:

1. **Sends real Slack messages** via DOGI's `message-tool` to Bot_Walter's channel
2. **Monitors bot logs** for internal processing confirmation
3. **Reads Slack threads** via `slack-query-tool` to verify response delivery
4. **Orchestrates with pytest** for assertions, fixtures, parallel execution, and reporting

### Test Architecture

```
pytest (orchestrator)
  |
  +-- message-tool send --> Slack --> Bot_Walter (Socket Mode)
  |                                      |
  |                                      v
  |                               Claude CLI execution
  |                                      |
  +-- slack-query-tool read-thread <-----+  (verify response)
  +-- bot log grep <---------------------+  (verify internal state)
```

## Change Scope

| Area | Changes |
|------|---------|
| `tests/e2e/` | New test files for each feature category |
| `tests/e2e/conftest.py` | Shared fixtures (channel ID, bot user ID, timeouts) |
| `tests/e2e/utils/` | Helper functions for message sending, log monitoring, thread reading |
| `openspec/changes/20260331-e2e-verification/` | This proposal and research docs |

**No changes to production code.** This is purely additive test infrastructure.

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Bot_Walter heartbeat is stale (bot may be down) | High | Check heartbeat and restart bot before running E2E suite |
| Slack API rate limits during rapid testing | Medium | Add delays between test messages; use Tier 1 rate limit awareness (1 msg/sec) |
| Claude CLI usage consumes API quota | Medium | Keep test prompts minimal; use simple trigger phrases that produce short responses |
| Test flakiness from network latency | Medium | Use generous timeouts (30-60s) with polling; retry on transient failures |
| Bot_Walter channel conflicts with other users | Low | Use dedicated test thread per test run; prefix messages with test run ID |

## Success Criteria

- All P0 features verified working in production Slack
- Test suite is repeatable (can run again for regression)
- Clear pass/fail reporting per feature
- Test run completes within 15 minutes
