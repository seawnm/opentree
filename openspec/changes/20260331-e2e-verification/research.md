# Research: OpenTree Bot Runner E2E Verification

## Research Background

OpenTree Bot Runner has 795 unit/integration tests but only 2 E2E scenarios verified in production. Before v0.2.0 release, we need a repeatable way to verify all features work through the full Slack integration path. This research evaluates approaches for E2E test execution, orchestration, and result verification.

## Candidate Approaches

### Category 1: E2E Test Execution Method

How to send test messages and trigger bot behavior in production.

| Approach | Evaluation | Rejection Reason |
|----------|-----------|-----------------|
| Manual Slack testing | Simple, no setup required. But results are not repeatable, not automatable, and depend on human judgment for pass/fail | Not automatable, human dependent |
| DOGI message-tool + log monitoring | **Adopted.** Uses existing bot infrastructure (message-tool for sending, slack-query-tool for reading). Automatable, repeatable, verifies real Slack path | -- |
| Playwright/Selenium Slack UI | Browser automation against Slack web UI. Would test the full user experience but is extremely fragile (Slack UI changes frequently), slow to execute, and complex to set up with authentication | Over-engineered for bot testing; fragile selectors, slow execution |
| Direct Socket Mode event injection | Craft synthetic Slack events and inject into the bot's Socket Mode handler. Fast and controllable but bypasses real Slack delivery, so it does not verify actual Slack API integration | Bypasses real Slack, not true E2E verification |

### Category 2: Test Orchestration

How to structure, run, and report on E2E tests.

| Approach | Evaluation | Rejection Reason |
|----------|-----------|-----------------|
| Shell script per test | One bash script per scenario. Simple to write but lacks structured assertions, poor error handling, no fixtures or parameterization, difficult to get summary reports | Poor error handling, limited assertion capability |
| Python pytest with subprocess | **Adopted.** Full assertion library, fixtures for setup/teardown, parameterization for data-driven tests, built-in reporting (JUnit XML, HTML), parallel execution via pytest-xdist if needed | -- |
| Custom test runner | Build a bespoke test framework tailored to Slack bot E2E. Maximum flexibility but significant development effort for something pytest already provides | Over-engineering; pytest already covers all needs |

### Category 3: Result Verification

How to confirm that the bot processed the message and delivered the correct response.

| Approach | Evaluation | Rejection Reason |
|----------|-----------|-----------------|
| Log file grep only | Parse bot log files for expected entries (task received, processing started, response sent). Fast and gives internal state visibility, but does not confirm the message actually appeared in Slack | Partial verification only; does not confirm Slack delivery |
| slack-query-tool read-thread | **Adopted.** Reads the actual Slack thread to verify the bot's response message exists and contains expected content. Combined with log grep for internal state, this provides full coverage of the request-response cycle | -- |
| Slack Event subscription | Set up a separate listener app subscribed to Slack events, waiting for bot messages. Would provide real-time notification but adds significant infrastructure complexity (needs its own app, server, event routing) | Over-complex; would need a separate listener application |

## Additional Considerations

### Timing and Polling

Bot Runner processes messages asynchronously. After sending a test message, the test must poll for the response. Key timing parameters:

- **Minimum wait**: 5 seconds (bot receives message, starts Claude CLI)
- **Typical response**: 10-30 seconds (Claude CLI processes and responds)
- **Maximum timeout**: 60 seconds (for complex tasks or slow network)
- **Poll interval**: 3-5 seconds (balance between responsiveness and API rate limits)

### Test Isolation

Each test should:
- Send messages in a unique thread (avoids cross-test interference)
- Include a test run identifier in the message (for log correlation)
- Clean up or ignore previous test artifacts

### Rate Limit Awareness

Slack API rate limits (Tier 2: ~20 requests/minute for reads, Tier 3: ~50/min for posts):
- Space out test message sends by at least 1 second
- Batch read-thread calls where possible
- Total test suite should stay well under rate limits with 10-15 test scenarios

## Research Conclusion

**Selected combination**:

1. **Execution**: DOGI `message-tool` sends real Slack messages to Bot_Walter's channel, triggering the full production path (Socket Mode reception, task processing, Claude CLI execution, Slack response)
2. **Orchestration**: Python `pytest` manages test lifecycle with fixtures for channel/thread setup, parameterized test cases, and JUnit XML reporting
3. **Verification**: `slack-query-tool read-thread` confirms actual Slack message delivery; bot log grep provides supplementary internal state verification

This approach maximizes confidence (real Slack messages, real bot processing) while keeping infrastructure minimal (reuses existing tools, no new services needed).
