# cc-local-bench results — `run-20260512-195720-ollama-gptoss20b`

## Summary table

| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |
|---|---|---:|---:|---:|---:|---:|
| `ollama-gptoss20b` | ollama | 5.1 | 68.7 | 100% | 25 | 8 |

## Per-trial detail

### `ollama-gptoss20b` — gpt-oss:20b

| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |
|---:|---:|---:|:--:|---|:--:|---:|---:|
| 1 | 43.0 | 0 |  | 6/0 | ✓ | 25 | 8 |
| 2 | 68.7 | 0 |  | 6/0 | ✓ | 13 | 4 |
| 3 | 138.0 | 0 |  | 6/0 | ✓ | 49 | 16 |

**Tool calls (sum across trials):** `Bash`=12, `Read`=8, `Edit`=8


## How to read this

- **Green rate**: fraction of trials where all 6 tests passed. Below 100% means the model couldn't reliably drive the agentic loop.
- **Median wall**: median end-to-end time from prompt to terminal. Compare across backends for raw speed; across models for capability/speed tradeoff.
- **Cold-start**: time for the server to load the model into memory. Matters more for ad-hoc use than benchmarks.
- **Tool calls**: a higher count for the same task usually means more loops/retries — i.e. the model is fighting its way to a solution.
- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` indicates the hard timeout was hit.
