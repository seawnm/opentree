# Proposal: Phase 4 Advanced Features

## Requirements (verbatim)
"Phase 4 進階功能 (Tool Tracker/Retry/Circuit Breaker/Memory Extractor)"
"3>2, 1放代辦" — P2 Simulation issues first, then Phase 4, Bot Walter deployment to backlog.

## Problem
Bot Runner v0.2.0 lacks resilience and observability features needed for production 24/7 operation:
1. Transient Claude CLI errors (overloaded, session corruption) cause immediate task failure
2. Cascading failures from unhealthy Claude service flood the bot with error responses
3. No visibility into which tools Claude used during a task
4. No automatic memory persistence across conversations

## Solution
Four features implemented in the runner layer:

| Feature | File | Purpose |
|---------|------|---------|
| Retry | `retry.py` | Exponential backoff for overloaded errors, session clear for session errors |
| Circuit Breaker | `circuit_breaker.py` | State machine (CLOSED/OPEN/HALF_OPEN) protecting against cascading failures |
| Tool Tracker | `tool_tracker.py` | Records tool usage + duration, displays timeline in completion message |
| Memory Extractor | `memory_extractor.py` | Heuristic extraction of memorable content from conversations |

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `runner/retry.py` | New | RetryConfig + classify_error + calculate_delay + should_retry |
| `runner/circuit_breaker.py` | New | CircuitState + CircuitBreakerConfig + CircuitBreaker |
| `runner/tool_tracker.py` | New | ToolUse + ToolTracker + build_timeline |
| `runner/memory_extractor.py` | New | MemoryEntry + extract_memories + append_to_memory_file |
| `runner/dispatcher.py` | Modified | Retry loop, circuit breaker check, tool tracking, memory extraction |
| `runner/progress.py` | Modified | Tool timeline in completion blocks |

## Risk
- Retry delays (30-120s) may cause user-perceived latency
- Circuit breaker false trips on burst errors
- Memory extractor heuristics may miss or over-extract
- Tool tracker adds minimal overhead per tool_use event
