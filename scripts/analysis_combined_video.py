"""
analysis_combined_video.py
---------------------------
Renders a side-by-side MP4 combining:
  LEFT  (960×720): original tracked video with arm overlays
  RIGHT (960×720): 3 phase-space panels updating in real time
                   - Configuration space  θ₁ vs θ₂
                   - Phase portrait arm 1 θ₁ vs ω₁
                   - Phase portrait arm 2 θ₂ vs ω₂

Parameter strip along the bottom of the right panel shows:
  θ₁, θ₂, ω₁, ω₂, t, phase

Output: 1920×720 MP4 at source framerate.

Usage:
  python scripts/analysis_combined_video.py
  python scripts/analysis_combined_video.py path/to/tracking.csv path/to/video.mov
"""

import sys
import os
import csv
import numpy as np
import cv2
import matplotlib
matplotlib.use('Agg')          # non-interactive backend — much faster offscreen
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import savgol_filter


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV   = r"C:\dev\chaos\data\DSC_0136_v2_tracking.csv"
DEFAULT_VIDEO = r"C:\dev\chaos\Videos\DSC_0136.mov"
OUTPUT_DIR    = r"C:\dev\chaos\data\figures"
OUTPUT_MP4    = r"C:\dev\chaos\data\figures\DSC_0136_combined.mp4"

PANEL_W   = 960     # width of each half panel
PANEL_H   = 720     # height of both panels
FPS_OUT   = 59.94   # output framerate

SG_WINDOW = 11
SG_POLY   = 3

# Pivot pixel coordinates in original 1280×720 video
PIVOT_ORIG = (608, 355)

# ── Canonical color scheme ──────────────────────────────────────────────
# Matches physical markers and is consistent across all analysis scripts.
# matplotlib hex        OpenCV BGR
COLOR_CONFIG  = '#2196f3'          # blue  — configuration space (θ₁ vs θ₂)
COLOR_ARM1    = '#4caf50'          # green — arm 1 / green physical marker
COLOR_ARM2    = '#ef5350'          # red   — arm 2 / red physical marker

# OpenCV BGR equivalents (R,G,B -> B,G,R)
BGR_ARM1   = (80,  175,  76)       # green
BGR_ARM2   = (80,   83, 239)       # red
BGR_CONFIG = (243, 150,  33)       # blue


# ─────────────────────────────────────────────
# LOAD CSV
# ─────────────────────────────────────────────

