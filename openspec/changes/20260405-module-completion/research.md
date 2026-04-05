# Research: Module Completion & Project Polish

## 調研背景

專案分析階段（3 個 planner agent 並行）發現 modules/ 目錄的實際狀態與預期不同，需要重新評估任務範圍。

## 候選方案

### 版本號同步策略

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 手動同步（現狀） | 已證明會忘記同步 | 淘汰 — 版本已分歧 |
| B. `importlib.metadata.version()` | ✅ 採用 | — |
| C. `hatch-vcs`（git tag 驅動） | 最自動化 | 需額外依賴、改 build-system、過度工程化 |
| D. 讀取 pyproject.toml | 簡單 | 打包後路徑不可靠 |

### Modules permissions 路徑

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. 修改 manifest 對齊 rules 寫法 | ✅ 採用 | rules 行數多（改動小） |
| B. 搬工具到 `bin/` 目錄 | 需改大量 rules 內容 | 改動量大、風險高 |

### Thread 參與者提醒實作位置

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. PromptContext 新增欄位 + slack hook 處理 | ✅ 採用 | 模組化設計 |
| B. Dispatcher 硬編碼（DOGI 原始做法） | 違反模組化原則 | 淘汰 |

### `is_new_user` 偵測位置

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A. Dispatcher 層計算，透過 PromptContext 傳入 | ✅ 採用 | hook 應避免 I/O |
| B. memory hook 內部偵測 | hook 會被 cache + I/O 不適合 | 淘汰 |

## 調研結論

- 版本號用 `importlib.metadata`（標準庫，零依賴）
- Permissions 路徑修改 manifest（最小改動）
- prompt_hook 機制已完善，只需填入缺失的欄位和邏輯
- Code review 發現 7 個 HIGH/MEDIUM 問題，全部在同一輪修復
