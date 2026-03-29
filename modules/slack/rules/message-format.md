# Slack 訊息格式

- **Slack 不支援 markdown 表格**（`| col1 | col2 |` 格式會變成亂碼），改用逐項列出格式
- Slack 支援的格式：粗體 `*text*`、斜體 `_text_`、刪除線 `~text~`、code block、引用 `>`、列表 `-`/`1.`
- **連結一律用純文字 URL**：不要用角括號語法、不要用 markdown 連結語法、不要用括號包 URL
  - 錯誤：`（https://example.com）` — 括號會被 Slack 納入 URL
  - 錯誤：`[文字](https://example.com)` — markdown 格式在 Slack 無效
  - 正確：`來源：媒體名稱` + 換行 + `https://example.com` — 純文字 URL，Slack 自動偵測
- **超連結注意事項**：超連結後面不要直接接其他文字（不留空格），否則後續文字會被解析為連結的一部分
