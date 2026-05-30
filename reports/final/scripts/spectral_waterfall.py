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


def amp_at(x, dt, fd):
    """Locked-response amplitude |FFT(x)| at f = fd (deg), single periodogram."""
    x = x - np.mean(x)
    a = (2.0 / len(x)) * np.abs(np.fft.rfft(x))
    ff = np.fft.rfftfreq(len(x), d=dt)
    return float(interp1d(ff, a, bounds_error=False, fill_value=0.0)(fd))


def locked_amp_error(x, dt, fd, n_seg):
    """SEM of the locked-response amplitude at f_drive, from a Welch-style split.

    A single periodogram has no built-in error. Splitting the steady-state tail
    into ``n_seg`` independent contiguous sub-records, reading the amplitude at
    f_drive in each, and taking std/√K gives the sampling uncertainty of the
    full-record estimate (the full record IS the K segments, so var(mean) ≈
    σ²_seg/K). Returns NaN if the window is too short to split. Small at the
    locked ends; larger through the chaotic core where the line leaks into a
    broadband continuum that scatters segment to segment."""
    n = len(x) // n_seg
    if n < 8:
        return float("nan")
    vals = [amp_at(x[i * n:(i + 1) * n], dt, fd) for i in range(n_seg)]
    return float(np.std(vals, ddof=1) / np.sqrt(len(vals))) if len(vals) >= 2 else float("nan")


def parse_args():
    p = argparse.ArgumentParser(description="Report spectral-waterfall heatmap.")
    p.add_argument("--window", type=float, default=60.0,
                   help="steady-state tail window in s (default 60, for FFT resolution)")
    p.add_argument("--fmax", type=float, default=3.0,
                   help="max response frequency on the y-axis (Hz, default 3)")
    p.add_argument("--nfreq", type=int, default=800, help="response-frequency bins")
    p.add_argument("--n-seg", type=int, default=6,
                   help="Welch segments for the companion's amplitude SEM (default 6)")
    p.add_argument("--no-errors", action="store_true",
                   help="companion: draw a plain line without error bars")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "spectral_waterfall_3.2V.png"))
    p.add_argument("--out-companion",
                   default=os.path.join(FIGURES_DIR, "spectral_amplitude_3.2V.png"),
                   help="companion: locked-response amplitude at f_drive vs f_drive")
    return p.parse_args()


def main():
    args = parse_args()
    stems = list_clips()                                    # freq-sorted
    unified = np.linspace(0.01, args.fmax, args.nfreq)      # common y-axis
    drive, Z, amp_fd, amp_fd_err = [], [], [], []
    Tmin = np.inf                                           # shortest record used
    for stem in stems:
        t, th2 = load_theta2(stem)
        t, th2 = tail_window(t, th2, window_s=args.window)
        if t.size < 16:
            continue
        x = th2 - np.mean(th2)                              # remove DC offset
        dt = float(np.median(np.diff(t)))
        N = len(x)
        Tmin = min(Tmin, N * dt)
        amp = (2.0 / N) * np.abs(np.fft.rfft(x))
        xf = np.fft.rfftfreq(N, d=dt)
        col = interp1d(xf, amp, kind="linear", bounds_error=False,
                       fill_value=1e-10)(unified)
        Z.append(np.clip(col, 1e-3, None))
        fd = stem_freq(stem)
        drive.append(fd)
        # response amplitude locked to the drive: |FFT(θ₂)| at f = f_drive
        # (full-window value) + its Welch-segment sampling SEM.
        amp_fd.append(float(interp1d(xf, amp, bounds_error=False, fill_value=0.0)(fd)))
        amp_fd_err.append(locked_amp_error(x, dt, fd, args.n_seg))
    X = np.asarray(drive)
    Z = np.asarray(Z).T                                    # (freq, clip)
    amp_fd = np.asarray(amp_fd)
    amp_fd_err = np.asarray(amp_fd_err)
    df_res = 1.0 / args.window                              # FFT resolution Δf = 1/T

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
    yerr = None if args.no_errors else amp_fd_err
    axc.errorbar(X, amp_fd, yerr=yerr, fmt="o-", color="#c0392b", lw=1.6,
                 capsize=2, elinewidth=0.8, capthick=0.8)
    axc.fill_between(X, 0, amp_fd, color="#c0392b", alpha=0.10)
    axc.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    axc.set_ylabel(r"$|\mathrm{FFT}(\theta_2)|$ at $f_{drive}$ (deg)")
    axc.set_title(r"Locked-response amplitude at $f_{drive}$ across the 3.2 V sweep",
                  loc="left", fontweight="bold")
    axc.set_xlim(X.min(), X.max()); axc.grid(alpha=0.25)
    top = np.nanmax(amp_fd + (0.0 if args.no_errors else np.nan_to_num(amp_fd_err)))
    axc.set_ylim(0, float(top) * 1.10)
    fig2.savefig(args.out_companion, dpi=150)
    plt.close(fig2)
    print(f"{len(X)} clips  Δf = 1/T = {df_res:.4f} Hz "
          f"(shortest record {Tmin:.0f}s → Δf ≤ {1.0/Tmin:.4f} Hz);  "
          f"companion err = Welch-SEM over {args.n_seg} segments")
    print(f"  ->  {args.out}\n  ->  {args.out_companion}")


if __name__ == "__main__":
    main()
