# Proposal: OpenTree 獨立 Slack Bot Runner

> 建立日期：2026-03-30
> 狀態：已完成（Phase 1 核心循環）

## 需求背景

### 使用者原話

> 我希望 OpenTree 有自己獨立的 Slack bot 模組，不直接引用目前的 DOGI 程式。

### 需求澄清

- OpenTree 需要自己的 Slack event loop + Claude CLI subprocess 管理，完全獨立於 DOGI（`/mnt/e/develop/mydev/slack-bot/`）
- 從 DOGI 的 ~8,100 行 runtime 精簡為 ~2,400-3,000 行 MVP
- 必須與 OpenTree 既有的模組系統（10 模組、265 測試、91% coverage）無縫整合
- `opentree start` 需要支援兩種模式：互動 CLI（現有）和 Slack bot daemon（新增）

---

## 一、現狀分析

### 1.1 OpenTree 已完成的基礎設施

| 元件 | 檔案 | 行數 | 說明 |
|------|------|------|------|
| CLI 入口 | `cli/main.py` | 27 | Typer app，已有 init/start/module/prompt 子命令 |
| 模組系統 | `cli/module.py` | 425 | install/remove/list/refresh |
| init + start | `cli/init.py` | 358 | init 初始化、start 啟動 Claude CLI |
| 設定 | `core/config.py` | 55 | UserConfig (frozen dataclass) |
| Prompt 組裝 | `core/prompt.py` | 201 | PromptContext + 4 builders + hook collector |
| Placeholder | `core/placeholders.py` | 139 | `{{key}}` 替換引擎 |
| Registry | `registry/` | ~200 | 模組 CRUD、file lock、crash recovery |
| Settings 生成 | `generator/settings.py` | 235 | permissions.json → settings.json |
| CLAUDE.md 生成 | `generator/claude_md.py` | 202 | 動態生成模組索引 |
| Symlink 管理 | `generator/symlinks.py` | 383 | .claude/rules/ 管理 |
| Manifest 驗證 | `manifest/` | ~430 | JSON Schema + 12 error codes |
| **小計** | | **~2,655** | |

### 1.2 `opentree start` 現有行為

```python
# src/opentree/cli/init.py, line 348
args = ["claude", "--system-prompt", prompt, "--cwd", workspace_dir]
os.execvp("claude", args)  # 直接替換進程為互動式 Claude CLI
```

**關鍵限制**：`os.execvp` 替換當前進程，無法同時運行事件接收循環。Bot runner 需要完全不同的啟動路徑。

### 1.3 DOGI 的 8 個核心元件

| # | 元件 | DOGI 檔案 | 行數 | 核心職責 |
|---|------|----------|------|---------|
| 1 | Event Ingestion | `socket_receiver.py` | 376 | Socket Mode、事件去重、@mention 解析 |
| 2 | Bot Orchestrator | `bot.py` | 588 | 生命週期、signal handler、graceful shutdown |
| 3 | Claude Runner | `claude_runner.py` | 1,395 | subprocess、stream-json、circuit breaker |
| 4 | Stream Processor | `stream_processor.py` | 619 | JSON 串流解析、phase 偵測、token 統計 |
| 5 | Slack Client | `slack_client.py` | 883 | SDK/Legacy 雙模式、rate limit、查詢快取 |
| 6 | Task Queue | `task_queue.py` | 257 | 並行控制、per-user pending 限制 |
| 7 | Session Manager | `session_manager.py` | 149 | thread_ts:user_id → session_id 對應 |
| 8 | Task Processor | `task_processor.py` | 1,275 | 訊息解析、安全過濾、prompt 組裝 |
| | **小計** | | **5,542** | |

### 1.4 DOGI 中 OpenTree 已覆蓋的功能（不需重新實作）

