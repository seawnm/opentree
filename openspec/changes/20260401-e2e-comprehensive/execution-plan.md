# E2E Comprehensive Test Plan — Execution Blueprint

> **建立日期**: 2026-04-01
> **目標**: 補齊 OpenTree E2E 測試案例，對齊 DOGI 全功能，驗證模組化架構設計
> **狀態**: ✅ 測試碼完成，E2E 執行待 Loop 5
> **測試頻道**: ai-room (`C0AJ63F1T9P`)
> **決策紀錄**:
> - 測試頻道: ai-room（已清除 Ralph 監控設定）
> - 批次順序: 維持原案（核心 → 檔案/記憶 → 資安 → 擴充 → UX）
> - Bug 處理: 全部用 feature-workflow 修復，不留後續
> - 自動連續: Batch 1-3 自動連續執行，完成後回報

## 1. 任務總覽

### 1.1 現有 E2E 覆蓋（v0.2.0）

| 測試 ID | 場景 | 狀態 |
|---------|------|------|
| A0 | Bot 進程健康檢查 | ✅ 已有 |
| A1 | Config 隔離驗證 | ✅ 已有 |
| A2 | Admin 指令（status/help） | ✅ 已有 |
| A5 | 並行請求 | ✅ 已有 |
| A6 | Crash recovery wrapper | ✅ 已有 |
| A7 | 多輪對話上下文 | ✅ 已有 |

### 1.2 待補齊場景（對齊 DOGI）

| 批次 | 測試 ID | 場景 | 預估時間 | 對應模組 |
|------|---------|------|----------|----------|
| **Batch 1** | B1 | 思維訊息顯示（Progress/Thinking） | 15 min | slack, core |
| | B2 | 工具追蹤時間軸顯示（Tool Tracker） | 10 min | core |
| | B3 | Token 統計與完成摘要 | 10 min | core |
| **Batch 2** | B4 | 檔案下載/上傳完整流程 | 15 min | slack |
| | B5 | 記憶萃取與持久化 | 15 min | memory |
| | B6 | Session 管理（resume/expire/isolation） | 15 min | core |
| **Batch 3** | C1 | 安全輸入過濾 | 10 min | guardrail |
| | C2 | 輸出過濾（API Key/JWT 遮蔽） | 10 min | guardrail |
| | C3 | 路徑遍歷防護 | 10 min | guardrail |
| | C4 | 權限隔離（admin vs restricted） | 15 min | guardrail, core |
| **Batch 4** | D1 | 排程任務建立/執行 | 15 min | scheduler |
| | D2 | 需求收集流程 | 15 min | requirement |
| | D3 | DM 處理 | 10 min | slack |
| **Batch 5** | E1 | UX 體驗驗證（回應速度/錯誤訊息） | 15 min | slack, core |
| | E2 | Queue 回饋（排隊訊息） | 10 min | core |
| | E3 | 錯誤復原鏈（session 失敗 → retry → fallback） | 15 min | core |
| | E4 | Circuit Breaker 行為 | 10 min | core |

**總計**: ~5 批次，每批 25-45 分鐘，共約 3.5 小時

---

## 2. Agent Team 架構

### 2.1 Agent 角色分配

| Agent | 角色 | 負責範圍 | 並行規則 |
|-------|------|----------|----------|
| **Architect** | 測試架構師 | 設計測試案例、定義驗證標準、規劃 fixture | 獨立執行 |
| **TestWriter-Core** | 核心功能測試 | B1-B6、E1-E4 測試碼撰寫 | 最多 2 並行 |
| **TestWriter-Security** | 資安測試 | C1-C4 測試碼撰寫 | 最多 2 並行 |
| **TestWriter-Extension** | 擴充模組測試 | D1-D3 測試碼撰寫 | 最多 2 並行 |
| **Reviewer** | 程式碼審查 | 每批完成後 review | 與 Writer 交替 |
| **Runner** | E2E 執行 | 在 ai-room 執行測試 | 獨立執行 |

### 2.2 並行約束

- **同時最多 2 個 agent**（記憶體限制）
- **每批次流程**: Writer(s) → Reviewer → Runner（序列化）
- **批次間**: 回報結果 → 使用者確認 → 下一批

---

## 3. 測試環境

### 3.1 測試通道

