#!/usr/bin/env python3
"""
theta2_timeseries.py — per-clip lower-arm angle theta2(t) time series.

This is the PRIMITIVE: one measure (theta2), one clip, one panel. It is
meant to be run across a whole sweep (one figure per clip) and then tiled
into a single aggregate comparison figure. The actual drawing lives in
``draw_theta2(ax, ...)`` so the aggregate can reuse it cell-for-cell and
stay identical to the standalone per-clip figure.

theta2 is the lower arm's ABSOLUTE lab-frame angle (green->red marker
direction), already in [-180, 180] in the tracking output.

By default the figure shows the CUMULATIVE (unwrapped) angle in DEGREES on a
fixed +-8000 deg axis, regime-coloured (green regular / red chaotic by D2),
with a loop lane below marking over-the-top crossings (CCW ^ / CW v) and
their counts in the legend; D2 and lambda1 (from chaos_sweep_*.csv) appear in
the title. Net rotation accumulates, so libration reads as a flat ribbon at 0
and circulation/tumbling as a runaway staircase; the fixed axis keeps every
clip comparable.

  --wrapped  : plot theta2 in [-180, 180] (wrap jumps masked) instead.
  --units    : deg (default) / turns / rad for the cumulative view.
  --no-loops : hide the loop lane.

Usage
~~~~~
  python scripts/analysis/theta2_timeseries.py --stem 3.2V_1.20Hz
  python scripts/analysis/theta2_timeseries.py --stem 3.2V_0.93Hz --wrapped
  python scripts/analysis/theta2_timeseries.py --stem 3.2V_1.20Hz --units turns

Output
~~~~~~
  figures/theta2_timeseries/<stem>_theta2_timeseries_cumulative.png
"""

import argparse
import csv
import glob
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
from matplotlib.lines import Line2D

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir                              # noqa: E402
from figures_paths import figure_path, AGGREGATE        # noqa: E402

# regime colours echo the repo convention: green = regular, red = chaotic
COL_REGULAR = "#2e8b57"
COL_CHAOTIC = "#c0392b"
COL_UNKNOWN = "#555555"
D2_CHAOS_THRESHOLD = 1.8   # D2 below -> regular limit cycle; above -> chaotic

# Cumulative (unwrapped) theta2 spans ~[-6255, +7694] deg across the 3.2V
# sweep. ONE fixed symmetric axis keeps every clip comparable: regular clips
# read as a flat line near 0, chaotic clips show their runaway staircase.
# +-8000 fits every clip with no clipping (the widest are 1.16Hz +7694 and
# 1.17Hz -6255, both strong directional drifts). Override per-run with --ylim.
CUMULATIVE_YLIM = (-8000.0, 8000.0)


def parse_args():
    p = argparse.ArgumentParser(description="Per-clip theta2(t) primitive.")
    p.add_argument("--stem", required=True,
                   help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--wrapped", action="store_true",
                   help="plot wrapped theta2 in [-180,180] instead of the "
                        "default cumulative (unwrapped) angle")
    p.add_argument("--units", choices=["turns", "deg", "rad"], default="deg",
                   help="cumulative angle units (default deg)")
    p.add_argument("--no-loops", action="store_true",
                   help="hide the over-the-top loop lane (shown by default)")
    p.add_argument("--ylim", default=None,
                   help="cumulative y-limits 'lo,hi' in DEGREES (default: fixed "
                        f"sweep-wide {CUMULATIVE_YLIM[0]:.0f},{CUMULATIVE_YLIM[1]:.0f})")
    p.add_argument("--out", default=None, help="output png path override")
    return p.parse_args()


def stem_freq(stem):
    m = re.search(r"_(\d+(?:\.\d+)?)Hz", stem)
    return float(m.group(1)) if m else 0.0


def family_label(stem):
    m = re.match(r"([0-9.]+V)", stem)
    return m.group(1) if m else "set"


