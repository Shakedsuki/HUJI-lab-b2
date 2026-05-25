#!/usr/bin/env python3
"""
palette_sweep.py — shared driver for per-figure-type "palette" aggregates.

A palette is a contact sheet: one compact tile per QA-passed clip, frequency-
ordered, so a whole drive family reads at a glance (regular -> chaotic ->
regular). It is the cross-clip companion to each per-clip figure type shown in
the shell's figures matrix.

Same idea as theta2_timeseries_sweep.py (the th2vst palette), generalised: that
one is a single-axis tile, so it stays standalone; everything else flows through
this harness. Each type registers a PaletteSpec (how to load a clip's data, how
to draw one tile); the harness owns the shared machinery — QA gate, frequency
ordering, the live progress grid, the tiled layout, and opening the result. Each
tile reuses the SAME draw functions as the per-clip figure (e.g. phase_panels
.draw_phase1/2 + draw_config with compact=True), so a palette can never drift
from what the clips actually look like.

Usage
~~~~~
  python scripts/analysis/palette_sweep.py --type phase_panels
  python scripts/analysis/palette_sweep.py --type phase_panels --family 3.2V --ncols 3
  python scripts/analysis/palette_sweep.py --type phase_panels --qa-only

Output
~~~~~~
  figures/aggregate/<type>_<family>.png
"""

import argparse
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
from paths import clip_dir                                              # noqa: E402
from figures_paths import aggregate_path                               # noqa: E402
from theta2_timeseries import (load_metrics, stem_freq, classify)      # noqa: E402
import phase_panels                                                    # noqa: E402


# ── Palette registry ──────────────────────────────────────────────────────
# A type's tile is drawn by reusing its per-clip draw functions in compact form.
@dataclass
class PaletteSpec:
    label: str                       # human label for prompts/titles
    load: Callable[[str], dict]      # stem -> data dict for `tile`
    tile: Callable                   # (subfig, stem, data, meta) -> regime str
    available: Callable[[str], bool] # stem -> is the source data present?
    cell_w: float = 4.3              # tile width  (inches) per grid column
    cell_h: float = 1.3              # tile height (inches) per grid row
    key: str = ""                    # plain-English caption: what each tile shows


def _has_tracking(stem):
    return os.path.exists(os.path.join(clip_dir(stem), "tracking.csv"))


def _load_panels(stem):
    t, th1, th2 = phase_panels.load_csv(os.path.join(clip_dir(stem), "tracking.csv"))
    om1, om2 = phase_panels.compute_velocities(t, th1, th2)
    return {"t": t, "th1": th1, "th2": th2, "om1": om1, "om2": om2}


def _tile_panels(subfig, stem, data, meta):
    """One panels tile = phase portrait arm 1 (green) | arm 2 (red) |
    configuration space θ₁ vs θ₂ — the compact form of phase_panels."""
    ax1, ax2, ax3 = subfig.subplots(1, 3)
    phase_panels.draw_phase1(ax1, data["t"], data["th1"], data["om1"], compact=True)
    phase_panels.draw_phase2(ax2, data["t"], data["th2"], data["om2"], compact=True)
    phase_panels.draw_config(ax3, data["t"], data["th1"], data["th2"], compact=True)
    regime, col = classify(meta)
    subfig.suptitle(f"{stem_freq(stem):g} Hz", color=col, fontsize=9,
                    fontweight="bold", x=0.02, ha="left")
    return regime


SPECS = {
    "phase_panels": PaletteSpec(
        label="phase panels", load=_load_panels, tile=_tile_panels,
        available=_has_tracking, cell_w=5.2, cell_h=2.1,
        key="each tile:  arm 1 ω₁–θ₁ (green)  |  arm 2 ω₂–θ₂ (red)  |  "
            "configuration θ₂–θ₁ (blue)    ·  angles in deg, ω in deg/s"),
}


# ── Shared progress UI ────────────────────────────────────────────────────
REGIME_COLOR = {"REGULAR": "green", "CHAOTIC": "red"}


def _progress_grid(stems, ncols, regimes, cur):
    """rich matrix mirroring the aggregate layout: each cell fills (freq,
    regime-coloured) as its tile renders. pending = dim dot, current = …."""
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


def parse_args():
    p = argparse.ArgumentParser(description="Per-type palette (contact sheet) sweep.")
    p.add_argument("--type", required=True, choices=sorted(SPECS),
                   help="figure type to tile across the family")
    p.add_argument("--family", default="3.2V",
                   help="voltage prefix to sweep (default 3.2V)")
    p.add_argument("--ncols", type=int, default=3,
                   help="clips per row in the grid (default 3)")
    p.add_argument("--qa-only", action="store_true",
                   help="restrict to clips that passed overlay QA review")
    p.add_argument("--no-open", action="store_true",
                   help="don't open the PNG when done")
    return p.parse_args()


def main():
    args = parse_args()
    spec = SPECS[args.type]
    metrics = load_metrics()
    stems = sorted([s for s in metrics if s.startswith(args.family)], key=stem_freq)
    if args.qa_only:
        from batch_figures import passed_qa_stems
        passed = passed_qa_stems()
        stems = [s for s in stems if s in passed]
    stems = [s for s in stems if spec.available(s)]
    if not stems:
        raise SystemExit(f"no renderable clips for type {args.type!r} family "
                         f"{args.family!r}")

    n = len(stems)
    ncols = max(1, args.ncols)
    nrows = math.ceil(n / ncols)
    regimes = {}
    console.print(f"[bold]{args.family}[/] {spec.label} palette — {n} clips, "
                  f"{nrows}×{ncols} grid")

    with Live(_progress_grid(stems, ncols, regimes, 0), console=console,
              refresh_per_second=8) as live:
        fig = plt.figure(figsize=(spec.cell_w * ncols, spec.cell_h * nrows + 0.6),
                         dpi=150, constrained_layout=True)
        subfigs = fig.subfigures(nrows, ncols, squeeze=False).ravel()
        for k, stem in enumerate(stems):
            live.update(_progress_grid(stems, ncols, regimes, k))
            data = spec.load(stem)
            regimes[stem] = spec.tile(subfigs[k], stem, data, metrics.get(stem))
            live.update(_progress_grid(stems, ncols, regimes, k + 1))
        for k in range(n, len(subfigs)):
            subfigs[k].set_facecolor("none")     # blank trailing cells

        title = (f"{spec.label} — {args.family} frequency sweep   "
                 "(green = regular, red = chaotic)")
        if spec.key:
            title += "\n" + spec.key
        fig.suptitle(title, fontsize=11)
        out = aggregate_path(f"{args.type}_{args.family}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        live.update(_progress_grid(stems, ncols, regimes, n))

    console.print(f"[green]✓ palette ready[/]   [link={Path(out).as_uri()}]{out}[/link]")
    if not args.no_open:
        _open_file(out)


if __name__ == "__main__":
    main()
