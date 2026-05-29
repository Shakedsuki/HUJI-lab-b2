#!/usr/bin/env python3
"""
phase_area.py — normalised phase-space filling of arm 2 vs drive frequency.

A scalar chaos proxy: how much 2-D area the (θ₂, ω₂) trajectory OCCUPIES,
normalised to its own bounding box so amplitude drops out. A periodic limit
cycle is a 1-D loop and fills almost nothing; a strange attractor fills a 2-D
blob. Concretely the filling fraction is

    occupied 32×32 grid cells / 1024

over the cloud normalised to [0,1]². Low at the regular ends, high through the
chaotic core — a route-to-chaos curve from pure geometry.

Reuses (no new maths):
  - portrait loader: verification.csv θ₂ + kinematics.angular_velocity ω₂ +
    report_common.tail_window (PORTRAIT_WINDOW_S = 60 s);
  - cell counting: dimension.box_counting_dimension (normalises the cloud and
    returns occupied-cell counts; D_box from the same call is overlaid as the
    dimension cross-check — ≈1 loop, →2 filled).

Usage:
  python reports/final/scripts/phase_area.py

Output:
  reports/final/figures/phase_area_3.2V.png
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
    FIGURES_DIR, PORTRAIT_WINDOW_S, clip_dir, list_clips, tail_window, stem_freq,
)

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts", "utils"))
sys.path.insert(0, os.path.join(_REPO, "scripts", "analysis"))
from kinematics import angular_velocity         # noqa: E402
from dimension import box_counting_dimension     # noqa: E402

GRID_K = 5          # 2**5 = 32 -> 32x32 grid, 1024 cells
H_CHAOS = 0.4       # spectral-entropy split, for band shading


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


def spectral_entropy(stem):
    try:
        return float(json.load(open(os.path.join(clip_dir(stem), "chaos_windows.json"),
                                    encoding="utf-8")).get("spectral_entropy_th2", np.nan))
    except (OSError, ValueError, TypeError):
        return np.nan


def filling_and_dbox(th2, om2):
    pts = np.column_stack([th2, om2])
    box = box_counting_dimension(pts)            # normalises cloud to [0,1]^2
    nb = 2 ** GRID_K
    return float(box["Ns"][GRID_K - 1]) / (nb * nb), float(box["Dbox"])


def parse_args():
    p = argparse.ArgumentParser(description="Report phase-space filling vs f_drive.")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "phase_area_3.2V.png"))
    return p.parse_args()


def main():
    args = parse_args()
    rows = []
    for stem in list_clips():
        t, th2 = load_theta2(stem)
        om2 = angular_velocity(th2, t)
        t, th2, om2 = tail_window(t, th2, om2, window_s=PORTRAIT_WINDOW_S)
        if t.size < 64:
            continue
        ff, dbox = filling_and_dbox(th2, om2)
        rows.append((stem_freq(stem), ff, dbox, spectral_entropy(stem)))
    rows.sort()
    f, ff, dbox, H = (np.asarray(c, float) for c in zip(*rows))

    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
    chaotic = H >= H_CHAOS
    if chaotic.any():
        ax.axvspan(f[chaotic].min(), f[chaotic].max(), color="#c0392b", alpha=0.06, lw=0)

    ax.plot(f, ff, "o-", color="#c0392b", lw=1.8, label="phase-space filling fraction (32×32)")
    ax.fill_between(f, 0, ff, color="#c0392b", alpha=0.10)
    ax.set_xlabel(r"drive frequency $f_{drive}$ (Hz)")
    ax.set_ylabel("filling fraction (occupied / 1024)", color="#c0392b")
    ax.tick_params(axis="y", labelcolor="#c0392b")
    ax.set_ylim(0, float(np.max(ff)) * 1.15); ax.grid(alpha=0.25)

    ax2 = ax.twinx()
    ax2.plot(f, dbox, "s--", color="#8e44ad", ms=4, alpha=0.7,
             label=r"$D_{box}$ (1 = loop, 2 = filled)")
    ax2.set_ylabel(r"$D_{box}$", color="#8e44ad")
    ax2.tick_params(axis="y", labelcolor="#8e44ad"); ax2.set_ylim(0.8, 2.05)

    L1, La1 = ax.get_legend_handles_labels(); L2, La2 = ax2.get_legend_handles_labels()
    ax.legend(L1 + L2, La1 + La2, loc="upper right", fontsize=9)
    ax.set_title("Phase-space area filled by arm 2 vs drive frequency (3.2 V)",
                 loc="left", fontweight="bold")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"{len(f)} clips  ->  {args.out}")


if __name__ == "__main__":
    main()
