#!/usr/bin/env python3
"""Generate a static GitHub Pages site from cc-local-bench run results.

Walks results/, picks the latest run per combo name, aggregates per-trial data,
computes auto-findings, and renders docs/index.html.

Usage:
    python3 scripts/gen_site.py
"""
from __future__ import annotations

import html
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"
DISCUSSION_FILE = DOCS / "discussion.md"

TOOL_COLORS = {
    "Bash": "#3b82f6", "Read": "#10b981", "Edit": "#f59e0b",
    "Write": "#a855f7", "Grep": "#ec4899", "Glob": "#06b6d4",
}


# ── Data layer ───────────────────────────────────────────────────────────────

def parse_stream(path: Path) -> dict:
    """Pull turn count and tool_call breakdown from a Claude Code stream-json log."""
    turns = 0
    tool_calls: Counter = Counter()
    if not path.exists():
        return {"turns": 0, "tool_calls": {}, "tool_calls_total": 0}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") in {"assistant", "user", "tool_use", "message"}:
                turns += 1
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
    }


_LEADING_DOT_NUMBER = re.compile(r'(?<=[:\s,])\.(\d)')

def _load_trial_json(path: Path):
    """Read a trial JSON, tolerating bare leading-dot numbers (`.006` → `0.006`)
    that early run.sh versions emitted before the gtimeout fix."""
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = _LEADING_DOT_NUMBER.sub(r'0.\1', text)
        return json.loads(repaired)


def parse_combo_dir(combo_dir: Path):
    """Aggregate per-trial data for one combo directory. Returns None if no trials."""
    trial_files = sorted(combo_dir.glob("trial-*.json"))
    if not trial_files:
        return None
    trials = []
    for tp in trial_files:
        try:
            d = _load_trial_json(tp)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[gen_site] skipping malformed {tp}: {e}", file=sys.stderr)
            continue
        sp = combo_dir / f"trial-{d['trial']}.stream.ndjson"
        d.update(parse_stream(sp))
        trials.append(d)
    if not trials:
        return None
    meta_path = combo_dir / "backend_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    idle_path = combo_dir / "idle_baseline.json"
    idle = json.loads(idle_path.read_text()) if idle_path.exists() else None
    walls = [t["wall_clock_seconds"] for t in trials]

    # Power aggregation (per-trial → median across trials), only if data present.
    energy_js = [t.get("power", {}).get("energy_joules") for t in trials if t.get("power")]
    energy_js = [e for e in energy_js if e is not None]
    delta_energy_js = [
        t.get("power", {}).get("delta_energy_joules")
        for t in trials if t.get("power")
    ]
    delta_energy_js = [e for e in delta_energy_js if e is not None]
    package_avg_mw = [
        t.get("power", {}).get("package_mw", {}).get("avg")
        for t in trials if t.get("power")
    ]
    package_avg_mw = [v for v in package_avg_mw if v is not None]
    gpu_avg_mw = [
        t.get("power", {}).get("gpu_mw", {}).get("avg")
        for t in trials if t.get("power")
    ]
    gpu_avg_mw = [v for v in gpu_avg_mw if v is not None]
    cpu_avg_mw = [
        t.get("power", {}).get("cpu_mw", {}).get("avg")
        for t in trials if t.get("power")
    ]
    cpu_avg_mw = [v for v in cpu_avg_mw if v is not None]

    has_power = bool(energy_js)
    power_summary = None
    if has_power:
        power_summary = {
            "median_energy_joules": statistics.median(energy_js),
            "median_energy_wh": statistics.median(energy_js) / 3600,
            "median_delta_energy_joules": (
                statistics.median(delta_energy_js) if delta_energy_js else None
            ),
            "median_package_mw_avg": (
                int(statistics.median(package_avg_mw)) if package_avg_mw else None
            ),
            "median_gpu_mw_avg": (
                int(statistics.median(gpu_avg_mw)) if gpu_avg_mw else None
            ),
            "median_cpu_mw_avg": (
                int(statistics.median(cpu_avg_mw)) if cpu_avg_mw else None
            ),
            "idle_package_mw_avg": (
                idle.get("package_mw", {}).get("avg") if idle else None
            ),
        }

    return {
        "name": combo_dir.name,
        "backend": trials[0]["backend"],
        "model_id": trials[0]["model_id"],
        "alias": trials[0]["alias"],
        "trials": trials,
        "cold_start": meta.get("cold_start_seconds"),
        "median_wall": statistics.median(walls),
        "min_wall": min(walls),
        "max_wall": max(walls),
        "wall_spread": max(walls) - min(walls),
        "green_count": sum(1 for t in trials if t["all_green"]),
        "trials_count": len(trials),
        "median_turns": int(statistics.median([t["turns"] for t in trials])),
        "median_tool_calls": int(statistics.median([t["tool_calls_total"] for t in trials])),
        "total_tool_calls": sum(
            (Counter(t.get("tool_calls", {})) for t in trials), Counter()
        ),
        "has_power": has_power,
        "power": power_summary,
    }


