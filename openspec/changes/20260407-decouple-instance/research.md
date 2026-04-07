# Research: Decouple Instance

## 調研背景

opentree instance (bot_walter) 的 run.sh 硬編碼了 opentree source project 路徑，
導致 instance 無法獨立部署。需要找到解耦方案。

## 候選方案

### run.sh 解耦

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| A: OPENTREE_PROJECT_DIR 環境變數 | 最小改動，但仍依賴 source 存在 | 未完全解耦 |
| B: pip install -e + bare command | **採用** — instance 自帶套件，完全獨立 | — |
| C: uv tool run opentree | 最乾淨，但需發布到 PyPI | 尚未發布 |

### 偵測邏輯改進

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 1: 只改 init.py 模板 | 已生成的 run.sh 不受惠 | 不夠彈性 |
| 2: run.sh runtime 環境變數覆蓋 | **採用** — 不需重跑 init 即可切換 | — |
| 3: 完全重寫 run.sh 偵測邏輯 | 過度設計 | 向後相容風險 |

### _resolve_opentree_cmd() 偵測順序

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 1: pyproject.toml → bare | 現有邏輯，source checkout 永遠硬編碼 | 就是問題所在 |
| 2: shutil.which → pyproject.toml → bare | **採用** — 優先用 PATH 上的 opentree | — |
| 3: --cmd-mode 強制指定 | **採用（搭配 2）** — 明確覆蓋自動偵測 | — |

### E2E 測試外部依賴

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 1: 環境變數 + skip | **採用** — 簡潔，E2E 本就需要 live 環境 | — |
| 2: Mock subprocess | 過度設計，E2E 測的就是真實整合 | 違背 E2E 本意 |
| 3: 移除 slack-bot 工具呼叫 | 測試 setup/cleanup 需要這些工具 | 會降低測試品質 |

## 調研結論

三管齊下：
1. `_resolve_opentree_cmd()` 新增 `shutil.which` 偵測 + `--cmd-mode` 參數
2. run.sh 模板加入 `OPENTREE_CMD` 環境變數 runtime 覆蓋
3. E2E 測試用環境變數 + skip、module rules 改路徑