def load_csv(path):
    """Load full tracking CSV — all frames, all phases."""
    rows = list(csv.DictReader(open(path)))

    frames  = np.array([int(r['frame'])   for r in rows])
    times   = np.array([float(r['time_s']) for r in rows])
    phases  = [r['phase']                  for r in rows]
    dropouts = np.array([int(r['dropout']) for r in rows])

    th1 = np.array([float(r['theta1_deg']) if r['theta1_deg'] else np.nan for r in rows])
    th2 = np.array([float(r['theta2_deg']) if r['theta2_deg'] else np.nan for r in rows])

    # Compute velocities on clean data only, then interpolate NaNs
    dt = np.nanmean(np.diff(times))

    # Fill NaN with linear interpolation before SG filter
    def fill_nan(arr):
        nans = np.isnan(arr)
        if nans.any():
            idx = np.arange(len(arr))
            arr[nans] = np.interp(idx[nans], idx[~nans], arr[~nans])
        return arr

    th1c = fill_nan(th1.copy())
    th2c = fill_nan(th2.copy())

    om1 = savgol_filter(th1c, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2c, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    # Restore NaNs for dropout frames
    om1[dropouts == 1] = np.nan
    om2[dropouts == 1] = np.nan

    return frames, times, phases, th1, th2, om1, om2, dropouts


# ─────────────────────────────────────────────
# BUILD MATPLOTLIB FIGURE (offscreen)
# ─────────────────────────────────────────────

def setup_figure(th1, th2, om1, om2):
    """
    Create the matplotlib figure and all artists.
    Returns (fig, artists_dict) where artists_dict holds the line/scatter
    objects that get updated each frame.
    """
    # Figure at exactly PANEL_W x PANEL_H pixels
    dpi = 100
    fig = plt.figure(figsize=(PANEL_W / dpi, PANEL_H / dpi), dpi=dpi)
    fig.patch.set_facecolor('#0e0e0e')   # dark background

    gs = gridspec.GridSpec(
        3, 1, figure=fig,
        hspace=0.45,
        left=0.12, right=0.97,
        top=0.96, bottom=0.08
    )

    ax1 = fig.add_subplot(gs[0])   # config space
    ax2 = fig.add_subplot(gs[1])   # phase arm 1
    ax3 = fig.add_subplot(gs[2])   # phase arm 2

    axes = [ax1, ax2, ax3]

    # Compute axis limits from full data (ignoring NaN)
    def lim(arr, margin=0.12):
        a = np.nanmin(arr); b = np.nanmax(arr)
        pad = (b - a) * margin
        return a - pad, b + pad

    xlims = [lim(th1), lim(th1), lim(th2)]
    ylims = [lim(th2), lim(om1), lim(om2)]

    titles = [
        r"$\theta_1$ vs $\theta_2$  (configuration space)",
        r"$\theta_1$ vs $\omega_1$  (phase portrait — arm 1)",
        r"$\theta_2$ vs $\omega_2$  (phase portrait — arm 2)",
    ]
    xlabels = [r"$\theta_1$ (°)", r"$\theta_1$ (°)", r"$\theta_2$ (°)"]
    ylabels = [r"$\theta_2$ (°)", r"$\omega_1$ (°/s)", r"$\omega_2$ (°/s)"]
    colors  = [COLOR_CONFIG, COLOR_ARM1, COLOR_ARM2]

    trace_lines = []
    head_dots   = []

    for ax, xl, yl, title, xlabel, ylabel, color, xlim, ylim in zip(
            axes, xlims, ylims, titles, xlabels, ylabels, colors, xlims, ylims):

        ax.set_facecolor('#1a1a1a')
        ax.set_xlim(xlim); ax.set_ylim(ylim)
        ax.set_title(title, color='#cccccc', fontsize=8, pad=3)
        ax.set_xlabel(xlabel, color='#999999', fontsize=7)
        ax.set_ylabel(ylabel, color='#999999', fontsize=7)
        ax.tick_params(colors='#666666', labelsize=6)
        ax.axhline(0, color='#333333', lw=0.7, zorder=0)
        ax.axvline(0, color='#333333', lw=0.7, zorder=0)
        for spine in ax.spines.values():
            spine.set_edgecolor('#333333')
        ax.grid(True, color='#2a2a2a', lw=0.5)

        # Ghost: full future trajectory very faint
        # (gives visual sense of the attractor shape from the start)
        ax.plot([], [], color=color, lw=0.3, alpha=0.15, zorder=1)

        # Permanent trace
        trace, = ax.plot([], [], color=color, lw=0.8, alpha=0.85, zorder=2)
        trace_lines.append(trace)

        # Current position dot
        head, = ax.plot([], [], 'o', color=color, ms=5, zorder=3,
                        markeredgecolor='white', markeredgewidth=0.5)
        head_dots.append(head)

    # Time / parameter annotation at top
    time_txt = fig.text(0.5, 0.995, '', ha='center', va='top',
                        color='#aaaaaa', fontsize=8,
                        fontfamily='monospace')

    return fig, trace_lines, head_dots, time_txt


def render_figure(fig):
    """Render matplotlib figure to a BGR numpy array (PANEL_H × PANEL_W × 3)."""
    fig.canvas.draw()
    buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    buf = buf.reshape(PANEL_H, PANEL_W, 4)
    return cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)


# ─────────────────────────────────────────────
# LEFT PANEL: resize + overlay
# ─────────────────────────────────────────────

