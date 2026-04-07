# Proposal: Owner Freedom — 術語替換、權限模型、記憶升級

## 需求背景

OpenTree 目前使用「Admin」概念管理 bot instance 的擁有者身份。使用者（Walter）提出 7 項改進需求，
核心目標是將概念從「管理者」轉向「擁有者」，最大化 Owner 的自由度，同時保留基本的安全護欄。

## 使用者原話

1. 使用 bypassPermissions 時，仍能限制在工作區中才能讀寫嗎？
2. Proxy 模式仍開放 subagent，我希望最大化自由度，但用護欄對指令做一些惡意意圖防護就好
3. 停用 memory_extractor 我想考慮一下，因為我希望 bot 能主動記住 owner 的事情和曾接觸的環境資訊
4. 工作區內的 CLAUDE.md 我希望也能讓 owner 自由修改，我要實現最大化自由度
5. 使用者若要輸入自己的 key 長期保存，只有一個 env 要怎麼作？我只是希望預設的 key 明碼不要被 owner 看到
6. Reset-bot 也不會異動使用者修改的 env，只有在 reset-bot-all 才會重製 env
7. Admin 替換成 owner 必做，我一開始就要讓使用者知道這個概念，同時也幫我調整 bot 的人設自我介紹

## 變更範圍

### Phase 1A: Owner 術語替換（核心 dataclass + prompt + placeholder）
- `src/opentree/core/config.py` — admin_description → owner_description
- `src/opentree/core/prompt.py` — is_admin → is_owner, 權限等級標記
- `src/opentree/core/placeholders.py` — {{admin_description}} → {{owner_description}} + 別名
- `src/opentree/runner/dispatcher.py` — is_admin → is_owner（PromptContext 建構）
- `src/opentree/cli/init.py` — --admin-users → --owner CLI 參數

### Phase 1B: 人設調整
- `modules/personality/rules/character.md` — 全面重寫人設定位
- `modules/personality/rules/tone-rules.md` — 自我介紹範本
- `modules/personality/opentree.json` — placeholder 改名
- `modules/guardrail/rules/security-rules.md` — 術語調整
- `modules/guardrail/rules/permission-check.md` — 術語調整

### Phase 2: CLAUDE.md 可編輯 + .env 分層
- `src/opentree/generator/claude_md.py` — Marker Comment 保護機制
- `src/opentree/cli/module.py` — refresh 時保護 owner 修改
- `src/opentree/runner/bot.py` — .env 分層載入
- 新增 `.env.defaults` + `.env.local` 機制

### Phase 3: Reset 分級
- `src/opentree/runner/dispatcher.py` — reset-bot / reset-bot-all 指令
- 新增 onboard snapshot 機制

### Phase 4: Memory System 升級
- 新增 `src/opentree/runner/memory_schema.py`
- 重寫 `src/opentree/runner/memory_extractor.py`
- RunnerConfig 新增記憶提取設定

### Phase 5: 三角色權限模型（Owner/Proxy/Restricted）
- 待 Phase 1-4 穩定後評估

## 向後相容策略

所有術語變更保留別名：
- `{{admin_description}}` 繼續運作（alias → owner_description）
- `context["is_admin"]` 繼續運作（alias → is_owner）
- `--admin-users` CLI 繼續運作（隱藏別名 → --owner）
- `runner.json.admin_users` 不改名（runner 層面概念）

## 影響分析

- 約 25+ 個檔案變更
- 所有既有測試需配合更新
- 無破壞性 API 變更（全部向後相容）