- **測試頻道**: ai-room（`C0AJ63F1T9P`）
- **測試對象**: Bot Walter（`U0APZ9MR997`）
- **訊息發送**: DOGI message-tool（`/mnt/e/develop/mydev/slack-bot`）
- **結果讀取**: DOGI slack-query-tool
- **日誌檢查**: Bot Walter logs（`/mnt/e/develop/mydev/project/trees/bot_walter/data/logs/`）

### 3.2 工具路徑

```bash
# 發送測試訊息
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool send \
  --channel C0AJ63F1T9P \
  --text "<@U0APZ9MR997> 測試訊息"

# 讀取回覆
uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool read-thread \
  --channel C0AJ63F1T9P \
  --thread-ts <ts> \
  --limit 50

# 查看 Bot 日誌
grep "pattern" /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/$(date +%Y-%m-%d).log
```

---

## 4. 分批執行計畫

### Batch 1: 思維訊息與進度顯示（~35 min）

**Agent 分配**: Architect + TestWriter-Core（2 並行）

**B1 — 思維訊息顯示**
- 發送需要 Claude 深度思考的問題
- 驗證 Slack 收到 Block Kit 進度訊息
- 驗證 phase emoji 正確（🧠 thinking → 🔨 tool_use → ✍️ generating）
- 驗證 spinner 動畫更新（至少 2 次更新）
- 驗證完成後進度訊息變為最終回覆

**B2 — 工具追蹤時間軸**
- 發送觸發工具使用的請求（如「讀取某檔案」）
- 驗證完成訊息中包含工具時間軸
- 驗證時間軸 icon 正確（📖 read、💻 bash、✏️ edit 等）
- 驗證聚合顯示（多次同類工具合併為一行）

**B3 — Token 統計與完成摘要**
- 驗證完成訊息包含 📥/📤 token 統計
- 驗證耗時顯示格式正確
- 驗證長回覆自動分段（>3000 字元）

### Batch 2: 檔案/記憶/Session（~45 min）

**Agent 分配**: TestWriter-Core + TestWriter-Extension（2 並行）

**B4 — 檔案處理**
- 上傳測試檔案到 thread → 驗證 bot 下載並處理
- 驗證 SSRF 防護（內網 URL 拒絕）
- 驗證檔案大小限制（超限回報錯誤）
- 驗證 temp 檔清理

**B5 — 記憶萃取**
- 發送含「記住」指令的訊息
- 驗證 memory.md 更新
- 驗證後續對話引用記憶
- 驗證 EN/ZH 模式偵測

**B6 — Session 管理**
- 驗證 thread 內多輪 session resume
- 驗證不同 thread 有獨立 session
- 驗證同一 thread 不同使用者的 session 隔離
- 驗證 session 過期清理

### Batch 3: 資安防護（~45 min）

**Agent 分配**: TestWriter-Security + Reviewer（2 並行）

**C1 — 輸入過濾**
- Prompt injection 嘗試（「忽略所有指令...」）
- Command injection 嘗試（`$(rm -rf /)` 在訊息中）
- 超長輸入處理
- 驗證過濾器回報安全錯誤訊息

**C2 — 輸出過濾**
- 驗證回覆中 API key 模式（sk-、xoxb-）被遮蔽
- 驗證 JWT token 被遮蔽
- 驗證 .env 內容不洩漏

**C3 — 路徑遍歷**
- 驗證 prompt hook 載入時路徑檢查
- 驗證檔案下載時 URL 驗證
- 驗證 workspace 隔離（不能跨 workspace 存取）

**C4 — 權限隔離**
- Admin 使用者可執行 admin 指令
- Restricted 使用者的 admin 指令被拒絕
- Restricted 使用者的 Bash 存取被限制
- 驗證 settings.json 中的 allowedTools 生效

### Batch 4: 擴充模組（~40 min）

**Agent 分配**: TestWriter-Extension + Runner（2 並行）

**D1 — 排程任務**
- 建立一次性排程（delay 模式）
- 驗證排程觸發並回覆到正確 thread
- 驗證排程列表/刪除
- 驗證 cron 排程格式正確

**D2 — 需求收集**
- 發送功能需求訊息
- 驗證 requirement-tool create 被呼叫
- 驗證需求記錄包含 raw-text
- 驗證狀態流轉

**D3 — DM 處理**
- 驗證 DM 觸發正確 workspace
- 驗證 DM 無需 @mention 前綴
- 驗證 DM session 獨立

### Batch 5: UX 與韌性（~40 min）

**Agent 分配**: TestWriter-Core + Reviewer（2 並行）

