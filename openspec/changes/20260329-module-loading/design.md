# Design: OpenTree 模組載入架構

> 本文件定義 OpenTree 的模組載入機制 — 模組如何被發現、註冊、載入到 Claude Code CLI 的 context 中，以及多模組如何共存。
>
> 相關文件：
> - [proposal.md](../20260329-initial-architecture/proposal.md) — 架構提案
> - [decisions.md](../20260329-initial-architecture/decisions.md) — 核心決策記錄
> - [research.md](../20260329-initial-architecture/research.md) — 技術調研
> - [migration-map.md](../20260329-initial-architecture/migration-map.md) — DOGI 到 OpenTree 遷移對照

---

## 1. 設計背景

### 1.1 問題來源：DOGI 的 CLAUDE.md 膨脹

Anthropic 官方建議 CLAUDE.md 控制在 **200 行以內**。DOGI 目前的狀況：

| 檔案 | 行數 | 估算 Token |
|------|------|-----------|
| `DOGI.md`（人格設定） | 429 行 | ~6K tk |
| `cc/CLAUDE.md`（workspace 設定） | 965 行 | ~14K tk |
| **合計** | **1,394 行** | **~20K tk** |

`cc/CLAUDE.md` 單獨就是建議上限的 **4.8 倍**，每次啟動消耗 ~14K tokens。

### 1.2 Claude Code 的三種 context 載入機制

| 機制 | 載入時機 | 壓縮後行為 | Token 影響 |
|------|---------|-----------|-----------|
| `CLAUDE.md` | 啟動時自動讀取 | 隨 context 壓縮可能被摘要 | 啟動即消耗 |
| `.claude/rules/*.md` | 啟動時自動載入（always-on） | **壓縮後重新注入** | 每次壓縮都重新消耗 |
| `Read` 工具按需讀取 | Claude 主動呼叫時 | 不重新注入 | 真正的按需消耗 |

關鍵發現：
- `.claude/rules/` 的檔案是 **always-on**，壓縮後會被重新注入，等同於永遠在 context 中
- Skills 描述**不會**在壓縮後重新注入
- **按需 Read 是唯一能真正減少啟動 token 的方式**，但需要觸發索引（CLAUDE.md 中告訴 Claude 何時去讀什麼）

### 1.3 設計目標

1. **模組化檔案管理**：每個模組的 rules 獨立存放，安裝/移除模組 = 增刪 symlink
2. **CLAUDE.md 精簡化**：從 965 行降到 ~60-70 行，僅作為索引
3. **零遺忘風險**：所有模組 rules 經由 `.claude/rules/` 自動載入，Claude 不需要「記得」去 Read
4. **支援動態組合**：不同使用者可安裝不同模組組合

---

## 2. 三層載入架構（Tier System）

### 2.1 原始設計：三層 Tier

初始設計考慮了三個載入層級：

| Tier | 載入方式 | 判斷標準 | Token 行為 |
|------|----------|----------|-----------|
| Tier 1 | `.claude/rules/` always-on | 安全關鍵、身份核心、每回合都需要 | 每次壓縮後重新注入 |
| Tier 2 | `.claude/rules/` symlinks | 工具參考、流程文件 | 同 Tier 1 |
| ~~Tier 3~~ | ~~On-demand Read（modules/ 目錄）~~ | ~~使用頻率低的參考資料~~ | ~~真正按需~~ |

### 2.2 最終決策：Option A — 全部走 `.claude/rules/`

使用者選擇 **Option A**：所有模組 rules 一律放入 `.claude/rules/`，透過 symlink 管理。

**這意味著**：

- **零遺忘風險**：Claude 不需要判斷何時 Read，所有 rules 永遠可用
- **無 token 節省**：與行內 CLAUDE.md 相比，總 always-on token 數量不變
- **模組化管理收益**：安裝/移除模組 = 增刪 symlink，CLAUDE.md 不需要手動維護
- **CLAUDE.md 精簡化**：從承載所有規則的巨型文件，變成僅包含索引和概述的輕量入口

### 2.3 CLAUDE.md 的角色重新定義

在 Option A 下，CLAUDE.md 不再是 rules 的載體，而是：

```
CLAUDE.md = 工作區入口文件
  ├── 工作區基本資訊（所有者、權限等級）
  ├── 路徑慣例（$OPENTREE_HOME 等）
  ├── 已安裝模組清單（每模組一行描述）
  ├── 模組觸發索引表（informational，輔助 Claude 理解模組用途）
  └── 全域注意事項
```

觸發索引表是**純粹的資訊性質**，不是載入機制。因為 rules 已經透過 `.claude/rules/` 自動載入，索引表只是幫助 Claude 在回答時知道「哪些能力可用」和「相關關鍵字」。

---

## 3. 各模組 Tier 分類與 Rules 清單

### 3.1 預裝模組（Pre-installed）

安裝 OpenTree 時自動安裝，不可移除。

#### core

| 檔案 | 行數 | 內容 |
|------|------|------|
| `identity.md` | ~15 | 路由規則、角色定位 |
| `routing.md` | ~15 | 情境觸發路由表 |
| `path-conventions.md` | ~10 | 路徑佔位符說明 |
| `design-principles.md` | ~10 | 核心設計原則 |
| `environment.md` | ~15 | 環境限制（無 AskUserQuestion）、多輪對話 |
| **小計** | **~65** | |

