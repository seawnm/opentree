# OpenTree Bot Runner — 完整進度報告

> 來源 Thread：betaroom 1774800803.111649
> 報告日期：2026-03-31
> 專案路徑：/mnt/e/develop/mydev/opentree/

---

## 一、專案概述

OpenTree 是一套模組化的 AI agent 框架，讓使用者透過安裝/移除模組來自訂 Claude Code 的行為（rules、permissions、prompt hooks）。v0.1.0 已完成模組系統基礎設施（manifest 驗證、registry、symlink 管理、settings 生成、CLAUDE.md 動態生成、PlaceholderEngine），包含 10 個 bundled modules、265 tests、91% coverage。

Bot Runner 的目標是為 OpenTree 建立獨立的 Slack bot runtime，讓 `opentree start --mode slack` 能啟動一個 24/7 daemon，接收 Slack @mention 事件、呼叫 Claude CLI、串流解析回覆。**完全獨立於 DOGI 程式碼**（零 import），從 DOGI 的 ~8,100 行 runtime 精簡為 ~2,700 行。

---

## 二、研究與規劃階段

### 2.1 初始規劃（3 agent 並行）

Bot Runner 的規劃由三個 agent 並行執行，各自產出獨立報告後合併決策：

| Agent | 產出 | 重點 |
|-------|------|------|
| **Planner Agent** | 完整實作計畫（3 Phase、8 步驟、~2,420 行、~153 tests） | 目錄結構、依賴管理、Phase 拆分 |
| **Architect Agent** | 架構分析（OpenTree vs DOGI 本質差異、trade-off 矩陣） | 強調單使用者 vs 多租戶的簡化空間，建議 ~1,420 行核心 |
| **Flow Simulator Agent** | 41 場景模擬（通過 27、失敗 14） | 發現 3 個 CRITICAL + 5 個 HIGH + 4 個 MEDIUM issues |

#### Planner vs Architect 的分歧

- **CLI 整合方式**：Planner 傾向 `--mode` flag（共享前置步驟），Architect 傾向獨立子指令 `opentree serve`（語義更清晰）。最終採用 Planner 方案（實作成本較低），未來需要 daemon 專屬 flag 時再抽離。
- **預估行數**：Planner 包含 Phase 2 支援元件（~2,420 行），Architect 只算核心 runtime（~1,420 行）。

### 2.2 關鍵決策

| # | 決策 | 選擇 | 犧牲了什麼 | 換取了什麼 |
|---|------|------|-----------|-----------|
| 1 | Runner 定位 | 核心元件 (`src/opentree/runner/`) | Core 體積增大 | 一個指令啟動，zero-config |
| 2 | CLI 整合 | `--mode` flag | 語義不如獨立子指令清晰 | 共享前置步驟，實作成本低 |
| 3 | 依賴管理 | Optional group (`pip install opentree[slack]`) | CLI 使用者需額外安裝 | 不強制安裝 slack-bolt |
| 4 | 認證模式 | SDK only（Socket Mode） | 不支援 xoxc/xoxd 環境 | 程式碼量減半 |
| 5 | DOGI 隔離 | 零 import，從頭撰寫 | 重複勞動約 1,000 行 | 零耦合，獨立部署 |
| 6 | 多使用者 | 單使用者架構 | 無法多人同 thread 獨立對話 | 大幅簡化 session 管理 |

### 2.3 Flow Simulation 發現的 CRITICAL Issues（實作前必須修復）

| Issue | 問題 | 解決方案 |
|-------|------|---------|
| #3 | `start_command` 使用靜態空白 PromptContext，Slack mode 需每次請求動態注入 | 新增 SlackBotRunner，每個 task 前用 Slack 事件構建 PromptContext |
| #4 | `collect_module_prompts` 的 `sys.modules` 並行操作有競爭條件 | 使用 thread-local key + lock |
| #11 | `prompt_hook.py` 在 bot process 內 exec 等同 RCE（可讀取 Slack Token） | 短期：限制路徑驗證 + chmod 700 |

---

## 三、實作歷程

### Phase 1: 核心循環（commit `460849d`）

以 TDD 方式分 4 batches 實作，每 batch 3 agents 並行（test writer + implementer + integration）。

