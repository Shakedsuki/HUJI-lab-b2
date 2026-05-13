"""
driven_bifurcation.py
---------------------
Bifurcation diagram for the motor-driven double pendulum.

For each tracked clip in a 1D parameter sweep, compute the stroboscopic
Poincare map (samples once per drive period) and scatter the theta1
values at that clip's parameter coordinate on the x-axis.

  - Period-1 regime  -> single dot per clip.
  - Period-2 regime  -> two dots.
  - Quasiperiodic    -> dense arc.
  - Chaos            -> vertical cloud.

Two sweep modes
~~~~~~~~~~~~~~~
  --sweep vd            sweep voltage at fixed drive frequency
                        (default fixed-fd = 1.0 Hz)
  --sweep fd            sweep drive frequency at fixed voltage
                        (default fixed-vd = 3.0 V)

Usage
~~~~~
  python scripts/analysis/driven_bifurcation.py --sweep vd
  python scripts/analysis/driven_bifurcation.py --sweep fd --fixed-vd 3.0
  python scripts/analysis/driven_bifurcation.py --sweep vd --fixed-fd 1.0 \
      --transient 8 --tolerance 0.05

Output
~~~~~~
  figures/aggregate/driven_bifurcation_<sweep>_fixed_<param>.png
  data/driven_bifurcation_<sweep>_fixed_<param>.csv
      columns: stem, x_param, theta1_deg, omega1_deg_s
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

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, EXPERIMENTS  # noqa: E402
from figures_paths import aggregate_path  # noqa: E402
from driven_helpers import (load_driven_csv, strobe_sample,  # noqa: E402
                            list_tracked_clips)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sweep", choices=["vd", "fd"], default="vd",
                   help="Which axis to sweep on x (default: vd).")
    p.add_argument("--fixed-fd", type=float, default=1.0,
                   help="Drive frequency to hold fixed when --sweep vd (Hz).")
    p.add_argument("--fixed-vd", type=float, default=3.0,
                   help="Drive voltage to hold fixed when --sweep fd (V).")
    p.add_argument("--tolerance", type=float, default=0.05,
                   help="Match tolerance for the fixed parameter "
                        "(default: 0.05 — allows 1.0 +/- 0.05 Hz, etc.).")
    p.add_argument("--transient", type=float, default=5.0,
                   help="Seconds to skip at start of each clip (default: 5).")
    p.add_argument("--min-clips", type=int, default=3,
                   help="Refuse to plot fewer than this many matched clips.")
    return p.parse_args()


def select_clips(experiments, args):
    """Filter tracked clips to those matching the sweep configuration.

    Returns a list of (stem, entry, x_value) tuples where x_value is
    the value of the sweep parameter for that clip.
    """
    all_tracked = list_tracked_clips(experiments, MEAS_DIR)
    matched = []
    for stem, entry in all_tracked:
        vd = entry.get("drive_voltage_v")
        fd = entry.get("drive_freq_hz")
        if vd is None or fd is None:
            continue
        if args.sweep == "vd":
            if abs(fd - args.fixed_fd) > args.tolerance:
                continue
            matched.append((stem, entry, vd))
        else:  # sweep == "fd"
            if abs(vd - args.fixed_vd) > args.tolerance:
                continue
            matched.append((stem, entry, fd))
    matched.sort(key=lambda t: t[2])
    return matched


def collect_strobe_points(matched, transient_s):
    """For each matched clip, load the CSV, run the stroboscopic
    sampler, and return per-clip (x_value, theta1_array, omega1_array)
    tuples plus the flat aggregate arrays for writing to CSV."""
    per_clip = []
    flat_rows = []  # (stem, x, th1, om1)
    for stem, entry, x_val in matched:
        csv_path = os.path.join(MEAS_DIR, stem, "verification.csv")
        try:
            t, th1, _, om1, _ = load_driven_csv(csv_path)
        except SystemExit as e:
            print(f"  skip {stem}: {e}")
            continue
        fd = entry["drive_freq_hz"]
        ts, ths, oms = strobe_sample(t, th1, om1, fd, transient_s=transient_s)
        if len(ts) == 0:
            print(f"  skip {stem}: no strobe points (window too short).")
            continue
        per_clip.append((stem, x_val, ths, oms))
        for th, om in zip(ths, oms):
            flat_rows.append((stem, x_val, float(th), float(om)))
        print(f"  {stem:15s}  x={x_val:.3f}   n_strobe={len(ts)}")
    return per_clip, flat_rows


def make_figure(per_clip, args, out_path):
    """Two-panel bifurcation figure: theta1 (top), omega1 (bottom)."""
    if args.sweep == "vd":
        xlabel = "Drive voltage  V_drill  (V)"
        fixed_label = f"f_drive = {args.fixed_fd:.2f} Hz"
    else:
        xlabel = "Drive frequency  f_drive  (Hz)"
        fixed_label = f"V_drill = {args.fixed_vd:.2f} V"

    n_clips = len(per_clip)
    total_pts = sum(len(c[2]) for c in per_clip)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), sharex=True,
                                   gridspec_kw={"hspace": 0.08})

    # Slight horizontal jitter so identical x values do not overlap
    # vertically into a single dot; jitter is < 0.5% of the x-axis span.
    xs = np.array([c[1] for c in per_clip])
    if len(xs) > 1:
        jitter_scale = (xs.max() - xs.min()) * 0.002
    else:
        jitter_scale = 0.0

    rng = np.random.default_rng(seed=0)
    for stem, x_val, ths, oms in per_clip:
        n = len(ths)
        jx = x_val + rng.uniform(-jitter_scale, jitter_scale, size=n) if jitter_scale else np.full(n, x_val)
        ax1.scatter(jx, ths, s=8, alpha=0.55, color="tab:blue",
                    edgecolors="none", rasterized=True)
        ax2.scatter(jx, oms, s=8, alpha=0.55, color="tab:purple",
                    edgecolors="none", rasterized=True)

    # Clip-position guide rugs along the bottom.
    for x_val in xs:
        ax2.axvline(x_val, color="k", lw=0.3, alpha=0.15, zorder=0)
        ax1.axvline(x_val, color="k", lw=0.3, alpha=0.15, zorder=0)

    ax1.set_ylabel(r"$\theta_1$ at strobe  (deg)")
    ax2.set_ylabel(r"$\omega_1$ at strobe  (deg/s)")
    ax2.set_xlabel(xlabel)
    ax1.grid(True, alpha=0.3)
    ax2.grid(True, alpha=0.3)
    ax1.set_title(
        f"Bifurcation diagram — {fixed_label}   "
        f"({n_clips} clips, {total_pts} strobe points, "
        f"transient = {args.transient:.0f}s)",
        fontsize=12)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    if not os.path.exists(EXPERIMENTS):
        raise SystemExit(f"experiments.json not found at {EXPERIMENTS}")
    with open(EXPERIMENTS, encoding="utf-8") as f:
        experiments = json.load(f)

    matched = select_clips(experiments, args)
    if args.sweep == "vd":
        tag = f"vd_at_fd_{args.fixed_fd:g}Hz"
    else:
        tag = f"fd_at_vd_{args.fixed_vd:g}V"

    print(f"Sweep: {args.sweep}  ({tag})")
    print(f"Matched {len(matched)} tracked clips:")
    for stem, _, x in matched:
        print(f"  {stem:15s}  x={x:.3f}")

    if len(matched) < args.min_clips:
        raise SystemExit(
            f"Only {len(matched)} matched clips (< --min-clips={args.min_clips}).")

    per_clip, flat_rows = collect_strobe_points(matched, args.transient)
    if not per_clip:
        raise SystemExit("No strobe points collected — aborting.")

    out_csv = os.path.join(DATA_DIR, f"driven_bifurcation_{tag}.csv")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stem", "x_param", "theta1_deg", "omega1_deg_s"])
        for row in flat_rows:
            w.writerow([row[0], f"{row[1]:.4f}",
                        f"{row[2]:.4f}", f"{row[3]:.4f}"])
    print(f"Wrote {out_csv}")

    out_png = aggregate_path(f"driven_bifurcation_{tag}.png")
    make_figure(per_clip, args, out_png)
    print(f"Wrote {out_png}")


if __name__ == "__main__":
    main()
