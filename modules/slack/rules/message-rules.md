# Slack 訊息發送規則

**禁止使用 MCP Slack 工具發送訊息。** 包含但不限於：
- `mcp__claude_ai_Slack__slack_send_message`
- `mcp__claude_ai_Slack__slack_send_message_draft`
- `mcp__claude_ai_Slack__slack_schedule_message`
- `mcp__claude_ai_Slack__slack_create_canvas`

**原因**：MCP Slack 使用的是使用者個人 Token（xoxc-），發出的訊息會顯示為該使用者而非 bot。所有對 Slack 的訊息互動都應由 bot 主進程透過 Bot Token（xoxb-）處理。

**Slack 讀取一律使用 Bot Token**：MCP Slack 的 xoxc- token 有 workspace 限制，頻道/thread 讀取經常失敗。所有 Slack 讀取操作應使用 slack-query-tool（詳見 query-tool.md）。

**MCP Slack 唯讀工具僅作為備援**（當 slack-query-tool 無法使用時）：
- `mcp__claude_ai_Slack__slack_search_*`
- `mcp__claude_ai_Slack__slack_read_*`

**需要發訊息時**：回覆文字內容即可，bot 主進程會以 bot 身份發送到 Slack。

**需要上傳檔案時**：使用 upload-tool CLI 工具（詳見 upload-tool.md）。
