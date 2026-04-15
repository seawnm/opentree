# Research：Bash 依賴根因調查

**日期**：2026-04-14

## 調查方法

多 agent 並行分析：
- Agent A（工具權限）：分析 settings.json 格式和 dontAsk mode 行為
- Agent B（記憶模組）：追蹤記憶讀寫失敗的精確位置
- Agent C（能力宣告）：分析靜態宣告與 runtime 能力的脫鉤原因

## 方案比較

### 方案 A：在 settings.json allow 清單中加入 `Bash(mkdir *)` ← 淘汰
**淘汰原因**：允許 Bash mkdir 放寬安全邊界；而且 Write 工具本身可以自建目錄，
完全不需要這個 Bash 步驟。

### 方案 B：修改 memory-sop.md 移除 Bash 步驟 ← 採用
**採用原因**：Write 工具在 Claude Code 中已支援自動建立中間目錄。
移除 Bash 依賴讓整個記憶讀寫流程純用原生工具，不需要任何 Bash 呼叫。

## 結論

根本問題不在工具白名單，而在 memory-sop.md 規則本身包含了一個不必要的 Bash 依賴。
修復代價極小（改一行規則），效果立竿見影。

---

## 附錄：E2E 測試案例 bot 名稱錯誤根因（2026-04-15）

### 錯誤描述
生成的測試案例使用 `@walter` 而非正確的 `@Bot_Walter`（共 9 處）。

### 根因分析
上一個 Codex agent 在生成測試案例時，**從未取得 bot_name 的真實值**。

具體原因鏈如下：
1. **原始模組的 `character.md` 含未替換的 placeholder `{{bot_name}}`**：`/mnt/e/develop/mydev/opentree/modules/personality/rules/character.md` 中 bot 名稱以 `{{bot_name}}` 表示，placeholder 未展開為實際值。
2. **Codex agent 未讀取 `user.json`**：正確的 bot_name `Bot_Walter` 存在於 `/mnt/e/develop/mydev/project/trees/bot_walter/config/user.json`，但 agent 未讀取此檔案確認。
3. **使用者名稱與 bot 名稱混淆**：agent 可能將「walter」（workspace 目錄名稱 / 使用者名稱）與 bot mention 格式混用，直接寫出 `@walter` 而非查詢實際 bot_name。
4. **workspace 的 character.md 已正確替換**：`/mnt/e/develop/mydev/project/trees/bot_walter/workspace/.claude/rules/personality/character.md` 中 `{{bot_name}}` 已被替換為 `Bot_Walter`，但 agent 讀取的是原始模組（含 placeholder）而非已渲染的 workspace 副本。

### 預防措施
1. **生成測試案例前強制讀取 `user.json`**：在任何生成 bot interaction 測試案例的任務 prompt 中，明確要求先讀取 `config/user.json` 確認 `bot_name` 欄位再生成。
2. **優先讀取 workspace 已渲染的 rules**：讀取 character.md 時，應優先使用 `workspace/.claude/rules/personality/character.md`（已替換 placeholder）而非原始模組路徑。
3. **在測試案例 header 加入 bot_name 宣告**：已在修正版中加入 `> **Bot 名稱**：Bot_Walter` header，讓後續 agent 在讀取測試案例時能立即取得正確名稱。
