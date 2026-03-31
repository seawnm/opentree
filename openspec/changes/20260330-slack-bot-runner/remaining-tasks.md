# OpenTree Bot Runner — 待辦事項與下一步

> 更新日期：2026-03-31（P2 Simulation fixes done, commit 6d0969c）
> 來源 Thread：betaroom 1774800803.111649

## 已完成項目摘要

### Phase 1: 核心循環（commit 460849d）
- Bot 生命週期（bot.py）、Socket Mode 事件接收（receiver.py）
- 任務分發 + 動態 PromptContext（dispatcher.py）
- Claude CLI subprocess 管理（claude_process.py + stream_parser.py）
- Slack API 封裝、Task Queue、Session 管理
- RunnerConfig（frozen dataclass）

### Phase 2: UX 強化（commit 5199b56 + 0037aa6）
- 進度回報（Block Kit + spinner + token 統計）
- Thread 歷史讀取（滑動視窗 + char 上限截斷）
- 附件下載（sanitize + 大小限制 + cleanup）
- 安全修復：SSRF、path traversal、memory DoS

### Phase 3: 運維（commit 2f22906）
- 日誌系統（daily rotation + console 雙輸出）
- run.sh wrapper（自動重啟、watchdog、crash loop 保護、DNS 檢查）
- `opentree init` 產生 bin/run.sh + config/.env.example

### 合規性修復（commit 7e4bd65）
- Simulation + Code Review 的所有 HIGH issues 已修復
- run.sh: `wait || true` exit code 修復、`$BOT_CMD` 改 bash array
- cleanup() timeout + SIGKILL、handler.close() 洩漏修復
- bot.py: shutdown config 快取、reporter.start() fallback
- file_handler: cleanup_temp 路徑一致性

### P2 Simulation 修復（commit 6d0969c）
- prompt_hook 每次 exec_module → PromptHookCache 啟動時快取（thread-safe）
- PlaceholderEngine `{{` 誤替換 → re.sub single-pass regex（未知 pattern 保留原樣）
- 無磁碟空間監控 → health.py + hourly check + WARNING threshold
- exec_module 記憶體累積 → 由 PromptHookCache 解決（單次載入）

### E2E 實測修復（commit 75915ce）
- SlackResponse 轉換 + Claude CLI 參數修正

### CLAUDE_CONFIG_DIR 驗證（PASS）
- 4 項驗證全部通過：
  - [x] Claude CLI 啟動時尊重 `CLAUDE_CONFIG_DIR` 環境變數
  - [x] 多 bot instance 使用不同 config dir 互不干擾
  - [x] session 資料正確寫入指定路徑
  - [x] settings.json 在指定 config dir 中被正確讀取
- 注意：credentials 需手動複製到 config dir（非自動隔離）

### P1 MEDIUM 修復（commit 75e1181）
- 7 個 MEDIUM issues 全部修復，+34 tests：
  - [x] 超長訊息截斷（Slack 4,000 字元上限）
  - [x] `host` 指令 fallback（`getent hosts` + `ping -c1`）
  - [x] `.env` placeholder sentinel 檢查（攔截 `xoxb-your-bot-token` 等）
  - [x] exit 42 / restart command（更新重啟機制）
  - [x] `init --force` 覆寫警告（interactive confirmation）
  - [x] init transactional install（失敗時 rollback）
  - [x] `log_dir` readonly fallback（stderr fallback）

### 版本發布 v0.2.0
- [x] 更新 `pyproject.toml` version 為 `0.2.0`
- [x] 更新 CHANGELOG `[Unreleased]` -> `[0.2.0] - 2026-03-31`
- [x] Git tag `v0.2.0`

---

## P0 — 必須完成（阻擋部署）— ✅ 全部完成

### CLAUDE_CONFIG_DIR 驗證 — ✅ PASS
- **狀態**：已完成
- **驗證腳本**：`tests/isolation/verify_config_dir.sh`
- **驗證結果**：
  - [x] Claude CLI 啟動時尊重 `CLAUDE_CONFIG_DIR` 環境變數
  - [x] 多 bot instance 使用不同 config dir 互不干擾
  - [x] session 資料正確寫入指定路徑
  - [x] settings.json 在指定 config dir 中被正確讀取
