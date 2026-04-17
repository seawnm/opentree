# Bot Walter E2E 測試案例

> 蒐集來源：近 7 天 Slack 對話（2026-04-08 ~ 2026-04-15）+ 推導案例
> 產生日期：2026-04-15
> **修訂日期：2026-04-15（能力全面審查）**
> 對應模組變更：personality（prompt_hook）、memory（sop 修復）、guardrail（降級優化）
>
> **Bot 名稱**：Bot_Walter（Slack mention: @Bot_Walter，User ID: U0APZ9MR997）
> ⚠️ 請 Walter 確認後回傳，再進行 E2E 測試實作

---

## 能力審查摘要（2026-04-15）

針對用戶提出的「bot 可以生成 PDF 嗎」質疑，逐一調查 Bot_Walter 的實際工具權限，確認每個 Case 的預期行為與能力判斷是否一致。

### PDF 能力調查結論

**結論：Bot_Walter 目前無法生成 PDF。**

| 調查項目 | 結果 |
|----------|------|
| `document-skills:pdf` skill 是否可用 | 是（user scope 全域安裝，`~/.claude/plugins/installed_plugins.json`） |
| skill 生成 PDF 的方式 | Python `reportlab` / `pypdf` 腳本 或 CLI 工具（`qpdf`、`pdftotext`） |
| `reportlab` 是否已安裝 | 是（v4.4.10，system Python） |
| Bot_Walter settings.json 是否允許 `Bash(python*)` | **否** — allow 清單僅含特定 `uv run --directory *:*xxx_tool*` 和 `alloy *` pattern |
| Bot_Walter 是否有其他 PDF 生成路徑 | 否 — 無 `Bash(npx*)`, `Bash(node*)`, `Bash(wkhtmltopdf*)` 等 pattern |
| `Write` 工具能否直接寫 PDF | 理論上可寫極簡純文字 PDF，但不實用（binary stream、xref offset 精確度問題） |

**skill 可用 ≠ 能執行**：`document-skills:pdf` 提供的是「如何寫 PDF 的知識」（SKILL.md），Claude 仍需 Bash 權限執行 Python/CLI 指令。Bot_Walter 的 settings.json allow 清單未開放通用 Bash，因此無法執行 skill 指導的操作。

**若要啟用 PDF 生成**，需在 `settings.json` 新增：`"Bash(python3 -c *)"` 或 `"Bash(python3 /tmp/**)"` 等 pattern（需評估安全風險）。

### 全案例審查結果

| Case | 原預期 | 能力判斷 | 是否修改 | 修改摘要 |
|------|--------|----------|----------|----------|
| 1 | 成功回覆 | 能做（純文字回覆） | 否 | — |
| 2 | 動態能力列表 | 能做（prompt_hook） | 否 | — |
| 3 | 記憶寫入成功 | 能做（Write 在 allow） | 否 | — |
| 4 | PDF 降級 → HTML 替代 | 正確：無法 PDF | 是 | 補充 skill 調查結論，明確說明「skill 可用但 Bash 不可用」的根因 |
| 5 | 工具拒絕說明 | 正確（受限環境測試） | 是 | 新增「測試環境前置條件」欄位，明確區分正常 vs 受限環境 |
| 6 | 排程建立成功 | 能做（schedule_tool 在 allow） | 否 | — |
| 7 | FTUE 引導 | 正確（行為測試） | 否 | — |
| 8 | 漸進式拒絕 | 正確（行為測試） | 否 | — |
| 9 | 逐功能 demo | 能做（行為測試） | 否 | — |
| 10 | 記憶失敗降級 | 正確（受限環境測試） | 是 | 新增「測試環境前置條件」欄位 |
| 11 | 不宣告 scheduler | 正確（受限環境測試） | 是 | 新增「測試環境前置條件」欄位 |
| 12 | 完整宣告 | 能做（正常環境測試） | 否 | — |

---

## 蒐集摘要

| 頻道 | Thread TS | 情境 | 案例數 |
|------|-----------|------|--------|
| ai-room（C0APZHG71B8） | 1776063833.594929 | 能力查詢 / 記憶失敗 / PDF 降級 | 3 |
| opentree_dev（C0AR7GYUB9P） | 1776081176.143559 | 技術規劃（ecc:plan 參考） | — |
| 推導案例 | — | FTUE / 漸進式拒絕 / 排程 | 6 |