def make_left_panel(frame, phase, t, th1, th2, om1, om2,
                    x_green, y_green, x_red, y_red):
    """
    Scale original 1280x720 frame to 960x720, draw tracking overlay,
    and add parameter strip at the bottom.
    """
    # Scale frame: 1280x720 -> 960x720
    panel = cv2.resize(frame, (PANEL_W, PANEL_H))

    # Scale pivot and marker coords from 1280->960
    sx = PANEL_W / 1280.0
    sy = PANEL_H / 720.0
    pivot = (int(PIVOT_ORIG[0] * sx), int(PIVOT_ORIG[1] * sy))

    def sp(x, y):
        return (int(x * sx), int(y * sy))

    # Dashed circle search zone
    cv2.circle(panel, pivot, int(376 * sx), (80, 80, 80), 1,
               lineType=cv2.LINE_AA)

    # Yellow pivot
    cv2.circle(panel, pivot, 7, (0, 215, 255), -1, lineType=cv2.LINE_AA)

    # Arms and markers
    gp = None
    if not np.isnan(x_green):
        gp = sp(x_green, y_green)
        cv2.line(panel, pivot, gp, (0, 200, 0), 2, lineType=cv2.LINE_AA)
        cv2.circle(panel, gp, 7, (0, 255, 0), -1, lineType=cv2.LINE_AA)

    if not np.isnan(x_red):
        rp = sp(x_red, y_red)
        cv2.circle(panel, rp, 7, (0, 0, 255), -1, lineType=cv2.LINE_AA)
        if gp is not None:
            cv2.line(panel, gp, rp, (0, 0, 200), 2, lineType=cv2.LINE_AA)

    # ── Parameter strip at bottom ──────────────────────────────────────
    # Two-row grid, ASCII only (cv2.putText does not support Unicode)
    strip_h = 80
    y_top   = PANEL_H - strip_h

    # Dark background
    overlay = panel.copy()
    cv2.rectangle(overlay, (0, y_top), (PANEL_W, PANEL_H), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.72, panel, 0.28, 0, panel)

    # Helper: format a value or show --- if NaN
    def fv(v, decimals=1):
        return f"{v:+.{decimals}f}" if not np.isnan(v) else "  ---  "

    # Row 1: phase label + time
    phase_col = (80, 255, 80) if phase == 'free_swing' else (100, 100, 255)
    cv2.putText(panel, phase.upper(),
                (10, y_top + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, phase_col, 1,
                lineType=cv2.LINE_AA)
    cv2.putText(panel, f"t = {t:.3f} s",
                (220, y_top + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1,
                lineType=cv2.LINE_AA)

    # Row 2: four parameters in a 4-column grid, colour-coded by arm
    # Each column is PANEL_W/4 = 240px wide
    col_w = PANEL_W // 4
    y2    = y_top + 58
    font  = cv2.FONT_HERSHEY_SIMPLEX
    fs    = 0.50
    swatch_size = 10   # colored square side length

    params = [
        (f"th1 = {fv(th1)} deg",      10,              BGR_ARM1),
        (f"th2 = {fv(th2)} deg",      10 + col_w,      BGR_ARM2),
        (f"om1 = {fv(om1, 0)} deg/s", 10 + 2 * col_w, BGR_ARM1),
        (f"om2 = {fv(om2, 0)} deg/s", 10 + 3 * col_w, BGR_ARM2),
    ]
    for text, x, color in params:
        # Small color swatch before the label
        sy1 = y2 - swatch_size
        sy2 = y2
        cv2.rectangle(panel, (x, sy1), (x + swatch_size, sy2), color, -1)
        cv2.putText(panel, text, (x + swatch_size + 5, y2),
                    font, fs, color, 1, lineType=cv2.LINE_AA)

    return panel


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    csv_path   = args[0] if len(args) > 0 else DEFAULT_CSV
    video_path = args[1] if len(args) > 1 else DEFAULT_VIDEO

    print(f"CSV:   {csv_path}")
    print(f"Video: {video_path}")

    # ── Load data ──
    print("Loading CSV ...")
    frames, times, phases, th1, th2, om1, om2, dropouts = load_csv(csv_path)
    N = len(frames)
    print(f"  {N} frames, t_max = {times[-1]:.2f}s")

    # Load x/y coordinates too (for left panel overlay)
    rows = list(csv.DictReader(open(csv_path)))
    xg = np.array([float(r['x_green']) if r['x_green'] else np.nan for r in rows])
    yg = np.array([float(r['y_green']) if r['y_green'] else np.nan for r in rows])
    xr = np.array([float(r['x_red'])   if r['x_red']   else np.nan for r in rows])
    yr = np.array([float(r['y_red'])   if r['y_red']   else np.nan for r in rows])

    # ── Set up matplotlib figure ──
    print("Setting up figure ...")
    fig, trace_lines, head_dots, time_txt = setup_figure(th1, th2, om1, om2)

    # Pre-compute XY data for each panel
    XY = [(th1, th2), (th1, om1), (th2, om2)]

    # ── Open video ──
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {video_path}")
        return
    video_fps = cap.get(cv2.CAP_PROP_FPS) or FPS_OUT

    # ── Set up writer ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(OUTPUT_MP4, fourcc, video_fps,
                             (PANEL_W * 2, PANEL_H))

    # ── Render loop ──
    print(f"Rendering {N} frames → {OUTPUT_MP4}")
    print("(This will take several minutes)\n")

    step = max(1, N // 40)   # progress update every 2.5%

    for i in range(N):
        # Read video frame
        ret, vframe = cap.read()
        if not ret:
            print(f"\nWARNING: video ended at frame {i}")
            break

        # ── Update matplotlib plots ──
        for panel_idx, (x, y) in enumerate(XY):
            # Mask NaN for clean plotting
            valid = ~(np.isnan(x[:i+1]) | np.isnan(y[:i+1]))
            xv = x[:i+1][valid]
            yv = y[:i+1][valid]
            trace_lines[panel_idx].set_data(xv, yv)
            if valid.any():
                head_dots[panel_idx].set_data([x[i]], [y[i]])
            else:
                head_dots[panel_idx].set_data([], [])

        time_txt.set_text(
            f"frame {frames[i]:4d} / {N}   "
            f"t = {times[i]:.3f} s   "
            f"{'FREE SWING' if phases[i] == 'free_swing' else 'HOLDING'}"
        )

        # ── Render matplotlib → numpy ──
        right_panel = render_figure(fig)

        # ── Build left panel ──
        left_panel = make_left_panel(
            vframe, phases[i], times[i],
            th1[i], th2[i], om1[i], om2[i],
            xg[i], yg[i], xr[i], yr[i]
        )

        # ── Stack and write ──
        composite = np.hstack([left_panel, right_panel])
        writer.write(composite)

        # Progress
        if i % step == 0 or i == N - 1:
            pct = 100 * (i + 1) // N
            bar = '█' * (pct // 5) + '░' * (20 - pct // 5)
            eta_frames = N - i - 1
            print(f"  [{bar}] {pct:3d}%  frame {i+1}/{N}", end='\r', flush=True)

    cap.release()
    writer.release()
    plt.close(fig)

    print(f"\n\nDone. Saved to: {OUTPUT_MP4}")


if __name__ == "__main__":
    main()