**E1 — UX 體驗**
- 驗證首次回應延遲 < 5s（initial ack）
- 驗證進度更新間隔 ~10s
- 驗證錯誤訊息友善且有引導
- 驗證空回覆的 fallback 訊息

**E2 — Queue 回饋**
- 同時發送超過並行上限的請求
- 驗證排隊訊息包含排隊位置
- 驗證佇列中的任務依序執行

**E3 — 錯誤復原鏈**
- 模擬 session resume 失敗
- 驗證自動清除 session → 重試
- 驗證 prompt 過長 → fallback 到最新訊息
- 驗證最終失敗的用戶回報

**E4 — Circuit Breaker**
- 驗證連續失敗 5 次後進入 OPEN 狀態
- 驗證 OPEN 狀態拒絕新請求並回報
- 驗證 HALF_OPEN 恢復機制

---

## 5. 測試碼規範

### 5.1 檔案結構

```
tests/e2e/
├── conftest.py                    # 共用 fixture（已存在）
├── test_e2e_precheck.py           # ✅ 已有
├── test_e2e_admin.py              # ✅ 已有
├── test_e2e_conversation.py       # ✅ 已有
├── test_e2e_concurrency.py        # ✅ 已有
├── test_e2e_wrapper.py            # ✅ 已有
├── test_e2e_progress.py           # 🆕 B1-B3: 思維/進度/工具追蹤
├── test_e2e_file_handling.py      # 🆕 B4: 檔案處理
├── test_e2e_memory.py             # 🆕 B5: 記憶萃取
├── test_e2e_session.py            # 🆕 B6: Session 管理
├── test_e2e_security.py           # 🆕 C1-C4: 資安防護
├── test_e2e_extensions.py         # 🆕 D1-D3: 擴充模組
├── test_e2e_ux_resilience.py      # 🆕 E1-E4: UX 與韌性
└── fixtures/
    ├── test_files/                # 測試用檔案（小圖片、文字檔）
    └── security_payloads.py       # 安全測試 payload 集
```

### 5.2 測試碼風格

```python
@pytest.mark.e2e
@pytest.mark.skipif(not bot_alive(), reason="Bot not running")
class TestProgressDisplay:
    """B1: 思維訊息顯示驗證"""

    def test_thinking_phase_shown(self, send_message, wait_for_reply, read_thread):
        """發送深度思考問題，驗證 thinking phase emoji 出現"""
        # Arrange: 發送需要思考的問題
        ts = send_message("<@BOT> 請分析 OpenTree 的模組架構優缺點")

        # Act: 等待 15 秒讓 progress message 更新
        time.sleep(15)
        thread = read_thread(ts)

        # Assert: 中間更新包含 thinking phase
        progress_msgs = [m for m in thread if m['user'] == BOT_ID and '🧠' in m.get('text', '')]
        assert len(progress_msgs) > 0, "Should show thinking phase emoji"

        # Wait for final reply
        reply = wait_for_reply(ts, timeout=120)
        assert reply is not None
```

### 5.3 驗證標準

每個測試案例必須驗證：
1. **功能正確性** — 預期行為發生
2. **模組化合規** — 功能由正確模組提供，不依賴核心硬編碼
3. **錯誤處理** — 異常情況有明確回報
4. **清理完整** — temp 檔案/session 正確清理

---

## 6. 發現問題的處理流程

### 6.1 Bug 分級

| 等級 | 定義 | 處理方式 |
|------|------|----------|
| **CRITICAL** | 功能完全無法使用 | 立即修復，使用 feature-workflow |
| **HIGH** | 功能有缺陷但可 workaround | 當批次修復 |
| **MEDIUM** | 非預期行為但不影響核心流程 | 立即修復，使用 feature-workflow |
| **LOW** | 改善建議 | 立即修復，使用 feature-workflow |

### 6.2 修復流程

```
發現問題 → 記錄到 issues.md → 分級
  ├─ CRITICAL/HIGH → feature-workflow skill（multi-agent）
  │   ├─ Agent 1: 分析根因 + 設計修復方案
  │   └─ Agent 2: 實作修復 + 回歸測試
  └─ MEDIUM/LOW → 記錄，下批次或下 session 處理
```

### 6.3 文件記錄

- **每批次結果** → 更新 `batch-results.md`
- **Agent 發現** → 更新 `agent-findings.md`
- **交互決策** → 更新 `decisions.md`
- **最終報告** → 更新 `final-report.md`

---

## 7. 進度追蹤

### 7.1 批次狀態表

