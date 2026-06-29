"""
Composite video: real pendulum clips next to their theta2 time series.

Three rows, one per driving frequency (0.9 / 1.19 / 1.34 Hz):
  left  = square crop of the actual double-pendulum video,
  right = the theta2(t) trace revealed left-to-right, in lockstep with the video.

The plotted window is the SAME last-10 s segment that theta2_colored.py /
theta2_timeseries_colored.mp4 use, and each video frame is paired with the exact
tracking sample being drawn, so the live motion matches the point on the plot.

Run:   python theta2_video_combo.py          # render the mp4
QA:    python -c "import theta2_video_combo as M; M.qa([120,330], 'qa.png')"
"""
import os
import numpy as np
import pandas as pd
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter
from flip_utils import detect_flips, add_flip_icons, reveal_flips

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
DISP = 660                     # px the crop is resized to (video sharpness)

# ---- layout: wide 16:9 canvas, enlarged squares, minimal whitespace ----
FIG_W, FIG_H = 18.0, 10.13     # ~16:9 so it fills a slide
OUT_DPI = 120                  # -> ~2160x1216 px
WIDTH_RATIOS = [1.0, 4.9]      # video col sized ~= row height (square fills it, no side gap)
WSPACE, HSPACE = 0.16, 0.12    # column gap leaves room for the theta2 label + y-ticks
M_LEFT, M_RIGHT, M_TOP, M_BOT = 0.012, 0.993, 0.985, 0.115  # bottom margin clears the Time axis

# timeseries styling
MARKER_SIZE = 4
LABEL_FS = 22
TICK_FS = 17
FREQ_FS = 21
Y_LIM = (-185, 185)
Y_TICKS = [-180, 0, 180]
X_LIM = (-0.4, T + 0.4)


# ---------------------------------------------------------------------------
def load_clips():
    """Return per-clip window data (t, y, start_frame, n) and open VideoCaptures."""
    data, caps = [], []
    for c in CLIPS:
        df = pd.read_csv(os.path.join(BASE, "measurements", c["stem"], "tracking.csv"))
        df = df.dropna(subset=["time_s", "theta2_deg"])
        tmax = df["time_s"].max()
        w = df[df["time_s"] >= tmax - T].copy()
        t_rel = (w["time_s"] - w["time_s"].min()).to_numpy()
        y = w["theta2_deg"].to_numpy()
        start_frame = int(w["frame"].min())
        cap = cv2.VideoCapture(os.path.join(BASE, "videos", c["stem"] + ".mov"))
        data.append({"t": t_rel, "y": y, "n": len(w), "start": start_frame,
                     "color": c["color"], "freq": c["freq"]})
        caps.append(cap)
    return data, caps


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
    return cv2.resize(c, (DISP, DISP), interpolation=cv2.INTER_AREA)


def build_figure(data):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    gs = fig.add_gridspec(3, 2, width_ratios=WIDTH_RATIOS, wspace=WSPACE, hspace=HSPACE,
                          left=M_LEFT, right=M_RIGHT, top=M_TOP, bottom=M_BOT)
    vid_ims, ts_lines, ts_axes = [], [], []
    blank = np.zeros((DISP, DISP, 3), np.uint8)
    for r, d in enumerate(data):
        axv = fig.add_subplot(gs[r, 0])
        axv.axis("off")
        axv.set_box_aspect(1)
        vid_ims.append(axv.imshow(blank, aspect="auto"))

        axt = fig.add_subplot(gs[r, 1])
        (ln,) = axt.plot([], [], ".", markersize=MARKER_SIZE, color=d["color"], alpha=0.85)
        axt.set_xlim(*X_LIM)
        axt.set_ylim(*Y_LIM)
        axt.set_yticks(Y_TICKS)
        axt.set_ylabel(r"$\theta_2$ (deg)", fontsize=LABEL_FS)
        axt.tick_params(axis="both", labelsize=TICK_FS)
        axt.text(0.012, 0.93, f"{d['freq']:g} Hz", transform=axt.transAxes,
                 fontsize=FREQ_FS, fontweight="bold", va="top", ha="left", color=d["color"])
        if r < 2:
            axt.tick_params(labelbottom=False)
        ts_lines.append(ln)
        ts_axes.append(axt)
    fig.axes[-1].set_xlabel("Time (s)", fontsize=LABEL_FS)

    # flip icons on the chaotic (middle) panel, revealed in real time
    mid = len(data) // 2
    flips = detect_flips(data[mid]["t"], data[mid]["y"])
    flip_items = add_flip_icons(ts_axes[mid], flips, y_icon=150, fontsize=24, animated=True)
    return fig, vid_ims, ts_lines, flip_items


def qa(idxs, out_png):
    """Render a few composite frames (by window index) to a montage PNG — fast layout check."""
    data, caps = load_clips()
    tiles = []
    mid = len(data) // 2
    for k, idx in enumerate(idxs):
        fig, vid_ims, ts_lines, flip_items = build_figure(data)
        for r, (cap, d) in enumerate(zip(caps, data)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, d["start"] + idx)
            ret, frame = cap.read()
            if ret:
                vid_ims[r].set_data(crop_rgb(frame))
            ts_lines[r].set_data(d["t"][:idx + 1], d["y"][:idx + 1])
        reveal_flips(flip_items, data[mid]["t"][idx])
        p = f"{out_png}.{k}.png"
        fig.savefig(p, dpi=70)
        plt.close(fig)
        tiles.append(p)
    from PIL import Image
    ims = [Image.open(p) for p in tiles]
    w = max(i.width for i in ims)
    montage = Image.new("RGB", (w, sum(i.height for i in ims) + 10 * len(ims)), "white")
    yo = 0
    for im in ims:
        montage.paste(im, (0, yo)); yo += im.height + 10
    montage.save(out_png)
    for cap in caps:
        cap.release()
    print("saved", out_png)


def render():
    data, caps = load_clips()
    for cap, d in zip(caps, data):
        cap.set(cv2.CAP_PROP_POS_FRAMES, d["start"])
    fig, vid_ims, ts_lines, flip_items = build_figure(data)
    mid = len(data) // 2

    n_sweep = min(d["n"] for d in data)
    total = n_sweep + int(round(FPS * HOLD_SECONDS))
    writer = FFMpegWriter(
        fps=FPS, bitrate=14000, codec="libx264",
        extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white", "-pix_fmt", "yuv420p"],
    )
    last = [np.zeros((DISP, DISP, 3), np.uint8)] * 3
    with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
        for i in range(total):
            idx = min(i, n_sweep - 1)
            if i < n_sweep:
                for r, cap in enumerate(caps):
                    ret, frame = cap.read()
                    if ret:
                        last[r] = crop_rgb(frame)
                    vid_ims[r].set_data(last[r])
                    ts_lines[r].set_data(data[r]["t"][:idx + 1], data[r]["y"][:idx + 1])
                reveal_flips(flip_items, data[mid]["t"][idx])
            writer.grab_frame()
            if i % 120 == 0:
                print(f"  frame {i}/{total}")
    for cap in caps:
        cap.release()
    print(f"Saved -> {OUT_MP4}  ({total} frames @ {FPS} fps)")


if __name__ == "__main__":
    render()
