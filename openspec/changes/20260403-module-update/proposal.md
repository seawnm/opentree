# Proposal: opentree module update 指令

## Requirements (user's original words, verbatim)

「opentree module update 指令 — 模組版本升級流程」
「比對 bundled manifest version vs registry installed version」
「版本更高則升級（複用現有安裝邏輯）」
「版本相同則跳過」
「支援 --all 批次升級」
「支援 --dry-run 預覽」
「交易式安全（失敗回滾）」
「pyproject.toml 不加新依賴」

## Problem

`opentree init` 安裝模組後，隨著 opentree 版本升級，bundled modules 的內容（rules、permissions、placeholders）可能更新。目前沒有指令讓使用者將已安裝的模組升級到新版本。只能手動 `module remove` + `module install` 或重新 `init --force`。

## Solution

新增 `opentree module update` 子指令：

```
opentree module update <MODULE_NAME>   # 升級單一模組
opentree module update --all           # 升級所有已安裝模組
opentree module update --all --dry-run # 預覽可升級清單
```

比對 bundled manifest version vs registry installed version，版本更高則用現有安裝邏輯重新安裝（移除舊 symlinks → 複製新 bundled → 建立新 symlinks → 更新 registry）。

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `src/opentree/cli/module.py` | 修改 | 新增 `update` 子指令 |
| `src/opentree/core/version.py` | **新增** | semver 比較工具（tuple-based，無外部依賴） |
| `tests/test_module_update.py` | **新增** | update 指令的單元測試 |
| `tests/test_version.py` | **新增** | version 比較的單元測試 |
| `CHANGELOG.md` | 修改 | 記錄新功能 |

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| 升級時 symlink 殘留 | LOW | 先 remove_module_links 再 create |
| 依賴順序（A depends on B，B 先升級） | LOW | --all 時按拓撲排序安裝 |
| 降級風險 | LOW | 預設不允許降級，需 --force |
