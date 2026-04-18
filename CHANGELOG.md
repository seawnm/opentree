# Changelog

格式基於 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
- **`danger-full-access` sandbox mode** — 接線 `RunnerConfig.codex_sandbox` 欄位（原已定義但從未消費）。設定 `codex_sandbox: "danger-full-access"` 後：bot 啟動跳過 bwrap 檢查；Codex CLI 以 `--dangerously-bypass-approvals-and-sandbox` 直接在宿主機執行，可存取所有路徑。guardrail deny 規則（`settings.json`）仍有效。預設 `"workspace-write"` 行為完全不變。三個接線點：`dispatcher.py`（×2）+ `bot.py`（×1）。設計決策：[openspec/changes/20260418-danger-full-access/](openspec/changes/20260418-danger-full-access/)
- **`.env.local.example` 獨立模板檔** — 新增 `src/opentree/templates/.env.local.example`（4 節中英雙語註解）。`opentree init` 從模板檔讀取，fallback 至最小 inline stub。與 `run.sh.template` 一致的設計模式，易於維護與擴充。設計決策：[openspec/changes/20260418-danger-full-access/](openspec/changes/20260418-danger-full-access/)
- **Codex CLI runtime** — `codex_process.py` replaces `claude_process.py` as the subprocess backend. `CodexProcess.run()` returns the same `ClaudeResult` dataclass, keeping the dispatcher interface identical. `codex_stream_parser.py` parses Codex `--json` JSONL events (`thread.started`, `item.started/completed`, `turn.completed`). Design: [openspec/changes/20260416-codex-migration/](openspec/changes/20260416-codex-migration/)
- **AGENTS.md generator** — `generate_agents_md()` in `generator/claude_md.py` produces `workspace/AGENTS.md` (Codex system prompt carrier) using plain `# OPENTREE:AUTO:BEGIN/END` markers (not HTML comments). Owner content outside the markers is preserved across refresh. `_write_codex_config_trust()` in `cli/init.py` idempotently adds the workspace to `~/.codex/config.toml` as a trusted project.
- **`opentree stop` CLI 指令** — 安全停止 wrapper + bot（SIGTERM → 等待 → SIGKILL），支援 `--force` 和 `--timeout`。防 PID reuse 誤殺（/proc/cmdline 驗證）。設計決策：[openspec/changes/20260408-reinstall-improvements/](openspec/changes/20260408-reinstall-improvements/)
- **docs/DEPLOYMENT.md：WSL2 watchdog 說明** — 新增 WSL2 sleep/suspend 導致 watchdog 誤殺的行為說明與 `WATCHDOG_TIMEOUT` 調整建議（2026-04-13 bot_walter 生產部署中觀察到）
- **docs/DEPLOYMENT.md：Process manager 說明** — 明確說明 PM2 對 opentree 是冗餘的（run.sh 已有完整 daemon 機制），並提供清理 PM2 的指令。建議使用 nohup 直接啟動
- **`pip install .` 完全解耦** — wheel 包含 `bundled_modules/`（10 個模組），`opentree init` + `start` 可在無 source 環境運行。`_bundled_modules_dir()` 雙路徑 fallback（installed → dev layout）。設計決策：[openspec/changes/20260408-full-decouple/](openspec/changes/20260408-full-decouple/)
- **Slack 依賴提示** — bare/installed mode 下 `opentree init` 偵測缺少 slack_bolt 時提示 `pip install 'opentree[slack]'`
- **run.sh wrapper.pid + stop flag** — wrapper 寫入 `data/wrapper.pid` 供 `opentree stop` 定位；restart 迴圈前檢查 `.stop_requested` flag 防止重啟

