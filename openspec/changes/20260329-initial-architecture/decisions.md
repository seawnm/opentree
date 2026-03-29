# Decisions: OpenTree 初始架構

## Decision 0: 核心架構選型

**問題**：OpenTree 的核心架構應該是什麼？

**考慮過的方案**：
- **薄 wrapper**：外層包一層程式，底層調用 Claude Code CLI → ✅ 採用
- **Claude plugins**：用 Claude Code 原生 plugin 系統 → 淘汰，要跨 AI 廠商
- **獨立 AI agent framework**：不依賴 Claude Code CLI → 淘汰，重造輪子

**最終選擇**：薄 wrapper
**決策依據**：最小化自建邏輯，最大化利用 Claude Code 的 sandbox、session、MCP 等既有能力。
**約束條件**：使用者需安裝 Claude Code CLI 作為 runtime。

---

## Decision 1: Manifest 格式

**問題**：OpenTree 模組的 manifest 格式應該採用什麼標準？

**考慮過的方案**：
- **Claude Code plugin.json**：直接沿用 → 淘汰，驗證器不穩定（hooks 欄位翻覆 4 次），無法表達 sandbox 權限、lifecycle hooks
- **npm package.json 擴展**：加 `opentree` 命名空間 → 淘汰，語義錯位（非 Node 模組）
- **自定義 opentree.json**：命名參照 npm 慣例，schema 自主 → ✅ 採用
- **多 manifest 共存**：核心用 opentree.json，不禁止額外 manifest → ✅ 作為補充策略

**最終選擇**：自定義 `opentree.json`
**決策依據**：
1. 與「自有模組格式」已確認決策一致
2. 避免 Claude Code plugin 驗證器的不穩定風險
3. 精確對應 OpenTree 需求（sandbox 權限、lifecycle、模組依賴）
4. 欄位命名沿用 npm 慣例，降低學習成本
**約束條件**：需自建 JSON Schema 驗證器（工作量小）。

---

## Decision 2: 安全設定機制

**問題**：如何在任意路徑實現安全設定，且支援多使用者同機器？

**考慮過的方案**：
- **managed-settings（統一最嚴格 superset）**：所有人共用一份 → 淘汰，使用者越多越嚴格到不可用
- **managed-settings（namespace 隔離）**：mount namespace bind mount → 淘汰，需 root、Windows 不支援
- **managed-settings（swap + 鎖）**：搶鎖 → 寫入 → 啟動 → 放鎖 → 淘汰，長任務 = 長鎖 = 單工
- **等待 --managed-settings-path**：GitHub #33857 → 淘汰，不存在、時程不明
- **project-level .claude/settings.json**：wrapper 動態產生 → ✅ 採用

**最終選擇**：project-level `.claude/settings.json` + wrapper 啟動時覆蓋
**決策依據**：
1. DOGI bot 已在生產環境驗證此模式數月（`permission_manager.py` 的 `ensure_workspace()`）
2. 不依賴 OS 固定路徑、不需 root、跨平台一致
3. 每人完整獨立實例（`$OPENTREE_HOME`），零共享 = 零衝突
**約束條件**：犧牲 managed-settings 的「不可覆寫」保證。在 OpenTree 的威脅模型中（單使用者 = bot 擁有者），此損失可接受。
**補償措施**：wrapper 每次啟動覆蓋 settings.json；使用者改了也只活到下次啟動。

---

## Decision 3: 認證模式

**問題**：不輸入 API Key 時，預設使用什麼認證方式？

**考慮過的方案**：
- **預設 API Key**：最穩定但門檻高（需付費取得 key） → 淘汰
- **預設訂閱 → API Key fallback**：最低門檻但無頭環境首次登入複雜 → 淘汰
- **Auto-detect**：有 key 用 key，有 session 用 session → ✅ 採用

**最終選擇**：Auto-detect
**決策依據**：優先順序 `ANTHROPIC_API_KEY` 環境變數 → config 中的 api_key → `~/.claude/` OAuth session → 引導設定。OpenTree 不重新實作 OAuth，完全委託 Claude CLI。
**約束條件**：長期無人值守的 bot（Slack 模式），建議使用 API Key（refresh token 過期需瀏覽器重新登入）。

---

## Decision 4: 無頭環境認證流程

**問題**：無 GUI 環境（Linux server、WSL、Docker）如何完成 Slack App 建立和 Token 認證？

**考慮過的方案**：
- **純手動**：在瀏覽器手動建立 Slack App → 可行但步驟多
- **Manifest URL + 手動貼入 token**：OpenTree 產生 URL，使用者在任意瀏覽器開啟 → ✅ 採用
- **Slack API 自動建立**：需要先有 Configuration Token（先有雞問題） → 淘汰
- **Device Code Flow**：Slack 不支援 RFC 8628 → 不可行

