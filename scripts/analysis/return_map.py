#!/usr/bin/env python3
"""
return_map.py — stroboscopic first-return map for a driven double pendulum.

Samples θ₁ and θ₂ once per drive period T = 1/f_drive (skipping the initial
transient) and plots the first-return map  θ(nT) vs θ((n+1)T):

  period-1 lock  → a single fixed point on the diagonal
  period-2       → a 2-cycle (two points, off the diagonal)
  chaos          → points trace out a 1-D curve (the attractor's return map)

This is the driven-system analogue of a 1-D Poincaré return map. Unlike the
successive-sample return panel in phase_panels.py, the sampling here is
drive-synchronised (one point per forcing period), which is the correct
return map for a periodically driven oscillator.

Output:
  figures/return_map/<stem>_return_map.png   (2-panel: θ₁, θ₂)
  measurements/<stem>/return_map.csv

Usage:
  python scripts/analysis/return_map.py --stem 3.2V_1.20Hz
  python scripts/analysis/return_map.py --stem 3.2V_0.91Hz --transient 8
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

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import EXPERIMENTS, clip_dir            # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402
from driven_helpers import (parse_stem, load_driven_csv,  # noqa: E402
                            strobe_sample)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True, help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start (default 5).")
    p.add_argument("--f-drive", type=float, default=None,
                   help="override drive frequency (Hz); default from "
                        "experiments.json, then the stem name.")
    p.add_argument("--no-csv", action="store_true")
    return p.parse_args()


def resolve_f_drive(stem, override):
    if override is not None:
        return override, "override"
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, encoding="utf-8") as f:
            exp = json.load(f)
        if stem in exp and "drive_freq_hz" in exp[stem]:
            return float(exp[stem]["drive_freq_hz"]), "experiments.json"
    return parse_stem(stem)["f_drive_hz"], "stem name"


def make_figure(t_s, th1_s, th2_s, stem, f_drive, transient_s, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.6))
    n_pts = len(th1_s) - 1
    for ax, ang, lab in ((axes[0], th1_s, r"$\theta_1$"),
                         (axes[1], th2_s, r"$\theta_2$")):
        xn, xnp1 = ang[:-1], ang[1:]
        sc = ax.scatter(xn, xnp1, c=t_s[:n_pts], cmap=plt.cm.viridis,
                        s=26, alpha=0.85, edgecolors="k", linewidths=0.3)
        plt.colorbar(sc, ax=ax, label="t (s)", shrink=0.85)
        lo = float(min(xn.min(), xnp1.min()))
        hi = float(max(xn.max(), xnp1.max()))
        pad = 0.05 * (hi - lo) if hi > lo else 1.0
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad],
                color="gray", lw=0.9, ls="--", zorder=0, label="y = x")
        ax.set_xlabel(f"{lab}(nT)  (deg)")
        ax.set_ylabel(f"{lab}((n+1)T)  (deg)")
        ax.set_title(f"{lab} stroboscopic return map")
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="datalim")
        ax.legend(loc="upper left", fontsize=8)

    fig.suptitle(
        f"Stroboscopic return map — {stem}   "
        f"(f_drive = {f_drive:.3f} Hz, T = {1/f_drive:.3f} s, "
        f"transient = {transient_s:.1f} s, n = {len(th1_s)} strobes)",
        fontsize=12, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    mirror_to_ready(out_path)
    plt.close(fig)


def main():
    args = parse_args()
    stem = args.stem
    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    f_drive, src = resolve_f_drive(stem, args.f_drive)
    t, th1, th2, om1, om2 = load_driven_csv(csv_path)

    # Strobe both arms at the SAME sample times t = n/f_drive. strobe_sample
    # samples one (angle, velocity) pair; call it per arm — both share the
    # n0..n1 strobe grid, so th1_s[i] and th2_s[i] are the same period i.
    t_s, th1_s, _ = strobe_sample(t, th1, om1, f_drive, transient_s=args.transient)
    _,   th2_s, _ = strobe_sample(t, th2, om2, f_drive, transient_s=args.transient)

    if len(t_s) < 2:
        raise SystemExit(
            f"only {len(t_s)} strobe sample(s) — window too short for a return map.")

    info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    info.add_column(style="dim", min_width=18)
    info.add_column(style="white", justify="right")
    info.add_row("stem", f"[cyan]{stem}[/]")
    info.add_row("f_drive", f"{f_drive:.4f} Hz  [dim]({src})[/]")
    info.add_row("T", f"{1/f_drive:.4f} s")
    info.add_row("strobe samples", f"{len(t_s)}  [dim](skip {args.transient:.1f} s)[/]")
    info.add_row("return points", f"{len(t_s) - 1}")
    console.print(info)

    if not args.no_csv:
        out_csv = os.path.join(clip_dir(stem), "return_map.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["n", "t_s", "theta1_n", "theta1_np1",
                        "theta2_n", "theta2_np1"])
            for i in range(len(t_s) - 1):
                w.writerow([i, f"{t_s[i]:.4f}",
                            f"{th1_s[i]:.4f}", f"{th1_s[i+1]:.4f}",
                            f"{th2_s[i]:.4f}", f"{th2_s[i+1]:.4f}"])
        console.print(f"  [dim]Saved → {out_csv}[/]")

    out_png = figure_path("return_map", stem)
    make_figure(t_s, th1_s, th2_s, stem, f_drive, args.transient, out_png)
    console.print(f"  [dim]Saved → {out_png}[/]")


if __name__ == "__main__":
    main()
