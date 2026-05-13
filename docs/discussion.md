## Headline takeaway

For the offline-coding-on-a-48 GB-Mac use case, **llama.cpp + Qwen3-Coder-30B-A3B (UD-Q4_K_XL)** wins on every meaningful axis: lowest median wall among 100% green combos, tightest run-to-run spread, comfortable disk and memory footprint (16.45 GB on disk, ~22 GB peak with KV cache), no daemon overhead.

This recommendation survives a 5-combo head-to-head test that included two specifically chosen comparators which *could* have dethroned it: a much bigger MoE (Qwen3-Coder-Next 80B/3B) and a smaller dense coder (Qwen2.5-Coder-14B). Neither did, for different and informative reasons.

## The decisive finding: agentic training trumps size or quality

Qwen2.5-Coder-14B Q6_K — a recent, high-quality, dense coding model — **failed 3/3 trials** despite being half the size of the winner. Every trial ended in `num_turns: 1, stop_reason: end_turn`. The model produced a multi-paragraph prose explanation of what it would do, with tool-call JSON embedded as plain text inside the response, then stopped. It never emitted a structured `tool_use` block.

Qwen2.5-Coder was trained for completion / chat. Qwen3-Coder was specifically post-trained with **long-horizon Agent RL** for the exact loop we measure. Same model family lineage, completely different operational behavior in an agentic harness. **For Claude Code, pick from the agentic-trained lineage only.** Don't be tempted by a smaller or newer-looking general coder unless you've verified it actually tool-calls.

## Qwen3-Coder-Next 80B/3B isn't a free upgrade on this hardware

Same active-param count (3B) as the 30B-A3B, **twice the disk and memory footprint**, marginally similar speed on this task. The 80B's bigger knowledge pool doesn't translate to faster wall-clock; we paid ~33 GB on disk for a slightly slower median (66 s vs 60 s) and 5× worse variance (68 s spread vs 13 s). The only thing Next gives you on a 48 GB Mac is **256K native context** — and if you're not regularly hitting the 30B's 32K limit, that's dead weight.

The general rule: per-token compute is set by *active* params, not total params. An 80B MoE with 3B active and a 30B MoE with 3B active have similar per-token cost. The 80B has more specialized expert knowledge baked in, but for a small, narrow task like this benchmark, that's invisible.

## Inference engine matters: llama.cpp > Ollama for the same model

Apples-to-apples (Qwen3-Coder-30B-A3B), llama.cpp is **24% faster on median (60 s vs 80 s) and 3× tighter on variance (13 s vs 41 s)** than Ollama. Ollama's daemon scheduling and keep-alive bookkeeping adds real per-request overhead; for focused coding sessions where you've already committed the model into GPU memory, llama-server's directness pays off. The trade-off: you manage the server lifecycle yourself (`llama-server &` to start, `kill %1` to stop), which is barely a trade-off for a laptop user.

## Gotchas worth recording

- **Plain Q4_K_M is broken for some MoE GGUFs on Apple Silicon.** Unsloth's `Q4_K_M.gguf` for Qwen3-Coder-30B-A3B produces degenerate `@@@@@` output regardless of inference flags. Their `UD-Q4_K_XL.gguf` ("Unsloth Dynamic" purpose-built for MoE expert layers) produces sane output. Always sanity-probe a newly downloaded quant with `temperature=0` before running the bench.
- **Ollama's `/v1` endpoint requires exact-tag matching.** `gpt-oss:20b` works; `gpt-oss` does not. The OpenAI shim doesn't do the fuzzy matching that the native `/api/*` endpoint does. The error surfaces as a Claude-Code-side message but the 404 actually comes from Ollama.
- **Claude Code talks Anthropic `/v1/messages`, not OpenAI `/v1/chat/completions`.** Ollama and llama-server both natively implement `/v1/messages`. If you point Claude Code at a backend that only speaks OpenAI shape, you need a translator proxy.
- **Cwd isolation matters.** `claude -p` resolves relative paths against its cwd. If you run it from the project root, it'll happily read and write `fixture/...` (the failing baseline) instead of the per-trial tmpdir. The harness now wraps the call in `(cd "$WORK_DIR" && claude …)` and pre-flights for fixture pollution.

## What to test next

- **DeepSeek-Coder-V2 / V3** — a different model lineage. The V3 series claims agentic training; worth a head-to-head against Qwen3-Coder-30B.
- **Qwen3-Coder-30B at higher quants** (UD-Q5_K_M, UD-Q6_K) — does precision improve solve efficiency, or are we already at the diminishing-returns plateau?
- **A long-context benchmark fixture** — a separate task that requires reading 30+ files (e.g. small refactor across a real codebase). The case where Qwen3-Coder-Next's 256K context could finally earn its disk space.
- **Power / thermal measurement** — wall-clock isn't the full battery picture. A combo that's slower per token but engages the GPU at lower TDP could net more useful work per battery percent. Out of scope for `cc-local-bench` as currently scoped, but interesting.
