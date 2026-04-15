<!-- bot_name 由 config/user.json 的 bot_name 欄位決定，範例：Bot_BotName。
     {{bot_name}} placeholder 在 module refresh 後自動替換為實際值。 -->
# OpenTree 概述

OpenTree 是模組化的 AI 助手框架，將人格、安全、記憶、排程等功能拆分為可插拔模組，由 core 統一組裝成 Claude CLI 可讀的規則集。

## 路徑慣例

| 變數 | 說明 |
|------|------|
| `$OPENTREE_HOME` (`{{opentree_home}}`) | OpenTree 安裝根目錄 |
| `modules/` | 模組目錄（每個模組含 `rules/`、`opentree.json`） |
| `workspace/` | 使用者工作區（檔案、記憶） |
| `data/` | 持久化資料（排程 DB、session 等） |
| `config/` | 設定檔（`user.json` 含 bot_name、team_name 等） |
