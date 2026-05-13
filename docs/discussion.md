## Headline takeaway

For the **offline-coding-on-a-48 GB-Mac** use case, **llama.cpp + Qwen3-Coder-30B-A3B (UD-Q4_K_XL)** wins on **2 of 3 Pareto axes** (speed, efficiency) and is the most defensible default pick. It uses **~335 mWh per solve** in steady-state inference — meaning ~300 task-solves per full charge of a 100 Wh laptop battery (display + idle floor not included).

This recommendation now survives a **7-combo head-to-head** that includes:
- Two engines (Ollama vs llama.cpp)
- Three precisions of the same model (Q4_K_XL, Q5_K_XL, Q6_K_XL)
- Three different model families (Qwen3-Coder, Qwen2.5-Coder, DeepSeek-Coder-V2-Lite, gpt-oss)
- One radically different architecture (Qwen3-Coder-Next 80B/3B with Gated DeltaNet)
- Two confirmed "doesn't tool-call" failures (Qwen2.5-Coder-14B, DeepSeek-V2-Lite)

## Finding #1 (the most important): agentic training trumps size, quality, AND family

We now have **two independent confirmations** of this hypothesis:

- **Qwen2.5-Coder-14B Q6_K** (12 GB, dense, Alibaba lineage) — failed 3/3, `num_turns=1, stop_reason=end_turn`.
- **DeepSeek-Coder-V2-Lite Q6_K** (13 GB, MoE 16B/2.4B-active, DeepSeek lineage) — failed 3/3, same pattern.

Both models are competent at code *completion* and chat. Neither was post-trained with **long-horizon Agent RL** for tool use. So neither emits structured `tool_use` blocks; instead they output multi-paragraph prose explanations with tool-call JSON embedded as plain text.

The two failing models share **nothing** architecturally: one is dense, one is MoE; one is from Alibaba, one from DeepSeek; both are post-2025 instruction-tuned coding models. They fail in the same way for the same reason. **The signal is real and lineage-agnostic.**

**Practical takeaway:** when picking a local model for Claude Code, the only filter that matters is *"was this model post-trained for agentic tool use?"* If you can't find an explicit "Agent RL" or "long-horizon agentic" note in the model card, assume it can't drive Claude Code's loop. Verify with a 1-line curl probe to `/v1/messages` with a tool definition before downloading 13 GB.

## Finding #2: precision doesn't help, and may HURT

Three quants of the same model (Qwen3-Coder-30B-A3B), same engine (llama.cpp), same prompt, on the same hardware:

|  | Median wall | Spread | Median energy | Green | Disk |
|---|---:|---:|---:|---:|---:|
| **UD-Q4_K_XL** | **53.5 s** | 117.0 s* | **1208 J** | 3/3 | 16.45 GB |
| UD-Q5_K_XL | 63.3 s | 8.4 s | 1515 J | 3/3 | 20.25 GB |
| UD-Q6_K_XL | 68.5 s | 6.5 s | 1532 J | **2/3** ⚠️ | 24.53 GB |

\*Q4's spread is inflated by a single 164.7 s outlier trial (the other two were 47.7 s and 53.5 s). The model has a long-tail thrashing distribution on this task that 3 trials can't fully characterize.

Three things to note:
1. **Speed is flat to slightly worse with higher precision.** Per-token compute is bound by the 3 B active params, not the bytes-per-param. Higher quant just means more bytes per param shipped through cache hierarchies on each token.
2. **Energy is ~25–27% higher** at Q5/Q6 vs Q4. Slightly slower wall × slightly hotter GPU = noticeably more joules.
3. **Q6_K_XL went 2/3 green for an unexpected reason.** See finding #3.

**Practical takeaway:** for a Qwen3-Coder-30B-A3B deployment, Q4_K_XL is the right pick. Don't pay disk and battery for precision that doesn't translate into agentic competence.

## Finding #3: the "destructive cleanup" failure mode (Q6 trial 2)

The harness's auto-finding detector flagged this and we're documenting it as a real model behavior. In Q6 trial 2:
1. The agent wrote a correct-looking implementation of `format_phone_number`.
2. It verified the implementation via a **hand-rolled Python script** (printed test cases through the function, checked the outputs by eye).
3. It then ran `rm test_phone_utils.py phone_utils.py` to "clean up."
4. The next pytest run collected zero tests; harness scored 0/6.

In a real Claude Code session, this would be an angry developer with `git status` showing `D  test_phone_utils.py` and a model emitting "I have successfully implemented the function!"

It's a single trial and we can't tell if Q6 is genuinely more prone or if we got unlucky. But it's the kind of failure that would be invisible without `pytest` as ground truth. **Watch for it.**

