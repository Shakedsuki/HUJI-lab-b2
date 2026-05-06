"""
friction_compare.py
-------------------
Run friction_fit on every clip with verification.csv, tabulate
results, and plot τ (energy decay time constant) vs initial
amplitude. Tells you whether damping scales with amplitude
(signature of nonlinear / Newton drag) or stays roughly constant
(linear / Stokes drag).

Outputs:
  data/friction_comparison.csv     — one row per clip
  data/friction_comparison.png     — τ vs initial amplitude scatter
  console                          — summary table

Usage:
    chaos friction-compare
    chaos friction-compare --filter <substr>   only clips matching
    chaos friction-compare --pass-only         only PASS clips
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
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit


ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
MEAS_DIR = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from track_one import read_verification_metrics, compute_verdict  # noqa: E402
from figures_paths import aggregate_path, mirror_to_journal  # noqa: E402


def E_per_frame(th1_deg, th2_deg, om1_dps, om2_dps, L=0.35, g=9.8):
    th1_r = np.radians(th1_deg)
    th2_abs_r = np.radians(th1_deg + th2_deg)
    th2_rel_r = np.radians(th2_deg)
    w1_r = np.radians(om1_dps)
    w2_abs_r = np.radians(om1_dps + om2_dps)
    PE = (g * (3.0 * L / 2.0) * (1.0 - np.cos(th1_r))
        + g * (L / 2.0)       * (1.0 - np.cos(th2_abs_r)))
    KE = L**2 * (
          (2.0 / 3.0) * w1_r ** 2
        + 0.5         * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1.0 / 6.0) * w2_abs_r ** 2)
    return KE + PE


def smooth_envelope(t, e, window_s=2.0):
    if len(t) < 3:
        return e
    dt = float(np.median(np.diff(t)))
    win = max(3, int(round(window_s / dt)) | 1)
    if win >= len(e):
        return np.full_like(e, e.mean())
    out = np.copy(e)
    half = win // 2
    cs = np.concatenate([[0.0], np.cumsum(e)])
    for i in range(len(e)):
        a = max(0, i - half)
        b = min(len(e), i + half + 1)
        out[i] = (cs[b] - cs[a]) / (b - a)
    return out


def fit_one(stem, smooth_window=2.0):
    """Return dict of fit results for this clip, or None on failure."""
    csv_path = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    free = df[df["phase"] == "free_swing"].copy().reset_index(drop=True)
    if len(free) < 30:
        return None
    om1 = pd.to_numeric(free["omega1_deg_s"], errors="coerce")
    om2 = pd.to_numeric(free["omega2_deg_s"], errors="coerce")
    valid = (~om1.isna() & ~om2.isna()
             & ~free["theta1_deg"].isna() & ~free["theta2_deg"].isna())
    if valid.sum() < 30:
        return None
    t = free.loc[valid, "time_s"].values - free.loc[valid, "time_s"].iloc[0]
    e = E_per_frame(free.loc[valid, "theta1_deg"].values,
                    free.loc[valid, "theta2_deg"].values,
                    om1[valid].values, om2[valid].values)
    e_smooth = smooth_envelope(t, e, window_s=smooth_window)

    # Initial amplitude: max |θ_abs| during the first half-second of swing.
    # More robust than just θ at t=0 (where ω can be noisy).
    early = free.loc[valid].iloc[:max(30, int(0.5 / np.median(np.diff(t))))]
    init_amp_th1 = float(early["theta1_deg"].abs().max())
    init_amp_th2 = float((early["theta1_deg"] + early["theta2_deg"]).abs().max())

    # Exponential fit
    def expo(t, E0, tau):
        return E0 * np.exp(-t / tau)
    try:
        p, _ = curve_fit(expo, t, e_smooth,
                         p0=(e_smooth[0], (t[-1] - t[0]) * 5),
                         bounds=([0, 1e-3], [np.inf, np.inf]))
        E_fit = expo(t, *p)
        ss_res = float(np.sum((e_smooth - E_fit) ** 2))
        ss_tot = float(np.sum((e_smooth - e_smooth.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        E0, tau = float(p[0]), float(p[1])
    except Exception:
        E0, tau, r2 = float("nan"), float("nan"), float("nan")

    return {
        "stem":              stem,
        "duration_s":        float(t[-1]),
        "n_free":            int(valid.sum()),
        "init_amp_th1_deg":  init_amp_th1,
        "init_amp_th2_deg":  init_amp_th2,
        "E_release":         float(e_smooth[0]),
        "E_end":             float(e_smooth[-1]),
        "drift_pct":         float(100 * (e_smooth[-1] - e_smooth[0]) / e_smooth[0]),
        "tau_s":             tau,
        "half_life_s":       tau * 0.6931 if not np.isnan(tau) else float("nan"),
        "fit_r2":            r2,
        "E0_fit":            E0,
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="Run friction_fit on every clip and compare τ "
                    "vs initial amplitude.")
    p.add_argument("--filter", metavar="SUBSTR",
                   help="only clips whose stem matches")
    p.add_argument("--pass-only", action="store_true",
                   help="only include clips currently PASS under live verdict")
    p.add_argument("--smooth-window", type=float, default=2.0,
                   metavar="SECONDS")
    return p.parse_args()


def main():
    args = parse_args()
    reg = json.load(open(EXPERIMENTS_FILE, "r", encoding="utf-8"))

    rows = []
    for k, e in reg.items():
        stem = e.get("config_description") or k
        if args.filter and args.filter not in stem:
            continue
        md = os.path.join(MEAS_DIR, stem)
        if not os.path.exists(os.path.join(md, "tracking.csv")):
            continue
        if args.pass_only:
            metrics = read_verification_metrics(md)
            if not metrics:
                continue
            status, _ = compute_verdict(
                metrics, metrics.get("n_suspect_hidden", 0))
            if status != "PASS":
                continue
        result = fit_one(stem, smooth_window=args.smooth_window)
        if result is None:
            continue
        # tag with current live status
        metrics = read_verification_metrics(md)
        if metrics:
            status, _ = compute_verdict(
                metrics, metrics.get("n_suspect_hidden", 0))
        else:
            status = "?"
        result["status"] = status
        rows.append(result)

    if not rows:
        print("No clips matched.")
        return 0

    rows.sort(key=lambda r: r["init_amp_th1_deg"])

    # ── Console table ────────────────────────────────────────────────
    print()
    print("=" * 90)
    print(f"  Friction comparison ({len(rows)} clips)")
    print("=" * 90)
    print(f"  {'STEM':30s}  {'STATUS':6s}  "
          f"{'AMP θ₁':>7s}  {'AMP θ₂_abs':>10s}  "
          f"{'τ (s)':>8s}  {'½-life':>7s}  {'R²':>5s}  {'drift':>7s}")
    print("  " + "-" * 88)
    for r in rows:
        if np.isnan(r["tau_s"]):
            print(f"  {r['stem']:30s}  {r['status']:6s}  "
                  f"{r['init_amp_th1_deg']:7.1f}  {r['init_amp_th2_deg']:10.1f}  "
                  f"{'fit failed':>30s}")
            continue
        print(f"  {r['stem']:30s}  {r['status']:6s}  "
              f"{r['init_amp_th1_deg']:7.1f}  {r['init_amp_th2_deg']:10.1f}  "
              f"{r['tau_s']:8.1f}  {r['half_life_s']:7.1f}  "
              f"{r['fit_r2']:5.2f}  {r['drift_pct']:+6.1f}%")

    # ── Plot τ vs initial amplitude ──────────────────────────────────
    out_png = aggregate_path("friction_comparison.png")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    color_for = {"PASS": "#2ca02c", "WARN": "#d4a017", "FAIL": "#d62728"}

    for ax, xkey, xlabel in (
        (axes[0], "init_amp_th1_deg", "initial |θ₁| (deg)"),
        (axes[1], "init_amp_th2_deg", "initial |θ₂_abs| (deg)"),
    ):
        for status in ("PASS", "WARN", "FAIL"):
            subset = [r for r in rows
                      if r["status"] == status and not np.isnan(r["tau_s"])]
            if subset:
                ax.scatter([r[xkey] for r in subset],
                           [r["tau_s"] for r in subset],
                           c=color_for.get(status, "gray"),
                           label=f"{status} (n={len(subset)})",
                           s=70, alpha=0.7,
                           edgecolors="black", linewidths=0.5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("decay time constant τ (s)")
        ax.set_yscale("log")
        ax.grid(alpha=0.3, which="both")
        ax.legend(loc="best")

    fig.suptitle("Energy decay τ vs initial amplitude", fontsize=14)
    plt.tight_layout()
    plt.savefig(out_png, dpi=140)
    mirror_to_journal(out_png)
    plt.close(fig)
    print(f"\n  Plot: {out_png}")

    # ── CSV ─────────────────────────────────────────────────────────
    out_csv = os.path.join(DATA_DIR, "friction_comparison.csv")
    fieldnames = ["stem", "status", "duration_s", "n_free",
                  "init_amp_th1_deg", "init_amp_th2_deg",
                  "E_release", "E_end", "drift_pct",
                  "tau_s", "half_life_s", "fit_r2", "E0_fit"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"  CSV:  {out_csv}")

    # ── Summary statistics ───────────────────────────────────────────
    valid = [r for r in rows if not np.isnan(r["tau_s"]) and r["fit_r2"] > 0.3]
    if valid:
        taus = np.array([r["tau_s"] for r in valid])
        amps = np.array([r["init_amp_th1_deg"] for r in valid])
        print()
        print(f"  Summary (R² > 0.3, n={len(valid)}):")
        print(f"    τ range:        [{taus.min():.0f}, {taus.max():.0f}] s")
        print(f"    τ median:       {np.median(taus):.0f} s")
        print(f"    half-life median: {np.median(taus)*0.693:.0f} s")
        # Power-law correlation: log τ = a + b log amp
        if len(valid) >= 4 and amps.min() > 1:
            log_amp = np.log(amps); log_tau = np.log(taus)
            slope, intercept = np.polyfit(log_amp, log_tau, 1)
            print(f"    log τ ~ {slope:+.2f} · log(amp) + const  "
                  f"(slope ≈ 0 → linear drag; slope < 0 → nonlinear)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
