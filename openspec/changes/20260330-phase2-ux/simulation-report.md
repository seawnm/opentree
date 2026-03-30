# Flow Simulation Report — Phase 2 UX + Phase 3 Ops

> 建立日期：2026-03-30
> 模擬場景：31（5 normal + 26 edge cases）
> 通過：23 | 失敗：8

## Summary

| Category | Tested | Passed | Failed |
|----------|--------|--------|--------|
| Normal Flows | 5 | 5 | 0 |
| ProgressReporter Edge Cases | 5 | 3 | 2 |
| ThreadContext Edge Cases | 5 | 4 | 1 |
| FileHandler Edge Cases | 6 | 4 | 2 |
| run.sh Edge Cases | 6 | 4 | 2 |
| Logging Edge Cases | 4 | 3 | 1 |

## HIGH Issues

### Issue #1: cleanup_temp 路徑與 download_files 不一致
- `cleanup_temp()` 用 `temp_base / thread_ts`，`download_files()` 用 `_safe_thread_dir()`
- 非標準 thread_ts 時路徑不一致，臨時目錄洩漏

### Issue #2 (from code review): run.sh `wait || true` 導致 exit_code 永遠為 0
- `set -e` 下 `|| true` 吃掉非零 exit code
- crash detection、restart、exit code 42 全部失效

## MEDIUM Issues
- _push_progress() 無例外處理（thread 靜默終止）
- wrapper cleanup() 無 timeout
- bot.py 不以 exit 42 退出
- reporter.start() 失敗使用者無回應
- log_dir 唯讀無 fallback
- run.sh $BOT_CMD 未引號（路徑含空格時崩潰）
- bot.py shutdown 重新讀取 config（應用快取值）
