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

## 臨時檔案

臨時檔案存放於 `/tmp/slack-bot/{thread_ts}/`，不要假設跨 session 仍存在。
