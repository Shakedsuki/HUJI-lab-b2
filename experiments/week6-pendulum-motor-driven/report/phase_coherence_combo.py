"""
Animated phase-coherence combo (slide "מדדים לכאוס (2)").

Two rows (periodic 0.9 Hz / chaotic 1.19 Hz), each:
  [ real pendulum crop ]  [ phi1,phi2 dial ]  [ phasor swarm + live rho ]

As time runs, each arm's phase phi_k spins on the dial; the relative-phase
phasor exp(i(phi1-phi2)) drops onto the unit circle and the running resultant
(black arrow, length = rho) updates live. Periodic -> phasors cluster, arrow
stays long (rho ~ 0.85). Chaotic -> phasors smear, arrow collapses (rho ~ 0.05).

Each clip's FULL post-transient record is compressed evenly into the animation
(video sped up ~5-8x) so rho reaches its true asymptotic value, consistent with
the static phase_coherence_swarm figure.

phi_k = inst_phase(theta_k, omega_k, f_drive) (phase_locking convention);
omega via kinematics.angular_velocity.

Run:  python phase_coherence_combo.py
QA:   python -c "import phase_coherence_combo as M; M.qa([5,450,899],'qa.png')"
"""
import os
import sys
import numpy as np
import pandas as pd
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "scripts", "utils"))
from kinematics import angular_velocity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
OUT_MP4 = os.path.join(HERE, "phase_coherence_combo.mp4")

ROWS = [
    {"label": "Periodic", "stem": "3.2V_0.9Hz",  "f": 0.9,  "color": "green"},
    {"label": "Chaotic",  "stem": "3.2V_1.19Hz", "f": 1.19, "color": "#d62728"},
]

TRANSIENT_S = 5.0
N_FRAMES = 900          # animation length (frames); full record compressed to this
FPS = 60
HOLD_S = 1.6

CX0, CY0, CSIDE = 245, 35, 680
DISP = 300

PHI1_C, PHI2_C = "#1f77b4", "#ff7f0e"   # phi1 / phi2 hand colours
HAND_LEN = 0.9

FIG_W, FIG_H, OUT_DPI = 15.0, 8.0, 120
WIDTH_RATIOS = [1.15, 1.0, 1.15]
WSPACE, HSPACE = 0.12, 0.16
M_LEFT, M_RIGHT, M_TOP, M_BOT = 0.075, 0.985, 0.88, 0.03


def inst_phase(theta_deg, omega_dps, f):
    th_c = theta_deg - np.mean(theta_deg)
    return np.unwrap(np.arctan2(omega_dps / (2.0 * np.pi * f), th_c))


def load_rows():
    data, caps = [], []
    for r in ROWS:
        df = pd.read_csv(os.path.join(BASE, "measurements", r["stem"], "tracking.csv"))
        df = df.dropna(subset=["time_s", "theta1_deg", "theta2_deg"])
        t = df["time_s"].to_numpy()
        th1 = df["theta1_deg"].to_numpy()
        th2 = df["theta2_deg"].to_numpy()
        fr = df["frame"].to_numpy()
        keep = t >= t[0] + TRANSIENT_S
        t, th1, th2, fr = t[keep], th1[keep], th2[keep], fr[keep]
        dt = float(np.median(np.diff(t)))
        win = int(0.2 * (1.0 / r["f"]) / dt) | 1
        o1 = angular_velocity(th1, t, window=max(win, 3))
        o2 = angular_velocity(th2, t, window=max(win, 3))
        phi1 = inst_phase(th1, o1, r["f"])
        phi2 = inst_phase(th2, o2, r["f"])
        idx = np.linspace(0, len(t) - 1, N_FRAMES).astype(int)   # even-sample full record
        data.append({
            "phi1": phi1[idx], "phi2": phi2[idx],
            "z": np.exp(1j * (phi1[idx] - phi2[idx])),
            "vframe": fr[idx].astype(int), "color": r["color"],
            "label": r["label"], "f": r["f"],
        })
        caps.append(cv2.VideoCapture(os.path.join(BASE, "videos", r["stem"] + ".mov")))
    return data, caps


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    return cv2.resize(cv2.cvtColor(c, cv2.COLOR_BGR2RGB), (DISP, DISP), interpolation=cv2.INTER_AREA)


def _unit_circle(ax):
    th = np.linspace(0, 2 * np.pi, 240)
    ax.plot(np.cos(th), np.sin(th), color="0.75", lw=1.2, zorder=1)
    ax.set_aspect("equal"); ax.set_xlim(-1.25, 1.25); ax.set_ylim(-1.5, 1.25); ax.axis("off")