### Changed
- bot_walter deployment: switched from `uv run --directory` (source-coupled) to dedicated `.venv` with non-editable install for full instance isolation
- `workspace/.codex` is now bound directly to `HOME/.codex` (`/home/codex/.codex`) inside bwrap. Codex uses `HOME/.codex` for **both** session state (`state_5.sqlite`, `sessions/`, rollout files) and auth (`auth.json`). Binding here ensures state persists across bwrap invocations so `codex exec resume` finds rollouts from previous turns. `auth.json` is overlaid RO on top via `--ro-bind-try` so the host credential is not writable inside the sandbox
- `CodexProcess.run()` now pre-creates `{workspace}/.codex/` on host before launching bwrap to avoid "Can't mkdir: Read-only file system" for non-owner workspaces
- **Dispatcher uses Codex CLI** — `dispatcher.py` now imports `CodexProcess` instead of `ClaudeProcess`. `sandboxed=True, is_owner=...` flags are forwarded from task context. `config.py` renames the primary field to `codex_command: str = "codex"`; the `claude_command` property returns `codex_command` as a deprecated alias for backward-compatible JSON configs. Design: [openspec/changes/20260416-codex-migration/](openspec/changes/20260416-codex-migration/)
- **Instance 解耦** — run.sh 支援 `OPENTREE_CMD` 環境變數覆蓋 baked-in 命令，實現 instance 與 source project 完全解耦。`opentree init --cmd-mode bare` 可直接生成 bare `opentree` 命令。設計決策：[openspec/changes/20260407-decouple-instance/](openspec/changes/20260407-decouple-instance/)
- **E2E 測試解耦** — `DOGI_DIR` 改為環境變數 `OPENTREE_E2E_DOGI_DIR`（未設定時 skip），移除對 slack-bot 的硬編碼路徑依賴
- **Module rules 路徑** — 臨時檔案路徑從 `/tmp/slack-bot/` 統一為 `/tmp/opentree/`
- **`_resolve_opentree_cmd("auto")`** — 安裝後優先偵測 `bundled_modules/` 存在，跳過 pyproject.toml probe，避免撞到不相關的 project root

### Fixed
- Fix `codex exec resume` CLI interface change: `--session-id` flag removed, SESSION_ID is now positional argument — second-turn conversations were returning "(no response)"
- Fix Codex CLI entering interactive mode inside bwrap sandbox: add `--new-session` flag to `bwrap` args (calls `setsid(2)`) to detach from controlling TTY, preventing Codex from detecting a terminal and waiting for interactive stdin. Also add `stdin=subprocess.DEVNULL` to `Popen` call as defence-in-depth
- Fix bwrap sandbox auth + multi-turn session resume: `workspace/.codex` is now bound to `HOME/.codex` (not `/workspace/.codex`). Codex uses `HOME/.codex` for both auth (`auth.json`) and session state (`state_5.sqlite`, rollout files). Previous design bound `workspace/.codex → /workspace/.codex` which Codex never reads; result was 401 Unauthorized for every request and `thread/resume failed: no rollout found` on every second-turn conversation
- Remove Bash `mkdir` dependency in memory-sop.md; Write tool handles directory creation natively
- Add conditional phrasing to capability declarations in personality rules to prevent over-promising
- Add graceful degradation guidance for tool unavailability scenarios
- **LLM Owner 識別修復** — `character.md` 新增 4 條識別規則，防止 LLM 將一般使用者誤識為 Owner、以及幻覺 Owner user_id。根因：`character.md` 缺乏「唯一判斷依據是系統提示的『權限等級』欄位」的明確指引。設計決策：[openspec/changes/20260418-owner-identification-fix/](openspec/changes/20260418-owner-identification-fix/)
- **AGENTS.md sync fix** — `module refresh/install/update/remove` now regenerates `workspace/AGENTS.md` in addition to `CLAUDE.md`. Previously, Codex CLI bots received stale instructions after any module change because `_regenerate_claude_md()` only updated `CLAUDE.md`. Design: [openspec/changes/20260418-agents-md-sync-fix/](openspec/changes/20260418-agents-md-sync-fix/)
- **Permission Remediation（三層防線）** — v0.5.0 部署後所有功能靜默失敗的根因修復。設計決策：[openspec/changes/20260408-permission-remediation/](openspec/changes/20260408-permission-remediation/)
  - **settings.json 格式修正**：`SettingsGenerator` 輸出從不合法的 `{"allowedTools": [...]}` 改為 Claude Code 規範的 `{"permissions": {"allow": [...], "deny": [...]}}`
  - **Permission mode 支援**：`ClaudeProcess._build_claude_args()` 新增 `permission_mode` 參數（**已由 20260411 安全修復取代，見下方 Security 節**）
  - **Dispatcher 權限傳遞**：`_process_task()` 用 `context.is_owner`（單一來源）推導 `permission_mode` 傳給 `ClaudeProcess`（**已由 20260411 安全修復取代，`permission_mode` 參數已移除**）
  - **Core 模組基線權限**：`modules/core/opentree.json` 新增 8 個基線工具（Read/Write/Edit/Glob/Grep/WebSearch/WebFetch/Task）
  - **Guardrail .env deny 加固**：`modules/guardrail/opentree.json` 新增 `Read(config/.env*)` 等 deny pattern，防禦敏感檔案讀取
  - **新用戶 memory 目錄預建**：`_build_prompt_context()` 為首次互動的用戶預先建立 memory 目錄
  - **permission_mode 驗證**：`_build_claude_args()` 對未知 permission_mode 值記錄 warning
  - **admin_users docstring 修正**：空 tuple 語意從「所有人都是 admin」修正為「無人有 owner 權限」
  - **回歸測試**：新增 `test_permission_completeness.py`（18 tests）+ `test_settings_coverage.py`（6 tests）確保權限完整性
