# Research: Phase 4 Advanced Features

## Background
Bot Runner needs production-grade resilience patterns. Evaluated approaches for each feature.

## Candidates

### Retry Mechanism
| Option | Evaluation | Rejection reason |
|--------|-----------|-----------------|
| tenacity library | Full-featured retry decorator | Over-engineered for 2 error types |
| Custom retry module | Adopted | Minimal, immutable config, pure functions |
| No retry (fail fast) | Simple | Poor UX for transient errors |

### Circuit Breaker
| Option | Evaluation | Rejection reason |
|--------|-----------|-----------------|
| pybreaker library | Industry standard | Dependency for ~50 lines of code |
| Custom implementation | Adopted | Thread-safe, no deps, Slack integration |
| Health check endpoint | Different pattern | Doesn't prevent cascading failures |

### Tool Tracking
| Option | Evaluation | Rejection reason |
|--------|-----------|-----------------|
| OpenTelemetry spans | Standard observability | Massive dependency for simple tracking |
| Custom ToolTracker | Adopted | Lightweight, integrates with Block Kit |
| Log-only tracking | Minimal | No user-facing timeline |

### Memory Extraction
| Option | Evaluation | Rejection reason |
|--------|-----------|-----------------|
| Second Claude API call | Most accurate | Expensive (doubles API cost per task) |
| Heuristic pattern matching | Adopted | Zero cost, catches explicit "remember" requests |
| No extraction | Simplest | No cross-session memory |

## Conclusion
All four features use custom, minimal implementations with zero external dependencies. The patterns are intentionally simple — complexity can be added when usage data justifies it.