def build_figure(data):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    gs = fig.add_gridspec(2, 3, width_ratios=WIDTH_RATIOS, wspace=WSPACE, hspace=HSPACE,
                          left=M_LEFT, right=M_RIGHT, top=M_TOP, bottom=M_BOT)
    H = {"vid": [], "h1": [], "h2": [], "swarm": [], "cur": [], "arrow": [], "rho": []}
    blank = np.zeros((DISP, DISP, 3), np.uint8)
    for r, d in enumerate(data):
        axv = fig.add_subplot(gs[r, 0]); axv.axis("off"); axv.set_box_aspect(1)
        H["vid"].append(axv.imshow(blank, aspect="auto"))
        axv.set_ylabel(f"{d['label']}\n{d['f']:g} Hz", fontsize=15, fontweight="bold",
                       rotation=0, ha="right", va="center", labelpad=22)
        axv.axis("on"); axv.set_xticks([]); axv.set_yticks([])
        for sp in axv.spines.values():
            sp.set_visible(False)

        axd = fig.add_subplot(gs[r, 1]); _unit_circle(axd)
        (h1,) = axd.plot([], [], "-", lw=3, color=PHI1_C, solid_capstyle="round", zorder=4)
        (h2,) = axd.plot([], [], "-", lw=3, color=PHI2_C, solid_capstyle="round", zorder=4)
        axd.plot(0, 0, "ko", ms=3, zorder=5)
        if r == 0:
            axd.legend([h1, h2], [r"$\phi_1$", r"$\phi_2$"], loc="upper center",
                       bbox_to_anchor=(0.5, 1.16), ncol=2, frameon=False, fontsize=14)
        H["h1"].append(h1); H["h2"].append(h2)

        axs = fig.add_subplot(gs[r, 2]); _unit_circle(axs)
        (sw,) = axs.plot([], [], ".", ms=5, color=d["color"], alpha=0.20, zorder=2)
        (cur,) = axs.plot([], [], "-", lw=1.6, color="0.35", zorder=3)
        arrow = FancyArrowPatch((0, 0), (0, 0), arrowstyle="-|>", mutation_scale=18,
                                lw=2.8, color="black", zorder=5)
        axs.add_patch(arrow)
        axs.plot(0, 0, "ko", ms=3, zorder=6)
        rho_txt = axs.text(0, -1.34, "", ha="center", va="center", fontsize=18, fontweight="bold")
        H["swarm"].append(sw); H["cur"].append(cur); H["arrow"].append(arrow); H["rho"].append(rho_txt)

    fig.suptitle(r"Phase coherence  $\rho=\left|\langle e^{\,i(\phi_1-\phi_2)}\rangle\right|$",
                 fontsize=17, y=0.965)
    return fig, H


def _update(H, data, i):
    for r, d in enumerate(data):
        p1, p2 = d["phi1"][i], d["phi2"][i]
        H["h1"][r].set_data([0, HAND_LEN * np.cos(p1)], [0, HAND_LEN * np.sin(p1)])
        H["h2"][r].set_data([0, HAND_LEN * np.cos(p2)], [0, HAND_LEN * np.sin(p2)])
        zi = d["z"][: i + 1]
        H["swarm"][r].set_data(zi.real, zi.imag)
        c = d["z"][i]
        H["cur"][r].set_data([0, c.real], [0, c.imag])
        R = zi.mean()
        H["arrow"][r].set_positions((0, 0), (R.real, R.imag))
        H["rho"][r].set_text(rf"$\rho = {abs(R):.2f}$")


def render():
    data, caps = load_rows()
    for cap, d in zip(caps, data):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(d["vframe"][0]))
    cur_frame = [int(d["vframe"][0]) for d in data]
    last = [np.zeros((DISP, DISP, 3), np.uint8) for _ in data]
    fig, H = build_figure(data)

    from matplotlib.animation import FFMpegWriter
    writer = FFMpegWriter(fps=FPS, bitrate=14000, codec="libx264",
                          extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white",
                                      "-pix_fmt", "yuv420p"])
    hold = int(round(FPS * HOLD_S))
    with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
        for i in range(N_FRAMES):
            for r, cap in enumerate(caps):
                target = int(data[r]["vframe"][i])
                while cur_frame[r] < target:          # skip-grab up to the target frame
                    cap.grab(); cur_frame[r] += 1
                ok, frame = cap.read()                # read + decode frame `target`
                cur_frame[r] += 1
                if ok and frame is not None:
                    last[r] = crop_rgb(frame)
                H["vid"][r].set_data(last[r])
            _update(H, data, i)
            writer.grab_frame()
            if i % 120 == 0:
                print(f"  frame {i}/{N_FRAMES}")
        for _ in range(hold):
            writer.grab_frame()
    for cap in caps:
        cap.release()
    print(f"Saved -> {OUT_MP4}  ({N_FRAMES + hold} frames @ {FPS} fps)")


def qa(idxs, out_png):
    data, caps = load_rows()
    tiles = []
    for k, i in enumerate(idxs):
        fig, H = build_figure(data)
        for r, cap in enumerate(caps):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(data[r]["vframe"][i]))
            ok, frame = cap.read()
            if ok:
                H["vid"][r].set_data(crop_rgb(frame))
        _update(H, data, i)
        p = f"{out_png}.{k}.png"; fig.savefig(p, dpi=70); plt.close(fig); tiles.append(p)
    from PIL import Image
    ims = [Image.open(p) for p in tiles]; w = max(i.width for i in ims)
    mont = Image.new("RGB", (w, sum(i.height for i in ims) + 10 * len(ims)), "white")
    yo = 0
    for im in ims:
        mont.paste(im, (0, yo)); yo += im.height + 10
    mont.save(out_png)
    for cap in caps:
        cap.release()
    print("saved", out_png)


if __name__ == "__main__":
    render()
