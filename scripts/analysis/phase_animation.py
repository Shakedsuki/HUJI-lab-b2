"""
analysis_animate.py
--------------------
Animated phase-space visualisation for double pendulum tracking data.

Three panels animated simultaneously in real time:
  1. Configuration space:   theta1 vs theta2
  2. Phase portrait arm 1:  theta1 vs omega1
  3. Phase portrait arm 2:  theta2 vs omega2

The trajectory builds up frame by frame, with a bright dot marking the
current state and a fading trail showing recent history.

Usage:
  python scripts/analysis/phase_animation.py
  python scripts/analysis/phase_animation.py path/to/tracking.csv

Optional: save to MP4 (requires ffmpeg):
  python scripts/analysis/phase_animation.py --save
"""

import sys

# Force UTF-8 stdout so unicode glyphs (θ, ω) don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
import os
import csv
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from scipy.signal import savgol_filter


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV  = r"C:\dev\chaos\data\long_recording_tracking.csv"
OUTPUT_DIR   = r"C:\dev\chaos\data\figures"
OUTPUT_MP4   = r"C:\dev\chaos\data\figures\long_recording_phase_animation.mp4"

SG_WINDOW    = 11
SG_POLY      = 3

INTERVAL_MS  = 16     # ~60fps playback (matches 59.94fps source)
SKIP         = 1      # process every Nth frame (1 = all frames, 2 = half speed)

SAVE_MP4     = "--save" in sys.argv

# ── Canonical color scheme ──────────────────────────────────────────────
COLOR_CONFIG = 'tab:blue'    # configuration space (θ₁ vs θ₂)
COLOR_ARM1   = 'tab:green'   # arm 1 / green physical marker
COLOR_ARM2   = 'tab:red'     # arm 2 / red physical marker


