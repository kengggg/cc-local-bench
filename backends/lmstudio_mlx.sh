#!/usr/bin/env bash
# backends/lmstudio_mlx.sh — LM Studio with MLX runtime.
# Model must already be downloaded with `lms get <id> --mlx`.
# OpenAI-compat endpoint: http://localhost:1234/v1

# shellcheck source=./_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

LMS_PORT="${LMS_PORT:-1234}"

backend_start() {
    local model_id="$1" alias="$2"
    export BACKEND_ENDPOINT="http://localhost:${LMS_PORT}"
    export BACKEND_MODEL_NAME="$model_id"
    export BACKEND_PID=""

    # Ensure `lms` is available
    command -v lms >/dev/null || fail "'lms' CLI not found. Install: ~/.lmstudio/bin/lms bootstrap"

    # Start LM Studio server if not running
    if ! curl -sf "${BACKEND_ENDPOINT}/v1/models" >/dev/null 2>&1; then
        log "Starting LM Studio server on port $LMS_PORT..."
        lms server start --port "$LMS_PORT" >/tmp/lms-server.log 2>&1 || \
            fail "lms server start failed"
        wait_for_endpoint "${BACKEND_ENDPOINT}/v1/models" 30 || fail "LM Studio server didn't come up"
    fi

    # Auto-download if missing (MLX variant)
    if ! lms ls 2>/dev/null | grep -q "$(basename "$model_id")"; then
        log "Downloading $model_id (MLX) — this can be large..."
        lms get "$model_id" --mlx --yes || fail "lms get failed for $model_id"
    fi

    # Unload any currently loaded model to free memory & ensure clean state
    lms unload --all 2>/dev/null || true
    sleep 2

    # Load with the alias as identifier; cold-start timing happens here
    log "Loading $model_id with MLX runtime..."
    lms load "$model_id" --identifier "$alias" --gpu max --ttl 1800 \
        || fail "lms load failed for $model_id"

    log "LM Studio (MLX) ready. Endpoint: ${BACKEND_ENDPOINT}/v1  Identifier: $alias"
}

backend_stop() {
    log "Unloading MLX model..."
    lms unload --all 2>/dev/null || true
}

backend_health() {
    curl -sf "${BACKEND_ENDPOINT}/v1/models" >/dev/null 2>&1
}
