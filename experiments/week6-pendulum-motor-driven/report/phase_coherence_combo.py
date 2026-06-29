"""
Animated phase-coherence combo (slide "מדדים לכאוס (2)").

Two rows (periodic 0.9 Hz / chaotic 1.19 Hz), each:
  [ real pendulum crop ]  [ phi1,phi2 dial ]  [ phasor swarm + live rho ]

As time runs, each arm's phase phi_k spins on the dial; the relative-phase
phasor exp(i(phi1-phi2)) drops onto the unit circle and the running resultant
(black arrow, length = rho) updates live. Periodic -> phasors cluster, arrow
stays long (rho ~ 0.85). Chaotic -> phasors smear, arrow collapses (rho ~ 0.05).

Plays the last T_WINDOW seconds of each clip at REAL TIME (1x) so the arms and
dials are easy to follow. Over a finite window the chaotic rho settles to
~0.27 (it keeps falling toward the static figure's full-record 0.05 the longer
you observe); the periodic rho stays ~0.85.

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
from matplotlib.patches import FancyArrowPatch, Rectangle

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

T_WINDOW = 20.0         # seconds of steady-state shown, played at REAL TIME (1x)
FPS = 60
HOLD_S = 1.6

CX0, CY0, CSIDE = 245, 35, 680
DISP = 300

PHI1_C, PHI2_C = "#1f77b4", "#ff7f0e"   # phi1 / phi2 hand colours
HAND_LEN = 0.9

FIG_W, FIG_H, OUT_DPI = 15.0, 8.8, 120
GS = dict(left=0.105, right=0.985, top=0.80, bottom=0.045, wspace=0.16, hspace=0.20,
          width_ratios=[0.8, 1.1, 1.1])   # narrow video col so the square fills its card
CARD_FC, CARD_EC = "#fbfbfb", "#c4c4c4"
ROW_TINT = {"Periodic": "#e9f5ea", "Chaotic": "#fdeceb"}
COL_HEADERS = ["Pendulum", r"Arm phase", r"Phase coherence  $\rho$"]


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
        keep = t >= t.max() - T_WINDOW                 # last T_WINDOW s, real time
        t, th1, th2, fr = t[keep], th1[keep], th2[keep], fr[keep]
        dt = float(np.median(np.diff(t)))
        win = int(0.2 * (1.0 / r["f"]) / dt) | 1
        o1 = angular_velocity(th1, t, window=max(win, 3))
        o2 = angular_velocity(th2, t, window=max(win, 3))
        phi1 = inst_phase(th1, o1, r["f"])
        phi2 = inst_phase(th2, o2, r["f"])
        data.append({
            "phi1": phi1, "phi2": phi2,
            "z": np.exp(1j * (phi1 - phi2)),
            "start": int(fr[0]), "n": len(t), "color": r["color"],
            "label": r["label"], "f": r["f"],
        })
        caps.append(cv2.VideoCapture(os.path.join(BASE, "videos", r["stem"] + ".mov")))
    return data, caps


def crop_rgb(frame):
    c = frame[CY0:CY0 + CSIDE, CX0:CX0 + CSIDE]
    return cv2.resize(cv2.cvtColor(c, cv2.COLOR_BGR2RGB), (DISP, DISP), interpolation=cv2.INTER_AREA)


def _circle_axes(ax, lim=1.16):
    """Clean circular plot: outer unit circle + faint cross-hairs, no spines."""
    th = np.linspace(0, 2 * np.pi, 256)
    ax.plot(np.cos(th), np.sin(th), color="0.45", lw=1.6, zorder=2)
    ax.axhline(0, color="0.86", lw=0.8, zorder=1)
    ax.axvline(0, color="0.86", lw=0.8, zorder=1)
    ax.plot(0, 0, "o", color="0.35", ms=3, zorder=3)
    ax.set_aspect("equal"); ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_xticks([]); ax.set_yticks([]); ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


def _phase_dial(ax, lim=1.36):
    """The (theta, omega) phase plane: phi_k is the angle of arm k's state here.
    Labelled theta (x) / omega (y) axes with a faint unit-direction circle."""
    th = np.linspace(0, 2 * np.pi, 256)
    ax.plot(np.cos(th), np.sin(th), color="0.82", lw=1.1, zorder=1)        # unit reference
    ax.annotate("", xy=(1.16, 0), xytext=(-1.16, 0),
                arrowprops=dict(arrowstyle="-|>", color="0.45", lw=1.4), zorder=2)   # theta axis
    ax.annotate("", xy=(0, 1.16), xytext=(0, -1.16),
                arrowprops=dict(arrowstyle="-|>", color="0.45", lw=1.4), zorder=2)   # omega axis
    ax.text(1.26, 0.0, r"$\theta$", ha="left", va="center", fontsize=14, color="0.3")
    ax.text(0.0, 1.24, r"$\omega$", ha="center", va="bottom", fontsize=14, color="0.3")
    ax.plot(0, 0, "o", color="0.35", ms=3, zorder=3)
    ax.set_aspect("equal"); ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_xticks([]); ax.set_yticks([]); ax.patch.set_visible(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


def _swarm_grid(ax):
    th = np.linspace(0, 2 * np.pi, 256)
    for rr in (0.5,):                                   # radial scale ring for rho
        ax.plot(rr * np.cos(th), rr * np.sin(th), color="0.8", lw=0.9, ls=(0, (4, 3)), zorder=1)
    ax.text(0.5, 0.05, "0.5", color="0.55", fontsize=8, ha="center", va="bottom", zorder=2)
    ax.text(1.0, 0.05, "1", color="0.55", fontsize=8, ha="center", va="bottom", zorder=2)


def build_figure(data):
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    gs = fig.add_gridspec(2, 3, **GS)
    H = {"vid": [], "h1": [], "h2": [], "swarm": [], "cur": [], "arrow": [], "rho": []}
    blank = np.zeros((DISP, DISP, 3), np.uint8)

    # ── skeleton: a card behind every cell ──
    pad = 0.006
    for r in range(2):
        for c in range(3):
            bb = gs[r, c].get_position(fig)
            fig.add_artist(Rectangle((bb.x0 - pad, bb.y0 - pad),
                                     bb.width + 2 * pad, bb.height + 2 * pad,
                                     transform=fig.transFigure, facecolor=CARD_FC,
                                     edgecolor=CARD_EC, lw=1.3, zorder=0))

    for r, d in enumerate(data):
        axv = fig.add_subplot(gs[r, 0]); axv.set_box_aspect(1)
        axv.set_xticks([]); axv.set_yticks([])
        for sp in axv.spines.values():
            sp.set_color("0.6")
        H["vid"].append(axv.imshow(blank, aspect="auto"))

        axd = fig.add_subplot(gs[r, 1]); _phase_dial(axd)
        (h1,) = axd.plot([], [], "-", lw=3.4, color=PHI1_C, solid_capstyle="round", zorder=4)
        (h2,) = axd.plot([], [], "-", lw=3.4, color=PHI2_C, solid_capstyle="round", zorder=4)
        H["h1"].append(h1); H["h2"].append(h2)

        axs = fig.add_subplot(gs[r, 2]); _circle_axes(axs); _swarm_grid(axs)
        (sw,) = axs.plot([], [], ".", ms=5, color=d["color"], alpha=0.22, zorder=2)
        (cur,) = axs.plot([], [], "-", lw=1.6, color="0.4", zorder=3)
        arrow = FancyArrowPatch((0, 0), (0, 0), arrowstyle="-|>", mutation_scale=18,
                                lw=2.8, color="black", zorder=5)
        axs.add_patch(arrow)
        rho_txt = axs.text(0.96, 0.95, "", transform=axs.transAxes, ha="right", va="top",
                           fontsize=15, fontweight="bold",
                           bbox=dict(boxstyle="round,pad=0.32", fc="white", ec="0.6", lw=1.1))
        H["swarm"].append(sw); H["cur"].append(cur); H["arrow"].append(arrow); H["rho"].append(rho_txt)

    # ── column headers ──
    for c, htext in enumerate(COL_HEADERS):
        bb = gs[0, c].get_position(fig)
        fig.text(bb.x0 + bb.width / 2, GS["top"] + 0.052, htext, ha="center", va="bottom",
                 fontsize=15, fontweight="bold")
    bb = gs[0, 1].get_position(fig); xc = bb.x0 + bb.width / 2
    fig.text(xc - 0.017, GS["top"] + 0.024, r"$\phi_1$", color=PHI1_C, ha="right", va="bottom",
             fontsize=15, fontweight="bold")
    fig.text(xc, GS["top"] + 0.024, ",", color="0.3", ha="center", va="bottom", fontsize=15)
    fig.text(xc + 0.017, GS["top"] + 0.024, r"$\phi_2$", color=PHI2_C, ha="left", va="bottom",
             fontsize=15, fontweight="bold")

    # ── row label cards (left margin) ──
    for r, d in enumerate(data):
        bb = gs[r, 0].get_position(fig); yc = bb.y0 + bb.height / 2
        fig.add_artist(Rectangle((0.012, yc - 0.07), 0.078, 0.14, transform=fig.transFigure,
                                 facecolor=ROW_TINT[d["label"]], edgecolor="0.55", lw=1.2, zorder=0))
        fig.text(0.051, yc, f"{d['label']}\n{d['f']:g} Hz", ha="center", va="center",
                 fontsize=13, fontweight="bold")

    # ── title bar ──
    fig.text(0.5, 0.945, r"Phase coherence   $\rho=\left|\langle e^{\,i(\phi_1-\phi_2)}\rangle\right|$",
             ha="center", va="center", fontsize=19, fontweight="bold")
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
        cap.set(cv2.CAP_PROP_POS_FRAMES, d["start"])
    last = [np.zeros((DISP, DISP, 3), np.uint8) for _ in data]
    fig, H = build_figure(data)

    n_sweep = min(d["n"] for d in data)
    from matplotlib.animation import FFMpegWriter
    writer = FFMpegWriter(fps=FPS, bitrate=14000, codec="libx264",
                          extra_args=["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white",
                                      "-pix_fmt", "yuv420p"])
    hold = int(round(FPS * HOLD_S))
    with writer.saving(fig, OUT_MP4, dpi=OUT_DPI):
        for i in range(n_sweep):
            for r, cap in enumerate(caps):
                ok, frame = cap.read()                # real-time sequential 1:1
                if ok and frame is not None:
                    last[r] = crop_rgb(frame)
                H["vid"][r].set_data(last[r])
            _update(H, data, i)
            writer.grab_frame()
            if i % 120 == 0:
                print(f"  frame {i}/{n_sweep}")
        for _ in range(hold):
            writer.grab_frame()
    for cap in caps:
        cap.release()
    print(f"Saved -> {OUT_MP4}  ({n_sweep + hold} frames @ {FPS} fps, {(n_sweep+hold)/FPS:.1f}s)")


def qa(idxs, out_png):
    data, caps = load_rows()
    tiles = []
    for k, i in enumerate(idxs):
        fig, H = build_figure(data)
        for r, cap in enumerate(caps):
            cap.set(cv2.CAP_PROP_POS_FRAMES, data[r]["start"] + i)
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
