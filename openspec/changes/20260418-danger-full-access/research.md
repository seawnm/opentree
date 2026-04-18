# Research: `danger-full-access` 實作方案調研

**日期**：2026-04-18
**作者**：walter

---

## 問題一：如何讓 Codex CLI 以無沙箱模式執行？

### 候選方案

#### 方案 A：新增獨立 CLI flag `--no-sandbox`

在 `opentree start` 加一個 `--no-sandbox` flag，每次啟動手動指定。

**優點**：直覺，無需改 config 檔。
**缺點**：
- 每次啟動都要帶 flag，容易遺忘
- 無法透過 `run.sh` wrapper（不帶 flag）自動重啟
- 與現有「設定從 config 讀取」的設計原則不一致

**淘汰原因**：破壞 `run.sh` 自動重啟語意，且 `RunnerConfig` 中已有 `codex_sandbox` 欄位，直接消費更合理。

---

#### 方案 B：消費既有 `RunnerConfig.codex_sandbox` 欄位（已定義但未接線）✅ 採用

`RunnerConfig` 早已定義 `codex_sandbox: str = "workspace-write"`，合法值 `"workspace-write"` 和 `"danger-full-access"` 已在 docstring 中說明。只是三個讀取點都硬編碼為 `True`/`sandboxed=True`，從未實際讀取此欄位。

需要接線的三個點：
1. `dispatcher.py:353` — `CodexProcess(sandboxed=True, ...)` → 讀 config
2. `dispatcher.py:634` — `is_sandboxed=True` → 讀 config
3. `bot.py:127` — 無條件呼叫 `check_bwrap_or_raise()` → 加條件

`codex_process.py` 的 `_build_codex_args()` 再加第三分支：
- `sandboxed=True`（bwrap 內）→ `--dangerously-bypass-approvals-and-sandbox`（避免 nested sandbox）
- `sandboxed=False + workspace-write`（default/none）→ `--full-auto`
- `sandboxed=False + danger-full-access` → `--dangerously-bypass-approvals-and-sandbox`

**優點**：
- 變更最小（~10 行 diff，3 個檔案）
- 完全向後相容，existing config 無需修改
- 與 `runner.json` 設計一致：所有 bot 行為由 config 決定

**淘汰**：無替代方案，直接採用。

---

## 問題二：`.env.local.example` 模板應如何管理？

### 背景

現行 `opentree init` 在 `_write_env_local_example()` 中使用 inline Python 字串寫出 `.env.local.example`。內容為 4 個 key 加上英文註解，已略顯過時（缺少中文說明、缺少 OPENTREE_HOME 等部署常用欄位）。

本次機會：使用 bot_walter 的 `.env.local`（實際部署的模板）作為更完整的參考，更新範本。

### 候選方案

#### 方案 A：繼續使用 inline Python 字串，直接更新字串內容

在 `init.py` 中把 inline string 改成新版內容。

**優點**：改動集中在一個檔案。
**缺點**：
- 多行 Python 字串（含 # 註解、分節）難以維護，縮排容易被 IDE 改動
- 無法用一般文字編輯器直接預覽效果
- 若未來要雙語（中英）、多節、更豐富的說明，inline 字串會越來越難讀

**淘汰原因**：新版內容有 4 個分節、中英雙語、多行註解，inline 管理性差。

---

#### 方案 B：獨立模板檔 `src/opentree/templates/.env.local.example` ✅ 採用

`opentree` 已有 `templates/` 目錄（內含 `run.sh.template`）。將 `.env.local.example` 也移入此目錄，`init.py` 改為讀檔，加 fallback（template 缺失時用最小 inline stub）。

**優點**：
- 模板以純文字管理，可直接預覽、diff、編輯
- 與 `run.sh.template` 一致的設計模式
- `PackageError` 不會造成靜默失敗（fallback stub 仍可工作）
- 未來擴充（多語言、多 provider）容易

**缺點**：需確保 `pyproject.toml` 的 `package-data` 包含 `templates/` 目錄（已確認現有設定涵蓋）。

---

## 決策摘要

| 問題 | 採用方案 | 淘汰方案 |
|------|----------|----------|
| 無沙箱執行 | B（消費既有 config 欄位） | A（新增 CLI flag） |
| .env 模板管理 | B（獨立模板檔） | A（inline 字串） |

---

## 實作後驗證（冒煙測試結果，2026-04-18）

COGI bot（`runner.json: "codex_sandbox": "danger-full-access"`）部署後執行 15 個冒煙測試案例：

| 測試 | 結果 | 備註 |
|------|------|------|
| T1 基本回應 | ✅ Pass | |
| T2 中文回應 | ✅ Pass | |
| T3 角色定位 | ✅ Pass | |
| T4 Markdown 格式 | ✅ Pass | |
| T5 code block | ✅ Pass | |
| T6 多工 | ✅ Pass | |
| T7 Session 記憶 | ✅ Pass | |
| T8 跨 thread 記憶 | ✅ Pass | |
| T9 網路搜尋 | ⚠️ Partial | 3 則新聞已取得，因 Slack 4000 字元限制部分截斷 |
| T10 安全（拒讀 .env） | ✅ Pass | guardrail deny 規則在 danger-full-access 模式下仍有效 |
| T11 錯誤處理 | ✅ Pass | |
| T12 長任務 | ✅ Pass | |
| T13 人設問答 | ✅ Pass | |
| T14 排程測試 | ⚠️ Partial | bot 建立成功，3 分鐘後觸發待確認（測試窗口問題） |
| T15 AGENTS.md 人設 | ✅ Pass | |

**結論**：核心功能（無沙箱執行、guardrail 保護、記憶、多工）全部通過。T9/T14 為獨立問題（輸出截斷、測試時序），與本次 `danger-full-access` 接線無關。
