"""
Composite phase-space video for slide 16 (staged).

Top row: the original FIVE theta2-omega2 phase portraits in one row
(0.9 / 0.94 / 1.19 / 1.28 / 1.34 Hz), arm-2 red, shared axes.
Bottom row: the actual pendulum crop under the first / middle / last columns
only (0.9 / 1.19 / 1.34 Hz).

The action is staged left-to-right rather than simultaneous:
  1. 0.9 Hz  plays  (phase portrait animates in real time + its video plays)
  2. 0.94 Hz reveals its finished portrait (no video), slight pause
  3. 1.19 Hz plays   (animates + video), slight pause
  4. 1.28 Hz reveals its finished portrait (no video), slight pause
  5. 1.34 Hz plays   (animates + video), final hold
Each cell starts empty; once shown it persists. Animated videos freeze on
their last frame afterwards. A current-state dot shows only for the column
currently animating.

omega2 = SG-smoothed derivative of theta2 (scripts/utils/kinematics).

Run:   python phase_space_combo.py
QA:    python -c "import phase_space_combo as M; M.qa('qa.png')"
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

# five columns left -> right; video only for the first / middle / last
CLIPS = [
    {"freq": 0.9,  "stem": "3.2V_0.9Hz",  "video": True},
    {"freq": 0.94, "stem": "3.2V_0.94Hz", "video": False},
    {"freq": 1.19, "stem": "3.2V_1.19Hz", "video": True},
    {"freq": 1.28, "stem": "3.2V_1.28Hz", "video": False},
    {"freq": 1.34, "stem": "3.2V_1.34Hz", "video": True},
]

T = 10.0
FPS = 60
PAUSE_S = 1.2          # slight pause between stages
END_HOLD_S = 1.5       # final freeze

# same square crop as the timeseries combo
CX0, CY0, CSIDE = 245, 35, 680
DISP = 440

# phase-portrait axes (match the static slide)
TH_LIM, TH_TICKS = (-185, 185), [-180, -90, 0, 90, 180]
OM_LIM, OM_TICKS = (-1500, 1500), [-1500, -1000, -500, 0, 500, 1000, 1500]
ARM2 = "#c0392b"
TRAIL_MS, HEAD_MS = 2.6, 8

# layout (16:9 slide)
FIG_W, FIG_H, OUT_DPI = 16.0, 9.0, 120
HEIGHT_RATIOS = [1.25, 1.0]
WSPACE, HSPACE = 0.16, 0.12
M_LEFT, M_RIGHT, M_TOP, M_BOT = 0.052, 0.992, 0.90, 0.075
TITLE_FS, LABEL_FS, TICK_FS = 21, 16, 11


def load_clips():
    data, caps = [], []
    for c in CLIPS:
        df = pd.read_csv(os.path.join(BASE, "measurements", c["stem"], "tracking.csv"))
        df = df.dropna(subset=["time_s", "theta2_deg"])
        tmax = df["time_s"].max()
        w = df[df["time_s"] >= tmax - T].copy()
        th = w["theta2_deg"].to_numpy()
        om = angular_velocity(th, w["time_s"].to_numpy())
        cap = None
        if c["video"]:
            cap = cv2.VideoCapture(os.path.join(BASE, "videos", c["stem"] + ".mov"))
        data.append({"th": th, "om": om, "n": len(w),
                     "start": int(w["frame"].min()), "freq": c["freq"], "has_video": c["video"]})
        caps.append(cap)
    return data, caps


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    c = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
    return cv2.resize(c, (DISP, DISP), interpolation=cv2.INTER_AREA)


def build_figure(data):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    gs = fig.add_gridspec(2, len(data), height_ratios=HEIGHT_RATIOS,
                          wspace=WSPACE, hspace=HSPACE,
                          left=M_LEFT, right=M_RIGHT, top=M_TOP, bottom=M_BOT)
    trails, heads, vid_ims = [], [], {}
    white = np.full((DISP, DISP, 3), 255, np.uint8)
    for col, d in enumerate(data):
        axp = fig.add_subplot(gs[0, col])
        (trail,) = axp.plot([], [], ".", ms=TRAIL_MS, color=ARM2, alpha=0.85, zorder=3)
        (head,) = axp.plot([], [], "o", ms=HEAD_MS, mfc="black", mec="white", mew=1.2, zorder=5)
        axp.set_xlim(*TH_LIM)
        axp.set_ylim(*OM_LIM)
        axp.set_xticks(TH_TICKS)
        axp.set_yticks(OM_TICKS)
        axp.tick_params(labelsize=TICK_FS)
        axp.grid(True, alpha=0.25)
        axp.set_title(f"{d['freq']:g} Hz", fontsize=TITLE_FS, fontweight="bold", pad=7)
        axp.set_xlabel(r"$\theta_2$ (deg)", fontsize=LABEL_FS)
        if col == 0:
            axp.set_ylabel(r"$\omega_2$ (deg/s)", fontsize=LABEL_FS)
        else:
            axp.tick_params(labelleft=False)
        trails.append(trail)
        heads.append(head)

        if d["has_video"]:
            axv = fig.add_subplot(gs[1, col])
            axv.axis("off")
            axv.set_box_aspect(1)
            vid_ims[col] = axv.imshow(white, aspect="auto")
    return fig, trails, heads, vid_ims


def _set_phase(trails, heads, data, col, k, show_head):
    """Show first k points of column `col`; optionally a head dot at index k-1."""
    d = data[col]
    trails[col].set_data(d["th"][:k], d["om"][:k])
    if show_head and k > 0:
        heads[col].set_data([d["th"][k - 1]], [d["om"][k - 1]])
    else:
        heads[col].set_data([], [])


def render():
    data, caps = load_clips()
    fig, trails, heads, vid_ims = build_figure(data)
    last_crop = {c: np.full((DISP, DISP, 3), 255, np.uint8) for c, d in enumerate(data) if d["has_video"]}

    pause = int(round(FPS * PAUSE_S))
    end_hold = int(round(FPS * END_HOLD_S))

    # staged schedule: (kind, col)
    schedule = [
        ("anim", 0),                 # 0.9 plays
        ("reveal_pause", 1),         # 0.94 finished portrait + pause
        ("anim", 2),                 # 1.19 plays
        ("pause", None),             # slight pause
        ("reveal_pause", 3),         # 1.28 finished portrait + pause
        ("anim", 4),                 # 1.34 plays
        ("hold", None),              # final hold
    ]

    writer = FFMpegWriter(
        fps=FPS, bitrate=14000, codec="libx264",
        extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white", "-pix_fmt", "yuv420p"],
    )
    fcount = 0
    with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
        for kind, col in schedule:
            if kind == "anim":
                d = data[col]
                if d["has_video"]:
                    caps[col].set(cv2.CAP_PROP_POS_FRAMES, d["start"])
                for k in range(1, d["n"] + 1):
                    _set_phase(trails, heads, data, col, k, show_head=True)
                    if d["has_video"]:
                        ret, frame = caps[col].read()
                        if ret:
                            last_crop[col] = crop_rgb(frame)
                        vid_ims[col].set_data(last_crop[col])
                    writer.grab_frame(); fcount += 1
                _set_phase(trails, heads, data, col, d["n"], show_head=False)  # drop dot, keep portrait
            elif kind == "reveal_pause":
                _set_phase(trails, heads, data, col, data[col]["n"], show_head=False)
                for _ in range(pause):
                    writer.grab_frame(); fcount += 1
            elif kind == "pause":
                for _ in range(pause):
                    writer.grab_frame(); fcount += 1
            elif kind == "hold":
                for _ in range(end_hold):
                    writer.grab_frame(); fcount += 1
            print(f"  done {kind} {col if col is not None else ''} -> {fcount} frames")
    for cap in caps:
        if cap is not None:
            cap.release()
    print(f"Saved -> {OUT_MP4}  ({fcount} frames @ {FPS} fps, {fcount/FPS:.1f}s)")


def qa(out_png):
    """Montage of three representative states to check the staged layout."""
    data, caps = load_clips()
    # (shown columns full, video cols to fill) for each snapshot
    states = [
        ("after 0.9 plays", [0], [0]),
        ("after 1.28 reveal", [0, 1, 2, 3], [0, 2]),
        ("final", [0, 1, 2, 3, 4], [0, 2, 4]),
    ]
    tiles = []
    for k, (label, cols_full, vids) in enumerate(states):
        fig, trails, heads, vid_ims = build_figure(data)
        for col in cols_full:
            _set_phase(trails, heads, data, col, data[col]["n"], show_head=False)
        for col in vids:
            cap = caps[col]
            cap.set(cv2.CAP_PROP_POS_FRAMES, data[col]["start"] + data[col]["n"] - 1)
            ret, frame = cap.read()
            if ret:
                vid_ims[col].set_data(crop_rgb(frame))
        fig.text(0.5, 0.985, label, ha="center", va="top", fontsize=12)
        p = f"{out_png}.{k}.png"
        fig.savefig(p, dpi=68); plt.close(fig); tiles.append(p)
    from PIL import Image
    ims = [Image.open(p) for p in tiles]
    w = max(i.width for i in ims)
    montage = Image.new("RGB", (w, sum(i.height for i in ims) + 12 * len(ims)), "white")
    yo = 0
    for im in ims:
        montage.paste(im, (0, yo)); yo += im.height + 12
    montage.save(out_png)
    for cap in caps:
        if cap is not None:
            cap.release()
    print("saved", out_png)


if __name__ == "__main__":
    render()
