# STT 語音轉文字工具

使用 `alloy stt` 將音訊檔案轉錄為帶時間戳的文字。

## CLI 指令

```bash
# 基本用法
alloy stt transcribe <file_path> --user-id <user_id> --user-name <user_name>

# 完整參數
alloy stt transcribe /path/to/audio.m4a \
  --user-id U0AJRPQ55PH \
  --user-name walter \
  --channel C0AK78CNYBU \
  --thread-ts 1773542998.472329 \
  --prompt "關鍵詞提示"

# 查詢額度
alloy stt quota --user-id <user_id>

# 查詢使用統計
alloy stt usage --user-id <user_id> --date 2026-03-22

# 清理過期音訊
alloy stt cleanup --keep-days 3
```

## 規格

- **支援格式**：m4a, mp3, wav, ogg, webm, mp4
- **大檔案**：>25MB 自動用 ffmpeg 切割（20MB/段 + 10s 重疊）
- **輸出**：JSON（含 text、transcript_path、duration_seconds、cost_usd）
- **歸檔**：轉錄永久保存到使用者目錄下 `stt/`，音訊保留 3 天
- **費用**：`duration_minutes x $0.006`，每日額度 100 MB

## 使用指引

1. **觸發規則**：使用者上傳音訊檔（mimetype 含 `audio/` 或副檔名為 m4a/mp3/wav/ogg/webm/mp4）且表達轉錄意圖時，**必須**呼叫 `alloy stt transcribe`。禁止直接用 Read 工具讀取音訊檔案（會產生亂碼）
2. **無明確意圖時**：若使用者上傳音訊但未說明用途，應主動詢問而非自動轉錄
3. **大檔案預先確認**：音訊檔超過 50MB 時，應先告知使用者預估費用和時長，並詢問是否要拆分。提醒每日額度上限（100 MB）
4. `--user-id` 和 `--user-name` 從 system prompt 取得
5. **路徑 quoting**：檔案路徑需用引號包裹，避免空格或特殊字元造成解析錯誤
6. 轉錄結果 JSON 中的 `text` 欄位為帶時間戳格式（`[MM:SS] 文字`）
7. **轉錄失敗處理**：`success` 為 `false` 時，讀取 `error` 欄位告知使用者失敗原因，不要重試
8. **transcript_path**：成功時回傳的歸檔路徑，可用 Read 工具讀取完整文字。若為 `null`（歸檔失敗），直接使用 `text` 欄位
9. **長文字處理**：`text` 超過 3,500 字元時，應使用 upload-tool 上傳 .txt 檔給使用者，而非直接在 Slack 回覆
