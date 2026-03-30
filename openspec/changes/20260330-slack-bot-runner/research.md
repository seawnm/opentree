# Research: OpenTree 獨立 Slack Bot Runner

> 建立日期：2026-03-30

## 調研背景

OpenTree 目前已完成模組系統（Phase 1-6），但缺少獨立的 Slack bot runtime。需要評估如何在不引用 DOGI 程式碼的前提下，建立一個精簡的 bot runner。

本調研由三個並行 agent 執行：
1. **Planner Agent** — 完整實作計畫
2. **Architect Agent** — 架構分析與決策 trade-off
3. **Flow Simulator Agent** — 41 個場景的流程模擬

---

## 候選方案

### 類別 1：Runner 定位

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 核心元件 (`src/opentree/runner/`) | ✅ 採用 | — |
| B. 可選模組 (`modules/slack-runner/`) | 不可行 | 模組系統只能宣告 rules（.md），無法包含可執行 Python；runner 需 import OpenTree 內部模組，放 modules/ 會造成反向依賴 |
| C. 獨立套件 (`opentree-runner`) | 不適合 | 增加分發和版本同步複雜度，目前無此需求 |

### 類別 2：CLI 整合方式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. `--mode` flag (`opentree start --mode slack`) | ✅ 採用 | 共享前置步驟（config/registry/prompt），差異只在最後一步 |
| B. 獨立子指令 (`opentree serve`) | 可行替代 | 語義清晰但增加維護成本；Architect agent 傾向此方案，Planner agent 傾向 A |
| C. 環境自動偵測 | 不適合 | 隱式行為不利除錯，不建議 |

### 類別 3：依賴管理

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 主要依賴 | 不適合 | 純 CLI 使用者不需要 slack-bolt，強制安裝浪費空間 |
| B. Optional dependency group | ✅ 採用 | `pip install opentree[slack]` 明確表達意圖 |
| C. 執行時動態檢查 | 作為 B 的補充 | 啟動時 import 檢查，缺少時提示安裝指令 |

### 類別 4：認證模式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| SDK only (Socket Mode) | ✅ 採用 | 程式碼量減半，維護簡單 |
| SDK + Legacy 雙模式 | 不適合 | Legacy 需要瀏覽器 cookie（xoxc/xoxd），與無頭環境不相容 |

---

## 流程模擬結果

Flow Simulator Agent 測試了 41 個場景，發現 14 個問題：

### CRITICAL Issues（3 個，阻擋實作）

| Issue | 問題 | 解決方案 |
|-------|------|---------|
| #3 | `start_command` 使用靜態空白 PromptContext，Slack mode 需要每次請求動態注入 user_id/channel_id/thread_ts | 新增 SlackBotRunner，每個 task 處理前用 Slack 事件構建 PromptContext |
| #4 | `collect_module_prompts` 中 `sys.modules` 並行操作有競爭條件 | 使用 thread-local key 或啟動時預載快取 hook |
| #11 | `prompt_hook.py` 在 bot process 內 exec 等同 RCE（可讀取 Slack Token） | 短期：限制路徑驗證；長期：hook 在獨立 subprocess 執行 |

### HIGH Issues（5 個）

| Issue | 問題 | 解決方案 |
|-------|------|---------|
| #1 | settings.json 啟動時未覆寫 | 啟動序列加入 SettingsGenerator 覆寫 |
| #7 | Slack 429 rate limit 未處理 | 設定 bolt retry handler |
| #8 | 同一 session_id 被多任務同時 resume | per-thread 序列化（同一 thread_ts 按序執行） |
| #12 | settings.json 運行期間可被 Claude CLI 修改 | 每次 task 前覆寫 settings.json |
| #13 | user.json 欄位未做 prompt injection sanitization | load 後對字串值 sanitize |
| #14 | workspace 路徑缺少安全驗證 | 引入 `_is_safe_path_component` 等效驗證 |

### MEDIUM Issues（4 個）

| Issue | 問題 |
|-------|------|
| #2 | prompt_hook 每次請求 exec_module，效能不佳 |
| #6 | user config 含 `{{` 可能破壞 PlaceholderEngine |
| #9 | 無磁碟空間監控 |
| #10 | exec_module 物件未完全清理，記憶體累積 |

---

## 架構分析重點（Architect Agent）

### OpenTree vs DOGI 的本質差異

| 面向 | DOGI | OpenTree |
|------|------|---------|
| 定位 | 多租戶企業級 Slack bot（SaaS） | 單使用者個人 AI agent（self-hosted） |
| 多使用者 | 多 team、多 workspace、多使用者同 thread | 每人一個 bot 實例 |
| Security | SecurityFilter（input/output）、per-user policy | guardrail rules + 單使用者信任模型 |
| Prompt | 硬編碼 prompt_parts（965 行 CLAUDE.md） | 模組 prompt_hook + 動態生成（<200 行） |

### 關鍵 Trade-off

| 決策 | 犧牲了什麼 | 換取了什麼 |
|------|-----------|-----------|
| Runner 放在 core | Core 體積增大 | 一個指令啟動，zero-config |
| 只保留 SDK 模式 | 無法支援 xoxc/xoxd 環境 | 程式碼量減半 |
| 單使用者 session key | 無法多人同 thread 獨立對話 | 大幅簡化 session 管理 |
| 不從 DOGI import | 重複勞動約 1000 行 | 零耦合，獨立部署 |

### 模組系統整合流程

```
opentree init
  → symlinks: modules/rules/*.md → workspace/.claude/rules/
  → settings: modules permissions → workspace/.claude/settings.json
  → claude_md: registry → workspace/CLAUDE.md

opentree start --mode slack（每個 Slack 訊息）
  → PromptContext{user_id, channel_id, thread_ts}
  → assemble_system_prompt(home, registry, config, context)
  → claude --system-prompt "..." --cwd workspace/ [--resume session_id]
    → Claude CLI 自動讀取 .claude/rules/**/*.md + settings.json + CLAUDE.md
  → 串流解析 → 回覆 Slack
```

---

## Architect 與 Planner 的分歧

### `--mode` flag vs 獨立子指令

- **Planner** 傾向 `--mode` flag：共享前置步驟，差異只在最後一步
- **Architect** 傾向 `opentree serve`：生命週期完全不同（exec vs daemon），語義更清晰

**結論**：兩者皆可行。Planner 方案實作成本略低，Architect 方案擴展性更好。建議先用 `--mode`，未來需要 daemon 專屬 flag 時再抽離為 `serve`。

### 預估行數差異

- **Planner**：~2,420 行（較保守，含支援元件）
- **Architect**：~1,420 行（較激進，只算核心 runtime）

**差異原因**：Planner 包含了 progress.py、thread_context.py、file_handler.py 等 Phase 2 元件；Architect 只算 Phase 1 核心循環。

---

## 調研結論

1. **Bot runner 作為核心元件**（`src/opentree/runner/`），Slack 依賴用 optional group 隔離
2. **只支援 SDK 模式**（Socket Mode），不支援 Legacy polling
3. **完全獨立於 DOGI**，零 import，從頭撰寫但參考 DOGI 設計
4. **直接複用 `core/prompt.py`** 的 `assemble_system_prompt()`，每次請求動態組裝 PromptContext
5. **必須先修復 3 個 CRITICAL issues**（PromptContext 動態注入、sys.modules 並行安全、prompt_hook 安全隔離）
6. **預估 ~2,700 行 + ~153 tests，4.5-6.5 天工時**
