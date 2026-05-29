#!/usr/bin/env python3
"""
attractor.py — reconstructed 3-D attractor (delay embedding of ω₂).

Takens delay embedding

    x(t) = [ ω₂(t), ω₂(t+τ), ω₂(t+2τ) ]

of the lower-arm angular velocity, rendered as a time-coloured 3-D point
cloud. A phase-locked / periodic orbit traces a thin closed loop; a strange
attractor fills a fractal volume that never quite closes.

ω₂ (the derivative of the unwrapped lower-arm angle) is stationary even when
the arm circulates, so the reconstruction stays bounded. τ is reused from
each clip's dimension.json (delay_tau) when present — the same delay used for
the correlation dimension — else τ = 11. The embedding dimension reported in
the title comes from dimension.json; the visualisation always uses 3 delay
coordinates so it can be drawn.

Output:
  figures/attractor/<stem>_attractor.png

Usage:
  python scripts/analysis/attractor.py --stem 3.2V_1.20Hz
  python scripts/analysis/attractor.py --stem 3.2V_0.91Hz --azim 60 --elev 20
"""

import argparse
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
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3d projection)

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
sys.path.insert(0, _HERE)
from paths import clip_dir                          # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402
from dimension import load_clip, embed              # noqa: E402
from kinematics import angular_velocity             # noqa: E402

DEFAULT_M = 5
DEFAULT_TAU = 11


def read_embed_params(stem, tau_arg):
    """(m, τ, source) — m for the title, τ for the embedding. CLI τ wins,
    then dimension.json, then defaults."""
    m, tau, src = DEFAULT_M, DEFAULT_TAU, "defaults"
    path = os.path.join(clip_dir(stem), "dimension.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            m = int(d.get("embedding_m", m))
            tau = int(d.get("delay_tau", tau))
            src = "dimension.json"
        except (ValueError, OSError):
            pass
    if tau_arg is not None:
        tau = tau_arg
        src = "cli"
    return m, tau, src


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True, help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start (default 5).")
    p.add_argument("--tau", type=int, default=None, help="delay in frames (override).")
    p.add_argument("--elev", type=float, default=25.0, help="3-D elevation angle.")
    p.add_argument("--azim", type=float, default=45.0, help="3-D azimuth angle.")
    args = p.parse_args()
    stem = args.stem

    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    t, th2 = load_clip(csv_path)
    keep = t >= (t[0] + args.transient)
    if keep.sum() > 200:
        t, th2 = t[keep], th2[keep]

    om2 = angular_velocity(th2, t)   # SG-smoothed dθ₂/dt — see kinematics.py

    m, tau, src = read_embed_params(stem, args.tau)
    X = embed(om2, 3, tau)            # 3 delay coords for the 3-D render
    N = len(X)
    if N < 20:
        raise SystemExit(f"embedded length {N} too small to draw an attractor.")
    ct = (t[:N] - t[0])              # colour by base time of each embedded point

    info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    info.add_column(style="dim", min_width=18)
    info.add_column(style="white", justify="right")
    info.add_row("stem", f"[cyan]{stem}[/]")
    info.add_row("embedding", f"m={m}  τ={tau}  [dim]({src})[/]")
    info.add_row("points", f"{N}")
    console.print(info)

    fig = plt.figure(figsize=(10, 9))
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(X[:, 0], X[:, 1], X[:, 2], c=ct, cmap="viridis",
                    s=3, alpha=0.55, edgecolors="none")
    fig.colorbar(sc, ax=ax, label="t (s)", shrink=0.6, pad=0.1)
    ax.set_xlabel(r"$\omega_2(t)$")
    ax.set_ylabel(rf"$\omega_2(t+\tau)$")
    ax.set_zlabel(rf"$\omega_2(t+2\tau)$")
    ax.view_init(elev=args.elev, azim=args.azim)
    ax.set_title(
        f"Reconstructed attractor — {stem}\n"
        f"ω₂ delay embedding   τ={tau} frames   "
        f"(dim m={m})   N={N} points",
        fontsize=11)

    out = figure_path("attractor", stem)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    mirror_to_ready(out)
    plt.close(fig)
    console.print(f"  [dim]Saved → {out}[/]")


if __name__ == "__main__":
    main()
