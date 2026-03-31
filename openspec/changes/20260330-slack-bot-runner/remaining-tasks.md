# OpenTree Bot Runner — 待辦事項與下一步

> 更新日期：2026-03-31
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

### E2E 實測修復（commit 75915ce）
- SlackResponse 轉換 + Claude CLI 參數修正

---

## P0 — 必須完成（阻擋部署）

### CLAUDE_CONFIG_DIR 驗證
- **狀態**：未開始
- **驗證腳本**：`tests/isolation/verify_config_dir.sh`（已建立，需手動在實機執行）
- **需要驗證的項目**：
  - [ ] Claude CLI 啟動時是否尊重 `CLAUDE_CONFIG_DIR` 環境變數
  - [ ] 多 bot instance 使用不同 config dir 是否互不干擾
  - [ ] session 資料是否正確寫入指定路徑
  - [ ] settings.json 在指定 config dir 中是否被正確讀取

### E2E 測試剩餘項目
- **狀態**：大部分完成（commits 82eec96, 54db6cc, 72ecc6c）
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
- 待測項目：
  - [ ] Thread 多輪對話測試（longer conversation chains）
  - [ ] 並行請求測試
  - [ ] run.sh wrapper 測試
  - [ ] 檔案上傳測試
  - [x] ~~DM 訊息測試~~ — SKIPPED（DOGI 無法 relay DM 到 Bot_Walter）
- 已知問題：
  - **WSL2 bytecache**：rsync 部署後必須清理 `__pycache__`（跨檔案系統 timestamp 比較不可靠，stale .pyc 會導致行為不一致）

---

## P1 — 高價值

### 版本發布 v0.2.0
- [ ] 更新 `pyproject.toml` version 為 `0.2.0`
- [ ] 更新 CHANGELOG `[Unreleased]` → `[0.2.0] - YYYY-MM-DD`
- [ ] Git tag `v0.2.0`

### bot_walter 正式部署
- [ ] 從 E2E 測試環境升級為正式長期運行
- [ ] 設定 systemd / screen / nohup 持久化方案
- [ ] 確認 log rotation 在長時間運行下正常運作

### 未修復的 Phase 2+3 Simulation Issues（MEDIUM）

| Issue | 問題 | 來源 |
|-------|------|------|
| bot.py 缺 exit 42 | 更新重啟時 bot.py 未以 exit code 42 退出，run.sh 無法區分「更新重啟」vs「正常關閉」 | simulation-report (Phase 2+3) |
| reporter.start() 失敗靜默 | 進度回報 thread 啟動失敗時使用者無任何回應（已加 fallback send_message，但需驗證邊界情況） | simulation-report (Phase 2+3) |
| 超長訊息不截斷 | Claude 回覆超過 Slack 4,000 字元上限時未截斷或分段 | simulation-report (Phase 2+3) |
| log_dir 唯讀無 fallback | `setup_logging(log_dir)` 在唯讀檔案系統下無 fallback（已在 review 中提及 stderr fallback 方案，未實作） | simulation-report (Phase 2+3) |
| wrapper cleanup() 無 timeout | cleanup trap 中 wait bot 無 timeout（已修復，待確認邊界情況） | simulation-report (Phase 2+3) |
| bot.py shutdown 重新讀取 config | shutdown 時不應重新讀取 config（已修復，使用快取值） | simulation-report (Phase 2+3) |
| run.sh $BOT_CMD 未引號 | 路徑含空格時崩潰（已修復，改用 bash array） | simulation-report (Phase 2+3) |

### 未修復的 Code Review Issues（MEDIUM）

| Issue | 問題 | 來源 |
|-------|------|------|
| run.sh `host` 指令容器不可用 | `check_network` 使用 `host` 指令，在 minimal container（python:slim、Alpine）中不存在，需 fallback 到 `getent hosts` | review-log (Phase 3) |
| `init --force` 覆寫使用者目錄 | `shutil.rmtree` 刪除既有模組目錄時無警告，使用者自訂內容會靜默消失 | review-log (Phase 3) |
| init 模組安裝不是 transactional | 部分模組安裝失敗時，已安裝的模組留在不一致狀態（symlinks 已建立但 registry 未儲存） | review-log (Phase 3) |
| logging handlers.clear() 未 close | 已修復（commit 7e4bd65），但測試中的 teardown 仍用舊模式，需統一為 autouse fixture | review-log (Phase 3) |
| .env.example placeholder 通過驗證 | `xoxb-your-bot-token` 不會被 `_load_tokens()` 攔截，應加 sentinel 檢查 | review-log (Phase 3) |

---

## P2 — 中期

### Phase 4 進階功能（來自 proposal.md 規劃）
- [ ] **Tool Tracker + Timeline**：追蹤 Claude 使用的工具，產生 timeline 回報
- [ ] **Retry 機制**：overloaded_error / session_error 的自動重試邏輯
- [ ] **Circuit Breaker**：連續失敗時暫停接收新任務，避免雪崩
- [ ] **Memory Extractor**：對話結束後自動萃取記憶寫入使用者記憶檔

### opentree module update 指令
- [ ] 模組版本升級流程（比對 bundled vs installed 版本，選擇性升級）
- 來源：handoff.md #3

### Simulation Issues（MEDIUM — Phase 1）

| Issue | 問題 | 來源 |
|-------|------|------|
| #2 prompt_hook 每次 exec_module | 每個請求都 exec_module 載入 hook，應改為啟動時快取 | simulation-report (Phase 1) |
| #6 user config 含 `{{` 破壞 PlaceholderEngine | 使用者設定值含 `{{` 時被誤判為 placeholder | simulation-report (Phase 1) |
| #9 無磁碟空間監控 | 長時間運行下 log + session 檔案可能填滿磁碟 | simulation-report (Phase 1) |
| #10 exec_module 物件記憶體累積 | hook 模組未被 GC 回收，記憶體緩慢增長 | simulation-report (Phase 1) |

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

1. **完成 CLAUDE_CONFIG_DIR 驗證**（5 分鐘手動執行 verify_config_dir.sh）
2. **完成剩餘 E2E 測試**（multi-turn context、concurrent requests、run.sh wrapper）
3. **發布 v0.2.0**（更新版本號 + CHANGELOG 日期 + git tag）
4. 若時間充裕，處理 P1 的 MEDIUM issues（優先：超長訊息截斷、`host` 指令 fallback）
