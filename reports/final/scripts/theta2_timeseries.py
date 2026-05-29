#!/usr/bin/env python3
"""
theta2_timeseries.py — final-report θ₂(t) figure (low / mid / high frequency).

Report variant of scripts/analysis/theta2_timeseries.py. Two deliberate
changes from the repo primitive, both for cross-figure homogeneity:

  1. Time slice — instead of the whole clip from t=0, we show only the
     LAST ``--window`` seconds (default 10 s), anchored at the end of the
     recording, re-zeroed to a 0–window axis. This is the same steady-state
     slice every report figure uses (report_common.tail_window), so the FFT
     waterfall, the phase portraits and this trace all describe the same
     part of each clip — after transients have died.
  2. Wrapped angle — θ₂ is shown wrapped in [-180, 180]° (the ±180 wrap is
     masked, not drawn as a vertical streak), rather than the cumulative
     unwrapped staircase.

The figure is a single column of three stacked panels — the lowest drive
frequency, the middle of the sweep, and the highest — chosen automatically
(report_common.select_low_mid_high) or pinned with --stems. Each panel is
coloured by regime (green regular / red chaotic, from D2) so the
beginning→middle→end progression reads as regular → chaotic → regular.

Usage
~~~~~
  python reports/final/scripts/theta2_timeseries.py
  python reports/final/scripts/theta2_timeseries.py --window 10
  python reports/final/scripts/theta2_timeseries.py --stems 3.2V_0.91Hz,3.2V_1.19Hz,3.2V_1.34Hz

Output
~~~~~~
  reports/final/figures/theta2_timeseries.png
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
    select_low_mid_high, load_metrics, classify,
)


def parse_args():
    p = argparse.ArgumentParser(description="Report θ₂(t) low/mid/high figure.")
    p.add_argument("--stems", default=None,
                   help="comma-separated stems (low,mid,high). Default: "
                        "auto-select lowest / median / highest drive freq.")
    p.add_argument("--window", type=float, default=TIME_WINDOW_S,
                   help=f"tail window length in seconds (default {TIME_WINDOW_S:g})")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "theta2_timeseries.png"),
                   help="output png path")
    return p.parse_args()


def load_theta2(stem):
    """(t, theta2_deg) for the driven segment of a clip, t re-zeroed to 0."""
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


def mask_wraps(y, thresh=180.0):
    """Break the line (NaN) wherever |dy| > thresh so the ±180 wrap is not
    drawn as a vertical streak. Returns a copy."""
    y = y.astype(float).copy()
    jumps = np.where(np.abs(np.diff(y)) > thresh)[0]
    y[jumps] = np.nan
    return y


def draw_panel(ax, stem, meta, window_s, show_xlabel):
    t, th = load_theta2(stem)
    t, th = tail_window(t, th, window_s=window_s)   # last window_s s, re-zeroed
    regime, col = classify(meta)
    freq = stem_freq(stem)

    ax.plot(t, mask_wraps(th), lw=0.8, color=col, solid_capstyle="round")
    ax.set_xlim(0, window_s)
    ax.set_ylim(-188, 188)
    ax.set_yticks([-180, -90, 0, 90, 180])
    ax.grid(True, alpha=0.25)
    ax.set_ylabel(r"$\theta_2$ (deg)")
    ax.set_title(f"{freq:g} Hz   {regime}", loc="left", color=col,
                 fontsize=11, fontweight="bold", pad=3)
    if show_xlabel:
        ax.set_xlabel("time (s)")
    else:
        ax.tick_params(labelbottom=False)
    return regime


def main():
    args = parse_args()
    if args.stems:
        stems = [s.strip() for s in args.stems.split(",")]
        if len(stems) != 3:
            raise SystemExit("--stems needs exactly three comma-separated stems")
    else:
        stems = select_low_mid_high()

    metrics = load_metrics()

    fig, axes = plt.subplots(3, 1, figsize=(9, 7.2), dpi=150,
                             sharex=True, constrained_layout=True)
    labels = ["low", "mid", "high"]
    print(f"θ₂(t)  —  last {args.window:g} s, wrapped:")
    for i, (ax, stem) in enumerate(zip(axes, stems)):
        regime = draw_panel(ax, stem, metrics.get(stem), args.window,
                            show_xlabel=(i == len(stems) - 1))
        print(f"  [{labels[i]:>4}] {stem:<16} {stem_freq(stem):g} Hz  [{regime}]")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"->  {args.out}")


if __name__ == "__main__":
    main()
