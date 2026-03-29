# YouTube 使用指引

## 搜尋與瀏覽

- 所有子指令回傳 JSON（`{"success": true/false, ...}`）
- `upload_date` 格式為 YYYYMMDD（影片在 YouTube 上的發布日期）
- 字幕以 SRT 格式儲存，純文字同步寫入 DB 供 FTS5 全文搜尋
- 搜尋結果以 BM25 相關性排序（title 權重最高）

## 抓取影片

- 抓取操作（fetch、fetch-channel、sync、channels-add/remove、retry-subs）需要管理權限
- 一般使用者僅可搜尋和瀏覽（search、list、channels）
- `--user-id` 和 `--user-name` 從 system prompt 取得

## 排程整合

使用 schedule-tool 建立 cron 排程自動同步：
- task-type 設為 `ai_generate`
- prompt 指示執行 `alloy youtube sync`

範例：每天早上 9 點同步所有追蹤頻道的最新影片。

## 字幕重試策略

- 批次 fetch 後字幕可能因 429 Rate Limit 失敗（狀態為 `none`）
- 用 `retry-subs` 逐一重試，依語言優先順序 en → zh-Hant → zh-Hans 嘗試
- 使用 optimistic locking 避免與排程 sync 衝突
- `retry-subs --limit 50` 控制每次重試數量

## 資料儲存

- metadata + 字幕寫入 SQLite DB + FTS5 索引
- 資料目錄由環境變數 `YOUTUBE_DATA_DIR` 指定
- 跨 workspace 共享
