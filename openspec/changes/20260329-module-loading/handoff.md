# Handoff：OpenTree Phase 1 完成 → Phase 2 接續

## Phase 1 完成摘要（2026-03-29）

78 tests (77 pass + 1 xfail), coverage 98%, 39+ files created.
詳見 progress.md 第五節。

## 給下一個 AI 的上下文

### 你需要做什麼

Phase 1 已完成。你要開始 **OpenTree Phase 2**：CLAUDE.md 動態生成、.claude/rules/ symlink 管理、settings.json 合併。

### 專案位置

- 專案根目錄：`/mnt/e/develop/mydev/opentree/`
- 設計文件：`openspec/changes/20260329-module-loading/design.md`（1001 行，完整設計）
- 進度紀錄：`openspec/changes/20260329-module-loading/progress.md`
- 架構提案：`openspec/changes/20260329-initial-architecture/proposal.md`
- 遷移對照：`openspec/changes/20260329-initial-architecture/migration-map.md`

### 已確認的設計決策

1. **Tier-2 用 .claude/rules/ symlink**（Option A，零風險）——所有模組 rules 都 symlink 到 workspace/.claude/rules/，CLAUDE.md 只是索引
2. **CLAUDE.md 目標 < 200 行**（~60-70 行）
3. **多使用者隔離**：wrapper 必須設定 `CLAUDE_CONFIG_DIR=$OPENTREE_HOME/.claude-state`
4. **Python prototype**：先用 Python 實作，未來遷移到 Go
5. **使用 uv 管理 Python 環境**

### Phase 1 範圍

| 步驟 | 內容 | 預估 |
|------|------|------|
| 1-A | pyproject.toml + 專案骨架 | 1h |
| 1-B | JSON Schema + ManifestValidator + 測試 | 2-3h |
| 1-C | Registry CRUD + 測試 | 1h |
| 1-D | 10 個模組 manifest | 1h |
| 1-E | 整合驗證 | 0.5h |

### 關鍵檔案路徑

**要建立的檔案**：
- `src/opentree/schema/opentree.schema.json` — JSON Schema
- `src/opentree/manifest/models.py` — ValidationIssue, ManifestValidation dataclass
- `src/opentree/manifest/validator.py` — ManifestValidator 類別
- `src/opentree/registry/registry.py` — Registry CRUD
- `modules/{core,personality,guardrail,memory,scheduler,slack,audit-logger,requirement,stt,youtube}/opentree.json` — 10 個 manifest
- `tests/test_validator.py` — 33 個測試案例
- `tests/test_registry.py` — 15 個測試案例
- `tests/test_schema.py` — 2 個測試案例

### 設計要點提醒

1. **Immutability**：所有 dataclass 用 `frozen=True`，registry 操作回傳新 dict 不修改原物件
2. **Error codes**：12 種錯誤碼（MANIFEST_NOT_FOUND、SCHEMA_VALIDATION_ERROR、NAME_MISMATCH 等）
3. **Schema pattern**：`name` 用 `^[a-z]([a-z0-9-]*[a-z0-9])?$`（拒絕尾部 hyphen），`version` 用 semver regex，`loading.rules` 用 `^[a-z0-9-]+\.md$`（純檔名，無 rules/ 前綴）
4. **依賴圖**：core → personality → guardrail；core → memory → audit-logger；core → slack → requirement；core → scheduler；core → youtube
5. **priority**：不加入 manifest schema，載入順序由拓撲排序決定

### 注意事項

- 使用 `uv` 管理 Python（`uv run --directory /mnt/e/develop/mydev/opentree`）
- 目前專案只有 markdown 文件，無任何程式碼
- 依賴只需 `jsonschema>=4.20.0`（dev: pytest, pytest-cov）
- 每個檔案不超過 400 行
- 測試覆蓋率目標 80%+

### 使用者偏好

- 繁體中文溝通
- 先討論規劃再執行
- 使用 OpenSpec 工作流程（proposal + research）
- commit 使用中文訊息（但 Phase 1 可能還不到 commit 階段）
- 修改前分析影響半徑