| DOGI 功能 | OpenTree 替代 | 說明 |
|-----------|-------------|------|
| `permission_manager.py` | 移除 | OpenTree 為單使用者架構 |
| `workspace_initializer.py` | `opentree init` | 初始化一次即可 |
| DOGI.md 人格設定 | `modules/personality/` | 靜態 rules |
| cc/CLAUDE.md 巨型文件 | `ClaudeMdGenerator` | 動態生成 < 200 行 |
| `prompt_parts.py` | `core/prompt.py` | 已有 4 builders + hook |
| `security_filter.py` | `modules/guardrail/` | 靜態 rules |

---

## 二、設計決策

### Decision 1: Bot Runner 是核心元件還是可選模組？

| 方案 | 說明 | 評估 |
|------|------|------|
| A. 核心元件 (`src/opentree/runner/`) | 隨 `pip install opentree` 安裝 | ✅ 採用 |
| B. 可選模組 (`modules/slack-runner/`) | 作為模組安裝 | ❌ |
| C. 獨立套件 (`opentree-runner`) | 分離的 PyPI 套件 | ❌ |

**最終選擇**：方案 A — 核心元件 + optional dependency group

**理由**：
1. Bot runner 是 OpenTree 核心賣點（v1.0 只支援 Slack headless）
2. 模組系統只能宣告 rules（.md），無法包含可執行 Python 程式碼
3. `opentree start --mode slack` 需要直接 import runner，放在 `src/` 最自然

### Decision 2: `opentree start` 整合方式

| 方案 | 說明 | 評估 |
|------|------|------|
| A. `--mode` flag | `opentree start --mode interactive\|slack` | ✅ 採用 |
| B. 獨立子指令 | `opentree serve` | ⚠️ 可行替代 |

**最終選擇**：方案 A — `--mode` flag

**CLI 簽名**：
```
opentree start [--home PATH] [--mode interactive|slack] [--dry-run]
```

### Decision 3: 依賴管理

**選擇**：Optional dependency group（`pip install opentree[slack]`）

```toml
[project.optional-dependencies]
slack = ["slack-bolt>=1.20.0", "slack-sdk>=3.30.0"]
```

Runner 啟動時做 import 檢查，缺少時給出明確提示。

### Decision 4: 與 DOGI 的隔離策略

| 層面 | 措施 |
|------|------|
| 原始碼 | 零 import — 所有程式碼從頭撰寫，參考 DOGI 設計但不複製 |
| 資料格式 | session.json 等格式可相容但獨立定義 |
| 設定 | 使用 OpenTree 的 `UserConfig`，不用 DOGI 的 Config |
| CLI 工具 | runner 內建 Slack 功能 |
| 驗證 | CI 加入 `grep -r "slack-bot" src/` 檢查（應 0 結果） |

---

## 三、目錄結構

### 3.1 新增檔案

```
src/opentree/
├── runner/                          # 新增：Bot Runner 核心
│   ├── __init__.py
│   ├── bot.py                       # (~250 行) 生命週期、signal、graceful shutdown
│   ├── receiver.py                  # (~200 行) Socket Mode 事件接收
│   ├── dispatcher.py                # (~350 行) 任務分發、prompt 組裝、Claude 調用
│   ├── claude_process.py            # (~400 行) subprocess、stream-json、timeout
│   ├── stream_parser.py             # (~200 行) stream-json 解析、phase 偵測
│   ├── slack_api.py                 # (~250 行) Slack Web API（SDK only）
│   ├── task_queue.py                # (~120 行) 並行控制
│   ├── session.py                   # (~100 行) session 管理
│   ├── progress.py                  # (~200 行) Block Kit 進度回報
│   ├── thread_context.py            # (~100 行) thread 歷史讀取
│   ├── file_handler.py              # (~120 行) 附件下載
│   └── config.py                    # (~80 行) RunnerConfig
├── cli/
│   └── init.py                      # 修改：start 增加 --mode 分支
└── core/
    └── prompt.py                    # 修改：增加 runner 需要的 context 欄位
```

**預估總行數**：~2,370 行（核心）+ ~50 行（修改）= **~2,420 行**

### 3.2 Runtime 目錄