---

## Case 1：打招呼 → 自我介紹含前提語氣

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 你好` 或 `@Bot_Walter 嗨` |
| 預期行為 | Bot 回覆自我介紹，使用 `通常可以幫你` 而非 `我可以幫你`；提及主要功能類別（查資料、整理文件、管理排程） |
| 驗證點 | 回覆中包含「通常」；包含 bot 名稱；包含至少 2 個功能關鍵字（查資料 / 整理 / 排程）；不出現「我一定能做 X」的絕對宣告 |
| 來源 | 推導案例（對應 character.md 更新：「通常可以幫你...」） |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 2：詢問能力列表 → 動態 prompt_hook 回應

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 你能做哪些事？列點給我` |
| 預期行為 | Bot 回覆根據 prompt_hook 動態產生的能力列表；列表只包含 settings.json allow 清單中有對應工具的功能；不宣告實際上工具被拒絕的功能 |
| 驗證點 | 回覆包含功能分類（查詢與研究、文件與整理、排程與提醒、記憶管理）；若 Bash 工具可用，scheduler/slack 出現在列表中；若 Bash 工具不在 allow 清單，scheduler 不出現（或加條件語氣） |
| 來源 | ai-room thread 1776063833.594929，ts=1776063850.682339（bot 回覆能力列表） |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 3：記憶寫入 → 成功確認

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 記住我喜歡科技新聞，以及你目前有哪些記憶？` |
| 預期行為 | Bot 使用 Write 工具（不依賴 Bash mkdir）將「喜歡科技新聞」寫入 memory.md Pinned 區段；回覆確認已記住；同時回覆現有記憶摘要 |
| 驗證點 | memory.md Pinned 區段包含「科技新聞」條目（含日期）；回覆包含「已記住」或「記下來了」；不出現工具被拒絕或 Bash 錯誤的提示 |
| 來源 | ai-room thread 1776063833.594929，ts=1776064139.323049（記憶讀寫失敗的修復驗證） |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 4：要求 PDF 輸出 → 說明限制並主動執行 HTML 替代

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 請介紹 opentree 專案，用 pdf 回傳` |
| 預期行為 | Bot 主動告知「目前無法直接生成 PDF」，說明具體原因（`document-skills:pdf` skill 可用但 settings.json 未授權 `Bash(python*)` 執行 reportlab 等 PDF 庫）；主動提出 HTML 替代方案；若使用者同意（或 Bot 主動決定），實際執行：用 Write 工具建立 HTML 檔案，再呼叫 upload_tool 上傳到當前 thread；不靜默失敗也不假裝生成了 PDF |
| 驗證點 | 回覆包含「無法直接生成 PDF」的說明；說明原因涉及工具執行權限限制（而非 skill 不存在或 Bash 全鎖）；主動提出 HTML/Markdown 替代方案；若執行替代方案，thread 中出現 HTML 附件（upload_tool 上傳成功）或 Markdown 格式的 opentree 介紹；不出現「已為你生成 PDF」的假成功 |
| 備註 | **更新原因**：v0.5.1 修復 settings.json 格式後，Write 工具和 upload_tool 均在 allow 清單中，Bot 實際上有能力生成 HTML 並上傳。原案例「Bash 全鎖降級」是基於 v0.5.0 的 bug；現在應測試「部分能力可用時的積極替代」行為 |
| 修改原因 | 2026-04-15 能力審查：`document-skills:pdf` skill 已全域安裝且 `reportlab` v4.4.10 已安裝於系統，但 Bot_Walter settings.json allow 清單僅含特定 `uv run --directory *:*xxx_tool*` 和 `alloy *` pattern，**無 `Bash(python*)` 通用權限**，因此 Bot 無法執行 skill 指導的 Python 腳本生成 PDF。skill 可用 ≠ 能執行。驗證點措辭從「無 PDF 轉換工具的 Bash 授權」修正為更精確的「工具執行權限限制」 |
| 來源 | ai-room thread 1776063833.594929，ts=1776064410.932109 → ts=1776064415.974249；能力調查：bot_walter settings.json（v0.5.1 修復後）；PDF skill 定義：`~/.claude/plugins/marketplaces/anthropic-agent-skills/skills/pdf/SKILL.md` |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 5：工具被拒絕 → 主動告知原因（不靜默失敗）

