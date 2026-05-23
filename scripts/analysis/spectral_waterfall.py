#!/usr/bin/env python3
"""
spectral_waterfall.py — power-spectrum waterfall across a drive sweep.

The third defining signature of chaos (after a positive Lyapunov exponent
and a non-integer attractor dimension): the power spectrum goes from a few
sharp lines (periodic) to a CONTINUOUS broadband floor (chaotic). This
stacks the lower-arm spectrum of every clip in a fixed-voltage family into
one image so the transition is visible at a glance:

  x-axis   frequency (Hz)
  y-axis   drive frequency f_drive (Hz)            — one row per clip
  colour   power, per-row-normalised, in dB        — bright = strong

Overlaid guides: the 1:1 ridge (f = f_drive), the second harmonic
(2·f_drive) and the period-doubling sub-harmonic (f_drive/2). A periodic
row is dark except on those lines; a chaotic row fills in broadband.

A thin right panel shows the per-row spectral entropy (0 = pure tone,
1 = white noise; reused from chaos_analyze) — the quantitative companion
to the visual "is this row broadband?".

Signal: the lower arm's angular velocity ω₂ (= d/dt of the unwrapped
absolute angle θ₂), mean-removed and Hann-windowed before the FFT. ω₂ is
stationary whether the arm librates or circulates, so the spectrum is not
swamped by the rotation drift that a linear detrend of θ₂ leaves behind.

Outputs:
  figures/aggregate/spectral_waterfall_<V>V.png
  figures/aggregate/spectral_waterfall_<V>V.csv   (per-clip scalars)

Usage:
  python scripts/analysis/spectral_waterfall.py
  python scripts/analysis/spectral_waterfall.py --voltage 4.0 --fmax 6
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
from scipy.signal import welch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

from rich.console import Console
from rich.table import Table
import rich.box

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
sys.path.insert(0, _HERE)
from paths import clip_dir, iter_clip_dirs          # noqa: E402
from figures_paths import aggregate_path             # noqa: E402
from driven_helpers import parse_stem                # noqa: E402
from chaos_analyze import spectral_entropy_norm      # noqa: E402

console = Console()
RUN_PHASES = ("driven", "free_swing")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    """Clean (t, th2) — running phase, dropout 0, finite. (θ₂ absolute.)"""
    t, th2 = [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            b, tt = _f(r.get("theta2_deg")), _f(r.get("time_s"))
            if np.isfinite(b) and np.isfinite(tt):
                t.append(tt); th2.append(b)
    if len(t) < 200:
        raise ValueError(f"only {len(t)} clean frames")
    return np.array(t), np.array(th2)


def clip_spectrum(t, th2, fmax, nfreq, transient_s):
    """Per-row power spectrum on a common [0, fmax] grid + scalars.

    Returns (P_grid, entropy, peak_freq). P_grid is per-row max-normalised
    power on the common frequency grid; entropy is the spectral entropy of
    the detrended signal; peak_freq is the dominant spectral line (Hz)."""
    keep = t >= (t[0] + transient_s)
    if keep.sum() > 200:
        t, th2 = t[keep], th2[keep]

    # Spectrum of the angular VELOCITY ω₂: it is stationary whether the arm
    # librates or circulates (the mean rotation rate is just its DC term,
    # dropped below), so a linear detrend of the angle is not enough — a
    # chaotic arm's *varying* rotation rate leaves low-frequency wander that
    # swamps the angle's bins. ω₂ sidesteps that. Consistent with dimension.
    phi = np.degrees(np.unwrap(np.radians(th2)))
    om2 = np.gradient(phi, t)
    x = om2 - om2.mean()

    # Welch PSD: averaging ~8 s segments tames the periodogram's huge
    # variance so a sharp line reads as a sharp line and a broadband floor
    # reads as broadband (the whole point of the waterfall).
    n = len(x)
    dt = float(np.median(np.diff(t)))
    fs = 1.0 / dt
    nper = max(64, min(n // 4, int(round(fs * 8.0))))
    freqs, power = welch(x, fs=fs, nperseg=nper, detrend="constant")
    freqs, power = freqs[1:], power[1:]          # drop DC

    peak_freq = float(freqs[int(np.argmax(power))]) if len(power) else np.nan
    ent = spectral_entropy_norm(x)

    grid = np.linspace(0.0, fmax, nfreq)
    P = np.interp(grid, freqs, power, left=0.0, right=0.0)
    pmax = P.max()
    P = P / pmax if pmax > 0 else P
    return grid, P, ent, peak_freq


def collect(voltage, fmax, nfreq, transient_s):
    rows = []
    for stem, _dir in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        cdir = clip_dir(stem)
        csv_path = next((os.path.join(cdir, n) for n in
                         ("verification.csv", "tracking.csv")
                         if os.path.exists(os.path.join(cdir, n))), None)
        if csv_path is None:
            continue
        try:
            t, th2 = load_clip(csv_path)
            grid, P, ent, pk = clip_spectrum(t, th2, fmax, nfreq, transient_s)
        except (ValueError, SystemExit) as e:
            console.print(f"  [yellow]skip {stem}: {e}[/]")
            continue
        console.print(f"  [dim]{stem:<16} entropy={ent:.2f} peak={pk:.2f}Hz[/]")
        rows.append((meta["f_drive_hz"], stem, grid, P, ent, pk))
    rows.sort(key=lambda r: r[0])
    return rows


def make_figure(rows, voltage, fmax, out_path):
    fdrv = np.array([r[0] for r in rows])
    grid = rows[0][2]
    Z = np.vstack([r[3] for r in rows])          # (n_clips, nfreq)
    ent = np.array([r[4] for r in rows])
    dB = 10.0 * np.log10(np.clip(Z, 1e-3, None))  # per-row already max=1

    # y-cell edges from the (irregular) drive frequencies
    yc = fdrv
    yed = np.empty(len(yc) + 1)
    yed[1:-1] = 0.5 * (yc[:-1] + yc[1:])
    yed[0] = yc[0] - (yc[1] - yc[0]) / 2 if len(yc) > 1 else yc[0] - 0.05
    yed[-1] = yc[-1] + (yc[-1] - yc[-2]) / 2 if len(yc) > 1 else yc[-1] + 0.05
    xed = np.linspace(grid[0], grid[-1], len(grid) + 1)

    fig = plt.figure(figsize=(13, 8))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 0.28, 0.05], wspace=0.08)
    ax = fig.add_subplot(gs[0, 0])
    axE = fig.add_subplot(gs[0, 1], sharey=ax)
    cax = fig.add_subplot(gs[0, 2])

    pcm = ax.pcolormesh(xed, yed, dB, cmap="magma",
                        norm=Normalize(vmin=-30, vmax=0), shading="flat")
    # drive-locked guides
    ax.plot(fdrv, fdrv, color="cyan", lw=1.0, ls="--", alpha=0.8,
            label="f = f_drive (1:1)")
    ax.plot(2 * fdrv, fdrv, color="white", lw=0.8, ls=":", alpha=0.7,
            label="2·f_drive")
    ax.plot(0.5 * fdrv, fdrv, color="0.7", lw=0.8, ls=":", alpha=0.7,
            label="f_drive/2")
    ax.set_xlim(0, fmax)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("drive frequency (Hz)")
    ax.set_title(f"Spectral waterfall — {voltage:g} V   "
                 f"(ω₂ power, per-row dB)")
    ax.legend(loc="lower right", fontsize=8, framealpha=0.7)
    fig.colorbar(pcm, cax=cax, label="power (dB, per row)")

    axE.plot(ent, fdrv, "-o", color="tab:green", ms=3)
    axE.set_xlim(0, 1)
    axE.set_xlabel("spectral\nentropy")
    axE.tick_params(labelleft=False)
    axE.grid(True, alpha=0.25)
    axE.set_title("broadband-ness", fontsize=9)

    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def write_csv(rows, voltage, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stem", "f_drive_hz", "v_drill_v",
                    "spectral_entropy", "peak_freq_hz"])
        for f_hz, stem, _g, _P, ent, pk in rows:
            w.writerow([stem, f"{f_hz:g}", f"{voltage:g}",
                        f"{ent:.4f}", f"{pk:.4f}"])


def print_table(rows, voltage):
    t = Table(title=f"spectral waterfall — {voltage:g} V",
              box=rich.box.SIMPLE_HEAD, title_style="bold cyan")
    for c in ("f (Hz)", "stem", "entropy", "peak (Hz)"):
        t.add_column(c, justify="right" if c != "stem" else "left")
    for f_hz, stem, _g, _P, ent, pk in rows:
        t.add_row(f"{f_hz:g}", stem, f"{ent:.2f}", f"{pk:.2f}")
    console.print(t)


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2)
    p.add_argument("--fmax", type=float, default=5.0,
                   help="top of the frequency axis (Hz)")
    p.add_argument("--nfreq", type=int, default=400,
                   help="frequency-grid resolution")
    p.add_argument("--transient", type=float, default=5.0)
    args = p.parse_args()

    rows = collect(args.voltage, args.fmax, args.nfreq, args.transient)
    if not rows:
        raise SystemExit(f"no clips at {args.voltage:g} V")

    print_table(rows, args.voltage)
    csv_out = aggregate_path(f"spectral_waterfall_{args.voltage:g}V.csv")
    write_csv(rows, args.voltage, csv_out)
    png_out = aggregate_path(f"spectral_waterfall_{args.voltage:g}V.png")
    make_figure(rows, args.voltage, args.fmax, png_out)
    console.print(f"  [dim]{len(rows)} clips → {csv_out}[/]")
    console.print(f"  [dim]→ {png_out}[/]")


if __name__ == "__main__":
    main()