| Batch | 元件 | 檔案 | 行數 | 測試數 |
|-------|------|------|------|--------|
| 1 | RunnerConfig + SlackAPI + Session | `config.py`, `slack_api.py`, `session.py` | ~530 | ~35 |
| 2 | ClaudeProcess + StreamParser | `claude_process.py`, `stream_parser.py` | ~562 | ~25+ |
| 3 | TaskQueue + Dispatcher | `task_queue.py`, `dispatcher.py` | ~649 | ~30+ |
| 4 | Receiver + Bot + CLI 整合 | `receiver.py`, `bot.py`, `cli/init.py` | ~498 | ~25+ |

**Phase 1 產出**：
- 新增 10 個 runner 檔案（`src/opentree/runner/`）
- 修改 `core/prompt.py`（thread-safe hook loading + path traversal guards）
- 修改 `cli/init.py`（新增 `--mode` 參數）
- 新增 `pyproject.toml` optional dependency `[slack]`
- **8,643 行變更**（29 files changed），含大量測試

### Phase 2: UX 強化（commit `5199b56` + `0037aa6`）

3 agents 並行開發三個獨立模組：

| Agent | 元件 | 檔案 | 行數 | 測試數 |
|-------|------|------|------|--------|
| 1 | ProgressReporter | `progress.py` | 270 | 36 |
| 2 | ThreadContext | `thread_context.py` | 131 | 34 |
| 3 | FileHandler | `file_handler.py` | 192 | 55+ |

Dispatcher 整合後的新流程：`progress.start` -> `download_files` -> `build_context` -> `Claude(callback)` -> `progress.complete` -> `cleanup`

**安全修復**（commit `0037aa6`，3 agents 並行 review 後修復）：
- SSRF 防護：URL hostname whitelist（files.slack.com only）
- Path traversal 防護：`_safe_filename` + `_safe_thread_dir`
- Memory DoS 防護：streaming download + 50 MB runtime size limit
- **270 行新增**（主要為安全測試）

### Phase 3: 運維（commit `2f22906`）

| 元件 | 檔案 | 行數 | 測試數 |
|------|------|------|--------|
| 日誌系統 | `logging_config.py` | 64 | 19 |
| run.sh Wrapper | `templates/run.sh` | 246 | — |
| Init 整合 | `cli/init.py` 修改 | 27 | — |

run.sh 功能：自動重啟、watchdog（heartbeat 超時 120s）、crash loop 保護（5 次/600s -> cooldown 300s）、DNS 檢查、PID file、signal 轉發。

---

## 四、Code Review 與安全修復歷程

### Phase 1 Review（1 code-reviewer agent）

**發現 3 HIGH + 4 MEDIUM + 4 LOW**：

| 嚴重度 | 問題 | 修復狀態 |
|--------|------|---------|
| HIGH | Admin command pipeline 是 dead code（dispatch 未呼叫 parse_message） | 已修復 |
| HIGH | `user_name` 永遠為空字串，memory 路徑錯誤 | 已修復 |
| HIGH | `user_name` 用於路徑未做 path traversal 驗證 | 已修復（使用 `_is_safe_name()`） |
| MEDIUM | `cleanup_expired()` 在 lock 外讀取 `_sessions` — TOCTOU race | 已修復 |
| MEDIUM | `stderr=subprocess.DEVNULL` 丟棄 Claude CLI 錯誤輸出 | 已修復 |
| MEDIUM | 未知 `--mode` 值靜默 fallthrough | 已修復 |
| MEDIUM | `Task` dataclass mutable 但跨 thread 共享 | 已修復 |

### Phase 2 Review（3 agents 並行）

| Agent | 角色 | 發現 |
|-------|------|------|
| code-reviewer | 功能正確性 | Phase 2 + Dispatcher 整合邏輯 |
| security-reviewer | 安全分析 | SSRF、path traversal、memory DoS |
| python-reviewer | Python 慣例 | 型別安全、error handling |

**關鍵安全發現**：
- **SSRF**：file_handler 的 download URL 未做 hostname 驗證，可被導向內網
- **Path Traversal**：thread_ts 用於建立暫存目錄，未驗證格式
- **Memory DoS**：大檔案下載無串流限制，可耗盡記憶體

所有安全問題在 commit `0037aa6` 中一次修復。

### Phase 3 Review（1 code-reviewer agent）

**發現 4 HIGH + 5 MEDIUM + 4 LOW**：

