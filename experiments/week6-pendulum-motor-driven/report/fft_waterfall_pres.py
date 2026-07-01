"""
Presentation recreations of the FFT waterfall / spectral-bifurcation figure
(nir analysis/fft for rep.py), fixing the missing-data distortion.

The measured driving frequencies are dense on 0.90-1.00 and 1.15-1.34 Hz but the
middle has a real hole (only 1.09 Hz between 1.00 and 1.15). The original
pcolormesh(shading='nearest') over those non-uniform x-values stretches the lone
1.09 column into a wide block, fabricating continuity.

Two industry-standard fixes, both with large labels for a lecture screen:
  Direction 1 (fft_waterfall_gap.png)    : true 0.01 Hz grid, unmeasured columns
                                           greyed + hatched "not measured".
  Direction 2 (fft_waterfall_broken.png) : broken x-axis, under-sampled middle
                                           removed (two well-sampled panels).

Same FFT recipe as the original (last 60 s of theta2, DC-removed, rfft
amplitude, interpolated onto a common pendulum-frequency axis).
"""
import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from scipy.interpolate import interp1d

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "measurements")
VOLT = "3.2V"
TIME_WINDOW = 60.0
MAX_FFT_FREQ = 2.5
N_FFT_BINS = 800
GRID_STEP = 0.01            # driving-frequency grid (Hz)
HATCH_MIN = 0.02           # only hatch/label gaps wider than this

# large-screen type
FS_LABEL, FS_TICK, FS_CBAR = 25, 19, 22

# resonance guide (pendulum freq = drive freq): saturated cyan core with a black
# halo so it reads on BOTH the bright yellow ridge and the dark background.
GUIDE_KW = dict(color="#19ffe4", ls=(0, (7, 5)), lw=2.8, alpha=1.0, zorder=6,
                solid_capstyle="round", dash_capstyle="round",
                path_effects=[pe.withStroke(linewidth=5.5, foreground="black")])


def load_columns():
    uf = np.linspace(0.01, MAX_FFT_FREQ, N_FFT_BINS)
    rows = []
    seen = set()
    # "*Hz*" also catches retake folders like 3.2V_1.33Hz_1 / _2; dedupe by freq.
    for d in sorted(glob.glob(os.path.join(BASE, f"{VOLT}_*Hz*"))):
        m = re.search(r"_(\d+(?:\.\d+)?)Hz", os.path.basename(d))
        if not m:
            continue
        f = round(float(m.group(1)), 2)
        csv = os.path.join(d, "tracking.csv")
        if f in seen or not os.path.exists(csv):
            continue
        seen.add(f)
        df = pd.read_csv(csv).dropna(subset=["time_s", "theta2_deg"])
        t = df["time_s"].values
        th = df["theta2_deg"].values
        cut = t.max() - min(TIME_WINDOW, t.max() - t.min())
        mk = t >= cut
        t, th = t[mk], th[mk] - th[mk].mean()
        N = len(th)
        dt = float(np.mean(np.diff(t)))
        amp = (2.0 / N) * np.abs(np.fft.rfft(th))
        xf = np.fft.rfftfreq(N, d=dt)
        col = np.clip(interp1d(xf, amp, bounds_error=False, fill_value=1e-10)(uf), 0, None)
        rows.append((f, col))
    rows.sort()
    freqs = np.array([r[0] for r in rows])
    cols = np.column_stack([r[1] for r in rows])
    return uf, freqs, cols


def gap_ranges(grid, measured_mask):
    """Contiguous unmeasured x-ranges (edges) on the regular grid."""
    out = []
    i = 0
    n = len(grid)
    while i < n:
        if not measured_mask[i]:
            j = i
            while j < n and not measured_mask[j]:
                j += 1
            out.append((grid[i] - GRID_STEP / 2, grid[j - 1] + GRID_STEP / 2))
            i = j
        else:
            i += 1
    return out


