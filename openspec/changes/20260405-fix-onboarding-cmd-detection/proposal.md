# Proposal: Fix Onboarding Command Detection

## Requirements (user's original words, verbatim)

> 修正剛剛安裝失敗的問題到專案中, 下次 on board 時不要在發生這個問題

## Problem

`opentree init` 產生的 `bin/run.sh` 使用裸 `opentree` 指令：

```bash
BOT_CMD=(opentree start --mode slack --home "$OPENTREE_HOME")
```

在開發環境中，opentree 未全域安裝（透過 `uv run --directory` 執行），導致：

1. **`opentree: command not found`**（exit code 127）— run.sh 找不到 opentree CLI
2. **`slack_bolt` ImportError**（exit code 1）— `[slack]` optional extra 未自動安裝

這兩個問題會讓 onboarding 的 `opentree init` → `bin/run.sh` 流程必定失敗，需要手動修復。

## Solution

1. `templates/run.sh` 新增 `{{opentree_cmd}}` placeholder
2. `cli/init.py` 在渲染 run.sh 時偵測 `opentree` 是否在 PATH：
   - 在 PATH → 使用裸 `opentree`
   - 不在 PATH → 使用 `uv run --directory <project_root> opentree`
3. 使用 `uv run` 模式時，自動執行 `uv sync --extra slack` 確保依賴就緒

## Change Scope

| File | Change Type | Description |
|------|-------------|-------------|
| `src/opentree/templates/run.sh` | Modify | `opentree` → `{{opentree_cmd}}` placeholder |
| `src/opentree/cli/init.py` | Modify | 新增指令偵測、placeholder 替換、依賴安裝 |
| `tests/test_init.py` | Modify | 新增/更新測試覆蓋偵測邏輯 |

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| `shutil.which` 在 venv 中可能誤判 | LOW | 同時檢查 `shutil.which` + `sys.executable` 路徑 |
| `uv sync` 失敗（網路問題） | LOW | 加 error handling，失敗時印警告但不中斷 init |
| 硬編碼 opentree project 路徑到 run.sh | LOW | 使用 `Path(__file__).resolve()` 計算，不靠 env var |
