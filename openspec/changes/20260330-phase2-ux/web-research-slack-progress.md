# Web Research: Slack Block Kit Progress Patterns

Date: 2026-03-30
Keywords: "Slack Block Kit progress update bot best practices 2025 2026", "Slack bot progressive message update streaming response", "Slack Block Kit builder patterns Python"

---

## Source 1: Slack Official — chat.update Method

- URL: https://docs.slack.dev/reference/methods/chat.update/
- Relevance: **HIGH**

### Key Excerpts

> Use `chat.update` to continue updating ongoing state changes around a message. Provide the `ts` field the message you're updating and follow the bot user instructions above to update message text, and remove or add blocks.

> Tier 3: 50+ per minute

> If `blocks` provided without `text`: Previous blocks retained unless you send an empty array.
> If `text` provided without `blocks`: Previous blocks are removed.

> Rich-text blocks cannot be replaced with non-rich-text blocks.

> Only messages posted by the authenticated user are able to be updated.

> Ephemeral messages cannot be updated.

Error code for streaming conflict:
> `streaming_state_conflict` — Message is actively streaming content.

Text limits:
> `text`: Plain message text (max 4,000 characters)
> `markdown_text`: Markdown-formatted text (max 12,000 characters)

### Takeaways

- chat.update is Tier 3 (50+/min), but practical limit for progress updates is lower due to per-channel throttling
- Must track `message_ts` from initial post to update the same message
- Blocks and text have independent retention rules — be explicit about what you send
- Cannot update ephemeral messages or messages currently streaming
- Bot can only update its own messages

---

## Source 2: Slack Official — Modifying Messages

- URL: https://docs.slack.dev/messaging/modifying-messages/
- Relevance: **MEDIUM**

### Key Excerpts

> Any non-ephemeral message may possibly be updated by an app, by using the `chat.update` API method.

> Apps can only update ones posted by the authenticated user of the token being used.

> For interactive messages, a `response_url` is provided that allows updating the original message regardless of whether it was ephemeral.

### Takeaways

- `response_url` is an alternative for interactive message updates (useful for slash commands)
- The channel parameter in chat.update identifies the target message, not a destination — no cross-channel move

---

## Source 3: Streaming Token Responses to Slack (Let's Do DevOps Blog)

- URL: https://www.letsdodevops.com/p/building-a-slack-bot-with-ai-capabilities-d2d
- Relevance: **HIGH**

### Key Excerpts

> I initially edited the slack message for every token. It looks SO COOL to see individual words/tokens stream to slack. I also immediately hit an API limit for editing per minute.

Batching pattern (every 10 tokens):
```python
token_counter = 0
buffer = ""

for chunk in streaming_response["stream"]:
    if "contentBlockDelta" in chunk:
        text = chunk["contentBlockDelta"]["delta"]["text"]
        response += text
        buffer += text
        token_counter += 1

        if token_counter >= 10:
            client.chat_update(
                text=response,
                channel=channel_id,
                ts=message_ts
            )
            token_counter = 0
            buffer = ""
```

> If your app is widely adopted, you might have to bump this up to avoid the (globally-measured) rate limit in your slack.

Idempotent post-or-update function:
```python
def update_slack_response(say, client, message_ts,
                         channel_id, thread_ts, message_text):
    if message_ts is None:
        slack_response = say(text=message_text, thread_ts=thread_ts)
        message_ts = slack_response['ts']
    else:
        client.chat_update(text=message_text, channel=channel_id, ts=message_ts)

    return message_ts
```

Final buffer flush:
```python
if buffer:
    client.chat_update(text=response, channel=channel_id, ts=message_ts)
```

### Takeaways

- Per-token updates immediately hit rate limits — batch every 10+ tokens
- Use an idempotent function that posts on first call and updates on subsequent calls
- Always flush the remaining buffer after the stream ends
- For high-adoption apps, increase the batch size to stay within global rate limits
- The pattern works with any streaming LLM backend (Bedrock, OpenAI, Anthropic)

