# Phase 3b 設計決策（Memory 升級）

## Decision 1: logger import 移植
**決策**：`from logger import logger` → `import logging; logger = logging.getLogger(__name__)`
**依據**：與 OpenTree 所有模組慣例一致

## Decision 2: 舊格式 migration
**決策**：在 `append_to_memory_file` 中偵測舊格式（parse 後所有 section 空但檔案非空）→ 用 regex 掃描 `- [category] content (date)` 行 → 根據 category 分配到對應 section
**依據**：保守策略，不丟失既有使用者資料

## Decision 3: remember/記住 → Pinned
**決策**：`extract_memories()` 第一個 pattern（remember|記住|記得|記下）命中時 category 直接設為 `"pinned"`，不走 `_classify()`
**mapping**：pinned→PINNED, preference→CORE, decision→CORE, general→ACTIVE
**依據**：使用者明確要求記住的項目應永久保留

## Decision 4: 並發寫入鎖
**決策**：模組層級 per-user `threading.Lock`（`_USER_LOCKS` dict + `_LOCKS_LOCK`），parse→add→write 整段持鎖
**依據**：OpenTree max_concurrent_tasks=2，並發完成同一使用者的 task 有實際風險

## Decision 5: title 參數
**決策**：`append_to_memory_file(memory_path, entries, user_name="")` 新增 user_name 參數，ensure_file 使用 `f"{user_name} 的記憶"` 作為 title
**依據**：可讀性，dispatcher 已有 resolved_name 可傳入

## Decision 6: memory_extraction_enabled 傳入
**決策**：`load_runner_config` 加入 `memory_extraction_enabled=data.get("memory_extraction_enabled", True)`
**依據**：確保 runner.json 設定能生效

## Decision 7: 去重 false negative
**決策**：接受此限制，只做字串等價去重，不做語意相似去重
**依據**：精確語意去重需 LLM/embedding，與「不呼叫 LLM」原則衝突
