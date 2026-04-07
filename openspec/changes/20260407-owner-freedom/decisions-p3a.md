# Phase 3a 設計決策（Reset 分級）

## 基於 Flow Simulation 的 9 個 issue，做出以下設計決策

### Decision 1: .env.defaults 不重設為 placeholder

**問題**：reset-bot-all 後 .env.defaults 為 placeholder → bot 無法重啟（Issue #3）
**決策**：reset-bot-all **不動** .env.defaults（保留真實 token），只刪除 .env.local + .env.secrets
**依據**：使用者說「重製env」的意思是重設 Owner 自訂的 key，不是刪除 bot 的核心連線 token
**影響**：不需要 onboard snapshot 機制（Issue #3 消除）

### Decision 2: SessionManager.clear_all() 方法

**問題**：刪除 sessions.json 但記憶體狀態仍在，race condition（Issue #1, #9）
**決策**：新增 `SessionManager.clear_all()` 公開方法，同步清除記憶體 + 磁碟
**依據**：消除 race condition，dispatcher 可直接呼叫

### Decision 3: data/ 目錄保留，只清空內容

**問題**：shutil.rmtree(data/) 後 SessionManager._save() 拋 OSError（Issue #2, #6）
**決策**：reset_bot_all 保留 data/ 目錄本身，選擇性清空子目錄/檔案
**清空範圍**：data/memory/*, data/sessions.json, data/logs/*
**保留**：data/ 目錄本身

### Decision 4: 不實作兩步確認

**問題**：reset-bot-all 缺乏確認機制（Issue #7）
**決策**：不實作 Slack 兩步確認（複雜度高，需 pending state 管理）
**替代**：在確認訊息中明確說明後果（同 shutdown 的模式），指令本身已足夠明確
**依據**：MVP 原則，與 shutdown/restart 行為一致

### Decision 5: 不實作 rollback 機制

**問題**：重設中途失敗，部分狀態不一致（Issue #4）
**決策**：不實作 rollback（reset 操作是 idempotent，再執行一次即可修復）
**依據**：rollback 增加大量複雜度，且 reset 的每個步驟都是 idempotent；失敗時 log error + Slack 通知，Owner 可再試
**替代**：try/except 包裹，失敗步驟 log warning 繼續執行剩餘步驟（best-effort）

### Decision 6: reset.py 直接使用 generator API

**問題**：reset.py 應該直接操作檔案還是呼叫 CLI（Q1）
**決策**：直接使用 SettingsGenerator、SymlinkManager、ClaudeMdGenerator 的 API，不呼叫 CLI
**依據**：CLI 依賴 typer，不適合在 runtime 呼叫；generator API 已有完整測試

### Decision 7: SymlinkManager 失敗 → log warning + 繼續

**問題**：SymlinkManager 失敗靜默通過（Issue #8）
**決策**：檢查 LinkResult.success，失敗的 log WARNING 但不中斷 reset
**依據**：best-effort 策略，部分 rules 缺失比完全中斷好
