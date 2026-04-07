# Execution Plan: Owner Freedom

> 此文件由 orchestrator 維護，隨進度持續更新。

## 批次規劃

### Batch 1: Phase 1A + 1B（Owner 術語 + 人設調整）✅ DONE
- [x] Step 1: Flow Simulation — 推演正常流程和 edge case
- [x] Step 2: Implementation + TDD — 實作 + 測試先行
- [x] Step 3: Code Review — 審查實作品質 + 修復 MEDIUM issues

### Batch 2: Phase 2（CLAUDE.md 保護 + .env 分層）✅ DONE
- [x] Step 1: Flow Simulation — 2A: 9 issues, 2B: 7 issues（含 2 HIGH）
- [x] Step 2: Implementation + TDD — 2A: 13 新測試, 2B: 17 新測試
- [x] Step 3: Code Review — WARNING（1 HIGH + 3 MEDIUM），全部修復後 APPROVED

### Batch 3a: Phase 3（Reset 分級）✅ DONE
- [x] Step 1: Flow Simulation — 23 scenarios, 9 issues found（4 HIGH）
- [x] Step 2: Implementation + TDD — 40 新測試（Part1: 19, Part2: 21）
- [x] Step 3: Code Review — WARNING（1 HIGH + 2 MEDIUM），全部修復後 APPROVED

### Batch 3b: Phase 4（Memory 升級）✅ DONE
- [x] Step 1: Flow Simulation — 20 scenarios, 8 issues（2 CRITICAL, 3 HIGH）
- [x] Step 2: Implementation + TDD — Part1: 83 tests, Part2: 9 tests
- [x] Step 3: Code Review — WARNING（1 HIGH + 1 MEDIUM），全部修復後 APPROVED

## 並行限制

- 同時最多 2 個 agent
- 每批次預估 30 分鐘內完成
- 超過 30 分鐘分批，與使用者確認後再進行

## Agent 互動紀錄

### Batch 1 ✅

#### Flow Simulation Agents
- Agent A (Phase 1A - Owner Terminology): ✅ DONE
  - 5 normal flows PASS, 7 edge cases (6 PASS, 1 needs verification)
  - 10 issues found (all test-related, no design flaws)
  - 關鍵發現：to_dict() 需雙 key, PlaceholderEngine 需雙 key
- Agent B (Phase 1B - Persona): ✅ DONE
  - CRITICAL: Phase 1B 不可獨立於 Phase 1A 部署
  - HIGH: tone-rules.md 首次互動範本必須同步更新
  - MEDIUM: owner_description 空值需 fallback 設計
  - 決策：character.md 不嵌入 {{owner_description}}，避免空值破碎

#### Implementation Agents
- Agent C (Phase 1A): ✅ DONE — 5 source + 6 test files, 219 tests passed
- Agent D (Phase 1B): ✅ DONE — 8 module files, 額外發現 message-ban.md 需更新

#### Code Review Agent
- Agent E (Phase 1A+1B 合併): ✅ APPROVED
  - 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW
  - MEDIUM issues 已全部修復

#### Fix Agent
- Agent F (MEDIUM fixes): ✅ DONE
  - 修復 stale docstring
  - 新增 both-keys-present 測試
  - 加註 legacy fallback fixture 註解

### Batch 2 ✅

#### Flow Simulation Agents
- Agent G (Phase 2A - CLAUDE.md): ✅ DONE
  - 26 scenarios tested (15 pass, 9 fail, 2 warn)
  - 9 issues found, 3 P0（generate() 不含 marker、方法簽名方案 B、rfind → find 策略）
  - P0 修復後重推：ALL PASS
- Agent H (Phase 2B - .env): ✅ DONE
  - 26 scenarios tested (18 pass, 8 fail)
  - 7 issues found（1 HIGH: Owner key 傳遞缺失、1 HIGH: chmod 不可靠）
  - Decision: key 傳遞延後到 Phase 3+，改用 guardrail 保護

#### Implementation Agents
- Agent I (Phase 2A): ✅ DONE — 5 files, 13 新測試, 1084 passed
  - 決策：用 find() 從 BEGIN 位置搜尋（比 rfind 更穩健）
- Agent J (Phase 2B): ✅ DONE — 5 files, 17 新測試, 1020 passed
  - _parse_env_file() 抽為 @staticmethod

#### Code Review Agent
- Agent K (Phase 2A+2B): WARNING → APPROVED（修復後）
  - 1 HIGH（docstring 範例過時）+ 3 MEDIUM（deferred import、測試名、security-rules 遺漏）
  - 全部修復

#### Fix Agent
- Agent L: ✅ DONE — 4 個 issue 全部修復

## 測試覆蓋率紀錄

| Phase | 測試檔案 | 通過/總數 | 覆蓋率 |
|-------|---------|-----------|--------|
| 1A+1B | 全量測試 | 1066/1066 | 84% |
| 2A+2B | 全量測試 | 1134/1134 | 88% |
| 1A 核心 | config.py | - | 100% |
| 1A 核心 | placeholders.py | - | 100% |
| 1A 核心 | prompt.py | - | 88% |
| 1A 核心 | dispatcher.py | - | 91% |
| 2A 核心 | claude_md.py | - | 97% |
| 2B 核心 | bot.py | - | ~80% |
| 3a | 全量測試 | 1174/1174 | 88% |
| 3a 核心 | reset.py | - | ~90% |
| 3a 核心 | session.py | - | 96% |
| 3b | 全量測試 | 1224/1224 | 88% |
| 3b 核心 | memory_schema.py | - | 95% |
| 3b 核心 | memory_extractor.py | - | 98% |

## 決策歷程

### Batch 3b 決策

