#!/usr/bin/env python3
"""
dimension_sweep.py — attractor dimension (D₂, D_box) vs drive frequency.

Standalone fractal-dimension sweep for the fixed-voltage family — the
clean single-axis companion to the multi-panel chaos_sweep figure:

  D₂     correlation dimension (Grassberger–Procaccia) of the ω₂ embedding
  D_box  box-counting dimension of the (θ₂, ω₂) projection (≤ 2)

Reference levels: D = 1 (a limit cycle / closed loop) and D = 2 (a filled
surface; also the box-counting cap on a 2-D projection). A strange
attractor sits at fractional D between them.

Data sources:
  figures/aggregate/chaos_sweep_<V>V.csv   → f_drive, D₂, loops
  measurements/<stem>/dimension.json       → D_box

Points are coloured by regime via the lower-arm loop count: librating
(0 loops, periodic) vs circulating (> 0 loops).

Output:
  figures/aggregate/dimension_sweep_<V>V.png

Usage:
  python scripts/analysis/dimension_sweep.py
  python scripts/analysis/dimension_sweep.py --voltage 4.0
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
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from rich.console import Console

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir              # noqa: E402
from figures_paths import aggregate_path  # noqa: E402

console = Console()

LIBRATE = "#2563eb"   # 0 loops — periodic / librating
CIRCULATE = "#dc2626"  # > 0 loops — circulating / chaotic


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_sweep(path):
    """Read chaos_sweep CSV → list of dicts {stem, f, D2, loops}."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({
                "stem":  r["stem"],
                "f":     _f(r.get("f_drive_hz")),
                "D2":    _f(r.get("D2")),
                "loops": _f(r.get("loops")),
            })
    return out


def read_dbox(stem):
    """D_box from a clip's dimension.json, or NaN."""
    path = os.path.join(clip_dir(stem), "dimension.json")
    if not os.path.exists(path):
        return np.nan
    try:
        with open(path, encoding="utf-8") as f:
            return _f(json.load(f).get("D_box"))
    except (ValueError, OSError):
        return np.nan


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2,
                   help="fixed drive voltage of the sweep (default 3.2 V).")
    args = p.parse_args()

    csv_path = aggregate_path(f"chaos_sweep_{args.voltage:g}V.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"{csv_path} not found — run chaos_sweep.py first.")

    rows = load_sweep(csv_path)
    for r in rows:
        r["D_box"] = read_dbox(r["stem"])
    rows = [r for r in rows if np.isfinite(r["f"])]
    rows.sort(key=lambda r: r["f"])
    if not rows:
        raise SystemExit("no clips with a finite f_drive in the sweep CSV.")

    f = np.array([r["f"] for r in rows])
    d2 = np.array([r["D2"] for r in rows])
    dbox = np.array([r["D_box"] for r in rows])
    loops = np.array([r["loops"] for r in rows])
    # regime colour per point (loops == 0 → librating, > 0 → circulating)
    pt_color = np.where((loops > 0), CIRCULATE, LIBRATE)

    fig, ax = plt.subplots(figsize=(11, 6))

    # faint connectors (sorted by f) to read the trend
    m2 = np.isfinite(d2)
    mb = np.isfinite(dbox)
    if m2.any():
        ax.plot(f[m2], d2[m2], "-", color="0.75", lw=0.8, zorder=1)
    if mb.any():
        ax.plot(f[mb], dbox[mb], "--", color="0.8", lw=0.8, zorder=1)

    # D₂ as circles, D_box as triangles; both coloured by regime
    ax.scatter(f[m2], d2[m2], marker="o", s=55, c=pt_color[m2], zorder=3,
               edgecolors="k", linewidths=0.4)
    ax.scatter(f[mb], dbox[mb], marker="^", s=55, c=pt_color[mb], zorder=3,
               edgecolors="k", linewidths=0.4, alpha=0.85)

    # reference dimension levels
    ax.axhline(1.0, ls=":", color="k", lw=1.0)
    ax.axhline(2.0, ls=":", color="k", lw=1.0)
    xr = ax.get_xlim()[1]
    ax.text(xr, 1.02, "D = 1  limit cycle", ha="right", va="bottom",
            fontsize=8, color="0.3")
    ax.text(xr, 2.02, "D = 2  surface", ha="right", va="bottom",
            fontsize=8, color="0.3")

    ax.set_xlabel("drive frequency  f_drive  (Hz)")
    ax.set_ylabel("attractor dimension")
    n_circ = int(np.sum(loops > 0))
    ax.set_title(
        f"Attractor dimension vs drive frequency — {args.voltage:g} V   "
        f"({len(rows)} clips, {n_circ} circulating)")
    ax.grid(True, alpha=0.3)

    legend_handles = [
        Line2D([0], [0], marker="o", color="0.4", ls="", ms=8,
               markeredgecolor="k", label="D₂  (correlation)"),
        Line2D([0], [0], marker="^", color="0.4", ls="", ms=8,
               markeredgecolor="k", label="D_box  (box-count)"),
        Patch(facecolor=LIBRATE, edgecolor="k", label="librating  (0 loops)"),
        Patch(facecolor=CIRCULATE, edgecolor="k", label="circulating  (>0 loops)"),
    ]
    ax.legend(handles=legend_handles, loc="best", fontsize=9, framealpha=0.9)

    out = aggregate_path(f"dimension_sweep_{args.voltage:g}V.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    console.print(f"  [green]{len(rows)}[/] clips "
                  f"[dim](D₂ {int(m2.sum())}, D_box {int(mb.sum())})[/] → [dim]{out}[/]")


if __name__ == "__main__":
    main()
