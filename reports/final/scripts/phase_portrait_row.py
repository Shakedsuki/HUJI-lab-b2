#!/usr/bin/env python3
"""
phase_portrait_row.py — final-report arm-2 phase-portrait row.

A single row of θ₂–ω₂ phase portraits (arm 2 only, red), one per measurement,
left→right across the drive-frequency sweep — so the route to chaos reads as a
strip: a thin limit-cycle loop (periodic) → folded/doubled loops → a filled
band (chaotic) → back to a loop.

Conventions shared with the rest of the report (report_common):
  - steady-state slice: the last ``--window`` seconds of each clip
    (tail_window), so every portrait describes the same post-transient regime;
  - ω₂ is the SG-smoothed derivative (kinematics.angular_velocity), the single
    source of truth, so no raw-gradient jitter inflates the cloud.

Axes are shared across the row (fixed θ₂ ∈ [-185,185]°, symmetric ω₂ to the
row-wide robust max) so the reader compares attractor SIZE/shape directly; the
leftmost tile carries the ω₂ label, every tile carries the θ₂ label.

Usage
~~~~~
  python reports/final/scripts/phase_portrait_row.py
  python reports/final/scripts/phase_portrait_row.py --n 5
  python reports/final/scripts/phase_portrait_row.py --stems 3.2V_0.9Hz,3.2V_1.0Hz,3.2V_1.19Hz,3.2V_1.28Hz,3.2V_1.34Hz
  python reports/final/scripts/phase_portrait_row.py --window 10

Output
~~~~~~
  reports/final/figures/phase_portrait_row.png
"""

import argparse
import csv
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

from report_common import (
    FIGURES_DIR, TIME_WINDOW_S, clip_dir, tail_window, stem_freq,
    select_evenly, load_metrics, classify,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "scripts", "utils"))
from kinematics import angular_velocity   # noqa: E402

COLOR_ARM2 = "#c0392b"   # arm-2 red (repo convention)


def parse_args():
    p = argparse.ArgumentParser(description="Report arm-2 phase-portrait row.")
    p.add_argument("--n", type=int, default=5,
                   help="number of subplots / clips (default 5)")
    p.add_argument("--stems", default=None,
                   help="comma-separated stems (overrides --n auto-selection)")
    p.add_argument("--window", type=float, default=TIME_WINDOW_S,
                   help=f"steady-state tail window in seconds (default {TIME_WINDOW_S:g})")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "phase_portrait_row.png"),
                   help="output png path")
    return p.parse_args()


def load_theta2(stem):
    """(t, θ₂) for the driven segment, t re-zeroed to 0."""
    path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    t, th = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                t.append(float(r["time_s"]))
                th.append(float(r["theta2_deg"]))
            except (KeyError, ValueError):
                continue
    if not t:
        raise ValueError(f"no usable rows in {path}")
    t = np.asarray(t, dtype=float)
    return t - t[0], np.asarray(th, dtype=float)


def main():
    args = parse_args()
    if args.stems:
        stems = [s.strip() for s in args.stems.split(",") if s.strip()]
    else:
        stems = select_evenly(args.n)

    metrics = load_metrics()

    # Load all clips first so we can set a common ω₂ scale across the row.
    series = []
    om_max = 0.0
    for stem in stems:
        t, th2 = load_theta2(stem)
        om2 = angular_velocity(th2, t)               # SG-smoothed dθ₂/dt
        t, th2, om2 = tail_window(t, th2, om2, window_s=args.window)
        series.append((stem, th2, om2))
        if om2.size:
            om_max = max(om_max, np.percentile(np.abs(om2), 99.5))
    om_lim = float(np.ceil(om_max / 100.0) * 100.0)   # round up to a tidy limit

    n = len(series)
    fig, axes = plt.subplots(1, n, figsize=(3.1 * n, 3.4), dpi=150,
                             sharex=True, sharey=True, constrained_layout=True)
    if n == 1:
        axes = [axes]

    print(f"arm-2 phase portraits  —  last {args.window:g} s, ω₂ ∈ ±{om_lim:.0f} deg/s:")
    for ax, (stem, th2, om2) in zip(axes, series):
        regime, _ = classify(metrics.get(stem))
        ax.scatter(th2, om2, s=2, alpha=0.5, linewidths=0, color=COLOR_ARM2)
        ax.axhline(0, color="0.85", lw=0.5, zorder=0)
        ax.axvline(0, color="0.85", lw=0.5, zorder=0)
        ax.set_xlim(-185, 185)
        ax.set_ylim(-om_lim, om_lim)
        ax.set_xticks([-180, -90, 0, 90, 180])
        ax.grid(True, alpha=0.2)
        ax.set_xlabel(r"$\theta_2$ (deg)")
        ax.set_title(f"{stem_freq(stem):g} Hz", fontsize=11, fontweight="bold")
        print(f"  {stem:<16} {stem_freq(stem):g} Hz  [{regime}]")
    axes[0].set_ylabel(r"$\omega_2$ (deg/s)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"->  {args.out}")


if __name__ == "__main__":
    main()
