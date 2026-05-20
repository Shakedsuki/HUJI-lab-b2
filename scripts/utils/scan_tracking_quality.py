"""
scan_tracking_quality.py
-------------------------
Walk every clip in experiments.json that has a verification.csv on
disk and produce a per-clip quality table. Highlight outliers.

Designed as the post-bulk gate: after `chaos bulk` runs, this gives a
one-page view of whether the tracker output is uniformly clean or
whether specific clips need a second look before analysis.

Per-clip columns
~~~~~~~~~~~~~~~~
  n_frames        — total frames in verification.csv
  dropout_pct     — fraction of frames flagged dropout=1
  peak_om1        — max |ω₁| across the clip
  peak_om2        — max |ω₂| across the clip
  arm_dev_max     — max % deviation of green↔red distance from median
  n_suspect       — count of frames flagged suspect=1
  n_omega_cap     — subcount: frames with omega_cap_suspect=1
  n_delta_omega   — subcount: frames with delta_omega_suspect=1
  n_swap          — subcount: marker-swap candidates
  verdict         — PASS / WARN / FAIL (via track_one.compute_verdict)

Outliers flagged
~~~~~~~~~~~~~~~~
  dropout_pct > 1.0           — more than 1% of frames missing markers
  peak_om2 > PEAK_OMEGA_ABSURD — almost certainly a tracker error
  arm_dev_max > 5.0           — rigid-rod constraint violated badly
  verdict != PASS             — any reason at all in compute_verdict

Usage
~~~~~
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py

    # Write a CSV alongside the console table:
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --csv data/tracking_quality.csv

    # Filter to a substring (useful for one sweep at a time):
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --filter 3.2V

    # Only show flagged clips (the typical follow-up after a first scan):
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/scan_tracking_quality.py --flagged-only
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
from thresholds import PEAK_OMEGA_ABSURD, PEAK_OMEGA_PHYSICAL  # noqa: E402
from track_one import (  # noqa: E402
    compute_verdict, read_verification_metrics,
)

DROPOUT_OUTLIER_PCT = 1.0
ARM_DEV_OUTLIER_PCT = 5.0


def load_registry():
    if not os.path.exists(EXPERIMENTS):
        return {}
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def per_clip_stats(stem):
    """Return a dict of stats for one clip, or None if the
    verification.csv is missing."""
    meas_dir = os.path.join(MEAS_DIR, stem)
    csv_path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(csv_path):
        return None

    # Read raw counters out of verification.csv for the headline stats.
    n_total = n_drop = n_susp = 0
    n_om = n_dom = n_swap = 0
    peak_o1 = peak_o2 = 0.0
    arm_dev_max = 0.0
    with open(csv_path, "r", newline="") as f:
        for r in csv.DictReader(f):
            n_total += 1
            try:
                if int(r.get("dropout") or 0):
                    n_drop += 1
            except ValueError:
                pass
            try:
                if int(r.get("suspect") or 0):
                    n_susp += 1
            except ValueError:
                pass
            try:
                if int(r.get("omega_cap_suspect") or 0):
                    n_om += 1
            except ValueError:
                pass
            try:
                if int(r.get("delta_omega_suspect") or 0):
                    n_dom += 1
            except ValueError:
                pass
            try:
                if int(r.get("swap_suspect") or 0):
                    n_swap += 1
            except ValueError:
                pass
            try:
                o1 = abs(float(r.get("omega1_deg_s") or 0))
                if o1 > peak_o1:
                    peak_o1 = o1
            except ValueError:
                pass
            try:
                o2 = abs(float(r.get("omega2_deg_s") or 0))
                if o2 > peak_o2:
                    peak_o2 = o2
            except ValueError:
                pass
            try:
                dev = float(r.get("arm_dev_pct") or 0)
                if dev > arm_dev_max:
                    arm_dev_max = dev
            except ValueError:
                pass

    drop_pct = 100.0 * n_drop / n_total if n_total else 0.0

    # Reuse track_one.compute_verdict for verdict consistency with the
    # interactive `chaos track` flow.
    metrics = read_verification_metrics(meas_dir) or {}
    verdict, _ = compute_verdict(metrics, metrics.get("n_suspect_hidden", 0))

    return {
        "stem":         stem,
        "n_frames":     n_total,
        "dropout_pct":  drop_pct,
        "peak_om1":     peak_o1,
        "peak_om2":     peak_o2,
        "arm_dev_max":  arm_dev_max,
        "n_suspect":    n_susp,
        "n_omega_cap":  n_om,
        "n_delta_omega": n_dom,
        "n_swap":       n_swap,
        "verdict":      verdict,
    }


def is_outlier(row):
    if row["dropout_pct"]  > DROPOUT_OUTLIER_PCT:  return True
    if row["peak_om2"]     > PEAK_OMEGA_ABSURD:    return True
    if row["arm_dev_max"]  > ARM_DEV_OUTLIER_PCT:  return True
    if row["verdict"]     != "PASS":               return True
    return False


def fmt_row(row, flagged):
    flag = "⚠" if flagged else " "
    peak_om2_marker = ""
    if row["peak_om2"] > PEAK_OMEGA_ABSURD:
        peak_om2_marker = " !"
    elif row["peak_om2"] > PEAK_OMEGA_PHYSICAL:
        peak_om2_marker = " *"
    return (
        f"  {flag}  {row['stem']:<22}  "
        f"{row['n_frames']:>5}  "
        f"{row['dropout_pct']:>6.2f}%  "
        f"{row['peak_om1']:>6.0f}    "
        f"{row['peak_om2']:>6.0f}{peak_om2_marker:<3} "
        f"{row['arm_dev_max']:>5.1f}%   "
        f"{row['n_suspect']:>4}  "
        f"({row['n_omega_cap']:>3}/{row['n_delta_omega']:>3}/{row['n_swap']:>2})  "
        f"{row['verdict']}"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", metavar="SUBSTR",
                    help="only include clips whose stem contains SUBSTR")
    ap.add_argument("--flagged-only", action="store_true",
                    help="only print clips that hit at least one outlier rule")
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

    # Sort: outliers first (worst → least), then PASS clips alphabetically.
    flagged = [r for r in rows if is_outlier(r)]
    clean   = [r for r in rows if not is_outlier(r)]
    flagged.sort(key=lambda r: (-r["dropout_pct"], -r["peak_om2"]))
    clean.sort(key=lambda r: r["stem"])

    print()
    print("=" * 100)
    print(f"tracking quality scan — {len(rows)} clips "
          f"({len(flagged)} flagged, {len(clean)} clean)")
    print("=" * 100)
    print(f"  ⚠   {'stem':<22}  {'frames':>5}  {'drop%':>7}  "
          f"{'pkω1':>6}    {'pkω2':>8}  {'armDv':>6}   "
          f"{'susp':>4}  (ωcap/Δω/swap)  verdict")
    print("-" * 100)

    if flagged:
        print("  ── flagged ───────────────────────────────────────────────")
        for r in flagged:
            print(fmt_row(r, flagged=True))

    if clean and not args.flagged_only:
        if flagged:
            print("  ── clean ─────────────────────────────────────────────────")
        for r in clean:
            print(fmt_row(r, flagged=False))

    print("-" * 100)
    print(f"  outlier thresholds:  dropout > {DROPOUT_OUTLIER_PCT}%  "
          f"|  peak |ω₂| > {PEAK_OMEGA_ABSURD:.0f}°/s (!)  "
          f"or > {PEAK_OMEGA_PHYSICAL:.0f}°/s (*)  "
          f"|  arm-dev > {ARM_DEV_OUTLIER_PCT}%  |  verdict ≠ PASS")
    if missing:
        print(f"  {len(missing)} clips missing verification.csv: "
              f"{', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}")

    print()
    n_pass = sum(1 for r in rows if r["verdict"] == "PASS")
    n_warn = sum(1 for r in rows if r["verdict"] == "WARN")
    n_fail = sum(1 for r in rows if r["verdict"] == "FAIL")
    n_zero_drop = sum(1 for r in rows if r["dropout_pct"] == 0.0)
    print(f"  Summary:  PASS {n_pass}  /  WARN {n_warn}  /  FAIL {n_fail}  "
          f"|  zero-dropout clips: {n_zero_drop}/{len(rows)}")
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
