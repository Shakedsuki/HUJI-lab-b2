"""
verify_tracking.py
------------------
Compute ω from tracking.csv and write verification.csv.

What this script does
~~~~~~~~~~~~~~~~~~~~~
1. Read tracking.csv (10 cols from bgr_tracker).
2. Compute ω₁(t) and ω₂(t) via Savitzky-Golay differentiation of θ
   with proper ±180° unwrapping.
3. Write verification.csv with the same 10 cols plus omega1_deg_s and
   omega2_deg_s.
4. Optionally write verification.png (θ + ω panels).

No "suspect" detection. No arm-length, marker-swap, or |Δω| checks.
The verdict (track_one.compute_verdict) is binary based on dropout —
nothing else is needed. Downstream analysis scripts read omega1_deg_s
/ omega2_deg_s for Poincaré, Lyapunov, and bifurcation plots.

verification.csv columns
~~~~~~~~~~~~~~~~~~~~~~~~
    frame, time_s, phase, x_green, y_green, x_red, y_red,
    theta1_deg, theta2_deg, dropout,
    omega1_deg_s, omega2_deg_s

Usage
~~~~~
    python scripts/processing/verify_tracking.py --stem 4V_1.9Hz
"""

import argparse
import csv
import os
import sys

import numpy as np
from scipy.signal import savgol_filter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import MEAS_DIR, clip_dir  # noqa: E402

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

console = Console()

SG_WINDOW = 7
SG_POLY   = 3


def parse_args():
    p = argparse.ArgumentParser(
        description="Compute ω from tracking.csv; write verification.csv.")
    p.add_argument("csv", nargs="?", default=None,
                   help="path to tracking CSV (positional)")
    p.add_argument("--stem", default=None,
                   help="config_description; resolves CSV and out dir "
                        "from measurements/<stem>/")
    p.add_argument("--no-plot", action="store_true",
                   help="skip the matplotlib plot")
    p.add_argument("--no-csv-out", action="store_true",
                   help="skip writing verification.csv")
    # Legacy flags retained as no-ops so older callers don't break.
    p.add_argument("--omega-cap", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--arm-len-threshold", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--delta-omega-cap", type=float, default=None, help=argparse.SUPPRESS)
    return p.parse_args()


def resolve_paths(args):
    if args.stem:
        meas_dir = clip_dir(args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            console.print(f"[red]ERROR:[/] tracking.csv not found for stem '{args.stem}'")
            console.print(f"  [dim]Expected: {csv_path}[/]")
            sys.exit(1)
        return csv_path, meas_dir, args.stem
    if args.csv:
        csv_path = args.csv
        if not os.path.isabs(csv_path):
            csv_path = os.path.join(MEAS_DIR, csv_path)
        output_dir = os.path.dirname(csv_path)
        stem_label = os.path.basename(output_dir)
        return csv_path, output_dir, stem_label
    console.print("[red]ERROR:[/] provide --stem or a positional CSV path.")
    sys.exit(1)


def smooth_omega(angles, dt):
    """ω = dθ/dt via Savitzky-Golay. Unwraps ±180° jumps. NaN
    propagates through gaps. Output in deg/s."""
    a = np.asarray(angles, dtype=float)
    n = len(a)
    if n < SG_WINDOW:
        return np.full(n, np.nan)
    nan_mask = np.isnan(a)
    if nan_mask.all():
        return np.full(n, np.nan)
    a_filled = a.copy()
    idx = np.arange(n)
    if nan_mask.any():
        a_filled[nan_mask] = np.interp(idx[nan_mask], idx[~nan_mask],
                                        a_filled[~nan_mask])
    a_unw_deg = np.degrees(np.unwrap(np.radians(a_filled)))
    om = savgol_filter(a_unw_deg, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om[nan_mask] = np.nan
    return om


def main():
    args = parse_args()
    csv_path, output_dir, stem = resolve_paths(args)

    t_hdr = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t_hdr.add_column(style="dim", min_width=12)
    t_hdr.add_column(style="white")
    t_hdr.add_row("CSV",    f"[dim]{csv_path}[/]")
    t_hdr.add_row("Folder", f"[dim]{output_dir}[/]")
    console.print(t_hdr)

    with open(csv_path, "r") as f:
        rows = list(csv.DictReader(f))

    n = len(rows)
    if n == 0:
        console.print("[red]ERROR:[/] empty tracking.csv")
        return 1

    def to_float_or_nan(x):
        return float(x) if x not in ("", None) else np.nan

    times = np.array([float(r["time_s"]) for r in rows])
    drops = np.array([int(r["dropout"])  for r in rows])
    th1   = np.array([to_float_or_nan(r["theta1_deg"]) for r in rows])
    th2   = np.array([to_float_or_nan(r["theta2_deg"]) for r in rows])

    diffs = np.diff(times)
    dt = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 1.0 / 60.0

    om1 = smooth_omega(th1, dt)
    om2 = smooth_omega(th2, dt)

    n_drop = int(np.sum(drops == 1))
    drop_pct = 100.0 * n_drop / n
    drop_color = "green" if drop_pct <= 5.0 else "red"

    t_tot = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t_tot.add_column(style="dim", min_width=16)
    t_tot.add_column(style="white", justify="right")
    t_tot.add_row("median dt",     f"{dt * 1000:.2f} ms  ({1.0 / dt:.2f} fps)")
    t_tot.add_row("total frames",  str(n))
    t_tot.add_row("dropouts",      f"[{drop_color}]{n_drop} ({drop_pct:.2f}%)[/]")
    console.print(t_tot)

    # ── Write verification.csv ──────────────────────────────────────
    if not args.no_csv_out:
        os.makedirs(output_dir, exist_ok=True)
        out_csv = os.path.join(output_dir, "verification.csv")
        with open(out_csv, "w", newline="") as f:
            fieldnames = list(rows[0].keys()) + [
                "omega1_deg_s", "omega2_deg_s",
            ]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for i, r in enumerate(rows):
                out = dict(r)
                out["omega1_deg_s"] = (
                    f"{om1[i]:.2f}" if not np.isnan(om1[i]) else "")
                out["omega2_deg_s"] = (
                    f"{om2[i]:.2f}" if not np.isnan(om2[i]) else "")
                w.writerow(out)
        console.print(f"  [green]✓[/] wrote [dim]{out_csv}[/]")

    # ── Optional matplotlib plot ────────────────────────────────────
    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            console.print("[dim]matplotlib not available — skipping plot[/]")
            return 0
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
        axes[0].plot(times, th1, lw=0.6, label="θ1")
        axes[0].plot(times, th2, lw=0.6, label="θ2", alpha=0.7)
        axes[0].set_ylabel("angle (deg)")
        axes[0].legend(loc="upper right", fontsize=8)
        axes[0].grid(alpha=0.3)
        axes[1].plot(times, om1, lw=0.5, label="ω1")
        axes[1].plot(times, om2, lw=0.5, label="ω2", alpha=0.7)
        axes[1].set_ylabel("ω (deg/s)")
        axes[1].set_xlabel("t (s)")
        axes[1].legend(loc="upper right", fontsize=8)
        axes[1].grid(alpha=0.3)
        plt.tight_layout()
        out_png = os.path.join(output_dir, "verification.png")
        plt.savefig(out_png, dpi=150)
        plt.close(fig)
        console.print(f"  [green]✓[/] wrote [dim]{out_png}[/]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