#### personality

| 檔案 | 行數 | 內容 |
|------|------|------|
| `character.md` | ~25 | `{{bot_name}}`、個性、說話風格、禁用詞 |
| `tone-rules.md` | ~25 | 自我介紹範本、首次互動處理 |
| **小計** | **~50** | |

#### guardrail

| 檔案 | 行數 | 內容 |
|------|------|------|
| `permission-check.md` | ~15 | 權限判斷流程（單使用者簡化版） |
| `message-ban.md` | ~20 | 禁止 MCP Slack 發訊息、敏感詞清單 |
| `denial-escalation.md` | ~45 | 漸進式拒絕引導策略 |
| `security-rules.md` | ~40 | 資訊安全、系統資訊揭露限制 |
| **小計** | **~120** | |

#### memory

| 檔案 | 行數 | 內容 |
|------|------|------|
| `memory-sop.md` | ~35 | 記憶管理指引（記住/忘記/展現）、跨 Thread 引導 |
| `memory-paths.md` | ~25 | 記憶檔案路徑、FTUE 導覽 |
| **小計** | **~60** | |

#### slack

| 檔案 | 行數 | 內容 |
|------|------|------|
| `message-rules.md` | ~20 | 訊息發送規則、Bot Token 優先 |
| `message-format.md` | ~15 | Slack 格式限制 |
| `upload-tool.md` | ~30 | 檔案上傳工具 CLI |
| `query-tool.md` | ~60 | Slack 查詢工具（合併 slack-query-tool + alloy slack） |
| **小計** | **~125** | |

#### scheduler

| 檔案 | 行數 | 內容 |
|------|------|------|
| `schedule-tool.md` | ~75 | 排程 CRUD 指令和範例 |
| `watcher-tool.md` | ~25 | 監看器指令 |
| `task-split-guide.md` | ~35 | 操作指引、任務拆分指引 |
| **小計** | **~135** | |

#### audit-logger

| 檔案 | 行數 | 內容 |
|------|------|------|
| `audit-rules.md` | ~25 | 審計工具 CLI 指令、機制說明 |
| **小計** | **~25** | |

### 3.2 選裝模組（Optional）

使用者自行安裝，可隨時移除。

#### requirement

| 檔案 | 行數 | 內容 |
|------|------|------|
| `trigger-rules.md` | ~30 | 需求觸發條件、處理流程概述 |
| `requirement-tool.md` | ~45 | 需求 CRUD CLI 指令 |
| `requirement-workflow.md` | ~55 | 完整工作流（收集 → 訪談 → 評估 → 規格 → 確認） |
| `invest-checklist.md` | ~30 | INVEST 標準、降級方案、角色切換 |
| **小計** | **~160** | |

#### stt

| 檔案 | 行數 | 內容 |
|------|------|------|
| `stt-tool.md` | ~55 | STT 指令、使用指引、費用計算 |
| **小計** | **~55** | |

#### youtube

| 檔案 | 行數 | 內容 |
|------|------|------|
| `youtube-tool.md` | ~70 | 子指令參考、參數說明 |
| `youtube-guide.md` | ~35 | 使用指引、排程整合、字幕重試 |
| **小計** | **~105** | |

### 3.3 模組預算總覽

| 場景 | 模組數 | Rules 總行數 | 估算 Token |
|------|--------|-------------|-----------|
| 7 模組（預裝） | core + personality + guardrail + memory + slack + scheduler + audit-logger | ~580 行 | ~9K tk |
| 10 模組（全裝） | 上述 + requirement + stt + youtube | ~900 行 | ~14K tk |

---

## 4. opentree.json Manifest Schema

每個模組根目錄必須包含 `opentree.json`，定義模組的 metadata、載入規則、權限和生命週期。

### 4.1 完整 Schema

```json
{
  "$schema": "https://opentree.dev/schema/opentree.v1.json",

  "name": "scheduler",
  "version": "1.0.0",
  "description": "排程任務 CRUD、監看器、任務鏈",
  "author": "OpenTree",
  "license": "MIT",

  "type": "pre-installed",
  "depends_on": ["core"],
  "conflicts_with": [],

  "loading": {
    "rules": [
      "schedule-tool.md",
      "watcher-tool.md",
      "task-split-guide.md"
    ]
  },

  "triggers": {
    "keywords": ["排程", "定時", "提醒", "cron", "監看", "watcher"],
    "description": "排程工具 CLI 語法、參數、任務鏈和拆分指引"
  },

  "permissions": {
    "allow": [
      "Bash(uv run --directory $OPENTREE_HOME/modules/scheduler:*)"
    ],
    "deny": []
  },

  "prompt_hook": null,

  "placeholders": {
    "bot_name": "required",
    "opentree_home": "auto"
  },

  "hooks": {
    "on_install": null,
    "on_remove": null
  }
}
```

### 4.2 欄位說明