---

## Source 4: Slack Official — Best Practices for AI Apps

- URL: https://docs.slack.dev/ai/ai-apps-best-practices/
- Relevance: **HIGH**

### Key Excerpts

Status indicator:
> Your app should then call the `assistant.threads.setStatus` method to display the status indicator in the container. We recommend doing so immediately for the user's benefit.

Loading message rotation:
```json
"loading_messages": [
    "Teaching the hamsters to type faster...",
    "Untangling the internet cables...",
    "Consulting the office goldfish..."
]
```

Task display:
> Use `task_display_mode: "plan"` for grouped tasks. Tasks can show states: `pending`, `in_progress`, `completed`, `error`. Update individual tasks without recreating the entire plan.

Streaming API trio:
> `chat.startStream` initiates streaming.
> `chat.appendStream` adds progressive content.
> `chat.stopStream` finalizes with blocks.

Critical constraint:
> Blocks may be used in the `chat.stopStream` method, but not the `chat.startStream` or `chat.appendStream` method.

Rate limit for chat.update:
> Only call the `chat.update` method once every 3 seconds with new content, otherwise your calls may hit the rate limit.

Error handling:
> Graceful failure means the agent treats its own partial progress as something worth preserving. Save what it's accomplished. Explain where it got stuck and why. Give the user a clear set of options, including: provide the missing information, skip the blocked step, or take over manually.

Status clearing:
> Clear the status so the app is not stuck 'thinking' indefinitely by calling `setStatus` with an empty string.

Suggested prompts:
> Present users with up to 4 optional, preset prompts to choose from during thread initialization.

Citations:
> There should be a concise way to reference internal messages and files from external sources with inline links and reference blocks at message end.

### Takeaways

- Slack has a first-party streaming API (chat.startStream / appendStream / stopStream) since October 2025
- For non-streaming progress, use assistant.threads.setStatus with rotating messages
- **chat.update should be called at most once every 3 seconds** (official recommendation)
- Task updates support 4 states: pending, in_progress, completed, error
- Blocks can ONLY be attached at stream stop, not during streaming
- Graceful failure: preserve partial progress, explain what went wrong, offer options
- Clear status after completion to avoid stuck "thinking" state

---

## Source 5: Slack Official — assistant.threads.setStatus

- URL: https://docs.slack.dev/reference/methods/assistant.threads.setStatus/
- Relevance: **HIGH**

### Key Excerpts

> A two minute timeout applies, which will cause the status to be removed if no message has been sent.

> The list of messages to rotate through as a loading indicator. Maximum of 10 messages.

> The default limit is 600 requests per minute (per app per team).

Status display format:
> The status renders as `<App Name> <status>`, with Slack automatically inserting the app name.

Auto-clear behavior:
> The status will be automatically cleared when the app sends a reply. Sending an empty string in the `status` field will also clear the status indicator.

Scope:
> Currently accepts either `assistant:write` or `chat:write`, though soon this method will only accept the `chat:write` scope.

### Takeaways

- Status has a 2-minute timeout — must be refreshed or a message must be sent within 2 minutes
- Up to 10 rotating loading messages supported
- 600 req/min rate limit is very generous for status updates
- Status auto-clears when bot sends a reply — no manual cleanup needed in normal flow
- Plan migration: use `chat:write` scope going forward

---

## Source 6: Slack Official — Rate Limits

- URL: https://docs.slack.dev/apis/web-api/rate-limits/
- Relevance: **HIGH**

### Key Excerpts

Rate limit tiers:

| Tier | Limit |
|------|-------|
| Tier 1 | 1+ per minute |
| Tier 2 | 20+ per minute |
| Tier 3 | 50+ per minute |
| Tier 4 | 100+ per minute |
| Special | Varies |

> `chat.postMessage` falls under the "Special Tier" category: generally allows posting one message per second per channel, while also maintaining a workspace-wide limit.

> A burst limit defines the maximum rate of requests allowed concurrently.

