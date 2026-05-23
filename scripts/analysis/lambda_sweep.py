#!/usr/bin/env python3
"""
lambda_sweep.py — largest Lyapunov exponent λ₁ vs drive frequency.

Reads the per-clip λ₁ collected in figures/aggregate/chaos_sweep_<V>V.csv
(populated from each clip's lyapunov.json) and draws the standalone
λ₁(f_drive) curve for the fixed-voltage sweep:

  λ₁ > 0   sensitive dependence — chaotic
  λ₁ ≲ 0   periodic / quasi-periodic locking

Output:
  figures/aggregate/lambda_sweep_<V>V.png

Usage:
  python scripts/analysis/lambda_sweep.py
  python scripts/analysis/lambda_sweep.py --voltage 4.0
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

from rich.console import Console

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from figures_paths import aggregate_path  # noqa: E402

console = Console()


def load_sweep_csv(path):
    """Return (f_drive, lambda1) arrays from a chaos_sweep CSV."""
    fs, lams = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                f_hz = float(r["f_drive_hz"])
            except (ValueError, KeyError):
                continue
            raw = r.get("lambda1", "")
            try:
                lam = float(raw) if raw not in ("", None) else np.nan
            except ValueError:
                lam = np.nan
            fs.append(f_hz)
            lams.append(lam)
    return np.array(fs, dtype=float), np.array(lams, dtype=float)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2,
                   help="fixed drive voltage of the sweep (default 3.2 V).")
    args = p.parse_args()

    csv_path = aggregate_path(f"chaos_sweep_{args.voltage:g}V.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"{csv_path} not found — run chaos_sweep.py first.")

    f, lam = load_sweep_csv(csv_path)
    order = np.argsort(f)
    f, lam = f[order], lam[order]
    finite = np.isfinite(lam)
    if not finite.any():
        raise SystemExit(
            "no λ₁ values in CSV — run lyapunov.py per clip, then chaos_sweep.py.")

    ff, ll = f[finite], lam[finite]
    cols = ["tab:red" if v > 0 else "tab:green" for v in ll]
    n_chaotic = int(np.sum(ll > 0))

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(ff, ll, "-", color="0.6", lw=1.0, zorder=1)
    ax.scatter(ff, ll, c=cols, s=42, zorder=3, edgecolors="k", linewidths=0.4)
    ax.axhline(0.0, color="k", lw=0.9, ls="--", label="λ₁ = 0  (chaos threshold)")
    ax.set_xlabel("drive frequency  f_drive  (Hz)")
    ax.set_ylabel(r"$\lambda_1$  (1/s)")
    ax.set_title(
        f"Largest Lyapunov exponent vs drive frequency — {args.voltage:g} V   "
        f"({finite.sum()} clips, {n_chaotic} with λ₁ > 0)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    out = aggregate_path(f"lambda_sweep_{args.voltage:g}V.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    console.print(f"  [green]{finite.sum()}[/] clips "
                  f"[dim]({n_chaotic} chaotic)[/] → [dim]{out}[/]")


if __name__ == "__main__":
    main()