| 嚴重度 | 問題 | 修復狀態 |
|--------|------|---------|
| HIGH | run.sh `$BOT_CMD` 未引號 — 路徑含空格時崩潰 | 已修復（改用 bash array） |
| HIGH | `wait || true` 導致 exit_code 永遠為 0 — crash detection 完全失效 | 已修復 |
| HIGH | `setup_logging` 錯誤未處理 — exception 不進 log file | 已修復（加入 fallback） |
| HIGH | `_shutdown()` 重新讀取 config — signal-driven teardown 不應做 file I/O | 已修復（用快取值） |
| MEDIUM | `cleanup()` 未清 `BOT_PID` — double-wait 風險 | 已修復 |
| MEDIUM | `host` 指令在 minimal container 中不存在 | 已修復（改用 `getent hosts` + fallback） |
| MEDIUM | `handlers.clear()` 未 close — file descriptor 洩漏 | 已修復 |

> **Showstopper**：run.sh 的 `wait || true` bug 會讓整個 crash detection + 自動重啟機制失效。這是 code-reviewer agent 自行發現的（非人類指示），是整個 review 過程中最高價值的發現。

### Phase 2+3 合規性補齊（commit `7e4bd65`）

1. **3 background web research agents** 並行調研：
   - Slack Block Kit 進度更新模式
   - 檔案下載安全（SSRF 防護、temp 管理）
   - Bash 程序監督和 watchdog 模式

2. **1 flow-simulator agent**：31 場景模擬（通過 23、失敗 8）
   - 發現 `cleanup_temp` 路徑不一致（HIGH）
   - 確認 run.sh `wait || true` showstopper（HIGH）
   - 5 個 MEDIUM issues

3. **修復 7 issues**（commit `7e4bd65`）：
   - `file_handler.py`：`cleanup_temp()` 統一使用 `_safe_thread_dir()`
   - `progress.py`：`_push_progress()` 加入 exception handling
   - `logging_config.py`：`handlers.clear()` 前先 `close()`
   - `bot.py`：`_shutdown()` 使用 start() 時快取的 config
   - `dispatcher.py`：`reporter.start()` 失敗時 fallback send_message
   - `run.sh`：`wait || true` 改為 `set +e; wait; exit_code=$?; set -e`
   - `run.sh`：`$BOT_CMD` 改用 bash array + cleanup 加入 timeout

---

## 五、E2E 驗證階段（2026-03-31）

### 概述

在 Phase 1-3 合規性修復和 E2E 實測修復之後，進行完整的 E2E 驗證。透過 DOGI 在 Slack 中向 Bot_Walter 發送指令，驗證端到端流程。

### Batch 1：4 bugs 修復（commit `82eec96`）

首輪 E2E 測試發現 4 個問題並修復：

| Bug | 嚴重度 | 問題 | 修復方式 |
|-----|--------|------|----------|
| SlackAPI `_extract_data` | CRITICAL | `getattr` pattern 對 `SlackResponse` 無效 | `_extract_data()` helper，直接存取 `.data` dict |
| Bot-to-bot mention drop | CRITICAL | `bot_id` filter 丟棄所有 bot 訊息 | 允許帶有明確 @mention 的 bot 訊息 |
| Shutdown no auth | HIGH | 任何人都能 shutdown | `admin_users` config + auth check |
| Heartbeat before filters | MEDIUM | 只在 dispatch 寫 heartbeat | 移到 receiver filter 前 |

Status E2E 結果：**PASS**（回覆正確），但發現 dedup 問題——同一指令收到 2 則回覆。

### Batch 2：Dedup 修復（commits `54db6cc`, `72ecc6c`）

Dedup 問題根因：`slack_bolt` 對同一條 @mention 訊息同時觸發 `message` 和 `app_mention` 兩個 handler，在不同 thread 中並行處理，導致重複回覆。WSL2 跨檔案系統的 stale `.pyc` bytecache 加劇了問題。

**修復方案**：
1. **Single handler 架構**：移除 `app_mention` handler，只保留 `message` handler（commit `72ecc6c`）
2. **Layer 2 dedup**：`Dispatcher` 新增 `_dispatched_ts` set（with thread lock），攔截殘餘重複（commit `72ecc6c`）
3. **移除冗餘 heartbeat**：dispatcher 中的 heartbeat write 已由 receiver 涵蓋（commit `54db6cc`）

