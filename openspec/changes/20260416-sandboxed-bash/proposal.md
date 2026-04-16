# Proposal: Sandboxed Bash Execution via bubblewrap

## Background
OpenTree's Slack bot executes Claude CLI as a subprocess. Claude's Bash tool can access the host filesystem without restriction, creating a risk of data exfiltration or accidental modification of files outside the user's workspace.

## Problem
- Claude CLI Bash tool has access to all host filesystem paths
- In WSL2, /mnt/e/ exposes the Windows filesystem
- ~/.ssh, ~/.claude credentials are accessible
- Multi-user deployments risk cross-user data access

## Solution
Wrap ALL Claude CLI subprocesses with bubblewrap (bwrap) kernel namespace isolation.

## Key Decisions
1. **All users sandboxed**: No bypass for owner users. Zero-trust model: sandbox is infrastructure, not a permission.
2. **Network open**: --share-net preserves network (Claude CLI needs Anthropic API). BLOCKED_DOMAINS placeholder provided for future egress filtering.
3. **~/.claude RW**: Read-write mount so credentials and session state work normally.
4. **Fail-fast**: Bot refuses to start if bwrap is not installed (RuntimeError at startup).
5. **/workspace alias**: System prompt tells Claude its writable root is /workspace (sandboxed path alias).

## Affected Files
- NEW: src/opentree/runner/sandbox_launcher.py
- MOD: src/opentree/runner/claude_process.py
- MOD: src/opentree/runner/dispatcher.py
- MOD: src/opentree/runner/bot.py
- MOD: src/opentree/core/prompt.py
- NEW: tests/test_sandbox_launcher.py
- NEW: tests/isolation/test_sandbox_integration.py
- MOD: CHANGELOG.md
