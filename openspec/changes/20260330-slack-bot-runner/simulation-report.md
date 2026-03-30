# Flow Simulation Report: OpenTree Slack Bot Runner

> 建立日期：2026-03-30
> 測試場景數：41 | 通過：27 | 失敗：14

---

## 測試摘要

| Category | Tested | Passed | Failed |
|----------|--------|--------|--------|
| Normal Flows | 5 | 3 | 2 |
| Input Boundaries | 5 | 4 | 1 |
| Network & I/O | 6 | 4 | 2 |
| Concurrency | 5 | 3 | 2 |
| State | 6 | 6 | 0 |
| Resource | 4 | 2 | 2 |
| Security | 5 | 1 | 4 |
| Module Integration | 5 | 4 | 1 |

---

## CRITICAL Issues（必須在實作前解決）

### Issue #3：PromptContext 靜態空白（阻擋）

- **問題**：`start_command` 為 TUI 設計，組裝一次空白 `PromptContext` 就啟動。Slack mode 每個訊息需要不同的 user_id, channel_id, thread_ts
- **影響**：模組 prompt_hook 無法區分使用者，記憶路徑錯誤
- **修復**：新增 SlackBotRunner，每個 task 前用 Slack 事件構建 PromptContext

### Issue #4：sys.modules 並行競爭（阻擋）

- **問題**：`collect_module_prompts` 的 `del sys.modules[mod_key]` + `exec_module` 序列在多執行緒環境下有競爭條件
- **影響**：並行請求時可能拋出 AttributeError 或使用錯誤的 hook 版本
- **修復**：使用 thread-local key 或啟動時預載快取

### Issue #11：prompt_hook RCE 風險（安全）

- **問題**：`exec_module` 在 bot process 內執行任意 Python，具有 bot 完整環境變數（含 Slack Token）
- **影響**：惡意 hook 可讀取 token、發送任意訊息、執行系統指令
- **修復**：短期限制路徑驗證 + chmod 700；長期在獨立 subprocess 中執行

---

## HIGH Issues

### Issue #1：settings.json 覆寫時機
- 啟動序列未呼叫 `SettingsGenerator.write_settings()`，手動修改的 settings 不會被還原

### Issue #7：Slack 429 rate limit
- 需設定 bolt retry handler，避免連續失敗觸發 liveness probe 重啟

### Issue #8：同一 thread 的 session resume 競爭
- 同一 thread 連續訊息可能各自用新 session，上下文斷裂
- 需 per-thread 序列化

### Issue #12：settings.json 運行期間可被修改
- Claude CLI 可能靜默修改 settings，繞過工具限制
- 每次 task 前覆寫

### Issue #13：user.json prompt injection
- bot_name 含 `\n\n# OVERRIDE` 可污染 system prompt
- 需 sanitization

### Issue #14：workspace 路徑遍歷
- 若 workspace name 允許 `../../etc`，Claude CLI 的 --cwd 可指向系統路徑
- 需引入安全驗證

---

## MEDIUM Issues

| Issue | 問題 | 建議 |
|-------|------|------|
| #2 | prompt_hook 每次請求 exec_module | 啟動時快取 hook |
| #6 | user config 含 `{{` 破壞 PlaceholderEngine | 載入時轉義 |
| #9 | 無磁碟空間監控 | 啟動時檢查 |
| #10 | exec_module 物件記憶體累積 | 改為一次性 import |

---

## 修復優先級

| 優先級 | Issue | 類型 |
|--------|-------|------|
| P0 | #3 | Architecture（per-request PromptContext） |
| P0 | #4 | Concurrency（sys.modules thread safety） |
| P0 | #11 | Security（hook 執行隔離） |
| P1 | #1, #12 | State/Security（settings 覆寫） |
| P1 | #8 | Concurrency（per-thread 序列化） |
| P1 | #13, #14 | Security（sanitization + 路徑驗證） |
| P2 | #7 | Network（rate limit） |
| P3 | #2, #6, #9, #10 | Performance/Resource |

---

## 已有的良好基礎

- `assemble_system_prompt` + `PromptContext` 架構設計正確
- `collect_module_prompts` 的 error isolation 設計良好（hook 失敗不中斷）
- Registry 的 flock + fsync + crash recovery 已達生產品質
- DOGI 的 liveness probe、graceful shutdown、task queue 等機制可參考移植
- 模組熱更新天然支持（rules 是 symlink，Claude CLI per-task 啟動）