> Design with a limit of 1 request per second for any given API call, knowing that we'll allow it to go over this limit as long as this is only a temporary burst.

> When exceeded, Slack returns a `HTTP 429 Too Many Requests` error, and a `Retry-After` HTTP header containing the number of seconds until you can retry.

### Takeaways

- chat.update is Tier 3 (50+/min), but practical safe rate is 1 update per 3 seconds per the AI best practices doc
- chat.postMessage is Special tier (1/sec/channel + workspace-wide limit)
- chat.appendStream is Tier 4 (100+/min) — most generous for frequent appends
- chat.startStream and chat.stopStream are Tier 2 (20+/min)
- Always implement Retry-After header handling for 429 responses
- Design for 1 req/sec sustained, with burst tolerance

---

## Source 7: Slack Official — Chat Streaming Feature Announcement (October 2025)

- URL: https://docs.slack.dev/changelog/2025/10/7/chat-streaming/
- Relevance: **HIGH**

### Key Excerpts

> A new suite of features to help Slack apps provide an end-user experience typical of LLM tools.

Three new Block Kit elements:
> 1. `feedback_buttons` — enables users to rate responses as positive/negative
> 2. `icon_button` — triggers quick actions like response deletion
> 3. `context_actions` block — containers for these interactive elements

Python SDK streaming pattern:
```python
streamer = client.chat_stream(channel=channel_id, ...)
for event in returned_message:
    streamer.append(markdown_text=f"{chunk}")
streamer.stop(blocks=feedback_block)
```

> Template repositories for both Bolt for Python and Bolt for JavaScript were updated to demonstrate these streaming capabilities.

### Takeaways

- Streaming API is the official solution for LLM-style progressive responses (released Oct 2025)
- New Block Kit elements (feedback_buttons, icon_button, context_actions) designed for AI UX
- Python SDK has a high-level `chat_stream()` helper with automatic buffering
- Template repos available as reference implementations

---

## Source 8: Slack Python SDK — ChatStream Helper

- URL: https://docs.slack.dev/tools/python-slack-sdk/reference/web/chat_stream.html
- Relevance: **HIGH**

### Key Excerpts

> This class provides a convenient interface for the chat.startStream, chat.appendStream, and chat.stopStream API methods, with automatic buffering and state management.

Constructor parameters:
> `buffer_size`: Integer controlling markdown buffering threshold.
> `task_display_mode`: Optional string ("timeline" or "plan") for task display.

Usage:
```python
streamer = client.chat_stream(
    channel="C0123456789",
    thread_ts="1700000001.123456",
    recipient_team_id="T0123456789",
    recipient_user_id="U0123456789",
)
streamer.append(markdown_text="**hello wo")
streamer.append(markdown_text="rld!**")
streamer.stop()
```

State management:
> The class tracks stream state as "starting" -> "in_progress" -> "completed", preventing operations on completed streams.

append() behavior:
> Returns `SlackResponse` if buffer flushes; `None` if buffering continues. Raises `SlackRequestError` if stream already completed.

stop() supports blocks:
> `blocks`: Block objects for message footer.

### Takeaways

- Built-in buffer management — SDK handles batching automatically via `buffer_size` parameter
- State machine prevents invalid operations (e.g., appending to a completed stream)
- `append()` returns None when buffering, SlackResponse when flushed — can track actual API calls
- Blocks only attachable at `stop()` — consistent with API constraint
- `task_display_mode` supports "timeline" (default) and "plan" for task visualization
- Requires `recipient_user_id` and `recipient_team_id` for channel streaming

---

## Source 9: Slack Official — Designing with Block Kit

- URL: https://docs.slack.dev/block-kit/designing-with-block-kit/
- Relevance: **MEDIUM**

### Key Excerpts

> Use short, clear sentences and paragraphs.

> Don't use directional and sensory language, including emojis (as sole communication).

> Save people work wherever you can by minimizing the choices they have to make. Pre-select sensible defaults.

> Update messages post-interaction to condense rich content down to brief text records, reducing screen clutter.

