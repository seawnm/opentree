# Proposal: Bot Reinstall Improvements

## Requirements (user's original words, verbatim)

> 請閱讀 opentree 專案程式碼，並刪除 bot walter，重新安裝
> 反思這次遇到的問題，下次如何能避免

## Problem

bot_walter 刪除重裝過程中遇到 3 個問題：

1. **進程終止困難**：無 `opentree stop` 指令，無 wrapper.pid，`pkill -f` 匹配太廣易誤殺自身 shell，wrapper auto-restart 導致多輪操作才能停止
2. **init 缺 `data/logs/`**：`opentree init` 建立目錄時遺漏 `data/logs/`，`nohup bash run.sh >> data/logs/wrapper.log` 的 redirect 在 run.sh 的 mkdir 之前執行 → 靜默失敗
3. **Token 載入不相容**：`init --force` 無條件產生含 placeholder 的 `.env.defaults`，新版三層載入跳過 legacy `.env`，bot 讀到 placeholder token 啟動失敗

## Solution

### Fix 1: init 補齊 `data/logs/` 目錄
- `init.py` subdir tuple 加入 `"data/logs"`

### Fix 2: init 自動遷移 legacy `.env` → `.env.local`
- 偵測 legacy `.env` 含真實 token → 複製為 `.env.local`
- `.env.local` 已存在 → 不覆寫，輸出手動遷移指引

### Fix 3: `_load_tokens` placeholder fallback
- 三層 merge 後若 token 仍為 placeholder 且 legacy `.env` 存在 → fallback 載入
- 提取 `_is_placeholder()` 共用函式

### Fix 4: run.sh wrapper.pid + stop flag
- flock 成功後寫 `wrapper.pid`，cleanup 時刪除
- while 迴圈開頭檢查 `.stop_requested` flag

### Fix 5: 新增 `opentree stop` CLI 指令
- 讀 wrapper.pid → 驗證 PID → 寫 stop flag → SIGTERM → 等待 → 超時 SIGKILL → 清理

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `src/opentree/cli/init.py` | Modified | Fix 1: data/logs + Fix 2: .env migration |
| `src/opentree/runner/bot.py` | Modified | Fix 3: _is_placeholder + fallback |
| `src/opentree/templates/run.sh` | Modified | Fix 4: wrapper.pid + stop flag |
| `src/opentree/cli/lifecycle.py` | **New** | Fix 5: stop command |
| `src/opentree/cli/main.py` | Modified | Fix 5: register stop |
| `tests/test_init.py` | Modified | Fix 1+2 tests |
| `tests/test_bot.py` | Modified | Fix 3 tests |
| `tests/test_run_sh.py` | **New** | Fix 4 tests |
| `tests/test_lifecycle.py` | **New** | Fix 5 tests |

## Risk

- **Low**: Fix 1 是一行改動，exist_ok=True 不影響既有目錄
- **Low**: Fix 2 遷移只在 legacy .env 存在且 .env.local 不存在時觸發
- **Low**: Fix 3 fallback 只在 placeholder 偵測到時觸發，正常路徑不受影響
- **Medium**: Fix 4 修改 run.sh 模板，已部署的 instance 需 `opentree init --force` 更新
- **Medium**: Fix 5 新增 CLI 指令，signal 操作需注意權限和 PID reuse
