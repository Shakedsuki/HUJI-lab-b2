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

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import MEAS_DIR, EXPERIMENTS  # noqa: E402
from figures_paths import FIGURES_DIR, mirror_to_ready  # noqa: E402
from driven_helpers import (parse_stem, load_driven_csv,  # noqa: E402
                            strobe_sample)


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


def make_figure(t, th1, om1, t_s, th1_s, om1_s,
                stem, f_drive, transient_s, out_path):
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.28,
                          left=0.07, right=0.97, top=0.93, bottom=0.07)
    ax_main = fig.add_subplot(gs[:, 0])
    ax_tl   = fig.add_subplot(gs[0, 1])
    ax_full = fig.add_subplot(gs[1, 1])

    # Main: stroboscopic section, coloured by time.
    if len(t_s) > 0:
        sc = ax_main.scatter(th1_s, om1_s, c=t_s,
                             cmap=plt.cm.viridis, s=22, alpha=0.9,
                             edgecolors="k", linewidths=0.3)
        plt.colorbar(sc, ax=ax_main, label="t (s)", shrink=0.85)
    ax_main.axhline(0, color="gray", lw=0.5, ls="--")
    ax_main.axvline(0, color="gray", lw=0.5, ls="--")
    ax_main.set_xlabel(r"$\theta_1$  (deg) at strobe")
    ax_main.set_ylabel(r"$\omega_1$  (deg/s) at strobe")
    ax_main.set_title(
        f"Stroboscopic Poincare:  t = n / f_drive   (n = {len(t_s)} strobes)")
    ax_main.grid(True, alpha=0.3)

    # Top right: theta1 at each strobe vs time (period-n diagnostic).
    if len(t_s) > 0:
        ax_tl.scatter(t_s, th1_s, c=t_s, cmap=plt.cm.viridis, s=15,
                      edgecolors="k", linewidths=0.3)
        # Connect successive strobes lightly to read off period structure.
        ax_tl.plot(t_s, th1_s, color="0.6", lw=0.5, zorder=0)
    ax_tl.set_xlabel("t (s)")
    ax_tl.set_ylabel(r"$\theta_1$ (deg) at strobe")
    ax_tl.set_title("Strobe samples vs time")
    ax_tl.axhline(0, color="gray", lw=0.5, ls="--")
    ax_tl.grid(True, alpha=0.3)

    # Bottom right: full phase portrait + strobe overlay.
    ax_full.scatter(th1, om1, c=t, cmap=plt.cm.Greys, s=1, alpha=0.45)
    if len(t_s) > 0:
        ax_full.scatter(th1_s, om1_s, color="tab:red", s=22, zorder=5,
                        edgecolors="k", linewidths=0.3,
                        label="strobe points")
    ax_full.set_xlabel(r"$\theta_1$ (deg)")
    ax_full.set_ylabel(r"$\omega_1$ (deg/s)")
    ax_full.set_title("Full phase portrait + strobe overlay")
    ax_full.axhline(0, color="gray", lw=0.5, ls="--")
    ax_full.axvline(0, color="gray", lw=0.5, ls="--")
    ax_full.grid(True, alpha=0.3)
    if len(t_s) > 0:
        ax_full.legend(loc="upper right", fontsize=9)

    fig.suptitle(
        f"Driven Poincare — {stem}   "
        f"(f_drive = {f_drive:.3f} Hz, T = {1/f_drive:.3f} s, "
        f"transient = {transient_s:.1f} s)",
        fontsize=13, y=0.99)

    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    mirror_to_ready(out_path)
    plt.close(fig)


def main():
    args = parse_args()
    stem = args.stem
    csv_path = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"verification.csv not found at {csv_path}")

    f_drive, src = resolve_f_drive(stem, args.f_drive)
    print(f"Stem: {stem}")
    print(f"f_drive = {f_drive:.4f} Hz   (source: {src})")
    print(f"T = {1/f_drive:.4f} s")

    t, th1, _, om1, _ = load_driven_csv(csv_path)
    print(f"Loaded {len(t)} free_swing rows; t in [0, {t[-1]:.2f}] s")

    t_s, th1_s, om1_s = strobe_sample(t, th1, om1, f_drive,
                                      transient_s=args.transient)
    print(f"Stroboscopic samples: {len(t_s)} "
          f"(skipping first {args.transient:.1f} s)")

    if not args.no_csv:
        out_csv = os.path.join(MEAS_DIR, stem, "driven_poincare.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "theta1_deg", "omega1_deg_s"])
            for tc, th, om in zip(t_s, th1_s, om1_s):
                w.writerow([f"{tc:.4f}", f"{th:.4f}", f"{om:.4f}"])
        print(f"Wrote {out_csv}")

    out_dir = os.path.join(FIGURES_DIR, "driven_poincare")
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, f"{stem}_driven_poincare.png")
    make_figure(t, th1, om1, t_s, th1_s, om1_s,
                stem, f_drive, args.transient, out_png)
    print(f"Wrote {out_png}")


if __name__ == "__main__":
    main()