修復後全部測試通過：

| Test | 結果 |
|------|------|
| status command | PASS（單一回覆） |
| help command | PASS（單一回覆） |
| Claude reply | PASS（單一 Claude 回覆） |
| thread resume | PASS（session 保持） |
| dedup verification | PASS（無重複） |

### Code Review（Phase 4）

E2E 修復後進行 code review，發現並修復：

| 嚴重度 | 問題 | 修復 |
|--------|------|------|
| CRITICAL | status/help 標為 "admin" 但無 auth | 重新命名為 `_BOT_COMMANDS`，只有 shutdown 需 auth |
| HIGH | `dict()` fallback in `_extract_data` 遮蔽錯誤 | 移除，回傳 empty dict 僅用於 missing key |
| HIGH | Empty `admin_users` = 無人可 shutdown | 文件說明 + startup warning + validation |
| MEDIUM | Double heartbeat write | 移除 dispatcher 冗餘呼叫 |
| MEDIUM | admin_users 無 input validation | 新增 string/non-empty check |

完整 review log：`openspec/changes/20260331-e2e-verification/review-log.md`

### Agent 交互

E2E 驗證階段共約 8 次 agent 調用：

| Agent | 用途 |
|-------|------|
| explore | 分析現有程式碼結構 |
| flow-simulator | 31 場景模擬（21 pass / 10 fail） |
| tdd | 新增 29 個測試 |
| code-reviewer | E2E 修復後 review |
| sync (rsync) | 部署到測試環境 |

### 測試統計

- **總測試數**：824（+29 新增，原 795）
- **整體覆蓋率**：93%
- **新增測試**：E2E fixtures、dedup 測試、admin_users validation 測試

### Commits

| Hash | Message |
|------|---------|
| `82eec96` | fix: E2E 驗證 — SlackAPI parsing + bot-to-bot mention + shutdown auth + heartbeat |
| `54db6cc` | fix: 移除 dispatcher 冗餘 heartbeat write |
| `72ecc6c` | fix: cross-handler dedup — single handler + Layer 2 dispatcher dedup |

---

## 六、E2E 實機測試（早期）

### 環境準備

在實際 Slack workspace 中測試，使用真實的 Bot Token + App Token 連接 Socket Mode。

### 發現的 Runtime Bugs（commit `75915ce`）

#### Bug 1：SlackResponse dict() 轉換（4 處）

`slack_sdk` 的 `SlackResponse` 物件不支援直接 `dict()` 轉換。必須使用 `.data` 屬性取得底層 dict。影響 4 處：
- `slack_api.py` 的 `auth_test()` 回傳值
- `slack_api.py` 的 `get_thread_replies()` 回傳值
- `slack_api.py` 的 `send_message()` 回傳值
- `slack_api.py` 的 `update_message()` 回傳值

#### Bug 2：Claude CLI 參數不存在（3 個參數）

Claude CLI 實際上不支援以下參數：
- `--cwd` -> 應使用 subprocess 的 `cwd` 參數
- `--message` -> 應使用 `--prompt` 或 `-p`
- `--max-turns` -> 應使用 `--max-conversation-turns`

### 測試結果

| Test | 場景 | 結果 |
|------|------|------|
| Test 1 | @mention -> 收到 Claude 回覆 | PASS |
| Test 2 | Thread resume（同 thread 第二則訊息） | PASS |

---

## 七、測試覆蓋率

### 總覽

- **總測試數**：796（含 1 xfailed）
- **通過數**：795 passed, 1 xfailed
- **整體覆蓋率**：93%
- **原始碼行數**：2,468 行

### 各模組覆蓋率

| 模組 | 行數 | 未覆蓋 | 覆蓋率 |
|------|------|--------|--------|
| `runner/config.py` | 33 | 0 | 100% |
| `runner/__init__.py` | 1 | 0 | 100% |
| `runner/slack_api.py` | 120 | 1 | 99% |
| `runner/file_handler.py` | 112 | 2 | 98% |
| `runner/thread_context.py` | 52 | 1 | 98% |
| `runner/task_queue.py` | 121 | 3 | 98% |
| `runner/bot.py` | 100 | 4 | 96% |
| `runner/receiver.py` | 97 | 4 | 96% |
| `runner/session.py` | 78 | 3 | 96% |
| `runner/progress.py` | 93 | 5 | 95% |
| `runner/logging_config.py` | 31 | 2 | 94% |
| `runner/claude_process.py` | 124 | 9 | 93% |
| `runner/stream_parser.py` | 120 | 10 | 92% |
| `runner/dispatcher.py` | 148 | 14 | 91% |
| **Runner 小計** | **1,230** | **58** | **95%** |

