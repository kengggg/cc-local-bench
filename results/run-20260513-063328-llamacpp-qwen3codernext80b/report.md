# cc-local-bench results — `run-20260513-063328-llamacpp-qwen3codernext80b`

## Summary table

| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |
|---|---|---:|---:|---:|---:|---:|
| `llamacpp-qwen3codernext80b` | llamacpp | 6.1 | 66.0 | 100% | 13 | 5 |

## Per-trial detail

### `llamacpp-qwen3codernext80b` — unsloth/Qwen3-Coder-Next-GGUF::Qwen3-Coder-Next-UD-Q3_K_S.gguf

| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |
|---:|---:|---:|:--:|---|:--:|---:|---:|
| 1 | 66.0 | 0 |  | 6/0 | ✓ | 13 | 5 |
| 2 | 129.2 | 0 |  | 6/0 | ✓ | 21 | 8 |
| 3 | 61.2 | 0 |  | 6/0 | ✓ | 13 | 5 |

**Tool calls (sum across trials):** `Read`=7, `Bash`=7, `Edit`=4


## How to read this

- **Green rate**: fraction of trials where all 6 tests passed. Below 100% means the model couldn't reliably drive the agentic loop.
- **Median wall**: median end-to-end time from prompt to terminal. Compare across backends for raw speed; across models for capability/speed tradeoff.
- **Cold-start**: time for the server to load the model into memory. Matters more for ad-hoc use than benchmarks.
- **Tool calls**: a higher count for the same task usually means more loops/retries — i.e. the model is fighting its way to a solution.
- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` indicates the hard timeout was hit.