**最終選擇**：Manifest URL + 手動貼入 token
**決策依據**：
1. Slack Bot Token (`xoxb-`) 和 App Token (`xapp-`) 永久不過期，一次性貼入即可
2. Manifest URL 大幅簡化 App 建立流程（一鍵填入所有設定）
3. 任何有瀏覽器的設備都能完成，不限定在安裝 OpenTree 的機器上
**Secret 存儲**：`.env` + 權限 600（與 DOGI 一致，未來可疊加加密層）。

---

## Decision 5: 互動模式（TUI）支援

**問題**：OpenTree 是否應該支援 Claude Code 的互動 TUI 模式？

**考慮過的方案**：
- **v1.0 就支援 TUI + Slack 雙模式** → 淘汰，TUI 下安全邊界不可靠
- **只支援 Slack headless** → ✅ v1.0 採用
- **TUI 列入中期路線圖** → ✅ 等 Claude Code 企業功能成熟

**最終選擇**：v1.0 只支援 Slack headless，TUI 列入中期路線圖
**決策依據**：
1. Claude Code 目前無 admin-locked settings，互動模式下使用者可修改 settings.json、toggle sandbox、修改 CLAUDE.md
2. OpenTree 的核心賣點是「Admin 設定不可被使用者修改」，TUI 無法保證這點
3. 投入 TUI 安全方案（mount overlay、file watcher）工程量大，且 Windows 不可行
**條件變更觸發**：若 Claude Code 實作 `--managed-settings`、`--lock-sandbox` 或 policy-as-code，重新評估 TUI 支援。

---

## Decision 6: 實作語言

**問題**：OpenTree 應該用什麼語言實作？未來要能封裝成 Windows 二進位。

**考慮過的方案**：
- **Python（現階段）**：開發最快，所有邏輯已有 DOGI 參考實作 → ✅ 現階段採用
- **Go（未來重寫）**：Windows 交叉編譯一行指令，goroutine 適合 WebSocket → ✅ 未來首選
- **Rust**：binary 最小、記憶體安全 → 淘汰，學習曲線陡、交叉編譯複雜、開發速度慢 1.5-2x
- **Node.js SEA**：與 Claude Code 技術棧一致 → 淘汰，binary 30MB+、antivirus 問題嚴重

**最終選擇**：漸進式遷移
```
Phase 0 (Now)       → Python prototype
Phase 1 (v1.0)      → Python + PyInstaller
Phase 2 (v1.x)      → Go CLI launcher + Python core（如有 Windows 非開發者需求）
Phase 3 (v2.0)      → Full Go（如架構穩定 6+ 個月且有效能瓶頸）
```
**決策依據**：
1. 功能仍在快速迭代，過早選語言是 Premature Optimization
2. OpenTree 效能瓶頸在 Claude API 延遲而非 wrapper 本身
3. 先投資「讓架構可重寫」— 模組間 JSON CLI 介面、安全邏輯純函數化
**約束條件**：現階段為未來重寫做準備 — 模組間用 CLI/JSON 通訊而非 Python import。

---

## 決策總覽

| # | 問題 | 決策 | 狀態 |
|---|------|------|------|
| 0 | 核心架構 | 薄 wrapper + Claude Code CLI runtime | ✅ 確認 |
| 1 | Manifest 格式 | 自定義 `opentree.json`，命名參照 npm | ✅ 確認 |
| 2 | 安全設定 | project-level settings + wrapper 覆蓋 | ✅ 確認 |
| 3 | 認證模式 | Auto-detect（API Key > OAuth session） | ✅ 確認 |
| 4 | 無頭認證 | Manifest URL + 手動貼入 token | ✅ 確認 |
| 5 | 互動模式 | v1.0 Slack only，TUI 列入中期路線圖 | ✅ 確認 |
| 6 | 實作語言 | Python → 漸進式遷移到 Go | ✅ 確認 |

## 先行決策（訪談階段確認）

| 問題 | 決策 |
|------|------|
| 模組系統 | 自有格式（資料夾 + manifest），不用 Claude plugins |
| 模組安裝 | git clone |
| Slack 連線 | 方案 B：各自建 App，各自 bot 名稱 |
| AI 後端 | Claude Code only，模組格式留開放性 |
| 安全邊界 | Admin 預設，使用者不可修改但可在範圍內擴充 |
| 多租戶 | 不需要，每個 bot 圍繞單一使用者 |
| 預裝模組 | 人格、護欄、記憶、排程、Slack、audit-logger |
