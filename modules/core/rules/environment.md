# 環境限制與替代方案

## 不支援互動式工具

Claude CLI 在 bot 中以非互動模式執行，**無法使用 AskUserQuestion 工具**。

## 多輪對話替代方案

Slack thread 是天然的多輪對話介面。當需要訪談、蒐集需求或任何需要使用者回答的場景：

1. **直接以文字輸出問題**，不要使用 AskUserQuestion
2. **一次只問一個問題**，讓使用者容易回答
3. 使用者會在同一 thread 回覆（帶 @{{bot_name}}），透過 session resume 收到上下文
4. 收到回答後繼續下一題，直到蒐集完所有資訊

範例流程：
```
{{bot_name}}: 想先了解一下你的需求。你希望這個工具主要解決什麼問題？
使用者: 我想自動整理每週的會議紀錄
{{bot_name}}: 了解。會議紀錄的來源是什麼格式？（例如：Slack 訊息、Google Doc、手打筆記）
```

## 檔案路徑規則（BUG-03 修正）

> **重要：產生檔案後必須上傳，不可只回覆本機路徑**

### 路徑分流

| 使用者類型 | 檔案存放位置 | 原因 |
|-----------|------------|------|
| Owner / Admin（system prompt 顯示「權限等級：Owner」） | `{{opentree_home}}/workspace/files/{thread_ts}/` | 持久化，跨 session 可引用 |
| 一般使用者 | `/tmp/opentree/{thread_ts}/` | 暫存，session 結束後清除 |

### 產檔後的必要流程

1. 用 Write 工具或 Bash 建立檔案
2. **必須呼叫 upload-tool 上傳到當前 Slack thread**（見 upload-tool.md）
3. 在 Slack 回覆確認「已上傳」，不只是說「已產生到 /path/file」

### 禁止行為

- ❌ 只回覆「已產生檔案存到 /tmp/xxx」而不上傳
- ❌ 所有使用者都用 `/tmp`（Owner 的產物需要持久化）
- ❌ 上傳失敗後靜默不報告

### 臨時檔案（非交付用途）

非直接交付的中間產物（checkpoint、暫存資料）存放於 `/tmp/opentree/{thread_ts}/`。
