#!/usr/bin/env python3
"""
spectral_waterfall.py — final-report FFT spectral-bifurcation heatmap.

Report version of N. Cohen's fftheatmap.py, de-hardcoded onto the repo paths.
For every 3.2 V clip it takes the steady-state tail of θ₂(t), computes its
amplitude spectrum, and stacks the spectra into a 2-D map:

    x = drive frequency f_drive       y = response frequency
    colour = |FFT(θ₂)| amplitude (log)

This is the route to chaos in the frequency domain: a single bright line on
the f = f_drive diagonal is a phase-locked period-1 response; a line appearing
at f_drive/2 is a period-doubling; broadband vertical smear is chaos.

Conventions: θ₂ from verification.csv (driven phase), steady-state slice via
report_common.tail_window (last --window s, default 60 for FFT resolution).

Usage:
  python reports/final/scripts/spectral_waterfall.py
  python reports/final/scripts/spectral_waterfall.py --window 60 --fmax 3

Output:
  reports/final/figures/spectral_waterfall_3.2V.png
"""

import argparse
import csv
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
from matplotlib.colors import LogNorm
from scipy.interpolate import interp1d

from report_common import FIGURES_DIR, clip_dir, list_clips, tail_window, stem_freq


def load_theta2(stem):
    path = os.path.join(clip_dir(stem), "verification.csv")
    t, th = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                t.append(float(r["time_s"])); th.append(float(r["theta2_deg"]))
            except (KeyError, ValueError):
                continue
    return np.asarray(t, float), np.asarray(th, float)


def parse_args():
    p = argparse.ArgumentParser(description="Report spectral-waterfall heatmap.")
    p.add_argument("--window", type=float, default=60.0,
                   help="steady-state tail window in s (default 60, for FFT resolution)")
    p.add_argument("--fmax", type=float, default=3.0,
                   help="max response frequency on the y-axis (Hz, default 3)")
    p.add_argument("--nfreq", type=int, default=800, help="response-frequency bins")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "spectral_waterfall_3.2V.png"))
    p.add_argument("--out-companion",
                   default=os.path.join(FIGURES_DIR, "spectral_amplitude_3.2V.png"),
                   help="companion: locked-response amplitude at f_drive vs f_drive")
    return p.parse_args()


def main():
    args = parse_args()
    stems = list_clips()                                    # freq-sorted
    unified = np.linspace(0.01, args.fmax, args.nfreq)      # common y-axis
    drive, Z, amp_fd = [], [], []
    for stem in stems:
        t, th2 = load_theta2(stem)
        t, th2 = tail_window(t, th2, window_s=args.window)
        if t.size < 16:
            continue
        x = th2 - np.mean(th2)                              # remove DC offset
        dt = float(np.median(np.diff(t)))
        N = len(x)
        amp = (2.0 / N) * np.abs(np.fft.rfft(x))
        xf = np.fft.rfftfreq(N, d=dt)
        col = interp1d(xf, amp, kind="linear", bounds_error=False,
                       fill_value=1e-10)(unified)
        Z.append(np.clip(col, 1e-3, None))
        fd = stem_freq(stem)
        drive.append(fd)
        # response amplitude locked to the drive: |FFT(θ₂)| at f = f_drive
        amp_fd.append(float(interp1d(xf, amp, bounds_error=False, fill_value=0.0)(fd)))
    X = np.asarray(drive)
    Z = np.asarray(Z).T                                    # (freq, clip)
    amp_fd = np.asarray(amp_fd)

    fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
    vmax = float(np.percentile(Z, 99.9))
    c = ax.pcolormesh(X, unified, Z, cmap="inferno", shading="nearest",
                      norm=LogNorm(vmin=1.0, vmax=vmax))
    cbar = fig.colorbar(c, ax=ax, pad=0.02)
    cbar.set_label(r"$|\mathrm{FFT}(\theta_2)|$  amplitude (deg, log)")

    # guide lines: primary response, period-doubling sub-harmonic, 2nd harmonic
    ax.plot(X, X, color="#22d3ee", ls="--", lw=1.3, alpha=0.7, label=r"$f_{drive}$ (primary)")
    ax.plot(X, X / 2.0, color="#a3e635", ls=":", lw=1.4, alpha=0.8, label=r"$f_{drive}/2$ (period-doubling)")
    ax.plot(X, 2.0 * X, color="white", ls=":", lw=1.0, alpha=0.4, label=r"$2f_{drive}$")
    ax.legend(loc="upper left", fontsize=9, facecolor="black",
              edgecolor="0.5", labelcolor="white", framealpha=0.7)

    ax.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    ax.set_ylabel("response frequency (Hz)")
    ax.set_title(r"Spectral bifurcation — $\theta_2$ amplitude spectrum across the 3.2 V sweep",
                 loc="left", fontweight="bold")
    ax.set_xlim(X.min(), X.max()); ax.set_ylim(0, args.fmax)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)

    # companion: the locked-response amplitude |FFT(θ₂)| at f = f_drive, vs
    # f_drive — a 1-D slice along the heatmap's primary diagonal. High where the
    # response is concentrated at the drive (regular ends); it dips through the
    # chaotic core, where energy leaks into a broadband continuum.
    fig2, axc = plt.subplots(figsize=(11, 4), constrained_layout=True)
    axc.plot(X, amp_fd, "o-", color="#c0392b", lw=1.6)
    axc.fill_between(X, 0, amp_fd, color="#c0392b", alpha=0.10)
    axc.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    axc.set_ylabel(r"$|\mathrm{FFT}(\theta_2)|$ at $f_{drive}$ (deg)")
    axc.set_title(r"Locked-response amplitude at $f_{drive}$ across the 3.2 V sweep",
                  loc="left", fontweight="bold")
    axc.set_xlim(X.min(), X.max()); axc.grid(alpha=0.25)
    fig2.savefig(args.out_companion, dpi=150)
    plt.close(fig2)
    print(f"{len(X)} clips  ->  {args.out}\n           ->  {args.out_companion}")


if __name__ == "__main__":
    main()