| 批次 | 狀態 | 測試碼 | Review | 修復 | 備註 |
|------|------|--------|--------|------|------|
| Batch 1 | ✅ 完成 | 10 tests | 2C+6H+5M 已修 | 全修 | progress/tool/token |
| Batch 2 | ✅ 完成 | 10 tests | 共用 review | 全修 | file/memory/session |
| Batch 3 | ✅ 完成 | 20 tests | — | — | security C1-C4 |
| Batch 4 | ✅ 完成 | 7 tests | 1C+3H+2M+2L 已修 | 全修 | extensions D1-D3 |
| Batch 5 | ✅ 完成 | 12 tests | 3H+4M+2L 已修 | 全修 | UX/resilience E1-E4 |

### 7.2 測試覆蓋率目標

| 模組 | 目前覆蓋 | 目標覆蓋 | E2E 案例數 |
|------|----------|----------|------------|
| runner/progress.py | 93% | ≥95% | 3 (B1-B3) |
| runner/tool_tracker.py | 93% | ≥95% | 1 (B2) |
| runner/file_handler.py | 93% | ≥95% | 1 (B4) |
| runner/memory_extractor.py | 93% | ≥95% | 1 (B5) |
| runner/session.py | 93% | ≥95% | 1 (B6) |
| guardrail module | N/A | ≥90% | 4 (C1-C4) |
| scheduler module | N/A | ≥80% | 1 (D1) |
| requirement module | N/A | ≥80% | 1 (D2) |
| runner/dispatcher.py | 93% | ≥95% | 3 (E1-E3) |
| runner/circuit_breaker.py | 93% | ≥95% | 1 (E4) |

---

## 8. 各 Agent 的優化 Prompt

### 8.1 Architect Agent Prompt

```
你是 OpenTree 專案的測試架構師。你的任務是為 Batch {N} 設計 E2E 測試案例。

## 背景
OpenTree 是模組化 Slack bot 框架（v0.2.0），使用 Claude CLI 驅動，
支援擴充套件機制（manifest-based modules）。

## 專案路徑
- OpenTree 原始碼: /mnt/e/develop/mydev/opentree/
- 現有 E2E 測試: /mnt/e/develop/mydev/opentree/tests/e2e/
- 測試計畫: /mnt/e/develop/mydev/opentree/openspec/changes/20260401-e2e-comprehensive/

## 你的任務
1. 讀取 execution-plan.md 的 Batch {N} 描述
2. 讀取現有 conftest.py 了解 fixture 架構
3. 讀取對應的 source code 了解待測功能
4. 設計測試案例規格（輸入、預期輸出、驗證點）
5. 將規格寫入 test-specs/batch-{N}.md

## 設計原則
- 每個測試案例獨立可執行
- 驗證功能由正確模組提供（非核心硬編碼）
- 包含正向和負向測試
- 考慮 race condition 和 timing 問題

## 約束
- 不修改任何原始碼
- 不執行測試（由 Runner 執行）
- 產出物僅為測試規格文件
```

### 8.2 TestWriter Agent Prompt

```
你是 OpenTree 專案的測試工程師。你的任務是根據測試規格撰寫 E2E 測試碼。

## 背景
OpenTree 使用 pytest + 自訂 fixture 進行 E2E 測試。
測試透過 DOGI message-tool 發送訊息到 Slack，再用 slack-query-tool 驗證回覆。

## 專案路徑
- OpenTree: /mnt/e/develop/mydev/opentree/
- DOGI 工具: /mnt/e/develop/mydev/slack-bot/
- 測試規格: openspec/changes/20260401-e2e-comprehensive/test-specs/batch-{N}.md
- 現有 fixture: tests/e2e/conftest.py

## 測試環境
- 頻道: ai-room (C0AJ63F1T9P)
- Bot: Walter (U0APZ9MR997)
- 訊息工具: uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.message_tool
- 查詢工具: uv run --directory /mnt/e/develop/mydev/slack-bot python -m scripts.tools.slack_query_tool

## 你的任務
1. 讀取 batch-{N}.md 測試規格
2. 讀取 conftest.py 了解可用 fixture
3. 撰寫測試碼到 tests/e2e/test_e2e_{module}.py
4. 確保每個 test function 有清楚的 docstring
5. 需要新 fixture 時，追加到 conftest.py

## 程式碼風格
- @pytest.mark.e2e decorator
- Class-based test grouping
- 明確的 Arrange-Act-Assert 結構
- 適當的 timeout 和 retry 處理
- 中文 docstring 描述測試意圖

## 約束
- 不修改 OpenTree source code
- 不直接執行測試
- 測試碼需可在無 bot 環境下 skip（conftest 的 bot_alive check）
```

