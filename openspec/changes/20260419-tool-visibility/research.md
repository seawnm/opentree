# Research: Tool Visibility Phase 2

**Date:** 2026-04-19

## 背景

20260419 第一階段 proposal 只涵蓋 input preview 顯示：WebSearch 關鍵字、Bash 指令摘要、完成摘要代表性內容。
對照 DOGI（slack-bot）後，OpenTree 仍缺少多個可讀性與資訊密度相關細節，尤其是 timeline 壓縮、工作階段判斷、thinking/decision 可視化。

本文件補上 phase 2 的完整分析與實作決策。

## DOGI（slack-bot）參考實作分析

DOGI 的進度訊息設計重點不是「列出所有事件」，而是：

- 把高頻重複動作壓縮成可掃描的 timeline
- 讓使用者知道 bot 此刻主要在做什麼，而不是只知道上一個工具名稱
- 在完成摘要保留少量高訊號內容，例如查詢關鍵字、子任務、思考片段
- 當 bot 出現規劃或轉折時，顯示 decision/reasoning cue，降低黑盒感

OpenTree phase 1 已接上 input preview，但仍與 DOGI 有 7 個差距。

## 識別出的 7 個候選改進

1. **Timeline same-type grouping ±1s**
   - 連續同類工具若屬於同一批次，不應逐條刷屏
   - 目標：合併為單一 entry，必要時附 count

2. **Timeline head/tail folding**
   - timeline 很長時，只保留最後幾筆會丟失前段關鍵上下文
   - 目標：保留開頭與結尾，中間折疊成 `略過 N 個動作`

3. **Work phase from recent 5 tools majority**
   - 單看目前工具容易抖動，尤其是 tool/thinking/tool 快速切換時
   - 目標：用近窗多數決產生更穩定的「目前在做什麼」

4. **Task subtask expand**
   - `task` 類工具只用彙總數量，無法看出拆成哪些子任務
   - 目標：完成摘要逐項列出每個 task 與耗時

5. **In-progress duration**
   - 尚未結束的工具若只顯示名稱，缺少「卡多久」資訊
   - 目標：live timeline 顯示 `(執行中 Xs)`

6. **Thinking excerpt**
   - 只有「思考 N 秒」不足以讓使用者理解 bot 在思考什麼
   - 目標：完成摘要附一段代表性 thinking 內容

7. **Decision point block**
   - bot 出現規劃/重試/分析結論時，應顯示轉折點而非只留在原始文字流
   - 目標：progress Block Kit 顯示最新 `💡` decision cue

## 實作決策

### 1. Same-type grouping ±1s

採用。

- 實作位置：`ToolTracker._merge_same_type_groups()`
- 規則：僅合併「連續」且 category 相同的工具
- 時間判定：比較相鄰工具的 `started_at`，差距 `<= 1.0s`

原因：
- `started_at` 最能反映「同一波觸發」
- 若用 `ended_at`，長尾工具會把原本同批的短工具拆散

Trade-off：
- 這是顯示層壓縮，不改底層 `ToolUse` 記錄粒度

### 2. Head/tail folding

採用。

- 實作位置：`ToolTracker.build_progress_timeline()`
- 規則：entry 數超過 `max_entries` 時，固定保留 head(3) + skip + tail(3)
- 中段以 `略過 N 個動作` 表示

原因：
- 首段常包含初始化/第一輪搜尋，尾段則反映目前狀態
- 比單純尾端裁切更符合除錯與使用者理解需求

Trade-off：
- 這是純 display-only 折疊，原始 timeline 與 completion summary 不受影響
- 預設折疊後可能略高於呼叫端 `max_entries`，屬刻意設計，優先保留可讀性

### 3. Work phase from recent 5 tools majority

採用。

- 實作位置：`ToolTracker.get_work_phase()`
- 規則：使用最近 5 個工具視窗（已完成 4 筆 + 當前 1 筆）
- 以 category 多數決決定 phase label；若平手，偏向最近一筆

原因：
- 比單看 `_current` 更穩定，也避免 phase label 過度閃動

Trade-off：
- 這是 coarse label，不保證與當前秒級事件完全一致
- 選 5 是折衷值：夠平滑，但不會把很早之前的階段拖太久

### 4. Task subtask expand

採用。

- 實作位置：`ToolTracker.build_completion_summary()`
- 顯示方式：
  - 先顯示父層 `🌟 子任務執行` 或單一 task 的描述
  - 再逐項列出 `📋 desc ✅ Xs`
  - 若尚未結束則顯示 `📋 desc (執行中 Xs)`

原因：
- `task` 類工具本質上是子任務編排，逐項列出比「task N 次」更有價值

Trade-off：
- summary 會變長，但 task 類本來就是高訊號內容，值得保留逐項明細

### 5. In-progress duration

採用。

- 實作位置：`ToolTracker._format_tool_entry()`
- 規則：
  - 已完成工具：`(1.2s)`
  - 執行中工具：`(執行中 12s)`

原因：
- 使用者能直接看出某個工具是否卡住、剛開始，或只是尚未完成

Trade-off：
- live duration 以秒為單位，刻意保持粗粒度，避免頻繁刷新造成視覺噪音

### 6. Thinking excerpt

採用。

- 實作位置：`ToolTracker.build_completion_summary()`
- 規則：從 `_thinking_excerpts` 取最長片段作為代表內容
- 顯示：`💭 excerpt...`
- 截斷：80 字

原因：
- 最長 thinking block 通常最接近真正的分析/規劃內容
- 比取第一段或最後一段更穩定，也較不容易拿到過短 filler 片段

Trade-off：
- longest block 不一定是語義上最重要的一段，但實作簡單且訊號通常足夠高

### 7. Decision point block

採用。

- 實作位置：
  - `ToolTracker.track_text()`：regex 偵測 decision pattern
  - `ToolTracker.get_latest_decision()`：取最新 `DecisionPoint`
  - `build_progress_blocks()`：插入 `💡` section
- 偵測內容：子任務完成、重試、資訊蒐集完成、規劃開始、重新思考、分析發現等轉折語句

原因：
- 不需要等任務完成，就能讓使用者看到 bot 已進入規劃/判斷/重試等狀態

Trade-off：
- 目前是 regex heuristics，可能有 false positive / false negative
- 顯示最新 decision，而非保留 decision 歷史，避免 Block Kit 過長

## 關鍵取捨總結

- **Grouping 使用 `started_at`，不是 `ended_at`**：保留「同一波工具呼叫」語義
- **Folding 是 display-only**：不更動底層資料，只壓縮 Slack 呈現
- **Work phase 用 recent-5 多數決**：用少量歷史平滑 phase label 抖動
- **Task 類逐項展開**：犧牲一點摘要長度，換取實際可讀性
- **In-progress duration 用整秒**：降低更新噪音
- **Thinking excerpt 取最長區塊**：規則簡單、穩定，通常比 first/last 更有資訊量
- **Decision block 只顯示最新一個**：避免訊息面板被推滿

## 結論

Tool visibility phase 2 的重點不是新增更多資料，而是把已存在的 tool / thinking / text signal 壓縮成更接近 DOGI 的可讀 Slack UX。

phase 1 解決了「看不到內容」；
phase 2 解決的是「看得到，但還不夠像人在追 bot 工作過程」。
