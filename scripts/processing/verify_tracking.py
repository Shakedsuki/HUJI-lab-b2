"""
verify_tracking.py
------------------
Compute ω from tracking.csv, apply regime-agnostic sanity checks, write
verification.csv. Optional matplotlib plot.

What this script does NOT do anymore (PR D — driven-only pipeline)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The free-swing physics checks that previously lived here
(release-energy ceiling, fixed-pivot drift, θ-prediction residual,
holding-phase ω, trend arm-length, energy rolling spike) all assumed a
free-swinging pendulum with a fixed upper pivot. They produced near-
universal false positives on driven clips, where the motor pumps
energy in continuously and the upper pivot oscillates by design.
They've been removed. Their threshold constants in `thresholds.py` and
the corresponding reason blocks in `track_one.compute_verdict` are
gone too.

What this script does now
~~~~~~~~~~~~~~~~~~~~~~~~~
1. Reads tracking.csv (10 columns from bgr_tracker).
2. Computes ω₁(t) and ω₂(t) via Savitzky-Golay differentiation of θ
   with proper ±180° unwrapping.
3. Computes per-frame green↔red pixel distance and its deviation from
   the run median (rigid-rod sanity).
4. Applies regime-agnostic checks → sets `suspect=1`:
     * |ω| > omega_cap (default 2500 °/s, well above physical RoT)
     * |Δω| > delta_omega_cap (unphysical acceleration between adjacent
       clean frames)
     * marker swap (cross-pair distance test)
     * arm-length deviation > threshold (rigid-rod sanity)
5. Writes verification.csv. Columns kept:
     frame, time_s, phase, x_green, y_green, x_red, y_red,
     theta1_deg, theta2_deg, dropout,
     omega1_deg_s, omega2_deg_s,
     suspect,
     arm_length_px, arm_dev_pct, omega_cap_applied,
     delta_omega_suspect, swap_suspect, omega_cap_suspect
   Columns dropped: residual_suspect, energy_J,
   energy_ceiling_suspect, energy_rolling_spike, energy_suspect,
   trend_arm_suspect (all free-swing-only).
6. Optionally writes verification.png (θ + ω panels).

Usage
~~~~~
    python scripts/processing/verify_tracking.py --stem 4V_1.9Hz
    python scripts/processing/verify_tracking.py --stem 4V_1.9Hz --omega-cap 2000
"""

import argparse
import csv
import os
import sys

import numpy as np
from scipy.signal import savgol_filter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import MEAS_DIR  # noqa: E402
from thresholds import (  # noqa: E402
    ARM_LEN_THRESHOLD_PCT,
    DELTA_OMEGA_CAP,
    SWAP_RATIO_THRESHOLD,
)


SG_WINDOW = 7
SG_POLY   = 3


# ─────────────────────────────────────────────
# CLI / PATH RESOLUTION
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Compute ω and apply sanity checks; write verification.csv.")
    p.add_argument("csv", nargs="?", default=None,
                   help="path to tracking CSV (positional)")
    p.add_argument("--stem", default=None,
                   help="config_description; resolves CSV and out dir "
                        "from measurements/<stem>/")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="deg/s above which |ω| is flagged (default 2500)")
    p.add_argument("--no-plot", action="store_true",
                   help="skip the matplotlib plot")
    p.add_argument("--no-csv-out", action="store_true",
                   help="skip writing verification.csv")
    p.add_argument("--arm-len-threshold", type=float,
                   default=ARM_LEN_THRESHOLD_PCT,
                   help=f"arm-length deviation %% threshold "
                        f"(default {ARM_LEN_THRESHOLD_PCT})")
    p.add_argument("--delta-omega-cap", type=float, default=DELTA_OMEGA_CAP,
                   help=f"max |Δω| per frame (default {DELTA_OMEGA_CAP})")
    return p.parse_args()


