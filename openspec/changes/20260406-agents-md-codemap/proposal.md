# Proposal: 建立 AGENTS.md Codemap

## 需求背景

### 使用者原話（不可改寫）
> 我需要頻繁重新閱讀並修改這個專案，有比較快的方式可以讓你理解這個專案程式嗎？

### 問題分析
- opentree 目前沒有 CLAUDE.md 也沒有 AGENTS.md
- README.md 品質不錯（184 行），但 Claude Code 不會自動載入 README.md
- 每次新 session 需要花 ~10 分鐘全量掃描 42 個 Python 檔案（~7,894 行）才能理解專案
- 目前 ecc:update-codemaps skill 的分類邏輯（frontend/backend/database）不適用於 Python CLI 框架

## 變更範圍

| 項目 | 變更類型 | 說明 |
|------|----------|------|
| `AGENTS.md`（專案根目錄） | **新增** | AI-optimized 架構摘要，≤200 行 |
| `openspec/changes/20260406-agents-md-codemap/` | **新增** | 本次變更的 OpenSpec 文件 |

### 不在範圍內
- 不修改 README.md（AGENTS.md 引用它，不重複內容）
- 不修改任何程式碼
- 不建立 .claude/ 目錄或 CLAUDE.md（使用跨工具標準 AGENTS.md）
- 不改造 ecc:update-codemaps skill（未來可考慮，本次不做）

## 解決方案

### AGENTS.md 設計

**檔名選擇：AGENTS.md**（而非 CLAUDE.md）
- Claude Code、Cursor、Codex 三者都自動載入 AGENTS.md
- 跨工具相容性更好
- 開放標準（Linux Foundation 提出）

**內容設計原則**：
1. Token-lean：≤1000 tokens，表格為主，不貼程式碼
2. 結構導航：子系統 → 目錄 → 職責 → 關鍵檔案
3. 不重複 README：只放 AI 需要的快速上下文，詳細資訊引用 README.md
4. Freshness metadata：頂部標注生成日期和掃描檔案數

**內容結構**（~150-200 行）：
1. Freshness header（generated date, file count, token estimate）
2. 一句話定位 + 版本
3. 子系統對照表（8 個子系統）
4. Runner 執行流程（ASCII flow）
5. 模組系統摘要（10 模組 + 依賴順序）
6. 設計模式清單
7. 跨子系統依賴圖
8. 已知技術債
9. 測試結構
10. 引用連結

### 更新機制

| 層 | 機制 | 說明 |
|----|------|------|
| Primary | Manual | 重大變更後手動編輯或重新生成 |
| Safety net | Freshness metadata | 頂部 `Generated: YYYY-MM-DD`，AI 載入時可判過期 |
| Optional | Pre-commit check | 只檢查 timestamp 是否超過 30 天，不自動重新生成 |

## 影響分析

### 風險評估

| 風險 | 等級 | 緩解策略 |
|------|------|----------|
| AGENTS.md 與程式碼脫節 | 🟡 中 | freshness metadata + 版本更新時 refresh |
| 內容過多超過 token 預算 | 🟢 低 | 嚴格控制 ≤200 行 |
| 跨工具格式差異 | 🟢 低 | AGENTS.md 是開放標準 |

### 預期效果
- 新 session 載入時間：10 分鐘 → <1 秒（自動載入 AGENTS.md）
- AI 理解準確度：依賴完整掃描 → 直接獲得結構化上下文
- 跨工具一致性：Cursor / Codex 開啟同一專案也能受益
