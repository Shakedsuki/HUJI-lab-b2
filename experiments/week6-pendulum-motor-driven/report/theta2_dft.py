"""
Side-by-side DFT of theta2(t): periodic vs chaotic, illustrating spectral
entropy H (slide "מדדים לכאוס (1)").

Left  : a periodic clip (0.9 Hz drive) -> a single dominant line -> H ~ 0.
Right : a chaotic clip (1.19 Hz drive) -> a broadband forest    -> H ~ 1.

H is computed on the SAME displayed DFT, per the slide's formula
    p_i = P_i / sum_j P_j ,   H = -(1/ln N) sum_i p_i ln p_i ,
with P_i = |DFT(theta2 - mean)|^2 over the positive frequencies (DC dropped),
so the number on each panel matches the picture under it.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
OUT_PNG = os.path.join(HERE, "theta2_dft_periodic_vs_chaotic.png")

FS = 60000 / 1001          # clip frame rate (Hz)
FMAX = 6.0                 # display range (most power sits below ~5 Hz)

PANELS = [
    {"stem": "3.2V_0.9Hz",  "label": "Periodic",  "freq": 0.9,  "color": "green"},
    {"stem": "3.2V_1.19Hz", "label": "Chaotic",   "freq": 1.19, "color": "#d62728"},
]


def theta2_dft(stem):
    df = pd.read_csv(os.path.join(BASE, "measurements", stem, "tracking.csv"))
    df = df.dropna(subset=["time_s", "theta2_deg"])
    x = df["theta2_deg"].to_numpy()
    x = x - x.mean()                       # drop DC offset
    P = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), d=1.0 / FS)
    P, f = P[1:], f[1:]                    # drop the DC bin
    H = -np.sum((P / P.sum()) * np.log(P / P.sum() + 1e-12)) / np.log(len(P))
    return f, P / P.max(), H              # normalise display power to peak = 1


fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
for ax, panel in zip(axes, PANELS):
    f, P, H = theta2_dft(panel["stem"])
    m = f <= FMAX
    ax.fill_between(f[m], P[m], color=panel["color"], alpha=0.85, lw=0)
    ax.set_xlim(0, FMAX)
    ax.set_ylim(0, 1.06)
    ax.set_xlabel("frequency (Hz)", fontsize=14)
    ax.set_title(f"{panel['label']} — {panel['freq']:g} Hz     $H_{{\\theta_2}}$ = {H:.2f}",
                 fontsize=15, fontweight="bold")
    ax.tick_params(labelsize=12)
    ax.grid(True, axis="y", alpha=0.25)
axes[0].set_ylabel("normalised power", fontsize=14)

fig.tight_layout()
fig.savefig(OUT_PNG, dpi=200, bbox_inches="tight")
print(f"Saved -> {OUT_PNG}")