1. **logger import 移植**：`from logger import logger` → 標準 `logging.getLogger(__name__)`
2. **舊格式 migration**：偵測方式改為檢查 section headers 是否存在（而非只看 items 數量）
3. **remember/記住 → Pinned**：第一個 pattern 命中時 category 直接設 "pinned"，不走 _classify()
4. **per-user lock**：`_USER_LOCKS` dict + `_LOCKS_LOCK`，parse→add→write 整段持鎖
5. **title 參數**：`append_to_memory_file` 新增 `user_name` 參數，ensure_file 用 `f"{user_name} 的記憶"`
6. **memory_extraction_enabled**：RunnerConfig 新增欄位，dispatcher Step 11b 檢查旗標
7. **去重策略**：字串等價去重，接受 false negative（語意相似但措辭不同不去重）
8. **_is_old_format 修正**：Code Review 發現空模板 false positive，改為檢查 section headers 存在性

### Batch 3a 決策

1. **.env.defaults 不重設為 placeholder**：reset-bot-all 只刪 .env.local + .env.secrets，保留真實 token → 不需要 onboard snapshot
2. **SessionManager.clear_all()**：新增公開方法，同步清除記憶體 + 磁碟，消除 race condition
3. **data/ 保留目錄本身**：只清空子目錄/檔案，避免 SessionManager._save() OSError
4. **不實作兩步確認**：與 shutdown 行為一致，MVP 原則
5. **不實作 rollback**：reset 是 idempotent，失敗再試即可
6. **Best-effort 策略**：每步 try/except，失敗 log warning 繼續
7. **Docstring 精確化**：reset_bot() 不含 session clearing，明確標註由 caller 負責

### Batch 2 決策

1. **`generate()` 不含 marker**（Decision 1）：保護 12 個現有測試，新增 `wrap_with_markers()` 公開方法
2. **`generate_with_preservation()` 接收字串**（Decision 2）：方案 B，保持 generator 為純函數
3. **Marker 不對稱 → migration fallback**（Decision 3）：用 `find()` + 三情況分支，避免靜默資料損失
4. **`_backup_state` 納入 CLAUDE.md**（Decision 4）：force re-init rollback 時保護 Owner 內容
5. **Owner key 傳遞延後**（Decision 5）：scope 限制，Phase 2 的 .env.local 只用於覆蓋 Slack tokens
6. **.env.defaults 雙層保護**（Decision 6）：chmod 600 + guardrail 規則（prompt-based）
7. **Fallback 邏輯明確**（Decision 7）：defaults 存在 → 三段合併；只有舊 .env → fallback + WARNING
8. **remove 最後模組不改**（Decision 8）：ROI 低，列入 TODO

### Batch 1 決策

1. **Phase 1A + 1B 合併**：Flow Simulation 發現 Phase 1B 依賴 Phase 1A 的 PlaceholderEngine 更新，不可分開部署
2. **character.md 不使用 {{owner_description}}**：避免空值時產生破碎文字「你是  的個人 AI 助手」
3. **tone-rules.md 同步更新**：首次互動範本（高優先規則）必須與 character.md 一致
4. **denial-escalation.md 加入更新**：Flow Simulation 發現術語不同步
5. **message-ban.md 加入更新**：Implementation 時 grep 發現殘留「管理員」
6. **personality/opentree.json 移除 team_name 和 admin_description placeholder**：新版 rule 不再使用，保持 manifest 乾淨
7. **runner.json admin_users 不改名**：runner 層面概念（操作權限），與 Owner 身份概念分離
8. **Proxy 場景自我介紹**：延後到 Proxy 模式實作時處理（OpenTree 目前 single-user）

## 變更檔案清單（Batch 1）

### Source Code（5 檔）
| 檔案 | 變更 |
|------|------|
| `src/opentree/core/config.py` | admin_description → owner_description + fallback |
| `src/opentree/core/prompt.py` | is_admin → is_owner + to_dict 雙 key + 顯示文字 |
| `src/opentree/core/placeholders.py` | {{owner_description}} primary + {{admin_description}} alias |
| `src/opentree/runner/dispatcher.py` | PromptContext 建構改名 |
| `src/opentree/cli/init.py` | --owner CLI + user.json key |

### Test Code（6 檔）
| 檔案 | 變更 |
|------|------|
| `tests/test_config.py` | owner_description 測試 + fallback + precedence |
| `tests/test_prompt.py` | is_owner + expected_keys + 權限等級 |
| `tests/test_placeholders.py` | _make_config + len(keys) + alias |
| `tests/test_dispatcher.py` | is_owner + docstring |
| `tests/test_migration_integration.py` | _KNOWN_PLACEHOLDERS |
| `tests/test_init.py` | owner_description key 斷言 |

### Module Files（8 檔）
| 檔案 | 變更 |
|------|------|
| `modules/personality/rules/character.md` | 全面重寫人設 |
| `modules/personality/rules/tone-rules.md` | 首次互動範本 |
| `modules/personality/opentree.json` | 移除未使用 placeholder |
| `modules/guardrail/rules/security-rules.md` | 管理員 → Owner |
| `modules/guardrail/rules/permission-check.md` | 管理員 → Owner |
| `modules/guardrail/rules/denial-escalation.md` | 管理員 → Owner |
| `modules/guardrail/rules/message-ban.md` | 非管理員 → 非 Owner |
| `modules/guardrail/opentree.json` | 移除未使用 placeholder |

### Infrastructure（2 檔）
| 檔案 | 變更 |
|------|------|
| `tests/test_bot.py` | legacy fallback 註解 |
| `tests/test_e2e_phase3.py` | legacy fallback 註解 |
