# Migration Map: DOGI → OpenTree 模組拆分

## 一、遷移對照總表

### 1.1 DOGI.md（429 行）→ 模組拆分

| 區塊 | 行數 | 目標模組 | 目標檔案 | 備註 |
|------|------|---------|---------|------|
| `# DOGI 人格設定`（優先級宣告） | 1-3 | core | core wrapper 負責載入順序 | 不需要顯式宣告，由合併順序保證 |
| `## 你是誰` | 5-11 | personality | `rules/identity.md` | `DOGI` → `{{bot_name}}`、組織名 → `{{team_name}}` |
| `## 說話風格` + 自我介紹範本 | 13-25 | personality | `rules/speaking-style.md` | 範本中 `DOGI` → `{{bot_name}}` |
| `### 首次互動 / 打招呼` | 27-49 | personality | `rules/first-interaction.md` | 範本中 `DOGI` → `{{bot_name}}` |
| `## 通用行為準則` | 51-54 | core | `rules/base-behavior.md` | 繁體中文、簡潔直接 |
| `## 管理員申請流程` | 56-102 | guardrail | `rules/admin-request-flow.md` | 具體 CLI 指令抽象化（`message_tool` → 模組介面） |
| `## 通用安全規則` | 104-141 | guardrail | `rules/information-security.md` | 敏感詞清單動態化（從模組 manifest 收集） |
| `## 瀏覽器內容安全` | 143-148 | guardrail | `rules/browser-content-safety.md` | |
| `## 多使用者 Thread 意識` | 150-215 | guardrail | `rules/multi-user-thread.md` | 頻道 ID → `{{admin_channel}}`；工具指令抽象化 |
| `## 系統資訊回覆限制` | 217-278 | guardrail | `rules/system-info-disclosure.md` | |
| `## 情境觸發規則` | 280-290 | core | `rules/context-routing.md` | 路徑引用改用模組 ID（`personality://identity`） |
| `## 拒絕後導向（漸進式引導）` | 292-382 | guardrail | `rules/rejection-guidance.md` | 依賴 personality 風格 → manifest 宣告 `depends_on` |
| `## 跨 Thread 記憶引導` | 384-416 | memory | `rules/cross-thread-guidance.md` | |
| `## Slack 訊息格式` | 418-430 | slack | `rules/message-format.md` | |

### 1.2 cc/CLAUDE.md（965 行）→ 模組拆分

| 區塊 | 約行數 | 目標 | 目標檔案 | 備註 |
|------|--------|------|---------|------|
| Slack 訊息發送規則 | 19 | slack | `rules/message-rules.md` | 禁用 MCP Slack、Bot Token 優先 |
| **權限控管** | 49 | **移除** | — | 無多租戶 |
| 專案概述 | 3 | core | `rules/overview.md` | 改寫為 OpenTree 描述 |
| 路徑慣例 | 5 | core | `rules/overview.md` | `<BOT_ROOT>` → `$OPENTREE_HOME` |
| **技術架構** | 28 | **移除** | — | 開發者文件 |
| **開發規則（OpenSpec）** | 14 | **移除** | — | 開發者規範 |
| **執行方式 / 重啟 SOP** | 31 | **移除** | — | 運維 SOP |
| **錯誤修復後續動作** | 10 | **移除** | — | 開發者 workflow |
| **日誌查看** | 12 | **移除** | — | 運維指令 |
| 關鍵設定 | 14 | core | `rules/overview.md` | 精簡為使用者可見參數 |
| **資料檔案** | 10 | **移除** | — | bot 內部資料 |
| 檔案上傳工具 | 31 | slack | `rules/upload-tool.md` | |
| Slack 查詢工具 | 56 | slack | `rules/query-tool.md` | |
| **變更管理** | 44 | **移除** | — | 開發者規範 |
| 排程工具（schedule-tool） | 75 | scheduler | `rules/schedule-tool.md` | |
| 排程工具（watcher-tool） | 22 | scheduler | `rules/watcher-tool.md` | |
| 排程參數 + 操作指引 + 拆分 | 43 | scheduler | `rules/schedule-guide.md` | |
| 需求管理工具 | 159 | **選裝** | `requirement/rules/` | 不預裝，作為可選模組 |
| **需求權限** | 9 | **移除** | — | 多租戶權限碼 |
| **Alloy Deploy** | 29 | **移除** | — | Alloy sandbox 專屬 |
| Alloy STT | 54 | **選裝** | `stt/rules/` | 不預裝 |
| Alloy YouTube | 105 | **選裝** | `youtube/rules/` | 不預裝 |
| Alloy Slack 查詢 | 33 | slack | `rules/query-tool.md` | 合併至 Slack 模組 |
| 記憶修改審計 | 35 | audit-logger | `rules/audit-tool.md` | |
| **Alloy CLI Admin** | 11 | **移除** | — | Alloy sandbox |
| 注意事項 | 7 | core | `rules/overview.md` | |
| 環境限制 + 多輪對話 | 22 | core | `rules/environment.md` | |
| 設計原則 | 4 | core | `rules/overview.md` | |