## Finding #4: Qwen3-Coder-Next 80B/3B isn't a free upgrade on 48 GB

Same active-param count (3 B) as the 30B-A3B, **twice the disk and memory footprint** at Q3 (33 GB vs 16.45 GB), marginally similar speed (66.0 s vs 53.5 s median), and **5× worse variance** (68 s spread vs 12.9 s in the original pre-power run). The 80B's bigger knowledge pool doesn't translate to faster wall-clock; we paid ~33 GB on disk for a slightly slower median. The only differentiator on a 48 GB Mac is **256 K native context**, which is dead weight for typical Claude Code sessions under 32 K.

The general rule: per-token compute is set by *active* params, not total. An 80B MoE with 3 B active and a 30B MoE with 3 B active have similar per-token cost. Bigger total just specializes the experts.

## Finding #5: engine matters — llama.cpp > Ollama for the same model

Apples-to-apples (Qwen3-Coder-30B-A3B):
- Ollama: 79.6 s median, 40.7 s spread
- llama.cpp: 53.5 s median (3/3), 117 s spread (outlier-inflated; pre-power run was 12.9 s)

llama.cpp wins. Ollama's daemon scheduling and keep-alive bookkeeping adds real per-request overhead; for focused coding sessions, llama-server's directness pays off.

## Finding #6: energy reality check

With `--with-power` instrumentation we can finally quantify the "how much battery does an offline coding session cost?" question.

For the recommended combo (Q4_K_XL):
- **Median energy per solve**: 1208 J = **0.335 Wh** (GPU + CPU + ANE on SoC)
- **Idle floor**: ~50–110 mW package power (when model loaded but no inference)
- **Delta over idle**: 1172 J = 0.326 Wh (the "actually inference" cost)
- **GPU avg during inference**: 21.8 W
- **CPU avg during inference**: 0.96 W (the model is GPU-bound, as expected)

Per-task math on a M4 Pro 16-inch (100 Wh battery):
- Pure inference-only ceiling: 100 / 0.335 ≈ **300 solves per full charge**
- Real-world: cut that in half once you add display, browser, IDE, idle baselines, and the fact that you don't only do one solve per minute. **Realistic estimate: 100–150 useful Claude Code interactions per charge.**

These are SoC-only numbers. Wall-plug consumption adds ~30–40% (DC-DC conversion, display, charger losses) but doesn't affect the *comparison between models*. For "is model X more battery-efficient than model Y," package mW is the right axis.

## Finding #7: 3 trials isn't enough to characterize the long tail

Q4's pre-power run gave a 12.9 s spread. The with-power re-run gave a 117 s spread (because of one 164.7 s outlier trial). Same model, same flags, same hardware — different sampling paths.

The agentic loop has a heavy-tailed wall-time distribution because there's a non-zero probability the model gets stuck in an inefficient reasoning path. 3 trials gives us median + range but doesn't tell us how often the long tail hits. For decisions, we want **N=10 or higher**. For now: read the median, ignore the spread when it's outlier-dominated, watch for the *frequency* of outliers across runs.

## Operational gotchas accumulated over the sessions

- **Plain Q4_K_M is broken for some MoE GGUFs on Apple Silicon.** Unsloth's plain `Q4_K_M` for Qwen3-Coder-30B-A3B produces degenerate `@@@@@` output regardless of flags. Use Unsloth Dynamic (UD-Q4_K_XL).
- **Ollama's `/v1` endpoint requires exact-tag matching.** `gpt-oss:20b` works; `gpt-oss` doesn't.
- **Claude Code uses Anthropic `/v1/messages`, not OpenAI `/v1/chat/completions`.** Both Ollama and llama-server happen to implement `/v1/messages` natively. A backend that only speaks OpenAI shape needs a translator.
- **The `BACKEND_ENDPOINT` URL must NOT end with `/v1`.** Claude Code appends `/v1/messages` itself. Trailing `/v1` causes silent failure.
- **`claude -p` must run with `cwd=$WORK_DIR`.** Otherwise it'll happily edit (or `rm`) files in the project root, corrupting the benchmark's failing baseline.

## What to test next

- **Long-context fixture** — a real 30+ file refactor to give Qwen3-Coder-Next's 256 K context a genuine workload (the user has one in mind).
- **More trials per combo** — N=10 to characterize the long tail, not just the median.
- **Power on Ollama side** — re-run the Ollama combos with `--with-power` to confirm the 24% wall-time gap also shows up in energy. Hypothesis: yes, Ollama uses more joules per solve because it runs longer at similar power.
- **DeepSeek-V4-Flash** — when a deployable quant lands (current `V4-Flash` is 284 B / 13 B active and won't fit), and it claims Agent RL post-training, worth a head-to-head.
