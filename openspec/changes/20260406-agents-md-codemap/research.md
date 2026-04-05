# Research: AGENTS.md Codemap — 格式選擇與更新機制調研

## 調研背景

opentree 專案每次新 AI session 需花 ~10 分鐘全量掃描才能理解架構。需要一份 AI-optimized 的架構摘要自動載入。本調研涵蓋兩個核心問題：(1) 檔案格式與命名、(2) 長期更新機制。

---

## 1. 檔案命名與格式

### 調研目標
確定最佳的檔案命名和內容格式，使 AI coding agent 能在 session 啟動時自動獲得專案上下文。

### 候選方案

#### CLAUDE.md
- Claude Code 原生支援，自動載入
- 僅 Claude Code 識別，Cursor / Codex 不讀取
- 評估：⚠️ 功能可用但跨工具性差

#### AGENTS.md
- Claude Code v1.7.0+ 支援自動載入
- Cursor IDE、Codex CLI、OpenCode 都識別
- Linux Foundation 提出的開放標準
- 評估：✅ 採用

#### CLAUDE.md + AGENTS.md 雙檔案
- CLAUDE.md 放 Claude 專用指令，AGENTS.md 放通用架構
- 維護成本翻倍，內容易重複
- 評估：❌ 過度設計，opentree 不需要

#### docs/CODEMAPS/*.md（ecc:update-codemaps 模式）
- 分類為 frontend / backend / database / integrations / workers
- 分類邏輯基於路徑 pattern（`app/`, `pages/`, `api/`, `models/`）
- opentree 是 Python CLI 框架，子系統（cli/, core/, generator/, manifest/, registry/, runner/）無法對應
- 評估：❌ 分類模型不適用

### 調研結論
採用單一 `AGENTS.md`，跨工具相容且維護成本最低。

---

## 2. 內容格式原則

### 調研目標
確定 token-lean 的內容格式，在 ≤1000 tokens 內傳達足夠的架構上下文。

### 參考分析

| 專案 | 檔案 | 行數 | 風格 | 特點 |
|------|------|------|------|------|
| ECC | AGENTS.md | 167 行 | 綜合指引型 | agents 列表、coding style、workflow、architecture |
| ralph-workspace | AGENTS.md | 137 行 | 操作手冊型 | SOP、bash 指令、critical rules |
| claude-code-transcripts | AGENTS.md | 15 行 | 極簡型 | 只列測試和 commit 習慣 |

### ECC codemap 的 7 個 token-lean 原則
1. 結構而非實作細節 — 只描述「是什麼」和「在哪裡」
2. 路徑 + 簽名 > 完整程式碼 — `src/core/config.py (UserConfig frozen dataclass, 54 lines)`
3. 每個 codemap < 1000 tokens
4. ASCII diagram > 冗長描述
5. Freshness metadata — `Generated: YYYY-MM-DD | Files: 42 | ~800 tokens`
6. 從程式碼生成，非手寫
7. 變更 > 30% 需人工確認

### 調研結論
採用 ECC 的 token-lean 原則，以表格 + ASCII flow 為主，控制在 ≤200 行。

---

## 3. 更新機制

### 調研目標
找到維護 AGENTS.md 新鮮度的最佳策略，平衡維護成本和準確性。

### 候選方案

| 方案 | 複雜度 | 可靠性 | 維護成本 | Token 成本 | 評估 |
|------|--------|--------|----------|------------|------|
| Manual（手動觸發） | 低 | 低（易遺忘） | 低 | 0 | ✅ 採用（primary） |
| Pre-commit hook（驗證） | 中 | 中高 | 中 | 0（只檢查 timestamp） | ✅ 採用（optional） |
| PostToolUse hook | 高 | 低（過度觸發） | 高 | ~25K tokens/session | ❌ 不建議 |
| Scheduled task（排程） | 低 | 中 | 低 | 可控 | ⚠️ 備選 |
| CI/CD（GitHub Action） | 中 | 高 | 中 | 每次 PR | ⚠️ 備選 |

#### Manual（手動觸發）
- 做法：重大變更後手動編輯或用 doc-updater agent 重新生成
- 優點：零開銷，完全可控，不需額外基礎設施
- 缺點：人會忘記更新
- ECC 實際做法：doc-updater agent 本質上也是手動觸發
- 結論：✅ 作為 primary 機制

#### Pre-commit hook（只做驗證）
- 做法：檢查 AGENTS.md 頂部的 `Generated` 日期是否超過 30 天，超過則 warn
- 優點：自動提醒，不阻擋 commit（只 warn 不 block）
- 缺點：需配置 hook，對 opentree 目前的 git 流程增加一步
- 重要：不做 regeneration（pre-commit 中跑 AI 太慢），只做 staleness check
- 結論：✅ 作為 optional safety net

#### PostToolUse hook
- 做法：每次 Edit/Write 後觸發 codemap 更新
- 問題：假設一個 session 有 50 次 Edit/Write，每次消耗 500 tokens = 25,000 tokens/session
- 結論：❌ 過度觸發，成本不合理

#### Scheduled task（排程）
- 做法：每週排程一次 freshness check
- 在 DOGI bot 環境中已有基礎設施（schedule-tool）
- 但 opentree 是獨立專案，不在 bot 管轄範圍
- 結論：⚠️ 如果 opentree 未來也有 bot runtime，可以考慮

#### CI/CD（GitHub Action）
- 做法：PR 時檢查 AGENTS.md 是否過期
- 需要 AI API access 配置
- 結論：⚠️ 團隊開發時再考慮

### 調研結論

採用 **Manual + Freshness metadata** 組合：
1. AGENTS.md 頂部放 `Generated: YYYY-MM-DD` metadata
2. 每次版本發布（CHANGELOG 更新）時同步 refresh AGENTS.md
3. Optional：加 pre-commit hook 做 30 天 staleness warning

---

## 調研來源

- ECC AGENTS.md（/mnt/e/develop/mydev/everything-claude-code/AGENTS.md）
- ECC update-codemaps 指令（commands/update-codemaps.md）
- ECC doc-updater agent（agents/doc-updater.md）
- ECC hooks 設定（hooks/hooks.json）
- ralph-workspace AGENTS.md
- opentree README.md 和現有 openspec 文件
