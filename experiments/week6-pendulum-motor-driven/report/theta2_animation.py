"""
Animated version of theta2_colored.py (slide-12 figure).

Reveals the three theta2 time series left-to-right in real time (a synchronized
10 s sweep across all panels), ending on the exact static figure. Same layout,
colours and styling as theta2_colored.py. Renders to mp4 via ffmpeg.

Run:  python theta2_animation.py
"""
import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter
from flip_utils import detect_flips, add_flip_icons, reveal_flips

# =============================================================================
# 1. CONFIGURATION  (kept in sync with theta2_colored.py)
# =============================================================================
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "measurements")
OUT_MP4 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theta2_timeseries_colored.mp4")
T = 10                              # seconds of data shown (window + sweep length)
COL_TIME = "time_s"
COL_THETA2 = "theta2_deg"

CHOSEN_FREQS = [0.9, 1.19, 1.34]    # top -> bottom (match slide labels)
PANEL_COLORS = ["green", "red", "green"]  # non-chaotic green, chaotic (middle) red

# --- PLOT SETTINGS (mirror the static figure) ---
MARKER_SIZE = 4
LABEL_FONT_SIZE = 28
TICK_FONT_SIZE = 24
TICK_PAD = 10
LABEL_PAD = 14
HSPACE = 0.45
FIG_WIDTH = 16
PANEL_HEIGHT = 2.8
Y_LIM = (-185, 185)
Y_TICKS = [-180, 0, 180]
X_LIM = (-0.4, T + 0.4)

# --- ANIMATION SETTINGS ---
FPS = 60                # match the 60 fps tracking data -> 1 sample/frame
VIDEO_DPI = 120         # 16x8.4in @120dpi -> 1920x1008 px
HOLD_SECONDS = 1.5      # freeze on the completed figure at the end
SWEEP = True            # draw a faint vertical "now" cursor
# ---------------------

csv_files = glob.glob(os.path.join(BASE_DIR, "*", "tracking.csv"), recursive=True)


def find_file(freq):
    for fp in csv_files:
        m = re.search(r"(\d+(?:\.\d+)?)\s*Hz", fp, re.IGNORECASE)
        if m and float(m.group(1)) == freq:
            return fp
    return None


# =============================================================================
# 2. LOAD SERIES (last T seconds, time-shifted to start at 0)
# =============================================================================
series = []  # list of dicts: t, y, color
for freq, color in zip(CHOSEN_FREQS, PANEL_COLORS):
    fp = find_file(freq)
    if fp is None:
        raise FileNotFoundError(f"No tracking.csv for {freq} Hz under {BASE_DIR}")
    df = pd.read_csv(fp).dropna(subset=[COL_TIME, COL_THETA2])
    t_max = df[COL_TIME].max()
    seg = df[df[COL_TIME] >= (t_max - T)].copy()
    t = (seg[COL_TIME] - seg[COL_TIME].min()).to_numpy()
    y = seg[COL_THETA2].to_numpy()
    series.append({"t": t, "y": y, "color": color})
    print(f"{freq} Hz: {len(t)} pts, span {t.min():.2f}-{t.max():.2f} s")

# =============================================================================
# 3. BUILD FIGURE (identical styling to the static export)
# =============================================================================
fig, axs = plt.subplots(
    len(CHOSEN_FREQS), 1,
    figsize=(FIG_WIDTH, PANEL_HEIGHT * len(CHOSEN_FREQS)),
    sharex=True,
    gridspec_kw={"hspace": HSPACE},
)
axs = np.atleast_1d(axs)
fig.subplots_adjust(left=0.085, right=0.985, top=0.97, bottom=0.13)

lines, cursors = [], []
for i, (ax, s) in enumerate(zip(axs, series)):
    (ln,) = ax.plot([], [], ".", markersize=MARKER_SIZE, color=s["color"], alpha=0.8)
    lines.append(ln)
    cur = ax.axvline(0, color="0.35", lw=1.2, alpha=0.0) if SWEEP else None
    cursors.append(cur)

    ax.set_xlim(*X_LIM)
    ax.set_ylim(*Y_LIM)
    ax.set_yticks(Y_TICKS)
    if i == len(CHOSEN_FREQS) // 2:
        ax.set_ylabel(r"$\theta_2$ (deg)", fontsize=LABEL_FONT_SIZE, labelpad=LABEL_PAD)
    ax.tick_params(axis="both", which="major", labelsize=TICK_FONT_SIZE, pad=TICK_PAD)

axs[-1].set_xlabel("Time (s)", fontsize=LABEL_FONT_SIZE, labelpad=LABEL_PAD)

# =============================================================================
# 4. ANIMATE: synchronized left-to-right reveal in real time
# =============================================================================
n_sweep = int(round(FPS * T))
n_hold = int(round(FPS * HOLD_SECONDS))
total_frames = n_sweep + n_hold


def update(frame):
    tc = min(frame, n_sweep) / FPS  # data-seconds elapsed; clamps during the hold
    artists = []
    for ln, cur, s in zip(lines, cursors, series):
        m = s["t"] <= tc
        ln.set_data(s["t"][m], s["y"][m])
        artists.append(ln)
        if cur is not None:
            cur.set_xdata([tc, tc])
            cur.set_alpha(0.0 if frame >= n_sweep else 0.5)
            artists.append(cur)
    return artists


anim = FuncAnimation(fig, update, frames=total_frames, interval=1000.0 / FPS, blit=False)

writer = FFMpegWriter(
    fps=FPS, bitrate=8000, codec="libx264",
    # pad to even width/height (libx264 requires it; canvas can be odd by 1px)
    extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white",
                "-pix_fmt", "yuv420p"],
)
anim.save(OUT_MP4, writer=writer, dpi=VIDEO_DPI)
print(f"Saved animation -> {OUT_MP4}  ({total_frames} frames, {FPS} fps)")