def walk_runs(results_dir: Path):
    """Yield combo aggregates for every combo in every run, with run timestamp attached."""
    for run_dir in sorted(results_dir.glob("run-*")):
        if not run_dir.is_dir():
            continue
        m = re.match(r"run-(\d{8})-(\d{6})-(.+)", run_dir.name)
        if not m:
            continue
        ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        for combo_dir in sorted(run_dir.iterdir()):
            if not combo_dir.is_dir():
                continue
            c = parse_combo_dir(combo_dir)
            if c is None:
                continue
            c["run_name"] = run_dir.name
            c["run_timestamp"] = ts
            yield c


def latest_per_combo(all_combos, include_smoke=False):
    """Pick latest run for each combo name. Sorted: green rate desc, then median wall asc.

    Smoke combos (`smoke-*`) use non-comparable settings (short timeout, small max_turns)
    and are excluded from the main comparison by default.
    """
    by_name = {}
    for c in all_combos:
        if not include_smoke and c["name"].startswith("smoke-"):
            continue
        if c["name"] not in by_name or c["run_timestamp"] > by_name[c["name"]]["run_timestamp"]:
            by_name[c["name"]] = c
    return sorted(
        by_name.values(),
        key=lambda c: (-c["green_count"] / c["trials_count"], c["median_wall"]),
    )


# ── Auto-findings ────────────────────────────────────────────────────────────

def compute_findings(combos):
    findings = []

    for c in combos:
        if (c["median_tool_calls"] == 0 and c["median_turns"] <= 3
                and c["green_count"] == 0 and c["trials_count"] >= 2):
            findings.append({
                "kind": "red",
                "title": "Model doesn't tool-call",
                "body": (
                    f"<code>{c['name']}</code> never emitted a structured <code>tool_use</code> "
                    f"block — every trial ended at turn 1 with <code>stop_reason=end_turn</code>. "
                    f"The model isn't trained for agentic tool use; it describes tool calls in "
                    f"prose instead of invoking them. Unfit for Claude Code regardless of how "
                    f"good its raw outputs look."
                ),
            })

    greens = [c for c in combos if c["green_count"] == c["trials_count"] and c["trials_count"] > 0]

    if greens:
        # Pareto leaders — separate axes, let the reader pick by their priority.
        # We DON'T collapse to a single "Best overall" because the right answer
        # depends on use case (latency-sensitive vs travel-on-battery vs reliability).
        leaders = {}
        leaders["speed"] = min(greens, key=lambda c: c["median_wall"])
        leaders["reliability"] = min(greens, key=lambda c: c["wall_spread"])
        greens_with_power = [c for c in greens if c["has_power"] and c["power"]]
        if greens_with_power:
            leaders["efficiency"] = min(
                greens_with_power, key=lambda c: c["power"]["median_energy_joules"]
            )

        findings.append({
            "kind": "green",
            "title": "Speed leader",
            "body": (
                f"<code>{leaders['speed']['name']}</code> has the lowest median wall "
                f"({leaders['speed']['median_wall']:.1f} s) among 100% green combos."
            ),
        })
        findings.append({
            "kind": "green",
            "title": "Reliability leader",
            "body": (
                f"<code>{leaders['reliability']['name']}</code> has the tightest "
                f"run-to-run spread ({leaders['reliability']['wall_spread']:.1f} s) — "
                f"most predictable wall time."
            ),
        })
        if "efficiency" in leaders:
            eff = leaders["efficiency"]
            findings.append({
                "kind": "green",
                "title": "Efficiency leader",
                "body": (
                    f"<code>{eff['name']}</code> uses the least energy per solve "
                    f"(median {eff['power']['median_energy_joules']:.0f} J "
                    f"≈ {eff['power']['median_energy_wh']*1000:.0f} mWh) among 100% green combos."
                ),
            })

        # Multi-axis dominance callout
        wins_per_combo = Counter(c["name"] for c in leaders.values())
        for name, wins in wins_per_combo.items():
            if wins >= 2:
                axes = [k for k, v in leaders.items() if v["name"] == name]
                findings.append({
                    "kind": "green",
                    "title": "Multi-axis champion",
                    "body": (
                        f"<code>{name}</code> wins {wins} of {len(leaders)} axes "
                        f"({', '.join(axes)}). The most defensible default pick."
                    ),
                })

    for c in combos:
        if c["green_count"] > 0 and c["median_wall"] > 0:
            ratio = c["wall_spread"] / c["median_wall"]
            if ratio > 0.5 and c["wall_spread"] > 30:
                findings.append({
                    "kind": "yellow",
                    "title": f"High variance: {c['name']}",
                    "body": (
                        f"Spread is {c['wall_spread']:.0f} s — "
                        f"{ratio*100:.0f}% of median ({c['median_wall']:.1f} s). "
                        f"Worst trial took {c['max_wall']:.1f} s. The model thrashes when stuck."
                    ),
                })

    return findings


