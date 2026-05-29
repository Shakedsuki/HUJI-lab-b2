#!/usr/bin/env python3
"""
chaos_profile.py — quantified route to chaos + the physical "why", vs f_drive.

Two stacked panels across the 3.2 V sweep:

  top  — chaos score: spectral entropy H_θ₂ (0 = line spectrum / periodic,
         1 = broadband / chaotic) and the correlation dimension D₂ on a twin
         axis. Both rise sharply at ~0.94 Hz and fall back by ~1.29 Hz — the
         chaotic band.
  bottom — the physical driver: upper-arm response amplitude (θ₁ rms) and the
         fraction of frames the lower arm is near inversion (|θ₂| > 160°). The
         chaotic band coincides with where the (declining) drive still pumps
         arm 2 over the top; once the amplitude drops too far, inversion — and
         chaos — stop.

Sources: H_θ₂ from chaos_windows.json, D₂ + θ₁ rms from the chaos_sweep csv
(report_common.load_metrics), inversion fraction from verification.csv.

Usage:
  python reports/final/scripts/chaos_profile.py

Output:
  reports/final/figures/chaos_profile_3.2V.png
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

from report_common import FIGURES_DIR, clip_dir, list_clips, stem_freq, load_metrics

H_CHAOS = 0.4


def spectral_entropy(stem):
    try:
        return float(json.load(open(os.path.join(clip_dir(stem), "chaos_windows.json"),
                                    encoding="utf-8")).get("spectral_entropy_th2", np.nan))
    except (OSError, ValueError, TypeError):
        return np.nan


def frac_inverted(stem, thresh=160.0):
    path = os.path.join(clip_dir(stem), "verification.csv")
    th2 = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                th2.append(float(r["theta2_deg"]))
            except (KeyError, ValueError):
                continue
    th2 = np.abs(np.asarray(th2, float))
    return 100.0 * np.mean(th2 > thresh) if th2.size else np.nan


def parse_args():
    p = argparse.ArgumentParser(description="Report chaos-profile figure.")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "chaos_profile_3.2V.png"))
    return p.parse_args()


def main():
    args = parse_args()
    metrics = load_metrics()
    rows = []
    for stem in list_clips():
        m = metrics.get(stem, {})
        try:
            D2 = float(m.get("D2", "nan")); amp = float(m.get("theta1_rms", "nan"))
        except ValueError:
            D2 = amp = np.nan
        rows.append((stem_freq(stem), spectral_entropy(stem), D2, amp, frac_inverted(stem)))
    rows.sort()
    f, H, D2, amp, inv = (np.asarray(c, float) for c in zip(*rows))

    fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   constrained_layout=True)

    # shade the chaotic band (H >= H_CHAOS) on both panels
    chaotic = H >= H_CHAOS
    for ax in (ax1, ax3):
        if chaotic.any():
            ax.axvspan(f[chaotic].min(), f[chaotic].max(), color="#c0392b",
                       alpha=0.06, lw=0)

    # top — chaos score
    ax1.plot(f, H, "o-", color="#c0392b", label=r"$H_{\theta_2}$ spectral entropy")
    ax1.axhline(H_CHAOS, color="0.6", ls=":", lw=0.8)
    ax1.set_ylabel(r"$H_{\theta_2}$  (0=periodic, 1=chaotic)", color="#c0392b")
    ax1.set_ylim(0, 1.0); ax1.tick_params(axis="y", labelcolor="#c0392b")
    ax1.grid(alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(f, D2, "s--", color="#8e44ad", ms=4, alpha=0.7, label=r"$D_2$ correlation dim")
    ax2.set_ylabel(r"$D_2$", color="#8e44ad"); ax2.tick_params(axis="y", labelcolor="#8e44ad")
    ax1.set_title("Quantified route to chaos vs drive frequency (3.2 V)",
                  loc="left", fontweight="bold")
    L1, La1 = ax1.get_legend_handles_labels(); L2, La2 = ax2.get_legend_handles_labels()
    ax1.legend(L1 + L2, La1 + La2, loc="lower right", fontsize=9)

    # bottom — physical driver
    ax3.plot(f, amp, "o-", color="#2980b9", label=r"$\theta_1$ response amplitude (rms)")
    ax3.set_ylabel(r"$\theta_1$ rms (deg)", color="#2980b9")
    ax3.tick_params(axis="y", labelcolor="#2980b9"); ax3.grid(alpha=0.25)
    ax3.set_xlabel(r"drive frequency $f_{drive}$ (Hz)")
    ax4 = ax3.twinx()
    ax4.plot(f, inv, "^-", color="#e67e22", ms=4, label=r"% frames $|\theta_2|>160°$ (near inversion)")
    ax4.set_ylabel("% near inversion", color="#e67e22")
    ax4.tick_params(axis="y", labelcolor="#e67e22")
    L3, La3 = ax3.get_legend_handles_labels(); L4, La4 = ax4.get_legend_handles_labels()
    ax3.legend(L3 + L4, La3 + La4, loc="upper right", fontsize=9)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"{len(f)} clips  ->  {args.out}")


if __name__ == "__main__":
    main()