### 1.3 System Prompt 13 片段重新分配

| # | 片段 | 注入方式 | 歸屬 | 變更說明 |
|---|------|---------|------|---------|
| 1 | 人格設定讀取指引 | ~~system-prompt~~ → **CLAUDE.md** | personality | 消除 Read 跳板，直接合併 |
| 2 | 台北時區日期 | **--system-prompt** | core | 保留動態注入 |
| 3 | 系統參數摘要 | **--system-prompt** | core | 保留動態注入 |
| 4 | Bot 根目錄 | **--system-prompt** | core | 改為統一路徑區塊 |
| 5 | Bot 資料目錄 | **--system-prompt** | core | 合併到路徑區塊 |
| 6 | 使用者身份 | **--system-prompt** | core | 保留，解耦 slack_client |
| 7 | 記憶管理指引 | ~~system-prompt~~ → **CLAUDE.md** | memory | 從硬編碼提取到模組 rules |
| 8 | 記憶修改通知 | **移除** | — | 多租戶功能 |
| 9 | 頻道/Thread 資訊 | **--system-prompt** | slack（prompt_hook） | 模組貢獻動態片段 |
| 10 | Thread 參與者提醒 | **--system-prompt** | slack（prompt_hook） | 模組貢獻動態片段 |
| 11 | 訪談上下文偵測 | **--system-prompt** | requirement（prompt_hook） | 選裝模組，未安裝時不存在 |
| 12 | 新使用者 FTUE | **--system-prompt** | memory（prompt_hook） | 觸發旗標動態，導覽內容在 CLAUDE.md |
| 13 | 功能清單 | **移除** | — | 多租戶功能 |

### 1.4 模板 CLAUDE.md（556 行）

**移除**。理由：
- 90% 與 cc/CLAUDE.md 重複
- 多租戶模板機制在 OpenTree 中不需要
- 替代方案：core 模組提供精簡骨架（~30 行），模組 rules 動態合併

---

## 二、各模組 rules 檔案清單

### core

```
modules/core/rules/
├── overview.md          (~30行) 一句話描述、路徑慣例、關鍵設定、注意事項、設計原則
├── base-behavior.md     (~10行) 繁體中文、簡潔直接
├── context-routing.md   (~15行) 情境觸發路由表
└── environment.md       (~25行) 環境限制（無 AskUserQuestion）、多輪對話模式
```

### personality

```
modules/personality/rules/
├── identity.md          (~15行) {{bot_name}}、個性、角色定位、{{team_name}}
├── speaking-style.md    (~20行) 風格定位、禁用詞、自我介紹範本
└── first-interaction.md (~25行) 首次打招呼處理順序、範本、反例
```

### guardrail

```
modules/guardrail/rules/
├── information-security.md      (~40行) 通用安全規則、敏感詞清單
├── system-info-disclosure.md    (~60行) 五條準則 + 核心原則
├── rejection-guidance.md        (~90行) 漸進式引導策略
├── admin-request-flow.md        (~45行) 管理員申請流程
├── multi-user-thread.md         (~65行) Thread 意識、敏感話題轉移
└── browser-content-safety.md    (~10行) Prompt injection 防護
```

