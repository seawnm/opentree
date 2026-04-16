# Research: Sandboxed Bash for OpenTree WSL2

## Sandbox Alternatives Evaluated

| Option | Isolation | WSL2 support | Complexity |
|--------|-----------|-------------|------------|
| bwrap (bubblewrap) | Kernel namespace | ✅ Native (kernel 5.10+) | Low |
| Docker | Container | ✅ Via Docker Desktop | High |
| nsjail | Syscall filter | ⚠️ Requires seccomp | High |
| AppArmor/SELinux | MAC | ⚠️ WSL2 limited | Medium |

**Selected: bwrap** — available as apt package, unprivileged namespaces, no daemon required.

## Windows Security Research
From Gemini deep research (2026-04-15):
- Native Windows (Git Bash): No kernel-level isolation in Claude Code. Only application-level path checks (bypassable).
- WSL2: Full Linux kernel namespace isolation via bwrap. Anthropic's recommended approach for Windows.
- Claude Cowork architecture: Uses bwrap on Linux/WSL2, Seatbelt on macOS.

## Network Decision: --share-net
Rationale: Claude CLI must reach api.anthropic.com. Closing network would break all AI functionality. Future: BLOCKED_DOMAINS list for domain-level filtering without architectural changes.

## ~/.claude RW Decision
Claude CLI writes session files to ~/.claude/projects/. Read-only would cause silent write failures. RW mount accepted as OpenTree is single-bot-user per instance.

## WSL2 Compatibility
- Kernel: 6.6.87.2-microsoft-standard-WSL2 ✅
- Ubuntu 22.04 (Jammy) ✅
- bwrap install: sudo apt-get install -y bubblewrap
- --ro-bind-try used for /lib64, /lib32 (not always present)
- Node.js nvm paths: dynamically detected via _resolve_node_bind()