- **init 缺 `data/logs/` 目錄** — nohup redirect 在 run.sh mkdir 之前執行導致靜默失敗，init 現在建立完整目錄結構
- Fix cross-thread memory: bind `data/memory/` into bwrap sandbox (via `--ro-bind` at same host path) so Codex can read `memory.md` inside the sandbox; `memory_extractor` now scans user message (`task.text`) instead of bot response (`result.response_text`) to prevent garbage entries from bot confirmation phrases

### Security

- **Sandboxed Bash execution (bwrap)** — All Codex CLI subprocesses now execute inside
  a bubblewrap (bwrap) kernel namespace sandbox. Mount isolation restricts filesystem
  access to /workspace and ~/.codex only. /mnt/e/ (Windows FS), ~/.ssh, and other
  sensitive paths are excluded. Zero-trust design: sandbox applies to all users including
  owner. Bot refuses to start if bwrap is unavailable. Network remains open for Codex API.
  Design: [openspec/changes/20260416-sandboxed-bash/](openspec/changes/20260416-sandboxed-bash/)
  - **bwrap HOME 分離修正** — sandbox HOME 改為獨立 tmpfs `/home/codex`（原為 `/workspace`），避免非 owner 的 ro-bind workspace 導致 `bwrap: Can't mkdir /workspace/.codex` 失敗
  - **nested bwrap 禁止** — sandboxed 模式改用 `--dangerously-bypass-approvals-and-sandbox --skip-git-repo-check`（原 `--full-auto`），避免 Codex 在 outer bwrap 內再嵌套自己的 sandbox
  - **SSL CA bundle 注入** — sandbox 內設定 `SSL_CERT_FILE` + `NODE_EXTRA_CA_CERTS` 指向 `/etc/ssl/certs/ca-certificates.crt`，解決 Codex Node.js TLS 無法驗證憑證的問題
- **移除 `--dangerously-skip-permissions`（bypassPermissions）** — Owner 用戶不再跳過權限評估。所有使用者（含 Owner）一律採 `--permission-mode dontAsk`，`settings.json` 的 allow/deny 規則對所有人生效。`ClaudeProcess` 的 `permission_mode` 參數已移除。設計決策：[openspec/changes/20260411-owner-dontask-mode/](openspec/changes/20260411-owner-dontask-mode/)
  - **`modules/core/opentree.json` 路徑限縮**：裸 `Read`/`Write`/`Edit` 改為 `$OPENTREE_HOME/**` 和 `//tmp/**` 範圍限制，防止讀寫工作區外的系統路徑
  - **`modules/guardrail/opentree.json` 絕對路徑 deny 強化**：新增 `Read($OPENTREE_HOME/config/.env*)` 等 3 條絕對路徑規則，補強相對路徑 deny 的盲點
  - ⚠️ **部署注意**：升級後必須執行 `opentree module refresh` 以重新生成 `workspace/.claude/settings.json`，否則舊的裸 `Read`/`Write`/`Edit` 規則仍會生效