def load_metrics():
    """stem -> row dict from aggregate chaos_sweep_*.csv (D2, lambda1, loops...)."""
    out = {}
    for path in glob.glob(os.path.join(AGGREGATE, "chaos_sweep_*.csv")):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    out[r["stem"]] = r
        except (OSError, KeyError):
            continue
    return out


def load_theta2(stem):
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
        raise ValueError(f"no rows in {path}")
    t = np.asarray(t, dtype=float)
    th = np.asarray(th, dtype=float)
    return t - t[0], th


def mask_wraps(y, thresh=180.0):
    """Break the line (NaN) wherever |dy| exceeds thresh, so the +-180 wrap is
    not drawn as a vertical streak. Returns a copy."""
    y = y.astype(float).copy()
    jumps = np.where(np.abs(np.diff(y)) > thresh)[0]
    y[jumps] = np.nan
    return y


# Concepts/methods used below (names only — look up for review):
#   angle unwrapping; circulation vs libration; winding number;
#   over-the-top crossing = full revolution; rotation sense (CW / CCW).
def detect_overtop(th, thresh=180.0):
    """Over-the-top crossings (full revolutions) from the wrapped angle th.
    Returns (event_indices, direction) with +1 = CCW, -1 = CW. A wrapped
    drop (Δ < -180) is the angle passing up through +180 -> CCW."""
    d = np.diff(th)
    idx = np.where(np.abs(d) > thresh)[0]
    direction = np.where(d[idx] < 0, 1, -1)
    return idx + 1, direction


def unit_factor(units):
    """Divisor to convert cumulative DEGREES into the requested unit, plus the
    axis-label string. turns = net revolutions (deg/360)."""
    return {"deg": (1.0, "deg"),
            "turns": (360.0, "turns"),
            "rad": (180.0 / np.pi, "rad")}[units]


def classify(meta):
    if meta is None:
        return "?", COL_UNKNOWN
    try:
        d2 = float(meta["D2"])
    except (KeyError, ValueError, TypeError):
        return "?", COL_UNKNOWN
    return ("CHAOTIC", COL_CHAOTIC) if d2 >= D2_CHAOS_THRESHOLD else ("REGULAR", COL_REGULAR)


def metric_caption(meta):
    if meta is None:
        return ""
    def g(k):
        try:
            return float(meta[k])
        except (KeyError, ValueError, TypeError):
            return float("nan")
    d2, lam = g("D2"), g("lambda1")
    bits = []
    if np.isfinite(d2):
        bits.append(rf"$D_2$={d2:.2f}")
    if np.isfinite(lam):
        bits.append(rf"$\lambda_1$={lam:+.2f}/s")
    return "   ".join(bits)