| 欄位 | 類型 | 必要 | 說明 |
|------|------|------|------|
| `name` | string | 是 | 模組識別名（目錄名一致） |
| `version` | string | 是 | SemVer 版本號 |
| `description` | string | 是 | 一句話描述，顯示在 CLAUDE.md 模組清單 |
| `author` | string | 否 | 作者 |
| `license` | string | 否 | 授權 |
| `type` | enum | 是 | `"pre-installed"` 或 `"optional"` |
| `depends_on` | string[] | 否 | 依賴模組名清單（安裝時驗證） |
| `conflicts_with` | string[] | 否 | 衝突模組名清單（不可同時安裝） |
| `loading.rules` | string[] | 是 | 要 symlink 到 `.claude/rules/` 的檔案清單（相對於 `modules/{name}/rules/`） |
| `triggers.keywords` | string[] | 否 | 觸發關鍵字（寫入 CLAUDE.md 索引表） |
| `triggers.description` | string | 否 | 模組功能描述（寫入 CLAUDE.md 索引表） |
| `permissions.allow` | string[] | 否 | 合併到 `.claude/settings.json` 的 `allowedTools` |
| `permissions.deny` | string[] | 否 | 合併到 `.claude/settings.json` 的 `denyTools` |
| `prompt_hook` | string\|null | 否 | prompt_hook 腳本檔名（相對於模組根目錄） |
| `placeholders` | object | 否 | 需要的佔位符及其取得方式 |
| `hooks.on_install` | string\|null | 否 | 安裝後執行的腳本（相對路徑） |
| `hooks.on_remove` | string\|null | 否 | 移除前執行的腳本（相對路徑） |

### 4.3 各模組 Manifest 範例

**personality**（無 prompt_hook，有佔位符）：

```json
{
  "name": "personality",
  "version": "1.0.0",
  "description": "Bot 人格設定 — 身份、說話風格、自我介紹",
  "type": "pre-installed",
  "depends_on": ["core"],
  "loading": {
    "rules": ["character.md", "tone-rules.md"]
  },
  "triggers": {
    "keywords": ["自我介紹", "你是誰", "打招呼"],
    "description": "Bot 名稱、個性、說話風格、首次互動"
  },
  "permissions": { "allow": [], "deny": [] },
  "prompt_hook": null,
  "placeholders": {
    "bot_name": "required",
    "team_name": "optional"
  }
}
```

**slack**（有 prompt_hook）：

```json
{
  "name": "slack",
  "version": "1.0.0",
  "description": "Slack 連線 — 訊息規則、查詢、上傳",
  "type": "pre-installed",
  "depends_on": ["core"],
  "loading": {
    "rules": ["message-rules.md", "message-format.md", "upload-tool.md", "query-tool.md"]
  },
  "triggers": {
    "keywords": ["Slack", "訊息", "上傳", "頻道", "thread"],
    "description": "Slack 訊息發送規則、查詢工具、檔案上傳"
  },
  "permissions": {
    "allow": [
      "Bash(uv run --directory $OPENTREE_HOME/bin:*upload*)",
      "Bash(uv run --directory $OPENTREE_HOME/bin:*slack_query*)"
    ],
    "deny": [
      "mcp__claude_ai_Slack__slack_send_message",
      "mcp__claude_ai_Slack__slack_send_message_draft",
      "mcp__claude_ai_Slack__slack_schedule_message"
    ]
  },
  "prompt_hook": "prompt_hook.py",
  "placeholders": {
    "opentree_home": "auto",
    "admin_channel": "required"
  }
}
```

**requirement**（選裝，有 prompt_hook 和依賴）：

```json
{
  "name": "requirement",
  "version": "1.0.0",
  "description": "需求管理 — 收集、訪談、評估、追蹤",
  "type": "optional",
  "depends_on": ["slack"],
  "loading": {
    "rules": [
      "trigger-rules.md",
      "requirement-tool.md",
      "requirement-workflow.md",
      "invest-checklist.md"
    ]
  },
  "triggers": {
    "keywords": ["需求", "功能請求", "我想要", "能不能做", "INVEST"],
    "description": "需求收集流程、CRUD 工具、INVEST 評估"
  },
  "permissions": {
    "allow": [
      "Bash(uv run --directory $OPENTREE_HOME/bin:*requirement*)"
    ],
    "deny": []
  },
  "prompt_hook": "prompt_hook.py",
  "placeholders": {
    "opentree_home": "auto"
  }
}
```

---

## 5. CLAUDE.md 動態生成

Wrapper 啟動時（或模組增減後），根據已安裝模組的 manifest 自動產生 `workspace/CLAUDE.md`。

### 5.1 生成模板

```markdown
# {{bot_name}} 的工作區

> 模組 rules 已透過 .claude/rules/ 自動載入，本文件僅為索引。

## 路徑慣例

- `$OPENTREE_HOME` = {{opentree_home}}
- 模組目錄：`$OPENTREE_HOME/modules/`
- 工作區目錄：`$OPENTREE_HOME/workspace/`
- 資料目錄：`$OPENTREE_HOME/data/`

## 已安裝模組

{{#each modules}}
- **{{name}}** (v{{version}}) — {{description}}
{{/each}}

## 模組觸發索引

| 模組 | 觸發關鍵字 | 說明 |
|------|-----------|------|
{{#each modules}}
| {{name}} | {{triggers.keywords | join ", "}} | {{triggers.description}} |
{{/each}}

## 注意事項

- 所有模組 rules 已自動載入（.claude/rules/），不需要手動 Read
- 修改 config 後需重啟
- .env 不納入版控，包含敏感 Token
- 臨時檔案存放於 `/tmp/opentree/{session_id}/`
```

