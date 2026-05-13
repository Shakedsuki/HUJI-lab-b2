"""
analysis_3d.py
---------------
3D phase space trajectory for the double pendulum.

Plots the trajectory as a ribbon in (theta1, theta2, omega1) space,
coloured by time. The trajectory lives on the energy surface — a curved
3D manifold inside the full 4D phase space.

Also produces a rotating animation saved as an MP4.

Usage:
  # Mode 1 — measurement folder (preferred for pipeline use):
  python scripts/analysis/phase_3d.py --stem th1_p044_th2_m001

  # Mode 2 — explicit CSV path:
  python scripts/analysis/phase_3d.py measurements/th1_p044_th2_m001/tracking.csv

  # Mode 3 — interactive (no args, plt.show() instead of saving):
  python scripts/analysis/phase_3d.py
"""

import sys

# Force UTF-8 stdout so unicode glyphs (θ, ω) don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
import os
import csv
import argparse
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from mpl_toolkits.mplot3d import Axes3D          # registers 3D projection
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from scipy.signal import savgol_filter
from matplotlib.collections import LineCollection

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV  = os.path.join(REPO_ROOT, "measurements", "th1_p180_th2_m179",
                            "tracking.csv")

SG_WINDOW    = 11
SG_POLY      = 3

# Rotation animation parameters
AZIM_START   = 30       # starting azimuth angle
AZIM_END     = 390      # ending azimuth (one full rotation + 30)
N_ROT_FRAMES = 360      # frames for the rotation
ELEV         = 22       # fixed elevation angle

def parse_args():
    p = argparse.ArgumentParser(
        description="3D phase-space trajectory + rotating animation.")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to tracking CSV (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p044_th2_m001. "
                        "Resolves CSV and output dir from measurements/.")
    p.add_argument("--save", action="store_true",
                   help="Save outputs to disk instead of plt.show().")
    return p.parse_args()

