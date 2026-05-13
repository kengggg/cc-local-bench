#!/usr/bin/env bash
# backends/_common.sh — helpers sourced by each backend script.
# Each backend script must define:
#   backend_start <model_id> <alias>   → sets BACKEND_ENDPOINT, BACKEND_PID
#   backend_stop                       → kills the server
#   backend_health                     → returns 0 if server responds

# ── Pretty-printers ──────────────────────────────────────────────────────────
log()   { printf '\033[34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
warn()  { printf '\033[33m[WARN]\033[0m %s\n'  "$*" >&2; }
fail()  { printf '\033[31m[FAIL]\033[0m %s\n'  "$*" >&2; exit 1; }

# ── Wait until an HTTP endpoint becomes ready ─────────────────────────────────
# Usage: wait_for_endpoint <url> <max_seconds>
wait_for_endpoint() {
    local url="$1" max="${2:-180}" elapsed=0
    while (( elapsed < max )); do
        if curl -sf -m 2 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        printf '.' >&2
    done
    printf '\n' >&2
    return 1
}

# ── Resolve a GNU-compatible `timeout` binary ────────────────────────────────
# Linux ships `timeout`. macOS doesn't — `brew install coreutils` provides
# `gtimeout`. Exported so callers can do `"$TIMEOUT_CMD" 600 some-command`.
resolve_timeout_cmd() {
    if command -v timeout  >/dev/null 2>&1; then TIMEOUT_CMD="timeout";  return 0; fi
    if command -v gtimeout >/dev/null 2>&1; then TIMEOUT_CMD="gtimeout"; return 0; fi
    return 1
}

# ── Kill a process tree (server + children) by PID ───────────────────────────
kill_tree() {
    local pid="$1"
    [[ -z "$pid" ]] && return 0
    # macOS-friendly: kill children first, then parent
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
}
