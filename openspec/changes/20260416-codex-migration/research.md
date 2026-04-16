# Research: Claude Code CLI vs Codex CLI 介面差異調研

## 建立日期
2026-04-16

---

## 1. CLI 呼叫介面對比

### Claude Code CLI（現況）

```bash
claude \
  --output-format stream-json \
  --verbose \
  --system-prompt "<system_prompt_text>" \
  --permission-mode dontAsk \
  --print \
  [--resume <session_uuid>] \
  "<user_message>"
```

關鍵旗標：
| 旗標 | 用途 |
|------|------|
| `--output-format stream-json` | 機器可讀的 JSONL 串流輸出 |
| `--system-prompt <text>` | 每次 request 動態注入 system prompt |
| `--permission-mode dontAsk` | 不問使用者，自動允許 allow 清單內的工具 |
| `--print` | 非互動模式（batch） |
| `--resume <uuid>` | 恢復指定 session |
| 無 `--cwd` 旗標 | cwd 透過 `subprocess.Popen(cwd=...)` 設定 |

### Codex CLI（目標）

```bash
codex exec \
  --json \
  --dangerously-bypass-approvals-and-sandbox \
  -C <workspace_dir> \
  [--full-auto] \
  "<user_message>"

# Session resume
codex exec resume \
  --json \
  --session-id <thread_id> \
  "<user_message>"
```

關鍵旗標：
| 旗標 | 用途 |
|------|------|
| `--json` | 輸出 JSONL 事件流（等同 Claude 的 stream-json） |
| `-C <dir>` | 設定 working directory（讀 AGENTS.md） |
| `--full-auto` | 低摩擦沙箱自動執行（`--sandbox workspace-write`） |
| `--dangerously-bypass-approvals-and-sandbox` | 跳過所有確認（等同 Claude 的 dontAsk，但更危險） |
| `--ephemeral` | 不持久化 session |
| `-o <file>` | 最後一則訊息寫入指定檔案 |

---

## 2. System Prompt 注入機制

### Claude：動態注入（每次 request）

`--system-prompt` 是 CLI 旗標，每次 subprocess 啟動時傳入，無需改動任何檔案。這使得：
- 每個 user 的 system prompt 完全動態（包含記憶路徑、user_id、thread_ts）
- 不同使用者可以有完全不同的 prompt，無競爭問題

### Codex：靜態檔案（`AGENTS.md`）

Codex 讀取 `-C <dir>` 指定目錄下的 `AGENTS.md` 作為 agent instructions。**沒有** `--system-prompt` 旗標。

**影響**：在呼叫 `codex exec` 前，必須將 system prompt 寫入 workspace 的 `AGENTS.md`。

**Concurrency 問題**：如果兩個使用者同時發送訊息，可能發生 AGENTS.md 被第二個使用者的 system prompt 覆蓋後，第一個使用者的 Codex subprocess 才讀取的情況。

**解決方案**（候選）：
- **A. 每個使用者獨立 workspace 目錄**（推薦）：Codex subprocess 的 `-C` 指向使用者專屬目錄（`data/<user_id>/workspace/`），AGENTS.md 寫入使用者目錄 → 無競爭
- **B. 使用 `--ephemeral` + stdin prompt**：Codex 0.120.0 支援從 stdin 讀取 prompt（`codex exec -`），但 system instructions 仍來自 AGENTS.md
- **C. 每次 request 用 temp dir**：為每個 request 建立 temp workspace，寫入 AGENTS.md，執行後清除 → overhead 高，session resume 困難

**結論**：採用方案 A，與現有 `cwd=workspace_dir` 設計吻合。

---

## 3. 輸出格式對比

### Claude `stream-json` 事件

```json
{"type": "system", "subtype": "init", "session_id": "abc-123"}
{"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "回覆文字"}]}}
{"type": "result", "result": "最終回覆", "session_id": "abc-123", "is_error": false,
 "usage": {"input_tokens": 100, "output_tokens": 50}}
```

### Codex `--json` JSONL 事件

```json
{"type": "thread.started", "thread_id": "019d9459-e5f1-7670-9b4c-31e108648deb"}
{"type": "turn.started"}
{"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "..."}}
{"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": "...", "status": "in_progress"}}
{"type": "item.completed", "item": {"id": "item_1", "type": "command_execution", "aggregated_output": "...", "exit_code": 0, "status": "completed"}}
{"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "最終回覆"}}
{"type": "turn.completed", "usage": {"input_tokens": 38211, "cached_input_tokens": 22400, "output_tokens": 84}}
```

### 映射關係

