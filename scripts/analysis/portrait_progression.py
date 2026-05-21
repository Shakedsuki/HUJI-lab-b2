"""
portrait_progression.py
------------------------
Aggregate visual: arm-1 phase portrait (θ₁ vs ω₁) for representative
clips spanning the amplitude range. Stacked into a small-multiples
grid sorted by |θ₁_release|. Shows the regular→chaotic structural
transition: low-amplitude clips trace closed loops (quasi-periodic
KAM tori); high-amplitude clips fill out a broad chaotic sea.

Reads measurements/<stem>/verification.csv (which already has SG-
smoothed ω columns from verify_tracking.py).

Output:
    figures/aggregate/portrait_progression.png

Usage:
    python scripts/analysis/portrait_progression.py
    python scripts/analysis/portrait_progression.py --filter th1_p1
    python scripts/analysis/portrait_progression.py --pass-only
    python scripts/analysis/portrait_progression.py --arm 2

    # Exclude unphysical tracker spikes (band-aid for high-amplitude
    # marker-occlusion artefacts; produces a publication-clean figure
    # while the underlying tracking is being repaired):
    python scripts/analysis/portrait_progression.py --omega-clip 3000

Hard-coded exclusions (see EXCLUDE_FROM_PROGRESSION below) drop clips
that aren't meaningfully phase-portrait-able (≈0° release, retake-
superseded broken tracks). Override with --include-excluded.
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
from matplotlib.colors import Normalize

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS
from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

# Hard-exclude list — clips for which a phase portrait simply isn't
# meaningful, regardless of audit verdict. Distinct from FAIL: a FAIL
# clip can still display interesting (if noisy) phase-space structure;
# these clips can't. Bypass with --include-excluded.
EXCLUDE_FROM_PROGRESSION = {
    "th1_m001_th2_p001":  "release |θ₁|≈0° — no oscillation to portray",
    "th1_p090_th2_p000":  "tracker froze (vertical strip artefact); "
                          "superseded by p090_th2_p000_r2",
    # Tracking failures producing physically impossible |ω| or empty data.
    # |ω| ~ several thousand deg/s for an arm with L≈30cm is non-physical.
    "th1_p079_th2_p000":  "tracking failure — empty / near-empty trajectory",
    "th1_p140_th2_p089":  "tracking failure — non-physical horizontal smear",
    "th1_p153_th2_p090":  "tracking failure — |ω| reaches 10⁴ deg/s",
    "th1_p176_th2_p180":  "tracking failure — |ω| reaches 8×10³ deg/s",
    "th1_p180_th2_p090":  "tracking failure — |ω| reaches 7.5×10³ deg/s",
}

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--filter", help="only stems containing SUBSTR")
    p.add_argument("--pass-only", action="store_true")
    p.add_argument("--arm", type=int, choices=[1, 2], default=1,
                   help="which arm's phase portrait to show (default 1)")
    p.add_argument("--min-amplitude", type=float, default=1.0,
                   metavar="DEG",
                   help="drop clips with |θ₁_release| < this (default 1°)")
    p.add_argument("--include-excluded", action="store_true",
                   help="ignore EXCLUDE_FROM_PROGRESSION (debug only)")
    p.add_argument("--omega-clip", type=float, default=None,
                   metavar="DEG_PER_S",
                   help="mask trajectory rows where |ω| exceeds this. "
                        "Band-aid for unphysical tracker spikes at "
                        "high amplitudes (suggested: 3000). "
                        "Default: no clipping.")
    return p.parse_args()

def load_registry():
    with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)

def is_passing(e):
    return e.get("audit_new_status") == "PASS" or bool(e.get("manual_accept"))

def load_traj(stem, arm):
    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(csv_path):
        return None, None, None
    th_col = f"theta{arm}_deg"
    om_col = f"omega{arm}_deg_s"
    t, th, om = [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") != "free_swing":
                continue
            try:
                vals = (float(r["time_s"]),
                        float(r[th_col]),
                        float(r[om_col]))
            except (KeyError, ValueError):
                continue
            t.append(vals[0]); th.append(vals[1]); om.append(vals[2])
    if len(t) < 50:
        return None, None, None
    return np.array(t), np.array(th), np.array(om)

def main():
    args = parse_args()
    print(f"portrait_progression.py  (arm {args.arm})")
    reg = load_registry()

    rows = []
    excluded = []  # list of (stem, reason) for the run-summary print
    for e in reg.values():
        stem = e.get("config_description")
        if not stem:
            continue
        if args.filter and args.filter not in stem:
            continue
        if args.pass_only and not is_passing(e):
            continue
        amplitude = abs(e.get("theta1_release", 0))
        if not args.include_excluded and stem in EXCLUDE_FROM_PROGRESSION:
            excluded.append((stem, EXCLUDE_FROM_PROGRESSION[stem]))
            continue
        if amplitude < args.min_amplitude:
            excluded.append(
                (stem, f"|θ₁|={amplitude:.2f}° < --min-amplitude "
                       f"{args.min_amplitude}°"))
            continue
        t, th, om = load_traj(stem, args.arm)
        if t is None:
            continue
        if args.omega_clip is not None:
            mask = np.abs(om) <= args.omega_clip
            n_dropped = int((~mask).sum())
            t, th, om = t[mask], th[mask], om[mask]
            if len(t) < 50:
                excluded.append(
                    (stem, f"<50 samples after --omega-clip "
                           f"{args.omega_clip}°/s (dropped {n_dropped})"))
                continue
        rows.append({
            "stem": stem,
            "amplitude": amplitude,
            "status": "PASS" if is_passing(e)
                       else ("FAIL" if e.get("audit_new_status") == "FAIL"
                             else "WARN"),
            "t": t, "th": th, "om": om,
        })

    if not rows:
        print("  no clips matched.")
        return

    rows = sorted(rows, key=lambda r: r["amplitude"])
    print(f"  {len(rows)} clips kept, amplitude range "
          f"{rows[0]['amplitude']:.1f}° → {rows[-1]['amplitude']:.1f}°")
    if excluded:
        print(f"  {len(excluded)} clip(s) excluded:")
        for stem, reason in excluded:
            print(f"    - {stem}: {reason}")

    n = len(rows)
    cols = 5
    rows_n = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols,
                             figsize=(3.4 * cols, 2.7 * rows_n),
                             squeeze=False)
    for i, r in enumerate(rows):
        ax = axes[i // cols][i % cols]
        # Colour by time so you see how the trajectory winds.
        ax.scatter(r["th"], r["om"],
                   c=r["t"], cmap="viridis",
                   s=1.2, alpha=0.55)
        ax.set_title(rf"$|\theta_1|={r['amplitude']:.0f}^\circ$",
                     fontsize=10, color="black")
        ax.axhline(0, color="gray", lw=0.4, ls="--")
        ax.axvline(0, color="gray", lw=0.4, ls="--")
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.25)

    for j in range(n, rows_n * cols):
        axes[j // cols][j % cols].axis("off")

    plt.tight_layout()
    out_path = aggregate_path(f"portrait_progression_arm{args.arm}.png")
    plt.savefig(out_path, dpi=140)
    mirror_to_ready(out_path)
    plt.close(fig)
    print(f"  wrote {out_path}")

if __name__ == "__main__":
    main()