### 5.2 Scenario A：7 模組（預裝）

生成結果約 **58 行**：

```markdown
# Groot 的工作區

> 模組 rules 已透過 .claude/rules/ 自動載入，本文件僅為索引。

## 路徑慣例

- `$OPENTREE_HOME` = ~/.opentree/
- 模組目錄：`$OPENTREE_HOME/modules/`
- 工作區目錄：`$OPENTREE_HOME/workspace/`
- 資料目錄：`$OPENTREE_HOME/data/`

## 已安裝模組

- **core** (v1.0.0) — 路由、路徑慣例、環境限制
- **personality** (v1.0.0) — Bot 人格設定 — 身份、說話風格、自我介紹
- **guardrail** (v1.0.0) — 安全護欄 — 權限檢查、拒絕策略、資訊安全
- **memory** (v1.0.0) — 記憶管理 — 記住/忘記/展現、跨 Thread 引導
- **slack** (v1.0.0) — Slack 連線 — 訊息規則、查詢、上傳
- **scheduler** (v1.0.0) — 排程任務 CRUD、監看器、任務鏈
- **audit-logger** (v1.0.0) — 操作審計 — 記憶修改追蹤

## 模組觸發索引

| 模組 | 觸發關鍵字 | 說明 |
|------|-----------|------|
| core | 路徑, 設定, 環境 | 路由規則、路徑慣例、環境限制 |
| personality | 自我介紹, 你是誰, 打招呼 | Bot 名稱、個性、說話風格、首次互動 |
| guardrail | 權限, 安全, 拒絕 | 權限檢查、安全規則、漸進式拒絕引導 |
| memory | 記住, 忘記, 記憶, 偏好 | 記憶 SOP、路徑、跨 Thread 引導 |
| slack | Slack, 訊息, 上傳, 頻道, thread | Slack 訊息發送規則、查詢工具、檔案上傳 |
| scheduler | 排程, 定時, 提醒, cron, 監看 | 排程工具 CLI 語法、參數、任務鏈和拆分指引 |
| audit-logger | 審計, 記憶修改, 追蹤 | 記憶修改審計工具、通知機制 |

## 注意事項

- 所有模組 rules 已自動載入（.claude/rules/），不需要手動 Read
- 修改 config 後需重啟
- .env 不納入版控，包含敏感 Token
- 臨時檔案存放於 `/tmp/opentree/{session_id}/`
```

### 5.3 Scenario B：10 模組（全裝）

在 Scenario A 基礎上新增 3 個選裝模組，生成結果約 **68 行**：

```markdown
# Groot 的工作區

> 模組 rules 已透過 .claude/rules/ 自動載入，本文件僅為索引。

## 路徑慣例

- `$OPENTREE_HOME` = ~/.opentree/
- 模組目錄：`$OPENTREE_HOME/modules/`
- 工作區目錄：`$OPENTREE_HOME/workspace/`
- 資料目錄：`$OPENTREE_HOME/data/`

## 已安裝模組

- **core** (v1.0.0) — 路由、路徑慣例、環境限制
- **personality** (v1.0.0) — Bot 人格設定 — 身份、說話風格、自我介紹
- **guardrail** (v1.0.0) — 安全護欄 — 權限檢查、拒絕策略、資訊安全
- **memory** (v1.0.0) — 記憶管理 — 記住/忘記/展現、跨 Thread 引導
- **slack** (v1.0.0) — Slack 連線 — 訊息規則、查詢、上傳
- **scheduler** (v1.0.0) — 排程任務 CRUD、監看器、任務鏈
- **audit-logger** (v1.0.0) — 操作審計 — 記憶修改追蹤
- **requirement** (v1.0.0) — 需求管理 — 收集、訪談、評估、追蹤
- **stt** (v1.0.0) — 語音轉文字 — 音訊轉錄、額度管理
- **youtube** (v1.0.0) — YouTube 影片資訊庫 — 搜尋、抓取、字幕

## 模組觸發索引

| 模組 | 觸發關鍵字 | 說明 |
|------|-----------|------|
| core | 路徑, 設定, 環境 | 路由規則、路徑慣例、環境限制 |
| personality | 自我介紹, 你是誰, 打招呼 | Bot 名稱、個性、說話風格、首次互動 |
| guardrail | 權限, 安全, 拒絕 | 權限檢查、安全規則、漸進式拒絕引導 |
| memory | 記住, 忘記, 記憶, 偏好 | 記憶 SOP、路徑、跨 Thread 引導 |
| slack | Slack, 訊息, 上傳, 頻道, thread | Slack 訊息發送規則、查詢工具、檔案上傳 |
| scheduler | 排程, 定時, 提醒, cron, 監看 | 排程工具 CLI 語法、參數、任務鏈和拆分指引 |
| audit-logger | 審計, 記憶修改, 追蹤 | 記憶修改審計工具、通知機制 |
| requirement | 需求, 功能請求, 我想要, 能不能做, INVEST | 需求收集流程、CRUD 工具、INVEST 評估 |
| stt | 語音, 錄音, 轉錄, 音訊, m4a | STT 轉錄指令、額度、費用計算 |
| youtube | YouTube, 影片, 字幕, 頻道追蹤 | 影片搜尋、抓取、字幕管理、排程同步 |

## 注意事項

- 所有模組 rules 已自動載入（.claude/rules/），不需要手動 Read
- 修改 config 後需重啟
- .env 不納入版控，包含敏感 Token
- 臨時檔案存放於 `/tmp/opentree/{session_id}/`
```