```
$OPENTREE_HOME/
├── config/
│   ├── .env                         # Slack Token
│   ├── user.json                    # 已存在
│   ├── runner.json                  # 新增：runner 設定
│   └── registry.json                # 已存在
├── data/
│   ├── sessions.json                # 新增
│   ├── bot.heartbeat                # 新增
│   ├── bot.pid                      # 新增
│   └── logs/
│       └── YYYY-MM-DD.log           # 新增
└── workspace/                       # 已存在
```

---

## 四、實作計畫

### Phase 1: 骨架 + 核心循環（最小可運行 bot）

| Step | 檔案 | 行數 | 複雜度 | 測試數 |
|------|------|------|--------|--------|
| 1.1 RunnerConfig + 依賴 | `runner/config.py` | ~80 | 低 | ~10 |
| 1.2 Slack API 封裝 | `runner/slack_api.py` | ~250 | 低 | ~15 |
| 1.3 Session Manager | `runner/session.py` | ~100 | 低 | ~10 |
| 1.4 Claude Process + Stream Parser | `runner/claude_process.py` + `stream_parser.py` | ~600 | **高** | ~25 |
| 1.5 Task Queue | `runner/task_queue.py` | ~120 | 低 | ~10 |
| 1.6 Task Dispatcher | `runner/dispatcher.py` | ~350 | **高** | ~20 |
| 1.7 Event Receiver | `runner/receiver.py` | ~200 | 中 | ~15 |
| 1.8 Bot 生命週期 + CLI 整合 | `runner/bot.py` + `cli/init.py` | ~300 | 中 | ~10 |

**Phase 1 小計**：~2,000 行、~115 tests

### Phase 2: 使用者體驗強化

| Step | 內容 | 行數 | 測試數 |
|------|------|------|--------|
| 2.1 Thread Context | 讀取 thread 歷史 | ~100 | ~8 |
| 2.2 File Handler | 附件下載 | ~120 | ~8 |
| 2.3 Progress Reporter | Block Kit 進度更新 | ~200 | ~12 |
| 2.4 管理指令 | status/help/shutdown | ~100 | ~6 |

**Phase 2 小計**：~520 行、~34 tests

### Phase 3: 運維

| Step | 內容 | 行數 |
|------|------|------|
| 3.1 run.sh Wrapper | 自動重啟、watchdog | ~100 |
| 3.2 日誌系統 | Daily rotation | ~80 |
| 3.3 PromptContext 擴充 | thread 參與者 | ~30 |

**Phase 3 小計**：~210 行

---

## 五、關鍵差異（vs DOGI）

| 面向 | DOGI | OpenTree Runner |
|------|------|----------------|
| 認證模式 | SDK + Legacy 雙模式 | **SDK only** |
| 多使用者 | 多租戶 | **單使用者** |
| Workspace | 多 workspace | **單一 workspace** |
| 安全過濾 | SecurityFilter | **guardrail rules** |
| System Prompt | 硬編碼 prompt_parts | **模組 prompt_hook** |
| Config | 531 行 | **55 行 UserConfig + 80 行 RunnerConfig** |
| 排程 | APScheduler in-process | **外部排程** |

---

## 六、工作量預估

| Phase | 行數 | 測試數 | 預估工時 |
|-------|------|--------|---------|
| Phase 1 | ~2,000 | ~115 | 3-4 天 |
| Phase 2 | ~520 | ~34 | 1-2 天 |
| Phase 3 | ~210 | ~4 | 0.5 天 |
| **合計** | **~2,730** | **~153** | **4.5-6.5 天** |

---

## 七、成功標準

- [ ] `opentree start --mode slack` 能啟動 bot daemon
- [ ] @mention 收到 Claude 回覆，延遲 < 5 秒
- [ ] Thread 對話自動 session resume
- [ ] SIGTERM 後 graceful shutdown（最多 30s）
- [ ] 零 import from DOGI
- [ ] 所有模組 prompt_hook 正確注入
- [ ] Phase 1 測試 80%+ coverage
- [ ] 總行數 < 3,000 行
