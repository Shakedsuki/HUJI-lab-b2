"""
driven_poincare.py
------------------
Stroboscopic (drive-synchronized) Poincare section for a single Phase 2
clip.  Samples (theta1, omega1) exactly once per drive period
T = 1/f_drive, with f_drive parsed from experiments.json or the stem.

Compared to scripts/analysis/poincare.py (which uses a geometric section
theta1+theta2 = 0), this is the natural Poincare map for a periodically
driven oscillator:
    period-1 locked  -> single fixed point.
    period-2         -> two points.
    quasiperiodic    -> closed invariant curve.
    chaos            -> strange-attractor cross section.

Note on absolute phase
~~~~~~~~~~~~~~~~~~~~~~
Strobe times are t = n/f_drive measured from t=0 of the video. The
absolute phase of the drive at t=0 is unknown (we have no sync signal).
This is fine for regime detection (period-n cardinality is phase-
invariant) but means theta1 values are not directly comparable across
clips that started at different drive phases.

Usage
~~~~~
  python scripts/analysis/driven_poincare.py --stem 3V_1.5Hz
  python scripts/analysis/driven_poincare.py --stem 3V_0.25Hz --transient 8

Output
~~~~~~
  measurements/<stem>/driven_poincare.csv
  figures/poincare/<stem>_driven_poincare.png  (4-panel)
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
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import MEAS_DIR, EXPERIMENTS, clip_dir  # noqa: E402
from figures_paths import FIGURES_DIR, mirror_to_ready  # noqa: E402
from driven_helpers import (parse_stem, load_driven_csv,  # noqa: E402
                            strobe_sample)
from figure_style import compact_tile_ax  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True,
                   help="Phase 2 clip stem, e.g. 3V_1.5Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="Seconds to skip at start (default: 5).")
    p.add_argument("--f-drive", type=float, default=None,
                   help="Override drive frequency (Hz). Default: from "
                        "experiments.json, falling back to parse_stem.")
    p.add_argument("--no-csv", action="store_true")
    return p.parse_args()


def resolve_f_drive(stem, override):
    if override is not None:
        return override, "override"
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, encoding="utf-8") as f:
            exp = json.load(f)
        if stem in exp and "drive_freq_hz" in exp[stem]:
            return float(exp[stem]["drive_freq_hz"]), "experiments.json"
    return parse_stem(stem)["f_drive_hz"], "stem name"


def draw_strobe_section(ax, x, y, ts, xlabel, ylabel, title=None, *, compact=False):
    """Stroboscopic section scatter, coloured by time. Shared by the per-clip
    figure and the palette tile (compact=True trims markers/labels for tiles).
    The time colour shows the section filling: orderly sweep = quasiperiodic
    curve, scattered = chaos. Returns the scatter handle (None if no points)."""
    sc = None
    if len(ts) > 0:
        if compact:
            sc = ax.scatter(x, y, c=ts, cmap=plt.cm.viridis, s=7, alpha=0.9,
                            linewidths=0)
        else:
            sc = ax.scatter(x, y, c=ts, cmap=plt.cm.viridis, s=22, alpha=0.9,
                            edgecolors="k", linewidths=0.3)
    if compact:
        ax.axhline(0, color="0.85", lw=0.4)
        ax.axvline(0, color="0.85", lw=0.4)
        compact_tile_ax(ax, xlabel, ylabel)
    else:
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.axvline(0, color="gray", lw=0.5, ls="--")
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=11)
        ax.grid(True, alpha=0.3)
    return sc


def _strobe_vs_time(ax, ts, ys, ylabel, title):
    """Strobe-sampled angle vs time (period-n diagnostic)."""
    if len(ts) > 0:
        ax.scatter(ts, ys, c=ts, cmap=plt.cm.viridis, s=15,
                   edgecolors="k", linewidths=0.3)
        ax.plot(ts, ys, color="0.6", lw=0.5, zorder=0)
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.set_xlabel("t (s)"); ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3)


def _phase_overlay(ax, x_full, y_full, t_full, x_s, y_s, xlabel, ylabel, title):
    """Full phase portrait with strobe points overlaid in red."""
    ax.scatter(x_full, y_full, c=t_full, cmap=plt.cm.Greys, s=1, alpha=0.45)
    if len(x_s) > 0:
        ax.scatter(x_s, y_s, color="tab:red", s=22, zorder=5,
                   edgecolors="k", linewidths=0.3, label="strobe points")
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.axvline(0, color="gray", lw=0.5, ls="--")
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.3)
    if len(x_s) > 0:
        ax.legend(loc="upper right", fontsize=8)


def make_figure(t, th1, th2, om1, om2,
                t_s, th1_s, th2_s, om1_s, om2_s,
                stem, f_drive, transient_s, out_path):
    n_s = len(t_s)
    fig, axes = plt.subplots(2, 3, figsize=(17, 11), constrained_layout=True)

    # ── Row 0: Arm 1 ────────────────────────────────────
    sc1 = draw_strobe_section(axes[0, 0], th1_s, om1_s, t_s,
                              r"$\theta_1$ (deg) at strobe",
                              r"$\omega_1$ (deg/s) at strobe",
                              f"Arm 1 stroboscopic  (n={n_s})")
    if sc1 is not None:
        plt.colorbar(sc1, ax=axes[0, 0], label="t (s)", shrink=0.85)
    _strobe_vs_time(axes[0, 1], t_s, th1_s,
                    r"$\theta_1$ (deg)",
                    r"Arm 1 — strobe $\theta_1$ vs time")
    _phase_overlay(axes[0, 2], th1, om1, t, th1_s, om1_s,
                   r"$\theta_1$ (deg)", r"$\omega_1$ (deg/s)",
                   "Arm 1 phase portrait + strobe")

    # ── Row 1: Arm 2 ────────────────────────────────────
    sc2 = draw_strobe_section(axes[1, 0], th2_s, om2_s, t_s,
                              r"$\theta_2$ (deg) at strobe",
                              r"$\omega_2$ (deg/s) at strobe",
                              f"Arm 2 stroboscopic  (n={n_s})")
    if sc2 is not None:
        plt.colorbar(sc2, ax=axes[1, 0], label="t (s)", shrink=0.85)
    _strobe_vs_time(axes[1, 1], t_s, th2_s,
                    r"$\theta_2$ (deg)",
                    r"Arm 2 — strobe $\theta_2$ vs time")
    _phase_overlay(axes[1, 2], th2, om2, t, th2_s, om2_s,
                   r"$\theta_2$ (deg)", r"$\omega_2$ (deg/s)",
                   "Arm 2 phase portrait + strobe")

    fig.suptitle(
        f"Driven Poincare — {stem}   "
        f"(f_drive = {f_drive:.3f} Hz, T = {1/f_drive:.3f} s, "
        f"transient = {transient_s:.1f} s)",
        fontsize=13)

    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    mirror_to_ready(out_path)
    plt.close(fig)


def main():
    args = parse_args()
    stem = args.stem
    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    f_drive, src = resolve_f_drive(stem, args.f_drive)

    t_info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    t_info.add_column(style="dim", min_width=20)
    t_info.add_column(style="white", justify="right")
    t_info.add_row("stem",    f"[cyan]{stem}[/]")
    t_info.add_row("f_drive", f"{f_drive:.4f} Hz  [dim](source: {src})[/]")
    t_info.add_row("T",       f"{1/f_drive:.4f} s")

    t, th1, th2, om1, om2 = load_driven_csv(csv_path)
    t_info.add_row("rows loaded", f"{len(t)}  [dim]t ∈ [0, {t[-1]:.2f}] s[/]")

    t_s, th1_s, om1_s = strobe_sample(t, th1, om1, f_drive,
                                      transient_s=args.transient)
    # Arm 2: interpolate on the same strobe times.
    th2_s = np.interp(t_s, t, th2) if len(t_s) > 0 else np.array([])
    om2_s = np.interp(t_s, t, om2) if len(t_s) > 0 else np.array([])

    t_info.add_row("strobe samples",
                   f"{len(t_s)}  [dim](skipping first {args.transient:.1f} s)[/]")
    console.print(t_info)

    if not args.no_csv:
        out_csv = os.path.join(clip_dir(stem), "driven_poincare.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "theta1_deg", "omega1_deg_s",
                        "theta2_deg", "omega2_deg_s"])
            for tc, a1, w1, a2, w2 in zip(t_s, th1_s, om1_s, th2_s, om2_s):
                w.writerow([f"{tc:.4f}", f"{a1:.4f}", f"{w1:.4f}",
                            f"{a2:.4f}", f"{w2:.4f}"])
        console.print(f"  [dim]Saved → {out_csv}[/]")

    out_dir = os.path.join(FIGURES_DIR, "driven_poincare")
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, f"{stem}_driven_poincare.png")
    make_figure(t, th1, th2, om1, om2,
                t_s, th1_s, th2_s, om1_s, om2_s,
                stem, f_drive, args.transient, out_png)
    console.print(f"  [dim]Saved → {out_png}[/]")


if __name__ == "__main__":
    main()
