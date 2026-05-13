#!/usr/bin/env bash
# run.sh — Orchestrate cc-local-bench across (backend, model) combos.
#
# Usage:
#   ./run.sh round1                          # run Round 1 (runtime shootout)
#   ./run.sh round2                          # run Round 2 (model shootout on winning runtime)
#   ./run.sh <run_name>                      # run a single named combo from config.yaml
#   ./run.sh --with-power <run_name>         # ALSO capture per-trial power via powermetrics
#
# --with-power: macOS-only. Requires sudo (powermetrics needs root). The script
# refreshes sudo in the background for the run's duration. Plug in for cleanest
# numbers; on-battery is warned-but-allowed. Per-trial samples land in
# trial-N.power.txt (raw) and trial-N.power.json (aggregated); idle baseline per
# combo lands in idle_baseline.{txt,json}.
#
# Output: results/run-<timestamp>/{combo}/{trial}.json + server_log.txt

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=backends/_common.sh
source "$ROOT/backends/_common.sh"

# ── Pre-flight ───────────────────────────────────────────────────────────────
command -v claude >/dev/null || fail "claude (Claude Code CLI) not on PATH"
command -v yq     >/dev/null || fail "yq not installed. brew install yq"
command -v jq     >/dev/null || fail "jq not installed. brew install jq"
command -v uv     >/dev/null || fail "uv not installed. brew install uv  (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
resolve_timeout_cmd       || fail "GNU timeout not found. macOS: brew install coreutils (provides 'gtimeout'). Linux: install coreutils."

# Fixture sanity check — the stub MUST be the failing baseline. If a prior
# misconfigured run leaked an implementation into fixture/, the benchmark is
# invalid (the model has nothing to solve). Refuse to start so we don't
# silently produce green results from contaminated fixture.
if ! grep -q 'raise NotImplementedError' "$ROOT/fixture/phone_utils.py" 2>/dev/null; then
    fail "fixture/phone_utils.py is missing 'raise NotImplementedError' — the failing baseline has been corrupted. Restore the original stub before running. See CLAUDE.md 'Critical rule: fixture/ is the test subject'."
fi

CONFIG="$ROOT/config.yaml"
[[ -f "$CONFIG" ]] || fail "config.yaml not found"

# ── Flag parsing (positional + --with-power) ─────────────────────────────────
WITH_POWER=0
POSITIONAL=()
for arg in "$@"; do
    case "$arg" in
        --with-power) WITH_POWER=1 ;;
        --*) fail "unknown flag: $arg" ;;
        *) POSITIONAL+=("$arg") ;;
    esac
done
set -- "${POSITIONAL[@]}"

# ── Power-measurement pre-flight (when --with-power is set) ──────────────────
if [[ $WITH_POWER -eq 1 ]]; then
    [[ "$(uname)" == "Darwin" ]] || fail "--with-power is macOS-only (powermetrics)"
    command -v powermetrics >/dev/null || fail "powermetrics not on PATH"
    log "Power measurement enabled. Authenticating sudo..."
    sudo -v || fail "sudo authentication failed"
    # Background sudo refresh so long runs don't lapse mid-trial
    ( while true; do sudo -n -v 2>/dev/null || break; sleep 50; done ) &
    SUDO_KEEPALIVE_PID=$!
    trap 'kill $SUDO_KEEPALIVE_PID 2>/dev/null || true' EXIT
    # AC-power check (non-fatal warn)
    if ! pmset -g batt | grep -q 'AC Power'; then
        warn "On battery — power numbers will include battery management noise. Plug in for cleanest measurement."
    else
        log "AC power confirmed."
    fi
fi

ROUND="${1:-round1}"
RUN_TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$ROOT/results/run-${RUN_TS}-${ROUND}"
mkdir -p "$RUN_DIR"

log "Run: $ROUND  →  $RUN_DIR"

# Snapshot config used
cp "$CONFIG" "$RUN_DIR/config.snapshot.yaml"

