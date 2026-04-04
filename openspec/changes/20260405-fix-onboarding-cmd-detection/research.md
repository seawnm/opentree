# Research: Fix Onboarding Command Detection

## Background

`opentree init` 產生的 `bin/run.sh` 用裸 `opentree` 指令啟動 bot，
但開發環境透過 `uv run --directory` 執行，`opentree` 不在 PATH 上。
需要讓 init 自動偵測並產生正確的啟動指令。

## Candidates

### 指令偵測方式

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| `shutil.which("opentree")` | ✅ 採用 | — |
| 檢查 `sys.executable` 路徑 | 不夠直接 | 判斷 venv vs global 需要多層邏輯，且 `uv run` 環境下 sys.executable 指向 venv python |
| 環境變數 `OPENTREE_INSTALLED=1` | 侵入性高 | 需要使用者手動設定，違背自動偵測原則 |
| 永遠使用 `uv run` | 不夠通用 | 全域安裝（pip install -e）時 uv 可能不存在 |

### run.sh 模板策略

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 新增 `{{opentree_cmd}}` placeholder | ✅ 採用 | 最小變更，與現有 placeholder 機制一致 |
| run.sh 內自行偵測 | 增加 shell 複雜度 | 每次啟動都偵測不必要，且 shell 偵測不如 Python 可靠 |
| 分成兩個模板（global / uv） | 維護成本高 | 只差一行指令，不值得分檔 |

### 依賴安裝策略

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| `uv sync --extra slack`（init 時自動執行） | ✅ 採用 | — |
| 提示使用者手動安裝 | UX 差 | 使用者剛 init 就要多一步，容易忘記 |
| 把 slack-bolt 改為必要依賴 | 過度打包 | interactive 模式不需要 slack-bolt |

## Conclusion

1. 使用 `shutil.which("opentree")` 偵測可用性
2. 不在 PATH → 用 `uv run --directory <project_root>` 替代
3. 使用 `uv run` 模式時自動 `uv sync --extra slack`
4. project_root 用 `Path(__file__).resolve()` 計算（與 `_bundled_modules_dir()` 相同邏輯）
