#!/usr/bin/env python3
"""
phase_portrait_grid.py — every 3.2 V arm-2 phase portrait, tinted by the
phase-locking quadrant, for cross-referencing against phase_locking_3.2V.

One tile per clip (frequency-ordered): the θ₂–ω₂ portrait of arm 2. Each tile
is tinted by the SAME (ρ, H_θ₂) quadrant the phase-locking scatter uses, so a
clip the scatter places in the red (unlocked+chaotic) corner should look like a
filled cloud here, and a green (locked+regular) clip should be a clean loop:

  red  tint  → ρ < RHO_LOCK and H_θ₂ ≥ 0.4   (unlocked + chaotic)
  green tint → ρ ≥ RHO_LOCK and H_θ₂ < 0.4   (locked + regular)
  gray tint  → transition (the two measures disagree)

ρ is taken from phase_locking.compute (identical to the scatter); H_θ₂ from
each clip's chaos_windows.json. Portraits use the report's steady-state
tail_window + SG-smoothed ω.

Usage:
  python reports/final/scripts/phase_portrait_grid.py
  python reports/final/scripts/phase_portrait_grid.py --ncols 6 --window 30

Output:
  reports/final/figures/phase_portrait_grid.png
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

from report_common import (
    FIGURES_DIR, TIME_WINDOW_S, clip_dir, list_clips, tail_window, stem_freq,
)

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts", "utils"))
sys.path.insert(0, os.path.join(_REPO, "scripts", "analysis"))
from kinematics import angular_velocity     # noqa: E402
import thresholds as TH                      # noqa: E402
import phase_locking as pl                   # noqa: E402

COLOR_ARM2 = "#c0392b"
H_CHAOS = 0.4                                 # spectral-entropy split (scatter)
TINT = {"chaotic": ("#c0392b", 0.10), "regular": ("#2e8b57", 0.10),
        "transition": ("#808080", 0.06)}


def parse_args():
    p = argparse.ArgumentParser(description="Arm-2 phase-portrait grid, tinted by phase-lock quadrant.")
    p.add_argument("--ncols", type=int, default=6, help="grid columns (default 6)")
    p.add_argument("--window", type=float, default=TIME_WINDOW_S,
                   help=f"steady-state tail window (s), default {TIME_WINDOW_S:g}")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "phase_portrait_grid.png"))
    return p.parse_args()


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
    t = np.asarray(t, float)
    return t - t[0], np.asarray(th, float)


def spectral_entropy(stem):
    try:
        return float(json.load(open(os.path.join(clip_dir(stem), "chaos_windows.json"),
                                    encoding="utf-8")).get("spectral_entropy_th2", np.nan))
    except (OSError, ValueError, TypeError):
        return np.nan


def quadrant(rho, H):
    """Match the phase-locking scatter's regions."""
    if rho is None or not np.isfinite(H):
        return "transition"
    locked = rho >= TH.PLOCK_RHO_LOCK
    regular = H < H_CHAOS
    if locked and regular:
        return "regular"
    if (not locked) and (not regular):
        return "chaotic"
    return "transition"


def main():
    args = parse_args()
    stems = list_clips()                      # freq-sorted
    tiles, om_max = [], 0.0
    for stem in stems:
        t, th2 = load_theta2(stem)
        om2 = angular_velocity(th2, t)
        tw, th2w, om2w = tail_window(t, th2, om2, window_s=args.window)
        try:
            rho = pl.compute(stem)["rho"]      # same ρ as the scatter
        except Exception:
            rho = None
        H = spectral_entropy(stem)
        q = quadrant(rho, H)
        tiles.append((stem, th2w, om2w, rho, H, q))
        if om2w.size:
            om_max = max(om_max, np.percentile(np.abs(om2w), 99.5))
    om_lim = float(np.ceil(om_max / 100.0) * 100.0)

    n = len(tiles)
    ncols = args.ncols
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.3 * ncols, 2.3 * nrows),
                             sharex=True, sharey=True, constrained_layout=True)
    axes = np.atleast_1d(axes).ravel()

    counts = {"chaotic": 0, "regular": 0, "transition": 0}
    for ax, (stem, th2, om2, rho, H, q) in zip(axes, tiles):
        counts[q] += 1
        face, a = TINT[q]
        ax.set_facecolor((*_hex2rgb(face), a))
        ax.scatter(th2, om2, s=1.2, alpha=0.45, linewidths=0, color=COLOR_ARM2)
        ax.set_xlim(-185, 185); ax.set_ylim(-om_lim, om_lim)
        ax.set_xticks([-180, 0, 180]); ax.tick_params(labelsize=6)
        rs = f"ρ={rho:.2f}" if rho is not None else "ρ=—"
        ax.set_title(f"{stem_freq(stem):g} Hz   {rs}  H={H:.2f}",
                     fontsize=7.5, color=TINT[q][0], fontweight="bold", pad=2)
    for ax in axes[n:]:
        ax.axis("off")

    fig.suptitle(
        f"Arm-2 phase portraits — 3.2 V sweep   "
        f"[red={counts['chaotic']} unlocked+chaotic · "
        f"green={counts['regular']} locked+regular · "
        f"gray={counts['transition']} transition]",
        fontsize=12, fontweight="bold")
    fig.supxlabel(r"$\theta_2$ (deg)"); fig.supylabel(r"$\omega_2$ (deg/s)")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=140)
    plt.close(fig)
    print(f"{n} clips  ({counts})  ->  {args.out}")


def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


if __name__ == "__main__":
    main()