### memory

```
modules/memory/rules/
├── memory-sop.md              (~30行) 記憶管理指引（記住/忘記/展現）
├── cross-thread-guidance.md   (~30行) 跨 Thread 記憶引導
└── ftue-guide.md              (~15行) 新使用者首次使用導覽內容
```

### scheduler

```
modules/scheduler/rules/
├── schedule-tool.md     (~75行) CRUD 指令和範例
├── watcher-tool.md      (~25行) 監看器指令
└── schedule-guide.md    (~45行) 操作指引 + 任務拆分指引
```

### slack

```
modules/slack/rules/
├── message-rules.md     (~20行) 訊息發送規則（禁 MCP Slack）
├── message-format.md    (~15行) Slack 格式限制
├── upload-tool.md       (~30行) 檔案上傳工具
└── query-tool.md        (~60行) Slack 查詢工具（合併 slack-query-tool + alloy slack）
```

### audit-logger

```
modules/audit-logger/rules/
└── audit-tool.md        (~35行) 審計工具 CLI 指令和機制說明
```

---

## 三、移除清單

| 內容 | 原位置 | 移除原因 |
|------|--------|---------|
| 權限控管（判斷流程、預設權限、回應範本） | cc/CLAUDE.md | 無多租戶 |
| permission_manager.py 動態 CLAUDE.md 產生 | bot 程式碼 | 無多租戶 |
| Feature code 系統（F01-F08, T01-T10 等） | _permissions/ | 無多租戶 |
| Alloy Sandbox CLI（alloy run/npx/ls/cat） | cc/CLAUDE.md | Alloy 是 DOGI 的 sandbox 工具 |
| .alloy/policy.json 產生機制 | permission_manager.py | 同上 |
| 技術架構（bot.py 模組樹） | cc/CLAUDE.md | 開發者文件 |
| OpenSpec 工作流程 | cc/CLAUDE.md | 開發者規範 |
| 執行方式 / 重啟 SOP | cc/CLAUDE.md | 運維 SOP |
| 錯誤修復後續動作 | cc/CLAUDE.md | 開發者 workflow |
| 日誌查看 | cc/CLAUDE.md | 運維指令 |
| 變更管理（版本號 + CHANGELOG） | cc/CLAUDE.md | 開發者規範 |
| 資料檔案（state.json 等） | cc/CLAUDE.md | bot 內部資料 |
| Alloy CLI Admin 手動執行 | cc/CLAUDE.md | 多租戶 Admin |
| 記憶修改通知（system prompt #8） | task_processor | 多租戶 audit |
| 功能清單注入（system prompt #13） | permission_manager | 多租戶權限 |
| 模板 CLAUDE.md（556 行） | _global/templates/ | 不再需要模板機制 |

---

## 四、新增設計

### 4.1 Prompt 組裝新架構

```
啟動時                              每次任務
────────                           ──────────

模組 rules/*.md ──合併──→ CLAUDE.md   core: 日期、路徑、config、identity ─┐
                    （Claude CLI         模組 prompt_hook(): 動態片段 ─────┤
                     自動讀取）                                            │
                                        claude --system-prompt "..." ←────┘
```

**CLAUDE.md**：靜態，啟動或模組增減時重新合併
**--system-prompt**：動態，每次任務從 config + 模組 hook 組裝

### 4.2 模組 prompt_hook 介面

模組可在 opentree.json 中宣告 `prompt_hook`，提供動態 system prompt 片段：

```json
{
  "prompt_hook": "prompt_hook.py"
}
```

```python
# prompt_hook.py
def prompt_hook(context: dict) -> list[str]:
    """回傳動態 prompt 片段。context 含 user_id, channel_id, thread_ts 等"""
    return []  # 或 ["頻道 ID：C0AK78CNYBU", "Thread TS：..."]
```

