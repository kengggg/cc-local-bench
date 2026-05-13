# cc-local-bench results — `run-20260513-061930-llamacpp-qwen25coder14b`

## Summary table

| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |
|---|---|---:|---:|---:|---:|---:|
| `llamacpp-qwen25coder14b` | llamacpp | 4.1 | 31.7 | 0% | 1 | 0 |

## Per-trial detail

### `llamacpp-qwen25coder14b` — bartowski/Qwen2.5-Coder-14B-Instruct-GGUF::Qwen2.5-Coder-14B-Instruct-Q6_K.gguf

| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |
|---:|---:|---:|:--:|---|:--:|---:|---:|
| 1 | 19.9 | 0 |  | 0/6 | ✗ | 1 | 0 |
| 2 | 48.0 | 0 |  | 0/6 | ✗ | 1 | 0 |
| 3 | 31.7 | 0 |  | 0/6 | ✗ | 1 | 0 |

## How to read this

- **Green rate**: fraction of trials where all 6 tests passed. Below 100% means the model couldn't reliably drive the agentic loop.
- **Median wall**: median end-to-end time from prompt to terminal. Compare across backends for raw speed; across models for capability/speed tradeoff.
- **Cold-start**: time for the server to load the model into memory. Matters more for ad-hoc use than benchmarks.
- **Tool calls**: a higher count for the same task usually means more loops/retries — i.e. the model is fighting its way to a solution.
- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` indicates the hard timeout was hit.
