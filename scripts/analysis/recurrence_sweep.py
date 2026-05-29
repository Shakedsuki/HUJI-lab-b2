#!/usr/bin/env python3
"""
recurrence_sweep.py — tile the stroboscopic recurrence plot across a whole
voltage family, one compact panel per clip, frequency-ordered.

Each tile is just the recurrence matrix (no stroboscopic scatter), with the
frequency + regime colour in the title. The aggregate grid shows the
texture transition from regular (uniform/banded) to chaotic (fragmented)
at a glance.

Usage
~~~~~
  python scripts/analysis/recurrence_sweep.py
  python scripts/analysis/recurrence_sweep.py --family 3.2V --ncols 3
  python scripts/analysis/recurrence_sweep.py --threshold-pct 12

Output
~~~~~~
  figures/aggregate/recurrence_<family>.png
"""

import argparse
import csv
import glob
import json
import math
import os
import re
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
from rich.live import Live
from rich.table import Table
from rich import box

console = Console()

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
sys.path.insert(0, _HERE)
from paths import EXPERIMENTS, clip_dir                    # noqa: E402
from figures_paths import aggregate_path, AGGREGATE        # noqa: E402
from driven_helpers import parse_stem, load_driven_csv     # noqa: E402


# ── Shared with recurrence.py ──────────────────────────

D2_CHAOS_THRESHOLD = 1.8
COL_REGULAR = "#2e8b57"
COL_CHAOTIC = "#c0392b"


def stem_freq(stem):
    m = re.search(r"_(\d+(?:\.\d+)?)Hz", stem)
    return float(m.group(1)) if m else 0.0


def load_metrics():
    """stem -> row dict from chaos_sweep CSV."""
    out = {}
    for path in glob.glob(os.path.join(AGGREGATE, "chaos_sweep_*.csv")):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    out[r["stem"]] = r
        except (OSError, KeyError):
            continue
    return out


def classify(meta):
    if meta is None:
        return "?", "#555555"
    try:
        d2 = float(meta["D2"])
    except (KeyError, ValueError, TypeError):
        return "?", "#555555"
    return ("CHAOTIC", COL_CHAOTIC) if d2 >= D2_CHAOS_THRESHOLD else ("REGULAR", COL_REGULAR)


def strobe_sample(t, th2, om2, f_drive, transient_s):
    T = 1.0 / f_drive
    n0 = int(np.ceil(transient_s / T))
    n1 = int(np.floor(t[-1] / T))
    if n1 < n0:
        return np.array([]), np.array([]), np.array([])
    ts = np.arange(n0, n1 + 1) * T
    return ts, np.interp(ts, t, th2), np.interp(ts, t, om2)


def recurrence_matrix(th2s, om2s, threshold_pct):
    n = len(th2s)
    if n < 3:
        return np.zeros((1, 1))
    th_range = th2s.max() - th2s.min()
    om_range = om2s.max() - om2s.min()
    th_n = (th2s - th2s.min()) / (th_range + 1e-12)
    om_n = (om2s - om2s.min()) / (om_range + 1e-12)
    states = np.column_stack([th_n, om_n])
    diff = states[:, None, :] - states[None, :, :]
    dist = np.sqrt((diff ** 2).sum(axis=2))
    nonzero = dist[dist > 0]
    if len(nonzero) == 0:
        return np.ones((n, n))
    threshold = np.percentile(nonzero, threshold_pct)
    return (dist < threshold).astype(float)


# ── Sweep driver ───────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--family", default="3.2V",
                   help="voltage prefix to sweep (default 3.2V)")
    p.add_argument("--ncols", type=int, default=3,
                   help="columns in the aggregate grid (default 3)")
    p.add_argument("--transient", type=float, default=5.0)
    p.add_argument("--threshold-pct", type=float, default=15.0)
    p.add_argument("--qa-only", action="store_true",
                   help="restrict to clips that passed overlay QA review")
    return p.parse_args()


REGIME_COLOR = {"REGULAR": "green", "CHAOTIC": "red"}


def _progress_grid(stems, ncols, done, cur):
    g = Table(box=box.SQUARE, show_header=False, padding=(0, 1))
    for _ in range(ncols):
        g.add_column(justify="center", min_width=6)
    cells = []
    for k, s in enumerate(stems):
        f = stem_freq(s)
        if s in done:
            cells.append(f"[{REGIME_COLOR.get(done[s], 'white')}]{f:g}[/]")
        elif k == cur:
            cells.append("[yellow]…[/]")
        else:
            cells.append("[dim]·[/]")
    for i in range(0, len(cells), ncols):
        row = cells[i:i + ncols]
        row += [""] * (ncols - len(row))
        g.add_row(*row)
    return g


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
    done = {}
    console.print(f"[bold]{args.family}[/] recurrence palette — {n} clips, "
                  f"{nrows}×{ncols} grid")

    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.0 * ncols, 3.8 * nrows + 0.8), dpi=150,
        constrained_layout=True)
    axes = np.atleast_1d(axes).ravel()

    with Live(_progress_grid(stems, ncols, done, 0), console=console,
              refresh_per_second=8) as live:
        for k, stem in enumerate(stems):
            live.update(_progress_grid(stems, ncols, done, k))
            meta = metrics.get(stem)
            regime, col = classify(meta)
            freq = stem_freq(stem)

            try:
                f_drive = freq
                csv_path = os.path.join(clip_dir(stem), "verification.csv")
                t, _, th2, _, om2 = load_driven_csv(csv_path)
                ts, th2s, om2s = strobe_sample(t, th2, om2, f_drive,
                                               args.transient)
                if len(ts) < 5:
                    raise ValueError("too few strobes")
                R = recurrence_matrix(th2s, om2s, args.threshold_pct)
            except Exception as e:
                axes[k].text(0.5, 0.5, f"err:\n{e}", ha="center", va="center",
                             fontsize=7, transform=axes[k].transAxes)
                axes[k].set_title(f"{freq:g} Hz", loc="left", color=col,
                                  fontsize=9, fontweight="bold", pad=2)
                done[stem] = regime
                continue

            axes[k].imshow(R, cmap="Greys", origin="lower",
                           interpolation="nearest", aspect="equal")
            axes[k].set_title(f"{freq:g} Hz  (n={len(ts)})", loc="left",
                              color=col, fontsize=9, fontweight="bold", pad=2)
            axes[k].tick_params(labelsize=6)

            done[stem] = regime
            live.update(_progress_grid(stems, ncols, done, k + 1))

        # blank out unused axes
        for k in range(n, len(axes)):
            axes[k].axis("off")

    fig.suptitle(f"Recurrence plots — {args.family} frequency sweep   "
                 f"(green = regular, red = chaotic)",
                 fontsize=13)
    out = aggregate_path(f"recurrence_{args.family}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)

    from pathlib import Path
    console.print(f"[green]✓ palette ready[/]   [link={Path(out).as_uri()}]{out}[/link]")
    try:
        if sys.platform == "win32":
            os.startfile(out)
    except Exception:
        pass


if __name__ == "__main__":
    main()