def direction1(uf, freqs, cols, vmax, out_png):
    grid = np.round(np.arange(0.90, freqs.max() + GRID_STEP / 2, GRID_STEP), 2)
    Z = np.full((len(uf), len(grid)), np.nan)
    measured = np.zeros(len(grid), bool)
    for k, f in enumerate(freqs):
        j = int(np.argmin(np.abs(grid - f)))
        Z[:, j] = cols[:, k]
        measured[j] = True
    Zm = np.ma.masked_invalid(Z)
    cmap = matplotlib.colormaps["inferno"].copy()
    cmap.set_bad("#d4d4d4")

    fig, ax = plt.subplots(figsize=(14, 7))
    pc = ax.pcolormesh(grid, uf, Zm, shading="nearest", cmap=cmap, vmin=0, vmax=vmax)
    ax.plot(grid, grid, **GUIDE_KW)
    for x0, x1 in gap_ranges(grid, measured):
        if x1 - x0 >= HATCH_MIN:
            ax.add_patch(plt.Rectangle((x0, 0), x1 - x0, MAX_FFT_FREQ, facecolor="none",
                                       hatch="///", edgecolor="0.5", lw=0, zorder=4))
            ax.text((x0 + x1) / 2, MAX_FFT_FREQ * 0.5, "not measured", rotation=90,
                    ha="center", va="center", fontsize=18, color="0.3", zorder=5)
    ax.set_xlim(0.90, freqs.max()); ax.set_ylim(0, MAX_FFT_FREQ)
    ax.set_xlabel("Driving Motor Frequency (Hz)", fontsize=FS_LABEL)
    ax.set_ylabel("Pendulum Frequency (Hz)", fontsize=FS_LABEL)
    ax.tick_params(labelsize=FS_TICK)
    cbar = fig.colorbar(pc, ax=ax, pad=0.02)
    cbar.set_label("FFT Amplitude", fontsize=FS_CBAR); cbar.ax.tick_params(labelsize=FS_TICK)
    fig.tight_layout(); fig.savefig(out_png, dpi=200); plt.close(fig)
    print("Saved ->", out_png)


def direction2(uf, freqs, cols, vmax, out_png, tick_step=2):
    """Broken x-axis with DISCRETE, equal-width columns (one per measured clip),
    ticked at the real measured frequencies. The under-sampled middle
    (1.00–1.15 Hz, only 1.09) is dropped."""
    mL = freqs <= 1.005
    mR = freqs >= 1.145
    fL, cL = freqs[mL], cols[:, mL]
    fR, cR = freqs[mR], cols[:, mR]
    iL, iR = np.arange(len(fL)), np.arange(len(fR))

    fig = plt.figure(figsize=(15.5, 7.4))
    gs = fig.add_gridspec(1, 2, width_ratios=[len(fL), len(fR)], wspace=0.05)
    axL = fig.add_subplot(gs[0]); axR = fig.add_subplot(gs[1], sharey=axL)
    axL.pcolormesh(iL, uf, cL, shading="nearest", cmap="inferno", vmin=0, vmax=vmax)
    pc = axR.pcolormesh(iR, uf, cR, shading="nearest", cmap="inferno", vmin=0, vmax=vmax)
    # resonance guide (pendulum freq = drive freq) on the categorical axis
    axL.plot(iL, fL, **GUIDE_KW)
    axR.plot(iR, fR, **GUIDE_KW)

    M = 0.7                                   # half-column margin -> break breathing room
    axL.set_xlim(-M, len(fL) - 1 + M)
    axR.set_xlim(-M, len(fR) - 1 + M)
    axL.set_ylim(0, MAX_FFT_FREQ)

    def discrete_ticks(ax, idx, fvals):
        sel = list(range(0, len(idx), tick_step))
        ax.set_xticks(idx[sel])
        ax.set_xticklabels([f"{fvals[i]:.2f}" for i in sel])
    discrete_ticks(axL, iL, fL)
    discrete_ticks(axR, iR, fR)

    axL.spines["right"].set_visible(False); axR.spines["left"].set_visible(False)
    axR.tick_params(left=False); plt.setp(axR.get_yticklabels(), visible=False)
    axL.tick_params(axis="x", labelsize=FS_TICK); axL.tick_params(axis="y", labelsize=FS_TICK)
    axR.tick_params(axis="x", labelsize=FS_TICK)

    dd = 0.014
    for ax, xx in [(axL, 1), (axR, 0)]:
        kw = dict(transform=ax.transAxes, color="k", clip_on=False, lw=1.4)
        ax.plot((xx - dd, xx + dd), (-dd, dd), **kw)
        ax.plot((xx - dd, xx + dd), (1 - dd, 1 + dd), **kw)

    axL.set_ylabel("Pendulum Frequency (Hz)", fontsize=FS_LABEL)
    fig.text(0.5, 0.03, "Driving Motor Frequency (Hz)", ha="center", fontsize=FS_LABEL)
    cbar = fig.colorbar(pc, ax=axR, pad=0.02)
    cbar.set_label("FFT Amplitude", fontsize=FS_CBAR); cbar.ax.tick_params(labelsize=FS_TICK)
    fig.subplots_adjust(bottom=0.135, left=0.065, right=0.99, top=0.985)
    fig.savefig(out_png, dpi=200); plt.close(fig)
    print("Saved ->", out_png)


if __name__ == "__main__":
    uf, freqs, cols = load_columns()
    vmax = float(np.percentile(cols, 99.5))   # clip a few outlier peaks for contrast
    print(f"{len(freqs)} clips, vmax={vmax:.1f} (max={cols.max():.1f})")
    direction1(uf, freqs, cols, vmax, os.path.join(HERE, "fft_waterfall_gap.png"))
    direction2(uf, freqs, cols, vmax, os.path.join(HERE, "fft_waterfall_broken.png"))
