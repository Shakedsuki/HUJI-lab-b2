#!/usr/bin/env python3
"""
theta2_timeseries_sweep.py — run the theta2(t) primitive across a whole
voltage family: one standalone figure per clip, plus a single aggregate that
tiles every clip (frequency-ordered) so the regular -> chaotic -> regular
transition reads at a glance.

Reuses render_clip + draw_theta2 from theta2_timeseries, so the per-clip
figures and the aggregate tiles are identical to the locked primitive (the
tiles are the compact form of the same draw).

Usage
~~~~~
  python scripts/analysis/theta2_timeseries_sweep.py
  python scripts/analysis/theta2_timeseries_sweep.py --family 3.2V --ncols 3
  python scripts/analysis/theta2_timeseries_sweep.py --no-individual

Output
~~~~~~
  figures/theta2_timeseries/<stem>_theta2_timeseries_cumulative.png   (per clip)
  figures/aggregate/theta2_timeseries_<family>.png                    (grid)
"""

import argparse
import math
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
sys.path.insert(0, _HERE)
from figures_paths import aggregate_path                              # noqa: E402
from theta2_timeseries import (load_theta2, load_metrics, stem_freq,  # noqa: E402
                               family_label, draw_theta2, render_clip)


def parse_args():
    p = argparse.ArgumentParser(description="theta2(t) per-clip + aggregate sweep.")
    p.add_argument("--family", default="3.2V",
                   help="voltage prefix to sweep (default 3.2V)")
    p.add_argument("--ncols", type=int, default=3,
                   help="columns in the aggregate grid (default 3)")
    p.add_argument("--no-individual", action="store_true",
                   help="build only the aggregate, skip per-clip figures")
    return p.parse_args()


def main():
    args = parse_args()
    metrics = load_metrics()
    stems = sorted([s for s in metrics if s.startswith(args.family)],
                   key=stem_freq)
    if not stems:
        raise SystemExit(f"no clips found for family {args.family!r}")
    print(f"{len(stems)} clips: {stems[0]} ... {stems[-1]}")

    # ── per-clip standalone primitives ────────────────────────────────────
    if not args.no_individual:
        for stem in stems:
            regime, _ = render_clip(stem, meta=metrics.get(stem))
            print(f"  {stem:18s} [{regime}]")

    # ── aggregate grid (frequency-ordered, compact tiles) ─────────────────
    n = len(stems)
    ncols = max(1, args.ncols)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.3 * ncols, 1.15 * nrows + 0.7), dpi=150,
        sharey=True, constrained_layout=True)
    axes = np.atleast_1d(axes).ravel()

    for k, stem in enumerate(stems):
        t, th = load_theta2(stem)
        draw_theta2(axes[k], stem, t, th, metrics.get(stem),
                    unwrap=True, compact=True, units="deg", mark_loops=False)
    for k in range(n, len(axes)):
        axes[k].axis("off")

    fig.suptitle(rf"$\theta_2(t)$ cumulative (deg) — {args.family} frequency "
                 r"sweep   (green = regular, red = chaotic)", fontsize=13)
    out = aggregate_path(f"theta2_timeseries_{args.family}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"aggregate -> {out}")


if __name__ == "__main__":
    main()
