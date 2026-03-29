# OpenTree Phase 1: Manifest Validation & Registry — Execution Plan

> 建立日期：2026-03-29
> 狀態：Phase 1-6 全部完成
> 決策確認：Q1=純檔名 Q2=["core"] Q3=不加priority
> 完成日期：2026-03-30
> 結果：265 tests (264 pass + 1 xfail), coverage 91%, 8 commits
> 預計 Batch 數：5（每 batch ≤ 25 min，並行 ≤ 2 agents）
> 專案路徑：/mnt/e/develop/mydev/opentree/

---

## 背景

前一個 thread（ts: 1774714753.034719）完成了 OpenTree 模組載入架構的完整設計：
- 4 輪 × 12 個 agent 並行分析
- design.md（1001 行）、migration-map.md、progress.md、handoff.md 已寫入
- 使用者確認所有設計決策（Option A symlink、三層 Tier、多使用者隔離等）

**Phase 1 目標**：建立模組系統的基礎層 — JSON Schema + ManifestValidator + Registry CRUD + 10 個模組 manifest。

---

## Phase 1 範圍（from design.md + handoff.md）

| 步驟 | 內容 | 預估 | 產出 |
|------|------|------|------|
| 1-A | pyproject.toml + 專案骨架 | 1h | src/opentree/ 結構 |
| 1-B | JSON Schema + ManifestValidator + 33 tests | 2-3h | schema, validator, errors |
| 1-C | Registry CRUD + 15 tests | 1h | registry.py |
| 1-D | 10 個模組 manifest | 1h | modules/*/opentree.json |
| 1-E | 整合驗證 | 0.5h | 15 integration tests |

---

## Planner Agent 發現的設計歧義（需確認）

### 歧義 1: `loading.rules` 路徑格式

| 來源 | 格式 | 範例 |
|------|------|------|
| design.md（權威） | 純檔名 | `"schedule-tool.md"` |
| handoff.md（摘要） | 含 rules/ 前綴 | `"rules/schedule-tool.md"` |

**建議**：採用 design.md（權威來源），Schema pattern = `^[a-z0-9-]+\.md$`。
Validator 在解析時自動補上 `modules/{name}/rules/` 前綴。

### 歧義 2: scheduler 的 depends_on

| 來源 | depends_on |
|------|-----------|
| design.md section 4.1 範例 | `["slack"]` |
| handoff.md 依賴圖 | `core -> scheduler`（直接邊） |
| migration-map section 6 | `core -> scheduler`（直接邊） |

**建議**：採用 `["core"]`（migration-map 為權威依賴圖）。
scheduler 的 CLI 工具用 `$OPENTREE_HOME/bin` 路徑，不依賴 slack 功能。

### 歧義 3: priority 欄位

handoff.md 提到 priority 範圍（core=0-99, pre-installed=100-499, optional=500-999），但 design.md manifest schema 不含 priority 欄位。

**建議**：不在 manifest 加 priority 欄位。載入順序由 dependency graph 的拓撲排序決定，同層級用字母序（deterministic）。

---

## 專案目錄結構

```
/mnt/e/develop/mydev/opentree/
├── pyproject.toml
├── src/opentree/
│   ├── __init__.py                    # __version__ = "0.1.0"
│   ├── schema/
│   │   ├── __init__.py
│   │   └── opentree.schema.json       # JSON Schema (draft-2020-12)
│   ├── manifest/
│   │   ├── __init__.py
│   │   ├── errors.py                  # 12 ErrorCode enum
│   │   ├── models.py                  # ValidationIssue, ManifestValidation (frozen)
│   │   └── validator.py               # ManifestValidator class
│   └── registry/
│       ├── __init__.py
│       ├── models.py                  # RegistryEntry, RegistryData (frozen)
│       └── registry.py                # Registry CRUD (static methods)
├── modules/
│   ├── core/opentree.json + rules/.gitkeep
│   ├── personality/opentree.json + rules/.gitkeep
│   ├── guardrail/opentree.json + rules/.gitkeep
│   ├── memory/opentree.json + rules/.gitkeep + prompt_hook.py
│   ├── slack/opentree.json + rules/.gitkeep + prompt_hook.py
│   ├── scheduler/opentree.json + rules/.gitkeep
│   ├── audit-logger/opentree.json + rules/.gitkeep
│   ├── requirement/opentree.json + rules/.gitkeep + prompt_hook.py
│   ├── stt/opentree.json + rules/.gitkeep
│   └── youtube/opentree.json + rules/.gitkeep
├── tests/
│   ├── conftest.py
│   ├── test_schema.py                 # 2 tests
│   ├── test_validator.py              # 33 tests
│   ├── test_registry.py               # 15 tests
│   ├── test_integration.py            # 10 tests (manifests validation)
│   └── test_registry_integration.py   # 5 tests (registry smoke)
└── openspec/changes/...               # 既有設計文件
```

---

## 12 個 Error Codes

| Code | Severity | 觸發條件 |
|------|----------|---------|
| MANIFEST_NOT_FOUND | ERROR | opentree.json 不存在 |
| MANIFEST_PARSE_ERROR | ERROR | 檔案不是合法 JSON |
| SCHEMA_VALIDATION_ERROR | ERROR | 不符合 JSON Schema |
| NAME_MISMATCH | ERROR | name != 模組目錄名 |
| EMPTY_RULES | ERROR | loading.rules 為空陣列 |
| DUPLICATE_RULES | ERROR | loading.rules 有重複 |
| DEPENDENCY_NOT_FOUND | ERROR | depends_on 引用不存在的模組 |
| CIRCULAR_DEPENDENCY | ERROR | 依賴圖有環 |
| SELF_DEPENDENCY | ERROR | 自己依賴自己 |
| CONFLICT_WITH_INSTALLED | ERROR | conflicts_with 碰到已安裝模組 |
| MISSING_TRIGGERS | WARNING | 無 triggers 區塊 |
| UNKNOWN_PLACEHOLDER_MODE | WARNING | placeholder 值不是 required/optional/auto |

---

## 10 個模組 Manifest 摘要

| # | Module | Type | depends_on | Rules | prompt_hook |
|---|--------|------|-----------|-------|-------------|
| 1 | core | pre-installed | [] | 5 | null |
| 2 | personality | pre-installed | [core] | 2 | null |
| 3 | guardrail | pre-installed | [personality] | 4 | null |
| 4 | memory | pre-installed | [core] | 2 | prompt_hook.py |
| 5 | slack | pre-installed | [core] | 4 | prompt_hook.py |
| 6 | scheduler | pre-installed | [core] | 3 | null |
| 7 | audit-logger | pre-installed | [memory] | 1 | null |
| 8 | requirement | **optional** | [slack] | 4 | prompt_hook.py |
| 9 | stt | **optional** | [slack] | 1 | null |
| 10 | youtube | **optional** | [core] | 2 | null |

依賴圖（DAG）：
```
core (root)
├── personality → guardrail
├── memory → audit-logger
├── slack → requirement (opt), stt (opt)
├── scheduler
└── youtube (opt)
```

---

## 測試計畫

### test_schema.py（2 tests）
1. schema 是合法 JSON Schema
2. schema 檔案存在且可解析

### test_validator.py（33 tests）
- **Structural（6）**：valid minimal/full, not found, parse errors (bad JSON, array, empty)
- **Schema（11）**：missing required 5 欄位, invalid patterns (name/version/type/rules), extra properties
- **Semantic（5）**：name mismatch, name match, skip when no dir, empty rules, duplicate rules
- **Dependency（6）**：satisfied, not found, multiple missing, self, conflict installed, conflict not installed
- **Batch（2）**：circular 2-module, circular 3-module
- **Warning（3）**：missing triggers, unknown placeholder, warnings don't block validity

### test_registry.py（15 tests）
- Load: nonexistent/valid/malformed/wrong version
- Save: creates file/parent dirs, roundtrip
- Register: new/update/empty name
- Unregister: existing/nonexistent
- Query: is_registered true/false, list sorted

### test_integration.py（10 tests）
- IV-01~10: 全部 manifest schema 通過、name match、DAG acyclic、depends_on 解析、pre-installed 不依賴 optional、rules pattern、type 計數、拓撲排序、無 conflicts、名稱唯一

### test_registry_integration.py（5 tests）
- IR-01~05: 註冊全部 pre-installed、註冊 optional、移除有反向依賴時被拒、正確移除順序、list 結果

**總計：65 tests，目標覆蓋率 80%+**

---

## 分批執行計畫

### Batch 1: 專案骨架 + Schema + Flow Simulation（≤ 25 min）

**Agent 1 — Project Skeleton + JSON Schema + Error Codes + Models**
```
讀取：design.md, handoff.md
建立：
- pyproject.toml (uv, jsonschema dep, pytest)
- src/opentree/ 所有 __init__.py
- src/opentree/schema/opentree.schema.json (draft-2020-12)
- src/opentree/manifest/errors.py (12 ErrorCode enum)
- src/opentree/manifest/models.py (ValidationIssue, ManifestValidation, frozen=True)
- tests/conftest.py (shared fixtures)
- tests/test_schema.py (2 tests)
驗證：uv sync + pytest test_schema.py pass
```

**Agent 2 — Flow Simulation（Normal + Edge）**
```
讀取：design.md, migration-map.md, 本執行計畫
推演情境：
Normal: fresh install, install optional, remove module, batch validate
Edge: missing dep, circular dep, name mismatch, invalid JSON, pre-installed depends optional,
      remove with reverse dep, remove pre-installed, concurrent access
產出：flow-simulation.md（寫入 openspec 目錄）
若發現設計缺陷 → 提出修正建議
```

### Batch 2: ManifestValidator + Tests（≤ 25 min）

**Agent 1 — ManifestValidator 實作（TDD）**
```
讀取：Batch 1 產出（schema, errors, models）、flow-simulation.md
TDD 流程：
1. 寫 test_validator.py 全部 33 tests（RED）
2. 實作 validator.py（GREEN）
3. 重構（IMPROVE）
驗證：pytest test_validator.py -v 全通過
```

**Agent 2 — Registry CRUD 實作（TDD）**
```
讀取：Batch 1 產出
TDD 流程：
1. 建立 src/opentree/registry/models.py (RegistryEntry, RegistryData, frozen=True)
2. 寫 test_registry.py 全部 15 tests（RED）
3. 實作 registry.py — static methods, immutable pattern（GREEN）
4. 重構（IMPROVE）
驗證：pytest test_registry.py -v 全通過
```

### Batch 3: 10 Module Manifests + Integration Tests（≤ 25 min）

**Agent 1 — 建立 10 個 Module Manifests**
```
讀取：design.md（manifest 規格）、migration-map.md（依賴圖）、本計畫的 manifest 摘要
建立 modules/ 目錄結構：
- 10 個 opentree.json（完整 JSON 內容見本計畫 Part B agent 產出）
- 10 個 rules/.gitkeep
- 3 個 prompt_hook.py stub（memory, slack, requirement）
驗證：全部 opentree.json 可被 json.load() 解析
```

**Agent 2 — Integration Tests**
```
讀取：Batch 2 產出（validator, registry）
建立：
- tests/test_integration.py（10 tests: IV-01~10）
- tests/test_registry_integration.py（5 tests: IR-01~05）
驗證：pytest tests/test_integration.py tests/test_registry_integration.py -v
```

### Batch 4: Code Review + Coverage（≤ 20 min）

**Agent 1 — Code Review**
```
審查清單：
- [ ] 安全性：manifest path traversal 防護
- [ ] Immutability：所有 dataclass frozen=True，mutation 回傳新物件
- [ ] 錯誤處理：所有 IO 有 try/except
- [ ] 檔案大小：每個 < 400 行
- [ ] 命名一致性
- [ ] 測試品質：覆蓋所有 12 error codes
產出：code-review-report.md
若有 CRITICAL/HIGH → 修復後重新 review
```

**Agent 2 — Full Test Suite + Coverage**
```
執行：
1. uv run --directory /mnt/e/develop/mydev/opentree pytest -v --tb=short
2. uv run --directory /mnt/e/develop/mydev/opentree pytest --cov=opentree --cov-report=term-missing
驗證：
- 65 tests 全通過
- 覆蓋率 80%+
- 明確標注 mock vs 實際（本次全為實際呼叫，無 mock）
```

### Batch 5: 文件更新 + 收尾（≤ 15 min）

**Agent 1 — 文件更新**
```
1. 更新 progress.md：
   - 標記 1-A~1-E 為完成
   - 記錄 3 個歧義的解決方案
   - 記錄 agent 交互歷程
   - 記錄測試結果和覆蓋率

2. 更新 handoff.md：
   - Phase 1 完成，Phase 2 接續資訊

3. 量化驗證：
   - 檔案數量
   - 測試數量和通過率
   - 覆蓋率
```

---

## 風險評估

| 風險 | 嚴重度 | 緩解 |
|------|--------|------|
| WSL2 上 /mnt/e/ symlink 可能失敗 | MEDIUM | Phase 1 不建 symlink（純 JSON）；Phase 2 需測試 |
| jsonschema error message 映射不精確 | MEDIUM | 用 iter_errors() + validator 屬性映射 |
| $OPENTREE_HOME placeholder 在 permissions 中 | MEDIUM | Phase 1 manifests 保持原樣；Phase 2 才解析 |
| circular dep DFS edge cases | LOW | 自迴圈獨立檢查 + 全節點 DFS |
| 同 OS user 多實例共用 ~/.claude/ | MEDIUM | Phase 1 記錄風險；Phase 2 驗證 CLAUDE_CONFIG_DIR |

## 成功標準

- [ ] 65 tests 全通過
- [ ] 覆蓋率 80%+
- [ ] 10 個 manifest 全部通過 schema 驗證
- [ ] 依賴圖 acyclic 驗證通過
- [ ] 所有 dataclass 使用 frozen=True
- [ ] 所有檔案 < 400 行
- [ ] jsonschema 為唯一 runtime dependency
- [ ] OpenSpec 文件完整更新
