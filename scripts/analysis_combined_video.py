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
    colors  = ['#4caf50', '#42a5f5', '#ef5350']

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
    buf = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
    buf = buf.reshape(PANEL_H, PANEL_W, 3)
    return cv2.cvtColor(buf, cv2.COLOR_RGB2BGR)


# ─────────────────────────────────────────────
# LEFT PANEL: resize + overlay
# ─────────────────────────────────────────────

def make_left_panel(frame, phase, t, th1, th2, om1, om2,
                    x_green, y_green, x_red, y_red):
    """
    Scale original 1280×720 frame to 960×720, draw tracking overlay,
    and add parameter strip at the bottom.
    """
    # Scale frame: 1280×720 → 960×720
    panel = cv2.resize(frame, (PANEL_W, PANEL_H))

    # Scale pivot and marker coords from 1280→960
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
    if not np.isnan(x_green):
        gp = sp(x_green, y_green)
        cv2.line(panel, pivot, gp, (0, 200, 0), 2, lineType=cv2.LINE_AA)
        cv2.circle(panel, gp, 7, (0, 255, 0), -1, lineType=cv2.LINE_AA)

    if not np.isnan(x_red):
        rp = sp(x_red, y_red)
        cv2.circle(panel, rp, 7, (0, 0, 255), -1, lineType=cv2.LINE_AA)
        if not np.isnan(x_green):
            cv2.line(panel, gp, rp, (0, 0, 200), 2, lineType=cv2.LINE_AA)

    # Dark strip at bottom for parameters
    strip_h = 72
    overlay = panel.copy()
    cv2.rectangle(overlay, (0, PANEL_H - strip_h), (PANEL_W, PANEL_H),
                  (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, panel, 0.3, 0, panel)

    # Parameter text
    phase_col = (80, 255, 80) if phase == 'free_swing' else (80, 80, 255)
    cv2.putText(panel, phase.upper(),
                (12, PANEL_H - strip_h + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, phase_col, 1,
                lineType=cv2.LINE_AA)

    def fmt(v, unit):
        return f"{v:+7.1f} {unit}" if not np.isnan(v) else "  ---    "

    params = [
        (f"t  = {t:6.2f} s",          (12,  PANEL_H - strip_h + 42)),
        (f"θ₁ = {fmt(th1,'°')}",       (12,  PANEL_H - 20)),
        (f"θ₂ = {fmt(th2,'°')}",       (250, PANEL_H - 20)),
        (f"ω₁ = {fmt(om1,'°/s')}",     (490, PANEL_H - 20)),
        (f"ω₂ = {fmt(om2,'°/s')}",     (730, PANEL_H - 20)),
    ]
    for text, pos in params:
        cv2.putText(panel, text, pos,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1,
                    lineType=cv2.LINE_AA)

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
