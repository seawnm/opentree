# 遷移計畫：Claude Code CLI → Codex CLI

## 建立日期
2026-04-16

## 前置條件

- Codex CLI v0.120.0+ 已安裝（`codex --version` 可執行）
- `~/.codex/config.toml` 已設定 `trust_level = "trusted"` 給 OpenTree workspace 目錄
- Python 3.11+，OpenTree v0.5.0

---

## Phase 0：準備工作（人工執行，30 分鐘）

### 0-1. 確認 Codex 環境

```bash
codex --version                    # 確認 v0.120.0+
codex exec --json "echo hello"     # 確認 --json 輸出正常
codex exec resume --help           # 確認 session resume 支援
```

### 0-2. 備份現有測試基準

```bash
cd /mnt/e/develop/mydev/opentree
pytest tests/isolation/ -q --tb=no > /tmp/opentree-baseline-tests.txt 2>&1
echo "Tests baseline saved"
```

### 0-3. 建立 feature branch

```bash
git checkout -b feat/codex-migration
```

---

## Phase 1：新 Stream Parser（Codex JSONL）

### 目標
將 `runner/stream_parser.py` 重寫為解析 Codex `--json` JSONL 格式。

### 1-1. 新增 `runner/codex_stream_parser.py`

**Codex 事件映射**：

| Codex 事件 | 對應 Phase | 說明 |
|-----------|-----------|------|
| `thread.started` | INITIALIZING → THINKING | 提取 `thread_id` 作為 session_id |
| `turn.started` | THINKING | 開始思考 |
| `item.started` (command_execution) | TOOL_USE | 提取 `command` 作為 tool_name |
| `item.completed` (command_execution) | THINKING | 工具執行完畢，回到思考 |
| `item.completed` (agent_message) | GENERATING | 收集回覆文字（取最後一則） |
| `turn.completed` | COMPLETED | 提取 token 統計 |
| 無回覆且 exit_code != 0 | ERROR | 錯誤判斷 |

**新 `ProgressState` 欄位新增**：
- `cached_input_tokens: int = 0`（Codex 提供 cache hit 統計）

**保留介面**：`parse_line(line: str) -> Optional[Phase]`，`get_result() -> dict`

### 1-2. 更新 `runner/stream_parser.py`

保留原始 `StreamParser` 類別（供測試和回滾），在檔案頂部新增：
```python
# Codex migration: see codex_stream_parser.py for the new implementation
```

或直接替換（由 codex 執行）。

---

## Phase 2：新 Process Manager（Codex subprocess）

### 目標
重寫 `runner/claude_process.py` → `runner/codex_process.py`，對外介面與現有 `ClaudeProcess` 相同。

### 2-1. 呼叫介面變更

**Claude 舊介面**：
```bash
claude \
  --output-format stream-json \
  --verbose \
  --system-prompt "<text>" \
  --permission-mode dontAsk \
  --print \
  [--resume <uuid>] \
  "<message>"
```

**Codex 新介面**：
```bash
# 新 session
codex exec \
  --json \
  --dangerously-bypass-approvals-and-sandbox \
  -C <workspace_dir> \
  "<message>"

# Resume session
codex exec resume \
  --json \
  --session-id <thread_id> \
  --dangerously-bypass-approvals-and-sandbox \
  -C <workspace_dir> \
  "<message>"
```

### 2-2. System Prompt 注入策略

Codex 讀取 `-C <workspace_dir>/AGENTS.md` 作為 agent instructions。

**流程**：
1. `CodexProcess.__init__()` 接收 `system_prompt: str`（與現有介面相同）
2. 在 `run()` 執行 subprocess **前**，將 `system_prompt` 寫入 `<cwd>/AGENTS.md`
3. 使用 `per-user cwd`（已在 dispatcher 中實作），避免並發競爭
4. 寫入使用 atomic write（write to .tmp → os.replace）

