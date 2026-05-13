# CLAUDE.md

Guidance for Claude Code (or any AI coding assistant) working inside this repo.

## What this repo is

`cc-local-bench` is a **benchmark harness**, not a product. It measures how well Claude Code can drive local-model inference runtimes through a fixed agentic coding task. The fixture (`fixture/`) is the *thing being solved by the model under test* — it is **not** code to maintain or extend casually.

## Critical rule: fixture/ is the test subject, not the codebase

The files in `fixture/` are the prompt's deliverable. **Do not "fix" them unless explicitly asked.**

- `fixture/phone_utils.py` ships with `raise NotImplementedError`. That is **correct and intentional** — it is the failing baseline.
- `fixture/test_phone_utils.py` defines the contract the benchmarked model must satisfy. Changing tests changes the benchmark and invalidates prior results.
- If asked to add a new benchmark task: create a *new* fixture directory (e.g. `fixture-longctx/`) and add a config option to point at it. Don't overwrite the existing one.

If you ever find yourself implementing `format_phone_number`, stop — you've misread the task. The whole point is that the local LLM does that.

### How the harness keeps fixture/ uncorrupted

The benchmarked model can edit any file under its cwd. Therefore `claude -p` is invoked from inside the per-trial tmpdir (via `(cd "$WORK_DIR" && claude …)` in `run.sh`), NOT from the project root. If you ever see the agent reading `fixture/phone_utils.py` (i.e. a relative path containing `fixture/`) in a `trial-*.stream.ndjson`, the cwd isolation has regressed — the agent is resolving paths against `$ROOT`. Fix `run.sh`, restore the stub, and re-run. `run.sh` pre-flight grep's for `raise NotImplementedError` and refuses to start if the stub is missing.

## Architecture in one paragraph

`run.sh` is the orchestrator. It reads `config.yaml`, picks a list of (backend, model) combos, and for each combo: (1) sources `backends/<name>.sh` which exposes `backend_start`/`backend_stop`/`backend_health`, (2) starts the inference server, (3) copies `fixture/` to a fresh tmpdir, (4) runs `claude -p` against the local OpenAI-compatible endpoint with stream-json output captured, (5) runs `pytest` on the resulting fixture to score correctness, (6) tears the backend down. `score.py` aggregates `results/run-*/<combo>/trial-*.json` plus the stream-json logs into `report.md` and `summary.json`.

## Repo layout

```
cc-local-bench/
├── run.sh                  # orchestrator — entry point
├── score.py                # post-run report generation
├── config.yaml             # combo matrix + shared params (trials, timeout, prompt)
├── fixture/                # the task: do NOT edit casually (see rule above)
│   ├── phone_utils.py      # stub the LLM must implement
│   ├── test_phone_utils.py # the contract — 6 tests
│   └── pytest.ini
├── backends/               # one driver per inference runtime
│   ├── _common.sh          # shared helpers (logging, wait_for_endpoint, kill_tree)
│   ├── ollama.sh
│   ├── llamacpp.sh
│   ├── lmstudio_mlx.sh
│   └── lmstudio_gguf.sh
└── results/                # generated; one subdir per ./run.sh invocation
    └── run-YYYYMMDD-HHMMSS-<round>/
        ├── config.snapshot.yaml
        ├── report.md
        ├── summary.json
        └── <combo>/
            ├── backend_meta.json
            ├── server_log.txt
            ├── trial-N.json
            ├── trial-N.stream.ndjson
            ├── trial-N.pytest.txt
            └── trial-N.stderr.txt
```

## The backend contract

Every file in `backends/*.sh` (except `_common.sh`) must define three shell functions and export specific env vars. When adding a new backend, follow this contract exactly — `run.sh` depends on it:

```bash
backend_start <model_id> <alias>
    # Must export:
    #   BACKEND_ENDPOINT   — e.g. "http://localhost:8080" (no /v1 suffix)
    #   BACKEND_PID        — pid of server process, or "" if we don't own it
    #   BACKEND_MODEL_NAME — the model identifier Claude Code should pass via --model
    # Optional:
    #   BACKEND_LOGFILE    — path to server log (will be copied into results)
    # On failure: must call `fail "reason"` (exits non-zero).

backend_stop
    # Tear down. Idempotent. Free GPU memory.

backend_health
    # Return 0 if endpoint responds, non-zero otherwise.
```