| 模組 | 有 prompt_hook？ | 產出 |
|------|-----------------|------|
| slack | ✅ | 頻道/Thread 資訊、參與者提醒 |
| memory | ✅ | FTUE 旗標（新使用者時） |
| requirement | ✅ | 訪談上下文（選裝，未安裝時不存在） |
| personality | ❌ | 全部在 CLAUDE.md |
| guardrail | ❌ | 全部在 CLAUDE.md |
| scheduler | ❌ | 全部在 CLAUDE.md |
| audit-logger | ❌ | 全部在 CLAUDE.md |

### 4.3 通用化佔位符

模組 rules 中使用佔位符，wrapper 合併時替換：

| 佔位符 | 來源 | 範例 |
|--------|------|------|
| `{{bot_name}}` | config/user.json | `Groot` |
| `{{team_name}}` | config/user.json | `數據 & AI 團隊` |
| `{{admin_channel}}` | config/user.json | `C0AEED4BNTA` |
| `{{opentree_home}}` | 環境變數 | `~/.opentree/` |
| `{{admin_description}}` | config/user.json | `管理員團隊` |

### 4.4 prompt_parts.py 重構

| 原函數 | 處置 | 新位置 |
|--------|------|--------|
| `build_taipei_date_block()` | **保留改名** → `build_date_block()` | `opentree/core/prompt.py` |
| `build_config_summary()` | **保留改名** → `build_config_block()` | `opentree/core/prompt.py` |
| `build_identity_block()` | **保留**，解耦 slack_client | `opentree/core/prompt.py` |
| `build_channel_block()` | **搬到 slack 模組** | `modules/slack/prompt_hook.py` |
| `build_persona_block()` | **移除** | — 人格直接在 CLAUDE.md |
| `build_bot_root_block()` | **移除** | — 合併到統一路徑區塊 |
| （新增）`build_paths_block()` | **新增** | `opentree/core/prompt.py` |
| （新增）`collect_module_prompts()` | **新增** | `opentree/core/prompt.py` |
| （新增）`assemble_system_prompt()` | **新增**，頂層函數 | `opentree/core/prompt.py` |

---

## 五、風險與緩解

| 風險 | 嚴重度 | 緩解措施 |
|------|--------|---------|
| guardrail 與 personality 隱含依賴（拒絕策略引用人格風格） | 高 | manifest 宣告 `depends_on: ["personality"]`；rejection-guidance.md 自帶精簡風格錨點 |
| guardrail 與 slack 操作耦合（轉移敏感討論用 message-tool） | 中 | guardrail 描述意圖，slack 提供實作；用 `{{admin_channel}}` 參數化 |
| 敏感詞清單維護同步（新模組引入新工具名） | 低 | wrapper 從模組 manifest 動態收集 internal_tools，自動擴展敏感詞 |
| 高優先級規則分散到多個檔案 | 低 | wrapper 合併時提取高優先級摘要區塊放在 CLAUDE.md 開頭 |
| context-routing 的路徑引用失效 | 中 | 改用模組 ID 引用（`personality://identity`），wrapper 解析為實際路徑 |

---

## 六、執行順序

| 階段 | 任務 | 優先級 | 依賴 |
|------|------|--------|------|
| **Phase 1** | 建立模組目錄結構 + 空 opentree.json | P0 | 無 |
| **Phase 2** | 拆分 DOGI.md → personality + guardrail + memory + slack 的 rules | P0 | Phase 1 |
| **Phase 3** | 拆分 cc/CLAUDE.md → scheduler + slack + audit-logger + core 的 rules | P0 | Phase 1 |
| **Phase 4** | 實作 CLAUDE.md 合併邏輯（core wrapper） | P1 | Phase 2, 3 |
| **Phase 5** | 實作 prompt_hook 介面 + system prompt 組裝 | P1 | Phase 4 |
| **Phase 6** | 佔位符替換機制（`{{bot_name}}` 等） | P1 | Phase 4 |
| **Phase 7** | 驗證：用一個完整的 Slack 互動流程測試 | P1 | Phase 5, 6 |
| **Phase 8** | 選裝模組拆出（requirement, stt, youtube） | P2 | Phase 7 |
