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

Sources: H_θ₂ (+ window-to-window σ) from chaos_windows.json, D₂ (+ bootstrap σ)
from dimension.json, θ₁ rms recomputed from verification.csv (with a cycle/acf/
plain error model), inversion fraction (+ binomial σ) from verification.csv.

Error bars: H_θ₂ — SEM across per-window entropies; D₂ — its bootstrap σ;
θ₁ rms — steady-state time-average error (--err-model, see report_common);
% inversion — binomial proportion error. All grow through the chaotic band.

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

from report_common import (
    FIGURES_DIR, clip_dir, list_clips, stem_freq, rms_with_error, ERR_MODELS,
)

H_CHAOS = 0.4


def spectral_entropy(stem):
    """(H_θ₂, σ_H): the headline spectral entropy and the standard error of the
    mean across the per-window entropies (window_entropy[] in
    chaos_windows.json). σ_H is how repeatable the broadband-ness is window to
    window — small for a clean line/limit-cycle spectrum, larger mid-band."""
    try:
        j = json.load(open(os.path.join(clip_dir(stem), "chaos_windows.json"),
                           encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return np.nan, np.nan
    H = float(j.get("spectral_entropy_th2", np.nan))
    we = np.asarray(j.get("window_entropy", []), float)
    sigma = float(np.std(we, ddof=1) / np.sqrt(we.size)) if we.size >= 2 else np.nan
    return H, sigma


def d2(stem):
    """(D₂, σ_D₂) from dimension.json. Value and σ come from the SAME
    bootstrap (pair-sampling) computation, so the bar matches the point."""
    try:
        j = json.load(open(os.path.join(clip_dir(stem), "dimension.json"),
                           encoding="utf-8"))
        return float(j.get("D2_correlation", np.nan)), float(j.get("D2_sigma", np.nan))
    except (OSError, ValueError, TypeError):
        return np.nan, np.nan


def load_theta1(stem):
    """(t, θ₁) over the running phase, for the response-amplitude rms + error."""
    path = os.path.join(clip_dir(stem), "verification.csv")
    t, th1 = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                t.append(float(r["time_s"])); th1.append(float(r["theta1_deg"]))
            except (KeyError, ValueError):
                continue
    return np.asarray(t, float), np.asarray(th1, float)


def frac_inverted(stem, thresh=160.0):
    """(percentage of frames near inversion, σ): σ is the binomial proportion
    error 100·√(p(1−p)/n) on the inversion fraction."""
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
    if th2.size == 0:
        return np.nan, np.nan
    p = float(np.mean(th2 > thresh))
    return 100.0 * p, 100.0 * float(np.sqrt(p * (1.0 - p) / th2.size))


def parse_args():
    p = argparse.ArgumentParser(description="Report chaos-profile figure.")
    p.add_argument("--err-model", choices=ERR_MODELS, default="cycle",
                   help="time-average error model for θ₁ rms (default cycle; "
                        "see report_common). H_θ₂, D₂ and inversion carry their "
                        "own native errors regardless of this flag.")
    p.add_argument("--no-errors", action="store_true",
                   help="draw plain lines without error bars")
    p.add_argument("--out", default=os.path.join(FIGURES_DIR, "chaos_profile_3.2V.png"))
    return p.parse_args()


def main():
    args = parse_args()
    show_err = not args.no_errors
    rows = []
    for stem in list_clips():
        H, He = spectral_entropy(stem)
        D2, D2e = d2(stem)
        t1, th1 = load_theta1(stem)
        amp, ampe = rms_with_error(th1, t1, stem_freq(stem), args.err_model)
        inv, inve = frac_inverted(stem)
        rows.append((stem_freq(stem), H, He, D2, D2e, amp, ampe, inv, inve))
    rows.sort()
    f, H, He, D2, D2e, amp, ampe, inv, inve = (np.asarray(c, float) for c in zip(*rows))

    def yerr(e):
        return e if show_err else None

    fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   constrained_layout=True)
    ebar = dict(capsize=2, elinewidth=0.8, capthick=0.8)

    # shade the chaotic band (H >= H_CHAOS) on both panels
    chaotic = H >= H_CHAOS
    for ax in (ax1, ax3):
        if chaotic.any():
            ax.axvspan(f[chaotic].min(), f[chaotic].max(), color="#c0392b",
                       alpha=0.06, lw=0)

    # top — chaos score
    ax1.errorbar(f, H, yerr=yerr(He), fmt="o-", color="#c0392b",
                 label=r"$H_{\theta_2}$ spectral entropy", **ebar)
    ax1.axhline(H_CHAOS, color="0.6", ls=":", lw=0.8)
    ax1.set_ylabel(r"$H_{\theta_2}$  (0=periodic, 1=chaotic)", color="#c0392b")
    ax1.set_ylim(0, 1.0); ax1.tick_params(axis="y", labelcolor="#c0392b")
    ax1.grid(alpha=0.25)
    ax2 = ax1.twinx()
    ax2.errorbar(f, D2, yerr=yerr(D2e), fmt="s--", color="#8e44ad", ms=4, alpha=0.7,
                 label=r"$D_2$ correlation dim", **ebar)
    ax2.set_ylabel(r"$D_2$", color="#8e44ad"); ax2.tick_params(axis="y", labelcolor="#8e44ad")
    ax1.set_title("Quantified route to chaos vs drive frequency (3.2 V)",
                  loc="left", fontweight="bold")
    L1, La1 = ax1.get_legend_handles_labels(); L2, La2 = ax2.get_legend_handles_labels()
    ax1.legend(L1 + L2, La1 + La2, loc="lower right", fontsize=9)

    # bottom — physical driver
    ax3.errorbar(f, amp, yerr=yerr(ampe), fmt="o-", color="#2980b9",
                 label=r"$\theta_1$ response amplitude (rms)", **ebar)
    ax3.set_ylabel(r"$\theta_1$ rms (deg)", color="#2980b9")
    ax3.tick_params(axis="y", labelcolor="#2980b9"); ax3.grid(alpha=0.25)
    ax3.set_xlabel(r"drive frequency $f_{drive}$ (Hz)")
    ax4 = ax3.twinx()
    ax4.errorbar(f, inv, yerr=yerr(inve), fmt="^-", color="#e67e22", ms=4,
                 label=r"% frames $|\theta_2|>160°$ (near inversion)", **ebar)
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
