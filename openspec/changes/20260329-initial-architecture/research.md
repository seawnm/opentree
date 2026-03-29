# Research: OpenTree 初始架構 — 6 個核心問題調研

## 調研背景

OpenTree 架構規劃過程中，6 個關鍵技術問題需要調研才能做決策。本文件記錄完整的調研過程、候選方案比較、淘汰原因。

---

## 1. Manifest 格式標準

### 調研目標
找到既有的 manifest 標準，避免完全自製。

### 候選方案

#### 1.1 Claude Code plugin.json

**來源**：ECC（Everything Claude Code）的 `.claude-plugin/plugin.json`

```json
{
  "name": "everything-claude-code",
  "version": "1.8.0",
  "description": "...",
  "author": {"name": "...", "url": "..."},
  "homepage": "...",
  "repository": "...",
  "license": "MIT",
  "keywords": [...]
}
```

**調研發現**：
- ECC 的 `PLUGIN_SCHEMA_NOTES.md` 記錄了大量 undocumented 陷阱
- agents 欄位必須是 array，不能用目錄路徑
- hooks 欄位經歷 4 次 add/remove 循環（不穩定）
- 驗證器錯誤訊息模糊（generic "Invalid input"）
- 格式被 Anthropic 控制，隨版本變動

**評估**：❌ 不採用 — 驗證器不穩定，OpenTree 的需求（sandbox 權限、lifecycle hooks）無法原生表達

#### 1.2 npm package.json

**優點**：全球最廣泛使用的套件 manifest，工具鏈豐富
**缺點**：語義錯位 — OpenTree 模組不一定是 Node.js 專案；`dependencies` 語義是 npm 套件而非模組依賴

**評估**：⚠️ 可行但不自然

