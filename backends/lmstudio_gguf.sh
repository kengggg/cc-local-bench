#!/usr/bin/env bash
# backends/lmstudio_gguf.sh — LM Studio with llama.cpp/GGUF runtime.
# Same server, just different model format. Apples-to-apples vs llama-cpp raw.
# OpenAI-compat endpoint: http://localhost:1234/v1

# shellcheck source=./_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

LMS_PORT="${LMS_PORT:-1234}"

backend_start() {
    local model_id="$1" alias="$2"
    export BACKEND_ENDPOINT="http://localhost:${LMS_PORT}"
    export BACKEND_MODEL_NAME="$model_id"
    export BACKEND_PID=""

    command -v lms >/dev/null || fail "'lms' CLI not found. Install: ~/.lmstudio/bin/lms bootstrap"

    if ! curl -sf "${BACKEND_ENDPOINT}/v1/models" >/dev/null 2>&1; then
        log "Starting LM Studio server on port $LMS_PORT..."
        lms server start --port "$LMS_PORT" >/tmp/lms-server.log 2>&1 || \
            fail "lms server start failed"
        wait_for_endpoint "${BACKEND_ENDPOINT}/v1/models" 30 || fail "LM Studio server didn't come up"
    fi

    if ! lms ls 2>/dev/null | grep -q "$(basename "$model_id")"; then
        log "Downloading $model_id (GGUF)..."
        lms get "$model_id" --gguf --yes || fail "lms get failed for $model_id"
    fi

    lms unload --all 2>/dev/null || true
    sleep 2

    log "Loading $model_id with llama.cpp/GGUF runtime..."
    lms load "$model_id" --identifier "$alias" --gpu max --ttl 1800 \
        || fail "lms load failed for $model_id"

    log "LM Studio (GGUF) ready. Endpoint: ${BACKEND_ENDPOINT}/v1  Identifier: $alias"
}

backend_stop() {
    log "Unloading GGUF model..."
    lms unload --all 2>/dev/null || true
}

backend_health() {
    curl -sf "${BACKEND_ENDPOINT}/v1/models" >/dev/null 2>&1
}
