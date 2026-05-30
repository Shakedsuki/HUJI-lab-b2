#!/usr/bin/env python3
"""
cohen_replica.py — faithful, de-hardcoded reproduction of N. Cohen's
fftheatmap.py, kept for the report's method-comparison appendix.

Cohen's original (experiments/week6-pendulum-motor-driven/nir analysis/
fftheatmap.py) hardcodes an absolute machine path and ends in plt.show(),
so it cannot be rendered on this repo. This reproduces his numerical and
visual pipeline EXACTLY — only the data dir, the Agg backend and savefig()
differ — so the report can show what his figure actually looks like and how
the report's spectral_waterfall.py improves on it. His file is left untouched.

Faithful to the original:
  * reads tracking.csv, column theta2_deg
  * last 60 s tail, DC removed by mean
  * dt = mean(diff(t));  rfft;  amplitude = 2/N |.|
  * interp fill 1e-10, clip floor 1e-5
  * pcolormesh inferno, shading nearest, **linear colour** (he imports
    LogNorm but never passes it — the chaotic dust is crushed as a result)
  * guides: f_drive, f_drive/2, 3*f_drive

Output:
  reports/final/figures/comparison/cohen_fftheatmap_3.2V.png
  reports/final/figures/comparison/waterfall_cohen_vs_report.png
"""
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from report_common import FIGURES_DIR, MEAS_DIR

COL_TIME, COL_THETA2 = "time_s", "theta2_deg"
TIME_WINDOW, MAX_FFT_FREQ = 60.0, 3.0
OUT_DIR = os.path.join(FIGURES_DIR, "comparison")
OUT = os.path.join(OUT_DIR, "cohen_fftheatmap_3.2V.png")
OUT_SXS = os.path.join(OUT_DIR, "waterfall_cohen_vs_report.png")
REPORT_FIG = os.path.join(FIGURES_DIR, "spectral_waterfall_3.2V.png")


def load_data():
    out = {}
    for fp in glob.glob(os.path.join(MEAS_DIR, "*", "tracking.csv")):
        folder = os.path.basename(os.path.dirname(fp))
        m = re.search(r"(\d+(?:\.\d+)?)\s*Hz", folder, re.IGNORECASE)
        if not m:
            continue
        try:
            df = pd.read_csv(fp).dropna(subset=[COL_TIME, COL_THETA2])
            out[folder] = {"t": df[COL_TIME].values,
                           "th2": df[COL_THETA2].values,
                           "freq_val": float(m.group(1))}
        except Exception:
            pass
    return out


def main():
    from scipy.interpolate import interp1d
    data = load_data()
    folders = sorted(data, key=lambda k: data[k]["freq_val"])
    unified = np.linspace(0.01, MAX_FFT_FREQ, 800)
    drive, Zm = [], []
    for name in folders:
        t_raw, th2_raw = data[name]["t"], data[name]["th2"]
        cutoff = t_raw.max() - min(TIME_WINDOW, t_raw.max() - t_raw.min())
        mask = t_raw >= cutoff
        t_f, th2_f = t_raw[mask], th2_raw[mask]      # (his no-op "unwrap" omitted; identical)
        x = th2_f - np.mean(th2_f)
        N, dt = len(x), np.mean(np.diff(t_f))
        if N <= 0 or dt <= 0:
            continue
        amp = (2.0 / N) * np.abs(np.fft.rfft(x))
        xf = np.fft.rfftfreq(N, d=dt)
        col = interp1d(xf, amp, kind="linear", bounds_error=False,
                       fill_value=1e-10)(unified)
        Zm.append(np.clip(col, 1e-5, None))
        drive.append(data[name]["freq_val"])
    X, Y, Z = np.array(drive), unified, np.array(Zm).T

    os.makedirs(OUT_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
    c = ax.pcolormesh(X, Y, Z, cmap="inferno", shading="nearest")   # linear, as written
    cbar = fig.colorbar(c, ax=ax, pad=0.02)
    cbar.set_label(r"$|\mathrm{FFT}(\theta_2)|$  amplitude (deg, linear)")
    ax.plot(X, X, color="cyan", ls="--", lw=1.5, alpha=0.6, label=r"$f_{drive}$ (primary)")
    ax.plot(X, X / 2.0, color="lime", ls=":", lw=1.5, alpha=0.8, label=r"$f_{drive}/2$")
    ax.plot(X, X * 3.0, color="white", ls=":", lw=1.0, alpha=0.4, label=r"$3f_{drive}$")
    ax.legend(loc="upper left", fontsize=9, facecolor="black", edgecolor="0.5",
              labelcolor="white", framealpha=0.7)
    ax.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    ax.set_ylabel("response frequency (Hz)")
    ax.set_title(r"Cohen fftheatmap.py — $\theta_2$ FFT, linear colour scale (3.2 V sweep)",
                 loc="left", fontweight="bold")
    ax.set_xlim(X.min(), X.max()); ax.set_ylim(0, MAX_FFT_FREQ)
    fig.savefig(OUT, dpi=150)
    plt.close(fig)

    if os.path.exists(REPORT_FIG):
        a, b = mpimg.imread(OUT), mpimg.imread(REPORT_FIG)
        f2, axs = plt.subplots(1, 2, figsize=(20, 6.5), constrained_layout=True)
        for axx, img, ttl in zip(axs, (a, b),
                                 ("Cohen — θ₂ FFT, linear colour",
                                  "Report — θ₂ FFT, LogNorm + companion")):
            axx.imshow(img); axx.axis("off")
            axx.set_title(ttl, fontweight="bold", fontsize=11)
        f2.savefig(OUT_SXS, dpi=130)
        plt.close(f2)
    print(f"{len(X)} clips  ->  {OUT}\n           ->  {OUT_SXS}")


if __name__ == "__main__":
    main()
