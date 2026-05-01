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
    python scripts/processing/verify_tracking.py --stem th1_p180_th2_m179
    python scripts/processing/verify_tracking.py measurements/th1_p180_th2_m179/tracking.csv
    python scripts/processing/verify_tracking.py --omega-cap 2000 --stem th1_p044_th2_m001

Outputs
~~~~~~~
    Console:                                summary of suspect rows split
                                            by phase, plus the cross-tab
                                            with the existing `dropout`
                                            flag.
    measurements/<config>/verification.png  : θ1 / θ2 over time with suspect
                                              frames in red, plus the apparent ω.
    measurements/<config>/verification.csv  : same rows as the input + a
                                              `suspect` column (0/1).
"""

import csv
import os
import sys
import json
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
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")
DEFAULT_CSV = os.path.join(ROOT, "measurements", "th1_p180_th2_m179",
                           "tracking.csv")

# Pull rendering helpers from scripts/utils/render.py — every print
# block in this script that produces a table is delegated there so
# the verdict layer and the live verify output stay visually
# consistent.
sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from render import (  # noqa: E402
    render_verification_summary,
    render_arm_breakdown,
    render_phase_summary,
    render_suspect_table,
    render_arm_length_violations,
)
from thresholds import (  # noqa: E402
    ARM_LEN_THRESHOLD_PCT,
    OMEGA_CAP_HOLDING,
    DELTA_OMEGA_CAP,
    SWAP_RATIO_THRESHOLD,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Sanity-check a pendulum tracking CSV.")
    p.add_argument("csv", nargs="?", default=None,
                   help="path to tracking CSV (positional)")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p180_th2_m179. "
                        "Resolves the CSV and output dir from "
                        "measurements/<stem>/.")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="deg/s above which |Δθ/dt| is flagged as suspect "
                        "(default 2500; arm-2 chaos peaks ~1500)")
    p.add_argument("--no-plot", action="store_true",
                   help="skip the matplotlib plot")
    p.add_argument("--no-csv-out", action="store_true",
                   help="skip writing the verification.csv companion")
    p.add_argument("--arm-len-threshold", type=float,
                   default=ARM_LEN_THRESHOLD_PCT,
                   help=f"pixel arm-length deviation %% above which a "
                        f"clean frame is flagged as a tracker error "
                        f"(default {ARM_LEN_THRESHOLD_PCT:.0f}%%)")
    p.add_argument("--delta-omega-cap", type=float,
                   default=DELTA_OMEGA_CAP,
                   help=f"maximum |Δω| per frame in °/s; catches sudden "
                        f"acceleration spikes that signal a tracker latch "
                        f"(default {DELTA_OMEGA_CAP:.0f})")
    return p.parse_args()


def resolve_paths(args):
    """
    Returns (csv_path, output_dir, stem_label).
    Priority: --stem > positional csv > DEFAULT_CSV.
    output_dir is where verification.csv / verification.png are written.
    """
    if args.stem:
        meas_dir = os.path.join(ROOT, "measurements", args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            print(f"ERROR: tracking.csv not found for stem '{args.stem}'")
            print(f"  Expected: {csv_path}")
            sys.exit(1)
        return csv_path, meas_dir, args.stem

    if args.csv:
        csv_path = args.csv
        if not os.path.isabs(csv_path):
            csv_path = os.path.join(ROOT, csv_path)
        # Write outputs next to the CSV — i.e., into the measurement folder.
        output_dir = os.path.dirname(csv_path)
        stem_label = os.path.basename(output_dir) or \
                     os.path.splitext(os.path.basename(csv_path))[0]
        return csv_path, output_dir, stem_label

    csv_path = DEFAULT_CSV
    output_dir = os.path.dirname(csv_path)
    stem_label = os.path.basename(output_dir)
    return csv_path, output_dir, stem_label


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

    csv_path, output_dir, stem = resolve_paths(args)
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    print(f"verify_tracking.py")
    print(f"CSV    : {csv_path}")
    print(f"Folder : {output_dir}")
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

    # Load marker pixel positions for the arm-length rigidity check.
    x_green = np.array([to_float_or_nan(r.get("x_green", "")) for r in rows])
    y_green = np.array([to_float_or_nan(r.get("y_green", "")) for r in rows])
    x_red   = np.array([to_float_or_nan(r.get("x_red",   "")) for r in rows])
    y_red   = np.array([to_float_or_nan(r.get("y_red",   "")) for r in rows])

    # ── Per-frame dt (use median to be robust to gaps) ─────────────────
    diffs = np.diff(times)
    dt_med = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 1.0 / 60.0
    print(f"Median dt: {dt_med * 1000:.2f} ms  ({1.0 / dt_med:.2f} fps)")

    # ── ω from finite differences with unwrap ──────────────────────────
    dth1 = wrap_diff(th1)
    dth2 = wrap_diff(th2)

    om1 = dth1 / dt_med   # deg/s
    om2 = dth2 / dt_med

    # Arm-length rigidity (pixel distance from green pivot to red tip).
    # Frames where green or red is missing yield NaN; the median is
    # taken over clean rows so dropouts don't pull the reference.
    arm_len = np.sqrt((x_red - x_green) ** 2 + (y_red - y_green) ** 2)
    clean_arm_mask = (drops == 0) & ~np.isnan(arm_len)
    if clean_arm_mask.any():
        arm_median = float(np.nanmedian(arm_len[clean_arm_mask]))
    else:
        arm_median = float("nan")
    if not np.isnan(arm_median) and arm_median > 0:
        arm_dev_pct = np.abs(arm_len - arm_median) / arm_median * 100.0
    else:
        arm_dev_pct = np.full_like(arm_len, np.nan)

    # Phase-separated ω caps. Holding-phase markers should be
    # stationary, so ANY ω above OMEGA_CAP_HOLDING is tracker noise,
    # not physics. Free-swing keeps the user-configurable cap (default
    # 2500 °/s, well above the 1500 °/s physical RoT).
    suspect = np.zeros(n, dtype=bool)
    free_mask    = (phase == "free_swing")
    holding_mask = (phase == "holding")
    if free_mask.any():
        suspect[free_mask] = (
            (np.abs(om1[free_mask]) > args.omega_cap) |
            (np.abs(om2[free_mask]) > args.omega_cap)
        )
    if holding_mask.any():
        suspect[holding_mask] = (
            (np.abs(om1[holding_mask]) > OMEGA_CAP_HOLDING) |
            (np.abs(om2[holding_mask]) > OMEGA_CAP_HOLDING)
        )

    # Per-arm masks (using the same phase-aware caps) for the breakdown.
    suspect1 = np.zeros(n, dtype=bool)
    suspect2 = np.zeros(n, dtype=bool)
    if free_mask.any():
        suspect1[free_mask] = np.abs(om1[free_mask]) > args.omega_cap
        suspect2[free_mask] = np.abs(om2[free_mask]) > args.omega_cap
    if holding_mask.any():
        suspect1[holding_mask] = np.abs(om1[holding_mask]) > OMEGA_CAP_HOLDING
        suspect2[holding_mask] = np.abs(om2[holding_mask]) > OMEGA_CAP_HOLDING

    # Arm-length violations (clean frames only — dropouts have no
    # arm length to check).
    arm_violation = np.zeros(n, dtype=bool)
    if not np.isnan(arm_median):
        arm_violation = ((arm_dev_pct > args.arm_len_threshold)
                         & (drops == 0)
                         & ~np.isnan(arm_dev_pct))

    # Δω post-hoc check (Brief 5). Catches frames where ω itself looks
    # plausible but the per-frame change in ω is unphysical — typical
    # signature of a tracker latch onto a slow-moving wrong object.
    dom1 = np.empty_like(om1)
    dom2 = np.empty_like(om2)
    dom1[:] = np.nan
    dom2[:] = np.nan
    for i in range(1, n):
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om1[i]) and not np.isnan(om1[i - 1])):
            dom1[i] = abs(om1[i] - om1[i - 1])
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om2[i]) and not np.isnan(om2[i - 1])):
            dom2[i] = abs(om2[i] - om2[i - 1])
    accel_suspect1 = dom1 > args.delta_omega_cap
    accel_suspect2 = dom2 > args.delta_omega_cap
    accel_suspect  = (accel_suspect1 | accel_suspect2) & (drops == 0)
    # Treat NaN-derived comparisons as False — np.isnan(...) > X is
    # already False but be explicit.
    accel_suspect &= ~np.isnan(np.where(accel_suspect1, dom1, dom2))

    # Marker swap detection (Brief 5). Each consecutive pair of clean
    # frames is checked: if the cross-pairing distance is much smaller
    # than the same-pairing, the markers have swapped labels.
    swap_suspect = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if drops[i] or drops[i - 1]:
            continue
        gx0, gy0 = x_green[i - 1], y_green[i - 1]
        gx1, gy1 = x_green[i],     y_green[i]
        rx0, ry0 = x_red[i - 1],   y_red[i - 1]
        rx1, ry1 = x_red[i],       y_red[i]
        if any(np.isnan(v) for v in (gx0, gy0, gx1, gy1,
                                     rx0, ry0, rx1, ry1)):
            continue
        d_same  = (np.hypot(gx1 - gx0, gy1 - gy0)
                 + np.hypot(rx1 - rx0, ry1 - ry0))
        d_cross = (np.hypot(rx1 - gx0, ry1 - gy0)
                 + np.hypot(gx1 - rx0, gy1 - ry0))
        if d_same > 0 and (d_cross / d_same) < SWAP_RATIO_THRESHOLD:
            swap_suspect[i] = True

    # Merge new flags into the combined suspect mask. They count as
    # hidden suspects (dropout=0 + suspect=1) for downstream consumers.
    suspect = suspect | accel_suspect | swap_suspect
    n_accel_suspect = int(np.sum(accel_suspect))
    n_swap_suspect  = int(np.sum(swap_suspect))

    # ── Headline numbers ────────────────────────────────────────────────
    n_drop          = int(np.sum(drops == 1))
    n_suspect       = int(np.sum(suspect))
    n_drop_suspect  = int(np.sum(suspect & (drops == 1)))
    n_clean_suspect = int(np.sum(suspect & (drops == 0)))

    render_verification_summary(
        n, n_drop, n_suspect, n_clean_suspect, dt_med,
        extras={
            "n_accel_suspect": n_accel_suspect,
            "n_swap_suspect":  n_swap_suspect,
        })

    # ── Per-arm breakdown ──────────────────────────────────────────────
    clean = drops == 0
    render_arm_breakdown({
        "arm1_only": int(np.sum(suspect1 & ~suspect2 & clean)),
        "arm2_only": int(np.sum(suspect2 & ~suspect1 & clean)),
        "both":      int(np.sum(suspect1 & suspect2 & clean)),
    })

    # ── Phase breakdown ────────────────────────────────────────────────
    holding = phase == "holding"
    free    = phase == "free_swing"
    render_phase_summary({
        "holding": {
            "suspect":     int(np.sum(suspect & clean & holding)),
            "total_clean": int(np.sum(clean & holding)),
        },
        "free_swing": {
            "suspect":     int(np.sum(suspect & clean & free)),
            "total_clean": int(np.sum(clean & free)),
        },
    })

    # ── Show worst-offender frames ─────────────────────────────────────
    suspects_list = []
    if n_clean_suspect > 0:
        # Combined |ω| score (max of the two)
        worst_score = np.fmax(np.abs(om1), np.abs(om2))
        worst_score[~(suspect & clean)] = -1
        idx_sorted = np.argsort(worst_score)[::-1]
        worst = idx_sorted[:min(10, n_clean_suspect)]
        for i in worst:
            arm_l_val   = (float(arm_len[i])
                           if not np.isnan(arm_len[i]) else None)
            arm_dev_val = (float(arm_dev_pct[i])
                           if not np.isnan(arm_dev_pct[i]) else None)
            suspects_list.append({
                "frame":              int(rows[i]["frame"]),
                "time_s":             float(times[i]),
                "phase":              str(phase[i]),
                "th1":                float(th1[i]),
                "th2":                float(th2[i]),
                "om1":                float(abs(om1[i])),
                "om2":                float(abs(om2[i])),
                "arm_length_px":      arm_l_val,
                "arm_length_dev_pct": arm_dev_val,
            })
    render_suspect_table(suspects_list, omega_cap=args.omega_cap)

    # ── Arm-length violations (rigid-body sanity) ──────────────────────
    violations_list = []
    for i in np.where(arm_violation)[0]:
        violations_list.append({
            "frame":          int(rows[i]["frame"]),
            "time_s":         float(times[i]),
            "phase":          str(phase[i]),
            "arm_length_px":  float(arm_len[i]),
            "median_arm_px":  float(arm_median),
            "dev_pct":        float(arm_dev_pct[i]),
        })
    render_arm_length_violations(violations_list)

    # ── Optional: write CSV with extra audit columns ───────────────────
    if not args.no_csv_out:
        os.makedirs(output_dir, exist_ok=True)
        out_csv = os.path.join(output_dir, "verification.csv")
        with open(out_csv, "w", newline="") as f:
            fieldnames = list(rows[0].keys()) + [
                "omega1_deg_s", "omega2_deg_s", "suspect",
                "arm_length_px", "arm_dev_pct", "omega_cap_applied",
                "delta_omega_suspect", "swap_suspect",
            ]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for i, r in enumerate(rows):
                out = dict(r)
                out["omega1_deg_s"] = (
                    f"{om1[i]:.2f}" if not np.isnan(om1[i]) else "")
                out["omega2_deg_s"] = (
                    f"{om2[i]:.2f}" if not np.isnan(om2[i]) else "")
                out["suspect"] = 1 if suspect[i] else 0
                out["arm_length_px"] = (
                    f"{arm_len[i]:.2f}" if not np.isnan(arm_len[i]) else "")
                out["arm_dev_pct"] = (
                    f"{arm_dev_pct[i]:.2f}"
                    if not np.isnan(arm_dev_pct[i]) else "")
                out["omega_cap_applied"] = (
                    f"{OMEGA_CAP_HOLDING:.0f}"
                    if phase[i] == "holding"
                    else f"{args.omega_cap:.0f}")
                out["delta_omega_suspect"] = 1 if accel_suspect[i] else 0
                out["swap_suspect"]        = 1 if swap_suspect[i]  else 0
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

        os.makedirs(output_dir, exist_ok=True)
        out_png = os.path.join(output_dir, "verification.png")
        plt.savefig(out_png, dpi=140)
        print(f"Plot: {out_png}")


if __name__ == "__main__":
    main()
