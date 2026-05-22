#!/usr/bin/env python3
"""
seismograph.py — Double-pendulum "seismograph" / hodograph projection.

Maps the lower arm's tip direction θ_tip(t) onto a radial coordinate
system: the angular position is θ_tip and the radius encodes time. It's an
angle-preserving radial extrusion of the circular tip trajectory — each
successive position is displaced outward instead of retracing the same
circle, so the trace unfurls in the direction the tip points.

θ_tip is the lower arm's ABSOLUTE lab-frame angle measured from the
intermediate pivot (green marker) — i.e. ``theta2_deg`` directly. In this
rig's tracking output theta2 is already absolute (green→red direction), so
θ_tip is θ₂, NOT θ₁+θ₂.

Two radial mappings, same angular series:
  v1 "spiral trail":       r = R0 + spread     · (t − t0)     newest outermost
  v2 "ripple propagation": r = R0 + wave_speed · (t_end − t)  oldest outermost

Points are plotted at (r·sinθ, −r·cosθ) so 0° points straight down.

Regular oscillation → symmetric, evenly spaced lobes; chaotic episodes →
asymmetric tangled regions. The regular↔chaotic transition reads as a
geometric texture change, without reducing the data to a scalar.

Usage:
  python scripts/analysis/seismograph.py --stem 3.2V_1.20Hz
  python scripts/analysis/seismograph.py --stem 3.2V_1.20Hz --t-start 10 --t-end 60
  python scripts/analysis/seismograph.py path/to/tracking.csv --out fig.png

Output (with --stem):
  figures/seismograph/<stem>_seismograph.png
"""

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
from matplotlib import colormaps

from rich.console import Console

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir             # noqa: E402
from figures_paths import figure_path  # noqa: E402

# ═══════════════════════════════════════════════════════════════════
# TWEAKABLE PARAMETERS
# ═══════════════════════════════════════════════════════════════════

SPREAD = 1.5               # v1 radial growth per second
WAVE_SPEED = 1.5           # v2 radial propagation speed per second

SOURCE_RADIUS = 1.0        # source circle radius (arbitrary units)
SUBSAMPLE = 2              # take every Nth point (1 = all)
JUMP_THRESHOLD_DEG = 120   # break line at angular jumps larger than this

LINE_WIDTH_MIN = 0.2
LINE_WIDTH_MAX = 1.6
CMAP_NAME = "inferno"      # try: 'magma', 'hot', 'plasma', 'turbo'
BG_COLOR = "#0a0a0c"
PANEL_BG = "#0e0e12"
CIRCLE_COLOR = "#2ecc40"
CIRCLE_ALPHA = 0.35
CIRCLE_LW = 1.2
GRID_RINGS = True          # faint concentric reference rings
GRID_RING_SPACING = 2.0
GRID_ALPHA = 0.06
TRACE_ALPHA_MIN = 0.08     # alpha for oldest/farthest segments
TRACE_ALPHA_MAX = 0.85     # alpha for newest/nearest segments

# Tracker rows we treat as "running" motion (driven phase, or legacy
# free_swing). Mirrors the rest of the analysis pipeline.
RUN_PHASES = ("driven", "free_swing")

# ═══════════════════════════════════════════════════════════════════


def load_data(path, t_start=None, t_end=None):
    """Load tracking/verification CSV; keep running-phase, non-dropout,
    finite-angle rows; apply the time window; subsample."""
    df = pd.read_csv(path)

    if "phase" in df.columns:
        df = df[df["phase"].isin(RUN_PHASES)].copy()

    if "dropout" in df.columns:
        keep = pd.to_numeric(df["dropout"], errors="coerce").fillna(0) == 0
        df = df[keep].copy()

    # Drop rows with non-finite angle / time.
    for col in ("theta1_deg", "theta2_deg", "time_s"):
        df = df[pd.to_numeric(df[col], errors="coerce").notna()]
    df = df.reset_index(drop=True)

    if t_start is not None:
        df = df[df.time_s >= t_start]
    if t_end is not None:
        df = df[df.time_s <= t_end]
    df = df.reset_index(drop=True)

    if SUBSAMPLE > 1:
        df = df.iloc[::SUBSAMPLE].reset_index(drop=True)

    return df


def compute_tip_geometry(df):
    """Return (tip_angle [rad], time [s]).

    θ_tip = theta2 — the lower arm's absolute lab-frame angle measured
    from the green (intermediate) pivot. theta2 is already absolute in
    this rig, so this is NOT theta1 + theta2.
    """
    tip_angle = np.radians(pd.to_numeric(df.theta2_deg).values)
    time = pd.to_numeric(df.time_s).values
    return tip_angle, time


def angle_to_xy(angle, radius):
    """Polar (angle, radius) → Cartesian, 0° = straight down."""
    x = radius * np.sin(angle)
    y = -radius * np.cos(angle)
    return x, y


def build_segments(x, y, tip_angle):
    """Build line segments, breaking at large angular jumps (±180° wraps
    and single-frame tracking artifacts)."""
    points = np.column_stack([x, y])
    segments = []
    seg_indices = []  # index of the SECOND point in each segment

    angle_diffs = np.abs(np.diff(tip_angle))
    threshold = np.radians(JUMP_THRESHOLD_DEG)

    for i in range(len(points) - 1):
        if angle_diffs[i] < threshold:
            segments.append(np.array([points[i], points[i + 1]]))
            seg_indices.append(i + 1)

    return segments, seg_indices