| 模組 | 行數 | 未覆蓋 | 覆蓋率 |
|------|------|--------|--------|
| `core/config.py` | 17 | 0 | 100% |
| `core/placeholders.py` | 45 | 0 | 100% |
| `manifest/` | 178 | 2 | 99% |
| `registry/` | 138 | 5 | 96% |
| `generator/settings.py` | 85 | 6 | 93% |
| `cli/main.py` | 12 | 1 | 92% |
| `core/prompt.py` | 121 | 13 | 89% |
| `generator/symlinks.py` | 151 | 17 | 89% |
| `cli/init.py` | 166 | 26 | 84% |
| `cli/module.py` | 240 | 49 | 80% |
| `generator/claude_md.py` | 62 | 1 | 98% |
| **非 Runner 小計** | **1,238** | **120** | **90%** |

---

## 八、Agent 交互與決策歷程

### 使用的 Agent 類型統計

| Agent Type | 次數 | 用途 |
|------------|------|------|
| **planner** | 1 | Phase 1 完整實作計畫 |
| **architect** | 1 | 架構分析、OpenTree vs DOGI trade-off |
| **flow-simulator** | 3 | Phase 1（41 場景）、Phase 2+3（31 場景）、Phase 1 前期（flow-simulation.md） |
| **code-reviewer** | 3 | Phase 1 review、Phase 3 review、Phase 2+3 合併 review |
| **security-reviewer** | 1 | Phase 2 安全分析（SSRF、path traversal、memory DoS） |
| **python-reviewer** | 1 | Phase 2 Python 慣例檢查 |
| **web-research** (background) | 3 | Slack Block Kit、檔案安全、watchdog 模式 |
| **TDD agents** (per batch) | ~12 | 4 batches x 3 agents（test writer + implementer + integrator） |
| **合計** | **~25** | |

### 關鍵 Agent 自行發現的問題（非人類指示）

1. **run.sh `wait || true` showstopper**：code-reviewer agent 在 Phase 3 review 中自行發現。`|| true` 讓 `exit_code` 永遠為 0，整個 crash detection 機制形同虛設。這是最高價值的 agent 發現。

2. **admin command dead code**：code-reviewer agent 在 Phase 1 review 中發現 `parse_message()` 和 `_handle_admin_command()` 存在但從未被 `dispatch()` 呼叫。`shutdown` 指令完全無效。

3. **`user_name` 永遠為空字串**：code-reviewer agent 追蹤到 `Receiver._build_task()` 設定 `user_name=""`，而 runner 從未 resolve 它，導致所有使用者共享同一個 memory 路徑。

4. **PromptContext 靜態空白**：flow-simulator agent 在 41 場景模擬中發現 `start_command` 只組裝一次空白 PromptContext，Slack mode 每個訊息需要不同的動態 context。

5. **SSRF via file download URL**：security-reviewer agent 發現 `file_handler.py` 未驗證 download URL hostname，攻擊者可透過 Slack file sharing 機制導向內網 URL。

### Agent 間的交叉發現

- **Phase 1 flow-simulator + code-reviewer** 同時指出 `user_name` 相關問題（#13 prompt injection + #14 path traversal + review 的 empty user_name），三個發現互相關聯
- **Phase 3 code-reviewer + Phase 2+3 flow-simulator** 獨立確認 run.sh `wait || true` bug 的嚴重性，前者從程式碼分析、後者從場景模擬
- **Planner + Architect** 對 CLI 整合方式有分歧，但對「Runner 應為核心元件」和「SDK only」達成一致

---

## 九、Commit 歷史

