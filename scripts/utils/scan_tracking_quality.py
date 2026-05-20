"""
scan_tracking_quality.py
-------------------------
Walk every clip in experiments.json that has a verification.csv on
disk and produce a one-page PASS / FAIL table.

Verdict is binary: a clip FAILs if dropout > DROPOUT_FAIL_PCT
(via track_one.compute_verdict). Nothing else.

Per-clip columns
~~~~~~~~~~~~~~~~
  stem         — clip name
  n_frames     — total frames in verification.csv
  n_dropout    — frames with dropout=1
  dropout_pct  — n_dropout / n_frames × 100
  verdict      — PASS / FAIL

FAIL clips sort to the top.

Usage
~~~~~
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py

    # Subset to one sweep
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --filter 3.2V

    # Show only FAILs
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --flagged-only

    # Also export CSV
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --csv data/tracking_quality.csv
"""

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import MEAS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from thresholds import DROPOUT_FAIL_PCT  # noqa: E402
from track_one import compute_verdict, read_verification_metrics  # noqa: E402


def load_registry():
    if not os.path.exists(EXPERIMENTS):
        return {}
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def per_clip_stats(stem):
    """Return {stem, n_frames, n_dropout, dropout_pct, verdict} or None."""
    meas_dir = os.path.join(MEAS_DIR, stem)
    metrics = read_verification_metrics(meas_dir)
    if metrics is None:
        return None
    verdict, _ = compute_verdict(metrics)
    return {
        "stem":        stem,
        "n_frames":    metrics.get("n_total", 0),
        "n_dropout":   metrics.get("n_dropout", 0),
        "dropout_pct": metrics.get("dropout_pct", 0.0) or 0.0,
        "verdict":     verdict,
    }


def fmt_row(row):
    flag = "✗" if row["verdict"] == "FAIL" else "✓"
    return (
        f"  {flag}  {row['stem']:<22}  "
        f"{row['n_frames']:>5}  "
        f"{row['n_dropout']:>5}  "
        f"{row['dropout_pct']:>6.2f}%   "
        f"{row['verdict']}"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", metavar="SUBSTR",
                    help="only include clips whose stem contains SUBSTR")
    ap.add_argument("--flagged-only", action="store_true",
                    help="only print clips that FAILed")
    ap.add_argument("--csv", metavar="PATH",
                    help="also write the per-clip table to a CSV file")
    args = ap.parse_args()

    reg = load_registry()
    if not reg:
        print(f"ERROR: registry not found or empty: {EXPERIMENTS}")
        return 1

    rows = []
    missing = []
    for key in sorted(reg.keys()):
        entry = reg[key]
        stem = entry.get("config_description") or key
        if args.filter and args.filter not in stem:
            continue
        stats = per_clip_stats(stem)
        if stats is None:
            missing.append(stem)
            continue
        rows.append(stats)

    if not rows:
        print("No verification.csv files found.")
        if missing:
            print(f"  {len(missing)} clips missing verification.csv "
                  f"(run chaos verify or chaos bulk first)")
        return 0

    # Sort: FAILs first (worst dropout first), PASSes alphabetically.
    fails = [r for r in rows if r["verdict"] == "FAIL"]
    passes = [r for r in rows if r["verdict"] == "PASS"]
    fails.sort(key=lambda r: -r["dropout_pct"])
    passes.sort(key=lambda r: r["stem"])

    print()
    print("=" * 70)
    print(f"tracking quality scan — {len(rows)} clips "
          f"({len(fails)} FAIL, {len(passes)} PASS)")
    print("=" * 70)
    print(f"     {'stem':<22}  {'frames':>5}  {'drop':>5}  "
          f"{'drop%':>7}   verdict")
    print("-" * 70)

    if fails:
        for r in fails:
            print(fmt_row(r))

    if passes and not args.flagged_only:
        if fails:
            print("  ── PASS ──────────────────────────────────────")
        for r in passes:
            print(fmt_row(r))

    print("-" * 70)
    print(f"  FAIL when dropout > {DROPOUT_FAIL_PCT}%")
    if missing:
        print(f"  {len(missing)} clips missing verification.csv: "
              f"{', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}")

    print()
    n_pass = len(passes)
    n_fail = len(fails)
    print(f"  Summary:  PASS {n_pass}  /  FAIL {n_fail}")
    print()

    if args.csv:
        out_path = args.csv
        if not os.path.isabs(out_path):
            out_path = os.path.join(REPO_ROOT, out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        fieldnames = list(rows[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"Wrote CSV: {os.path.relpath(out_path, REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