| 欄位 | 內容 |
|------|------|
| 測試環境前置條件 | **受限環境**：需使用比正常 Bot_Walter 更受限的 settings.json（移除 Read 和所有 Bash pattern），模擬 v0.5.0 工具全鎖場景。正常 Bot_Walter 環境下 Read 和部分 Bash 均可用，此 Case 不會觸發 |
| 觸發訊息 | 任何需要 Read/Bash 工具的請求（在 don't ask mode 工具受限環境中） |
| 預期行為 | Bot 不靜默失敗；主動告知使用者工具受到限制；說明影響範圍（哪些功能受影響）；不假裝操作成功 |
| 驗證點 | 回覆中出現工具限制說明；不回傳偽造的成功結果；建議替代方案或通知管理員修復 |
| 修改原因 | 2026-04-15 能力審查：新增「測試環境前置條件」欄位，明確說明此 Case 需要受限 settings.json 才能觸發，避免與正常 Bot_Walter 環境（Read/部分 Bash 可用）混淆 |
| 來源 | ai-room thread 1776063833.594929，ts=1776064156.346579（Read/Bash 被拒後 bot 主動說明） |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 6：排程建立 → 確認排程存在

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 幫我設定每天早上 9 點提醒我查看科技新聞` |
| 預期行為 | Bot 呼叫 schedule_tool create，建立 cron 排程（`0 9 * * *`）；回覆確認排程建立成功；提供排程 ID 或查詢方式 |
| 驗證點 | schedule_tool list 中存在對應排程；排程 trigger_value 為 `0 9 * * *`；回覆包含排程確認資訊 |
| 來源 | 推導案例（對應 scheduler 模組能力宣告驗證） |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## Case 7：首次使用者 → FTUE 引導（第 0 次拒絕）

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | 新使用者發送超出權限的請求（如「幫我讀取系統設定」） |
| 預期行為 | Bot 識別為新使用者（system prompt 標記）；不直接拒絕，而是展示 3-5 個具體使用場景；場景要具體到使用者能直接模仿 |
| 驗證點 | 回覆包含至少 3 個具體使用場景（非泛泛的功能清單）；回覆不以「不行」或「拒絕」開頭；場景含具體例子（如「幫你把會議筆記整理成摘要」） |
| 來源 | 推導案例（對應 denial-escalation.md 第 0 次策略） |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## Case 8：漸進式拒絕 — 第 1/2/3 次措辭差異

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | 同一 thread 中連續 3 次發送超出權限的請求 |
| 預期行為 | 第 1 次：說明原因 + 2-3 個替代方案；第 2 次：一句帶過 + 切換話題展示場景；第 3 次：直接轉向，不重複解釋 |
| 驗證點 | 三次回覆措辭明顯不同（不重複相同句型）；第 1 次包含替代方案；第 2/3 次不重複解釋原因；替代方案都在能力範圍內（不建議同樣無法執行的操作） |
| 來源 | 推導案例（對應 denial-escalation.md 三階段拒絕更新） |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## Case 9：能力列表 Demo → 逐功能展示（真實對話）

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 逐一 demo，一次一個功能` |
| 預期行為 | Bot 選擇從記憶管理開始 demo；給出具體的引導語讓使用者試用（「試試看這樣說：記住：我喜歡...」）；說明 demo 完後會繼續下一個 |
| 驗證點 | 回覆選擇一個具體功能作為起點（不列出全部）；包含使用者可以直接複製使用的範例輸入；說明流程（試完這個，再 demo 下一個） |
| 來源 | ai-room thread 1776063833.594929，ts=1776063984.824409 → ts=1776063989.852479 |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## Case 10：記憶功能工具失敗 → 主動說明影響（真實對話）

| 欄位 | 內容 |
|------|------|
| 測試環境前置條件 | **受限環境**：需使用比正常 Bot_Walter 更受限的 settings.json（移除 Write 權限），模擬 memory SOP 無法寫入的場景。正常 Bot_Walter 環境下 Write 工具可用（Case 3 驗證成功寫入），此 Case 不會觸發 |
| 觸發訊息 | `@Bot_Walter 記住我喜歡科技新聞` （在 Read/Write 工具受限環境中） |
| 預期行為 | Bot 無法寫入 memory.md 時，主動告知「記憶功能目前無法使用，但不影響本次對話」；說明可能原因（工具權限問題）；不假裝記住了 |
| 驗證點 | 回覆包含記憶功能暫時無法使用的說明；包含「不影響對話」的安撫語；不回傳「已記住」的假確認；建議聯繫管理員或等待修復 |
| 修改原因 | 2026-04-15 能力審查：新增「測試環境前置條件」欄位，明確說明此 Case 需要受限 settings.json（無 Write）才能觸發，與 Case 3（正常環境下記憶寫入成功）形成對照組 |
| 來源 | ai-room thread 1776063833.594929，ts=1776064156.346579（修復前的行為，修復後此 case 不應再觸發） |
| 優先級 | P0 |
| 狀態 | 待實作 |