- **legacy `.env` 遷移** — `init --force` 時自動偵測 legacy `.env` 含真實 token 並遷移到 `.env.local`，避免 placeholder 覆蓋
- **`_load_tokens` placeholder fallback** — 三層 .env merge 後若 token 仍為 placeholder，fallback 到 legacy `.env`
- **`_validate_not_placeholder` 雙重掃描** — 改為 `next()` 單次掃描取得 prefix 用於錯誤訊息
- **run.sh uv run 路徑不再含 single-quotes** — 修復 bash 變數展開時 literal quote 導致 `uv --directory` 失敗的問題

## [0.5.0] - 2026-04-07

> **Owner Freedom** — 術語替換、人設重寫、CLAUDE.md 保護、.env 分層、Reset 指令、記憶系統升級
>
> 設計決策：[openspec/changes/20260407-owner-freedom/](openspec/changes/20260407-owner-freedom/)

### Added
- **Admin -> Owner 術語替換** — 全系統將「Admin」概念替換為「Owner」，向後相容保留所有別名（`{{admin_description}}`、`context["is_admin"]`、`--admin-users` CLI）
- **Owner 人設重寫** — personality 模組從「團隊虛擬員工」轉向「個人 AI 助手」（忠誠、好奇、正向、主動關心），character.md + tone-rules.md 全面改寫
- **CLAUDE.md Marker Comment 保護** — `<!-- OPENTREE:AUTO:BEGIN/END -->` 標記自動生成區塊，Owner 自訂內容在 marker 外不被 refresh/install 覆蓋。新增 `wrap_with_markers()`、`generate_with_preservation()` API
- **.env 三段式載入** — `.env.defaults`（bot 預設 key）+ `.env.local`（Owner 自訂 key）+ `.env.secrets`（可選），向後相容舊 `.env` fallback。新增 `_parse_env_file()` + placeholder 驗證
- **reset-bot / reset-bot-all 指令** — Owner 專用。`reset-bot` 軟重設（保留 .env.local + data/ + Owner CLAUDE.md 內容）；`reset-bot-all` 硬重設（清除全部自訂）。Best-effort 錯誤處理 + SessionManager.clear_all() 並發安全
- **四區段結構化記憶系統** — Pinned（明確記住）/ Core（偏好+環境）/ Episodes（互動經驗）/ Active（近期工作）。語意路由（記住->Pinned, 偏好->Core）+ 語意去重 + 舊格式自動 migration + per-user threading.Lock 並發安全 + 原子寫入
- **memory_extraction_enabled 設定** — RunnerConfig 新增旗標，可一鍵關閉記憶提取
- **`is_admin` 欄位** — PromptContext 新增 `is_admin: bool`（alias -> `is_owner`），system prompt 輸出權限等級
- **`build_channel_block()`** — 新增頻道資訊區塊，輸出頻道 ID、Thread TS、Workspace
- **thread_participants 自動填入** — Dispatcher 從 thread 歷史提取參與者 display name
- **記憶讀取提示** — `build_identity_block()` 在記憶路徑後加入讀取提示
- **`has_result_event` 旗標** — StreamParser 的 ProgressState 區分「token 為 0」和「沒收到 result event」
- **Token 缺失 warning log** — Claude CLI stream 未回報 result event 時記錄 warning
- **PromptContext 擴充** — 新增 `thread_participants`、`opentree_home` 欄位
- **Dispatcher `_check_new_user`** — 新使用者偵測 + `_known_existing_users` 快取
- **slack hook: Thread 參與者提醒** — 多參與者 thread 注入安全提醒
- **requirement hook: 訪談上下文偵測** — thread_ts 匹配時注入需求訪談上下文
- **版本號 single source of truth** — `importlib.metadata.version("opentree")` 動態讀取
- **pyyaml 主依賴** — 加入 `pyproject.toml` 主依賴
- **README 完整覆寫** — 涵蓋功能特色、安裝、Quick Start、模組系統、架構、開發指引

