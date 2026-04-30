"""
verify_tracking.py
------------------
Independent quality check on a tracking CSV produced by ring_tracker.py.

The `dropout` column only flags frames where *no* marker was found at all.
It cannot tell you whether the marker that *was* found is the right one —
without an anchor gate, the fallback chain can latch onto a chunk of arm
shaft when the marker mask is empty, and that shows up as `dropout=0`.

This script computes the apparent angular velocity (ω = Δθ/dt with proper
±180° unwrapping) per frame and flags rows whose |ω| exceeds a physical
threshold. A pendulum with arm length 35 cm starting from inverted
maxes out around 1200–1500 °/s for arm 2 in chaotic regimes, so anything
above ~2500 °/s is almost certainly a tracking jump rather than physics.

Usage
~~~~~
    python scripts/processing/verify_tracking.py
    python scripts/processing/verify_tracking.py data/long_recording_tracking.csv
    python scripts/processing/verify_tracking.py data/long_recording_tracking.csv --omega-cap 2000

Outputs
~~~~~~~
    Console: summary of suspect rows split by phase, plus the
             cross-tab with the existing `dropout` flag.
    output/<stem>_verification.png : θ1 / θ2 over time with suspect
                                     frames highlighted in red. Also
                                     overlays the apparent ω.
    data/<stem>_verification.csv  : same rows as the input + a
                                     `suspect` column (0/1).
"""

import csv
import os
import sys
import argparse
import numpy as np

# The script prints angle / omega symbols (θ, ω, Δ) which fall outside
# Windows' default cp1252 stdout encoding when output is captured. Force
# UTF-8 so the script works the same in cmd, PowerShell, Git Bash, and
# when piped to a file.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT = r"C:\dev\chaos"
DEFAULT_CSV = os.path.join(ROOT, r"data\long_recording_tracking.csv")


def parse_args():
    p = argparse.ArgumentParser(
        description="Sanity-check a pendulum tracking CSV.")
    p.add_argument("csv", nargs="?", default=DEFAULT_CSV,
                   help="path to tracking CSV (default: long_recording_tracking.csv)")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="deg/s above which |Δθ/dt| is flagged as suspect "
                        "(default 2500; arm-2 chaos peaks ~1500)")
    p.add_argument("--no-plot", action="store_true",
                   help="skip the matplotlib plot")
    p.add_argument("--no-csv-out", action="store_true",
                   help="skip writing data/<stem>_verification.csv")
    return p.parse_args()


def wrap_diff(angle_series):
    """
    Frame-to-frame Δθ that handles the ±180° wraparound. Returns an array
    the same length as the input, with NaN in slots where the diff is
    undefined (first frame, or either neighbour was a dropout).
    """
    a = np.asarray(angle_series, dtype=float)
    d = np.empty_like(a)
    d[:] = np.nan
    for i in range(1, len(a)):
        if np.isnan(a[i]) or np.isnan(a[i - 1]):
            continue
        delta = ((a[i] - a[i - 1] + 180.0) % 360.0) - 180.0
        d[i] = delta
    return d


