# cc-local-bench results — `run-20260512-191414-ollama-qwen3coder30b`

## Summary table

| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |
|---|---|---:|---:|---:|---:|---:|
| `ollama-qwen3coder30b` | ollama | 5.4 | 79.6 | 100% | 22 | 7 |

## Per-trial detail

### `ollama-qwen3coder30b` — qwen3-coder:30b

| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |
|---:|---:|---:|:--:|---|:--:|---:|---:|
| 1 | 78.0 | 0 |  | 6/0 | ✓ | 22 | 7 |
| 2 | 118.7 | 0 |  | 6/0 | ✓ | 28 | 9 |
| 3 | 79.6 | 0 |  | 6/0 | ✓ | 19 | 6 |

**Tool calls (sum across trials):** `Bash`=13, `Read`=6, `Edit`=3


## How to read this

- **Green rate**: fraction of trials where all 6 tests passed. Below 100% means the model couldn't reliably drive the agentic loop.
- **Median wall**: median end-to-end time from prompt to terminal. Compare across backends for raw speed; across models for capability/speed tradeoff.
- **Cold-start**: time for the server to load the model into memory. Matters more for ad-hoc use than benchmarks.
- **Tool calls**: a higher count for the same task usually means more loops/retries — i.e. the model is fighting its way to a solution.
- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` indicates the hard timeout was hit.
