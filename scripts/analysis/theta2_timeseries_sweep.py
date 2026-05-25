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
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich import box

console = Console()

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
    p.add_argument("--qa-only", action="store_true",
                   help="restrict to clips that passed overlay QA review")
    return p.parse_args()


REGIME_COLOR = {"REGULAR": "green", "CHAOTIC": "red"}


def _progress_grid(stems, ncols, regimes, cur):
    """A rich matrix mirroring the aggregate layout: each cell fills (freq,
    regime-coloured) as its plot renders. pending = dim dot, in-progress = …."""
    g = Table(box=box.SQUARE, show_header=False, padding=(0, 1))
    for _ in range(ncols):
        g.add_column(justify="center", min_width=6)
    cells = []
    for k, s in enumerate(stems):
        f = stem_freq(s)
        if s in regimes:
            cells.append(f"[{REGIME_COLOR.get(regimes[s], 'white')}]{f:g}[/]")
        elif k == cur:
            cells.append("[yellow]…[/]")
        else:
            cells.append("[dim]·[/]")
    for i in range(0, len(cells), ncols):
        row = cells[i:i + ncols]
        row += [""] * (ncols - len(row))
        g.add_row(*row)
    return g


def _open_file(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


def main():
    args = parse_args()
    metrics = load_metrics()
    stems = sorted([s for s in metrics if s.startswith(args.family)],
                   key=stem_freq)
    if args.qa_only:
        from batch_figures import passed_qa_stems
        passed = passed_qa_stems()
        stems = [s for s in stems if s in passed]
    if not stems:
        raise SystemExit(f"no clips found for family {args.family!r}")

    n = len(stems)
    ncols = max(1, args.ncols)
    nrows = math.ceil(n / ncols)
    regimes = {}
    console.print(f"[bold]{args.family}[/] palette — {n} clips, {nrows}×{ncols} grid")

    with Live(_progress_grid(stems, ncols, regimes, 0), console=console,
              refresh_per_second=8) as live:
        # per-clip standalone primitives (the slow render pass)
        if not args.no_individual:
            for k, stem in enumerate(stems):
                live.update(_progress_grid(stems, ncols, regimes, k))
                regime, _ = render_clip(stem, meta=metrics.get(stem))
                regimes[stem] = regime
                live.update(_progress_grid(stems, ncols, regimes, k + 1))

        # aggregate (frequency-ordered, compact tiles)
        fig, axes = plt.subplots(
            nrows, ncols, figsize=(4.3 * ncols, 1.15 * nrows + 0.7), dpi=150,
            sharey=True, constrained_layout=True)
        axes = np.atleast_1d(axes).ravel()
        for k, stem in enumerate(stems):
            t, th = load_theta2(stem)
            regime, _ = draw_theta2(axes[k], stem, t, th, metrics.get(stem),
                                    unwrap=True, compact=True, units="deg",
                                    mark_loops=False)
            axes[k].set_yticks([-8000, 0, 8000])   # show the true +-8000 range
            if stem not in regimes:                 # --no-individual: animate here
                regimes[stem] = regime
                live.update(_progress_grid(stems, ncols, regimes, k + 1))
        for k in range(n, len(axes)):
            axes[k].axis("off")
        fig.suptitle(rf"$\theta_2(t)$ cumulative (deg) — {args.family} frequency "
                     r"sweep   (green = regular, red = chaotic)", fontsize=13)
        out = aggregate_path(f"theta2_timeseries_{args.family}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        live.update(_progress_grid(stems, ncols, regimes, n))

    console.print(f"[green]✓ palette ready[/]   [link={Path(out).as_uri()}]{out}[/link]")
    _open_file(out)


if __name__ == "__main__":
    main()
