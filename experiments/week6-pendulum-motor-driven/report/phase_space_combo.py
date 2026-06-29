"""
Composite phase-space video: animated theta2-omega2 portraits beside the clips.

Slide-16 treatment, the phase-space analogue of theta2_video_combo.py.
Three columns, one per driving frequency (0.9 / 1.19 / 1.34 Hz):
  top    = the theta2-omega2 phase portrait, drawn in real time (the attractor
           fills in as the trajectory evolves; a dot marks the current state),
  bottom = the same square crop of the actual pendulum video.

Same last-10 s window and 1:1 frame<->sample sync as the timeseries combo, so
the moving dot in phase space matches the live pendulum below it.

omega2 = SG-smoothed derivative of theta2 (scripts/utils/kinematics), the
repo's single source of truth, exactly as the static phase_portrait_row uses.

Run:   python phase_space_combo.py
QA:    python -c "import phase_space_combo as M; M.qa([200,400,599],'qa.png')"
"""
import os
import sys
import numpy as np
import pandas as pd
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "scripts", "utils"))
from kinematics import angular_velocity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
OUT_MP4 = os.path.join(HERE, "phase_space_combo.mp4")

# columns left -> right
CLIPS = [
    {"freq": 0.9,  "stem": "3.2V_0.9Hz"},
    {"freq": 1.19, "stem": "3.2V_1.19Hz"},
    {"freq": 1.34, "stem": "3.2V_1.34Hz"},
]

T = 10.0
FPS = 60
HOLD_SECONDS = 1.5

# same square crop as the timeseries combo
CX0, CY0, CSIDE = 245, 35, 680
DISP = 480

# phase-portrait axes
TH_LIM = (-185, 185)
TH_TICKS = [-180, 0, 180]
OM_LIM = (-1500, 1500)
OM_TICKS = [-1500, 0, 1500]
ARM2 = "#c0392b"          # arm-2 red (repo convention, matches static slide)
TRAIL_MS = 3.2            # accumulated-points marker size
HEAD_MS = 9              # current-state dot

# styling / layout (16:9 slide)
FIG_W, FIG_H, OUT_DPI = 16.0, 9.0, 120
HEIGHT_RATIOS = [1.32, 1.0]
WSPACE, HSPACE = 0.20, 0.10
M_LEFT, M_RIGHT, M_TOP, M_BOT = 0.058, 0.992, 0.925, 0.07
TITLE_FS, LABEL_FS, TICK_FS = 24, 19, 14


def load_clips():
    data, caps = [], []
    for c in CLIPS:
        df = pd.read_csv(os.path.join(BASE, "measurements", c["stem"], "tracking.csv"))
        df = df.dropna(subset=["time_s", "theta2_deg"])
        tmax = df["time_s"].max()
        w = df[df["time_s"] >= tmax - T].copy()
        t = w["time_s"].to_numpy()
        th = w["theta2_deg"].to_numpy()
        om = angular_velocity(th, t)
        cap = cv2.VideoCapture(os.path.join(BASE, "videos", c["stem"] + ".mov"))
        data.append({"th": th, "om": om, "n": len(w),
                     "start": int(w["frame"].min()), "freq": c["freq"]})
        caps.append(cap)
    return data, caps


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
    return cv2.resize(c, (DISP, DISP), interpolation=cv2.INTER_AREA)


def build_figure(data):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    gs = fig.add_gridspec(2, 3, height_ratios=HEIGHT_RATIOS, wspace=WSPACE, hspace=HSPACE,
                          left=M_LEFT, right=M_RIGHT, top=M_TOP, bottom=M_BOT)
    trails, heads, vid_ims = [], [], []
    blank = np.zeros((DISP, DISP, 3), np.uint8)
    for col, d in enumerate(data):
        axp = fig.add_subplot(gs[0, col])
        (trail,) = axp.plot([], [], ".", ms=TRAIL_MS, color=ARM2, alpha=0.85, zorder=3)
        (head,) = axp.plot([], [], "o", ms=HEAD_MS, mfc="black", mec="white", mew=1.2, zorder=5)
        axp.set_xlim(*TH_LIM)
        axp.set_ylim(*OM_LIM)
        axp.set_xticks(TH_TICKS)
        axp.set_yticks(OM_TICKS)
        axp.tick_params(labelsize=TICK_FS)
        axp.set_title(f"{d['freq']:g} Hz", fontsize=TITLE_FS, fontweight="bold", pad=8)
        axp.set_xlabel(r"$\theta_2$ (deg)", fontsize=LABEL_FS)
        if col == 0:
            axp.set_ylabel(r"$\omega_2$ (deg/s)", fontsize=LABEL_FS)
        else:
            axp.tick_params(labelleft=False)
        trails.append(trail)
        heads.append(head)

        axv = fig.add_subplot(gs[1, col])
        axv.axis("off")
        axv.set_box_aspect(1)
        vid_ims.append(axv.imshow(blank, aspect="auto"))
    return fig, trails, heads, vid_ims


def qa(idxs, out_png):
    data, caps = load_clips()
    tiles = []
    for k, idx in enumerate(idxs):
        fig, trails, heads, vid_ims = build_figure(data)
        for col, (cap, d) in enumerate(zip(caps, data)):
            trails[col].set_data(d["th"][:idx + 1], d["om"][:idx + 1])
            heads[col].set_data([d["th"][idx]], [d["om"][idx]])
            cap.set(cv2.CAP_PROP_POS_FRAMES, d["start"] + idx)
            ret, frame = cap.read()
            if ret:
                vid_ims[col].set_data(crop_rgb(frame))
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
    fig, trails, heads, vid_ims = build_figure(data)

    n_sweep = min(d["n"] for d in data)
    total = n_sweep + int(round(FPS * HOLD_SECONDS))
    writer = FFMpegWriter(
        fps=FPS, bitrate=14000, codec="libx264",
        extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white", "-pix_fmt", "yuv420p"],
    )
    last = [np.zeros((DISP, DISP, 3), np.uint8)] * len(data)
    with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
        for i in range(total):
            idx = min(i, n_sweep - 1)
            if i < n_sweep:
                for col, cap in enumerate(caps):
                    d = data[col]
                    trails[col].set_data(d["th"][:idx + 1], d["om"][:idx + 1])
                    heads[col].set_data([d["th"][idx]], [d["om"][idx]])
                    ret, frame = cap.read()
                    if ret:
                        last[col] = crop_rgb(frame)
                    vid_ims[col].set_data(last[col])
            writer.grab_frame()
            if i % 120 == 0:
                print(f"  frame {i}/{total}")
    for cap in caps:
        cap.release()
    print(f"Saved -> {OUT_MP4}  ({total} frames @ {FPS} fps)")


if __name__ == "__main__":
    render()