| Hash | Message | 變更規模 |
|------|---------|---------|
| `8de60af` | docs: OpenTree 初始架構規劃 | 5 files, +562 |
| `0e516f5` | docs: DOGI -> OpenTree 模組拆分遷移對照表 | 1 file, +272 |
| `be19aaf` | feat: Phase 1 完成 — Manifest Validation & Registry 系統 | 47 files, +5,124 |
| `dc40d9a` | fix: 推演驗證修正 — 3 輪推演循環至零問題 | 8 files, +279/-157 |
| `b9ceb7e` | feat: Phase 2 完成 — Module Loading Runtime 系統 | 26 files, +4,000/-25 |
| `e923f12` | feat: Phase 3 完成 — 模組內容遷移 + PlaceholderEngine | 45 files, +2,731/-17 |
| `b3b44b6` | fix: Option C — admin_channel 混合策略（推演驗證通過） | 2 files, +2/-3 |
| `9907e5b` | feat: Phase 4-6 完成 — prompt_hook + init/start + E2E 驗證 | 13 files, +1,686/-17 |
| `6ae3217` | docs: Phase 1-6 收尾 — 完整進度記錄 + handoff 更新 | 4 files, +276/-89 |
| `f8e2fd6` | docs: handoff 加入新舊 thread 雙向連結 | 1 file, +3/-2 |
| `460849d` | **feat: Slack Bot Runner — 獨立 runtime 核心循環（Phase 1）** | 29 files, +8,643/-16 |
| `5199b56` | **feat: Phase 2 UX 強化 — 進度回報、thread 上下文、附件處理** | 10 files, +2,659/-44 |
| `0037aa6` | **fix: Phase 2 安全修復 — SSRF、path traversal、memory DoS** | 6 files, +270/-81 |
| `2f22906` | **feat: Phase 3 運維 — 日誌系統 + run.sh wrapper + init 整合** | 5 files, +684/-1 |
| `7e4bd65` | **fix: Phase 2+3 合規性補齊 — simulation + review 發現的 HIGH issues 修復** | 18 files, +2,815/-32 |
| `75915ce` | **fix: E2E 實測修復 — SlackResponse 轉換 + Claude CLI 參數** | 3 files, +34/-28 |
| `82eec96` | **fix: E2E 驗證 — SlackAPI parsing + bot-to-bot mention + shutdown auth + heartbeat** | — |
| `54db6cc` | **fix: 移除 dispatcher 冗餘 heartbeat write** | — |
| `72ecc6c` | **fix: cross-handler dedup — single handler + Layer 2 dispatcher dedup** | — |

> **Bot Runner 相關**（`460849d` ~ `72ecc6c`）：9 commits

---

## 十、OpenSpec 文件清單

### 20260329-initial-architecture/（初始架構）

| 文件 | 內容摘要 |
|------|---------|
| `proposal.md` | OpenTree 專案提案：從 DOGI 拆分為模組化框架 |
| `research.md` | 模組系統候選方案調研（JSON Schema vs TOML、symlink vs copy 等） |
| `decisions.md` | 6 個架構決策（模組格式、安裝方式、設定管理等） |
| `migration-map.md` | DOGI -> OpenTree 模組拆分遷移對照表（10 模組對應） |

### 20260329-module-loading/（Phase 1-6 模組系統）

| 文件 | 內容摘要 |
|------|---------|
| `design.md` | 完整技術設計（1,001 行）：manifest schema、registry、symlink、settings |
| `execution-plan.md` | 6 Phase 執行計畫 |
| `flow-simulation.md` | 早期流程模擬 |
| `handoff.md` | Session handoff 記錄（含新舊 thread 雙向連結） |
| `progress.md` | Phase 1-6 詳細進度記錄 |

### 20260329-phase2-runtime/（Phase 2 Runtime）

| 文件 | 內容摘要 |
|------|---------|
| `simulation-report.md` | Module Loading Runtime 模擬報告 |
| `web-research-*.md` (5 files) | Claude Code CLI、隔離機制、settings merge、symlink、Typer 調研 |

### 20260329-phase3-migration/

| 文件 | 內容摘要 |
|------|---------|
| `proposal.md` | Phase 3 模組內容遷移提案 |

### 20260329-phase4-runtime/

| 文件 | 內容摘要 |
|------|---------|
| `research.md` | Phase 4 prompt_hook 系統調研 |

### 20260330-slack-bot-runner/（Bot Runner Phase 1 核心）

