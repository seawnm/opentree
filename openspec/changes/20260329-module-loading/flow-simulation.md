# Flow Simulation Report: OpenTree Phase 1

> 執行日期：2026-03-29
> 推演 Agent 數：3（2 路徑比較 + 1 系統推演）

## 決策推演：loading.rules 路徑格式

### Approach A: 純檔名 `^[a-z0-9-]+\.md$`
- 測試 15 情境：12 PASS / 3 conditional
- 問題 3 個（1H, 1M, 1L）
- 優勢：可攜性、rename 安全性、無冗餘

### Approach B: rules/ 前綴 `^rules/[a-z0-9-]+\.md$`
- 測試 22 情境：16 PASS / 6 FAIL
- 問題 5 個（2H, 1M, 2L）
- 優勢：自描述性、未來目錄擴充

### 決策：採用 Approach A（使用者確認 2026-03-29）

---

## 系統推演：完整 Phase 1 流程

### Normal Flows

| # | 情境 | 結果 | 備註 |
|---|------|------|------|
| N1 | Fresh install 7 pre-installed modules | PASS | 拓撲排序正確 |
| N2 | Install optional requirement (slack installed) | PASS | depends_on 滿足 |
| N3 | Batch validate 10 manifests + DAG acyclic | PASS | 修正 design.md 後一致 |
| N4 | Generate CLAUDE.md from registry | DEFERRED | Phase 2 scope（RegistryEntry 缺 triggers） |
| N5 | Remove stt module | PASS | registry 正確更新 |
| N6 | Validator bare filename resolve | PASS | modules/{name}/rules/{filename} |
| N7 | Registry roundtrip save/load | PASS | |

### Edge Cases

| # | 情境 | 結果 | Error Code |
|---|------|------|-----------|
| E1 | Install requirement without slack | PASS | DEPENDENCY_NOT_FOUND |
| E2 | Remove personality with guardrail dependent | PASS | 拒絕 + reverse-dep message |
| E3 | Circular dependency foo<->bar | PASS | CIRCULAR_DEPENDENCY |
| E4 | Name mismatch dir vs manifest | PASS | NAME_MISMATCH |
| E5 | Invalid JSON syntax | PASS | MANIFEST_PARSE_ERROR |
| E6 | Pre-installed depends on optional | NOTED | 無專用 ErrorCode（P2） |
| E7 | Same filename in two modules | PASS | symlink namespace 隔離 |
| E8 | Extra unknown field | PASS | SCHEMA_VALIDATION_ERROR |
| E9 | Corrupted registry.json | PASS | load raises ValueError |
| E10 | Concurrent install | KNOWN LIMIT | 單進程 scope，Phase 1 不處理 |

### 17 情境總結：15 PASS / 1 DEFERRED / 1 KNOWN LIMIT

---

## 發現的問題與修正

### HIGH（已修正）

| # | 問題 | 修正動作 |
|---|------|---------|
| #1 | handoff.md 的 loading.rules pattern 錯誤 | ✅ 修正為 `^[a-z0-9-]+\.md$` |
| #2 | personality/slack 的 depends_on 跨文件不一致 | ✅ design.md 統一為 `["core"]` |
| #7 | design.md scheduler example 仍為 `["slack"]` | ✅ 修正為 `["core"]` |

### MEDIUM（記錄，Phase 1 可接受）

| # | 問題 | 處置 |
|---|------|------|
| #3 | generate_claude_md 存取 RegistryEntry.triggers | Phase 2 scope |
| #4 | list_installed() sort order 未定義 | Registry.list_modules() 回傳 sorted tuple |
| #5 | 無 pre-installed-depends-optional ErrorCode | 記錄為 P2 enhancement |
| #6 | registry.json 無 file locking | Phase 1 單進程 scope |

### LOW（已記錄）

| # | 問題 | 處置 |
|---|------|------|
| #8 | ValidationIssue 無 module_path field | error message 實作時含 full path |
| #9 | Registry.load() nonexistent 行為 | 回傳空 RegistryData |

---

## 共通實作要求

兩個路徑格式推演 agent **一致指出**：
- Validator error messages 必須包含 **module name + 完整解析路徑**
- Install command 用 `path.basename()` 取 symlink name，不用 regex strip
- `manifest.name` == 目錄名的一致性由 NAME_MISMATCH 檢查保證