**注意**：AGENTS.md 的 owner content preservation 邏輯（目前在 `ClaudeMdGenerator`）需要整合進來，或在寫入前先讀取並保留 marker 以外的 owner 內容。

### 2-3. 環境變數白名單更新

移除 Claude-specific 變數，新增 Codex 相關：

```python
_ENV_WHITELIST: frozenset[str] = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
    # Codex/OpenAI
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",        # 自訂 endpoint
    "CODEX_UNSAFE_ALLOW_NO_SANDBOX",
    # 通用
    "TMPDIR", "TMP", "TEMP",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
})
```

移除：`ANTHROPIC_API_KEY`, `CLAUDE_CODE_USE_BEDROCK`, `AWS_*`, `CLAUDE_CONFIG_DIR`, `NODE_EXTRA_CA_CERTS`

### 2-4. `ClaudeResult` → `AgentResult`（可選）

建議：保留 `ClaudeResult` dataclass 名稱或新增型別別名，避免破壞所有 import：
```python
AgentResult = ClaudeResult  # backward-compat alias
```

---

## Phase 3：Config 更新

### 目標
更新 `runner/config.py` 的 `RunnerConfig`。

### 3-1. 欄位變更

```python
@dataclass(frozen=True)
class RunnerConfig:
    # 改名：claude_command → codex_command（預設值改變）
    codex_command: str = "codex"

    # 新增：sandbox 模式
    codex_sandbox: str = "workspace-write"  # or "danger-full-access"

    # 移除（Codex 無等價項）：無需移除，只需不使用
    # claude_command 保留作 deprecated alias（向後相容）

    # 其餘欄位不變
    progress_interval: int = 10
    task_timeout: int = 1800
    heartbeat_timeout: int = 900
    max_concurrent_tasks: int = 2
    session_expiry_days: int = 180
    drain_timeout: int = 30
    admin_users: tuple[str, ...] = ()
    memory_extraction_enabled: bool = True
```

---

## Phase 4：Generator 更新（AGENTS.md 替代 CLAUDE.md）

### 目標
`generator/claude_md.py` 改為生成 `AGENTS.md`；`generator/settings.py` 的 `settings.json` 可選保留（Codex 不讀取，但不影響）。

### 4-1. `generator/claude_md.py` → 支援 `AGENTS.md`

**變更**：
- `_MARKER_BEGIN = "<!-- OPENTREE:AUTO:BEGIN -->"` 保留（AGENTS.md 也可以有 HTML 注釋）
- 輸出檔案名從 `workspace/CLAUDE.md` → `workspace/AGENTS.md`
- Marker preservation 邏輯完整保留
- 新增 `generate_agents_md()` 方法（或重命名 `generate_claude_md()` 為通用名）

**向後相容**：保留 `CLAUDE.md` 生成（某些使用者可能同時使用 Claude CLI），或在 init 時詢問目標 CLI。

### 4-2. `generator/settings.py`

Codex 不讀取 `.claude/settings.json`，但此檔案保留不影響運作。可選：
- **保留**：現有邏輯不動，只是 Codex 忽略此檔案
- **廢棄**：在 reset 和 init 時不再生成（清理目的）

建議：**保留**（漸進式遷移，降低風險）。

---

## Phase 5：CLI Init 更新

### 目標
`cli/init.py` 的 init 流程生成 Codex workspace 設定。

### 5-1. 生成 `~/.codex/config.toml` trust entry

```bash
[projects."<workspace_dir>"]
trust_level = "trusted"
```

在 `opentree init` 時自動追加到使用者的 `~/.codex/config.toml`。

### 5-2. 生成 `workspace/AGENTS.md`

呼叫更新後的 `ClaudeMdGenerator`，生成 `workspace/AGENTS.md`。

### 5-3. `_resolve_opentree_cmd()` 更新

`run.sh` 中的啟動指令從：
```bash
claude --output-format stream-json ...
```
改為：
```bash
codex exec --json -C <workspace_dir> ...
```
（這段由 `run.sh` template 管理，不在 `_resolve_opentree_cmd` 中）

