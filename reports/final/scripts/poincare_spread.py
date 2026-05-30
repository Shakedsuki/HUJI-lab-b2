#!/usr/bin/env python3
"""
poincare_spread.py — stroboscopic Poincaré spread of arm 2 vs drive frequency.

Companion to phase_area.py, but on the STROBE points instead of the full
trajectory. The driven (stroboscopic) Poincaré samples (θ₂, ω₂) once per drive
period; for a phase-locked periodic clip the system returns to the same state
every period, so the strobe points pile into a tight cluster, while a chaotic
clip scatters them across the attractor. The spread of that strobe cloud is a
direct clustering↔scatter chaos measure.

Spread metric — the normalised standard distance of the strobe cloud: the RMS
distance of strobe points from their centroid in (θ₂, ω₂), each axis scaled by
a fixed/global reference so clips are comparable, θ₂ handled circularly
(wrap-safe). ~0 = tightly clustered (regular), large = scattered (chaotic). The
script reports the extrema: the most-clustered and most-scattered clips.

Reuses each clip's existing driven_poincare.csv (the strobe points) +
report_common; no re-strobing.

Usage:
  python reports/final/scripts/poincare_spread.py

Output:
  reports/final/figures/poincare_spread_3.2V.png
"""

import argparse
import csv
import json
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

from report_common import FIGURES_DIR, clip_dir, list_clips, stem_freq

S_THETA = 180.0       # fixed θ₂ scale (half-range, deg)
H_CHAOS = 0.4


def load_strobe(stem):
    path = os.path.join(clip_dir(stem), "driven_poincare.csv")
    th2, w2 = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                th2.append(float(r["theta2_deg"])); w2.append(float(r["omega2_deg_s"]))
            except (KeyError, ValueError):
                continue
    return np.asarray(th2, float), np.asarray(w2, float)


def circ_mean_deg(a):
    r = np.radians(a)
    return float(np.degrees(np.arctan2(np.mean(np.sin(r)), np.mean(np.cos(r)))))


def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def spectral_entropy(stem):
    try:
        return float(json.load(open(os.path.join(clip_dir(stem), "chaos_windows.json"),
                                    encoding="utf-8")).get("spectral_entropy_th2", np.nan))
    except (OSError, ValueError, TypeError):
        return np.nan


def parse_args():
    p = argparse.ArgumentParser(description="Stroboscopic Poincaré spread vs f_drive.")
    p.add_argument("--no-errors", action="store_true",
                   help="draw a plain line without error bars")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "poincare_spread_3.2V.png"))
    return p.parse_args()


def main():
    args = parse_args()
    show_err = not args.no_errors
    stems = [s for s in list_clips()
             if os.path.exists(os.path.join(clip_dir(s), "driven_poincare.csv"))]

    # pass 1 — global ω scale (pooled strobe points) so clips are comparable
    pooled_w = []
    cache = {}
    for s in stems:
        th2, w2 = load_strobe(s)
        cache[s] = (th2, w2)
        pooled_w.extend(w2.tolist())
    S_omega = float(np.std(pooled_w)) or 1.0

    # pass 2 — per-clip normalised standard distance of the strobe cloud
    rows = []
    for s in stems:
        th2, w2 = cache[s]
        if th2.size < 5:
            continue
        dth = wrap180(th2 - circ_mean_deg(th2)) / S_THETA
        dw = (w2 - np.mean(w2)) / S_omega
        spread = float(np.sqrt(np.mean(dth**2 + dw**2)))
        # sampling error of an RMS distance from N strobe points: σ ≈ spread/√(2N).
        # Few strobe points (short clip / low f) ⇒ a loosely-determined spread.
        err = spread / np.sqrt(2.0 * th2.size)
        rows.append((stem_freq(s), spread, err, spectral_entropy(s), s))
    rows.sort()
    f = np.array([r[0] for r in rows]); spread = np.array([r[1] for r in rows])
    spread_err = np.array([r[2] for r in rows])
    H = np.array([r[3] for r in rows]); names = [r[4] for r in rows]

    imin, imax = int(np.argmin(spread)), int(np.argmax(spread))

    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
    chaotic = H >= H_CHAOS
    if chaotic.any():
        ax.axvspan(f[chaotic].min(), f[chaotic].max(), color="#c0392b", alpha=0.06, lw=0)
    ax.errorbar(f, spread, yerr=(spread_err if show_err else None), fmt="o-",
                color="#8e44ad", lw=1.8, capsize=2, elinewidth=0.8, capthick=0.8)
    ax.fill_between(f, 0, spread, color="#8e44ad", alpha=0.10)

    ax.scatter(f[imin], spread[imin], s=140, marker="*", color="#2e8b57", zorder=6,
               edgecolors="k", linewidths=0.5)
    ax.annotate(f"most clustered\n{f[imin]:g} Hz", (f[imin], spread[imin]),
                xytext=(0, -34), textcoords="offset points", ha="center",
                fontsize=9, color="#2e8b57", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#2e8b57"))
    ax.scatter(f[imax], spread[imax], s=140, marker="*", color="#c0392b", zorder=6,
               edgecolors="k", linewidths=0.5)
    ax.annotate(f"most scattered\n{f[imax]:g} Hz", (f[imax], spread[imax]),
                xytext=(0, 14), textcoords="offset points", ha="center",
                fontsize=9, color="#c0392b", fontweight="bold")

    ax.set_xlabel(r"drive frequency $f_{drive}$ (Hz)")
    ax.set_ylabel("strobe-cloud spread (normalised std distance)")
    ax.set_ylim(0, float(np.max(spread + (spread_err if show_err else 0.0))) * 1.18)
    ax.grid(alpha=0.25)
    ax.set_title("Stroboscopic Poincaré spread of arm 2 vs drive frequency (3.2 V)",
                 loc="left", fontweight="bold")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"{len(f)} clips")
    print(f"  most CLUSTERED (min spread): {names[imin]}  {f[imin]:g} Hz  spread={spread[imin]:.3f}")
    print(f"  most SCATTERED (max spread): {names[imax]}  {f[imax]:g} Hz  spread={spread[imax]:.3f}")
    print(f"  ->  {args.out}")


if __name__ == "__main__":
    main()
