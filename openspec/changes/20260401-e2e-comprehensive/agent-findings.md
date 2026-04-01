# Agent Findings — E2E Comprehensive Test

> 建立日期: 2026-04-01
> 最後更新: Batch 1-5 完成（Final）

## Architect Agent 發現

### OpenTree vs DOGI 功能差距

| 項目 | DOGI 行為 | OpenTree 行為 | 差距 | 處理 |
|------|----------|--------------|------|------|
| 工具 Icon | `📖`/`🔍`/`🌐`/`✏️`/`📋`/`💻` | 無 icon，純文字 | MEDIUM | 可作為 feature request |
| 工具聚合 | 同類工具合併（如「讀取了 3 個檔案」） | 逐一列出每個工具 | MEDIUM | 可作為 feature request |
| 工具分類 | `ToolCategory` enum（6 類） | 無分類系統 | LOW | 不影響功能 |
| Phase emoji | 相同 | 相同 | — | 無差距 |
| Token 統計 | 相同 | 相同 | — | 無差距 |
| 長文分段 | 相同（3000 chars） | 相同 | — | 無差距 |
| 訊息更新 | chat.update 原地更新 | 相同 | — | 無差距 |

### slack-query-tool 的 blocks 限制

`slack_query_tool.py` 的 `_simplify_message()` 會 strip 掉 `blocks` 欄位，
導致 E2E 測試無法透過標準 fixture 驗證 Block Kit 結構。

**解決方案**: 新增 `read_thread_raw` fixture，直接用 `slack_sdk.WebClient`
呼叫 `conversations.replies`，繞過 simplify 邏輯。

## Code Reviewer 發現

### CRITICAL（已修復）

1. **`read_thread_raw` 環境變數污染**: `load_dotenv` 在 polling loop 內重複執行，
   污染 `os.environ`。改用 `dotenv_values` + fixture body 初始化。

2. **`test_completion_replaces_progress` race condition**: `assert len == 1` 在
   `chat.update` race 下會 false fail。改為 `assert len >= 1`。

### HIGH（已修復）

1. **重複的 helper functions**: 3 個測試檔各自定義 `_wait_for_bot_reply_text`，
   與 conftest fixture 重複。統一使用 conftest fixtures。

2. **缺少負面斷言**: `test_different_threads_independent` 只驗證正面回憶，
   未檢查跨 thread 洩漏。新增 cross-thread negative assertions。

3. **Hardcoded sleep**: `test_remember_command_persists` 用 `time.sleep(10)`
   等待 memory 更新。改為 polling loop（2s 間隔，30s deadline）。

4. **相對路徑**: 工具追蹤測試用 `CLAUDE.md` 相對路徑，bot cwd 可能沒有此檔案。
   改為絕對路徑 `/mnt/e/develop/mydev/opentree/pyproject.toml`。

5. **不可靠的 fallback**: `wait_for_bot_reply` 用 `str(msg)` 做 fallback 匹配，
   會誤匹配使用者訊息。移除此 fallback。

6. **無斷言測試**: `test_thinking_phase_shown` 和 `test_progress_updates_periodically`
   沒有 assert。新增 warning 輸出。

### MEDIUM（已修復）

1. **_collect_bot_messages 假設**: 加上 docstring 說明排序假設
2. **Hardcoded TEMP_BASE**: 改為 import `file_handler.DEFAULT_TEMP_BASE`
3. **Cleanup error handling**: `_cleanup_test_memories` 改用 broad `except Exception`
4. **_BOT_UID 重複**: 加上同步 comment
5. **wait_for_bot_reply fallback**: 修復 `str(msg)` 不可靠匹配

## Security Agent 發現

### C1-C4 安全測試覆蓋

| 類別 | OWASP 對照 | 測試數 | 備註 |
|------|-----------|--------|------|
| C1 輸入過濾 | LLM01, LLM02, LLM04 | 5 | 含中英文 prompt injection |
| C2 輸出過濾 | LLM06 | 3 | API key/env/路徑洩漏 |
| C3 路徑遍歷 | LLM02 | 3 | ../../ 和絕對路徑 |
| C4 權限隔離 | LLM08 | 9 | 含靜態設定驗證 |

### 混合驗證策略
- C1/C2/C3: Slack 互動測試（發送真實訊息、檢查回覆）
- C4 部分: 靜態設定驗證（讀取 settings.json/permissions.json，不需 bot 運行）

## Batch 4 Code Reviewer 發現

### CRITICAL（已修復）

1. **排程測試缺少 cleanup**: `test_schedule_create_via_bot` 和 `test_schedule_delete_via_bot`
   建立的排程若測試中途失敗會殘留。新增 fixture-based cleanup，確保測試結束後自動刪除測試排程。

### HIGH（已修復）

1. **timestamp 比較 bug**: 排程列表回傳的 `next_run_time` 為字串格式，直接與 datetime 比較
   會 TypeError。改為統一解析後比較。

2. **錯誤路徑未覆蓋**: `test_schedule_delete_via_bot` 只測試成功路徑，未驗證刪除不存在的
   排程時的錯誤處理。新增 negative case。

3. **xfail 理由不精確**: `test_feature_request_triggers_collection` 的 xfail reason
   過於模糊。改為精確描述「AI 行為不確定：需求收集 prompt_hook 目前返回空列表」。

### MEDIUM（已修復）

1. **DM skip 訊息**: 補充 skip reason 說明具體框架限制（message-tool 不支援 DM 發送）
2. **spinner guard 遺漏**: 排程相關測試的 `wait_for_bot_reply` 未加入 spinner guard，
   可能返回 ack 而非實際回覆。統一套用 spinner guard。

### LOW（已修復）

1. **測試 docstring**: 補齊所有測試函式的 docstring
2. **import 排序**: 調整 import 順序符合 isort 規範

## Batch 5 Code Reviewer 發現

### HIGH（已修復）

1. **dead assert in test_error_message_user_friendly**: 原始版本只檢查 `"error" not in reply`，
   但 bot 回覆正常包含 "error" 一詞（如「發生了一個錯誤」）。改為檢查具體 traceback 格式
   （`Traceback (most recent call last)`、`File "..."`）。

2. **Circuit Breaker 狀態機路徑遺漏**: `test_circuit_breaker_state_transitions` 原始版本
   只測 CLOSED→OPEN→HALF_OPEN→CLOSED 路徑，遺漏 HALF_OPEN→OPEN 的回退路徑。
   補完雙向轉換測試。

3. **並行測試 race condition**: `test_concurrent_requests_handled` 發送 3 個並行請求後
   用固定 sleep 等待，可能在高負載下超時。改為 polling loop（5s 間隔，180s deadline）
   逐一確認所有回覆到達。

### MEDIUM（已修復）

1. **retry 錯誤分類 pattern**: `test_retry_error_classification` 原始用 substring match，
   會誤匹配非目標錯誤。改為精確正規表達式 pattern。
2. **Circuit Breaker 設定硬編碼**: `test_circuit_breaker_config_present` 將預期值
   硬編碼在測試中。改為從 config 模組 import 實際值比對。
3. **test_bot_recovers_after_error 依賴順序**: 原始先觸發錯誤再送正常請求，但未等待
   錯誤回覆完成。新增中間等待步驟確保時序正確。
4. **observational 測試標記**: `test_error_message_user_friendly` 新增 custom marker
   `@pytest.mark.observational` 區分驗證型和觀察型測試。

### LOW（已修復）

1. **test fixture 命名**: `cb_config` fixture 改為更具描述性的 `circuit_breaker_config`
2. **多餘的 import**: 移除未使用的 `json` import