| Claude 事件 | Codex 事件 | 備註 |
|-------------|-----------|------|
| `system/init` → `session_id` | `thread.started` → `thread_id` | session ID 來源 |
| `content_block_start` (tool_use) | `item.started` (command_execution) | 工具呼叫開始 |
| `result` → `result` text | `item.completed` (agent_message) 最後一則 | 最終回覆文字 |
| `result` → `usage` | `turn.completed` → `usage` | token 統計 |
| `result.is_error` | 目前需從 exit code 或 error event 判斷 | 錯誤判斷 |

**重要差異**：
- Codex 可能有多則 `agent_message`（thinking + 最終回覆），需取**最後一則**
- Codex token 統計在 `turn.completed`（最後才到），Claude 在 `result` 事件
- Codex 沒有直接等同 `is_error` 的旗標，需從事件流判斷

---

## 4. Session Resume

### Claude

```bash
claude --resume abc-123-def ... "下一則訊息"
```
session_id 來自 `result` 事件，格式為標準 UUID。

### Codex

```bash
codex exec resume --session-id 019d9459-e5f1-7670-9b4c-31e108648deb "下一則訊息"
```
thread_id 來自 `thread.started` 事件，格式為 UUID v7（含時間戳）。

**驗證狀態**：Codex `exec resume` 是否能保留工具呼叫歷史和對話上下文，需實測確認。

---

## 5. Permission Model

### Claude `settings.json`

```json
{
  "permissions": {
    "allow": ["Bash(git:*)", "Read(**)"],
    "deny": ["Bash(rm -rf *)"]
  }
}
```
細粒度工具層級白名單/黑名單，由 `SettingsGenerator` 從模組 manifest 彙整。

### Codex `config.toml` / CLI 旗標

```toml
[sandbox_permissions]
# disk-full-read-access, disk-full-write-access, network-full-access...

[shell_environment_policy]
inherit = "none" | "all" | { allowlist = ["VAR1", "VAR2"] }
```

Codex 的 permission 是 sandbox 層級（file system / network），而非工具層級。精細的工具控制需透過 `AGENTS.md` 中的 instructions 約束 AI 行為，而非 CLI 強制執行。

**影響**：`SettingsGenerator` 的 allow/deny per-tool 設計在 Codex 下無法直接對應，需改為：
1. Codex sandbox 設定（粗粒度）
2. AGENTS.md 中的行為規則（指示 AI 不要做哪些事）

---

## 6. 環境變數白名單

### Claude

`_ENV_WHITELIST` 控制哪些環境變數傳遞給 subprocess（含 `ANTHROPIC_API_KEY`、`CLAUDE_CONFIG_DIR` 等）。

### Codex

使用 `shell_environment_policy`：
- `inherit = "all"` — 繼承所有環境變數
- `inherit = "none"` — 不繼承
- `inherit = { allowlist = ["OPENAI_API_KEY", "PATH", ...] }` — 白名單模式

等同 `_ENV_WHITELIST`，但在 `config.toml` 設定而非程式碼。

---

## 7. 淘汰方案

### 方案 B（中介層）：保留 `stream_parser.py` 介面，加一層轉換器

在 `codex_process.py` 中將 Codex JSONL 事件翻譯成 Claude stream-json 格式，再送給現有的 `StreamParser`。

**優點**：不需改動 `StreamParser` 和 `Dispatcher`
**缺點**：多一層轉換複雜度，Codex 事件和 Claude 事件語義不完全對應（如 `turn.completed` vs `result`），轉換層容易出現邊界案例 bug。

**結論**：淘汰。直接重寫 `StreamParser` 更清晰，測試也更容易。

### 方案 C（雙模式支援）：同時支援 Claude 和 Codex

在 `RunnerConfig` 加 `backend: "claude" | "codex"` 旗標，根據設定選擇不同的 Process class。

**優點**：漸進式遷移，可回滾
**缺點**：長期維護兩套程式碼；Permission model 差異大，很難真正做到透明切換。

**結論**：若有回滾需求可考慮保留 `claude_process.py` 原始檔案，但不建議長期維護雙模式。

---

## 結論

最小侵入性的遷移路徑：
1. **重寫** `claude_process.py` → `codex_process.py`（相同介面，返回相同 `ClaudeResult`）
2. **重寫** `stream_parser.py`（解析 Codex JSONL）
3. **修改** `generator/` 生成 `AGENTS.md` 而非 `CLAUDE.md`
4. **保留** `ClaudeResult` dataclass 名稱（或改名為 `AgentResult`，型別別名向後相容）
5. **保留** SessionManager（只是 session_id 格式從 UUID → thread_id）
