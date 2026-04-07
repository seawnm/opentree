# Phase 2 設計決策（基於 Flow Simulation 發現）

## Decision 1: `generate()` 是否包含 marker

**問題**：`generate()` 輸出包裹 marker 會破壞 12 個現有測試。
**決策**：`generate()` 不含 marker（純內容），新增 `_wrap_with_markers(content)` 私有方法。
**依據**：保護現有測試不需改動，separation of concerns。

## Decision 2: `generate_with_preservation()` 方法簽名

**問題**：方法自行讀檔（方案 A）vs 接收字串（方案 B）。
**決策**：方案 B — `generate_with_preservation(existing_content: str | None, ...)`
**依據**：保持 generator 層為純函數（無 I/O），易於測試。

## Decision 3: marker 不對稱處理策略

**問題**：BEGIN 或 END 缺失時的行為未定義。
**決策**：
- BEGIN 和 END 都存在 → 正常（用 `rfind()` 取最後一個 END）
- 任一缺失 → migration fallback（整個舊檔視為 Owner 內容，append 在新 auto 區塊後）+ WARNING log
- 兩者都不存在 → 純新檔（auto + Owner 提示注解）
**依據**：避免靜默資料損失，migration 友善。

## Decision 4: `_backup_state` 納入 CLAUDE.md

**問題**：force re-init rollback 時 Owner 自訂內容無法還原。
**決策**：`_backup_state()` 加入 `workspace/CLAUDE.md`。
**依據**：CLAUDE.md 含 Owner 不可重建的手寫內容，應視為需備份的狀態。

## Decision 5: Owner 自訂 key 的傳遞路徑

**問題**：`.env.local` 的 Owner key 無法傳遞到 Claude CLI subprocess。
**決策**：Phase 2B 不處理 key 傳遞（scope out）。
- `.env.local` 在 Phase 2 只用於：(1) 覆蓋 Slack tokens (2) 儲存供未來使用的 key
- Owner 自訂 key → Claude CLI 的傳遞管道 → 列入 Phase 3+ backlog
- 文件明確說明此限制
**依據**：key 傳遞涉及 bot.py → dispatcher.py → claude_process.py 三層修改，scope 太大。先建立檔案結構，再處理傳遞。

## Decision 6: .env.defaults 保護機制

**問題**：chmod 600 在同 UID 環境（WSL2、本地開發）無效。
**決策**：雙層保護 — chmod 600 + guardrail 規則（prompt-based）。
- 不使用 settings.json deny 規則（bypassPermissions 模式下 deny rules 不可靠，Batch 1 調研已確認）
- 在 `security-rules.md` 中加入 `.env.defaults` 路徑禁止存取規則
**依據**：guardrail 規則是 prompt-based 軟限制，但在 single-owner 場景下（Owner 不會攻擊自己的 bot）已足夠。

## Decision 7: 向後相容 fallback 邏輯

**問題**：舊 `.env` 存在時的搜索順序未明確。
**決策**：
```
if .env.defaults exists:
    load .env.defaults
    if .env.local exists: merge (override)
    if .env.secrets exists: merge (override)
elif .env exists:
    log WARNING "Legacy config/.env detected"
    load .env (legacy fallback)
else:
    raise RuntimeError
```
**依據**：向後相容必須支援，但明確提示遷移。

## Decision 8: remove 最後模組時的 Owner 內容

**問題**：remove 最後模組會直接 unlink CLAUDE.md。
**決策**：Phase 2A 不修改 remove 行為（scope out）。
- 移除最後一個模組是極罕見操作
- 列入 TODO（未來 remove 前檢查 Owner 內容並警告）
**依據**：ROI 低，不值得增加 remove 的複雜度。
