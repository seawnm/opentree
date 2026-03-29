#!/bin/bash
# OpenTree P0: CLAUDE_CONFIG_DIR Verification Script
# Run manually on a machine with Claude CLI installed.
# Usage: bash tests/isolation/verify_config_dir.sh

set -euo pipefail

CUSTOM_DIR=$(mktemp -d /tmp/opentree-verify-XXXXXX)
echo "=== CLAUDE_CONFIG_DIR Verification ==="
echo "Custom dir: $CUSTOM_DIR"

# Check if claude is available
if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found. Install Claude Code first."
    exit 1
fi

echo ""
echo "--- Step 1: Create files with custom CLAUDE_CONFIG_DIR ---"
CLAUDE_CONFIG_DIR="$CUSTOM_DIR" claude --version 2>/dev/null || true

echo ""
echo "--- Step 2: List created files ---"
echo "Files in custom dir:"
find "$CUSTOM_DIR" -type f 2>/dev/null | sort || echo "(none)"
echo ""
echo "Directories in custom dir:"
find "$CUSTOM_DIR" -type d 2>/dev/null | sort || echo "(none)"

echo ""
echo "--- Step 3: Check if ~/.claude/ was modified ---"
echo "~/.claude/ contents (should NOT have new files from this test):"
ls -la ~/.claude/ 2>/dev/null || echo "(~/.claude/ does not exist)"

echo ""
echo "--- Step 4: KEY TEST - Does rules/ follow CLAUDE_CONFIG_DIR? ---"
mkdir -p "$CUSTOM_DIR/rules"
echo "# Test rule from custom config dir" > "$CUSTOM_DIR/rules/test-rule.md"
echo "Created: $CUSTOM_DIR/rules/test-rule.md"
echo "Check manually: does Claude load this rule when CLAUDE_CONFIG_DIR=$CUSTOM_DIR?"

echo ""
echo "--- Summary ---"
echo "Custom dir created: $CUSTOM_DIR"
echo "Run 'CLAUDE_CONFIG_DIR=$CUSTOM_DIR claude' to test rule loading"
echo "Then check if test-rule.md was loaded by Claude"

# Cleanup hint
echo ""
echo "Cleanup: rm -rf $CUSTOM_DIR"
