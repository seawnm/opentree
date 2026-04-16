# Proposal: Replace Claude Code CLI with Codex CLI

## 建立日期
2026-04-16

## 需求背景

使用者希望將 OpenTree 底層 AI runtime 從 **Claude Code CLI (`claude`)** 替換成 **OpenAI Codex CLI (`codex`)**。

目前 OpenTree 的 Runner 子系統透過 `claude_process.py` 呼叫 `claude --output-format stream-json --system-prompt ...` 執行 AI 任務，整條鏈路高度綁定 Claude CLI 的介面規格。

## 變更範圍

### 需要修改的檔案

| 檔案 | 變更類型 | 原因 |
|------|----------|------|
| `runner/claude_process.py` | **重寫** | 呼叫介面、輸出格式、session resume 全部不同 |
| `runner/stream_parser.py` | **重寫** | Codex JSONL 事件結構與 Claude stream-json 不同 |
| `runner/config.py` | **修改** | `claude_command` → `codex_command`；移除 Claude-specific 設定 |
| `runner/reset.py` | 小修改 | reset 後重建 AGENTS.md 而非 settings.json |
| `generator/settings.py` | **修改** | 生成 AGENTS.md（Codex 的 system prompt 載體）而非 `.claude/settings.json` |
| `generator/symlinks.py` | 小修改 | symlink 目標從 `.claude/rules/` 改為 Codex 支援的路徑 |
| `generator/claude_md.py` | **修改** | 生成 `AGENTS.md` 而非 `CLAUDE.md`（marker preservation 邏輯保留） |
| `cli/init.py` | **修改** | 產生 Codex workspace 設定；不產生 `.claude/settings.json` |
| `templates/run.sh` | **修改** | 啟動指令從 `claude ...` 改為 `codex exec ...` |
| `core/config.py` | 小修改 | 移除 `CLAUDE_CONFIG_DIR`；新增 Codex 相關設定 |

### 不需修改的檔案（設計保持不變）

- `runner/dispatcher.py`（呼叫 `ClaudeProcess` 的介面不變）
- `runner/session.py`（SessionManager 保留，session_id 格式改用 Codex thread_id）
- `runner/progress.py`（ProgressReporter 介面不變）
- `runner/memory_extractor.py`（記憶萃取邏輯與 CLI 無關）
- `registry/`、`manifest/`（模組系統不變）
- `core/prompt.py`（system prompt assembly 邏輯不變；輸出改為寫入 AGENTS.md）

## 影響分析

### 功能影響
- **System prompt 注入方式改變**：Claude 每次 request 動態注入 `--system-prompt`；Codex 讀取 workspace 的 `AGENTS.md`，需要在每次 request 前更新檔案
- **Session resume 格式改變**：Claude session_id 是 UUID；Codex 使用 `thread_id`，格式為 `019d...`（7.x UUID-like）
- **Token 計量格式改變**：`cached_input_tokens` 欄位新增
- **Permission model 改變**：Claude 有 `settings.json` allow/deny；Codex 用 `sandbox_permissions` + `shell_environment_policy`

### 風險
1. **Codex 無 `--system-prompt` 參數**：必須在每次 request 前將 system prompt 寫入 `AGENTS.md`，引入 I/O 開銷和 concurrency 競爭
2. **Session 連續性**：Codex `codex exec resume` 的行為需驗證是否支援跨重啟保留上下文
3. **測試覆蓋率下降**：現有 ~1250 tests 大量 mock Claude CLI，需全部更新

## 成功標準
- `opentree start --mode slack` 可正常接收 Slack 訊息並透過 Codex 回覆
- Session resume 跨 thread 正常運作
- Memory extraction 繼續有效
- 現有測試通過率 ≥ 85%
