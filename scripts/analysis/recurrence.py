#!/usr/bin/env python3
"""
recurrence.py — recurrence plot of the ω₂ attractor for a driven clip.

A recurrence plot shows when the reconstructed trajectory returns close to
a previously visited state:

    R(i, j) = 1   if ‖x(i) − x(j)‖ < ε,   else 0

Reading it:
  long diagonals parallel to the main diagonal  → deterministic / periodic
  short, broken diagonals + isolated points     → chaos (sensitive)
  uniform speckle                               → noise / stochastic

The embedding mirrors dimension.py — a delay embedding of ω₂ (the lower
arm's angular velocity, stationary even when the arm circulates), reusing
that clip's (m, τ) from dimension.json when present (else m=5, τ=11).
ε self-tunes to a low percentile of the pairwise-distance distribution.

Output:
  figures/recurrence/<stem>_recurrence.png

Usage:
  python scripts/analysis/recurrence.py --stem 3.2V_1.20Hz
  python scripts/analysis/recurrence.py --stem 3.2V_0.91Hz --eps-pct 8
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
from scipy.spatial.distance import cdist

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

DEFAULT_M = 5
DEFAULT_TAU = 11


def read_embed_params(stem, m_arg, tau_arg):
    """(m, τ, source) — CLI overrides win, then dimension.json, then defaults."""
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
    if m_arg is not None:
        m = m_arg; src = "cli"
    if tau_arg is not None:
        tau = tau_arg; src = "cli"
    return m, tau, src


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True, help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start (default 5).")
    p.add_argument("--m", type=int, default=None, help="embedding dimension (override).")
    p.add_argument("--tau", type=int, default=None, help="delay in frames (override).")
    p.add_argument("--max-points", type=int, default=2000,
                   help="cap on embedded points (recurrence matrix is N×N).")
    p.add_argument("--eps-pct", type=float, default=10.0,
                   help="ε = this percentile of pairwise distances (default 10).")
    args = p.parse_args()
    stem = args.stem

    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    t, th2 = load_clip(csv_path)
    keep = t >= (t[0] + args.transient)
    if keep.sum() > 200:
        t, th2 = t[keep], th2[keep]

    # ω₂ = derivative of the unwrapped lower-arm angle (mirrors dimension.py).
    phi = np.degrees(np.unwrap(np.radians(th2)))
    om2 = np.gradient(phi, t)

    m, tau, src = read_embed_params(stem, args.m, args.tau)
    X = embed(om2, m, tau)
    n_full = len(X)
    if n_full < 20:
        raise SystemExit(f"embedded length {n_full} too small for a recurrence plot.")

    # Subsample (preserving time order) so the N×N matrix stays tractable.
    if n_full > args.max_points:
        idx = np.unique(np.linspace(0, n_full - 1, args.max_points).astype(int))
        X = X[idx]
    N = len(X)

    D = cdist(X, X)
    off = D[np.triu_indices_from(D, k=1)]
    eps = float(np.percentile(off, args.eps_pct))
    R = (D < eps).astype(np.uint8)
    rr = float(R.sum() - N) / float(N * N - N) if N > 1 else float("nan")  # recurrence rate (excl. diagonal)

    info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    info.add_column(style="dim", min_width=18)
    info.add_column(style="white", justify="right")
    info.add_row("stem", f"[cyan]{stem}[/]")
    info.add_row("embedding", f"m={m}  τ={tau}  [dim]({src})[/]")
    info.add_row("points N", f"{N}  [dim](from {n_full})[/]")
    info.add_row("ε", f"{eps:.3f}  [dim]({args.eps_pct:g}th pct)[/]")
    info.add_row("recurrence rate", f"{rr*100:.2f}%")
    console.print(info)

    fig, ax = plt.subplots(figsize=(8.6, 8))
    # 'Greys' maps 0→white, 1→black, so R=1 (recurrence) renders as black on white.
    ax.imshow(R, origin="lower", cmap="Greys", vmin=0, vmax=1,
              interpolation="nearest", aspect="equal")
    ax.set_xlabel("time index  j")
    ax.set_ylabel("time index  i")
    ax.set_title(
        f"Recurrence plot — {stem}\n"
        f"ω₂ embedding m={m}, τ={tau}   N={N}   "
        f"ε={eps:.2f} ({args.eps_pct:g}th pct)   RR={rr*100:.1f}%",
        fontsize=11)

    out = figure_path("recurrence", stem)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    mirror_to_ready(out)
    plt.close(fig)
    console.print(f"  [dim]Saved → {out}[/]")


if __name__ == "__main__":
    main()