Emoji accessibility:
> Do not use an emoji as a control. Place emojis at line/sentence endings. Always pair emojis with text. Avoid using emojis as bullet points.

### Takeaways

- After a progress update completes, condense the rich progress view into a brief summary
- Emoji for status indicators must be paired with text (accessibility)
- Keep progress messages concise — short sentences, no jargon
- Pre-select defaults in any interactive elements

---

## Source 10: Slack Official — Block Kit Overview

- URL: https://docs.slack.dev/block-kit/
- Relevance: **MEDIUM**

### Key Excerpts

> You can include up to 50 blocks in each message, and 100 blocks in modals or Home tabs.

Three foundational elements:
> 1. Blocks — Visual components arranged to create layouts
> 2. Block Elements — Interactive components like buttons and menus
> 3. Composition Objects — Define text, options, and interactive features

> To make an accessible app, you must either: include all necessary content for screen reader users in the top-level `text` field of your message, or do not include a top-level `text` field if the message has `blocks`.

### Takeaways

- 50 blocks per message limit — progress displays with many steps need to stay within this
- Always include a top-level `text` fallback for accessibility/notifications
- Blocks, elements, and composition objects are the three layers of abstraction

---

## Source 11: blockkit Python Library (imryche/blockkit)

- URL: https://github.com/imryche/blockkit
- Relevance: **MEDIUM**

### Key Excerpts

Fluent builder pattern:
```python
from blockkit import Message, Section, Button, Confirm

message = (
    Message()
    .add_block(
        Section("Please approve *Alice's* expense report for $42")
        .accessory(
            Button("Approve")
            .action_id("approve_button")
            .style(Button.PRIMARY)
            .confirm(
                Confirm()
                .title("Are you sure?")
                .text("This action cannot be undone")
                .confirm("Yes, approve")
                .deny("Cancel")
            )
        )
    )
    .thread_ts(1234567890)
    .build()
)
```

> Type hints, validation, and zero dependencies.
> Automatic markdown detection.
> Class constants to prevent typos (e.g., `Button.PRIMARY`).

### Takeaways

- Fluent builder API for composing Block Kit messages in Python
- Pre-send validation catches errors before API calls
- Zero dependencies — easy to adopt
- Good for building dynamic progress blocks programmatically

---

## Source 12: slack-progress (bcicen/slack-progress)

- URL: https://github.com/bcicen/slack-progress
- Relevance: **MEDIUM**

### Key Excerpts

```python
from slack_progress import SlackProgress
sp = SlackProgress('SLACK_TOKEN', 'CHANNEL_NAME')

# Iterator wrapping
for i in sp.iter(range(500)):
    time.sleep(.2)

# Manual position control
pbar = sp.new()
pbar.pos = 10
pbar.pos = 100

# Logging during progress
pbar.pos = 50
pbar.log("Step 1 complete")
pbar.pos = 100
pbar.log("Step 2 complete")
```

### Takeaways

- Dedicated library for visual progress bars in Slack using emoji
- Supports iterator wrapping and manual position control
- Log messages can be interleaved with progress updates
- Uses chat.update under the hood — subject to same rate limits

---

## Source 13: Slack chat.appendStream — Chunk Types Detail

- URL: https://docs.slack.dev/reference/methods/chat.appendStream/
- Relevance: **HIGH**

### Key Excerpts

Task Update Chunk:
```json
{
  "type": "task_update",
  "id": "unique_task_id",
  "title": "Remind Sandra how amazing she is",
  "status": "pending|in_progress|complete|error",
  "details": "wow such good details",
  "output": "amazing output here",
  "sources": [
    {
      "type": "url",
      "text": "Example.com",
      "url": "https://example.com"
    }
  ]
}
```

Plan Update Chunk:
```json
{
  "type": "plan_update",
  "title": "Sandra's new and improved plan"
}
```

> Rate Limit: Tier 4: 100+ per minute

### Takeaways

