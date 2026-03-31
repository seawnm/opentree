# E2E Verification — Code Review Log

> Date: 2026-03-31
> Phase: Phase 4 Code Review (post-E2E fixes)
> Source Thread: betaroom 1774800803.111649

---

## Review Scope

Code review of all changes made during the E2E verification phase, covering commits `82eec96`, `54db6cc`, and `72ecc6c`. Focus areas: SlackAPI parsing, admin command auth, receiver filtering, dedup architecture, and heartbeat logic.

---

## Findings

### CRITICAL

#### C1: status/help labeled "admin" but no auth check

- **File**: `dispatcher.py`
- **Problem**: `status` and `help` were categorized as "admin commands" alongside `shutdown`, but they had no authorization requirement. This was misleading — they are informational bot commands, not privileged operations. The naming implied a security boundary that didn't exist.
- **Fix**: Renamed the command dict from `_ADMIN_COMMANDS` to `_BOT_COMMANDS`. Updated help text to distinguish between general bot commands (`status`, `help`) and privileged admin commands (`shutdown`). Only `shutdown` requires `admin_users` authorization.
- **Status**: Fixed

---

### HIGH

#### H1: `dict()` fallback in `_extract_data` misleading

- **File**: `slack_api.py`
- **Problem**: The original `getattr(response, key, dict())` pattern was replaced with `_extract_data()`, but an early draft still had a `dict()` fallback that could mask API errors. When Slack returns an unexpected structure, silently returning an empty dict makes debugging very difficult.
- **Fix**: Removed `dict()` fallback. `_extract_data()` returns empty dict only for missing keys (expected case), and lets actual API errors propagate as exceptions.
- **Status**: Fixed

#### H2: Empty `admin_users` = all allowed footgun

- **File**: `config.py`
- **Problem**: If `admin_users` is configured as an empty list `[]`, the `user_id in admin_users` check returns `False` for everyone, meaning nobody can execute `shutdown`. However, if the field is omitted entirely from config and defaults to `None`, the auth check `task.user_id in config.admin_users` would raise `TypeError`. The inconsistent behavior between "empty list" and "missing field" is a footgun.
- **Fix**: Default `admin_users` to empty list `[]` (never `None`). Added startup log warning when `admin_users` is empty: "No admin_users configured — shutdown command will be rejected for all users." Added `__post_init__` validation ensuring all entries are non-empty strings.
- **Status**: Fixed

---

### MEDIUM

#### M1: Double heartbeat write

- **File**: `receiver.py`, `dispatcher.py`
- **Problem**: After fixing heartbeat to write before filters (commit `82eec96`), the original heartbeat write in `dispatcher.dispatch()` was left in place. Every dispatched task wrote heartbeat twice — once in receiver, once in dispatcher.
- **Fix**: Removed the redundant `_write_heartbeat()` call in `dispatcher.py`. Heartbeat is now written exactly once per event, in the receiver.
- **Status**: Fixed (commit `54db6cc`)

#### M2: admin_users no input validation

- **File**: `config.py`
- **Problem**: `admin_users` accepted any list content — integers, nested lists, `None` values. A typo like `admin_users: [12345]` (int instead of string) would silently fail all auth checks because `"U12345" in [12345]` is always `False`.
- **Fix**: Added `__post_init__` validation: each entry must be `isinstance(str)` and non-empty. Raises `ValueError` with descriptive message on invalid entries.
- **Status**: Fixed

---

### LOW

#### L1: Test improvements needed for dedup coverage

- **Problem**: Existing unit tests for `receiver.py` didn't cover the scenario where both `message` and `app_mention` events arrive for the same Slack message. The dedup race condition was only caught during E2E testing.
- **Recommendation**: Add integration test simulating concurrent event delivery to validate Layer 2 dedup in Dispatcher.
- **Status**: Noted (tests added as part of commit `72ecc6c`, +29 new tests)

#### L2: WSL2 bytecache stale `.pyc` issue

- **Problem**: When syncing code via `rsync` to WSL2, stale `.pyc` files in `__pycache__` directories can cause Python to load outdated handler registrations, exacerbating dedup issues.
- **Recommendation**: Document `__pycache__` cleanup as a required step after `rsync` deployment on WSL2 cross-filesystem setups.
- **Status**: Noted (documented in remaining-tasks.md)

#### L3: Help text formatting

- **Problem**: Help command output used a flat text format. For Slack, Block Kit formatting would be more readable.
- **Recommendation**: Low priority — current plain text is functional.
- **Status**: Deferred

---

## Summary

| Severity | Count | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 2 | 2 | 0 |
| MEDIUM | 2 | 2 | 0 |
| LOW | 3 | 0 | 3 |
| **Total** | **8** | **5** | **3** |

All CRITICAL, HIGH, and MEDIUM issues resolved in commits `82eec96`, `54db6cc`, `72ecc6c`.
