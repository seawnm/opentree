#!/usr/bin/env bash
# OpenTree Instance Deployment Script
#
# Usage:
#   scripts/deploy.sh --target bot_COGI        # Deploy a specific instance
#   scripts/deploy.sh --all                    # Deploy all instances in instances.conf
#   scripts/deploy.sh --all --skip-init        # Update package only, skip opentree init
#   scripts/deploy.sh --target bot_COGI --dry-run
#
# Deployment steps per instance:
#   1. Write .stop_requested flag (prevents wrapper auto-restart)
#   2. SIGTERM the WRAPPER — wrapper's cleanup trap shuts down bot + watchdog
#   3. Wait for wrapper to exit (max 60s, SIGKILL fallback)
#   4. Kill any orphan bot/stale processes
#   5. Clean up state files (wrapper.pid, bot.pid, bot.heartbeat)
#   6. pip install --upgrade opentree[slack] into instance .venv
#   7. opentree init --cmd-mode venv --force (regenerate run.sh + update modules)
#   8. nohup run.sh (start new wrapper)
#
# One-time setup for new instances (before first deploy):
#   python3 -m venv <home>/.venv
#   <home>/.venv/bin/pip install '<opentree_src>[slack]'
#   Then run this script.

set -euo pipefail

OPENTREE_SRC="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$OPENTREE_SRC/instances.conf"

SKIP_INIT=0
DRY_RUN=0
TARGET=""
DEPLOY_ALL=0

# ---- Parse arguments ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)    TARGET="$2"; shift 2 ;;
        --all)       DEPLOY_ALL=1; shift ;;
        --skip-init) SKIP_INIT=1; shift ;;
        --dry-run)   DRY_RUN=1; shift ;;
        --help|-h)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ $DEPLOY_ALL -eq 0 && -z "$TARGET" ]]; then
    echo "Usage: $0 --target <name> | --all [--skip-init] [--dry-run]" >&2
    exit 1
fi

if [[ ! -f "$CONF" ]]; then
    echo "ERROR: instances.conf not found at $CONF" >&2
    exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [DRY-RUN] $*"
    else
        "$@"
    fi
}

# ---- Stop a running instance (wrapper-first approach) ----
# Always target the WRAPPER pid, not the bot directly.
# The wrapper's SIGTERM trap cascades to bot + watchdog cleanly.
stop_instance() {
    local name="$1" home="$2"
    local wrapper_pid_file="$home/data/wrapper.pid"
    local bot_pid_file="$home/data/bot.pid"

    log "[$name] Stopping instance..."

    # Write stop flag: prevents wrapper from auto-restarting after shutdown
    if [[ -d "$home/data" ]]; then
        run touch "$home/data/.stop_requested"
    fi

    # Stop wrapper (which cascades SIGTERM to bot + watchdog via cleanup trap)
    if [[ -f "$wrapper_pid_file" ]]; then
        local wpid
        wpid=$(cat "$wrapper_pid_file" 2>/dev/null | tr -d '[:space:]')
        if [[ -n "$wpid" ]] && kill -0 "$wpid" 2>/dev/null; then
            log "[$name] SIGTERM -> wrapper PID $wpid"
            run kill -TERM "$wpid"

            if [[ $DRY_RUN -eq 0 ]]; then
                local elapsed=0
                while [[ $elapsed -lt 60 ]] && kill -0 "$wpid" 2>/dev/null; do
                    sleep 1
                    elapsed=$((elapsed + 1))
                done
                if kill -0 "$wpid" 2>/dev/null; then
                    log "[$name] WARNING: wrapper stuck after 60s — sending SIGKILL"
                    kill -9 "$wpid" 2>/dev/null || true
                    sleep 2
                fi
                log "[$name] Wrapper stopped (${elapsed}s)"
            fi
        else
            log "[$name] No running wrapper (PID file exists but process $wpid is gone)"
        fi
    else
        log "[$name] No wrapper.pid found — instance may already be stopped"
    fi

    # Kill any orphaned bot process the wrapper didn't clean up
    if [[ -f "$bot_pid_file" ]]; then
        local bpid
        bpid=$(cat "$bot_pid_file" 2>/dev/null | tr -d '[:space:]')
        if [[ -n "$bpid" ]] && kill -0 "$bpid" 2>/dev/null; then
            log "[$name] WARNING: orphan bot process PID $bpid — SIGKILL"
            run kill -9 "$bpid" || true
            sleep 1
        fi
    fi

    # Belt-and-suspenders: kill any stale processes still referencing this home
    if [[ $DRY_RUN -eq 0 ]]; then
        local stale_pids
        stale_pids=$(pgrep -f "opentree.*${home}|${home}.*opentree" 2>/dev/null || true)
        if [[ -n "$stale_pids" ]]; then
            log "[$name] WARNING: stale processes — SIGKILL: $(echo "$stale_pids" | tr '\n' ' ')"
            echo "$stale_pids" | xargs kill -9 2>/dev/null || true
            sleep 1
        fi
    fi

    # Remove all stale state files so the new wrapper starts from a clean slate
    run rm -f \
        "$home/data/wrapper.pid" \
        "$home/data/bot.pid" \
        "$home/data/bot.heartbeat" \
        "$home/data/.stop_requested"

    log "[$name] Stopped and cleaned up"
}

