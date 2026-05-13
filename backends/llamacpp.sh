#!/usr/bin/env bash
# backends/llamacpp.sh — raw llama.cpp via llama-server.
# Pulls model directly from HuggingFace via -hf flag.
# OpenAI-compat endpoint: http://localhost:<port>/v1

# shellcheck source=./_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

LLAMACPP_PORT="${LLAMACPP_PORT:-8080}"
LLAMACPP_CTX="${LLAMACPP_CTX:-65536}"

backend_start() {
    local model_id="$1" alias="$2"
    local logfile="/tmp/llamacpp-bench.log"

    # Sanity: not already in use
    if lsof -iTCP:"$LLAMACPP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        warn "Port $LLAMACPP_PORT already in use — attempting to kill prior llama-server"
        pkill -f "llama-server.*--port $LLAMACPP_PORT" || true
        sleep 2
    fi

    # model_id syntax accepted:
    #   <repo>                       → llama-server picks the default file
    #   <repo>:<quant>               → llama-server preset shortcut (e.g. ":Q4_K_M")
    #   <repo>::<filename.gguf>      → explicit file via --hf-file (bypasses preset lookup;
    #                                  use this when the preset shortcut 404s, or when a repo
    #                                  publishes split shards and you want a specific first shard)
    local hf_args=()
    if [[ "$model_id" == *"::"* ]]; then
        local hf_repo="${model_id%%::*}"
        local hf_file="${model_id#*::}"
        hf_args=(-hf "$hf_repo" --hf-file "$hf_file")
        log "Starting llama-server: repo=$hf_repo  file=$hf_file  (alias: $alias)..."
    else
        hf_args=(-hf "$model_id")
        log "Starting llama-server with $model_id (alias: $alias)..."
    fi

    # Key flags:
    #   --jinja          : enable Jinja chat template (required for tool calling)
    #   --kv-unified     : faster KV access on Apple Silicon
    #   --flash-attn on  : flash attention (Metal supports it)
    #   --cache-type-*   : q8_0 KV cache halves memory at minimal quality loss
    llama-server \
        "${hf_args[@]}" \
        --alias "$alias" \
        --port "$LLAMACPP_PORT" \
        --jinja \
        --kv-unified \
        --cache-type-k q8_0 --cache-type-v q8_0 \
        --flash-attn on \
        --batch-size 4096 --ubatch-size 1024 \
        --ctx-size "$LLAMACPP_CTX" \
        >"$logfile" 2>&1 &
    BACKEND_PID=$!
    export BACKEND_PID
    export BACKEND_ENDPOINT="http://localhost:${LLAMACPP_PORT}"
    export BACKEND_MODEL_NAME="$alias"
    export BACKEND_LOGFILE="$logfile"

    log "Waiting for llama-server (pid $BACKEND_PID, logs: $logfile)..."
    if ! wait_for_endpoint "${BACKEND_ENDPOINT}/health" 300; then
        cat "$logfile" | tail -30 >&2
        fail "llama-server failed to become ready within 5 min"
    fi
    log "llama.cpp ready. Endpoint: ${BACKEND_ENDPOINT}/v1  Alias: $alias"
}

backend_stop() {
    if [[ -n "${BACKEND_PID:-}" ]]; then
        kill_tree "$BACKEND_PID"
        log "Stopped llama-server (pid $BACKEND_PID)"
    fi
}

backend_health() {
    curl -sf "${BACKEND_ENDPOINT}/health" >/dev/null 2>&1
}
