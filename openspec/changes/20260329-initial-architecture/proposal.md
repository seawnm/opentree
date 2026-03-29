# Proposal: OpenTree 初始架構設計

## 需求背景

### 使用者原話（不可改寫）

> 我希望在 Claude Code CLI 外層多包一層程式，能夠限制使用者不能修改預先設定好的參數和隱藏相關密鑰。

### 後續訪談摘要

經過 6 輪問答，釐清以下需求：

1. **核心定位**：薄 wrapper，底層是 Claude Code CLI + sandbox
2. **模組系統**：自有格式（資料夾 + manifest），不用 Claude plugins（要跨 AI 廠商留開放性）
3. **Slack 連線**：每個使用者各自建 Slack App，各自 bot 名稱（方案 B）
4. **AI 後端**：固定 Claude Code only，模組格式留開放性
5. **安全邊界**：Admin 預設，使用者不可修改但可在範圍內擴充
6. **單一使用者**：無多租戶，每個 bot 圍繞單一使用者
7. **預裝模組**：人格、護欄、記憶、排程、Slack、audit-logger
8. **選裝模組**：YouTube、STT、需求管理、檔案上傳等

### 後續 6 個關鍵問題（本次規劃主題）

1. manifest.json 格式標準
2. 多使用者同機器 + 任意安裝路徑
3. 預設使用 Claude Code CLI 訂閱（無 API Key）
4. 無頭模式認證（無瀏覽器環境）
5. 互動模式（TUI）可行性
6. 二進位封裝語言選擇

## 變更範圍

本次為架構規劃階段，不涉及程式碼。產出為：
- 6 個核心問題的決策記錄（decisions.md）
- 調研過程記錄（research.md）
- 架構總覽（本文件後半段）

## 架構總覽

### 一句話定義

OpenTree = 安全限制的 Claude Code CLI wrapper + 模組化個人 AI agent 平台

### 核心設計原則

1. 每個使用者擁有自己的 bot 實例
2. 核心極小（wrapper + sandbox + onboard）
3. 所有功能皆為模組（包含 Slack 連線）
4. Admin 預設安全邊界，使用者不可突破，但可在範圍內擴充
5. 單一使用者，無多租戶

### 架構分層

```
┌─────────────────────────────────────────────────────┐
│                  使用者可擴充區域                      │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐          │
│  │ youtube   │ │ stt       │ │ requirement│ ...      │
│  │ (選裝)    │ │ (選裝)    │ │ (選裝)     │          │
│  └───────────┘ └───────────┘ └───────────┘          │
├─────────────────────────────────────────────────────┤
│                  預設安裝模組                         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌───────────┐ │
│  │人格  │ │護欄  │ │記憶  │ │排程  │ │ Slack 連線 │ │
│  └──────┘ └──────┘ └──────┘ └──────┘ └───────────┘ │
├─────────────────────────────────────────────────────┤
│                  OpenTree Core                       │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐   │
│  │ CLI      │ │ Onboard  │ │ Module Manager    │   │
│  │ Wrapper  │ │ Wizard   │ │ (install/remove)  │   │
│  └──────────┘ └──────────┘ └───────────────────┘   │
├─────────────────────────────────────────────────────┤
│              安全層（Admin 鎖定，不可修改）            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Sandbox  │ │ Settings │ │ Audit    │            │
│  │ 檔案+網路│ │ Generator│ │ Logger   │            │
│  └──────────┘ └──────────┘ └──────────┘            │
├─────────────────────────────────────────────────────┤
│              Claude Code CLI（runtime）              │
└─────────────────────────────────────────────────────┘
```

### DOGI 功能拆分對照

| DOGI 原始功能 | OpenTree 模組 | 類型 |
|--------------|--------------|------|
| bot.py + slack_client.py + socket_receiver.py | `slack` | 預裝 |
| DOGI.md 人格 + 說話風格 | `personality` | 預裝 |
| 護欄 / 安全過濾 | `guardrail` | 預裝 |
| memory.md + 記憶管理 | `memory` | 預裝 |
| schedule_tool + task_queue | `scheduler` | 預裝 |
| 操作紀錄 + audit | `audit-logger` | 預裝 |
| alloy youtube | `youtube` | 選裝 |
| alloy stt | `stt` | 選裝 |
| requirement_tool | `requirement` | 選裝 |
| upload_tool | `file-upload` | 選裝 |
| message_tool | 併入 `slack` | — |
| 權限控管（多租戶 policy） | 移除 | — |

### 安裝後目錄結構

```
$OPENTREE_HOME/                   # 環境變數，預設 ~/.opentree/
├── workspace/                    # Claude Code 的 cwd
│   ├── .claude/settings.json     # wrapper 每次啟動動態產生
│   └── CLAUDE.md                 # wrapper 每次啟動動態產生
├── modules/                      # 已安裝模組（git clone）
│   ├── personality/
│   │   ├── opentree.json
│   │   └── rules/
│   ├── guardrail/
│   ├── memory/
│   ├── scheduler/
│   ├── slack/
│   └── audit-logger/
├── data/                         # 持久化資料
│   ├── memory/
│   ├── logs/
│   ├── schedules/
│   └── cache/
├── config/
│   ├── .env                      # Token（權限 600）
│   └── user.json                 # 使用者偏好
└── bin/
    └── opentree                  # CLI 入口
```

## 影響分析

本次為全新專案規劃，不影響現有 DOGI bot。未來 OpenTree 成熟後，DOGI 的功能模組將逐步遷移為 OpenTree 模組。