#### 1.3 ECC marketplace.json

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "plugins": [{"name": "...", "source": "./", "category": "workflow"}]
}
```

**評估**：❌ marketplace 分發專用，不適合作為模組 manifest

#### 1.4 OpenCode opencode.json

**特色**：rich agent 定義（description、mode、model routing、tool permissions）
**評估**：⚠️ 參考價值高，但專為 OpenCode 平台設計

#### 1.5 自定義 opentree.json（最終採用）

命名參照 npm 慣例（name/version/description/author/license），欄位精確對應 OpenTree 需求。

### 調研結論

採用自定義 `opentree.json`。欄位命名沿用 npm 慣例降低學習成本，但 schema 完全自主。參考了 ECC 的多層 manifest 策略（不禁止模組額外放 plugin.json 或 package.json）。

---

## 2. 多使用者同機器 + 安全設定路徑

### 調研目標
找到讓 managed-settings 在任意路徑生效的方法，或找到替代方案。

### Claude Code 設定層級

```
優先順序（高 → 低）：
1. managed-settings (/etc/claude-code/managed-settings.json) ← 不可覆寫
2. user settings    (~/.claude/settings.json)
3. project settings (.claude/settings.json)               ← 隨 cwd 載入
```

### 候選方案

| 方案 | 說明 | 評估結果 | 未採用原因 |
|------|------|----------|------------|
| A. 統一最嚴格的 superset | 所有使用者共用一份 managed-settings（取最嚴限制） | ❌ | 使用者越多越嚴格，最終不可用；資訊洩漏 |
| B. OS namespace 隔離 | 每人跑在 mount namespace，bind mount 不同 managed-settings | ⚠️ | 需要 root；Windows 完全不支援 |
| C. 啟動時 swap + 鎖 | 搶鎖 → 寫入 → 啟動 Claude → 放鎖 | ❌ | 長任務 = 長時間鎖定 = 單工；race condition |
| D. 等待 `--managed-settings-path` | GitHub #33857 已有請求 | ❌ | 目前不存在，時程不明 |
| **E. project-level settings** | wrapper 動態產生 `.claude/settings.json` | ✅ 採用 | — |

### DOGI 驗證

DOGI bot 的 `permission_manager.py` 已在生產環境使用 project-level settings + 啟動時覆蓋模式超過數月，驗證可行。每次處理任務前 `ensure_workspace()` 重新產生 `settings.json`。

### 調研結論

放棄 managed-settings，採用 project-level `.claude/settings.json` + wrapper 啟動時覆蓋。犧牲「不可覆寫」保證，換取：任意路徑、無需 root、跨平台、每人獨立。

在 OpenTree 的威脅模型中（單一使用者 = bot 擁有者 = 有 SSH 權限的人），managed-settings 的「不可覆寫」本身是 theater security。

---

## 3. Claude Code 認證模式

### 調研目標
確認 Claude Code CLI 的兩種認證模式差異，以及 OpenTree 如何處理。

### 兩種模式對比

| 面向 | API Key 模式 | 訂閱模式（OAuth） |
|------|-------------|-----------------|
| 認證方式 | 環境變數 `ANTHROPIC_API_KEY` | OAuth 2.0 瀏覽器登入 |
| 計費 | 按用量（token-based） | 月費制（Max $100/Pro $20） |
| Session 存儲 | 無狀態 | `~/.claude/` 下的 OAuth token |
| Token 過期 | 永不過期 | Access token 數小時，Refresh token 數月 |
| Headless 支援 | 完美 | 首次需瀏覽器 |

### Bot 場景風險

訂閱模式下 refresh token 過期時需要瀏覽器重新登入，24/7 bot 無法自動處理。

### 調研結論

採用 auto-detect：有 API Key 用 API Key，否則用 OAuth session。文件中明確建議長期無人值守的 bot 使用 API Key。

---

## 4. 無頭認證

### 調研目標
確認各服務在無 GUI 環境下的認證方案。

### 各服務認證方式

| 服務 | Token 類型 | 有效期 | 無頭方案 |
|------|-----------|--------|---------|
| Claude Code（API Key） | `sk-ant-*` | 永久 | 直接貼入 |
| Claude Code（訂閱） | OAuth token | 數月 | SSH tunnel 或改用 API Key |
| Slack Bot Token | `xoxb-*` | 永久 | Manifest URL + 手動貼入 |
| Slack App Token | `xapp-*` | 永久 | 同上 |

### Device Code Flow 調研

Slack 不支援 RFC 8628 Device Authorization Grant，僅支援 Authorization Code Grant。但 Slack token 不過期，一次性貼入即可，不需要 Device Code Flow。

### 調研結論

Slack 認證：Manifest URL（OpenTree 產生 URL，使用者在任意瀏覽器開啟建立 App，貼回 token）。
Claude 認證：無頭環境推薦 API Key，有 GUI 則自動 OAuth。

---

## 5. 互動模式（TUI）可行性

### 調研目標
評估 Claude Code 互動模式在 OpenTree 安全框架下的可行性。

### 安全威脅分析

| 威脅 | Slack (headless) | TUI (interactive) |
|------|------------------|-------------------|
| 修改 settings.json | 不可能（bot 每次重新產生） | **可能**（使用者有 terminal 存取） |
| 繞過 sandbox | 不暴露 toggle | **可能**（`/sandbox` 可 toggle） |
| 修改 CLAUDE.md | deny rule 保護 | **可能**（可繞過 deny rule） |
| 修改 hooks | deny rule 保護 | **可能** |

### 根本問題

Claude Code 目前沒有「admin-locked settings」機制。互動模式下使用者對 terminal 有完整控制，所有 project-level 的安全設定都可被修改。

### 調研結論

v1.0 只支援 Slack headless 模式。中期監控 Claude Code 企業功能發展（`--managed-settings`、`--lock-sandbox`），一旦支援不可覆寫設定，即可安全開放 TUI。

---

## 6. 二進位封裝語言選擇

### 調研目標
評估 Rust、Go、Node.js、Python 各語言的跨平台二進位打包能力。

### 候選方案

| 面向 | Rust | Go | Node.js (SEA) | Python (PyInstaller) |
|------|------|-----|---------------|---------------------|
| Binary size | 2-3MB | 5-8MB | 30MB+ | 50MB+ |
| Startup time | 快 | 最快 | 慢 | 最慢 |
| Windows 交叉編譯 | 需要 cross+xwin | 一行指令 | 不原生 | 困難 |
| 學習曲線 | 陡峭 | 溫和 | 已知 | 已知 |
| TUI library | ratatui | bubbletea | ink | rich/textual |
| 業界案例 | Goose (Block) | OpenCode (SST) | Claude Code | — |

### 業界參考

- **Goose**（Block）：Rust 實作，AI agent framework
- **OpenCode**（SST）：Go 實作，Claude Code 的 TUI 替代品
- **Claude Code**：Node.js + npm 分發

### 調研結論

現階段維持 Python（功能仍在快速迭代）。若未來必須選編譯語言，Go 優於 Rust（Windows 交叉編譯是硬需求，Go 體驗遠優於 Rust；OpenTree 效能瓶頸在 Claude API 延遲而非 wrapper）。

---

## 調研來源

- Claude Code 官方文件：cli-reference.md、headless.md、sandboxing.md、memory.md、interactive-mode.md、server-managed-settings.md
- ECC repository：plugin.json、PLUGIN_SCHEMA_NOTES.md、marketplace.json、opencode.json
- DOGI bot 原始碼：permission_manager.py、claude_runner.py、config.py
- GitHub issue #33857（custom settings path request）
- Rust vs Go CLI 比較：JetBrains Blog、Medium、cuchi.me
- Rust 跨平台打包：rust-cli.github.io、Rust forum
- Node.js SEA：Node.js 25.5 --build-sea
