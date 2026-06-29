"""
Composite video: real pendulum clips next to their theta2 time series.

Three rows, one per driving frequency (0.9 / 1.19 / 1.34 Hz):
  left  = square crop of the actual double-pendulum video,
  right = the theta2(t) trace revealed left-to-right, in lockstep with the video.

The plotted window is the SAME last-10 s segment that theta2_colored.py /
theta2_timeseries_colored.mp4 use, and each video frame is paired with the exact
tracking sample being drawn, so the live motion matches the point on the plot.

Run:  python theta2_video_combo.py
"""
import os
import numpy as np
import pandas as pd
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
OUT_MP4 = os.path.join(HERE, "theta2_video_combo.mp4")

# clips top -> bottom, with the slide colours (chaotic middle = red)
CLIPS = [
    {"freq": 0.9,  "stem": "3.2V_0.9Hz",  "color": "green"},
    {"freq": 1.19, "stem": "3.2V_1.19Hz", "color": "red"},
    {"freq": 1.34, "stem": "3.2V_1.34Hz", "color": "green"},
]

T = 10.0                       # seconds shown (last-T window, matches static fig)
VID_FPS = 60000 / 1001         # 59.94, true clip rate
FPS = 60                       # output fps (≈ real time)
HOLD_SECONDS = 1.5             # freeze on completed figure

# square crop on the 1280x720 frame (contains full swing + pivot for all clips)
CX0, CY0, CSIDE = 245, 35, 680
DISP = 430                     # px the crop is resized to for display

# timeseries styling (scaled down from the standalone figure for the 3-up stack)
MARKER_SIZE = 4
LABEL_FS = 19
TICK_FS = 15
FREQ_FS = 18
Y_LIM = (-185, 185)
Y_TICKS = [-180, 0, 180]
X_LIM = (-0.4, T + 0.4)

FIG_W, FIG_H, OUT_DPI = 14, 9, 110


# ---------------------------------------------------------------------------
# Load window data + locate the matching video frames for each clip
# ---------------------------------------------------------------------------
def load_clip(stem):
    df = pd.read_csv(os.path.join(BASE, "measurements", stem, "tracking.csv"))
    df = df.dropna(subset=["time_s", "theta2_deg"])
    tmax = df["time_s"].max()
    w = df[df["time_s"] >= tmax - T].copy()
    t_rel = (w["time_s"] - w["time_s"].min()).to_numpy()
    y = w["theta2_deg"].to_numpy()
    start_frame = int(w["frame"].min())
    return t_rel, y, start_frame, len(w)


data = []
caps = []
for c in CLIPS:
    t_rel, y, start_frame, n = load_clip(c["stem"])
    cap = cv2.VideoCapture(os.path.join(BASE, "videos", c["stem"] + ".mov"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    data.append({"t": t_rel, "y": y, "n": n, "color": c["color"], "freq": c["freq"]})
    caps.append(cap)
    print(f"{c['freq']} Hz: {n} frames from video frame {start_frame}")

N_SWEEP = min(d["n"] for d in data)           # all 600; align by index
N_HOLD = int(round(FPS * HOLD_SECONDS))
TOTAL = N_SWEEP + N_HOLD

# ---------------------------------------------------------------------------
# Figure: 3 rows x (video | timeseries)
# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(FIG_W, FIG_H))
gs = fig.add_gridspec(3, 2, width_ratios=[1.0, 2.4], wspace=0.06, hspace=0.30,
                      left=0.04, right=0.985, top=0.98, bottom=0.085)

vid_axes, vid_ims, ts_axes, ts_lines = [], [], [], []
blank = np.zeros((DISP, DISP, 3), np.uint8)
for r, d in enumerate(data):
    axv = fig.add_subplot(gs[r, 0])
    axv.axis("off")
    axv.set_box_aspect(1)
    im = axv.imshow(blank, aspect="auto")
    vid_axes.append(axv)
    vid_ims.append(im)

    axt = fig.add_subplot(gs[r, 1])
    (ln,) = axt.plot([], [], ".", markersize=MARKER_SIZE, color=d["color"], alpha=0.85)
    axt.set_xlim(*X_LIM)
    axt.set_ylim(*Y_LIM)
    axt.set_yticks(Y_TICKS)
    axt.set_ylabel(r"$\theta_2$ (deg)", fontsize=LABEL_FS)
    axt.tick_params(axis="both", labelsize=TICK_FS)
    axt.text(0.015, 0.92, f"{d['freq']:g} Hz", transform=axt.transAxes,
             fontsize=FREQ_FS, fontweight="bold", va="top", ha="left",
             color=d["color"])
    if r < 2:
        axt.tick_params(labelbottom=False)
    ts_axes.append(axt)
    ts_lines.append(ln)
ts_axes[-1].set_xlabel("Time (s)", fontsize=LABEL_FS)


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
    return cv2.resize(c, (DISP, DISP), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
# Render (sequential reads -> low memory, frame-exact sync)
# ---------------------------------------------------------------------------
writer = FFMpegWriter(
    fps=FPS, bitrate=12000, codec="libx264",
    extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white", "-pix_fmt", "yuv420p"],
)

last_frames = [blank, blank, blank]
with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
    for i in range(TOTAL):
        idx = min(i, N_SWEEP - 1)
        if i < N_SWEEP:
            for r, cap in enumerate(caps):
                ret, frame = cap.read()
                if ret:
                    last_frames[r] = crop_rgb(frame)
                vid_ims[r].set_data(last_frames[r])
                d = data[r]
                ts_lines[r].set_data(d["t"][:idx + 1], d["y"][:idx + 1])
        writer.grab_frame()
        if i % 60 == 0:
            print(f"  frame {i}/{TOTAL}")

for cap in caps:
    cap.release()
print(f"Saved -> {OUT_MP4}  ({TOTAL} frames @ {FPS} fps)")
