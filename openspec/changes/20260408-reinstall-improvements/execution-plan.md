# Execution Plan: Bot Reinstall Improvements

> 建立日期：2026-04-08
> 狀態：**執行中**

## 背景

bot_walter 刪除重裝過程中遇到 3 個問題，需修正 opentree 專案程式碼：

1. **進程終止困難**：無 `opentree stop` 指令，無 wrapper.pid，pkill 易誤殺
2. **init 缺 `data/logs/`**：nohup redirect 在 run.sh mkdir 之前執行 → 靜默失敗
3. **Token 載入不相容**：init --force 產生 placeholder .env.defaults，legacy .env 被忽略

## 設計原則

- 參考 DOGI（slack-bot）的現有做法，不重複造輪子
- 遵循 opentree 現有的 coding style 和測試慣例
- TDD：先寫測試 → 實作 → code review

## 修改項目

### Fix 1: init 補齊 `data/logs/` 目錄（1 行改動）
- 檔案：`src/opentree/cli/init.py` 第 382-387 行
- 改動：subdir tuple 加入 `"data/logs"`

### Fix 2: init 自動遷移 legacy `.env` → `.env.local`（~20 行）
- 檔案：`src/opentree/cli/init.py` 第 592 行前
- 邏輯：偵測 legacy .env 含真實 token → 複製為 .env.local → 輸出遷移訊息
- Edge case：.env.local 已存在 → 不覆寫，輸出手動遷移指引

### Fix 3: `_load_tokens` placeholder fallback（~10 行）
- 檔案：`src/opentree/runner/bot.py` 第 207-221 行
- 邏輯：三層 merge 後若 token 仍為 placeholder 且 legacy .env 存在 → fallback 載入
- 提取 `_is_placeholder()` 共用函式

### Fix 4: run.sh 新增 wrapper.pid + stop flag（~8 行 shell）
- 檔案：`src/opentree/templates/run.sh`
- 改動：lock 成功後寫 wrapper.pid，cleanup 時刪除；restart 迴圈前檢查 .stop_requested

### Fix 5: 新增 `opentree stop` CLI 指令（~80 行）
- 檔案：新增 `src/opentree/cli/lifecycle.py` + 修改 `cli/main.py`
- 邏輯：讀 wrapper.pid → 寫 stop flag → SIGTERM → 等待 → 超時 SIGKILL → 清理

## 執行批次

### Batch 1（預估 20 分鐘）— Fix 1 + Fix 2 + Fix 3
- 較小的改動，集中在 init.py 和 bot.py
- 先研究 DOGI 的 .env 處理做法
- 設計 → 推演 → 開發 → 測試 → review

### Batch 2（預估 25 分鐘）— Fix 4 + Fix 5
- run.sh 模板修改 + 新增 stop 指令
- 先研究 DOGI 的 run.sh 和 shutdown 機制
- 設計 → 推演 → 開發 → 測試 → review

## Agent 分工

| Agent | 角色 | 用途 |
|-------|------|------|
| researcher | 研究 DOGI 做法 + 網路最佳實務 | 設計前調研 |
| designer-simulator | 設計方案 + 推演正常/edge case | 確認設計無缺陷 |
| implementer | TDD 開發（寫測試 → 實作） | 程式碼撰寫 |
| code-reviewer | code review + 安全審查 | 品質把關 |

## 進度追蹤

- [ ] Batch 1: Fix 1 (init data/logs)
- [ ] Batch 1: Fix 2 (legacy .env migration)
- [ ] Batch 1: Fix 3 (_load_tokens fallback)
- [ ] Batch 1: Code review 通過
- [ ] Batch 1: 測試覆蓋率 >= 80%
- [ ] Batch 2: Fix 4 (wrapper.pid + stop flag)
- [ ] Batch 2: Fix 5 (opentree stop CLI)
- [ ] Batch 2: Code review 通過
- [ ] Batch 2: 測試覆蓋率 >= 80%
- [ ] openspec 文件完成
- [ ] CHANGELOG 更新

## Agent 交互歷程

（隨執行進度更新）
