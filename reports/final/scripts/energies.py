#!/usr/bin/env python3
"""
energies.py — final-report mechanical energy vs drive frequency.

Static report version of N. Cohen's interactive energy explorer. For every
3.2 V clip it reconstructs the kinetic (T) and potential (U) energy of the two
rods, averages each over the steady-state tail, and plots ⟨E⟩, ⟨T⟩, ⟨U⟩ and the
virial ratio ⟨T⟩/⟨U⟩ against drive frequency — the resonance peak plus the
departure of T/U from 1 (an anharmonicity / chaos marker) across the sweep.

Two changes from the original beyond making it static:
  - ω from the shared SG derivative (kinematics.angular_velocity), NOT a raw
    np.gradient — energy ∝ ω², so finite-difference jitter would inflate T.
  - θ from verification.csv, steady-state slice via report_common.tail_window.

Rod model (N. Cohen): two uniform rods, M=0.1 kg, L=0.27 m each. These set the
absolute Joule scale (approximate); the resonance shape and T/U ratio are the
physics of interest.

Usage:
  python reports/final/scripts/energies.py
  python reports/final/scripts/energies.py --window 60

Output:
  reports/final/figures/energies_3.2V.png
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

from report_common import FIGURES_DIR, clip_dir, list_clips, tail_window, stem_freq

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts", "utils"))
from kinematics import angular_velocity     # noqa: E402

# rod model (N. Cohen): two uniform rods
M1 = M2 = 0.1      # kg
L1 = L2 = 0.27     # m (full rod length)
G = 9.81           # m/s²


def load_clip(stem):
    path = os.path.join(clip_dir(stem), "verification.csv")
    t, a, b = [], [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                t.append(float(r["time_s"]))
                a.append(float(r["theta1_deg"])); b.append(float(r["theta2_deg"]))
            except (KeyError, ValueError):
                continue
    return np.asarray(t, float), np.asarray(a, float), np.asarray(b, float)


def energies(stem, window_s):
    """Steady-state ⟨E⟩, ⟨T⟩, ⟨U⟩ (J) for one clip."""
    t, th1, th2 = load_clip(stem)
    om1 = np.radians(angular_velocity(th1, t))      # SG derivative -> rad/s
    om2 = np.radians(angular_velocity(th2, t))
    r1, r2 = np.radians(th1), np.radians(th2)
    # kinetic (two-rod double pendulum, full coupling)
    T1 = (1.0 / 6.0) * M1 * L1**2 * om1**2
    T2 = (0.5 * M2 * L1**2 * om1**2
          + (1.0 / 6.0) * M2 * L2**2 * om2**2
          + 0.5 * M2 * L1 * L2 * om1 * om2 * np.cos(r1 - r2))
    # potential
    U1 = M1 * G * (L1 / 2.0) * (1 - np.cos(r1))
    U2 = M2 * G * (L1 * (1 - np.cos(r1)) + (L2 / 2.0) * (1 - np.cos(r2)))
    T, U = T1 + T2, U1 + U2
    _, T, U = tail_window(t, T, U, window_s=window_s)
    return float(np.mean(T + U)), float(np.mean(T)), float(np.mean(U))


def parse_args():
    p = argparse.ArgumentParser(description="Report energy vs drive frequency.")
    p.add_argument("--window", type=float, default=60.0,
                   help="steady-state tail window in s (default 60)")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "energies_3.2V.png"))
    return p.parse_args()


def main():
    args = parse_args()
    f, E, T, U = [], [], [], []
    for stem in list_clips():
        try:
            e, kt, pu = energies(stem, args.window)
        except (FileNotFoundError, ValueError):
            continue
        f.append(stem_freq(stem)); E.append(e); T.append(kt); U.append(pu)
    f, E, T, U = map(np.asarray, (f, E, T, U))
    ratio = np.divide(T, U, out=np.zeros_like(T), where=U > 1e-12)

    fig, ax1 = plt.subplots(figsize=(11, 6), constrained_layout=True)
    ax1.plot(f, E, "o-", color="black", lw=2.0, label=r"total $E$")
    ax1.plot(f, T, "s--", color="#2980b9", ms=4, lw=1.5, label=r"kinetic $T$")
    ax1.plot(f, U, "^-.", color="#2e8b57", ms=4, lw=1.5, label=r"potential $U$")
    ax1.set_xlabel("drive frequency $f_{drive}$ (Hz)")
    ax1.set_ylabel("steady-state energy (J)")
    ax1.grid(alpha=0.3)
    ax1.set_ylim(0, float(np.max(E)) * 1.15)

    ax2 = ax1.twinx()
    ax2.plot(f, ratio, ":", color="#8e44ad", lw=2.0, marker="D", ms=4, label=r"$T/U$ (virial)")
    ax2.axhline(1.0, color="#8e44ad", lw=1.0, alpha=0.3)
    ax2.set_ylabel(r"virial ratio  $\langle T\rangle/\langle U\rangle$", color="#8e44ad")
    ax2.tick_params(axis="y", labelcolor="#8e44ad")

    # mark resonance peak in total energy
    i = int(np.argmax(E))
    ax1.annotate(f"resonance\n{f[i]:g} Hz", xy=(f[i], E[i]), xytext=(0, 22),
                 textcoords="offset points", ha="center", fontsize=10, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", lw=1.3))

    lines = ax1.get_lines()[:3] + ax2.get_lines()[:1]
    ax1.legend(lines, [ln.get_label() for ln in lines], loc="upper right", fontsize=9)
    ax1.set_title(r"Mechanical energy & virial ratio vs drive frequency (3.2 V)",
                  loc="left", fontweight="bold")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"{len(f)} clips  peak E at {f[i]:g} Hz  ->  {args.out}")


if __name__ == "__main__":
    main()