def draw_theta2(ax, stem, t, th, meta, unwrap=False, compact=False,
                cum_ylim=CUMULATIVE_YLIM, units="turns", mark_loops=False,
                rug_ax=None):
    """Render one theta2(t) trace onto ``ax``. This is the shared primitive —
    the standalone per-clip figure and each cell of the aggregate both call it.

    compact=True trims fonts/title for small aggregate tiles.
    units applies to the cumulative (unwrap) view: turns / deg / rad.
    mark_loops draws over-the-top crossings; if rug_ax is given they go in
    that lane BELOW the trace (CCW ^ above midline / CW v below) so they don't
    obscure the trend, and the counts go in a legend on ``ax``.
    Returns (regime, colour).
    """
    regime, col = classify(meta)
    freq = stem_freq(stem)
    if unwrap:
        div, _ = unit_factor(units)
        y = np.degrees(np.unwrap(np.radians(th))) / div
    else:
        y = mask_wraps(th)

    ax.plot(t, y, lw=0.6, color=col, solid_capstyle="round", zorder=2)
    ax.set_xlim(t[0], t[-1])
    ax.grid(True, alpha=0.25)

    if mark_loops:
        ev, dirn = detect_overtop(th)
        n_ccw, n_cw = int((dirn > 0).sum()), int((dirn < 0).sum())
        up = dirn > 0
        if rug_ax is not None:                       # markers BELOW the trace
            rug_ax.axhline(0, color="0.85", lw=0.6, zorder=1)
            if ev.size:
                rug_ax.scatter(t[ev[up]],  np.full(int(up.sum()), 0.5),
                               marker="^", s=14, lw=0, color="#1a9850", zorder=3)
                rug_ax.scatter(t[ev[~up]], np.full(int((~up).sum()), -0.5),
                               marker="v", s=14, lw=0, color="#762a83", zorder=3)
            rug_ax.set_xlim(t[0], t[-1])
            rug_ax.set_ylim(-1, 1)
            rug_ax.set_yticks([])
            rug_ax.grid(True, axis="x", alpha=0.25)
            rug_ax.set_ylabel("loops", fontsize=8)
        if not compact:
            ax.legend(handles=[
                Line2D([], [], marker="^", lw=0, ms=6, color="#1a9850",
                       label=f"CCW ({n_ccw})"),
                Line2D([], [], marker="v", lw=0, ms=6, color="#762a83",
                       label=f"CW ({n_cw})")],
                loc="upper left", fontsize=8, framealpha=0.9,
                handletextpad=0.3, labelspacing=0.3, borderpad=0.5)
    if unwrap:
        lo, hi = cum_ylim                 # fixed shared axis -> clips comparable
        ax.set_ylim(lo / div, hi / div)
    else:
        ax.set_ylim(-188, 188)
        ax.set_yticks([-180, -90, 0, 90, 180])

    if compact:
        ax.set_title(f"{freq:g} Hz", loc="left", color=col, fontsize=9,
                     fontweight="bold", pad=2)
        ax.tick_params(labelsize=7)
    else:
        cap = metric_caption(meta)
        title = (rf"$\theta_2(t)$   —   {family_label(stem)}  {freq:g} Hz"
                 f"      {regime}")
        if cap:
            title += f"      {cap}"
        ax.set_title(title, loc="left", color=col, fontsize=13,
                     fontweight="bold")
    return regime, col


def out_path(stem, unwrap, override=None):
    if override:
        return override
    base = figure_path("theta2_timeseries", stem)
    if unwrap:
        base = base[:-4] + "_cumulative.png"
    return base


def render_clip(stem, meta=None, *, unwrap=True, units="deg", mark_loops=True,
                cum_ylim=CUMULATIVE_YLIM, out=None):
    """Build and save the standalone per-clip primitive figure. Returns
    (regime, out_path). Shared by the CLI (main) and the sweep driver."""
    t, th = load_theta2(stem)
    if meta is None:
        meta = load_metrics().get(stem)

    if mark_loops:
        fig, (ax, rug) = plt.subplots(
            2, 1, figsize=(11, 3.7), dpi=150, sharex=True,
            constrained_layout=True, gridspec_kw={"height_ratios": [6, 1]})
    else:
        fig, ax = plt.subplots(figsize=(11, 3.2), dpi=150,
                               constrained_layout=True)
        rug = None

    regime, _ = draw_theta2(ax, stem, t, th, meta, unwrap=unwrap,
                            cum_ylim=cum_ylim, units=units,
                            mark_loops=mark_loops, rug_ax=rug)
    bottom = rug if rug is not None else ax
    bottom.set_xlabel("time (s)", fontsize=10)
    if rug is not None:
        ax.tick_params(labelbottom=False)
    if unwrap:
        _, ulabel = unit_factor(units)
        ax.set_ylabel(rf"$\theta_2$ cumulative ({ulabel})", fontsize=10)
    else:
        ax.set_ylabel(r"$\theta_2$ (deg)", fontsize=10)

    out = out or out_path(stem, unwrap)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return regime, out


def main():
    args = parse_args()
    cum_ylim = CUMULATIVE_YLIM
    if args.ylim:
        lo, hi = (float(x) for x in args.ylim.split(","))
        cum_ylim = (lo, hi)
    regime, out = render_clip(
        args.stem, unwrap=not args.wrapped, units=args.units,
        mark_loops=not args.no_loops, cum_ylim=cum_ylim, out=args.out)
    print(f"{args.stem}  [{regime}]  ->  {out}")


if __name__ == "__main__":
    main()
