"""
lyapunov_compare.py
--------------------
Aggregate visual: λ₁ vs initial amplitude across every clip with a
verification.csv. Re-runs lyapunov.py headlessly per clip, parses the
slope + R² + sample count, and produces:

    figures/aggregate/lyapunov_vs_amplitude.png   (the headline plot)
    data/lyapunov_summary.csv                     (per-clip table)

Usage:
    python scripts/analysis/lyapunov_compare.py
    python scripts/analysis/lyapunov_compare.py --filter th1_p1
    python scripts/analysis/lyapunov_compare.py --pass-only

Caveat: this re-runs lyapunov.py for every clip on every invocation.
Each call is ~1–10 s except for the long_recording (~30 s with default
k_max). For a full 28-clip pass expect ~3–5 min wall-clock.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT             = os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__))))
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")
LYAP_SCRIPT      = os.path.join(ROOT, "scripts", "analysis", "lyapunov.py")
DATA_DIR         = os.path.join(ROOT, "data")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import aggregate_path  # noqa: E402


# Per-stem k_max overrides for clips where the auto-fit picks a poor
# range. These stem from previous runs where we eyeballed the divergence
# curve and saw saturation kick in early — capping k_max forces the fit
# to stay in the linear regime.
KMAX_OVERRIDES = {
    "th1_p180_th2_m179":   60,   # full inversion, fast saturation
    "th1_m179_th2_p089":   60,
    "th1_p067_th2_p096":   60,
    "th1_p094_th2_p000_r2": 60,
    "th1_p138_th2_m002":   60,
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--filter", help="only stems containing SUBSTR")
    p.add_argument("--pass-only", action="store_true")
    p.add_argument("--no-rerun", action="store_true",
                   help="don't re-run lyapunov.py; trust last summary")
    return p.parse_args()


def load_registry():
    with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def is_passing(e):
    return e.get("audit_new_status") == "PASS" or bool(e.get("manual_accept"))


def status_for(e):
    if is_passing(e):
        return "PASS"
    if e.get("audit_new_status") == "FAIL":
        return "FAIL"
    return "WARN"


_LAM_RE = re.compile(
    r"lambda_1\s*=\s*([+\-0-9.]+)\s*/s\s+R\^2\s*=\s*([0-9.]+)")


def run_lyap(stem):
    cmd = [sys.executable, LYAP_SCRIPT, "--stem", stem, "--no-plot"]
    if stem in KMAX_OVERRIDES:
        cmd += ["--k-max", str(KMAX_OVERRIDES[stem])]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    text = out.stdout + out.stderr
    m = _LAM_RE.search(text)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def collect(args):
    reg = load_registry()
    rows = []
    for e in reg.values():
        stem = e.get("config_description")
        if not stem:
            continue
        if args.filter and args.filter not in stem:
            continue
        if args.pass_only and not is_passing(e):
            continue

        meas_csv = os.path.join(ROOT, "measurements", stem,
                                "verification.csv")
        if not os.path.exists(meas_csv):
            continue

        amp = abs(e.get("theta1_release", 0))
        amp2 = abs(e.get("theta2_release", 0))
        status = status_for(e)
        if args.no_rerun:
            lam = r2 = float("nan")
        else:
            print(f"  {stem} ...", flush=True)
            lam, r2 = run_lyap(stem)
            if lam is None:
                lam, r2 = float("nan"), float("nan")
        rows.append({
            "stem": stem, "amplitude": amp, "amp_th2": amp2,
            "status": status, "lambda1": lam, "r2": r2,
        })
    return rows


def make_plot(rows, out_path):
    fig, ax = plt.subplots(figsize=(11, 7))

    COLORS = {"PASS": "tab:green", "WARN": "tab:orange", "FAIL": "tab:red"}
    MARKERS = {"PASS": "o", "WARN": "s", "FAIL": "^"}

    valid = [r for r in rows
             if np.isfinite(r["lambda1"]) and r["amplitude"] > 0]

    for stat in ("PASS", "WARN", "FAIL"):
        sub = [r for r in valid if r["status"] == stat]
        if not sub:
            continue
        xs = [r["amplitude"] for r in sub]
        ys = [r["lambda1"] for r in sub]
        # Marker size scales with R² confidence.
        ss = [40 + 90 * max(0, r["r2"]) for r in sub]
        ax.scatter(xs, ys, s=ss,
                   color=COLORS[stat], marker=MARKERS[stat],
                   label=f"{stat} (n={len(sub)})",
                   edgecolor="black", linewidths=0.5,
                   alpha=0.85, zorder=3)

    # Annotate every point with its stem.
    for r in valid:
        ax.annotate(r["stem"].replace("th1_", ""),
                    (r["amplitude"], r["lambda1"]),
                    xytext=(6, 4), textcoords="offset points",
                    fontsize=7, alpha=0.7)

    # Log-amplitude fit on the full set (keeps rough trend visible).
    xs_all = np.array([r["amplitude"] for r in valid])
    ys_all = np.array([r["lambda1"] for r in valid])
    if len(xs_all) >= 4 and (xs_all > 0).all():
        coef = np.polyfit(np.log(xs_all), ys_all, 1)
        x_line = np.linspace(xs_all.min(), xs_all.max(), 200)
        y_line = coef[0] * np.log(x_line) + coef[1]
        ax.plot(x_line, y_line, color="gray", lw=1.2, ls="--",
                alpha=0.6,
                label=f"log fit:  λ₁ ≈ {coef[0]:.2f}·ln(|θ₁|) + "
                      f"{coef[1]:+.2f}")

    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("|θ₁ release|  (deg)")
    ax.set_ylabel("largest Lyapunov exponent  λ₁  (1/s)")
    ax.set_title(
        f"λ₁ vs initial amplitude — {len(valid)} clips  "
        f"(marker size ∝ R² of slope fit)",
        fontsize=12)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    plt.close(fig)
    print(f"\n  wrote {out_path}")


def write_summary_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "stem", "amplitude", "amp_th2", "status", "lambda1", "r2"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["amplitude"]):
            w.writerow(r)
    print(f"  wrote {out_path}")


def main():
    args = parse_args()
    print("lyapunov_compare.py")
    rows = collect(args)
    if not rows:
        print("  no clips matched.")
        return
    valid = [r for r in rows if np.isfinite(r["lambda1"])]
    print(f"  {len(valid)}/{len(rows)} clips with valid λ₁ "
          f"(amplitude {min(r['amplitude'] for r in valid):.1f}° → "
          f"{max(r['amplitude'] for r in valid):.1f}°)")

    out_csv = os.path.join(DATA_DIR, "lyapunov_summary.csv")
    write_summary_csv(rows, out_csv)
    make_plot(rows, aggregate_path("lyapunov_vs_amplitude.png"))


if __name__ == "__main__":
    main()
