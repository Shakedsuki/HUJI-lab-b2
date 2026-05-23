#!/usr/bin/env python3
"""
winding_sweep.py — winding number (f_response / f_drive) vs drive frequency.

The winding number  w = f_response / f_drive  of the UPPER arm across the
fixed-voltage sweep. In a driven nonlinear oscillator, phase-locked
(Arnold-tongue) windows pin w to a rational p/q and show up as flat
plateaus; between them w drifts or the motion goes chaotic — the
devil's-staircase signature of mode locking.

  freq_ratio   read from resonance_<V>V.csv
  loops        lower-arm turn count from chaos_sweep_<V>V.csv (point colour)

Dashed guides mark low-order rationals (1/2, 2/3, 1/1, 3/2, 2/1, …) so
plateaus that sit on a rational are easy to spot.

Output:
  figures/aggregate/winding_sweep_<V>V.png

Usage:
  python scripts/analysis/winding_sweep.py
  python scripts/analysis/winding_sweep.py --voltage 4.0
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

from rich.console import Console

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from figures_paths import aggregate_path  # noqa: E402

console = Console()

# Low-order rationals to mark as locking guides.
RATIONALS = [(1, 3), (1, 2), (2, 3), (1, 1), (3, 2), (2, 1), (5, 2), (3, 1)]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_resonance(path):
    """stem → (f_drive, freq_ratio)."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["stem"]] = (_f(r.get("f_drive_hz")), _f(r.get("freq_ratio")))
    return out


def load_loops(path):
    """stem → loops (lower-arm turn count)."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["stem"]] = _f(r.get("loops"))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2,
                   help="fixed drive voltage of the sweep (default 3.2 V).")
    args = p.parse_args()

    res_path = aggregate_path(f"resonance_{args.voltage:g}V.csv")
    if not os.path.exists(res_path):
        raise SystemExit(f"{res_path} not found — run the resonance analysis first.")
    res = load_resonance(res_path)
    loops = load_loops(aggregate_path(f"chaos_sweep_{args.voltage:g}V.csv"))

    rows = []
    for stem, (fd, ratio) in res.items():
        if np.isfinite(fd) and np.isfinite(ratio):
            rows.append((fd, ratio, loops.get(stem, np.nan)))
    if not rows:
        raise SystemExit("no finite (f_drive, freq_ratio) rows in the resonance CSV.")
    rows.sort(key=lambda r: r[0])
    f = np.array([r[0] for r in rows])
    w = np.array([r[1] for r in rows])
    lp = np.array([r[2] for r in rows])
    lp_plot = np.where(np.isfinite(lp), lp, 0.0)

    fig, ax = plt.subplots(figsize=(11, 6))

    # rational locking guides within the data's y-range (+ margin)
    ymin, ymax = float(np.min(w)), float(np.max(w))
    lo, hi = ymin - 0.15, ymax + 0.15
    xmax = float(np.max(f))
    for pq in RATIONALS:
        val = pq[0] / pq[1]
        if lo <= val <= hi:
            ax.axhline(val, ls="--", color="0.7", lw=0.8, zorder=0)
            ax.text(xmax, val, f" {pq[0]}/{pq[1]}", va="center", ha="left",
                    fontsize=8, color="0.4")

    ax.plot(f, w, "-", color="0.8", lw=0.7, zorder=1)
    sc = ax.scatter(f, w, c=lp_plot, cmap="plasma", s=55, zorder=3,
                    edgecolors="k", linewidths=0.4)
    cb = fig.colorbar(sc, ax=ax, shrink=0.85)
    cb.set_label("lower-arm loops")

    ax.set_xlabel("drive frequency  f_drive  (Hz)")
    ax.set_ylabel(r"winding number  $w = f_{\mathrm{resp}} / f_{\mathrm{drive}}$")
    ax.set_title(
        f"Winding number vs drive frequency — {args.voltage:g} V   "
        f"({len(rows)} clips)")
    ax.grid(True, alpha=0.3)
    ax.margins(x=0.04)

    out = aggregate_path(f"winding_sweep_{args.voltage:g}V.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    n_locked = int(np.sum(np.abs(w - 1.0) < 0.05))
    console.print(f"  [green]{len(rows)}[/] clips "
                  f"[dim]({n_locked} near 1:1 lock)[/] → [dim]{out}[/]")


if __name__ == "__main__":
    main()
