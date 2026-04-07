# Flow Simulation Summary

## 關鍵發現

### Phase 1A（Owner 術語替換）
- 正常流程 5/5 PASS，Edge case 6/7 PASS
- 設計邏輯無缺陷，所有問題都是「測試需同步更新」
- **可以進入實作**

### Phase 1B（人設調整）
- **CRITICAL**：Phase 1B 必須在 Phase 1A 之後部署（{{owner_description}} 依賴 PlaceholderEngine 更新）
- **HIGH**：tone-rules.md 第 20 行首次互動範本必須同步更新
- **MEDIUM**：owner_description 空值需要 fallback 設計
- **MEDIUM**：Proxy 場景自我介紹需要決策（延後到 Proxy 模式實作時處理）
- **LOW**：denial-escalation.md 術語需同步更新

## 設計修正決策

1. **Phase 1A + 1B 合併為同一批次**（不可分開部署）
2. **tone-rules.md 全面更新**（加入變更清單）
3. **denial-escalation.md 加入變更清單**
4. **owner_description 空值 fallback**：character.md 設計為空值也通順的句型
   - 不用 `你是 {{owner_description}} 的個人 AI 助手`
   - 改用 `你是一個個人 AI 助手`，owner_description 放獨立段落
5. **Proxy 場景**：延後（OpenTree 目前為 single-user 架構，Proxy 模式尚未實作）

## 實作順序（合併後）

1. Phase 1A 核心：config.py → prompt.py → placeholders.py
2. Phase 1A CLI：init.py（CLI 參數）
3. Phase 1A 測試更新：test_config, test_prompt, test_placeholders, test_dispatcher, test_migration_integration, test_init
4. Phase 1B 人設：character.md → tone-rules.md → personality/opentree.json
5. Phase 1B 護欄：security-rules.md → permission-check.md → denial-escalation.md → guardrail/opentree.json
6. Phase 1B dispatcher：dispatcher.py（PromptContext 建構改名）

## 合併後影響的測試檔案

| 測試檔案 | 更新內容 |
|---------|---------|
| test_config.py | admin_description → owner_description, 新增 fallback 測試 |
| test_prompt.py | is_admin → is_owner, expected_keys 更新, 權限等級字串 |
| test_placeholders.py | _make_config() 改名, len(keys) 更新, alias 測試 |
| test_dispatcher.py | UserConfig 建構改名, is_admin → is_owner |
| test_migration_integration.py | _KNOWN_PLACEHOLDERS 加入 {{owner_description}} |
| test_init.py | 新增 owner_description key 斷言 |
| test_e2e_phase3.py | 確認 fallback 仍正常 |