def resolve_paths(args):
    """
    Returns (csv_path, output_dir, stem_label, force_save).
    --stem mode is non-interactive: force_save is True so outputs are
    always written to disk.
    """
    if args.stem:
        meas_dir = os.path.join(REPO_ROOT, "measurements", args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            print(f"ERROR: tracking.csv not found for stem '{args.stem}'")
            print(f"  Expected: {csv_path}")
            sys.exit(1)
        return csv_path, meas_dir, args.stem, True

    if args.csv:
        csv_path = args.csv if os.path.isabs(args.csv) \
                   else os.path.join(REPO_ROOT, args.csv)
        output_dir = os.path.dirname(csv_path) or LEGACY_OUT
        stem_label = os.path.basename(output_dir) or \
                     os.path.splitext(os.path.basename(csv_path))[0]
        return csv_path, output_dir, stem_label, args.save

    return DEFAULT_CSV, LEGACY_OUT, "long_recording", args.save

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

def load(path):
    rows = [r for r in csv.DictReader(open(path))
            if r['phase'] == 'free_swing'
            and r['dropout'] == '0'
            and r['theta1_deg']]

    t   = np.array([float(r['time_s'])     for r in rows])
    th1 = np.array([float(r['theta1_deg']) for r in rows])
    th2 = np.array([float(r['theta2_deg']) for r in rows])
    t   = t - t[0]

    dt = np.mean(np.diff(t))
    # Unwrap before SG-differentiating so the derivative is physically
    # correct across the ±180° wrap.
    th1u = np.degrees(np.unwrap(np.radians(th1)))
    th2u = np.degrees(np.unwrap(np.radians(th2)))
    om1  = savgol_filter(th1u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2  = savgol_filter(th2u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    return t, th1, th2, om1, om2

# ─────────────────────────────────────────────
# COLOURED LINE SEGMENTS
# ─────────────────────────────────────────────

def make_segments(x, y, z, wrap_threshold=180.0):
    """
    Break (x, y, z) arrays into line segments connecting consecutive
    points. Drops segments that straddle a ±180° wrap on either x (θ1)
    or y (θ2) so the trajectory doesn't draw a long line across the
    plot at every inverted-angle crossing.
    """
    pts = np.array([x, y, z]).T                       # (N, 3)
    segs = np.stack([pts[:-1], pts[1:]], axis=1)      # (N-1, 2, 3)
    # Drop segments where x or y jumps by more than the wrap threshold.
    keep = (np.abs(np.diff(x)) <= wrap_threshold) & \
           (np.abs(np.diff(y)) <= wrap_threshold)
    return segs[keep], keep

# ─────────────────────────────────────────────
# STATIC 3D PLOT
# ─────────────────────────────────────────────

def plot_3d(t, th1, th2, om1, label, out_path, output_dir):
    """
    Static 3D trajectory: (theta1, theta2, omega1) coloured by time.
    """
    fig = plt.figure(figsize=(11, 8))
    ax  = fig.add_subplot(111, projection='3d')
    fig.patch.set_facecolor('#0d0d0d')
    ax.set_facecolor('#0d0d0d')

    # ── Colour by time ──────────────────────────────────────────────────
    norm  = plt.Normalize(t.min(), t.max())
    cmap  = plt.cm.plasma

    segs, keep = make_segments(th1, th2, om1)
    colors = cmap(norm((t[:-1] + t[1:]) / 2))[keep]   # midpoint colour per kept segment

    lc = Line3DCollection(segs, colors=colors, linewidth=0.7, alpha=0.85)
    ax.add_collection3d(lc)

    # ── Start and end markers ───────────────────────────────────────────
    ax.scatter([th1[0]],  [th2[0]],  [om1[0]],
               color='white', s=40, zorder=5, label='release')
    ax.scatter([th1[-1]], [th2[-1]], [om1[-1]],
               color='yellow', s=40, zorder=5, label='end')

    # ── Axes limits and labels ──────────────────────────────────────────
    pad = 0.08
    def padded(arr):
        r = arr.max() - arr.min()
        return arr.min() - pad*r, arr.max() + pad*r

    ax.set_xlim(*padded(th1))
    ax.set_ylim(*padded(th2))
    ax.set_zlim(*padded(om1))

    ax.set_xlabel(r'$\theta_1$ (°)', color='#aaaaaa', labelpad=8)
    ax.set_ylabel(r'$\theta_2$ (°)', color='#aaaaaa', labelpad=8)
    ax.set_zlabel(r'$\omega_1$ (°/s)', color='#aaaaaa', labelpad=8)

    ax.tick_params(colors='#555555', labelsize=7)
    for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
        pane.fill = False
        pane.set_edgecolor('#222222')
    ax.grid(True, color='#222222', lw=0.4)

    ax.set_title(
        r'3D Phase Trajectory  ($\theta_1$, $\theta_2$, $\omega_1$)',
        color='#cccccc', fontsize=12, pad=12
    )

    # ── Colourbar ───────────────────────────────────────────────────────
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.5, pad=0.1)
    cb.set_label('t (s)', color='#aaaaaa')
    cb.ax.yaxis.set_tick_params(color='#555555')
    plt.setp(cb.ax.yaxis.get_ticklabels(), color='#888888', fontsize=7)

    ax.legend(fontsize=8, facecolor='#1a1a1a', edgecolor='#333333',
              labelcolor='#aaaaaa', loc='upper left')

    ax.view_init(elev=ELEV, azim=AZIM_START)

    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    mirror_to_ready(out_path)
    print(f"Static figure saved to: {out_path}")
    return fig, ax, lc, norm, cmap

# ─────────────────────────────────────────────
# ROTATING ANIMATION
# ─────────────────────────────────────────────

def make_rotation_animation(fig, ax, out_mp4, output_dir):
    """
    Rotate the 3D plot through 360° and save as MP4.
    """
    azimuths = np.linspace(AZIM_START, AZIM_END, N_ROT_FRAMES)

    def update(frame):
        ax.view_init(elev=ELEV, azim=azimuths[frame])
        return []

    anim = animation.FuncAnimation(
        fig, update, frames=N_ROT_FRAMES, interval=1000/30, blit=False
    )

    os.makedirs(output_dir, exist_ok=True)
    writer = animation.FFMpegWriter(fps=30, bitrate=1800)
    print(f"Saving rotation to {out_mp4} ...")

    step = max(1, N_ROT_FRAMES // 20)
    with writer.saving(fig, out_mp4, dpi=120):
        for i in range(N_ROT_FRAMES):
            update(i)
            writer.grab_frame()
            if i % step == 0 or i == N_ROT_FRAMES - 1:
                pct = 100 * (i + 1) // N_ROT_FRAMES
                bar = '█' * (pct // 5) + '░' * (20 - pct // 5)
                print(f"  [{bar}] {pct:3d}%", end='\r', flush=True)

    print(f"\nRotation saved to: {out_mp4}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    csv_path, output_dir, stem, force_save = resolve_paths(args)

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    ext = os.path.splitext(csv_path)[1].lower()
    if ext != ".csv":
        print(f"ERROR: expected a tracking CSV, got '{csv_path}' (extension '{ext}').")
        print("       This script reads the per-frame angle CSV, not videos.")
        print(f"       Try:  python {os.path.basename(__file__)} --stem <config_description>")
        sys.exit(2)

    print(f"Loading {csv_path} ...")
    t, th1, th2, om1, om2 = load(csv_path)
    print(f"  {len(t)} frames  ({t[-1]:.2f}s)")
    print(f"  theta1: [{th1.min():.1f}, {th1.max():.1f}] deg")
    print(f"  theta2: [{th2.min():.1f}, {th2.max():.1f}] deg")
    print(f"  omega1: [{om1.min():.0f}, {om1.max():.0f}] deg/s")

    # When called via --stem (or --save) we write to the canonical
    # figures/ directory; otherwise (interactive fallback) we keep the
    # legacy <stem>_3d_*.{png,mp4} naming inside output_dir.
    if force_save and args.stem:
        png_path = figure_path("phase_3d_trajectory", args.stem)
        mp4_path = figure_path("phase_3d_rotation", args.stem, ext="mp4")
    elif force_save and args.save:
        # save without --stem: derive stem from output_dir if it's a
        # measurements/<stem>/ folder.
        derived_stem = os.path.basename(output_dir)
        png_path = figure_path("phase_3d_trajectory", derived_stem)
        mp4_path = figure_path("phase_3d_rotation", derived_stem, ext="mp4")
    else:
        png_path = os.path.join(output_dir, f"{stem}_3d_trajectory.png")
        mp4_path = os.path.join(output_dir, f"{stem}_3d_rotation.mp4")

    fig, ax, lc, norm, cmap = plot_3d(t, th1, th2, om1, stem, png_path,
                                      output_dir)

    if force_save:
        make_rotation_animation(fig, ax, mp4_path, output_dir)
    else:
        plt.show()

if __name__ == "__main__":
    main()