def draw_panel(ax, tip_angle, time, mode, title):
    """Draw one seismograph panel.

    mode='v1': radius = R + SPREAD × (t − t₀)
    mode='v2': radius = R + WAVE_SPEED × (t_end − t)
    """
    t0, t1 = time[0], time[-1]

    if mode == "v1":
        radii = SOURCE_RADIUS + SPREAD * (time - t0)
    else:  # v2
        radii = SOURCE_RADIUS + WAVE_SPEED * (t1 - time)

    x, y = angle_to_xy(tip_angle, radii)
    segments, seg_indices = build_segments(x, y, tip_angle)

    if not segments:
        ax.set_title(title, color="#aaa", fontsize=11)
        ax.set_facecolor(PANEL_BG)
        return

    seg_times = time[seg_indices]
    norm = Normalize(vmin=t0, vmax=t1)
    cmap = colormaps[CMAP_NAME]

    normed_t = (seg_times - t0) / (t1 - t0) if t1 > t0 else np.ones_like(seg_times)
    linewidths = LINE_WIDTH_MIN + (LINE_WIDTH_MAX - LINE_WIDTH_MIN) * normed_t

    colors_rgba = cmap(norm(seg_times)).copy()
    colors_rgba[:, 3] = TRACE_ALPHA_MIN + (TRACE_ALPHA_MAX - TRACE_ALPHA_MIN) * normed_t

    lc = LineCollection(segments, colors=colors_rgba, linewidths=linewidths,
                        capstyle="round", joinstyle="round")
    ax.add_collection(lc)

    # Source circle.
    circle_theta = np.linspace(0, 2 * np.pi, 200)
    cx, cy = angle_to_xy(circle_theta, SOURCE_RADIUS)
    ax.plot(cx, cy, color=CIRCLE_COLOR, alpha=CIRCLE_ALPHA, lw=CIRCLE_LW)

    # Faint reference rings.
    if GRID_RINGS:
        r_max = radii.max() * 1.05
        r = SOURCE_RADIUS + GRID_RING_SPACING
        while r < r_max:
            gx, gy = angle_to_xy(circle_theta, r)
            ax.plot(gx, gy, color="#ffffff", alpha=GRID_ALPHA, lw=0.5)
            r += GRID_RING_SPACING

    pad = radii.max() * 1.08
    ax.set_xlim(-pad, pad)
    ax.set_ylim(-pad, pad)
    ax.set_aspect("equal")
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors="#333", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#1a1a1a")
    ax.set_title(title, color="#ccc", fontsize=11, fontfamily="monospace", pad=10)


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", nargs="?", default=None,
                   help="ad-hoc path to a tracking/verification CSV")
    p.add_argument("--stem", default=None,
                   help="clip stem; reads verification.csv (or tracking.csv) "
                        "from its measurements dir")
    p.add_argument("--t-start", type=float, default=None, dest="t_start",
                   help="window start (s)")
    p.add_argument("--t-end", type=float, default=None, dest="t_end",
                   help="window end (s)")
    p.add_argument("--out", default=None, help="output PNG (overrides default)")
    p.add_argument("--dpi", type=int, default=150)
    return p.parse_args()


def resolve_csv_and_out(args):
    if args.stem:
        cdir = clip_dir(args.stem)
        csv_path = next((os.path.join(cdir, n) for n in
                         ("verification.csv", "tracking.csv")
                         if os.path.exists(os.path.join(cdir, n))), None)
        if csv_path is None:
            raise SystemExit(f"no verification.csv / tracking.csv in {cdir}")
        return csv_path, (args.out or figure_path("seismograph", args.stem))
    if args.csv:
        return args.csv, (args.out or "seismograph.png")
    raise SystemExit("provide --stem <stem> or a positional CSV path")


def main():
    args = parse_args()
    csv_path, out_path = resolve_csv_and_out(args)

    df = load_data(csv_path, args.t_start, args.t_end)
    if len(df) < 3:
        raise SystemExit(
            f"only {len(df)} points after filtering — check the time range / CSV")

    tip_angle, time = compute_tip_geometry(df)
    t0, t1 = time[0], time[-1]
    label = args.stem or os.path.basename(csv_path)

    console.print(f"  [cyan]{label}[/]  [dim]{len(df)} pts · "
                  f"t ∈ [{t0:.2f}, {t1:.2f}] s · subsample {SUBSAMPLE}×[/]")
    console.print(f"  [dim]θ_tip (=θ₂) range "
                  f"[{np.degrees(tip_angle.min()):.1f}, "
                  f"{np.degrees(tip_angle.max()):.1f}]°[/]")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8), facecolor=BG_COLOR)
    draw_panel(ax1, tip_angle, time, "v1",
               f"v1 — Spiral Trail\nspread = {SPREAD}  ·  R = {SOURCE_RADIUS}")
    draw_panel(ax2, tip_angle, time, "v2",
               f"v2 — Ripple Propagation\n"
               f"wave_speed = {WAVE_SPEED}  ·  R = {SOURCE_RADIUS}")

    sm = plt.cm.ScalarMappable(cmap=CMAP_NAME, norm=Normalize(vmin=t0, vmax=t1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=[ax1, ax2], location="bottom",
                        fraction=0.03, pad=0.06, aspect=50)
    cbar.set_label("time (s)", color="#888", fontsize=10, fontfamily="monospace")
    cbar.ax.tick_params(colors="#666", labelsize=8)
    cbar.outline.set_edgecolor("#222")

    fig.suptitle(f"Seismograph — {label}  ·  {len(df)} pts  ·  subsample {SUBSAMPLE}×",
                 color="#555", fontsize=10, fontfamily="monospace", y=0.97)

    plt.tight_layout(rect=[0, 0.07, 1, 0.95])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=args.dpi, facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)
    console.print(f"  [dim]→ {out_path}[/]")


if __name__ == "__main__":
    main()
