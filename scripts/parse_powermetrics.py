#!/usr/bin/env python3
"""Parse powermetrics text output → JSON summary.

powermetrics (macOS) emits text reports separated by `*** Sampled system activity ***`.
We extract per-sample CPU/GPU/ANE/Combined power in mW, then aggregate.

Usage:
    parse_powermetrics.py POWER.txt [--baseline BASELINE.json]

Writes JSON to stdout. Schema:
    {
      "sample_count": N,
      "sample_interval_s": 1.0,
      "duration_s": N * interval,
      "cpu_mw":     {"avg", "max", "min"},
      "gpu_mw":     {"avg", "max", "min"},
      "ane_mw":     {"avg", "max", "min"},
      "package_mw": {"avg", "max", "min"},
      "energy_joules": ...,   # integral of package_mw over duration
      "energy_wh": ...,
      "thermal_pressure_max": "Nominal|Light|Moderate|Heavy|Trapping" (best-effort),
      "delta_package_mw_avg": optional,  # if --baseline given: avg - baseline.package_avg
      "delta_energy_joules": optional,
      "baseline_subtracted": bool
    }
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

SAMPLE_DELIMITER = re.compile(r"\*\*\* Sampled system activity[^\n]*\*\*\*")
ELAPSED_MS = re.compile(r"\(([\d.]+)\s*ms elapsed\)")
CPU_POWER = re.compile(r"CPU Power(?:\s+\(combined\))?:\s+([\d.]+)\s+mW", re.IGNORECASE)
GPU_POWER = re.compile(r"GPU Power:\s+([\d.]+)\s+mW", re.IGNORECASE)
ANE_POWER = re.compile(r"ANE Power:\s+([\d.]+)\s+mW", re.IGNORECASE)
COMBINED_POWER = re.compile(
    r"Combined Power\s*\(CPU \+ GPU(?:\s*\+\s*ANE)?\):\s+([\d.]+)\s+mW",
    re.IGNORECASE,
)
THERMAL = re.compile(r"Current pressure level:\s+(\w+)", re.IGNORECASE)


def parse_samples(text: str):
    """Yield one dict per power sample chunk."""
    chunks = SAMPLE_DELIMITER.split(text)
    for chunk in chunks:
        if not chunk.strip() or "Power" not in chunk:
            continue
        sample = {}
        if m := ELAPSED_MS.search(chunk):
            sample["elapsed_ms"] = float(m.group(1))
        if m := CPU_POWER.search(chunk):
            sample["cpu_mw"] = float(m.group(1))
        if m := GPU_POWER.search(chunk):
            sample["gpu_mw"] = float(m.group(1))
        if m := ANE_POWER.search(chunk):
            sample["ane_mw"] = float(m.group(1))
        if m := COMBINED_POWER.search(chunk):
            sample["package_mw"] = float(m.group(1))
        else:
            # Some powermetrics versions omit Combined Power; sum what we have
            parts = [sample.get(k, 0) for k in ("cpu_mw", "gpu_mw", "ane_mw")]
            if any(v > 0 for v in parts):
                sample["package_mw"] = sum(parts)
        if m := THERMAL.search(chunk):
            sample["thermal_pressure"] = m.group(1)
        if "cpu_mw" in sample or "gpu_mw" in sample:
            yield sample


def stats_of(values):
    """Return {avg, max, min} as ints (mW). None-safe."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return {
        "avg": int(round(statistics.mean(nums))),
        "max": int(round(max(nums))),
        "min": int(round(min(nums))),
    }


def aggregate(samples):
    if not samples:
        return None
    cpu = stats_of(s.get("cpu_mw") for s in samples)
    gpu = stats_of(s.get("gpu_mw") for s in samples)
    ane = stats_of(s.get("ane_mw") for s in samples)
    pkg = stats_of(s.get("package_mw") for s in samples)

    # Estimate sample interval from elapsed_ms (median is robust to startup jitter)
    intervals_ms = [s.get("elapsed_ms") for s in samples if s.get("elapsed_ms")]
    interval_s = (
        statistics.median(intervals_ms) / 1000.0
        if intervals_ms else 1.0
    )

    duration_s = interval_s * len(samples)
    # Energy = ∫ package_mw dt. Sum (mW × interval_s) / 1000 = joules.
    if pkg:
        # Use per-sample integration when possible (handles varying intervals).
        energy_j = sum(
            (s.get("package_mw") or 0) * ((s.get("elapsed_ms") or interval_s * 1000) / 1000) / 1000
            for s in samples
        )
    else:
        energy_j = None

    # Thermal pressure: worst-case seen
    thermal_levels = {"Nominal": 0, "Light": 1, "Moderate": 2, "Heavy": 3, "Trapping": 4}
    seen = [s.get("thermal_pressure") for s in samples if s.get("thermal_pressure")]
    worst = max(seen, key=lambda x: thermal_levels.get(x, -1), default=None) if seen else None

    return {
        "sample_count": len(samples),
        "sample_interval_s": round(interval_s, 3),
        "duration_s": round(duration_s, 2),
        "cpu_mw": cpu,
        "gpu_mw": gpu,
        "ane_mw": ane,
        "package_mw": pkg,
        "energy_joules": round(energy_j, 2) if energy_j is not None else None,
        "energy_wh": round(energy_j / 3600, 4) if energy_j is not None else None,
        "thermal_pressure_max": worst,
        "baseline_subtracted": False,
    }


def apply_baseline(agg, baseline_path):
    """Add delta_* fields if a baseline JSON is provided."""
    if not baseline_path or not Path(baseline_path).exists():
        return agg
    try:
        baseline = json.loads(Path(baseline_path).read_text())
    except (json.JSONDecodeError, OSError):
        return agg
    if not baseline or not agg or not agg.get("package_mw"):
        return agg
    base_pkg_avg = baseline.get("package_mw", {}).get("avg")
    if base_pkg_avg is None:
        return agg
    agg["delta_package_mw_avg"] = max(0, agg["package_mw"]["avg"] - base_pkg_avg)
    if agg.get("energy_joules") and agg.get("duration_s"):
        delta_mw = agg["delta_package_mw_avg"]
        agg["delta_energy_joules"] = round(delta_mw * agg["duration_s"] / 1000, 2)
    agg["baseline_subtracted"] = True
    agg["baseline_package_mw_avg"] = base_pkg_avg
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("power_txt", type=Path)
    ap.add_argument("--baseline", type=Path, default=None,
                    help="Optional idle-baseline JSON (produced by an earlier run of this script).")
    args = ap.parse_args()

    if not args.power_txt.exists():
        print(json.dumps({"error": f"file not found: {args.power_txt}"}))
        return 1

    text = args.power_txt.read_text(errors="replace")
    samples = list(parse_samples(text))
    agg = aggregate(samples)
    if agg is None:
        print(json.dumps({"error": "no power samples parsed", "raw_bytes": len(text)}))
        return 2
    agg = apply_baseline(agg, args.baseline)
    print(json.dumps(agg, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
