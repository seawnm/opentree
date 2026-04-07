<!-- Generated: 2026-04-07 | Python files: 44 | Lines: ~8,600 | Token estimate: ~1,000 -->

# OpenTree

Modular Claude Code CLI wrapper — one user, one bot, zero shared state. v0.5.0

## Subsystems

| Subsystem | Directory | Responsibility | Key Files | Lines |
|-----------|-----------|---------------|-----------|-------|
| **CLI** | `src/opentree/cli/` | `init`, `start`, `module`, `prompt` commands | init.py (705), module.py (665), main.py (26) | ~1,449 |
| **Core** | `src/opentree/core/` | Config, placeholder engine, prompt assembly, version | prompt.py (392), placeholders.py (146), config.py (54) | ~648 |
| **Generator** | `src/opentree/generator/` | Produce CLAUDE.md index, settings.json, .claude/rules/ symlinks | symlinks.py (382), settings.py (234), claude_md.py (276) | ~893 |
| **Manifest** | `src/opentree/manifest/` | Validate opentree.json against JSON Schema + semantic rules | validator.py (432), models.py (54), errors.py (48) | ~553 |
| **Registry** | `src/opentree/registry/` | Track installed modules, file locking, atomic persistence | registry.py (303), models.py (46) | ~355 |
| **Runner** | `src/opentree/runner/` | Slack bot runtime (largest subsystem) | dispatcher.py (842), bot.py (380), claude_process.py (356), reset.py (210), memory_schema.py (186) | ~4,867 |
| **Schema** | `src/opentree/schema/` | JSON Schema for opentree.json manifest | opentree.schema.json | — |
| **Templates** | `src/opentree/templates/` | run.sh wrapper (auto-restart, watchdog, crash loop protection) | run.sh (303) | ~303 |

## Runner Flow (Slack Bot)

```
@mention / DM
  → Receiver (Socket Mode, layer-1 dedup)
    → Dispatcher (layer-2 dedup, priority queue, prompt assembly)
      ├─ Bot command? (status, help, shutdown, restart, reset-bot, reset-bot-all)
      │   → Owner-only auth check (is_owner via RunnerConfig.admin_users)
      │   → reset-bot → reset.reset_bot() + SessionManager.clear_all() → restart
      │   → reset-bot-all → reset.reset_bot_all() → restart
      └─ Normal task:
          → ClaudeProcess (subprocess, stream parsing)
            → ProgressReporter (phase tracking, Slack updates)
          ← ClaudeResult
          → MemoryExtractor (section routing → Pinned/Core/Episodes/Active)
        ← SlackAPI.post_thread_reply()

Fault tolerance: CircuitBreaker (5 failures → OPEN → 30s → HALF_OPEN)
                 RetryConfig (exponential backoff, transient vs permanent)
                 run.sh watchdog (120s heartbeat timeout → SIGTERM → 40s → SIGKILL)
```

## Runner Components

| Component | File | Role |
|-----------|------|------|
| Bot | bot.py | Lifecycle: startup → receiver.start() → shutdown. Three-layer .env loading (_parse_env_file, _validate_not_placeholder): .env.defaults → .env.local → .env.secrets, with legacy .env fallback |
| Receiver | receiver.py | Socket Mode listener, layer-1 dedup (10K cap) |
| Dispatcher | dispatcher.py | Message → prompt → Claude → result orchestration. Handles reset-bot/reset-bot-all commands. Owner check via is_owner (RunnerConfig.admin_users). Step 11b: memory extraction gated by memory_extraction_enabled |
| SlackAPI | slack_api.py | Slack SDK wrapper (post, upload, react, update) |
| ClaudeProcess | claude_process.py | Spawn claude CLI subprocess, stream stdout |
| StreamParser | stream_parser.py | Parse phases: THINKING → TOOL_CALL → RESPONSE |
| Progress | progress.py | Track & report task progress to Slack |
| TaskQueue | task_queue.py | Priority heap (HIGH=owner, NORMAL=user), worker threads |
| Session | session.py | Per-user memory persistence across threads |
| CircuitBreaker | circuit_breaker.py | CLOSED → OPEN (5 fails) → HALF_OPEN (30s) |
| Retry | retry.py | Exponential backoff, transient vs permanent classification |
| FileHandler | file_handler.py | Download from / upload to Slack |
| ThreadContext | thread_context.py | Build PromptContext from Slack event |
| Reset | reset.py | reset_bot() soft reset (regenerate settings/symlinks/CLAUDE.md, preserve owner content) and reset_bot_all() hard reset (clear .env.local, .env.secrets, data/, full regeneration). Best-effort error handling: each step wrapped in try/except, returns action list |
| MemorySchema | memory_schema.py | MemorySchema class: parse/serialize four-section memory.md (Pinned, Core, Episodes, Active). Provides add_item (dedup via NFKC normalization), remove_item, ensure_file. Atomic writes via tempfile + os.replace. Old-format migration support |
| MemoryExtractor | memory_extractor.py | Extract memories from conversation text via regex patterns. Section routing: "remember/記住" → Pinned, preference/decision → Core, general → Active. Per-user locking (_get_user_lock). Old-format auto-migration on first write |
| ToolTracker | tool_tracker.py | Audit tool call accounting |
| Health | health.py | Disk usage monitoring (warn 90%, critical 95%) |
| Config | config.py | RunnerConfig dataclass (admin_users, timeouts, memory_extraction_enabled) |