- **備註**：credentials 需手動複製到 config dir（Claude CLI 不自動隔離 credentials）

### E2E 測試剩餘項目 — ✅ 完成
- **狀態**：完成（commits 82eec96, 54db6cc, 72ecc6c, 0fa88d8）
- 已修復：
  - [x] SlackAPI response parsing（`_extract_data` helper）— commit `82eec96`
  - [x] Bot-to-bot @mention（receiver.py 允許其他 bot 的明確 @mention）— commit `82eec96`
  - [x] Shutdown 權限檢查（`admin_users` 設定 + auth check）— commit `82eec96`
  - [x] Heartbeat 在所有事件寫入（before filters）— commit `82eec96`
  - [x] Double heartbeat write（移除 dispatcher 冗餘寫入）— commit `54db6cc`
  - [x] Cross-handler dedup race（single handler + Layer 2 dispatcher dedup）— commit `72ecc6c`
- 已通過：
  - [x] Admin 指令測試 — status（單一回覆確認）
  - [x] Admin 指令測試 — help（單一回覆確認）
  - [x] Claude reply flow（@Bot_Walter 問候 → Claude 回覆）
  - [x] Thread resume（同 thread 第二則訊息，session 保持）
  - [x] Dedup 驗證（同一事件只觸發一次回覆）
- Batch 3 完成（commits 82eec96, 54db6cc, 72ecc6c, 0fa88d8）：
  - [x] Thread 多輪對話測試（A7）— PASS（2 turns，pineapple42 context retained）
  - [x] 並行請求測試（A5）— PASS（3/3：Paris, Tokyo, Brasilia，90s 內全部回覆）
  - [x] run.sh wrapper 測試（A6）— PASS（SIGKILL → exit 137 → wrapper auto-restart，新 PID 31864→32196）
  - [x] ~~DM 訊息測試（A3）~~ — SKIPPED（DOGI message-tool 無法 send DM 到 Bot_Walter）
- 待測項目：
  - [ ] 檔案上傳測試（deferred to P2）
- 已知問題：
  - **WSL2 bytecache**：rsync 部署後必須清理 `__pycache__`（跨檔案系統 timestamp 比較不可靠，stale .pyc 會導致行為不一致）
- **Batch 3 完成。所有可自動化的 E2E 項目已驗證。**

---

## P1 — 高價值 — ✅ 全部完成

### 版本發布 v0.2.0 — ✅ 完成
- [x] 更新 `pyproject.toml` version 為 `0.2.0`
- [x] 更新 CHANGELOG `[Unreleased]` -> `[0.2.0] - 2026-03-31`
- [x] Git tag `v0.2.0`

### CLAUDE_CONFIG_DIR 驗證 — ✅ PASS
- 4 項驗證全部通過（詳見 P0 區塊）
- credentials 需手動複製到 config dir

### P1 MEDIUM Issues — ✅ 全部修復（commit `75e1181`，+34 tests）

#### 已修復的 Phase 2+3 Simulation Issues

| Issue | 修復方式 | 狀態 |
|-------|----------|------|
| 超長訊息不截斷 | Slack 4,000 字元上限截斷 + 分段 | ✅ 已修復 |
| log_dir 唯讀無 fallback | stderr fallback 機制 | ✅ 已修復 |
| bot.py 缺 exit 42 | exit code 42 + restart admin command | ✅ 已修復 |
| reporter.start() 失敗靜默 | 已在 commit 7e4bd65 加 fallback send_message | ✅ 先前已修復 |
| wrapper cleanup() 無 timeout | 已在 commit 7e4bd65 加 timeout | ✅ 先前已修復 |
| bot.py shutdown 重新讀取 config | 已在 commit 7e4bd65 使用快取值 | ✅ 先前已修復 |
| run.sh $BOT_CMD 未引號 | 已在 commit 7e4bd65 改用 bash array | ✅ 先前已修復 |

#### 已修復的 Code Review Issues