### Changed
- **workspace 動態化** — `_build_prompt_context()` workspace 從硬編碼改為 `team_name or "default"`
- **Modules manifest permissions 路徑統一** — 對齊 `Bash(uv run --directory *:*<tool>*)` 格式
- **Modules manifest placeholder 補齊** — personality 補 `admin_description`、guardrail 補 `bot_name`、memory 補 `bot_name`
- **guardrail 模組術語** — security-rules / permission-check / denial-escalation / message-ban 全部從「管理員」更新為「Owner」
- **.env.defaults guardrail 保護** — security-rules.md 新增禁止存取 .env.defaults / .env.local / .env.secrets 規則

### Fixed
- **run.sh command detection** — 自動偵測 source checkout 並使用 `uv run --directory`
- **Slack 依賴自動安裝** — source checkout 模式下自動 `uv sync --extra slack`
- 移除 init.py hint 訊息中已不存在的 `--admin-channel` 參數引用
- 移除 guardrail manifest 中 `admin_channel` placeholder 殘留宣告
- run.sh singleton lock file 改到 `/tmp/`（修復 WSL2 DrvFs flock 問題）
- Registry.lock file 同步改到 `/tmp/`（md5 hash 隔離）
- **Elapsed time 與 token stats 解耦** — 完成訊息耗時不再依賴 token 計數
- **3 個 xfail 升級為 hard pass** — test_long_input_handled、test_multi_turn_context、test_same_thread_maintains_context
- 清理 modules/ 殘留：5 個 `.gitkeep`、3 個 `__pycache__/`
- **`ParsedMessage.files` 不可變** — 從 `list` 改為 `tuple`
- **未使用 import 清理** — dispatcher.py、prompt.py、requirement hook

## [0.4.0] - 2026-04-04

### Added
- **`opentree module update` 指令** — 比對 bundled vs installed 版本，支援 `--all`/`--dry-run`/`--force`。純 Python tuple-based semver 比較（無外部依賴）。新增 `core/version.py`
- **E2E single-instance guard** — session-scoped autouse fixture，所有 E2E 測試前自動檢查 Bot Walter instance 數（`pgrep` 結果 >2 = 多 instance → `pytest.exit` 中止）
- **E2E 並行控制** — `E2E_MAX_CONCURRENT=5`（semaphore 控制同時 pending bot 互動數）、`E2E_QUEUE_TIMEOUT=300`（5 分鐘排隊超時）、`E2E_MAX_TIMEOUT_FAILURES=3`（累積超時中止）。均可透過環境變數覆寫
- **SlackAPI.delete_message()** — 用於清除 queued ack 訊息

### Fixed
- **Queued ack 訊息未清理** — task 被 queue 時發的 "Your request is queued..." 在 task 被 promoted 處理後未刪除，導致 thread 同時出現 ack + 真實回覆。修復：Task 新增 `queued_ack_ts` 欄位，`_process_task` 開頭 `delete_message` 清除 ack
- **TaskQueue promotion 不 spawn worker thread** — `_promote_next_locked()` 將 pending task 標記為 RUNNING 但沒有通知 Dispatcher spawn worker thread。concurrent messages 時 promoted task 永久佔用 running slot，後續 task 全部卡在 pending。修復：`mark_completed`/`mark_failed` 回傳 promoted tasks，`Dispatcher._spawn_promoted()` 為每個 promoted task spawn thread
- **test_initial_ack_sent** — 改用 `read_thread_raw`（SDK 直接呼叫）保留 Block Kit blocks；assertion 改為檢查非 ack 狀態（不含 hourglass + 非空）取代字串長度比較
- **temp_file_cleanup flaky** — 新增 `drain_bot_queue` conftest fixture，測試前送 ping 等 bot 回覆確認 queue 清空
- **2 個 xfail 升級為 hard pass** — `test_file_not_found_handled_gracefully`、`test_session_stored_in_sessions_json` 在單 instance 環境穩定通過
- **LOW issues 批次修復** — run.sh log() 導向 stderr、sleep 變數加引號、bot.py 移除重複 startup log、test_logging teardown 標準化 h.close()