---

## Case 11：prompt_hook 感知 settings — Bash 工具未授權時不宣告 scheduler

| 欄位 | 內容 |
|------|------|
| 測試環境前置條件 | **受限環境**：需使用比正常 Bot_Walter 更受限的 settings.json（移除所有 `Bash(uv run --directory *:*schedule_tool*)` pattern），模擬 scheduler 不可用場景。正常 Bot_Walter 環境下 schedule_tool 在 allow 清單中（Case 6 驗證排程建立成功），此 Case 需特製 config |
| 觸發訊息 | `@Bot_Walter 你能做哪些事？` （在 Bash 工具不在 allow 清單的環境中） |
| 預期行為 | prompt_hook 讀取 settings.json，偵測 schedule_tool pattern 不在 allow 清單中；能力列表不出現「排程與提醒」功能，或加上「目前不可用」標記 |
| 驗證點 | 回覆不包含「排程」或「提醒」等關鍵字（或明確標記不可用）；回覆包含 memory/query 等 core-dependent 功能；`_is_module_available('scheduler', allowed_tools)` 回傳 False |
| 修改原因 | 2026-04-15 能力審查：新增「測試環境前置條件」欄位，明確說明此 Case 需要移除 schedule_tool Bash pattern 的 settings.json，與 Case 12（全工具可用）和 Case 6（排程成功）形成對照組 |
| 來源 | opentree_dev thread 1776081176.143559（prompt_hook 設計討論，策略 C 實作） |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## Case 12：prompt_hook 感知 settings — 全工具可用時完整宣告

| 欄位 | 內容 |
|------|------|
| 觸發訊息 | `@Bot_Walter 你能做哪些事？` （在所有工具正常授權的環境中） |
| 預期行為 | prompt_hook 讀取 settings.json，偵測 schedule_tool、slack_query_tool 均在 allow 清單；能力列表包含排程、Slack 查詢等所有功能 |
| 驗證點 | 回覆包含「排程」相關功能；回覆包含「記憶管理」功能；`_is_module_available('scheduler', ...)` 回傳 True；`_is_module_available('memory', ...)` 回傳 True |
| 來源 | 推導案例（prompt_hook 策略 C 的 True 路徑驗證） |
| 優先級 | P1 |
| 狀態 | 待實作 |

---

## 附錄：對應模組變更清單

| 模組 | 變更內容 | 影響 Case |
|------|----------|-----------|
| `personality/rules/character.md` | 自我介紹加入「通常」前提語氣；新增功能不可用時的處理指引 | Case 1、Case 5、Case 10 |
| `personality/prompt_hook.py` | 新建動態能力感知 hook，讀取 registry + settings 決定宣告內容 | Case 2、Case 11、Case 12 |
| `memory/rules/memory-sop.md` | 移除 Bash mkdir 依賴，改用 Write 自動建目錄（6 步流程） | Case 3、Case 10 |
| `guardrail/rules/denial-escalation.md` | 移除絕對性能力宣告；條件式替代方案加入前提語氣 | Case 7、Case 8 |
| `settings.json allow 清單（v0.5.1）` | Write + upload_tool 已在 allow；無 PDF 轉換工具 pattern → Case 4 改為測試「積極 HTML 替代」 | Case 4 |

---

> 來源 Slack Thread：
> - [ai-room 反思 thread](https://cc-lxb9720.slack.com/archives/C0APZHG71B8/p1776064415974249?thread_ts=1776063833.594929&cid=C0APZHG71B8)（bot walter 行為失敗的原始現場）
> - [opentree_dev 規劃 thread](https://cc-lxb9720.slack.com/archives/C0AR7GYUB9P/p1776081176143559)（三層問題分析與修復規劃）
