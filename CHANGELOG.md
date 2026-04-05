# Changelog

格式基於 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
- **`is_admin` 欄位** — PromptContext 新增 `is_admin: bool`，由 Dispatcher 比對 `RunnerConfig.admin_users` 自動計算，system prompt 輸出「權限等級：Admin」或「權限等級：一般使用者」
- **`build_channel_block()`** — 新增頻道資訊區塊，輸出頻道 ID、Thread TS、Workspace（參考 DOGI `build_channel_block`）
- **thread_participants 自動填入** — Dispatcher 從 thread 歷史提取參與者 display name，slack hook 的多人 thread 警告現可正常觸發
- **記憶讀取提示** — `build_identity_block()` 在記憶路徑後加入「如需了解此使用者的偏好和習慣，請使用 Read 工具讀取上述檔案」
- **`has_result_event` 旗標** — StreamParser 的 ProgressState 新增旗標，區分「token 真的是 0」和「沒收到 result event」
- **Token 缺失 warning log** — Claude CLI stream 未回報 result event 或 token 都為 0 時，記錄 warning（含 pid、exit_code、timed_out 狀態）
- **PromptContext 擴充** — 新增 `thread_participants`（Thread 參與者列表）和 `opentree_home`（根目錄路徑）欄位，供模組 hook 動態注入
- **Dispatcher `_check_new_user`** — 新使用者偵測邏輯（memory.md 不存在/空/僅模板時回傳 True），驅動 FTUE 導覽
- **slack hook: Thread 參與者提醒** — 當 thread 有其他參與者時注入安全提醒，自動排除當前使用者
- **requirement hook: 訪談上下文偵測** — 掃描 `data/requirements/*/interviews/*.yaml`，匹配 thread_ts 時注入需求訪談上下文（受訪者、階段、題數、觀察筆記）
- **版本號 single source of truth** — `__version__` 改為 `importlib.metadata.version("opentree")` 動態讀取，fallback 硬編碼；`runner.__version__` 改為 re-export 主套件版本。新增版本一致性測試
- **`_check_new_user` 快取** — 已確認非新使用者的 memory_path 快取到 `_known_existing_users` set，避免每次請求重複讀檔
- **pyyaml 主依賴** — `pyyaml>=6.0` 加入 `pyproject.toml` 主依賴，requirement hook 改為直接 import（移除 optional fallback）
- **README 完整覆寫** — 從 21 行佔位符更新為完整英文文件，涵蓋功能特色、安裝、Quick Start、模組系統、架構、開發指引

### Changed
- **workspace 動態化** — `_build_prompt_context()` 的 workspace 從硬編碼 `"default"` 改為 `team_name or "default"`
- **Modules manifest permissions 路徑統一** — scheduler、slack、audit-logger、requirement 的 `permissions.allow` 從 `$OPENTREE_HOME/bin` 改為 `Bash(uv run --directory *:*<tool>*)` 格式，對齊 rules 中的實際 CLI 指令
- **Modules manifest placeholder 補齊** — personality 補 `admin_description`、guardrail 補 `bot_name`、memory 補 `bot_name`

### Fixed
- **run.sh command detection** — `opentree init` 自動偵測 source checkout（pyproject.toml 存在）並使用 `uv run --directory` 取代裸 `opentree` 指令。路徑使用單引號避免空格問題。非 source checkout 時保持裸 `opentree`
- **Slack 依賴自動安裝** — source checkout 模式下 `opentree init` 自動執行 `uv sync --extra slack`，失敗時警告但不中斷（timeout 120s）
- 移除 init.py hint 訊息中已不存在的 `--admin-channel` 參數引用
- 移除 guardrail manifest 中 `admin_channel` placeholder 殘留宣告
- run.sh singleton lock file 改到 `/tmp/`（修復 WSL2 DrvFs 上 flock 不生效的問題）
- Registry.lock file 同步改到 `/tmp/`（md5 hash 隔離不同 instance）
- **Elapsed time 與 token stats 解耦** — 完成訊息的耗時（`:clock1:`）不再依賴 token 計數才顯示。Claude CLI 未回報 usage 時，耗時仍正常顯示（progress.py line 135 條件修正）
- **3 個 xfail 升級為 hard pass** — test_long_input_handled、test_multi_turn_context、test_same_thread_maintains_context 在單 instance 環境穩定通過
- 清理 modules/ 殘留：5 個 `.gitkeep`（rules 已有 .md）、3 個 `__pycache__/`
- **`ParsedMessage.files` 不可變** — 從 `list`（mutable）改為 `tuple`，對齊 `frozen=True` dataclass 語義
- **未使用 import 清理** — dispatcher.py（`build_completion_blocks`、`TaskStatus`、`Optional`）、prompt.py（`field`）、requirement hook（`os`、`glob`）

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
