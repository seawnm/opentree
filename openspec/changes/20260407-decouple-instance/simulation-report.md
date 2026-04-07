# Flow Simulation Report: Decouple Instance

## Summary
20 scenarios tested: 14 PASS, 6 FAIL
2 HIGH + 5 MEDIUM issues found, all with fix plans

## Issues

| # | Severity | Description | Fix |
|---|----------|-------------|-----|
| 1 | HIGH | uv run cmd 嵌入 single-quotes, bash 變數展開後變成 literal chars | 移除 quotes |
| 2 | HIGH | `Path("")` is truthy, E2E skip 不生效 | 用 None sentinel |
| 3 | MEDIUM | `--cmd-mode` 無效值靜默 fallback | 加 validation |
| 4 | MEDIUM | auto mode 選到錯誤 binary 無提示 | 加 echo |
| 5 | MEDIUM | E2E_FOREIGN_PATH 無 default | 用 synthetic path |
| 6 | MEDIUM | `--force` 改變 cmd 無 warning | 加 warning |
| 7 | MEDIUM | test_e2e_extensions cleanup 呼叫 DOGI_DIR 需 guard | 加 None check |