def resolve_paths(args):
    """Return (csv_path, output_dir, stem_label)."""
    if args.stem:
        meas_dir = os.path.join(MEAS_DIR, args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            print(f"ERROR: tracking.csv not found for stem '{args.stem}'")
            print(f"  Expected: {csv_path}")
            sys.exit(1)
        return csv_path, meas_dir, args.stem
    if args.csv:
        csv_path = args.csv
        if not os.path.isabs(csv_path):
            csv_path = os.path.join(MEAS_DIR, csv_path)
        output_dir = os.path.dirname(csv_path)
        stem_label = os.path.basename(output_dir)
        return csv_path, output_dir, stem_label
    print("ERROR: provide --stem or a positional CSV path.")
    sys.exit(1)


# ─────────────────────────────────────────────
# ANGLE / ω HELPERS
# ─────────────────────────────────────────────

def smooth_omega(angles, dt):
    """ω = dθ/dt via Savitzky-Golay differentiation. NaN propagates
    through gaps. Input θ is unwrapped before differentiation to remove
    ±180° jumps; output ω is in deg/s."""
    a = np.asarray(angles, dtype=float)
    n = len(a)
    if n < SG_WINDOW:
        return np.full(n, np.nan)
    nan_mask = np.isnan(a)
    if nan_mask.all():
        return np.full(n, np.nan)
    a_filled = a.copy()
    idx = np.arange(n)
    if nan_mask.any():
        # Linear interpolation over NaNs so SG has a continuous input.
        a_filled[nan_mask] = np.interp(idx[nan_mask], idx[~nan_mask],
                                        a_filled[~nan_mask])
    # Unwrap to remove ±180° jumps before differentiation.
    a_unw_deg = np.degrees(np.unwrap(np.radians(a_filled)))
    om = savgol_filter(a_unw_deg, SG_WINDOW, SG_POLY,
                       deriv=1, delta=dt)
    om[nan_mask] = np.nan
    return om


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    csv_path, output_dir, stem = resolve_paths(args)

    print(f"verify_tracking.py")
    print(f"  CSV    : {csv_path}")
    print(f"  Folder : {output_dir}")
    print(f"  |ω| threshold: {args.omega_cap:.0f} deg/s")

    with open(csv_path, "r") as f:
        rows = list(csv.DictReader(f))

    n = len(rows)
    if n == 0:
        print("ERROR: empty tracking.csv")
        return 1

    def to_float_or_nan(x):
        return float(x) if x not in ("", None) else np.nan

    times = np.array([float(r["time_s"]) for r in rows])
    drops = np.array([int(r["dropout"])  for r in rows])
    phase = np.array([r["phase"]         for r in rows])
    th1   = np.array([to_float_or_nan(r["theta1_deg"]) for r in rows])
    th2   = np.array([to_float_or_nan(r["theta2_deg"]) for r in rows])
    x_g   = np.array([to_float_or_nan(r.get("x_green", "")) for r in rows])
    y_g   = np.array([to_float_or_nan(r.get("y_green", "")) for r in rows])
    x_r   = np.array([to_float_or_nan(r.get("x_red",   "")) for r in rows])
    y_r   = np.array([to_float_or_nan(r.get("y_red",   "")) for r in rows])

    diffs = np.diff(times)
    dt = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 1.0 / 60.0
    print(f"  median dt: {dt * 1000:.2f} ms  ({1.0 / dt:.2f} fps)")

    # ── ω via SG smoothing ───────────────────────────────────────────
    om1 = smooth_omega(th1, dt)
    om2 = smooth_omega(th2, dt)

    # ── Arm-length rigidity (green↔red pixel distance) ──────────────
    arm_len = np.sqrt((x_r - x_g) ** 2 + (y_r - y_g) ** 2)
    clean_mask = (drops == 0) & ~np.isnan(arm_len)
    arm_median = (float(np.nanmedian(arm_len[clean_mask]))
                  if clean_mask.any() else float("nan"))
    if not np.isnan(arm_median) and arm_median > 0:
        arm_dev_pct = np.abs(arm_len - arm_median) / arm_median * 100.0
    else:
        arm_dev_pct = np.full_like(arm_len, np.nan)
    arm_violation = (
        (arm_dev_pct > args.arm_len_threshold)
        & (drops == 0)
        & ~np.isnan(arm_dev_pct)
    )

    # ── ω-cap suspect (frame-by-frame physical ceiling) ─────────────
    omega_cap_suspect = (
        ((np.abs(om1) > args.omega_cap) | (np.abs(om2) > args.omega_cap))
        & (drops == 0)
        & ~np.isnan(om1) & ~np.isnan(om2)
    )

    # ── Δω spike (unphysical acceleration between adjacent clean frames)
    dom1 = np.full_like(om1, np.nan)
    dom2 = np.full_like(om2, np.nan)
    for i in range(1, n):
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om1[i]) and not np.isnan(om1[i - 1])):
            dom1[i] = abs(om1[i] - om1[i - 1])
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om2[i]) and not np.isnan(om2[i - 1])):
            dom2[i] = abs(om2[i] - om2[i - 1])
    accel_suspect = (
        ((dom1 > args.delta_omega_cap) | (dom2 > args.delta_omega_cap))
        & (drops == 0)
    )

    # ── Marker swap (green↔red cross-pair distance test) ────────────
    swap_suspect = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if drops[i] or drops[i - 1]:
            continue
        gx0, gy0 = x_g[i - 1], y_g[i - 1]
        gx1, gy1 = x_g[i],     y_g[i]
        rx0, ry0 = x_r[i - 1], y_r[i - 1]
        rx1, ry1 = x_r[i],     y_r[i]
        if any(np.isnan(v) for v in (gx0, gy0, gx1, gy1,
                                     rx0, ry0, rx1, ry1)):
            continue
        d_same  = (np.hypot(gx1 - gx0, gy1 - gy0)
                 + np.hypot(rx1 - rx0, ry1 - ry0))
        d_cross = (np.hypot(rx1 - gx0, ry1 - gy0)
                 + np.hypot(gx1 - rx0, gy1 - ry0))
        if d_same > 0 and (d_cross / d_same) < SWAP_RATIO_THRESHOLD:
            swap_suspect[i] = True

    # Combined suspect mask.
    suspect = omega_cap_suspect | accel_suspect | swap_suspect | arm_violation

    # ── Headline numbers ────────────────────────────────────────────
    n_drop      = int(np.sum(drops == 1))
    n_suspect   = int(np.sum(suspect))
    n_omega_cap = int(np.sum(omega_cap_suspect))
    n_accel     = int(np.sum(accel_suspect))
    n_swap      = int(np.sum(swap_suspect))
    n_arm       = int(np.sum(arm_violation))
    peak_o1     = float(np.nanmax(np.abs(om1))) if not np.isnan(om1).all() else 0.0
    peak_o2     = float(np.nanmax(np.abs(om2))) if not np.isnan(om2).all() else 0.0
    print()
    print(f"  total frames   {n}")
    print(f"  dropouts       {n_drop} ({100.0 * n_drop / n:.2f}%)")
    print(f"  peak |ω₁|      {peak_o1:.0f} °/s")
    print(f"  peak |ω₂|      {peak_o2:.0f} °/s")
    print(f"  median arm     {arm_median:.1f} px")
    print(f"  suspects       {n_suspect} ({100.0 * n_suspect / n:.2f}%)")
    print(f"    ω-cap        {n_omega_cap}")
    print(f"    Δω spike     {n_accel}")
    print(f"    marker swap  {n_swap}")
    print(f"    arm-length   {n_arm}")

    # ── Write verification.csv ──────────────────────────────────────
    if not args.no_csv_out:
        os.makedirs(output_dir, exist_ok=True)
        out_csv = os.path.join(output_dir, "verification.csv")
        with open(out_csv, "w", newline="") as f:
            fieldnames = list(rows[0].keys()) + [
                "omega1_deg_s", "omega2_deg_s",
                "suspect",
                "arm_length_px", "arm_dev_pct", "omega_cap_applied",
                "delta_omega_suspect", "swap_suspect", "omega_cap_suspect",
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
                out["omega_cap_applied"] = f"{args.omega_cap:.0f}"
                out["delta_omega_suspect"] = 1 if accel_suspect[i] else 0
                out["swap_suspect"]        = 1 if swap_suspect[i]  else 0
                out["omega_cap_suspect"]   = 1 if omega_cap_suspect[i] else 0
                w.writerow(out)
        print(f"\nWrote: {out_csv}")

    # ── Optional matplotlib plot ────────────────────────────────────
    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available — skipping plot")
            return 0
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
        axes[0].plot(times, th1, lw=0.6, label="θ1")
        axes[0].plot(times, th2, lw=0.6, label="θ2", alpha=0.7)
        if n_suspect > 0:
            mask = suspect & (drops == 0)
            axes[0].scatter(times[mask], th1[mask], s=6, c="red",
                            label="suspect", zorder=3)
        axes[0].set_ylabel("angle (deg)")
        axes[0].legend(loc="upper right", fontsize=8)
        axes[0].grid(alpha=0.3)
        axes[1].plot(times, om1, lw=0.5, label="ω1")
        axes[1].plot(times, om2, lw=0.5, label="ω2", alpha=0.7)
        axes[1].axhline( args.omega_cap, color="red", ls=":", lw=0.7)
        axes[1].axhline(-args.omega_cap, color="red", ls=":", lw=0.7,
                        label=f"±{args.omega_cap:.0f} °/s cap")
        axes[1].set_ylabel("ω (deg/s)")
        axes[1].set_xlabel("t (s)")
        axes[1].legend(loc="upper right", fontsize=8)
        axes[1].grid(alpha=0.3)
        plt.tight_layout()
        out_png = os.path.join(output_dir, "verification.png")
        plt.savefig(out_png, dpi=150)
        plt.close(fig)
        print(f"Wrote: {out_png}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