# ── Rendering ────────────────────────────────────────────────────────────────

def esc(s):
    return html.escape(str(s))


def svg_wall_bars(trials, max_height=80):
    if not trials:
        return ""
    max_wall = max(t["wall_clock_seconds"] for t in trials)
    bar_w, gap = 26, 14
    width = len(trials) * (bar_w + gap) + 10
    total_h = max_height + 30
    parts = [
        f'<svg class="wall-bars" viewBox="0 0 {width} {total_h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    for i, t in enumerate(trials):
        h = t["wall_clock_seconds"] / max_wall * max_height if max_wall > 0 else 0
        x = i * (bar_w + gap) + 5
        y = max_height - h + 14
        fill_cls = "ok-fill" if t["all_green"] else "bad-fill"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" '
            f'class="{fill_cls}" rx="2"/>'
        )
        parts.append(
            f'<text x="{x+bar_w/2}" y="{max_height+26}" text-anchor="middle" '
            f'class="bar-axis">T{t["trial"]}</text>'
        )
        parts.append(
            f'<text x="{x+bar_w/2}" y="{y-3}" text-anchor="middle" '
            f'class="bar-value">{t["wall_clock_seconds"]:.0f}s</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_tool_bar(counter, total_width=320):
    total = sum(counter.values())
    if total == 0:
        return '<div class="tool-empty">No tool calls in this run.</div>'
    parts = [
        f'<svg class="tool-bar" viewBox="0 0 {total_width} 22" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    x = 0
    for tool, count in counter.most_common():
        w = count / total * total_width
        c = TOOL_COLORS.get(tool, "#6b7280")
        parts.append(
            f'<rect x="{x}" y="0" width="{w}" height="22" fill="{c}">'
            f'<title>{esc(tool)}={count}</title></rect>'
        )
        x += w
    parts.append("</svg>")
    legend = " ".join(
        f'<span class="legend-item">'
        f'<span class="dot" style="background:{TOOL_COLORS.get(t, "#6b7280")}"></span>'
        f'{esc(t)}={c}</span>'
        for t, c in counter.most_common()
    )
    return "".join(parts) + f'<div class="legend">{legend}</div>'


def render_combo_card(c):
    cold = f"{c['cold_start']:.1f} s" if c.get("cold_start") is not None else "n/a"
    green_class = (
        "ok" if c["green_count"] == c["trials_count"]
        else ("warn" if c["green_count"] > 0 else "bad")
    )
    badge = f'<span class="badge {green_class}">{c["green_count"]}/{c["trials_count"]} green</span>'

    # Optional energy stat (only when --with-power data exists)
    energy_block = ""
    if c["has_power"] and c["power"]:
        p = c["power"]
        delta_note = ""
        if p.get("median_delta_energy_joules") is not None and p.get("idle_package_mw_avg"):
            delta_note = (
                f' <span class="muted">(Δ {p["median_delta_energy_joules"]:.0f} J '
                f'above {p["idle_package_mw_avg"]/1000:.1f} W idle floor)</span>'
            )
        gpu_cpu_note = ""
        if p.get("median_gpu_mw_avg") and p.get("median_cpu_mw_avg"):
            gpu_cpu_note = (
                f'<div class="muted">GPU {p["median_gpu_mw_avg"]/1000:.1f} W avg · '
                f'CPU {p["median_cpu_mw_avg"]/1000:.1f} W avg</div>'
            )
        energy_block = f"""
    <div class="stat">
      <div class="stat-label">Energy per solve (median)</div>
      <div class="stat-val">{p['median_energy_joules']:.0f} J · {p['median_energy_wh']*1000:.0f} mWh{delta_note}</div>
      {gpu_cpu_note}
    </div>"""

    return f"""
<section class="combo-card" id="combo-{esc(c['name'])}">
  <header>
    <h3>{esc(c['name'])} {badge}</h3>
    <p class="meta">
      <span class="kvp"><strong>Backend</strong> {esc(c['backend'])}</span>
      <span class="kvp"><strong>Model</strong> <code>{esc(c['model_id'])}</code></span>
      <span class="kvp"><strong>Alias</strong> <code>{esc(c['alias'])}</code></span>
      <span class="kvp"><strong>Run</strong> {esc(c['run_timestamp'].strftime('%Y-%m-%d %H:%M'))}</span>
    </p>
  </header>
  <div class="combo-grid">
    <div class="stat">
      <div class="stat-label">Cold-start</div>
      <div class="stat-val">{cold}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Wall (min / median / max)</div>
      <div class="stat-val">{c['min_wall']:.1f} / <strong>{c['median_wall']:.1f}</strong> / {c['max_wall']:.1f} s</div>
    </div>
    <div class="stat">
      <div class="stat-label">Spread</div>
      <div class="stat-val">{c['wall_spread']:.1f} s</div>
    </div>
    <div class="stat">
      <div class="stat-label">Median turns / tool calls</div>
      <div class="stat-val">{c['median_turns']} / {c['median_tool_calls']}</div>
    </div>{energy_block}
  </div>
  <div class="chart-row">
    <div class="chart-col">
      <div class="chart-label">Per-trial wall time</div>
      {svg_wall_bars(c['trials'])}
    </div>
    <div class="chart-col">
      <div class="chart-label">Tool-call distribution (sum across trials)</div>
      {svg_tool_bar(c['total_tool_calls'])}
    </div>
  </div>
</section>
"""


# ── Markdown → HTML (tiny subset) ─────────────────────────────────────────────

def markdown_to_html(md):
    """Minimal converter: ##/### headings, paragraphs, inline `code`, **bold**, *italic*, lists."""
    lines = md.strip().split("\n")
    out = []
    para = []
    in_list = False

    def inline(text):
        text = html.escape(text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        return text

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para = []

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in lines:
        if line.startswith("### "):
            flush_para(); flush_list()
            out.append(f"<h4>{inline(line[4:])}</h4>")
        elif line.startswith("## "):
            flush_para(); flush_list()
            out.append(f"<h3>{inline(line[3:])}</h3>")
        elif line.startswith("# "):
            flush_para(); flush_list()
            out.append(f"<h3>{inline(line[2:])}</h3>")
        elif line.lstrip().startswith("- "):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line.lstrip()[2:])}</li>")
        elif line.strip() == "":
            flush_para(); flush_list()
        else:
            flush_list()
            para.append(line)
    flush_para(); flush_list()
    return "\n".join(out)


# ── Page assembly ────────────────────────────────────────────────────────────

def render_html(combos, findings, discussion_md, run_history, repo_slug):
    any_power = any(c["has_power"] for c in combos)
    summary_rows = []
    for c in combos:
        green_class = (
            "ok" if c["green_count"] == c["trials_count"]
            else ("warn" if c["green_count"] > 0 else "bad")
        )
        cold = f"{c['cold_start']:.1f} s" if c.get("cold_start") is not None else "—"
        if c["has_power"] and c["power"]:
            energy_cell = (
                f'{c["power"]["median_energy_joules"]:.0f} J '
                f'<span class="muted">({c["power"]["median_energy_wh"]*1000:.0f} mWh)</span>'
            )
        else:
            energy_cell = '<span class="muted">—</span>'
        row = (
            f'<tr>'
            f'<td><a href="#combo-{esc(c["name"])}"><code>{esc(c["name"])}</code></a></td>'
            f'<td>{esc(c["backend"])}</td>'
            f'<td class="{green_class}">{c["green_count"]}/{c["trials_count"]}</td>'
            f'<td>{c["median_wall"]:.1f} s</td>'
            f'<td>{c["wall_spread"]:.1f} s</td>'
            f'<td>{c["median_turns"]}</td>'
            f'<td>{c["median_tool_calls"]}</td>'
            f'<td>{cold}</td>'
        )
        if any_power:
            row += f'<td>{energy_cell}</td>'
        row += '</tr>'
        summary_rows.append(row)

    summary_header = (
        '<th>Combo</th><th>Backend</th><th>Green</th>'
        '<th>Median wall</th><th>Spread</th>'
        '<th>Med. turns</th><th>Med. tools</th><th>Cold-start</th>'
    )
    if any_power:
        summary_header += '<th>Med. energy</th>'

    summary_table = (
        '<table class="summary"><thead><tr>'
        + summary_header
        + '</tr></thead><tbody>'
        + "".join(summary_rows) + "</tbody></table>"
    )

    findings_html = "".join(
        f'<div class="finding finding-{f["kind"]}">'
        f'<h4>{esc(f["title"])}</h4><p>{f["body"]}</p></div>'
        for f in findings
    ) or '<p class="muted">No findings to surface yet.</p>'

    cards_html = "".join(render_combo_card(c) for c in combos)

    history_rows = "".join(
        f'<tr><td><code>{esc(r["run_name"])}</code></td>'
        f'<td>{esc(r["timestamp"].strftime("%Y-%m-%d %H:%M"))}</td>'
        f'<td>{esc(r["combos"])}</td></tr>'
        for r in run_history
    )

    discussion_html = markdown_to_html(discussion_md)
    repo_link = (
        f'<a href="https://github.com/{esc(repo_slug)}">source</a>'
        if repo_slug else "source"
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>cc-local-bench — Claude Code × local model benchmark</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="page-head">
  <h1>cc-local-bench</h1>
  <p class="tagline">How well does Claude Code drive local-LLM inference runtimes on an agentic coding task?</p>
  <p class="run-stamp">Generated {esc(now_str)} · {len(combos)} model{'s' if len(combos) != 1 else ''} compared</p>
</header>

<nav class="toc">
  <a href="#goals">Goals</a>
  <a href="#summary">Executive Summary</a>
  <a href="#findings">Auto Findings</a>
  <a href="#details">Per-Model Details</a>
  <a href="#discussion">Discussion</a>
  <a href="#runs">Run history</a>
</nav>

<section id="goals">
<h2>Goals</h2>
<p>
This benchmark answers a narrow question: <strong>given a fixed agentic coding task,
how well does Claude Code drive each candidate local inference runtime + model combination?</strong>
The task itself is intentionally small (implement a <code>format_phone_number</code> function until 6
pytest tests pass). The interesting signal isn't the code — it's how each model navigates the agentic
loop (Read → Edit → Bash → observe pytest → iterate) under a wall-clock budget.
</p>
<p>For each <em>(backend, model)</em> combo we run 3 trials with a 600 s timeout and capture:</p>
<ul>
  <li><strong>Green rate</strong> — fraction of trials where all 6 tests pass. Headline reliability metric.</li>
  <li><strong>Median / min / max wall</strong> — end-to-end time from prompt to terminal state.</li>
  <li><strong>Spread</strong> (max − min) — predictability matters more than peak speed for offline use.</li>
  <li><strong>Turns and tool calls</strong> — how efficiently the model navigates the loop.</li>
  <li><strong>Cold-start</strong> — time from <code>backend_start</code> until the endpoint is ready.</li>
</ul>
<p>
Each <code>claude -p</code> invocation uses hermetic flags (<code>--bare</code>, <code>--strict-mcp-config</code>,
<code>--disable-slash-commands</code>) and a per-trial tmpdir so the operator's plugins, hooks, MCP servers,
and skills don't leak into the model's context. See the
<a href="https://github.com/{esc(repo_slug)}/blob/main/README.md">README</a> and
<a href="https://github.com/{esc(repo_slug)}/blob/main/CLAUDE.md">CLAUDE.md</a> for harness details.
</p>
</section>

<section id="summary">
<h2>Executive Summary</h2>
{summary_table}
</section>

<section id="findings">
<h2>Auto-generated Findings</h2>
<p class="muted">Computed from the data above, not human-written. Regenerated every time the site rebuilds.</p>
{findings_html}
</section>

<section id="details">
<h2>Per-Model Details</h2>
{cards_html}
</section>

<section id="discussion">
<h2>Discussion</h2>
<p class="muted">Narrative observations. Edit <code>docs/discussion.md</code> and re-run <code>scripts/gen_site.py</code> to update.</p>
<div class="discussion">{discussion_html}</div>
</section>

<section id="runs">
<h2>Run history</h2>
<p class="muted">Every benchmark run recorded under <code>results/</code>. The latest run per combo populates the per-model details above; earlier runs are kept for reference.</p>
<table class="history">
  <thead><tr><th>Run directory</th><th>Timestamp</th><th>Combos in this run</th></tr></thead>
  <tbody>{history_rows}</tbody>
</table>
</section>

<footer>
<p>Generated by <code>scripts/gen_site.py</code> · {repo_link}</p>
</footer>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

DEFAULT_DISCUSSION = """## Headline takeaway

_Write the single most important conclusion here._

## Why these results matter

_Frame the decision (e.g. "for offline coding while traveling") and what we should run, and why._

## Surprises and gotchas

_Things that didn't match expectations — model behaviors, broken quants, configuration quirks._

## What to test next

_Open questions; models or settings worth a follow-up run._
"""

def repo_slug_or_none():
    """Read git config for the owner/repo if available, else None."""
    import subprocess
    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
        # git@github.com:OWNER/REPO.git  OR  https://github.com/OWNER/REPO(.git)?
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "REPO-OWNER/REPO-NAME"


def main():
    DOCS.mkdir(exist_ok=True)

    if not DISCUSSION_FILE.exists():
        DISCUSSION_FILE.write_text(DEFAULT_DISCUSSION)
        print(f"[gen_site] created {DISCUSSION_FILE} with template")
    discussion_md = DISCUSSION_FILE.read_text()

    all_combos = list(walk_runs(RESULTS))
    print(f"[gen_site] found {len(all_combos)} combo runs across {RESULTS}")
    if not all_combos:
        print("[gen_site] no runs found; nothing to render")
        return 1

    latest = latest_per_combo(all_combos)
    print(f"[gen_site] showing {len(latest)} unique combos (latest per name)")

    findings = compute_findings(latest)

    run_history = {}
    for c in all_combos:
        rn = c["run_name"]
        if rn not in run_history:
            run_history[rn] = {
                "run_name": rn,
                "timestamp": c["run_timestamp"],
                "combos": set(),
            }
        run_history[rn]["combos"].add(c["name"])
    history_list = sorted(
        run_history.values(), key=lambda r: r["timestamp"], reverse=True
    )
    for r in history_list:
        r["combos"] = ", ".join(sorted(r["combos"]))

    repo_slug = repo_slug_or_none()
    html_content = render_html(latest, findings, discussion_md, history_list, repo_slug)

    (DOCS / "index.html").write_text(html_content)
    print(f"[gen_site] wrote {DOCS/'index.html'} ({len(html_content)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