## Notable CLI & Generator Functions

| Function | File | Detail |
|----------|------|--------|
| `_resolve_opentree_cmd()` | cli/init.py | Determines how run.sh invokes opentree. `--cmd-mode` flag: `auto` (default: pyproject.toml present → `uv run --directory`, else shutil.which("opentree") → bare), `bare`, `uv-run`. Returns `(command_string, project_root_or_None)` |
| `wrap_with_markers()` | generator/claude_md.py | Wrap generated content with `<!-- OPENTREE:AUTO:BEGIN/END -->` markers + owner hint block |
| `generate_with_preservation()` | generator/claude_md.py | Regenerate CLAUDE.md auto block while preserving owner-written content outside markers. Legacy migration: missing markers → entire old file treated as owner content |

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
| **Marker preservation** | Generator | CLAUDE.md auto block wrapped in `<!-- OPENTREE:AUTO:BEGIN/END -->` markers; owner content outside markers survives regeneration |
| **Layered .env** | Runner bot.py | Three-layer merge: .env.defaults → .env.local → .env.secrets (highest wins). Placeholder rejection via _validate_not_placeholder |
| **Per-user locking** | Runner memory_extractor | threading.Lock per user key; prevents concurrent memory writes from corrupting same file |
| **Best-effort steps** | Runner reset.py | Each reset step in its own try/except; failures logged and reported but don't abort remaining steps |

## Cross-Subsystem Dependencies

```
CLI (entry point)
├── imports: Core, Generator, Manifest, Registry
└── does NOT import: Runner

Runner (Slack bot, independent)
├── imports: Core, Registry, Generator (reset.py uses ClaudeMdGenerator, SettingsGenerator, SymlinkManager)
└── does NOT import: CLI, Manifest

Core (foundation, no upstream deps)
Generator (depends on: Registry for module list)
Manifest (standalone, uses only schema/)
Registry (standalone, fcntl for locking)
```

## Known Technical Debt

- **Task dataclass not fully immutable** — relies on GIL; deferred refactor to frozen
- **SlackAPI error swallowing** — all methods catch Exception → return empty; callers can't distinguish failure from empty
- **MemoryExtractor regex false positives** — `always/never` patterns too broad; LLM-based extraction deferred (still pure regex)
- **Module tool external deps** — manifest references CLI tools (schedule_tool etc.) not in this repo
- **Owner key → Claude CLI passthrough** — deferred; owner identity not yet forwarded to Claude CLI subprocess environment
- **Active section 30-day aging** — not implemented; Active items accumulate without automatic expiration or promotion

## Tests

- **~1,250 tests** across `tests/isolation/` (unit) and `tests/e2e/` (13 E2E tests), **89% coverage**
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
| memory_extraction_enabled | true | runner/config.py |

## Entry Points

- **CLI**: `opentree` → `opentree.cli.main:app` (typer)
- **Bot**: `opentree start --mode slack` → Runner.bot.Bot
- **Python API**: `from opentree.manifest import ManifestValidator`, `from opentree.registry import Registry`

## References

- [README.md](README.md) — full architecture, quick start, module list
- [CHANGELOG.md](CHANGELOG.md) — version history (0.1.0 → 0.5.0)
- [openspec/changes/](openspec/changes/) — design decisions per feature
- [openspec/changes/20260329-initial-architecture/](openspec/changes/20260329-initial-architecture/) — foundational architecture decisions

---

*Update this file when: new subsystem added, module dependency changes, major architectural shift. See openspec/changes/20260406-agents-md-codemap/ for maintenance guidelines.*