## [0.3.0] - 2026-04-03

### Fixed
- PlaceholderEngine: unknown `{{...}}` patterns preserved (single-pass regex, no double-replacement)
- prompt_hook: cached at startup via `PromptHookCache` (no repeated exec_module)
- **run.sh wrapper singleton lock** — `flock` 防止多 wrapper 同時執行導致 bot instance 累積（36 instance 殘留事故的根因修復）
- **run.sh stale PID cleanup** — 啟動前檢查 PID file 對應進程是否殘留，SIGTERM→30s→SIGKILL 升級清理
- **test_crash_recovery 精準化** — `pkill -f "opentree"` 改為從 PID file 讀取精準 PID + `os.kill()`；`sleep(5)` 盲等改為 poll 確認進程退出；新增 teardown fixture 清理 orphan；`_get_bot_pids()` pattern 從 `"opentree"` 精準到 `"opentree start --mode slack"`
- **E2E conftest 回覆過濾增強** — `wait_for_bot_reply`/`wait_for_nth_bot_reply` 過濾範圍擴大：新增 `:brain:`、`:hammer_and_wrench:`、`:writing_hand:` progress emoji + `"queued"` 佇列訊息過濾；`check_bot_alive` 改為 PID file 優先 + 精準 pgrep fallback
- **E2E 測試穩定化** — 22 個 failure 修復：3 scheduler tests skip（Bot_Walter 無 CLI 工具）、中文關鍵詞補充、null byte 移除、workspace 內部路徑、inter-message delay 10s、sessions.json 輪詢、AI 非確定性測試標 xfail

### Added
- **E2E 測試套件** (`tests/e2e/`): 59 個新測試案例（7 檔案），涵蓋 progress（思維/工具追蹤/token 統計）、file handling、memory extraction、session management、OWASP security（20 tests）、extensions（排程/需求/DM）、UX resilience（queue/錯誤復原/circuit breaker）。4 輪 Code Review，37 個問題全修
- **E2E conftest 動態頻道解析** — `_resolve_channel_id()` 三層策略：`E2E_CHANNEL_ID` 環境變數 → Slack API `conversations_list` 按名稱查找 → hardcoded fallback。取代先前硬編碼的 channel ID
- Disk space health monitoring (`health.py`) with hourly checks and WARNING threshold
- `PromptHookCache` class for thread-safe hook callable caching
- **Retry mechanism** (`retry.py`): exponential backoff for overloaded errors, session clear for session errors
- **Circuit Breaker** (`circuit_breaker.py`): CLOSED→OPEN→HALF_OPEN state machine, 5-failure threshold
- **Tool Tracker** (`tool_tracker.py`): tracks tool usage + duration, displays timeline in completion message
- **Memory Extractor** (`memory_extractor.py`): heuristic extraction of memorable content (EN/ZH patterns), auto-persist to user memory file

## [0.2.0] - 2026-03-31

### Added
- E2E verification complete: status, help, Claude reply, multi-turn context, concurrent requests, crash recovery
- **Slack Bot Runner** (`src/opentree/runner/`): 獨立的 Slack bot runtime，不依賴 DOGI 程式碼
  - `bot.py`: Bot 生命週期管理（啟動、signal handling、graceful shutdown）
  - `receiver.py`: Socket Mode 事件接收（app_mention、DM、去重、heartbeat）
  - `dispatcher.py`: 任務分發（動態 PromptContext、admin 指令、worker thread）
  - `claude_process.py`: Claude CLI subprocess 管理（stream-json、timeout、env 白名單）
  - `stream_parser.py`: stream-json 解析（phase 偵測、token 統計）
  - `slack_api.py`: Slack Web API 封裝（SDK only、快取、error isolation）
  - `task_queue.py`: 並行控制（per-thread 序列化、FIFO、drain）
  - `progress.py`: Block Kit 進度回報（背景 thread 定期更新、spinner、token 統計）
  - `thread_context.py`: Thread 歷史讀取（滑動視窗、char 上限截斷）
  - `file_handler.py`: Slack 附件下載（sanitize、大小限制、cleanup）
  - `session.py`: Session 管理（thread_ts → session_id、JSON 持久化、atomic save）
  - `config.py`: RunnerConfig（frozen dataclass、runner.json 載入）
  - `logging_config.py`: 日誌系統（daily rotation + console 雙輸出、PermissionError fallback）
