#!/usr/bin/env python3
"""Aggregate cc-local-bench trial results into a markdown report.

Usage: score.py <run_dir>
Reads:  <run_dir>/<combo>/trial-*.json  +  trial-*.stream.ndjson  +  backend_meta.json
Writes: <run_dir>/report.md  +  <run_dir>/summary.json
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def parse_stream(stream_path: Path) -> dict:
    """Pull tool-call counts and turn count out of a Claude Code stream-json log.

    The exact schema can vary slightly across Claude Code versions; we tolerate
    that by counting message and tool_use blocks where we find them.
    """
    turns = 0
    tool_calls: Counter = Counter()
    malformed = 0

    if not stream_path.exists():
        return {"turns": 0, "tool_calls": {}, "tool_calls_total": 0, "malformed_lines": 0}

    with stream_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue

            # Each top-level message is one "turn" in the stream
            if obj.get("type") in {"assistant", "user", "tool_use", "message"}:
                turns += 1

            # Tool-use blocks may appear nested under .message.content or top-level
            def walk(node):
                if isinstance(node, dict):
                    if node.get("type") == "tool_use":
                        tool_calls[node.get("name", "<unknown>")] += 1
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)

            walk(obj)

    return {
        "turns": turns,
        "tool_calls": dict(tool_calls),
        "tool_calls_total": sum(tool_calls.values()),
        "malformed_lines": malformed,
    }


def load_combo(combo_dir: Path) -> dict:
    trials = []
    for tp in sorted(combo_dir.glob("trial-*.json")):
        # Skip sidecar files (trial-N.power.json etc) — only the canonical
        # trial-N.json has the .trial field.
        if ".power." in tp.name:
            continue
        with tp.open() as f:
            trial = json.load(f)
        stream_path = combo_dir / f"trial-{trial['trial']}.stream.ndjson"
        trial.update(parse_stream(stream_path))
        trials.append(trial)

    meta_path = combo_dir / "backend_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    if not trials:
        return {"name": combo_dir.name, "trials": [], "meta": meta}

    walls = [t["wall_clock_seconds"] for t in trials]
    greens = [t["all_green"] for t in trials]
    turns = [t.get("turns", 0) for t in trials]
    tool_totals = [t.get("tool_calls_total", 0) for t in trials]

    return {
        "name": combo_dir.name,
        "backend": trials[0]["backend"],
        "model_id": trials[0]["model_id"],
        "trials": trials,
        "meta": meta,
        "median_wall": statistics.median(walls),
        "min_wall": min(walls),
        "max_wall": max(walls),
        "green_rate": sum(greens) / len(greens),
        "median_turns": statistics.median(turns) if turns else 0,
        "median_tool_calls": statistics.median(tool_totals) if tool_totals else 0,
        "cold_start": meta.get("cold_start_seconds", float("nan")),
    }


def fmt(x, prec=1):
    try:
        return f"{x:.{prec}f}"
    except Exception:
        return str(x)


def write_report(run_dir: Path, combos: list[dict]) -> None:
    report = run_dir / "report.md"
    with report.open("w") as f:
        f.write(f"# cc-local-bench results — `{run_dir.name}`\n\n")
        f.write("## Summary table\n\n")
        f.write("| Combo | Backend | Cold-start (s) | Median wall (s) | Green rate | Median turns | Median tool calls |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|\n")

        # Sort by green rate desc, then median wall asc
        ordered = sorted(combos, key=lambda c: (-c.get("green_rate", 0), c.get("median_wall", 1e9)))
        for c in ordered:
            f.write(
                f"| `{c['name']}` | {c.get('backend','?')} "
                f"| {fmt(c.get('cold_start', float('nan')))} "
                f"| {fmt(c.get('median_wall', float('nan')))} "
                f"| {fmt(c.get('green_rate', 0) * 100, 0)}% "
                f"| {fmt(c.get('median_turns', 0), 0)} "
                f"| {fmt(c.get('median_tool_calls', 0), 0)} |\n"
            )

        f.write("\n## Per-trial detail\n\n")
        for c in ordered:
            f.write(f"### `{c['name']}` — {c.get('model_id','?')}\n\n")
            if not c["trials"]:
                f.write("_No trials completed._\n\n")
                continue
            f.write("| Trial | Wall (s) | cc_exit | timed out | pytest p/f | All green | Turns | Tool calls |\n")
            f.write("|---:|---:|---:|:--:|---|:--:|---:|---:|\n")
            for t in c["trials"]:
                f.write(
                    f"| {t['trial']} | {fmt(t['wall_clock_seconds'])} | {t['claude_exit_code']} "
                    f"| {'✓' if t.get('claude_timed_out') else ''} "
                    f"| {t['tests_passed']}/{t['tests_failed']} "
                    f"| {'✓' if t['all_green'] else '✗'} "
                    f"| {t.get('turns', 0)} | {t.get('tool_calls_total', 0)} |\n"
                )

            # Tool call breakdown across trials
            tool_total: Counter = Counter()
            for t in c["trials"]:
                for k, v in t.get("tool_calls", {}).items():
                    tool_total[k] += v
            if tool_total:
                f.write("\n**Tool calls (sum across trials):** ")
                f.write(", ".join(f"`{k}`={v}" for k, v in tool_total.most_common()))
                f.write("\n\n")

        f.write("\n## How to read this\n\n")
        f.write(
            "- **Green rate**: fraction of trials where all 6 tests passed. "
            "Below 100% means the model couldn't reliably drive the agentic loop.\n"
            "- **Median wall**: median end-to-end time from prompt to terminal. "
            "Compare across backends for raw speed; across models for capability/speed tradeoff.\n"
            "- **Cold-start**: time for the server to load the model into memory. "
            "Matters more for ad-hoc use than benchmarks.\n"
            "- **Tool calls**: a higher count for the same task usually means more "
            "loops/retries — i.e. the model is fighting its way to a solution.\n"
            "- **DNF** (Did Not Finish): `claude_exit_code=124` and `all_green=false` "
            "indicates the hard timeout was hit.\n"
        )

    # Also dump JSON summary for further analysis
    summary_path = run_dir / "summary.json"
    with summary_path.open("w") as f:
        json.dump([{k: v for k, v in c.items() if k != "trials"} for c in ordered], f, indent=2)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: score.py <run_dir>", file=sys.stderr)
        return 1
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"Not a directory: {run_dir}", file=sys.stderr)
        return 1

    combos = []
    for child in sorted(run_dir.iterdir()):
        if child.is_dir() and any(child.glob("trial-*.json")):
            combos.append(load_combo(child))

    if not combos:
        print(f"No combos with trial results found in {run_dir}", file=sys.stderr)
        return 1

    write_report(run_dir, combos)
    print(f"Report: {run_dir/'report.md'}")
    print(f"JSON:   {run_dir/'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
