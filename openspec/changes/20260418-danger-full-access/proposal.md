# Proposal: `danger-full-access` Sandbox Mode Activation

**日期**：2026-04-18
**作者**：walter
**狀態**：已實作

---

## 需求背景

部署 COGI bot 實例時，需要讓 Codex CLI 以完全無沙箱模式執行，使 bot 能夠存取宿主機所有檔案與路徑（例如：讀取本機 git 倉庫、修改任意檔案、執行系統指令）。現有 `codex_sandbox: "danger-full-access"` 設定欄位雖已定義在 `RunnerConfig`，但從未被任何執行路徑消費，等同虛設。

**使用場景**：部署給系統管理員使用、需要完整宿主機存取的 bot 實例。這類實例不服務一般使用者，本身即為安全邊界內的授信系統。

---

## 變更範圍

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `src/opentree/runner/codex_process.py` | Modified | 新增 `danger-full-access` 執行路徑（`--dangerously-bypass-approvals-and-sandbox`，無 bwrap） |
| `src/opentree/runner/dispatcher.py` | Modified | 兩處 `sandboxed=True` 硬編碼改為讀取 `runner_config.codex_sandbox` |
| `src/opentree/runner/bot.py` | Modified | `check_bwrap_or_raise()` 改為條件式（`danger-full-access` 時跳過） |
| `src/opentree/templates/.env.local.example` | Added | 新增 `.env.local.example` 獨立模板檔，供 `opentree init` 寫出給 Owner 填入 |
| `src/opentree/cli/init.py` | Modified | `_write_env_local_example()` 改從模板檔讀取，fallback 至最小 inline stub |

---

## 影響分析

**向後相容性**：完全相容。預設值 `codex_sandbox: "workspace-write"` 行為與修改前完全相同，`sandboxed=True` 路徑不受影響。

**安全影響**：
- `danger-full-access` 模式下無任何沙箱保護，Codex CLI 可讀寫宿主機所有路徑。
- 此模式需 Owner 在 `runner.json` 中明確設定，不可能被使用者意外啟用。
- guardrail 模組（deny 規則）在此模式下仍有效——Codex CLI 的行為受 `settings.json` 約束，只是沒有 bwrap 的 OS 層隔離。

**不影響的部分**：
- 現有所有 bot 實例（`workspace-write` 模式）
- `opentree stop` / `opentree module refresh` 等管理指令
- Socket Mode 接收器與心跳機制

---

## 驗收標準

1. `runner.json` 設定 `"codex_sandbox": "danger-full-access"` 時，bot 啟動不檢查 bwrap
2. Codex CLI 以 `--dangerously-bypass-approvals-and-sandbox` 啟動（可由 process list 確認）
3. Bot 可存取 `/mnt/e/` 等非 workspace 路徑
4. 預設 (`workspace-write`) 模式行為不變
5. T10 安全測試（拒絕讀取 `.env.local`）仍通過——guardrail deny 規則有效
