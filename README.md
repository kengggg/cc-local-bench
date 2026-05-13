# cc-local-bench

Benchmark Claude Code against local models across four inference runtimes (Ollama, llama.cpp, LM Studio MLX, LM Studio GGUF) on an agentic coding task.

The benchmark is a single fixed task: implement `format_phone_number` for Thai phone numbers until 6 pytest tests pass. This forces a full agentic loop (Read → Edit → Bash → Read test output → Edit → ...). DNF / wrong answer / loops-forever are all caught.

## Prerequisites

```bash
# Core tooling
brew install yq jq uv coreutils   # coreutils provides `gtimeout` (used to bound each trial)

# Claude Code (must be on PATH)
npm install -g @anthropic-ai/claude-code

# Backends (install whatever you want to test)
brew install llama.cpp ollama
# LM Studio: download from https://lmstudio.ai, then run once to install `lms` CLI:
#   ~/.lmstudio/bin/lms bootstrap
```

`uv` manages Python and pytest for the harness on demand — no `pip install`, no venv to activate. The first trial pulls pytest into uv's cache; subsequent trials are instant.

Verify everything's on PATH:
```bash
claude --version && uv --version && llama-server --version && ollama --version && lms version
```

## One-time model download

llama.cpp pulls on-demand from HuggingFace, so nothing to do for that backend.
Ollama and LM Studio need pre-fetched models:

```bash
# Ollama
ollama pull qwen3-coder:30b

# LM Studio — both flavours of the same logical model
lms get unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF --gguf --yes
lms get mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --mlx --yes
```

> ⚠️ Model identifiers change. Check `config.yaml` and adjust if a pull 404s.

## Run

```bash
chmod +x run.sh backends/*.sh

# Round 1: same model, 4 runtimes
./run.sh round1

# Look at results/run-*/report.md, pick a winner, edit config.yaml round2[].backend, then:
./run.sh round2
```

Single-combo runs (for debugging) work too:
```bash
./run.sh llamacpp-qwen3coder30b
```

## What it measures

For each (backend, model) combo, 3 trials each:

| Metric | Source | What it tells you |
|---|---|---|
| **Cold-start** | wall clock from `backend_start` to "ready" | One-off cost of swapping models |
| **Wall-clock to green** | wall clock around `claude -p` | End-to-end agentic speed |
| **All-green rate** | pytest exit code | Did the model actually solve it? |
| **Turn count** | stream-json parsing | How many round-trips? |
| **Tool calls** | stream-json parsing | Read/Edit/Bash distribution; higher = more thrashing |
| **Timed out** | `claude_exit_code == 124` | Stuck loops |

Median wall-clock across the 3 trials is the headline number, since local inference jitters a lot.

## Output layout

```
results/run-YYYYMMDD-HHMMSS-round1/
├── config.snapshot.yaml         # exact config used
├── report.md                    # human-readable comparison
├── summary.json                 # machine-readable
└── <combo>/
    ├── backend_meta.json        # cold-start, endpoint
    ├── server_log.txt           # llama-server log (where applicable)
    ├── trial-1.json             # per-trial summary
    ├── trial-1.stream.ndjson    # full Claude Code stream
    ├── trial-1.pytest.txt       # final test output
    ├── trial-1.stderr.txt
    └── ...
```

## Tweaking

- **Faster iteration while developing the harness:** drop `trials: 1` in `config.yaml`.
- **Tighter timeout:** drop `timeout_seconds: 300` to bail earlier on slow combos.
- **Different task:** edit `fixture/test_phone_utils.py` and `fixture/phone_utils.py`. The harness doesn't care what the task is, only that `pytest` reports pass/fail.

## Known caveats

- **Tool-calling reliability is the killer signal.** Many smaller models silently emit text-formatted "tool calls" instead of structured ones, breaking Claude Code's loop. The green rate exposes this directly.
- **llama.cpp `--jinja` flag is mandatory** for tool calling. Ollama and LM Studio handle this internally.
- **LM Studio MLX vs GGUF**: both go through the same OpenAI-compat server; the runtime difference is hidden behind `lms load`. We confirm which engine loaded by looking at the LM Studio app's UI (or `lms ps --json`).
- **Claude Code on subscription auth**: setting `ANTHROPIC_BASE_URL` overrides the subscription endpoint cleanly for that invocation only — your normal `claude` use isn't affected. Each bench invocation passes `ANTHROPIC_API_KEY=local-bench` (the value doesn't matter for local servers but the var must be present).
- **First run is slow.** Models download (10–20 GB each), Metal shaders compile on first inference. Re-runs use the macOS persistent shader cache.