# ---- Deploy one instance ----
deploy_instance() {
    local name="$1" home="$2" bot_name="$3"
    local venv="$home/.venv"

    log "[$name] ======= Starting deployment ======="

    # Pre-flight: instance venv must exist
    if [[ ! -f "$venv/bin/opentree" ]]; then
        log "[$name] ERROR: .venv not found at $venv"
        log "[$name] One-time setup required:"
        log "[$name]   python3 -m venv $venv"
        log "[$name]   $venv/bin/pip install '$OPENTREE_SRC[slack]'"
        log "[$name]   Then re-run this deploy script."
        return 1
    fi

    # Record current version for logging
    local old_ver
    old_ver=$("$venv/bin/opentree" --version 2>/dev/null || echo "unknown")

    # Step 1-5: Stop the instance cleanly
    stop_instance "$name" "$home"

    # Step 6: Update the installed package
    log "[$name] Updating opentree package..."
    run "$venv/bin/pip" install --upgrade "$OPENTREE_SRC[slack]" --quiet

    local new_ver
    new_ver=$("$venv/bin/opentree" --version 2>/dev/null || echo "unknown")
    log "[$name] Package version: $old_ver -> $new_ver"

    # Step 7: Re-init (regenerate run.sh with correct BOT_CMD + update bundled modules)
    if [[ $SKIP_INIT -eq 0 ]]; then
        log "[$name] Re-initializing with --cmd-mode venv --force..."
        run "$venv/bin/opentree" init \
            --home "$home" \
            --bot-name "$bot_name" \
            --cmd-mode venv \
            --force \
            --non-interactive
        log "[$name] run.sh regenerated (BOT_CMD -> $venv/bin/opentree)"
    else
        log "[$name] Skipping opentree init (--skip-init)"
    fi

    # Step 8: Start the new wrapper
    log "[$name] Starting wrapper..."
    mkdir -p "$home/data/logs"
    if [[ $DRY_RUN -eq 0 ]]; then
        nohup bash "$home/bin/run.sh" >> "$home/data/logs/wrapper.log" 2>&1 &
        local new_wpid=$!
        sleep 3
        if kill -0 "$new_wpid" 2>/dev/null; then
            log "[$name] Wrapper started (PID: $new_wpid)"
        else
            log "[$name] ERROR: Wrapper failed to start!"
            log "[$name] Check: tail $home/data/logs/wrapper.log"
            return 1
        fi
    else
        echo "  [DRY-RUN] nohup bash $home/bin/run.sh >> $home/data/logs/wrapper.log 2>&1 &"
    fi

    log "[$name] ======= Deployment complete ======="
    echo ""
}

# ---- Main: iterate instances.conf ----
target_found=0

while IFS=: read -r iname ihome ibot_name; do
    # Skip comments and blank lines
    [[ "$iname" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${iname// /}" ]] && continue

    if [[ $DEPLOY_ALL -eq 1 ]] || [[ "$iname" == "$TARGET" ]]; then
        target_found=1
        deploy_instance "$iname" "$ihome" "$ibot_name"
    fi
done < "$CONF"

# Validate that --target was actually found in the config
if [[ -n "$TARGET" && $target_found -eq 0 ]]; then
    echo "ERROR: Instance '$TARGET' not found in $CONF" >&2
    echo "Available instances:" >&2
    grep -v '^#' "$CONF" | grep -v '^[[:space:]]*$' | cut -d: -f1 | sed 's/^/  /' >&2
    exit 1
fi

log "All deployments complete."