### 8.3 Security TestWriter Agent Prompt

```
你是資安測試專家，負責 OpenTree 的安全性 E2E 測試。

## 背景
OpenTree 是模組化 Slack bot，使用 guardrail module 提供安全防護，
包含輸入過濾、輸出遮蔽、路徑遍歷防護、權限隔離。

## 專案路徑
- Guardrail module: /mnt/e/develop/mydev/opentree/modules/guardrail/
- 安全相關 source: src/opentree/runner/ 的各檔案
- DOGI 的安全實作參考: /mnt/e/develop/mydev/slack-bot/ 的 security_filter.py, path_validator.py

## 你的任務
1. 分析 OpenTree 的安全防護機制
2. 對照 DOGI 的安全實作，找出 OpenTree 可能的差距
3. 設計 OWASP Top 10 相關測試案例
4. 撰寫安全測試碼到 tests/e2e/test_e2e_security.py
5. 記錄發現到 agent-findings.md

## 測試重點
- Prompt Injection（直接/間接）
- Command Injection（透過 Bash tool）
- Path Traversal（檔案操作）
- Information Disclosure（錯誤訊息、API key 洩漏）
- Broken Access Control（權限繞過）
- SSRF（內網 URL 存取）

## OWASP 對照
每個測試案例標注對應的 OWASP 類別和風險等級。

## 約束
- 安全 payload 不得造成實際損害（read-only 驗證）
- 敏感 payload 存放在 fixtures/security_payloads.py
```

### 8.4 Reviewer Agent Prompt

```
你是資深程式碼審查員，負責審查 OpenTree E2E 測試碼。

## 審查重點
1. **測試品質**: 驗證點是否充分、是否有遺漏場景
2. **模組化合規**: 測試是否驗證了功能來自正確的 module
3. **穩定性**: 是否有 flaky test 風險（timing、race condition）
4. **安全性**: 測試本身是否安全（不洩漏 token、不造成損害）
5. **可維護性**: 程式碼是否清楚、fixture 是否適當

## 審查流程
1. 讀取測試碼
2. 讀取對應的 source code 驗證測試邏輯
3. 對照 DOGI 的同功能實作，檢查是否有遺漏
4. 輸出審查報告到 review-log.md

## 報告格式
每個 finding 標注：
- 等級: CRITICAL / HIGH / MEDIUM / LOW
- 檔案和行數
- 問題描述
- 建議修復方式
```

### 8.5 Runner Agent Prompt

```
你是 E2E 測試執行員，負責在 ai-room 執行測試並收集結果。

## 測試環境
- 測試頻道: ai-room (C0AJ63F1T9P)
- Bot Walter: U0APZ9MR997
- Bot Walter 日誌: /mnt/e/develop/mydev/project/trees/bot_walter/data/logs/

## 執行流程
1. 確認 Bot Walter 存活（heartbeat + pgrep）
2. 執行指定批次的 pytest:
   cd /mnt/e/develop/mydev/opentree && uv run pytest tests/e2e/test_e2e_{module}.py -v --tb=long -x 2>&1
3. 收集測試結果
4. 若有失敗，擷取 bot 日誌中的相關 error
5. 更新 batch-results.md

## 結果格式
- 通過: ✅ test_name — 描述
- 失敗: ❌ test_name — 錯誤摘要
- 跳過: ⏭️ test_name — 原因

## 約束
- 執行前確認 bot 存活
- 每個批次完成後等待 30 秒讓 bot 恢復
- 收集覆蓋率: uv run pytest --cov=src/opentree --cov-report=term-missing
```

---

## 9. 回報格式

### 最終報告結構（final-report.md）

```markdown
# E2E Comprehensive Test Report

## 執行摘要
- 總測試案例: N
- 通過: N (X%)
- 失敗: N
- 跳過: N

## Agent 交互紀錄
### 發現摘要
- Agent X 在 Batch Y 發現...
- Agent Z 建議...

### 決策歷程
- 決策 1: 因為 X，選擇 Y 而非 Z
- 決策 2: ...

## 批次結果
### Batch 1: ...
### Batch 2: ...
...

## 測試覆蓋率
(覆蓋率表)

## 開放問題
(待解決的 issue list)
```
