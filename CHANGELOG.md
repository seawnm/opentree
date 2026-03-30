# Changelog

格式基於 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
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
- `opentree start --mode slack`: 新增 Slack bot daemon 模式
- `pyproject.toml`: 新增 `[slack]` optional dependency group（slack-bolt、slack-sdk）

### Changed
- `core/prompt.py`: 修復 `collect_module_prompts` 的 sys.modules 並行競爭（thread-local key + lock）
- `core/prompt.py`: 新增 `_is_safe_name()` 和 `_is_safe_hook_path()` 路徑驗證（防止 path traversal）
- `cli/init.py`: `start_command` 新增 `--mode` 參數（`interactive` | `slack`），加入模式驗證

### 設計決策
詳見 [openspec/changes/20260330-slack-bot-runner/](openspec/changes/20260330-slack-bot-runner/)

## [0.1.0] - 2026-03-29

### Added
- 初始架構：模組系統（manifest 驗證、registry、symlink、settings、CLAUDE.md 生成）
- 10 個 bundled modules（core、personality、guardrail、memory、scheduler、slack、audit-logger、requirement、stt、youtube）
- CLI 命令：`opentree init`、`opentree start`、`opentree module install/remove/list/refresh`、`opentree prompt show`
- PlaceholderEngine（`{{key}}` 替換、symlink vs resolved_copy）
- Prompt hook 系統（PromptContext + 動態模組注入）
- 265 tests、91% coverage