def main():
    args = parse_args()

    csv_path = args.csv
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(ROOT, csv_path)
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    # Strip the trailing `_tracking` so outputs read e.g.
    # `long_recording_verification.csv`, not `long_recording_tracking_verification.csv`.
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    if stem.endswith("_tracking"):
        stem = stem[: -len("_tracking")]

    print(f"verify_tracking.py")
    print(f"CSV : {csv_path}")
    print(f"|ω| threshold: {args.omega_cap:.0f} deg/s")
    print()

    # ── Load the CSV ────────────────────────────────────────────────────
    with open(csv_path, "r") as f:
        rows = list(csv.DictReader(f))

    n     = len(rows)
    times = np.array([float(r["time_s"])     for r in rows])
    drops = np.array([int(r["dropout"])      for r in rows])
    phase = np.array([r["phase"]             for r in rows])

    def to_float_or_nan(x):
        return float(x) if x not in ("", None) else np.nan

    th1 = np.array([to_float_or_nan(r["theta1_deg"]) for r in rows])
    th2 = np.array([to_float_or_nan(r["theta2_deg"]) for r in rows])

    # ── Per-frame dt (use median to be robust to gaps) ─────────────────
    diffs = np.diff(times)
    dt_med = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 1.0 / 60.0
    print(f"Median dt: {dt_med * 1000:.2f} ms  ({1.0 / dt_med:.2f} fps)")

    # ── ω from finite differences with unwrap ──────────────────────────
    dth1 = wrap_diff(th1)
    dth2 = wrap_diff(th2)

    om1 = dth1 / dt_med   # deg/s
    om2 = dth2 / dt_med

    suspect1 = np.abs(om1) > args.omega_cap
    suspect2 = np.abs(om2) > args.omega_cap
    suspect  = suspect1 | suspect2

    # ── Headline numbers ────────────────────────────────────────────────
    n_drop          = int(np.sum(drops == 1))
    n_suspect       = int(np.sum(suspect))
    n_drop_suspect  = int(np.sum(suspect & (drops == 1)))
    n_clean_suspect = int(np.sum(suspect & (drops == 0)))

    print(f"\nTotals over {n} frames")
    print(f"  marked dropout=1            : {n_drop:>6}  ({100 * n_drop / n:.2f}%)")
    print(f"  suspect (|ω| > cap)         : {n_suspect:>6}  ({100 * n_suspect / n:.2f}%)")
    print(f"    also dropout=1            : {n_drop_suspect:>6}")
    print(f"    but dropout=0  ← hidden   : {n_clean_suspect:>6}  ({100 * n_clean_suspect / n:.2f}%)")
    if n_clean_suspect > 0:
        print("    ^^^ these are likely false-positive detections")

    # ── Per-arm breakdown ──────────────────────────────────────────────
    print(f"\nPer-arm |ω| > cap (clean rows only):")
    clean = drops == 0
    print(f"  arm 1 only : {int(np.sum(suspect1 & ~suspect2 & clean)):>6}")
    print(f"  arm 2 only : {int(np.sum(suspect2 & ~suspect1 & clean)):>6}")
    print(f"  both       : {int(np.sum(suspect1 & suspect2 & clean)):>6}")

    # ── Phase breakdown ────────────────────────────────────────────────
    holding = phase == "holding"
    free    = phase == "free_swing"
    print(f"\nBy phase (clean rows only):")
    print(f"  holding    suspect : {int(np.sum(suspect & clean & holding)):>6} / {int(np.sum(clean & holding))}")
    print(f"  free_swing suspect : {int(np.sum(suspect & clean & free)):>6} / {int(np.sum(clean & free))}")

    # ── Show worst-offender frames ─────────────────────────────────────
    if n_clean_suspect > 0:
        # Combined |ω| score (max of the two)
        worst_score = np.fmax(np.abs(om1), np.abs(om2))
        worst_score[~(suspect & clean)] = -1
        idx_sorted = np.argsort(worst_score)[::-1]
        worst = idx_sorted[:min(10, n_clean_suspect)]
        print(f"\nTop suspect frames (dropout=0):")
        print(f"  {'frame':>7}  {'time(s)':>8}  {'phase':>11}  "
              f"{'th1':>8}  {'th2':>8}  {'|w1|':>9}  {'|w2|':>9}")
        for i in worst:
            print(f"  {int(rows[i]['frame']):>7}  {times[i]:>8.3f}  "
                  f"{phase[i]:>11}  "
                  f"{th1[i]:>8.2f}  {th2[i]:>8.2f}  "
                  f"{abs(om1[i]):>9.0f}  {abs(om2[i]):>9.0f}")

    # ── Optional: write CSV with a `suspect` column ────────────────────
    if not args.no_csv_out:
        out_csv = os.path.join(ROOT, "data", f"{stem}_verification.csv")
        with open(out_csv, "w", newline="") as f:
            fieldnames = list(rows[0].keys()) + [
                "omega1_deg_s", "omega2_deg_s", "suspect"]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for i, r in enumerate(rows):
                out = dict(r)
                out["omega1_deg_s"] = (
                    f"{om1[i]:.2f}" if not np.isnan(om1[i]) else "")
                out["omega2_deg_s"] = (
                    f"{om2[i]:.2f}" if not np.isnan(om2[i]) else "")
                out["suspect"] = 1 if suspect[i] else 0
                w.writerow(out)
        print(f"\nWrote: {out_csv}")

    # ── Optional: matplotlib plot ──────────────────────────────────────
    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("\nmatplotlib not available — skipping plot")
            return

        fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)

        axes[0].plot(times, th1, lw=0.6, label="θ1")
        axes[0].plot(times, th2, lw=0.6, label="θ2", alpha=0.7)
        if n_clean_suspect > 0:
            mask = suspect & clean
            axes[0].scatter(times[mask], th1[mask], s=8, c="red",
                            label="suspect θ1", zorder=3)
            axes[0].scatter(times[mask], th2[mask], s=8, c="darkred",
                            label="suspect θ2", zorder=3)
        axes[0].axvline(times[(phase == "free_swing").argmax()],
                        color="grey", ls="--", lw=0.8, label="release")
        axes[0].set_ylabel("angle (deg)")
        axes[0].legend(loc="upper right", fontsize=8)
        axes[0].grid(alpha=0.3)

        axes[1].plot(times, om1, lw=0.5, label="ω1")
        axes[1].plot(times, om2, lw=0.5, label="ω2", alpha=0.7)
        axes[1].axhline( args.omega_cap, color="red", ls=":", lw=0.7)
        axes[1].axhline(-args.omega_cap, color="red", ls=":", lw=0.7,
                        label=f"±{args.omega_cap:.0f} deg/s cap")
        axes[1].set_ylabel("ω (deg/s)")
        axes[1].legend(loc="upper right", fontsize=8)
        axes[1].grid(alpha=0.3)

        # Bottom panel: dropout / suspect timeline
        axes[2].fill_between(times, 0, drops,
                             step="mid", color="grey", alpha=0.6,
                             label="dropout")
        axes[2].fill_between(times, 0, suspect.astype(int),
                             step="mid", color="red", alpha=0.4,
                             label="suspect")
        axes[2].set_yticks([0, 1])
        axes[2].set_ylabel("flags")
        axes[2].set_xlabel("time (s)")
        axes[2].legend(loc="upper right", fontsize=8)
        axes[2].grid(alpha=0.3)

        plt.suptitle(f"{stem}  —  "
                     f"dropouts {n_drop} ({100*n_drop/n:.1f}%)  |  "
                     f"hidden suspects {n_clean_suspect} "
                     f"({100*n_clean_suspect/n:.2f}%)")
        plt.tight_layout()

        out_png = os.path.join(ROOT, "output", f"{stem}_verification.png")
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        plt.savefig(out_png, dpi=140)
        print(f"Plot: {out_png}")


if __name__ == "__main__":
    main()
