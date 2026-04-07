# Execution Plan: Bot Reinstall Improvements

> 建立日期：2026-04-08
> 狀態：**全部完成**

## 背景

bot_walter 刪除重裝過程中遇到 3 個問題，需修正 opentree 專案程式碼：

1. **進程終止困難**：無 `opentree stop` 指令，無 wrapper.pid，pkill 易誤殺
2. **init 缺 `data/logs/`**：nohup redirect 在 run.sh mkdir 之前執行 → 靜默失敗
3. **Token 載入不相容**：init --force 產生 placeholder .env.defaults，legacy .env 被忽略

## 進度追蹤

- [x] Batch 1: Fix 1 (init data/logs) ✅
- [x] Batch 1: Fix 2 (legacy .env migration) ✅
- [x] Batch 1: Fix 3 (_load_tokens fallback) ✅
- [x] Batch 1: Code review 通過 ✅（2 HIGH + 2 MEDIUM 修正）
- [x] Batch 1: 125 tests passed, init.py 88%, bot.py 95% ✅
- [x] Batch 2: Fix 4 (wrapper.pid + stop flag) ✅
- [x] Batch 2: Fix 5 (opentree stop CLI) ✅
- [x] Batch 2: Code review 通過 ✅（APPROVE: 0 CRITICAL/HIGH）
- [x] Batch 2: 151 tests passed (Batch 1+2 合計) ✅
- [x] 全量測試: 1310 passed, 89% coverage ✅
- [x] openspec 文件完成 ✅
- [ ] CHANGELOG 更新（待 commit 時處理）

## 測試結果

| 測試集 | 數量 | 狀態 |
|--------|------|------|
| test_init.py（Batch 1 新增） | 7 | ✅ |
| test_bot.py（Batch 1 新增） | 12 | ✅ |
| test_run_sh.py（Batch 2 新增） | 8 | ✅ |
| test_lifecycle.py（Batch 2 新增） | 18 | ✅ |
| 全量測試（含既有） | 1310 | ✅ |
| 覆蓋率 | 89% | ✅ |

## Agent 交互歷程

### Batch 1

#### 1. 研究階段（2 agent 並行）
- **DOGI 研究 agent**：分析 slack-bot 的 .env 4 層載入、PID 管理、目錄初始化模式
  - 發現：DOGI 在 Config `__post_init__` 就 mkdir logs
  - 發現：DOGI 的 `_ENV_WHITELIST` 白名單機制可借鑑但 opentree 不需要
- **網路最佳實務 agent**：搜尋 dotenv-flow、PM2、PID file 管理
  - 發現：dotenv-flow 的分層模式與 opentree 設計完全吻合
  - 發現："Never Delete PID Files" — 用 flock 判斷存活
  - 發現：PID file + flock + flag file 三層機制各司其職

#### 2. 設計+推演（1 agent）
- 14 個場景 + 3 個組合場景，全部通過

#### 3. TDD 實作（worktree agent）
- 新增 19 個測試，全部通過

#### 4. Code Review（1 agent）
- 2 HIGH + 2 MEDIUM + 2 LOW
  - HIGH-1: `_validate_not_placeholder` 雙重掃描 → 改用 next()
  - HIGH-2: 遷移成功後無提示刪除 legacy .env → 加入 hint
  - MEDIUM-1: 缺 force 保留日誌測試 → 已補
  - MEDIUM-2: 缺無 legacy .env 測試 → 已補
- 修正後 125 tests passed

### Batch 2

#### 1. 設計+推演（1 agent）
- Fix 4: 7 個場景全通過
- Fix 5: 11 個場景全通過
- 推演中發現 2 個設計問題：
  - `_process_alive` 需處理 `PermissionError`（返回 True）
  - SIGKILL wrapper 後需追殺 orphan bot

#### 2. TDD 實作（worktree agent）
- 新增 26 個測試，1310 全量通過，89% 覆蓋率

#### 3. Code Review（1 agent）
- APPROVE: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 3 LOW
  - MEDIUM-1: test_match 有 dead code（可後續清理）
  - MEDIUM-2: 缺 PermissionError on SIGTERM 整合測試（真實部署場景，可後續補齊）
  - LOW: 移除 unused logger（已修正）

## 檔案變更總覽

| 檔案 | 類型 | 說明 |
|------|------|------|
| `src/opentree/cli/init.py` | 修改 | Fix 1: data/logs dir + Fix 2: .env migration |
| `src/opentree/runner/bot.py` | 修改 | Fix 3: _is_placeholder + fallback |
| `src/opentree/templates/run.sh` | 修改 | Fix 4: wrapper.pid + stop flag |
| `src/opentree/cli/lifecycle.py` | **新增** | Fix 5: stop command |
| `src/opentree/cli/main.py` | 修改 | Fix 5: register stop command |
| `tests/test_init.py` | 修改 | Fix 1+2 測試 |
| `tests/test_bot.py` | 修改 | Fix 3 測試 |
| `tests/test_run_sh.py` | **新增** | Fix 4 測試 |
| `tests/test_lifecycle.py` | **新增** | Fix 5 測試 |

## 後續追蹤（Next Steps）

- [ ] 補齊 MEDIUM issue: PermissionError on SIGTERM 整合測試
- [ ] 補齊 MEDIUM issue: wrapper.pid identity 驗證失敗 fallback 測試
- [ ] 清理 test_match dead code
- [ ] 更新 DEPLOYMENT.md 加入 `opentree stop` 文件
- [ ] 在 bot_walter 實例上實際驗證 `opentree stop`
