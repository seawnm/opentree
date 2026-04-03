# Research: opentree module update

## Background

需要版本比較功能來判斷 bundled module 是否比 installed 版本更新。

## Candidates

### 版本比較方案

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| `packaging.version.Version` | 功能完整、PEP 440 相容，但需加依賴 | 使用者約束「pyproject.toml 不加新依賴」 |
| `distutils.version.LooseVersion` | 已 deprecated (Python 3.12+) | deprecated，會觸發 warning |
| **tuple 比較** | ✅ 採用 | — |
| 正則解析 + 自訂邏輯 | 過度工程 | tuple 比較已足夠 |

### 升級策略

| 方案 | 評估結果 | 未採用原因 |
|------|----------|------------|
| 就地更新（修改現有 symlinks） | 複雜，需追蹤每個 link 的變化 | 風險高，現有 remove+create 模式更安全 |
| **移除 → 重新安裝** | ✅ 採用 | — |
| diff-based patch | 過度工程 | 模組只有 rules 文字檔，全量替換成本低 |

## Conclusion

- 版本比較：用 `tuple(int(x) for x in version.split("."))` 做純 Python tuple 比較
- 升級策略：先 remove_module_links + remove_module_permissions，再走 install 流程
- 複用現有 module.py 的 install/remove 邏輯，不從 init.py 提取