### 5.4 生成邏輯（虛擬碼）

```python
def generate_claude_md(registry: ModuleRegistry, config: UserConfig) -> str:
    modules = registry.list_installed()

    sections = []

    # 1. Header
    sections.append(f"# {config.bot_name} 的工作區\n")
    sections.append("> 模組 rules 已透過 .claude/rules/ 自動載入，本文件僅為索引。\n")

    # 2. 路徑慣例
    sections.append("## 路徑慣例\n")
    sections.append(f"- `$OPENTREE_HOME` = {config.opentree_home}")
    sections.append("- 模組目錄：`$OPENTREE_HOME/modules/`")
    sections.append("- 工作區目錄：`$OPENTREE_HOME/workspace/`")
    sections.append("- 資料目錄：`$OPENTREE_HOME/data/`\n")

    # 3. 已安裝模組清單
    sections.append("## 已安裝模組\n")
    for mod in modules:
        sections.append(f"- **{mod.name}** (v{mod.version}) — {mod.description}")

    # 4. 觸發索引表
    sections.append("\n## 模組觸發索引\n")
    sections.append("| 模組 | 觸發關鍵字 | 說明 |")
    sections.append("|------|-----------|------|")
    for mod in modules:
        keywords = ", ".join(mod.triggers.keywords)
        sections.append(f"| {mod.name} | {keywords} | {mod.triggers.description} |")

    # 5. 注意事項
    sections.append("\n## 注意事項\n")
    sections.append("- 所有模組 rules 已自動載入（.claude/rules/），不需要手動 Read")
    sections.append("- 修改 config 後需重啟")
    sections.append("- .env 不納入版控，包含敏感 Token")
    sections.append(f"- 臨時檔案存放於 `/tmp/opentree/{{session_id}}/`")

    return "\n".join(sections)
```

---

## 6. 模組生命週期

### 6.1 安裝（Install）

```
opentree module install <git-url-or-path>
```

流程：

```
1. git clone → $OPENTREE_HOME/modules/{name}/
   ↓
2. 讀取 opentree.json，驗證 schema
   ↓
3. 檢查依賴（depends_on 中的模組是否已安裝）
   ↓
4. 檢查衝突（conflicts_with 中的模組是否已安裝）
   ↓
5. 建立 symlinks：
   modules/{name}/rules/*.md → workspace/.claude/rules/{name}/*.md
   ↓
6. 合併 permissions 到 workspace/.claude/settings.json
   ↓
7. 重新產生 workspace/CLAUDE.md
   ↓
8. 更新 registry.json（已安裝模組清單）
   ↓
9. 執行 hooks.on_install（若有）
   ↓
10. 佔位符替換（rules 中的 {{...}} → 實際值）
```

### 6.2 移除（Remove）

```
opentree module remove <name>
```

流程：

```
1. 檢查反向依賴（其他模組 depends_on 本模組？）
   → 若有，拒絕移除，列出依賴者
   ↓
2. 執行 hooks.on_remove（若有）
   ↓
3. 刪除 symlinks：workspace/.claude/rules/{name}/
   ↓
4. 從 settings.json 移除本模組的 permissions
   ↓
5. 重新產生 workspace/CLAUDE.md
   ↓
6. 更新 registry.json
   ↓
7. 將模組目錄移到 $OPENTREE_HOME/.trash/{name}.{timestamp}/
   （保留 7 天，供誤刪恢復）
```

### 6.3 更新（Update）

```
opentree module update <name>
```

流程：

```
1. git pull（在 modules/{name}/ 中）
   ↓
2. 重新讀取 opentree.json，驗證 schema
   ↓
3. 比對 loading.rules 清單變化
   → 新增的檔案：建立 symlink
   → 刪除的檔案：移除 symlink
   → 不變的檔案：更新 symlink 目標（通常不需要，因為 symlink 指向原檔）
   ↓
4. 比對 permissions 變化，更新 settings.json
   ↓
5. 重新產生 workspace/CLAUDE.md
   ↓
6. 更新 registry.json（版本號）
   ↓
7. 佔位符替換（新/變更的 rules 檔案）
```

### 6.4 Registry 格式

`$OPENTREE_HOME/config/registry.json`：

```json
{
  "version": 1,
  "modules": {
    "core": {
      "version": "1.0.0",
      "type": "pre-installed",
      "installed_at": "2026-03-29T10:00:00+08:00",
      "source": "bundled"
    },
    "personality": {
      "version": "1.0.0",
      "type": "pre-installed",
      "installed_at": "2026-03-29T10:00:00+08:00",
      "source": "bundled"
    },
    "youtube": {
      "version": "1.0.0",
      "type": "optional",
      "installed_at": "2026-03-30T14:30:00+08:00",
      "source": "https://github.com/opentree-modules/youtube.git"
    }
  }
}
```

---

## 7. workspace/.claude/rules/ 結構

### 7.1 Scenario A：7 模組（預裝）

