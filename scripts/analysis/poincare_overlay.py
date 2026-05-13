"""
poincare_overlay.py
--------------------
Aggregate visual: overlay every clip's Poincaré section on a single
(theta1, omega1) plane, coloured by initial amplitude. Reveals the
periodic-to-chaotic structural transition geometrically — low-
amplitude clips draw small orbits as compact loops, high-amplitude
chaotic clips fill out a broad area of phase space.

Reads measurements/<stem>/poincare.csv produced by poincare.py.
Falls back to invoking poincare.py for any clip missing the CSV.

Output:
    figures/aggregate/poincare_overlay.png      (single combined panel)
    figures/aggregate/poincare_grid.png         (one small panel per clip)

Usage:
    python scripts/analysis/poincare_overlay.py
    python scripts/analysis/poincare_overlay.py --filter th1_p1
    python scripts/analysis/poincare_overlay.py --pass-only
"""

import argparse
import csv
import json
import os
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
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

POINCARE_SCRIPT  = os.path.join(REPO_ROOT, "scripts", "analysis", "poincare.py")

EXPERIMENTS_FILE = EXPERIMENTS
from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

def parse_args():
    p = argparse.ArgumentParser(
        description="Multi-clip Poincaré-section overlay.")
    p.add_argument("--filter", help="only stems containing SUBSTR")
    p.add_argument("--pass-only", action="store_true",
                   help="only PASS clips (audit_new_status==PASS or manual_accept)")
    return p.parse_args()

def load_registry():
    with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)

def get_passing(reg):
    out = set()
    for e in reg.values():
        if e.get("audit_new_status") == "PASS" or e.get("manual_accept"):
            cd = e.get("config_description")
            if cd:
                out.add(cd)
    return out

def status_for(reg, stem):
    e = next((v for v in reg.values()
              if v.get("config_description") == stem), None)
    if e is None:
        return "?"
    if e.get("audit_new_status") == "PASS" or e.get("manual_accept"):
        return "PASS"
    if e.get("audit_new_status") == "FAIL":
        return "FAIL"
    return "WARN"

def theta1_release(reg, stem):
    e = next((v for v in reg.values()
              if v.get("config_description") == stem), None)
    return abs(e.get("theta1_release", 0)) if e else 0.0

def ensure_poincare_csv(stem):
    csv_path = os.path.join(MEAS_DIR, stem, "poincare.csv")
    if os.path.exists(csv_path):
        return csv_path
    print(f"  generating poincare.csv for {stem} ...")
    subprocess.run([sys.executable, POINCARE_SCRIPT, "--stem", stem,
                    "--no-plot"],
                   cwd=REPO_ROOT, check=False, capture_output=True)
    return csv_path if os.path.exists(csv_path) else None

def load_poincare(csv_path):
    t, th1, om1 = [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t.append(float(r["t_s"]))
                th1.append(float(r["theta1_deg"]))
                om1.append(float(r["omega1_deg_s"]))
            except (KeyError, ValueError):
                continue
    return np.array(t), np.array(th1), np.array(om1)

def collect_data(args):
    reg = load_registry()
    passing = get_passing(reg) if args.pass_only else None

    rows = []
    for stem in sorted(set(e.get("config_description") for e in reg.values()
                           if e.get("config_description"))):
        if args.filter and args.filter not in stem:
            continue
        if passing is not None and stem not in passing:
            continue
        csv_path = ensure_poincare_csv(stem)
        if csv_path is None:
            continue
        t, th1, om1 = load_poincare(csv_path)
        if len(th1) < 2:
            continue
        rows.append({
            "stem": stem,
            "amplitude": theta1_release(reg, stem),
            "status": status_for(reg, stem),
            "t": t, "th1": th1, "om1": om1,
            "n": len(th1),
        })
    return rows

def make_overlay(rows, out_path):
    """One combined panel: every clip's section, coloured by amplitude."""
    fig, ax = plt.subplots(figsize=(11, 8))

    amps = np.array([r["amplitude"] for r in rows])
    norm = Normalize(vmin=amps.min(), vmax=amps.max())
    cmap = plt.cm.plasma

    # Plot lower-amplitude (more periodic) clips on top so the
    # high-amplitude chaotic seas form the background.
    for r in sorted(rows, key=lambda x: -x["amplitude"]):
        c = cmap(norm(r["amplitude"]))
        ax.scatter(r["th1"], r["om1"], color=c, s=18, alpha=0.7,
                   edgecolor="black", linewidth=0.2)

    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.axvline(0, color="gray", lw=0.5, ls="--")
    ax.set_xlabel("θ₁ at section (deg)")
    ax.set_ylabel("ω₁ at section (deg/s)")
    ax.set_title(f"Poincaré section overlay — section: θ₁+θ₂ = 0 upward "
                 f"  ({len(rows)} clips)")
    ax.grid(True, alpha=0.3)

    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02)
    cbar.set_label("|θ₁ release|  (deg)", fontsize=11)

    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    mirror_to_ready(out_path)
    plt.close(fig)
    print(f"  wrote {out_path}")

def make_grid(rows, out_path):
    """One small panel per clip, sorted by amplitude. Compact 'family'
    view of the periodic→chaotic transition."""
    rows = sorted(rows, key=lambda r: r["amplitude"])
    n = len(rows)
    cols = 5
    rows_n = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols,
                             figsize=(3.2 * cols, 2.6 * rows_n),
                             squeeze=False)
    amps = np.array([r["amplitude"] for r in rows])
    norm = Normalize(vmin=amps.min(), vmax=amps.max())
    cmap = plt.cm.plasma

    for i, r in enumerate(rows):
        ax = axes[i // cols][i % cols]
        c = cmap(norm(r["amplitude"]))
        ax.scatter(r["th1"], r["om1"], color=c, s=10, alpha=0.85)
        ax.set_title(f"{r['stem'].replace('th1_', '')}\n"
                     f"|θ₁|={r['amplitude']:.0f}°  n={r['n']}",
                     fontsize=8)
        ax.axhline(0, color="gray", lw=0.4, ls="--")
        ax.axvline(0, color="gray", lw=0.4, ls="--")
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.25)

    # Hide unused panels.
    for j in range(n, rows_n * cols):
        axes[j // cols][j % cols].axis("off")

    fig.suptitle("Poincaré section progression  "
                 "(panels sorted by initial |θ₁| — periodic ↘ chaotic)",
                 fontsize=13, y=0.995)
    plt.tight_layout(rect=[0, 0, 1, 0.985])
    plt.savefig(out_path, dpi=140)
    mirror_to_ready(out_path)
    plt.close(fig)
    print(f"  wrote {out_path}")

def main():
    args = parse_args()
    print("poincare_overlay.py")
    rows = collect_data(args)
    print(f"  collected {len(rows)} clip section(s)")
    if not rows:
        print("  nothing to plot.")
        return
    make_overlay(rows, aggregate_path("poincare_overlay.png"))
    make_grid(rows,    aggregate_path("poincare_grid.png"))

if __name__ == "__main__":
    main()
