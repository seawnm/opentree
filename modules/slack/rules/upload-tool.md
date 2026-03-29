# 檔案上傳工具（upload-tool）

當需要將檔案傳送給使用者時，使用此 CLI 工具上傳到當前 Slack thread。

```bash
uv run --directory {{opentree_home}} python -m scripts.tools.upload_tool upload <file_path> \
  --channel <channel_id> \
  --thread-ts <thread_ts>
```

## 可選參數

- `--title "自訂標題"` — 預設為檔名
- `--comment "說明文字"` — 附加在檔案旁的訊息

## 使用指引

1. **channel 和 thread-ts** 從 system prompt 中的「目前頻道 ID」和「目前 Thread TS」取得
2. **檔案必須先存在**，用 Write 工具或 Bash 建立檔案後再呼叫上傳
3. **大小限制** 50 MB
4. 工具輸出 JSON，上傳成功會回傳 `{"success": true, ...}`

## 範例

```bash
uv run --directory {{opentree_home}} python -m scripts.tools.upload_tool upload /home/user/report.html \
  --channel C0AK78CNYBU \
  --thread-ts 1739012345.123456 \
  --comment "Dashboard 報告"
```