---

## Phase 6：run.sh Template 更新

`templates/run.sh` 中的 Bot 啟動邏輯是 `opentree start --mode slack`，不直接呼叫 `claude`，因此 run.sh **不需要修改**。

`claude`/`codex` 的切換在 `codex_process.py` 內部處理。

---

## Phase 7：測試更新

### 7-1. 更新 mock

```
tests/isolation/runner/test_claude_process.py → test_codex_process.py
tests/isolation/runner/test_stream_parser.py  → test_codex_stream_parser.py
```

重點測試案例：
- `thread.started` 事件正確提取 `thread_id`
- 多則 `agent_message` 取最後一則
- `turn.completed` token 統計（含 `cached_input_tokens`）
- AGENTS.md atomic write 不競爭

### 7-2. E2E 測試更新

E2E 測試直接打實際 bot（`OPENTREE_E2E_DOGI_DIR`），換成 Codex 後行為應相同，但需確認：
- Session resume（`codex exec resume`）在 E2E 中正常工作
- 回應時間是否在可接受範圍（Codex 可能比 Claude 慢）

---

## 執行順序（codex exec 任務分配）

```
Task 1: 分析 + 建立 codex_stream_parser.py（Phase 1）
Task 2: 建立 codex_process.py（Phase 2）
Task 3: 更新 config.py、generator/claude_md.py（Phase 3, 4）
Task 4: 更新 cli/init.py（Phase 5）
Task 5: 更新所有相關測試（Phase 7）
Task 6: 整合測試 + 驗證
```

---

## 回滾計畫

若 Codex 遷移出現問題，回滾步驟：
1. `git checkout main` 或還原到 feature branch 前
2. `runner/config.py` 中將 `codex_command` 改回 `claude_command`
3. `runner/dispatcher.py` 的 `ClaudeProcess` import 切回舊版

---

## 風險清單

| 風險 | 機率 | 影響 | 緩解 |
|------|------|------|------|
| Codex session resume 行為不同 | 中 | 高 | Phase 0 先做實測 |
| AGENTS.md 並發競爭（同時多用戶） | 中 | 中 | Per-user cwd + atomic write |
| Codex 輸出格式版本間不穩定 | 低 | 高 | 鎖定 v0.120.0，加版本檢查 |
| Permission model 安全性下降 | 高 | 高 | AGENTS.md 中強化行為規則，sandbox 設定收緊 |
| 測試覆蓋率掉到 85% 以下 | 低 | 中 | Phase 7 全量更新測試 |

---

## 執行結果（2026-04-16）

### 完成的工作

| Phase | 狀態 | 說明 |
|-------|------|------|
| Phase 1: codex_stream_parser.py | ✅ 完成 | 新 JSONL 事件解析器，9 個測試全通過 |
| Phase 2: codex_process.py | ✅ 完成 | 新 subprocess 管理器，含 AGENTS.md atomic write |
| Phase 3: config.py | ✅ 完成 | `codex_command` 為主，`claude_command` 保留為 deprecated alias |
| Phase 4: dispatcher.py 切換 | ✅ 完成 | import CodexProcess 取代 ClaudeProcess；Phase import 改用 codex_stream_parser |
| Phase 7: 測試更新 | ✅ 完成 | test_dispatcher.py、test_runner_config.py、test_claude_process.py、test_memory_extractor.py 全部更新 |

### 測試結果
- 遷移相關測試：**302 passed, 0 failed**
- 核心 isolation 測試：**1143 passed, 0 failed**
- 排除項目：jsonschema 依賴缺失（test_validator 等）、E2E 需真實環境

### 尚未完成
- Phase 5: cli/init.py 生成 `~/.codex/config.toml` trust entry
- Phase 5: `workspace/AGENTS.md` 在 init 流程中生成
- generator/claude_md.py → AGENTS.md 支援（generator 層）
- CHANGELOG.md 更新