| 文件 | 內容摘要 |
|------|---------|
| `proposal.md` | Bot Runner 需求分析 + 設計決策 + 3 Phase 實作計畫（253 行） |
| `research.md` | 3 agent 並行調研結果 + 41 場景模擬摘要 + 架構 trade-off |
| `simulation-report.md` | 41 場景完整模擬報告（CRITICAL/HIGH/MEDIUM issues） |
| `review-log.md` | Phase 1 code review（3 HIGH + 4 MEDIUM + 4 LOW） |
| `session-handoff-plan.md` | Session handoff 計畫 |

### 20260330-phase2-ux/（Bot Runner Phase 2 UX）

| 文件 | 內容摘要 |
|------|---------|
| `proposal.md` | Phase 2 需求（progress + thread_context + file_handler） |
| `research.md` | Slack Block Kit、Thread 上下文策略、附件安全調研 |
| `codebase-analysis.md` | Phase 2 程式碼分析 |
| `simulation-report.md` | Phase 2+3 合併模擬（31 場景，8 失敗） |
| `web-research-slack-progress.md` | Slack Block Kit 進度更新模式（600 行） |
| `web-research-file-security.md` | 檔案下載安全調研（551 行） |

### 20260330-phase3-ops/（Bot Runner Phase 3 運維）

| 文件 | 內容摘要 |
|------|---------|
| `proposal.md` | Phase 3 需求（logging + run.sh + init 整合） |
| `research.md` | 日誌系統、Process supervision、Crash loop 保護調研 |
| `review-log.md` | Phase 3 code review（4 HIGH + 5 MEDIUM + 4 LOW，含 run.sh showstopper） |
| `web-research-watchdog.md` | Bash 程序監督和 watchdog 模式調研（838 行） |

### 20260331-e2e-verification/（E2E 驗證）

| 文件 | 內容摘要 |
|------|---------|
| `simulation-report.md` | 31 場景模擬報告（21 pass / 10 fail，10 issues all fixed） |
| `review-log.md` | Phase 4 code review（1 CRITICAL + 2 HIGH + 2 MEDIUM + 3 LOW） |
| `test-plan.md` | E2E 測試計畫 |

---

## 附錄：完整 OpenSpec 檔案路徑

```
openspec/changes/20260329-initial-architecture/decisions.md
openspec/changes/20260329-initial-architecture/migration-map.md
openspec/changes/20260329-initial-architecture/proposal.md
openspec/changes/20260329-initial-architecture/research.md
openspec/changes/20260329-module-loading/design.md
openspec/changes/20260329-module-loading/execution-plan.md
openspec/changes/20260329-module-loading/flow-simulation.md
openspec/changes/20260329-module-loading/handoff.md
openspec/changes/20260329-module-loading/progress.md
openspec/changes/20260329-phase2-runtime/simulation-report.md
openspec/changes/20260329-phase2-runtime/web-research-claude-code.md
openspec/changes/20260329-phase2-runtime/web-research-isolation.md
openspec/changes/20260329-phase2-runtime/web-research-settings-merge.md
openspec/changes/20260329-phase2-runtime/web-research-symlink.md
openspec/changes/20260329-phase2-runtime/web-research-typer.md
openspec/changes/20260329-phase3-migration/proposal.md
openspec/changes/20260329-phase4-runtime/research.md
openspec/changes/20260330-phase2-ux/codebase-analysis.md
openspec/changes/20260330-phase2-ux/proposal.md
openspec/changes/20260330-phase2-ux/research.md
openspec/changes/20260330-phase2-ux/simulation-report.md
openspec/changes/20260330-phase2-ux/web-research-file-security.md
openspec/changes/20260330-phase2-ux/web-research-slack-progress.md
openspec/changes/20260330-phase3-ops/proposal.md
openspec/changes/20260330-phase3-ops/research.md
openspec/changes/20260330-phase3-ops/review-log.md
openspec/changes/20260330-phase3-ops/web-research-watchdog.md
openspec/changes/20260330-slack-bot-runner/proposal.md
openspec/changes/20260330-slack-bot-runner/research.md
openspec/changes/20260330-slack-bot-runner/review-log.md
openspec/changes/20260330-slack-bot-runner/session-handoff-plan.md
openspec/changes/20260330-slack-bot-runner/simulation-report.md
openspec/changes/20260331-e2e-verification/simulation-report.md
openspec/changes/20260331-e2e-verification/review-log.md
openspec/changes/20260331-e2e-verification/test-plan.md
```
