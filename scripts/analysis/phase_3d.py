"""
analysis_3d.py
---------------
3D phase space trajectory for the double pendulum.

Plots the trajectory as a ribbon in (theta1, theta2, omega1) space,
coloured by time. The trajectory lives on the energy surface — a curved
3D manifold inside the full 4D phase space.

Also produces a rotating animation saved as an MP4.

Usage:
  python scripts/analysis/phase_3d.py
  python scripts/analysis/phase_3d.py path/to/tracking.csv
  python scripts/analysis/phase_3d.py path/to/tracking.csv --save
"""

import sys
import os
import csv
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from mpl_toolkits.mplot3d import Axes3D          # registers 3D projection
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from scipy.signal import savgol_filter
from matplotlib.collections import LineCollection


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV  = r"C:\dev\chaos\data\long_recording_tracking.csv"
OUTPUT_DIR   = r"C:\dev\chaos\data\figures"

SG_WINDOW    = 11
SG_POLY      = 3

SAVE_MP4     = "--save" in sys.argv

# Rotation animation parameters
AZIM_START   = 30       # starting azimuth angle
AZIM_END     = 390      # ending azimuth (one full rotation + 30)
N_ROT_FRAMES = 360      # frames for the rotation
ELEV         = 22       # fixed elevation angle


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

    dt  = np.mean(np.diff(t))
    om1 = savgol_filter(th1, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    return t, th1, th2, om1, om2


# ─────────────────────────────────────────────
# COLOURED LINE SEGMENTS
# ─────────────────────────────────────────────

def make_segments(x, y, z):
    """
    Break (x, y, z) arrays into N-1 line segments, each connecting
    consecutive points. Returns array of shape (N-1, 2, 3).
    """
    pts = np.array([x, y, z]).T                    # (N, 3)
    segs = np.stack([pts[:-1], pts[1:]], axis=1)   # (N-1, 2, 3)
    return segs


# ─────────────────────────────────────────────
# STATIC 3D PLOT
# ─────────────────────────────────────────────

def plot_3d(t, th1, th2, om1, label, out_path):
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

    segs  = make_segments(th1, th2, om1)
    colors = cmap(norm((t[:-1] + t[1:]) / 2))   # midpoint colour per segment

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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    print(f"Static figure saved to: {out_path}")
    return fig, ax, lc, norm, cmap


# ─────────────────────────────────────────────
# ROTATING ANIMATION
# ─────────────────────────────────────────────

def make_rotation_animation(fig, ax, out_mp4):
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

    os.makedirs(OUTPUT_DIR, exist_ok=True)
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
    args     = [a for a in sys.argv[1:] if not a.startswith('--')]
    csv_path = args[0] if args else DEFAULT_CSV

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    print(f"Loading {csv_path} ...")
    t, th1, th2, om1, om2 = load(csv_path)
    print(f"  {len(t)} frames  ({t[-1]:.2f}s)")
    print(f"  theta1: [{th1.min():.1f}, {th1.max():.1f}] deg")
    print(f"  theta2: [{th2.min():.1f}, {th2.max():.1f}] deg")
    print(f"  omega1: [{om1.min():.0f}, {om1.max():.0f}] deg/s")

    stem     = os.path.splitext(os.path.basename(csv_path))[0]
    png_path = os.path.join(OUTPUT_DIR, f"{stem}_3d_trajectory.png")
    mp4_path = os.path.join(OUTPUT_DIR, f"{stem}_3d_rotation.mp4")

    fig, ax, lc, norm, cmap = plot_3d(t, th1, th2, om1, stem, png_path)

    if SAVE_MP4:
        make_rotation_animation(fig, ax, mp4_path)
    else:
        plt.show()


if __name__ == "__main__":
    main()