```
$OPENTREE_HOME/workspace/.claude/rules/
├── core/
│   ├── identity.md        → ../../modules/core/rules/identity.md
│   ├── routing.md         → ../../modules/core/rules/routing.md
│   ├── path-conventions.md → ../../modules/core/rules/path-conventions.md
│   ├── design-principles.md → ../../modules/core/rules/design-principles.md
│   └── environment.md     → ../../modules/core/rules/environment.md
├── personality/
│   ├── character.md       → ../../modules/personality/rules/character.md
│   └── tone-rules.md      → ../../modules/personality/rules/tone-rules.md
├── guardrail/
│   ├── permission-check.md → ../../modules/guardrail/rules/permission-check.md
│   ├── message-ban.md      → ../../modules/guardrail/rules/message-ban.md
│   ├── denial-escalation.md → ../../modules/guardrail/rules/denial-escalation.md
│   └── security-rules.md   → ../../modules/guardrail/rules/security-rules.md
├── memory/
│   ├── memory-sop.md       → ../../modules/memory/rules/memory-sop.md
│   └── memory-paths.md     → ../../modules/memory/rules/memory-paths.md
├── slack/
│   ├── message-rules.md    → ../../modules/slack/rules/message-rules.md
│   ├── message-format.md   → ../../modules/slack/rules/message-format.md
│   ├── upload-tool.md      → ../../modules/slack/rules/upload-tool.md
│   └── query-tool.md       → ../../modules/slack/rules/query-tool.md
├── scheduler/
│   ├── schedule-tool.md    → ../../modules/scheduler/rules/schedule-tool.md
│   ├── watcher-tool.md     → ../../modules/scheduler/rules/watcher-tool.md
│   └── task-split-guide.md → ../../modules/scheduler/rules/task-split-guide.md
└── audit-logger/
    └── audit-rules.md      → ../../modules/audit-logger/rules/audit-rules.md
```

**檔案數**：21 個 symlinks
**目錄數**：7 個子目錄

### 7.2 Scenario B：10 模組（全裝）

Scenario A 的基礎上新增：

```
$OPENTREE_HOME/workspace/.claude/rules/
├── ... (Scenario A 的全部 21 個 symlinks) ...
├── requirement/
│   ├── trigger-rules.md        → ../../modules/requirement/rules/trigger-rules.md
│   ├── requirement-tool.md     → ../../modules/requirement/rules/requirement-tool.md
│   ├── requirement-workflow.md → ../../modules/requirement/rules/requirement-workflow.md
│   └── invest-checklist.md     → ../../modules/requirement/rules/invest-checklist.md
├── stt/
│   └── stt-tool.md             → ../../modules/stt/rules/stt-tool.md
└── youtube/
    ├── youtube-tool.md          → ../../modules/youtube/rules/youtube-tool.md
    └── youtube-guide.md         → ../../modules/youtube/rules/youtube-guide.md
```

**檔案數**：28 個 symlinks（+7）
**目錄數**：10 個子目錄（+3）

### 7.3 Symlink 建立邏輯

```python
def create_module_symlinks(module_name: str, manifest: Manifest) -> None:
    rules_dir = OPENTREE_HOME / "workspace" / ".claude" / "rules" / module_name
    rules_dir.mkdir(parents=True, exist_ok=True)

    source_dir = OPENTREE_HOME / "modules" / module_name / "rules"

    for rule_file in manifest.loading.rules:
        source = source_dir / rule_file
        target = rules_dir / rule_file

        if not source.exists():
            raise ModuleError(f"Rule file not found: {source}")

        if target.is_symlink():
            target.unlink()

        target.symlink_to(source.resolve())
```

### 7.4 Symlink 注意事項

- **Windows 相容性**：Windows 建立 symlink 需要開發者模式或管理員權限。若 symlink 失敗，fallback 到檔案複製（copy mode），但需在更新時重新複製
- **相對路徑 vs 絕對路徑**：symlink 使用絕對路徑（`source.resolve()`），確保從任何 cwd 都能正確解析
- **驗證**：安裝完成後，掃描所有 symlink 確認目標檔案存在（`target.resolve().exists()`）

---

## 8. 多使用者同機共存

### 8.1 隔離模型

每個使用者擁有完全獨立的 OpenTree 實例，**零共享狀態**。

```
/home/alice/.opentree/          ← Alice 的 $OPENTREE_HOME
├── workspace/
│   ├── .claude/settings.json   ← Alice 專屬的 Claude Code 設定
│   ├── .claude/rules/          ← Alice 的模組 rules
│   └── CLAUDE.md               ← Alice 的 CLAUDE.md
├── modules/                    ← Alice 安裝的模組
├── config/
│   ├── .env                    ← Alice 的 Slack Token
│   └── user.json               ← Alice 的偏好（bot_name: "Groot"）
└── data/                       ← Alice 的資料

/home/bob/.opentree/            ← Bob 的 $OPENTREE_HOME
├── workspace/
│   ├── .claude/settings.json   ← Bob 專屬的 Claude Code 設定
│   ├── .claude/rules/          ← Bob 的模組 rules
│   └── CLAUDE.md               ← Bob 的 CLAUDE.md
├── modules/                    ← Bob 安裝的模組（可能與 Alice 不同）
├── config/
│   ├── .env                    ← Bob 的 Slack Token（不同 Slack App）
│   └── user.json               ← Bob 的偏好（bot_name: "Nebula"）
└── data/                       ← Bob 的資料
```