- `templates/run.sh`: Bash wrapper（自動重啟、watchdog、crash loop 保護、DNS 檢查）
- `opentree start --mode slack`: 新增 Slack bot daemon 模式
- `opentree init`: 產生 `bin/run.sh`（placeholder 替換 + chmod +x）和 `config/.env.example`
- `pyproject.toml`: 新增 `[slack]` optional dependency group（slack-bolt、slack-sdk）
- E2E test infrastructure (`tests/e2e/`) with pytest fixtures for Slack integration
- `admin_users` field in `RunnerConfig` for shutdown authorization
- Layer 2 dedup in `Dispatcher` (`_dispatched_ts` set with thread lock)

### Changed
- `core/prompt.py`: 修復 `collect_module_prompts` 的 sys.modules 並行競爭（thread-local key + lock）
- `core/prompt.py`: 新增 `_is_safe_name()` 和 `_is_safe_hook_path()` 路徑驗證（防止 path traversal）
- `cli/init.py`: `start_command` 新增 `--mode` 參數（`interactive` | `slack`），加入模式驗證

### Fixed
- `slack_api.py`: SlackAPI response parsing — replaced broken `getattr` pattern with `_extract_data()` helper
- `receiver.py`: Bot-to-bot @mention — allow other bots' explicit @mentions through `_handle_message`
- `dispatcher.py`: Cross-handler dedup race — single handler architecture + Layer 2 dispatcher dedup (`_dispatched_ts` set with thread lock)
- `dispatcher.py`: Shutdown authorization — `admin_users` config with auth check in `_handle_admin_command`
- `receiver.py`: Heartbeat on all events — write before filters to prevent watchdog false kills
- `dispatcher.py`: Double heartbeat write — removed redundant `_write_heartbeat()` call
- `run.sh`: `wait || true` 導致 crash detection 失效（exit code 永遠為 0）
- `run.sh`: `$BOT_CMD` 未引號導致路徑含空格時崩潰（改用 bash array）
- `run.sh`: `cleanup()` 無 timeout（bot 掛起時 wrapper 永遠阻塞，加入 40s timeout + SIGKILL）
- `file_handler.py`: `cleanup_temp()` 路徑與 `download_files()` 不一致（統一使用 `_safe_thread_dir()`）
- `progress.py`: `_push_progress()` 缺少例外處理（Slack API 429 導致 thread 靜默終止）
- `logging_config.py`: `handlers.clear()` 未 close handler（file descriptor 洩漏）
- `bot.py`: `_shutdown()` 重新讀取 config（改用 start() 時快取的值）
- `dispatcher.py`: `reporter.start()` 失敗時使用者無回應（加入 fallback send_message）

### 設計決策
- Phase 1 核心循環：[openspec/changes/20260330-slack-bot-runner/](openspec/changes/20260330-slack-bot-runner/)
- Phase 2 UX 強化：[openspec/changes/20260330-phase2-ux/](openspec/changes/20260330-phase2-ux/)
- Phase 3 運維：[openspec/changes/20260330-phase3-ops/](openspec/changes/20260330-phase3-ops/)
- E2E 驗證：[openspec/changes/20260331-e2e-verification/](openspec/changes/20260331-e2e-verification/)

## [0.1.0] - 2026-03-29

### Added
- 初始架構：模組系統（manifest 驗證、registry、symlink、settings、CLAUDE.md 生成）
- 10 個 bundled modules（core、personality、guardrail、memory、scheduler、slack、audit-logger、requirement、stt、youtube）
- CLI 命令：`opentree init`、`opentree start`、`opentree module install/remove/list/refresh`、`opentree prompt show`
- PlaceholderEngine（`{{key}}` 替換、symlink vs resolved_copy）
- Prompt hook 系統（PromptContext + 動態模組注入）
- 265 tests、91% coverage
