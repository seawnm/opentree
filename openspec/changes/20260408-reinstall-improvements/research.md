# Research: Bot Reinstall Improvements

## 調研背景

bot_walter 刪除重裝過程遇到 3 個問題，需分析 DOGI 做法和業界最佳實務，設計改進方案。

## DOGI 可借鑑的模式

### .env 處理
- 4 層載入：`.env.{profile}` > `.env` > `config.env.local` > `config.env`
- 用 `dotenv_values()` 讀取（不寫 os.environ），再用 `load_dotenv()` 按順序載入
- run.sh 自動 `chmod 600` .env 檔案
- 子進程用白名單傳遞環境變數（`_ENV_WHITELIST`）

### 進程管理
- Exit code 約定：0=重啟、42=永久停止
- Signal handler 只 set `threading.Event()`，不做阻塞操作
- Graceful shutdown：drain 30s → close receiver → 清理 PID → 停排程
- PID file 在 `data/bot.pid`，bot 寫入、shutdown 時刪除
- Watchdog：bash subshell，每 30s 檢查 heartbeat，超時 120s → SIGTERM → 40s → SIGKILL
- Preflight check：`python -c "from config import config"`，驗證核心模組可載入

### 目錄初始化
- Config `__post_init__` 中 `logs_dir.mkdir(exist_ok=True)`
- `_ensure_team_data_dir()` 啟動時建立完整結構
- 所有 mkdir 都帶 `exist_ok=True`（避免 TOCTOU race）

## 網路最佳實務

### Stop 指令
- PM2 模式：SIGTERM → 等待 kill_timeout → SIGKILL
- PID file + flock 結合使用（flock 防多實例、PID file 供 stop 用）
- terminate 後必須 wait()，否則產生 zombie
- flag file 作為輕量替代/備援

### .env 分層（dotenv-flow）
- 優先順序：`.env.defaults` < `.env` < `.env.local` < `.env.{NODE_ENV}` < `.env.{NODE_ENV}.local`
- 遷移策略：保留現有 .env 作為 local config，另建 .env.defaults
- VCS 追蹤：defaults/env 追蹤、.local 不追蹤

### PID 管理
- **專家共識**：flock 優於純 PID file（原子性、自動釋放、無 stale 問題）
- Stale PID 偵測：`kill -0` + `/proc/$PID/cmdline` 驗證
- "Never Delete PID Files" — 用 flock 判斷存活，不靠檔案刪除
- 三者各司其職：flock（singleton）+ wrapper.pid（stop 用）+ bot.pid（watchdog 用）

## 調研結論

### Fix 1: init 補 `data/logs/`
- DOGI 在 Config `__post_init__` 中建立 logs 目錄
- opentree 應在 init 的目錄列表中加入 `data/logs`（一行改動）

### Fix 2: legacy .env 遷移
- 參考 dotenv-flow 的遷移策略：偵測 legacy .env 自動遷移到 .env.local
- DOGI 的多層 .env 設計可借鑑，但 opentree 已有三層夠用
- 關鍵：init 端遷移（根因）+ bot 端 fallback（防禦）

### Fix 3: `_load_tokens` fallback
- 參考 DOGI 的 `_resolve_profile()` 用 `dotenv_values()` 先讀再決定
- 提取 `_is_placeholder()` 函式，load 後若為 placeholder 再查 legacy .env

### Fix 4+5: wrapper.pid + stop 指令
- 參考 DOGI 的 PID file 管理（bot.pid）+ exit code 約定（42=永久停止）
- 新增 wrapper.pid（opentree 獨有需求，DOGI 不需要因為它沒有外部 stop 指令）
- run.sh 已用 flock（singleton），加 wrapper.pid 供 stop 指令定位 PID
- stop flag 作為 SIGTERM 的備援