# ─────────────────────────────────────────────
# LOAD & PREPARE
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

    # Unwrap before differentiating: the CSV stores angles wrapped to
    # [-180, 180], and SG-differentiating across a wrap produces phantom
    # ~360°/frame spikes that smear into thousand-deg/s plateaus.
    th1u = np.degrees(np.unwrap(np.radians(th1)))
    th2u = np.degrees(np.unwrap(np.radians(th2)))

    om1 = savgol_filter(th1u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    return t, th1, th2, om1, om2


def break_arrays(arrays, wrap_mask):
    """
    Set position (i + 1) to NaN in every array where wrap_mask[i] is True.
    matplotlib draws no line through NaN, so the trace breaks cleanly at
    each ±180° wrap instead of streaking across the whole plot.
    """
    out = []
    for a in arrays:
        b = np.asarray(a, dtype=float).copy()
        b[1:][wrap_mask] = np.nan
        out.append(b)
    return out


# ─────────────────────────────────────────────
# ANIMATION
# ─────────────────────────────────────────────

def animate(path):
    print(f"Loading {path} ...")
    t, th1, th2, om1, om2 = load(path)
    N = len(t)
    print(f"  {N} frames  ({t[-1]:.2f}s)")

    # Sub-sample if requested
    idx  = np.arange(0, N, SKIP)
    t    = t[idx];  th1 = th1[idx]; th2 = th2[idx]
    om1  = om1[idx]; om2 = om2[idx]
    N    = len(idx)

    # ── Figure layout ──────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.93,
                        bottom=0.12, wspace=0.35)

    titles = [
        r"Configuration space  $\theta_1$ vs $\theta_2$",
        r"Phase portrait — arm 1",
        r"Phase portrait — arm 2",
    ]
    xlabels = [r"$\theta_1$ (deg)", r"$\theta_1$ (deg)", r"$\theta_2$ (deg)"]
    ylabels = [r"$\theta_2$ (deg)", r"$\omega_1$ (deg/s)", r"$\omega_2$ (deg/s)"]

    # Compute wrap-break masks per panel. Config space breaks at either
    # arm's wrap; arm-1 / arm-2 portraits each break at their own wrap.
    diff_th1 = np.abs(np.diff(th1)) > 180
    diff_th2 = np.abs(np.diff(th2)) > 180
    mask_config = diff_th1 | diff_th2

    # Trace arrays (NaN-broken at wraps) — used for the building line.
    th1c, th2c   = break_arrays([th1, th2], mask_config)
    th1p, om1p   = break_arrays([th1, om1], diff_th1)
    th2p, om2p   = break_arrays([th2, om2], diff_th2)

    # Trace data per panel.
    XY = [
        (th1c, th2c),
        (th1p, om1p),
        (th2p, om2p),
    ]
    # Head-dot data per panel — original (non-broken) arrays so the dot
    # never disappears, even on a wrap frame.
    HEAD_XY = [
        (th1, th2),
        (th1, om1),
        (th2, om2),
    ]

    for ax, title, xl, yl, (x, y) in zip(axes, titles, xlabels, ylabels, XY):
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(xl);  ax.set_ylabel(yl)
        # NaN-aware min/max for axis limits.
        ax.set_xlim(np.nanmin(x) * 1.12, np.nanmax(x) * 1.12)
        ax.set_ylim(np.nanmin(y) * 1.12, np.nanmax(y) * 1.12)
        ax.axhline(0, color='gray', lw=0.5, ls='--', zorder=0)
        ax.axvline(0, color='gray', lw=0.5, ls='--', zorder=0)
        ax.grid(True, alpha=0.25)

    # ── Artists ────────────────────────────────
    # Each panel gets:
    #   - a permanent trace (builds up as animation progresses)
    #   - a head dot (current position, always on top)

    COLORS = [COLOR_CONFIG, COLOR_ARM1, COLOR_ARM2]

    traces = []
    heads  = []

    for ax, (x, y), col in zip(axes, XY, COLORS):
        # Permanent trace — grows frame by frame
        trace, = ax.plot([], [], color=col, lw=0.9, alpha=0.85, zorder=2)
        traces.append(trace)

        # Head: current point
        head, = ax.plot([], [], 'o', color=col, ms=7, zorder=3,
                        markeredgecolor='white', markeredgewidth=0.8)
        heads.append(head)

    # Time label
    time_txt = fig.text(0.5, 0.97, '', ha='center', va='top',
                        fontsize=11, color='0.3')

    # ── Update function ────────────────────────
    def update(frame):
        i = frame

        for panel, ((x, y), (xh, yh)) in enumerate(zip(XY, HEAD_XY)):
            # Permanent trace — show everything up to current frame
            # (uses NaN-broken arrays so wraps don't streak).
            traces[panel].set_data(x[:i+1], y[:i+1])
            # Head dot uses the un-broken arrays so it never disappears,
            # even when the trace just broke for a wrap.
            if i < N:
                heads[panel].set_data([xh[i]], [yh[i]])

        time_txt.set_text(f"t = {t[i]:.2f} s")

        return traces + heads + [time_txt]

    # ── Build animation ────────────────────────
    anim = animation.FuncAnimation(
        fig, update,
        frames=N,
        interval=INTERVAL_MS,
        blit=False,
    )

    if SAVE_MP4:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        writer = animation.FFMpegWriter(fps=int(1000 / INTERVAL_MS),
                                        bitrate=2000)
        print(f"Saving {N} frames to {OUTPUT_MP4} ...")
        print("This may take a few minutes.")

        # Progress callback — print every 5%
        step = max(1, N // 20)

        with writer.saving(fig, OUTPUT_MP4, dpi=150):
            for i in range(N):
                update(i)
                writer.grab_frame()
                if i % step == 0 or i == N - 1:
                    pct = 100 * (i + 1) // N
                    bar = '#' * (pct // 5) + '.' * (20 - pct // 5)
                    print(f"  [{bar}] {pct:3d}%  frame {i+1}/{N}",
                          end='\r', flush=True)

        print(f"\nSaved to: {OUTPUT_MP4}")
    else:
        plt.show()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_path = args[0] if args else DEFAULT_CSV

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    ext = os.path.splitext(csv_path)[1].lower()
    if ext != ".csv":
        print(f"ERROR: expected a tracking CSV, got '{csv_path}' (extension '{ext}').")
        print("       This script reads the per-frame angle CSV, not videos.")
        print(f"       Try:  python {os.path.basename(__file__)}    (uses default CSV)")
        sys.exit(2)

    animate(csv_path)
