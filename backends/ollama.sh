#!/usr/bin/env bash
# backends/ollama.sh — Ollama backend.
# Ollama is usually already running as a service; we just ensure model is loaded.
# OpenAI-compat endpoint: http://localhost:11434/v1

# shellcheck source=./_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

OLLAMA_PORT="${OLLAMA_PORT:-11434}"

backend_start() {
    local model_id="$1" alias="$2"
    export BACKEND_ENDPOINT="http://localhost:${OLLAMA_PORT}"
    export BACKEND_PID=""   # we don't own the process

    # Ensure ollama daemon is up
    if ! curl -sf "${BACKEND_ENDPOINT}/" >/dev/null 2>&1; then
        log "Ollama daemon not running — starting it..."
        ollama serve >/tmp/ollama-bench.log 2>&1 &
        BACKEND_PID=$!
        wait_for_endpoint "${BACKEND_ENDPOINT}/" 30 || fail "Ollama failed to start"
    else
        log "Ollama daemon already running, reusing it"
    fi

    # Pull model if missing
    if ! ollama list | awk '{print $1}' | grep -qx "$model_id"; then
        log "Pulling $model_id (may take a while)..."
        ollama pull "$model_id" || fail "ollama pull failed for $model_id"
    fi

    # Warm-load into memory (cold-start timing happens here)
    log "Loading $model_id into memory..."
    curl -s "${BACKEND_ENDPOINT}/api/generate" \
        -d "{\"model\":\"$model_id\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":\"30m\"}" \
        >/dev/null || warn "warm-load request failed (continuing)"

    # Claude Code talks to Ollama via /v1; tell user to use the model_id as alias
    export BACKEND_MODEL_NAME="$model_id"
    log "Ollama ready. Endpoint: ${BACKEND_ENDPOINT}/v1  Model: $model_id"
}

backend_stop() {
    # Only stop if WE started the daemon (most setups have ollama already running)
    if [[ -n "$BACKEND_PID" ]]; then
        kill_tree "$BACKEND_PID"
        log "Stopped Ollama daemon (pid $BACKEND_PID)"
    else
        # Just unload the model to free memory
        if [[ -n "${BACKEND_MODEL_NAME:-}" ]]; then
            curl -s "${BACKEND_ENDPOINT}/api/generate" \
                -d "{\"model\":\"$BACKEND_MODEL_NAME\",\"keep_alive\":0}" >/dev/null || true
            log "Unloaded $BACKEND_MODEL_NAME"
        fi
    fi
}

backend_health() {
    curl -sf "${BACKEND_ENDPOINT}/" >/dev/null 2>&1
}