| Issue | 修復方式 | 狀態 |
|-------|----------|------|
| run.sh `host` 指令容器不可用 | `getent hosts` + `ping -c1` fallback chain | ✅ 已修復 |
| `init --force` 覆寫使用者目錄 | interactive confirmation 警告 | ✅ 已修復 |
| init 模組安裝不是 transactional | 失敗時 rollback 已安裝模組 | ✅ 已修復 |
| .env.example placeholder 通過驗證 | sentinel 檢查攔截 `xoxb-your-bot-token` 等佔位符 | ✅ 已修復 |
| logging handlers.clear() 未 close | 已在 commit 7e4bd65 修復 | ✅ 先前已修復 |

### bot_walter 正式部署（deferred to P2）
- [ ] 從 E2E 測試環境升級為正式長期運行
- [ ] 設定 systemd / screen / nohup 持久化方案
- [ ] 確認 log rotation 在長時間運行下正常運作

---

## P2 — 中期

### Phase 4 進階功能 — ✅ 全部完成（commits `3519e40`, `0d266f9`, `65e0dab`，+186 tests）
- [x] **Retry 機制**：overloaded_error 指數退避 (30/60/120s)、session_error 清除 session 重試 ✅
- [x] **Circuit Breaker**：CLOSED→OPEN(5 failures)→HALF_OPEN(60s)→CLOSED，status 顯示 ✅
- [x] **Tool Tracker + Timeline**：追蹤工具名稱/耗時、completion message 含 timeline ✅
- [x] **Memory Extractor**：正則啟發式萃取 (EN/ZH)、auto-persist to memory.md（commit `65e0dab`）✅

### opentree module update 指令
- [ ] 模組版本升級流程（比對 bundled vs installed 版本，選擇性升級）
- 來源：handoff.md #3

### Simulation Issues（MEDIUM — Phase 1）— ✅ 全部完成（commit `6d0969c`）

| Issue | 問題 | 修復方式 | 狀態 |
|-------|------|----------|------|
| #2 prompt_hook 每次 exec_module | 每個請求都 exec_module 載入 hook | PromptHookCache 啟動時快取 | ✅ 完成 |
| #6 user config 含 `{{` 破壞 PlaceholderEngine | 使用者設定值含 `{{` 時被誤判 | re.sub single-pass regex | ✅ 完成 |
| #9 無磁碟空間監控 | log + session 可能填滿磁碟 | health.py + hourly check + WARNING threshold | ✅ 完成 |
| #10 exec_module 物件記憶體累積 | hook 模組未被 GC 回收 | 由 PromptHookCache 解決（單次載入） | ✅ 完成 |

### Code Review Issues（LOW）

| Issue | 問題 | 來源 |
|-------|------|------|
| run.sh log() 僅輸出 stdout | wrapper 日誌和 bot 日誌分離，需文件說明 | review-log (Phase 3) |
| sleep 變數未引號 | `$DNS_CHECK_INTERVAL` 等數值變數未引號，`set -u` 下潛在風險 | review-log (Phase 3) |
| bot.py 重複 startup log | 兩行 "starting" 訊息，第一行多餘 | review-log (Phase 3) |
| test_logging 共用全域 logger 狀態 | 測試間 root logger handler 可能洩漏，需改用 autouse fixture | review-log (Phase 3) |

---

## P3 — 長期

### 架構演進
- [ ] **Python → Go 遷移考慮**：長期目標，提升啟動速度和資源效率（handoff.md #5）
- [ ] **DOGI 遷移評估**：讓 DOGI 也使用 OpenTree 模組系統（991 行 CLAUDE.md → < 200 行）（handoff.md #2）
- [ ] **跨 workspace 模板複用**：多 workspace 共享模組配置模板

### 模組系統補完
- [ ] **requirement prompt_hook**：需求訪談上下文注入（stub 已建立，需 data layer）（handoff.md #4）

---

## 下一個 Session 的建議起始點

> v0.2.0 已發布，P0 和 P1 全部完成。

1. **bot_walter 正式部署**（systemd / screen / nohup 持久化）
2. **Phase 4 進階功能**（Tool Tracker、Retry、Circuit Breaker）
3. 若時間充裕，處理 P2 的 Simulation Issues（prompt_hook 快取、磁碟空間監控等）
