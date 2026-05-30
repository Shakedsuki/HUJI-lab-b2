#!/usr/bin/env python3
"""
omega2_reoriented.py — the ω₂ Welch waterfall drawn in the REPORT's frame.

The repo's chaos-correct spectral waterfall (scripts/analysis/
spectral_waterfall.py) spectra the angular velocity ω₂ via Welch and plots it
transposed (x = response freq, y = drive freq) with a per-row dB scale + an
entropy panel. This view re-draws that SAME data in the report waterfall's
frame — x = drive freq, y = response freq, inferno + LogNorm, the
f_drive / f_drive/2 / 2·f_drive guides, no side panel — so the only change
from reports/final/scripts/spectral_waterfall.py is the observable (ω₂ vs θ₂)
and the estimator (Welch PSD vs a single raw periodogram).

It reuses the analysis module's loader and the canonical ω₂ recipe, so this
stays a faithful re-orientation, not a re-implementation.

Output:
  reports/final/figures/comparison/omega2_welch_reoriented_3.2V.png
  reports/final/figures/comparison/waterfall_report_vs_welch.png
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.colors import LogNorm
from scipy.signal import welch

from report_common import FIGURES_DIR

# put the analysis package + utils on the path, then borrow its loader + recipe
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (os.path.join(_REPO_ROOT, "scripts", "analysis"),
           os.path.join(_REPO_ROOT, "scripts", "utils")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import spectral_waterfall as wf                 # analysis (ω₂) version  # noqa: E402
from paths import clip_dir, iter_clip_dirs      # noqa: E402
from driven_helpers import parse_stem           # noqa: E402

FMAX, NFREQ, TRANSIENT, VOLTAGE = 3.0, 800, 5.0, 3.2
OUT_DIR = os.path.join(FIGURES_DIR, "comparison")
OUT = os.path.join(OUT_DIR, "omega2_welch_reoriented_3.2V.png")
OUT_SXS = os.path.join(OUT_DIR, "waterfall_report_vs_welch.png")
REPORT_FIG = os.path.join(FIGURES_DIR, "spectral_waterfall_3.2V.png")


def main():
    grid = np.linspace(0.01, FMAX, NFREQ)        # report's response-freq grid
    rows = []
    for stem, _d in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - VOLTAGE) > 1e-6:
            continue
        cdir = clip_dir(stem)
        csvp = next((os.path.join(cdir, n) for n in
                     ("verification.csv", "tracking.csv")
                     if os.path.exists(os.path.join(cdir, n))), None)
        if not csvp:
            continue
        try:
            t, th2 = wf.load_clip(csvp)
        except Exception:
            continue
        keep = t >= (t[0] + TRANSIENT)
        if keep.sum() > 200:
            t, th2 = t[keep], th2[keep]
        # canonical observable: ω₂ = d/dt unwrap(θ₂), stationary, DC removed
        phi = np.degrees(np.unwrap(np.radians(th2)))
        om2 = np.gradient(phi, t)
        x = om2 - om2.mean()
        dt = float(np.median(np.diff(t)))
        fs = 1.0 / dt
        nper = max(64, min(len(x) // 4, int(round(fs * 8.0))))
        f, P = welch(x, fs=fs, nperseg=nper, detrend="constant")
        asd = np.sqrt(P)                          # amplitude spectral density
        rows.append((meta["f_drive_hz"], np.interp(grid, f, asd, left=0.0, right=0.0)))

    rows.sort(key=lambda r: r[0])
    X = np.array([r[0] for r in rows])
    Z = np.clip(np.array([r[1] for r in rows]).T, 1e-12, None)
    vmax = float(np.percentile(Z, 99.9)); vmin = vmax / 1e3
    Z = np.clip(Z, vmin, None)

    os.makedirs(OUT_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
    c = ax.pcolormesh(X, grid, Z, cmap="inferno", shading="nearest",
                      norm=LogNorm(vmin=vmin, vmax=vmax))
    cbar = fig.colorbar(c, ax=ax, pad=0.02)
    cbar.set_label(r"$\sqrt{\mathrm{PSD}(\omega_2)}$  (deg/s, log)")
    ax.plot(X, X, color="#22d3ee", ls="--", lw=1.3, alpha=0.7, label=r"$f_{drive}$ (primary)")
    ax.plot(X, X / 2.0, color="#a3e635", ls=":", lw=1.4, alpha=0.8, label=r"$f_{drive}/2$ (period-doubling)")
    ax.plot(X, 2.0 * X, color="white", ls=":", lw=1.0, alpha=0.4, label=r"$2f_{drive}$")
    ax.legend(loc="upper left", fontsize=9, facecolor="black", edgecolor="0.5",
              labelcolor="white", framealpha=0.7)
    ax.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    ax.set_ylabel("response frequency (Hz)")
    ax.set_title(r"$\omega_2$ Welch spectrum, report frame (3.2 V sweep)",
                 loc="left", fontweight="bold")
    ax.set_xlim(X.min(), X.max()); ax.set_ylim(0, FMAX)
    fig.savefig(OUT, dpi=150)
    plt.close(fig)

    if os.path.exists(REPORT_FIG):
        b, w = mpimg.imread(REPORT_FIG), mpimg.imread(OUT)
        f2, axs = plt.subplots(1, 2, figsize=(20, 6.5), constrained_layout=True)
        for axx, img, ttl in zip(axs, (b, w),
                                 ("Report — θ₂ FFT (raw periodogram)",
                                  "Welch — ω₂ PSD (same frame)")):
            axx.imshow(img); axx.axis("off")
            axx.set_title(ttl, fontweight="bold", fontsize=11)
        f2.savefig(OUT_SXS, dpi=130)
        plt.close(f2)
    print(f"{len(X)} clips  ->  {OUT}\n           ->  {OUT_SXS}")


if __name__ == "__main__":
    main()