# Pull shared params (per-combo overrides applied later via // fallback)
DEFAULT_TRIALS=$(yq '.trials' "$CONFIG")
DEFAULT_TIMEOUT=$(yq '.timeout_seconds' "$CONFIG")
DEFAULT_MAX_TURNS=$(yq '.max_turns' "$CONFIG")
PROMPT=$(yq '.prompt' "$CONFIG")
ALLOWED_TOOLS=$(yq -r '.allowed_tools' "$CONFIG")

# Resolve combos list. If user passed a round name, use that array.
# Otherwise treat the arg as a specific combo name and find it.
if yq -e ".${ROUND} | length > 0" "$CONFIG" >/dev/null 2>&1; then
    COMBOS_YAML=$(yq ".${ROUND}" "$CONFIG")
else
    # Search both rounds for matching name
    COMBOS_YAML=$(yq "[.round1[], .round2[]] | map(select(.name == \"${ROUND}\"))" "$CONFIG")
    [[ "$(echo "$COMBOS_YAML" | yq 'length')" -gt 0 ]] || fail "No combo named '$ROUND'"
fi

N_COMBOS=$(echo "$COMBOS_YAML" | yq 'length')
log "Found $N_COMBOS combo(s) to run"

# ── Run loop ─────────────────────────────────────────────────────────────────
for i in $(seq 0 $((N_COMBOS - 1))); do
    NAME=$(echo "$COMBOS_YAML"     | yq -r ".[$i].name")
    BACKEND=$(echo "$COMBOS_YAML"  | yq -r ".[$i].backend")
    MODEL_ID=$(echo "$COMBOS_YAML" | yq -r ".[$i].model_id")
    ALIAS=$(echo "$COMBOS_YAML"    | yq -r ".[$i].alias")
    # Per-combo overrides; fall back to file-level defaults via yq's // operator
    TRIALS=$(echo    "$COMBOS_YAML" | yq -r ".[$i].trials           // $DEFAULT_TRIALS")
    TIMEOUT=$(echo   "$COMBOS_YAML" | yq -r ".[$i].timeout_seconds  // $DEFAULT_TIMEOUT")
    MAX_TURNS=$(echo "$COMBOS_YAML" | yq -r ".[$i].max_turns        // $DEFAULT_MAX_TURNS")

    COMBO_DIR="$RUN_DIR/$NAME"
    mkdir -p "$COMBO_DIR"

    echo
    log "════════════════════════════════════════════════════════════════"
    log " Combo: $NAME"
    log "   backend = $BACKEND"
    log "   model   = $MODEL_ID"
    log "   alias   = $ALIAS"
    log "   trials=$TRIALS  timeout=${TIMEOUT}s  max_turns=$MAX_TURNS"
    log "════════════════════════════════════════════════════════════════"

    # Source the backend script (sets backend_start/stop/health funcs)
    BACKEND_SCRIPT="$ROOT/backends/${BACKEND}.sh"
    [[ -f "$BACKEND_SCRIPT" ]] || fail "Backend script missing: $BACKEND_SCRIPT"
    # shellcheck disable=SC1090
    source "$BACKEND_SCRIPT"

    # Start backend; capture cold-start time
    COLD_START=$(date +%s.%N)
    backend_start "$MODEL_ID" "$ALIAS"
    COLD_END=$(date +%s.%N)
    COLD_DURATION=$(echo "$COLD_END - $COLD_START" | bc -l)
    log "Cold-start (start→ready): ${COLD_DURATION}s"

    # Persist server log if backend captured one
    if [[ -n "${BACKEND_LOGFILE:-}" && -f "$BACKEND_LOGFILE" ]]; then
        cp "$BACKEND_LOGFILE" "$COMBO_DIR/server_log.txt"
    fi

    echo "{\"cold_start_seconds\": $COLD_DURATION, \"endpoint\": \"$BACKEND_ENDPOINT\", \"model\": \"$BACKEND_MODEL_NAME\"}" \
        > "$COMBO_DIR/backend_meta.json"

    # ── Idle baseline (when --with-power, once per combo, after model loaded) ──
    if [[ $WITH_POWER -eq 1 ]]; then
        log "Capturing 5s idle baseline (model loaded, no inference)..."
        IDLE_RAW="$COMBO_DIR/idle_baseline.txt"
        IDLE_JSON="$COMBO_DIR/idle_baseline.json"
        sudo -n powermetrics --samplers cpu_power -i 1000 -n 5 \
            >"$IDLE_RAW" 2>/dev/null || warn "idle baseline capture failed"
        python3 "$ROOT/scripts/parse_powermetrics.py" "$IDLE_RAW" \
            >"$IDLE_JSON" 2>/dev/null || warn "idle baseline parse failed"
    fi

    # ── Trials ────────────────────────────────────────────────────────────
    for t in $(seq 1 "$TRIALS"); do
        log "─── Trial $t/$TRIALS ───"

        WORK_DIR="$(mktemp -d -t "ccbench-${NAME}-t${t}-XXXX")"
        cp -R "$ROOT/fixture/." "$WORK_DIR/"

        TRIAL_OUT="$COMBO_DIR/trial-${t}.json"
        TRIAL_STREAM="$COMBO_DIR/trial-${t}.stream.ndjson"
        TRIAL_PYTEST="$COMBO_DIR/trial-${t}.pytest.txt"
        TRIAL_POWER_RAW="$COMBO_DIR/trial-${t}.power.txt"
        TRIAL_POWER_JSON="$COMBO_DIR/trial-${t}.power.json"

        # Start powermetrics sidecar (background, sudo). It will be SIGINT-killed
        # after claude exits so it can flush its final samples cleanly.
        PM_PID=""
        if [[ $WITH_POWER -eq 1 ]]; then
            sudo -n powermetrics --samplers cpu_power -i 1000 \
                >"$TRIAL_POWER_RAW" 2>/dev/null &
            PM_PID=$!
            sleep 1.2  # let it warm up so we don't miss the first sample
        fi

        START=$(date +%s.%N)
        # Claude Code uses the OpenAI-compatible endpoint at $BACKEND_ENDPOINT.
        # We bypass permissions to allow full agentic loop (sandboxed in tmp dir).
        set +e
        # Hermetic invocation flags (critical — without these, the user's local
        # plugins/hooks/MCP/skills/CLAUDE.md leak into the benchmark and
        # contaminate results):
        #   --bare                     skip hooks, LSP, plugin sync, auto-memory,
        #                              keychain reads, CLAUDE.md auto-discovery
        #   --strict-mcp-config        only load MCP from --mcp-config; we pass
        #                              none, so the session gets zero MCP servers
        #   --disable-slash-commands   no skills resolved by /name
        #
        # CRITICAL: run claude with cwd=$WORK_DIR so the agent's relative paths
        # (e.g. "phone_utils.py") resolve INSIDE the tmpdir, not against $ROOT.
        # Without this, the agent sees the project's `fixture/` from cwd and
        # writes to it, corrupting the benchmark's failing baseline. Confirmed
        # contamination observed on 2026-05-12 — see CLAUDE.md rules on fixture/.
        # We DROP --add-dir "$WORK_DIR" because the work dir is now cwd itself.
        ( cd "$WORK_DIR" && \
          ANTHROPIC_BASE_URL="$BACKEND_ENDPOINT" \
          ANTHROPIC_API_KEY="local-bench" \
              "$TIMEOUT_CMD" "${TIMEOUT}" \
              claude \
                  -p "$PROMPT" \
                  --model "$ALIAS" \
                  --output-format stream-json \
                  --max-turns "$MAX_TURNS" \
                  --allowedTools "$ALLOWED_TOOLS" \
                  --permission-mode bypassPermissions \
                  --bare \
                  --strict-mcp-config \
                  --disable-slash-commands \
                  --verbose \
        ) >"$TRIAL_STREAM" 2>"$COMBO_DIR/trial-${t}.stderr.txt"
        CC_EXIT=$?
        set -e
        END=$(date +%s.%N)
        WALL=$(echo "$END - $START" | bc -l)

        # Stop powermetrics sidecar + parse
        if [[ $WITH_POWER -eq 1 && -n "$PM_PID" ]]; then
            sudo -n kill -INT "$PM_PID" 2>/dev/null || true
            wait "$PM_PID" 2>/dev/null || true
            python3 "$ROOT/scripts/parse_powermetrics.py" "$TRIAL_POWER_RAW" \
                --baseline "$COMBO_DIR/idle_baseline.json" \
                >"$TRIAL_POWER_JSON" 2>/dev/null || warn "power parse failed for trial $t"
        fi

        # Verify final state by running pytest on the work dir.
        # --no-project: don't treat $WORK_DIR as a uv project.
        # --isolated:   hermetic env, won't inherit site-packages from a base Python.
        # --with pytest: provision pytest in the ephemeral env.
        pushd "$WORK_DIR" >/dev/null
        set +e
        uv run --no-project --isolated --with pytest --quiet -- pytest --tb=no -q >"$TRIAL_PYTEST" 2>&1
        PYTEST_EXIT=$?
        set -e
        popd >/dev/null

        PASS_COUNT=$(grep -oE '[0-9]+ passed' "$TRIAL_PYTEST" | head -1 | grep -oE '[0-9]+' || echo "0")
        FAIL_COUNT=$(grep -oE '[0-9]+ failed' "$TRIAL_PYTEST" | head -1 | grep -oE '[0-9]+' || echo "0")

        # Per-trial summary
        cat >"$TRIAL_OUT" <<EOF
{
  "combo": "$NAME",
  "backend": "$BACKEND",
  "model_id": "$MODEL_ID",
  "alias": "$ALIAS",
  "trial": $t,
  "wall_clock_seconds": $WALL,
  "claude_exit_code": $CC_EXIT,
  "claude_timed_out": $([ $CC_EXIT -eq 124 ] && echo true || echo false),
  "pytest_exit_code": $PYTEST_EXIT,
  "tests_passed": $PASS_COUNT,
  "tests_failed": $FAIL_COUNT,
  "all_green": $([ "$PASS_COUNT" = "6" ] && [ "$FAIL_COUNT" = "0" ] && echo true || echo false),
  "work_dir": "$WORK_DIR"
}
EOF

        # Merge power data into trial JSON if present
        if [[ -f "$TRIAL_POWER_JSON" ]] && jq -e . "$TRIAL_POWER_JSON" >/dev/null 2>&1; then
            tmp_trial="$(mktemp)"
            jq --slurpfile p "$TRIAL_POWER_JSON" '.power = $p[0]' "$TRIAL_OUT" >"$tmp_trial" \
                && mv "$tmp_trial" "$TRIAL_OUT" \
                || rm -f "$tmp_trial"
        fi

        # Log line includes energy when available
        if [[ -f "$TRIAL_POWER_JSON" ]] && jq -e .energy_joules "$TRIAL_POWER_JSON" >/dev/null 2>&1; then
            ENERGY_J=$(jq -r '.energy_joules // "?"' "$TRIAL_POWER_JSON")
            log "  wall=${WALL}s  cc_exit=$CC_EXIT  pytest: ${PASS_COUNT}p/${FAIL_COUNT}f  energy=${ENERGY_J}J"
        else
            log "  wall=${WALL}s  cc_exit=$CC_EXIT  pytest: ${PASS_COUNT}p/${FAIL_COUNT}f"
        fi
    done

    backend_stop
    log "Combo done: $NAME"
done

echo
log "All combos complete. Generating report..."
uv run --no-project --quiet "$ROOT/score.py" "$RUN_DIR"
log "Report ready: $RUN_DIR/report.md"
