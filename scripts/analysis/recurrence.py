#!/usr/bin/env python3
"""
recurrence.py — stroboscopic recurrence plot for a driven double-pendulum clip.

Samples the (θ₂, ω₂) state once per drive period T = 1/f_drive (after
discarding the initial transient), normalises both coordinates to [0, 1],
computes the pairwise distance matrix, and thresholds it to produce a
binary recurrence matrix R[i, j] = 1 iff ‖state_i − state_j‖ < ε.

Reading the plot:
    period-1  →  uniform black (every strobe is near every other)
    period-N  →  regular diagonal bands at spacing N
    quasiperiodic  →  broad diagonal bands, slowly drifting
    chaos     →  fragmented texture, short diagonal segments

Usage
~~~~~
  python scripts/analysis/recurrence.py --stem 3.2V_1.18Hz
  python scripts/analysis/recurrence.py --stem 3.2V_0.91Hz --threshold-pct 12

Output
~~~~~~
  figures/recurrence/<stem>_recurrence.png
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

from rich.console import Console
console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import EXPERIMENTS, clip_dir                  # noqa: E402
from figures_paths import figure_path, mirror_to_ready   # noqa: E402
from driven_helpers import parse_stem, load_driven_csv   # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True,
                   help="Driven clip stem, e.g. 3.2V_1.18Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="Seconds to skip at start (default 5).")
    p.add_argument("--threshold-pct", type=float, default=15.0,
                   help="Recurrence threshold as percentile of nonzero "
                        "pairwise distances (default 15).")
    p.add_argument("--f-drive", type=float, default=None,
                   help="Override drive frequency (Hz).")
    return p.parse_args()


def resolve_f_drive(stem, override):
    if override is not None:
        return override
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, encoding="utf-8") as f:
            exp = json.load(f)
        if stem in exp and "drive_freq_hz" in exp[stem]:
            return float(exp[stem]["drive_freq_hz"])
    return parse_stem(stem)["f_drive_hz"]


def strobe_sample(t, th2, om2, f_drive, transient_s):
    """Sample (θ₂, ω₂) once per drive period, after transient."""
    T = 1.0 / f_drive
    n0 = int(np.ceil(transient_s / T))
    n1 = int(np.floor(t[-1] / T))
    if n1 < n0:
        return np.array([]), np.array([]), np.array([])
    ts = np.arange(n0, n1 + 1) * T
    return ts, np.interp(ts, t, th2), np.interp(ts, t, om2)


def recurrence_matrix(th2s, om2s, threshold_pct):
    """Binary recurrence matrix from normalised (θ₂, ω₂) states."""
    n = len(th2s)
    if n < 3:
        return np.zeros((1, 1))
    th_range = th2s.max() - th2s.min()
    om_range = om2s.max() - om2s.min()
    th_n = (th2s - th2s.min()) / (th_range + 1e-12)
    om_n = (om2s - om2s.min()) / (om_range + 1e-12)
    states = np.column_stack([th_n, om_n])
    diff = states[:, None, :] - states[None, :, :]
    dist = np.sqrt((diff ** 2).sum(axis=2))
    nonzero = dist[dist > 0]
    if len(nonzero) == 0:
        return np.ones((n, n))
    threshold = np.percentile(nonzero, threshold_pct)
    return (dist < threshold).astype(float)


def load_metrics(stem):
    """Load D₂ and λ₁ from chaos_sweep CSV if available."""
    from figures_paths import AGGREGATE
    import glob
    for path in glob.glob(os.path.join(AGGREGATE, "chaos_sweep_*.csv")):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("stem") == stem:
                        d2 = float(r.get("D2", "nan"))
                        lam = float(r.get("lambda1", "nan"))
                        return d2, lam
        except (OSError, KeyError, ValueError):
            continue
    return np.nan, np.nan


D2_CHAOS_THRESHOLD = 1.8


def make_figure(stem, ts, th2s, om2s, R, f_drive, transient_s,
                threshold_pct, out_path):
    d2, lam = load_metrics(stem)
    regime = "CHAOTIC" if d2 >= D2_CHAOS_THRESHOLD else "REGULAR"
    col = "#c0392b" if regime == "CHAOTIC" else "#2e8b57"

    fig, (ax_rp, ax_strobe) = plt.subplots(
        1, 2, figsize=(13, 6), constrained_layout=True,
        gridspec_kw={"width_ratios": [1.1, 1]})

    # Left: recurrence plot
    ax_rp.imshow(R, cmap="Greys", origin="lower", interpolation="nearest",
                 aspect="equal")
    ax_rp.set_xlabel("strobe index n", fontsize=11)
    ax_rp.set_ylabel("strobe index m", fontsize=11)
    ax_rp.set_title(f"Recurrence plot  (ε = {threshold_pct:.0f}th pctile,"
                    f"  n = {len(ts)} strobes)", fontsize=11)

    # Right: the stroboscopic section for reference
    if len(ts) > 0:
        sc = ax_strobe.scatter(th2s, om2s, c=ts, cmap="viridis", s=18,
                               alpha=0.85, edgecolors="k", linewidths=0.3)
        plt.colorbar(sc, ax=ax_strobe, label="t (s)", shrink=0.85)
    ax_strobe.axhline(0, color="gray", lw=0.5, ls="--")
    ax_strobe.axvline(0, color="gray", lw=0.5, ls="--")
    ax_strobe.set_xlabel(r"$\theta_2$ (deg)", fontsize=11)
    ax_strobe.set_ylabel(r"$\omega_2$ (deg/s)", fontsize=11)
    ax_strobe.set_title(r"Stroboscopic section ($\theta_2, \omega_2$)",
                        fontsize=11)
    ax_strobe.grid(True, alpha=0.3)

    # Metrics caption
    bits = [f"f_drive = {f_drive:.3f} Hz"]
    if np.isfinite(d2):
        bits.append(f"D₂ = {d2:.2f}")
    if np.isfinite(lam):
        bits.append(f"λ₁ = {lam:+.2f}/s")
    caption = "   ".join(bits)

    fig.suptitle(f"Recurrence — {stem}   [{regime}]   {caption}",
                 fontsize=13, fontweight="bold", color=col)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    mirror_to_ready(out_path)
    plt.close(fig)


def main():
    args = parse_args()
    stem = args.stem
    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    f_drive = resolve_f_drive(stem, args.f_drive)
    t, _, th2, _, om2 = load_driven_csv(csv_path)

    ts, th2s, om2s = strobe_sample(t, th2, om2, f_drive, args.transient)
    if len(ts) < 5:
        raise SystemExit(f"Too few strobe samples ({len(ts)}) — "
                         f"clip may be shorter than transient.")

    R = recurrence_matrix(th2s, om2s, args.threshold_pct)

    out_path = figure_path("recurrence", stem)
    make_figure(stem, ts, th2s, om2s, R, f_drive, args.transient,
                args.threshold_pct, out_path)
    console.print(f"  [dim]{stem}  ({len(ts)} strobes) → {out_path}[/]")


if __name__ == "__main__":
    main()