- Task updates have rich structure: id, title, status, details, output, sources
- Plan updates group tasks visually under a titled plan
- Tier 4 rate limit (100+/min) allows frequent incremental updates
- Sources can be attached to individual tasks — good for citations

---

## Source 14: MagicBell — Slack Block Kit Builder Guide

- URL: https://www.magicbell.com/blog/slack-blocks
- Relevance: **LOW**

### Key Excerpts

> Essential content in the top-level text for screen reader users.

Approval workflow pattern:
```json
{
  "type": "section",
  "text": {
    "type": "mrkdwn",
    "text": "Would you like to approve this request?"
  },
  "accessory": {
    "type": "button",
    "text": {"type": "plain_text", "text": "Approve"},
    "value": "approve_request",
    "action_id": "approve_button"
  }
}
```

### Takeaways

- Use Block Kit Builder (visual tool) for prototyping before coding
- Combine multiple block types for structured information display
- Action handlers must respond within 3 seconds (for interactive elements)

---

## Summary

### Two Primary Approaches for Progress Reporting (2025-2026)

**Approach 1: Streaming API (Recommended for LLM/AI responses)**

Slack released first-party streaming support in October 2025 via `chat.startStream` / `chat.appendStream` / `chat.stopStream`. This is the official solution for progressive text responses from AI agents.

- **Rate limit**: appendStream is Tier 4 (100+/min), start/stop are Tier 2 (20+/min)
- **Buffering**: Python SDK `ChatStream` helper handles automatic buffering via `buffer_size`
- **Constraint**: Blocks can only be attached at `stop()`, not during streaming
- **Task updates**: Built-in chunk types for task_update (with status: pending/in_progress/complete/error) and plan_update
- **Feedback**: New Block Kit elements (feedback_buttons, icon_button, context_actions) for post-response interaction

**Approach 2: chat.update Polling (Fallback / Non-AI bots)**

The traditional approach of posting a message then updating it via `chat.update`.

- **Rate limit**: Tier 3 (50+/min), but **official recommendation is max 1 update per 3 seconds**
- **Batching**: When streaming LLM tokens, batch every 10+ tokens before calling chat.update
- **Pattern**: Post initial message -> store `message_ts` -> update with new blocks/text
- **Condensation**: After completion, replace rich progress view with brief summary

### Key Design Patterns

1. **Idempotent post-or-update**: Single function that posts on first call, updates on subsequent calls
2. **Buffer + flush**: Accumulate content, flush at threshold, always flush remaining at end
3. **Status indicator**: Use `assistant.threads.setStatus` with rotating messages (up to 10, 2-min timeout)
4. **Task state machine**: Track tasks as pending -> in_progress -> complete/error
5. **Graceful failure**: Preserve partial progress, explain failure, offer options to user
6. **Post-completion condensation**: Replace detailed progress blocks with brief text summary

### Rate Limit Summary

| Method | Tier | Practical Limit |
|--------|------|-----------------|
| chat.postMessage | Special | 1/sec/channel |
| chat.update | Tier 3 | 1 per 3 seconds (recommended) |
| chat.appendStream | Tier 4 | 100+/min |
| chat.startStream | Tier 2 | 20+/min |
| chat.stopStream | Tier 2 | 20+/min |
| assistant.threads.setStatus | Special | 600/min |

### Python Library Options

| Library | Pattern | Dependencies | Notes |
|---------|---------|--------------|-------|
| python-slack-sdk (official) | Dict-based blocks + ChatStream helper | slack_sdk | First-party, streaming support |
| blockkit (imryche) | Fluent builder | None | Validation, type hints |
| slackblocks (nicklambourne) | Builder | None (stdlib only) | Lightweight |
| slack-progress (bcicen) | Progress bar | slack_sdk | Emoji-based progress bars |

### Accessibility Requirements

- Always include top-level `text` field for screen readers and notifications
- Pair emojis with text — never use emoji as sole indicator
- Provide alt_text for images
- Test in both light and dark modes for color contrast