The endpoint must be **OpenAI-compatible at `/v1`** because Claude Code talks to it via `ANTHROPIC_BASE_URL`. All four current backends expose this natively.

## How `claude -p` is invoked

In `run.sh` the call is:

```bash
ANTHROPIC_BASE_URL="$BACKEND_ENDPOINT" \
ANTHROPIC_API_KEY="local-bench" \
    timeout "${TIMEOUT}" \
    claude \
        -p "$PROMPT" \
        --model "$ALIAS" \
        --output-format stream-json \
        --max-turns "$MAX_TURNS" \
        --allowedTools "$ALLOWED_TOOLS" \
        --permission-mode bypassPermissions \
        --verbose \
        --add-dir "$WORK_DIR"
```

Flag notes:
- `ANTHROPIC_API_KEY` value is irrelevant for local servers but must be **set** or Claude Code refuses to start.
- `--permission-mode bypassPermissions` is safe here because `$WORK_DIR` is a fresh tmpdir, not a real project.
- `--output-format stream-json` requires `--verbose`. Removing verbose silently produces empty output.
- `--add-dir` is what gives Claude Code write access to the fixture copy.
- **`--bare`, `--strict-mcp-config`, `--disable-slash-commands` are mandatory for benchmark validity.** Without them, `claude -p` inherits the operator's `~/.claude` config: SessionStart hooks (which dump multi-KB instructions into the model's context), plugins, custom skills, and any MCP servers (especially one that's `status: failed` — observed to hang the session until the timeout fires, producing 100% DNF). The first time we ran on a real machine, all three trials timed out with the model never receiving a single token because of a failed `github` MCP server in the operator's config. Do not remove these as "noise" — they're load-bearing.

## Common tasks

### Add a new backend

1. Create `backends/<name>.sh` implementing the three-function contract above.
2. Add a combo to `config.yaml` with `backend: <name>`.
3. Run `./run.sh <combo_name>` (single-combo mode) to smoke-test.
4. Once green, add to the appropriate round array.

### Add a new model to an existing backend

Just add a new entry to `config.yaml` under `round2` (or wherever). No code changes needed. `model_id` format varies per backend:
- Ollama: `qwen3-coder:30b` (must be pulled with `ollama pull` first). **`alias` MUST equal the exact Ollama tag** (e.g. `qwen3-coder:30b`, not `qwen3-coder`). Ollama's `/v1/chat/completions` endpoint requires exact tag matching; only its native `/api/*` endpoint does fuzzy matching. A short alias produces a 404 that Claude Code surfaces as "There's an issue with the selected model... It may not exist." Yes, this looks like a Claude-side error — it isn't.
- llama.cpp: three accepted forms, picked by `backends/llamacpp.sh`:
  - `<hf_repo>` — repo default
  - `<hf_repo>:<quant>` — llama-server's `:Q4_K_M`-style preset shortcut (convenient but 404s for some repos)
  - `<hf_repo>::<filename.gguf>` — explicit `--hf-file`; use this when the `:quant` form 404s (e.g. unsloth's Qwen3-Coder GGUFs) or when a repo publishes split shards and you need to pin the first shard. Find the exact filename via `curl -s 'https://huggingface.co/api/models/<repo>/tree/main' | jq -r '.[].path'`.
- LM Studio: `<hf_repo>` (must be `lms get`'d first, with `--mlx` or `--gguf`)

### Add a new benchmark task (e.g. long-context)

Don't touch `fixture/`. Instead:
1. Create `fixture-<name>/` with the same structure (`phone_utils.py`-style stub, `test_*.py`, `pytest.ini`).
2. Add a `fixture_dir` field to combos in `config.yaml` and have `run.sh` read it (currently hardcoded to `fixture/`).
3. Verify self-consistency: stub must fail all tests, a known-correct implementation must pass all.

### Debug a misbehaving backend

The pattern for tracing:

```bash
# Run one combo, one trial
yq -i '.trials = 1' config.yaml
./run.sh <combo-name>

# Then inspect, in order of usefulness:
cat results/run-*/<combo>/server_log.txt          # did the model load?
tail -50 results/run-*/<combo>/trial-1.stderr.txt # did claude -p crash?
jq -s . results/run-*/<combo>/trial-1.stream.ndjson | less  # what did the model emit?
cat results/run-*/<combo>/trial-1.pytest.txt      # final state of fixture
```

Empty `.stream.ndjson` usually means `--verbose` got dropped or the OpenAI-compat endpoint isn't actually OpenAI-compatible (some servers diverge on tool-calling fields). 0% green rate with non-empty stream usually means the model is emitting text-format "tool calls" that Claude Code can't parse — a `chat_template` problem, not a model-quality problem.

## Broken-quant gotcha (MoE on llama.cpp)

The PLAIN `Q4_K_M` quant of `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (and likely other MoE models) produces **degenerate output** (a single token repeated, e.g. `@@@@@@@@@@`) under `llama-server` on Apple Silicon. Confirmed 2026-05-12 on M4 Pro / ggml 0.11.1. The bug is in the quant file, not the inference flags — minimal flags (`--jinja --ctx-size 16384`) and exotic flags (`--cache-type-k q8_0 --flash-attn on`) both yield garbage.

Use Unsloth's **`UD-Q4_K_XL.gguf`** quant instead — it's purpose-built for MoE expert routing layers, slightly smaller (16.45 GB vs 17.28 GB), and produces sane output. The pattern `<repo>::UD-Q*_K_XL.gguf` applies to other Unsloth MoE GGUFs too.

Diagnostic: hit `/v1/chat/completions` directly with a 1-line prompt and `temperature=0`. If you get a single character repeated, switch quants. **Do not waste benchmark trials on a broken quant** — `run.sh` has no way to detect this; pytest will just fail with no usable model output, looking like a model-quality problem when it's a quant problem.

## Tool requirements

Hard requirements on PATH (checked by `run.sh` pre-flight):
- `claude` (Claude Code CLI, `npm i -g @anthropic-ai/claude-code`)
- `yq` (Go version — `brew install yq`)
- `jq`
- `uv` (`brew install uv`) — manages Python + pytest for trial scoring and `score.py`. The harness invokes them via `uv run --no-project --with pytest`, so there's no venv to maintain and no system pytest needed.
- GNU `timeout` — `brew install coreutils` on macOS (provides `gtimeout`). `run.sh` auto-detects either binary in pre-flight; missing this caused silent 0-byte stream files in early runs.

Per-backend, only what you're testing:
- `ollama`
- `llama-server` (from `brew install llama.cpp`)
- `lms` (LM Studio CLI, `~/.lmstudio/bin/lms bootstrap` after first GUI launch)

## Conventions

- **Bash style:** `set -euo pipefail` at the top of every script. Functions where reasonable. Source `_common.sh` for shared helpers. Use `log`/`warn`/`fail` for output, not raw `echo`.
- **No silent failures.** A backend that "starts" but never serves a real response must `fail` in `backend_start`, not pretend everything's fine and let `claude -p` time out 10 minutes later.
- **Idempotency.** `backend_start` should handle the case where its server is already running (reuse it). `backend_stop` should handle the case where nothing's running.
- **Results are append-only.** Each `./run.sh` invocation creates a new timestamped dir under `results/`. Never overwrite prior runs.
- **No formatting/lint config files needed.** This is a small harness; readability wins over tooling.

## What this benchmark deliberately does *not* measure

So you don't add code chasing the wrong signal:

- **Code quality / style.** Pytest is the only judge. If all 6 tests pass, the solution is "correct" regardless of how ugly the implementation is.
- **Token usage / cost.** Local inference is free; we're measuring wall-clock and reliability.
- **Multi-turn conversation quality.** Each trial is a single `claude -p` invocation. No session resume.
- **Real-world prompt engineering.** The prompt in `config.yaml` is deliberately terse to expose model differences. Don't make it more helpful — that defeats the point.

## When unsure

The README covers user-facing how-to. This file covers contributor-facing how-to. If a question isn't answered in either, ask before changing core files (`run.sh`, `score.py`, `fixture/`, the backend contract).