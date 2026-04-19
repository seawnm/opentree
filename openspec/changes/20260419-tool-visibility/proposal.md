# Proposal: Tool Execution Visibility Enhancement

**Date:** 2026-04-19
**Status:** approved

## 背景

bot_walter 執行任務時，進度訊息只顯示「🌐 搜尋網路中」、「💻 執行指令中」，
無法讓使用者看到具體在搜什麼、執行什麼指令。
任務結束後完成摘要也只有「搜尋網路 N 次」，無任何內容可見。

DOGI（slack-bot）的實作提供了完整的 input_preview 顯示：
- WebSearch：顯示搜尋關鍵字
- Bash：顯示指令描述摘要
- 完成摘要：顯示代表性查詢/指令

## 變更範圍

### tool_tracker.py

1. `_format_tool_entry()`：按 category 區分顯示格式
   - `web` → `搜尋：{query前30字}`
   - `bash` → input_preview（指令摘要），無 preview 時用 `執行指令`
   - `mcp` → `{tool_name}: {args前25字}`

2. `build_completion_summary()`：附上代表性內容
   - bash: 顯示最多 2 個代表性 preview
   - web: 顯示最多 2 個搜尋關鍵字

## 驗收標準

- 任務執行時，Slack 進度訊息能看到 WebSearch 的關鍵字
- 任務執行時，Slack 進度訊息能看到 Bash 的指令摘要
- 任務完成時，完成摘要能看到搜尋關鍵字和指令
- 文字過長時，截斷並加 `...`
- 不影響 241 個既有測試
- Progress timeline 會將同類型且 `started_at` 相差 1 秒內的連續工具合併顯示
- Progress timeline 超過顯示上限時，採 head(3) + `略過 N 個動作` + tail(3) 折疊，而非只保留尾端
- Live work phase 以最近 5 個工具的多數類別決定，不再只看當前單一工具
- Completion summary 的 task 類工具會逐項展開為 `📋 描述 ✅ Xs`（執行中則顯示 `執行中 Xs`）
- In-progress timeline 對尚未結束的工具顯示 `(執行中 Xs)`
- Completion summary 會顯示最具代表性的 thinking excerpt（`💭`，最長片段，80 字截斷）
- Progress Block Kit 會顯示最新 decision point（`💡` 區塊）
