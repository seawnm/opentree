<!-- Generated: 2026-04-06 | Python files: 42 | Lines: ~7,894 | Token estimate: ~900 -->

# OpenTree

Modular Claude Code CLI wrapper — one user, one bot, zero shared state. v0.4.0

## Subsystems

| Subsystem | Directory | Responsibility | Key Files | Lines |
|-----------|-----------|---------------|-----------|-------|
| **CLI** | `src/opentree/cli/` | `init`, `start`, `module`, `prompt` commands | init.py (599), module.py (665), main.py (26) | ~1,327 |
| **Core** | `src/opentree/core/` | Config, placeholder engine, prompt assembly, version | prompt.py (392), placeholders.py (146), config.py (54) | ~648 |
| **Generator** | `src/opentree/generator/` | Produce CLAUDE.md index, settings.json, .claude/rules/ symlinks | symlinks.py (382), settings.py (234), claude_md.py (201) | ~818 |
| **Manifest** | `src/opentree/manifest/` | Validate opentree.json against JSON Schema + semantic rules | validator.py (432), models.py (54), errors.py (48) | ~553 |
| **Registry** | `src/opentree/registry/` | Track installed modules, file locking, atomic persistence | registry.py (303), models.py (46) | ~355 |
| **Runner** | `src/opentree/runner/` | Slack bot runtime (largest subsystem) | dispatcher.py (750), bot.py (342), claude_process.py (356) | ~4,192 |
| **Schema** | `src/opentree/schema/` | JSON Schema for opentree.json manifest | opentree.schema.json | — |
| **Templates** | `src/opentree/templates/` | run.sh wrapper (auto-restart, watchdog, crash loop protection) | run.sh (303) | ~303 |

## Runner Flow (Slack Bot)

```
@mention / DM
  → Receiver (Socket Mode, layer-1 dedup)
    → Dispatcher (layer-2 dedup, priority queue, prompt assembly)
      → ClaudeProcess (subprocess, stream parsing)
        → ProgressReporter (phase tracking, Slack updates)
      ← ClaudeResult
    ← SlackAPI.post_thread_reply()

Fault tolerance: CircuitBreaker (5 failures → OPEN → 30s → HALF_OPEN)
                 RetryConfig (exponential backoff, transient vs permanent)
                 run.sh watchdog (120s heartbeat timeout → SIGTERM → 40s → SIGKILL)
```

## Runner Components

| Component | File | Role |
|-----------|------|------|
| Bot | bot.py | Lifecycle: startup → receiver.start() → shutdown |
| Receiver | receiver.py | Socket Mode listener, layer-1 dedup (10K cap) |
| Dispatcher | dispatcher.py | Message → prompt → Claude → result orchestration |
| SlackAPI | slack_api.py | Slack SDK wrapper (post, upload, react, update) |
| ClaudeProcess | claude_process.py | Spawn claude CLI subprocess, stream stdout |
| StreamParser | stream_parser.py | Parse phases: THINKING → TOOL_CALL → RESPONSE |
| Progress | progress.py | Track & report task progress to Slack |
| TaskQueue | task_queue.py | Priority heap (HIGH=admin, NORMAL=user), worker threads |
| Session | session.py | Per-user memory persistence across threads |
| CircuitBreaker | circuit_breaker.py | CLOSED → OPEN (5 fails) → HALF_OPEN (30s) |
| Retry | retry.py | Exponential backoff, transient vs permanent classification |
| FileHandler | file_handler.py | Download from / upload to Slack |
| ThreadContext | thread_context.py | Build PromptContext from Slack event |
| MemoryExtractor | memory_extractor.py | Load/update user memory files |
| ToolTracker | tool_tracker.py | Audit tool call accounting |
| Health | health.py | Disk usage monitoring (warn 90%, critical 95%) |
| Config | config.py | RunnerConfig dataclass (admin_users, timeouts) |

## Module System

10 bundled modules. Install order follows dependency chain:

```
core ─┬─ personality ── guardrail
      ├─ memory ─────── audit-logger
      ├─ scheduler
      ├─ slack ────┬─── requirement (optional)
      │            └─── stt (optional)
      └─ youtube (optional)
```

Each module = directory with:
- `opentree.json` — manifest (name, version, depends_on, conflicts_with, rules, permissions, placeholders)
- `rules/*.md` — rule files (symlinked into .claude/rules/)
- `prompt_hook.py` — optional dynamic prompt injection (exec'd at runtime)

Module operations: `opentree module install|remove|list|update|refresh`

## Design Patterns

| Pattern | Where | Detail |
|---------|-------|--------|
| **Frozen dataclass** | All subsystems | UserConfig, RegistryEntry, Task, ValidationIssue — mutation returns new instance |
| **Atomic write** | Registry, Settings | Write .tmp → fsync → os.replace (crash-safe) |
| **Symlink fallback** | Generator | symlink → junction (Windows) → copy |
| **Transactional init** | CLI init | Backup → install all → success? commit : rollback |
| **Two-layer dedup** | Runner | Receiver._processed_ts + Dispatcher._dispatched_ts |
| **File-based lock** | Registry | fcntl.flock on Linux, /tmp/opentree-registry-{hash}.lock |
| **Dynamic hook loading** | Core prompt | importlib.util.spec_from_file_location + path traversal protection |
| **Circuit breaker** | Runner | 5 consecutive failures → reject new requests → test after 30s |

## Cross-Subsystem Dependencies

```
CLI (entry point)
├── imports: Core, Generator, Manifest, Registry
└── does NOT import: Runner

Runner (Slack bot, independent)
├── imports: Core, Registry
└── does NOT import: CLI, Generator, Manifest

Core (foundation, no upstream deps)
Generator (depends on: Registry for module list)
Manifest (standalone, uses only schema/)
Registry (standalone, fcntl for locking)
```

## Known Technical Debt

- **Task dataclass not fully immutable** — relies on GIL; deferred refactor to frozen
- **SlackAPI error swallowing** — all methods catch Exception → return empty; callers can't distinguish failure from empty
- **MemoryExtractor regex false positives** — `always/never` patterns too broad
- **Module tool external deps** — manifest references CLI tools (schedule_tool etc.) not in this repo

## Tests

- **54 test files** across `tests/isolation/` (unit) and `tests/e2e/` (13 E2E tests)
- E2E requires running bot instance (Bot_Walter)
- Markers: `@pytest.mark.e2e`, `@pytest.mark.slow` (>60s), `@pytest.mark.destructive`
- Run: `pytest tests/` or `pytest tests/ --cov=opentree`

## Key Config

| Parameter | Default | Location |
|-----------|---------|----------|
| max_concurrent_tasks | 4 | runner/config.py |
| claude_timeout | 300s | runner/config.py |
| max_retries | 3 | runner/config.py |
| circuit_breaker_threshold | 5 | runner/circuit_breaker.py |
| circuit_breaker_recovery | 30s | runner/circuit_breaker.py |
| watchdog_timeout | 120s | templates/run.sh |
| crash_loop (max/window/cooldown) | 5/600s/300s | templates/run.sh |
| registry_lock_timeout | 10s | registry/registry.py |

## Entry Points

- **CLI**: `opentree` → `opentree.cli.main:app` (typer)
- **Bot**: `opentree start --mode slack` → Runner.bot.Bot
- **Python API**: `from opentree.manifest import ManifestValidator`, `from opentree.registry import Registry`

## References

- [README.md](README.md) — full architecture, quick start, module list
- [CHANGELOG.md](CHANGELOG.md) — version history (0.1.0 → 0.4.0)
- [openspec/changes/](openspec/changes/) — design decisions per feature
- [openspec/changes/20260329-initial-architecture/](openspec/changes/20260329-initial-architecture/) — foundational architecture decisions

---

*Update this file when: new subsystem added, module dependency changes, major architectural shift. See openspec/changes/20260406-agents-md-codemap/ for maintenance guidelines.*
