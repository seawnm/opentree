# Decisions — E2E Comprehensive Test

## Decision 1: Block Kit blocks 觀測方式

**問題**: slack-query-tool 的 _simplify_message() strip 掉 blocks，無法驗證 Block Kit 結構。

**考慮過的方案**:
- **A: conftest 新增 read_thread_raw fixture**（直接用 slack_sdk.WebClient）→ ✅ 採用
- **B: slack_query_tool 新增 --raw flag** → 改動 bot 工具程式碼，E2E 階段不宜
- **C: 只用 text fallback 驗證** → 無法驗證 phase emoji、section 分段等

**最終選擇**: A — 在 conftest 中用 dotenv_values 載入 token，建構 WebClient，不污染 os.environ。

## Decision 2: 中間進度狀態的驗證策略

**問題**: ProgressReporter 用 chat.update 原地更新訊息，thread 中只能看到最終版本。

**考慮過的方案**:
- **A: 輪詢 text 快照** — 每 3 秒讀取 thread 記錄 text 變化 → 可行但增加 API 呼叫
- **B: grep bot 日誌** — 從 bot 日誌驗證 phase transition → ✅ 採用
- **C: 只驗證最終結果** — 不驗證中間狀態 → 太弱

**最終選擇**: B — 用 grep_log fixture 驗證日誌中的 phase transition 記錄，搭配 warning 輸出。

## Decision 3: 安全測試的混合策略

**問題**: 部分安全防護在 Claude CLI 層（settings.json），部分在 OpenTree 程式碼層。

**考慮過的方案**:
- **A: 全部用 Slack 互動測試** → 無法精確測試 settings.json 設定
- **B: 全部用靜態驗證** → 無法測試實際防護效果
- **C: 混合策略** → ✅ 採用

**最終選擇**: C — C1/C2/C3 用 Slack 互動測試，C4 部分用靜態設定驗證。

## Decision 4: Bug 處理策略

**問題**: Code Review 發現的問題應如何處理。

**原始方案**: CRITICAL/HIGH 即修，MEDIUM/LOW 記錄後續。
**使用者決策**: 全部立即修復，不留後續。

**最終選擇**: 所有等級的發現全部用 feature-workflow 即時修復。

## Decision 5: 測試頻道選擇

**問題**: 用哪個 Slack 頻道進行 E2E 測試。

**考慮過的方案**:
- **ai-room** → ✅ 採用。已清除 Ralph 監控設定，專用於 AI 測試
- **beta-room** → 目前對話頻道，可能與正常使用混淆
- **新建專用頻道** → 額外管理成本

**最終選擇**: ai-room（C0AJ63F1T9P）。清除 Ralph 設定後作為 E2E 測試場地。
