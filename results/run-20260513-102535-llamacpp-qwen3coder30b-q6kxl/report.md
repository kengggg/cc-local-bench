# cc-local-bench results — `run-20260513-102535-llamacpp-qwen3coder30b-q6kxl`

## Summary table

| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |
|---|---|---:|---:|---:|---:|---:|
| `llamacpp-qwen3coder30b-q6kxl` | llamacpp | 16.2 | 68.5 | 67% | 22 | 7 |

## Per-trial detail

### `llamacpp-qwen3coder30b-q6kxl` — unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF::Qwen3-Coder-30B-A3B-Instruct-UD-Q6_K_XL.gguf

| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |
|---:|---:|---:|:--:|---|:--:|---:|---:|
| 1 | 68.5 | 0 |  | 6/0 | ✓ | 18 | 6 |
| 2 | 62.5 | 0 |  | 0/0 | ✗ | 22 | 7 |
| 3 | 69.0 | 0 |  | 6/0 | ✓ | 22 | 7 |

**Tool calls (sum across trials):** `Bash`=10, `Read`=7, `Edit`=3


## How to read this

- **Green rate**: fraction of trials where all 6 tests passed. Below 100% means the model couldn't reliably drive the agentic loop.
- **Median wall**: median end-to-end time from prompt to terminal. Compare across backends for raw speed; across models for capability/speed tradeoff.
- **Cold-start**: time for the server to load the model into memory. Matters more for ad-hoc use than benchmarks.
- **Tool calls**: a higher count for the same task usually means more loops/retries — i.e. the model is fighting its way to a solution.
- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` indicates the hard timeout was hit.
