# 設計原則

- **優先使用 Claude CLI 既有功能**：設定繼承使用 Claude 原生機制（`~/.claude/` 全域 + 專案級 `.claude/` 覆蓋），不自建繼承邏輯
- **使用者記憶透過 `--system-prompt` 注入**：只傳遞使用者名稱和記憶檔案路徑，Claude CLI 自行讀取記憶內容，不修改 CLAUDE.md 或 hook
- **模組化優先**：每個功能以獨立模組實現，透過 `opentree.json` 宣告依賴和介面
- **靜態 + 動態分離**：模組 `rules/*.md` 合併為靜態 CLAUDE.md；動態資訊（日期、身份、頻道）由 `--system-prompt` 注入