### 8.2 隔離點

| 層級 | 隔離方式 | 說明 |
|------|---------|------|
| OS 使用者 | `$HOME` 不同 | 各自的 `~/.claude/` |
| Claude Code 實例 | 各自的 process | 獨立的 Claude CLI session |
| Slack App | 各自建立 | 不同 bot name、不同 token |
| $OPENTREE_HOME | 環境變數 | 預設 `~/.opentree/`，可自訂 |
| 資料 | 各自的 `data/` | 記憶、日誌、排程各自獨立 |
| 設定 | 各自的 `config/` | .env、user.json 各自獨立 |

### 8.3 同一 OS 使用者多實例

若需要在同一 OS 帳號下跑多個 bot（例如一個測試、一個正式）：

```bash
# 正式環境
OPENTREE_HOME=~/.opentree-prod opentree start

# 測試環境
OPENTREE_HOME=~/.opentree-dev opentree start
```

唯一限制：`~/.claude/` 是 Claude Code CLI 的全域設定，所有實例共用。但 project-level `.claude/settings.json` 覆蓋全域設定，因此不衝突。

---

## 9. Token 預算分析

### 9.1 預算表

| 項目 | Scenario A（7 模組） | Scenario B（10 模組） |
|------|---------------------|---------------------|
| **CLAUDE.md** | ~58 行 / ~1.5K tk | ~68 行 / ~1.7K tk |
| **.claude/rules/** | ~580 行 / ~9K tk | ~900 行 / ~14K tk |
| **啟動總 Token** | **~10.5K tk** | **~15.7K tk** |
| vs DOGI（14K tk） | **-25%** | **+12%** |

### 9.2 Token 分布

**Scenario A（7 模組）**：

```
CLAUDE.md     ██░░░░░░░░░░░░░░  1.5K tk (14%)
core          ██░░░░░░░░░░░░░░  1.0K tk (10%)
personality   █░░░░░░░░░░░░░░░  0.8K tk  (8%)
guardrail     ███░░░░░░░░░░░░░  1.8K tk (17%)
memory        ██░░░░░░░░░░░░░░  0.9K tk  (9%)
slack         ███░░░░░░░░░░░░░  1.9K tk (18%)
scheduler     ███░░░░░░░░░░░░░  2.1K tk (20%)
audit-logger  █░░░░░░░░░░░░░░░  0.5K tk  (5%)
──────────────────────────────────────────
Total                           10.5K tk
```

**Scenario B（10 模組）**：

```
... Scenario A 的 10.5K tk ...
requirement   ████░░░░░░░░░░░░  2.5K tk (16%)
stt           █░░░░░░░░░░░░░░░  0.8K tk  (5%)
youtube       ██░░░░░░░░░░░░░░  1.6K tk (10%)
──────────────────────────────────────────
Total (additional)               4.9K tk
Grand Total                     15.4K tk
```

### 9.3 分析

Option A 的收益**不在 token 節省**，而在：

1. **模組化管理**：安裝/移除模組不需要編輯 CLAUDE.md
2. **CLAUDE.md 可讀性**：從 965 行降到 ~60 行，人類維護成本大幅降低
3. **獨立性**：每個模組的 rules 自成一體，可獨立開發和測試
4. **組合彈性**：不同使用者可安裝不同模組，不需要維護多份 CLAUDE.md

若未來需要 token 節省，可以在此架構上**漸進擴展**：
- 將特定模組的 rules 從 `.claude/rules/` 移到 `modules/` 目錄
- 在 CLAUDE.md 的觸發索引中標記為「按需 Read」
- 不需要重新設計架構

---

## 10. 設計決策記錄

| # | 決策 | 選擇 | 理由 |
|---|------|------|------|
| D1 | Tier-2 載入機制 | Option A：全部走 `.claude/rules/` symlinks | 零遺忘風險，使用者明確偏好 |
| D2 | CLAUDE.md 中的觸發索引 | 純資訊性（informational only） | 因為 rules 已透過 `.claude/rules/` 自動載入，索引不是載入機制 |
| D3 | guardrail rules | 全部 always-on（~120 行精簡後） | 安全規則不可延遲載入，必須每回合都存在 |
| D4 | 模組 manifest 格式 | 自定義 `opentree.json` | Decision 1 from initial architecture — 避免 Claude Code plugin 驗證器不穩定，精確對應 OpenTree 需求 |
| D5 | 多使用者隔離 | 獨立 `$OPENTREE_HOME` per user | Proposal 設計原則 — 每人完整獨立實例，零共享 |
| D6 | Symlink vs Copy | 優先 symlink，Windows fallback 到 copy | Symlink 更新即時、不佔空間；Windows 相容性需 fallback |
| D7 | 佔位符替換時機 | 安裝時替換（寫入到 rules 檔案） | 避免 runtime 每次啟動重複替換；Read 時 Claude 看到的是最終內容 |
| D8 | Registry 格式 | JSON 檔案（`config/registry.json`） | 輕量、人類可讀、不需要 DB |
| D9 | 模組移除策略 | 移到 `.trash/` 保留 7 天 | 允許誤刪恢復，不立即刪除 |

### D7 補充：佔位符替換策略

兩種替換策略的取捨：

| 策略 | 時機 | 優點 | 缺點 |
|------|------|------|------|
| **安裝時替換** | `opentree module install` | 零 runtime overhead；Claude 直接看到最終值 | 改 config 後需重新安裝模組 |
| **啟動時替換** | `opentree start` | 改 config 後自動生效 | 每次啟動需掃描所有 rules 檔案 |

**選擇安裝時替換**的理由：
1. Config 變更頻率極低（bot_name 設一次就不會改）
2. Rules 檔案是 symlink 目標，直接修改模組原始檔案，git diff 可追蹤變更
3. 若需要重新替換，`opentree module refresh` 即可

**例外**：`$OPENTREE_HOME` 標記為 `"auto"`，因為路徑可能因部署環境不同而變化，這個佔位符在**啟動時替換**。

---

## 11. 實作順序

### Phase 1：opentree.json Schema + Manifest 驗證器

**目標**：定義 schema、實作驗證邏輯

- 建立 JSON Schema 定義（`opentree.v1.schema.json`）
- 實作 `ManifestValidator` — 讀取 `opentree.json`，驗證必要欄位、型別、depends_on 合法性
- 單元測試：valid manifest / missing fields / invalid type / circular dependency

**產出**：`opentree/core/manifest.py` + `opentree/schemas/opentree.v1.schema.json`

### Phase 2：CLAUDE.md 生成器 + `.claude/rules/` Symlink 管理器

**目標**：核心基礎設施

- 實作 `ClaudeMdGenerator` — 從 registry + manifests 產生 CLAUDE.md
- 實作 `SymlinkManager` — 建立/移除/驗證 symlinks（含 Windows copy fallback）
- 實作 `SettingsGenerator` — 合併各模組 permissions 到 `.claude/settings.json`
- 單元測試：生成結果 snapshot 比對、symlink 完整性

**產出**：`opentree/core/generator.py` + `opentree/core/symlinks.py` + `opentree/core/settings.py`

### Phase 3：模組 Install / Remove / Update CLI

**目標**：使用者可操作的模組管理

- 實作 `opentree module install <source>` — git clone + validate + symlink + generate
- 實作 `opentree module remove <name>` — dependency check + cleanup + regenerate
- 實作 `opentree module update <name>` — git pull + revalidate + rebuild
- 實作 `opentree module list` — 列出已安裝模組
- 實作 `opentree module refresh` — 重新替換所有佔位符

**產出**：`opentree/cli/module.py` + `opentree/core/registry.py`

### Phase 4：System Prompt 組裝器 + prompt_hook 機制

**目標**：動態 system prompt

- 實作 `assemble_system_prompt()` — 收集 core 動態片段 + 模組 prompt_hooks
- 定義 `PromptHookContext` 資料結構（user_id, channel_id, thread_ts 等）
- 實作模組 prompt_hook 載入和執行（importlib 動態載入）
- 整合測試：模擬各模組 hook 回傳，驗證組裝結果

**產出**：`opentree/core/prompt.py`

### Phase 5：預裝模組內容（from migration-map）

**目標**：從 DOGI 遷移 rules 內容到模組格式

- 依 migration-map.md 拆分 DOGI.md → personality / guardrail / memory 的 rules
- 依 migration-map.md 拆分 cc/CLAUDE.md → core / slack / scheduler / audit-logger 的 rules
- 每個模組建立 `opentree.json` manifest
- 驗證：合併後的 rules 覆蓋原始 CLAUDE.md 的所有功能

**產出**：`modules/*/opentree.json` + `modules/*/rules/*.md`（7 個預裝模組）

### Phase 6：佔位符替換引擎

**目標**：`{{bot_name}}` 等佔位符自動替換

- 實作 `PlaceholderEngine` — 掃描 rules 檔案、讀取 user.json、替換
- 支援 `required`（缺少時報錯）和 `optional`（缺少時留空）和 `auto`（啟動時計算）
- 單元測試：替換正確性、缺少 required 時報錯

**產出**：`opentree/core/placeholders.py`

### Phase 7：E2E 驗證 with Slack

**目標**：完整流程驗證

- 啟動 OpenTree + Slack 模式
- 驗證所有預裝模組功能正常（排程、記憶、審計等）
- 驗證 CLAUDE.md 行數在預期範圍
- 驗證 prompt_hook 動態片段正確注入

### Phase 8：選裝模組（requirement, stt, youtube）

**目標**：驗證選裝模組安裝/移除流程

- 將 requirement / stt / youtube 封裝為獨立模組
- 測試 `opentree module install` 流程
- 測試安裝後 CLAUDE.md 自動更新
- 測試移除後 rules 正確清理
- 測試依賴檢查（requirement depends_on slack）

---

## 12. 相關文件

| 文件 | 位置 | 說明 |
|------|------|------|
| proposal.md | `openspec/changes/20260329-initial-architecture/` | 架構提案（需求背景、架構總覽） |
| decisions.md | 同上 | 核心決策記錄（6 個關鍵問題） |
| research.md | 同上 | 技術調研（manifest 格式、認證、語言選擇） |
| migration-map.md | 同上 | DOGI 到 OpenTree 遷移對照（行級拆分） |
