"""
phase_portrait_regimes.py
--------------------------
Focused 4-panel (θ_arm, ω_arm) phase-portrait ladder showing the
periodic→chaotic transition across factor-of-2 amplitude steps.

Use --arm 1 (default) or --arm 2 to choose which arm's portrait.
Output filename: phase_portrait_arm{1,2}.png.

Same panel selection and visual language as poincare_regimes.py:
shared axes across panels, trajectories colored by time index, no
tracker-quality labels on the figure. For arm 2 in chaotic regimes,
θ₂ is wrapped to ±180° per panel to keep the structure readable.

Trajectory data comes from verification.csv (Savitzky-Golay-smoothed ω).
Only the free_swing phase is plotted.
"""

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import cm
import matplotlib.colors as mcolors

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

LYAP_CSV = os.path.join(REPO_ROOT, "data", "lyapunov_summary.csv")

from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

PANELS = [
    {"stem": "th1_p044_th2_m001", "label": "Regular"},
    {"stem": "th1_p082_th2_p001", "label": "Transitional"},
    {"stem": "th1_p138_th2_m002", "label": "Strongly chaotic"},
    {"stem": "th1_p180_th2_m179", "label": "Fully chaotic"},
]

def load_lyap_index():
    if not os.path.exists(LYAP_CSV):
        return {}
    df = pd.read_csv(LYAP_CSV)
    return {
        row["stem"]: {
            "lambda1":   float(row.get("lambda1", float("nan"))),
            "r2":        float(row.get("r2", float("nan"))),
            "amplitude": float(row.get("amplitude", float("nan"))),
        }
        for _, row in df.iterrows()
    }

def load_traj(stem, arm):
    """Returns DataFrame of free_swing rows with (time_s, theta, omega) columns."""
    p = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    th_col, om_col = f"theta{arm}_deg", f"omega{arm}_deg_s"
    free = df[df["phase"].isin(["free_swing", "driven"])].dropna(
        subset=[th_col, om_col]).reset_index(drop=True)
    if len(free) < 30:
        return None
    out = pd.DataFrame({
        "time_s": free["time_s"].to_numpy(),
        "theta":  free[th_col].to_numpy(),
        "omega":  free[om_col].to_numpy(),
    })
    # Wrap θ₂ to ±180° (it can rotate without bound in chaotic regimes;
    # keeping it wrapped makes the per-panel phase-portrait readable).
    if arm == 2:
        out["theta"] = ((out["theta"] + 180) % 360) - 180
    return out

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", type=int, choices=[1, 2], default=1,
                          help="Which arm's phase portrait to plot.")
    parser.add_argument("--show", action="store_true",
                          help="plt.show() instead of save")
    parser.add_argument("--max-time", type=float, default=None,
                          help="Truncate trajectories to first MAX_TIME seconds.")
    args = parser.parse_args()

    arm = args.arm
    lyap = load_lyap_index()
    panel_data = []
    for p in PANELS:
        df = load_traj(p["stem"], arm)
        if df is None:
            print(f"WARNING: no usable verification.csv for {p['stem']}")
            continue
        if args.max_time is not None:
            t0 = df["time_s"].iloc[0]
            df = df[df["time_s"] - t0 <= args.max_time].reset_index(drop=True)
        panel_data.append({**p, "df": df, **lyap.get(p["stem"], {})})

    if not panel_data:
        print("ERROR: no panel data found")
        sys.exit(1)

    # Shared axis ranges over all panels
    all_th = np.concatenate([d["df"]["theta"].to_numpy() for d in panel_data])
    all_om = np.concatenate([d["df"]["omega"].to_numpy() for d in panel_data])
    th_pad = 0.05 * (all_th.max() - all_th.min())
    om_pad = 0.05 * (all_om.max() - all_om.min())
    xlim = (all_th.min() - th_pad, all_th.max() + th_pad)
    ylim = (all_om.min() - om_pad, all_om.max() + om_pad)

    fig, axes = plt.subplots(2, 2, figsize=(11, 10),
                                 sharex=True, sharey=True)
    axes_flat = axes.ravel()

    for ax, d in zip(axes_flat, panel_data):
        df = d["df"]
        t   = df["time_s"].to_numpy()
        th  = df["theta"].to_numpy()
        om  = df["omega"].to_numpy()
        if len(t) > 5000:
            stride = len(t) // 5000
            t, th, om = t[::stride], th[::stride], om[::stride]
        norm   = mcolors.Normalize(vmin=t[0], vmax=t[-1])
        colors = cm.viridis(norm(t))
        ax.scatter(th, om, c=colors, s=2, alpha=0.55, edgecolor="none")
        ax.axhline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.axvline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.grid(alpha=0.2)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_xlabel(rf"$\theta_{arm}$ (deg)")

        amp = d.get("amplitude", float("nan"))
        lam = d.get("lambda1",   float("nan"))
        # Compact one-line title: regime · amplitude
        ax.set_title(rf"{d['label']}  ·  $\theta_1(0)={amp:.0f}^\circ$",
                     fontsize=11)
        # λ annotation in upper-right corner
        if not np.isnan(lam):
            ax.text(0.97, 0.97, rf"$\lambda_1={lam:+.2f}$/s",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=10, family="monospace",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="white", alpha=0.8,
                              edgecolor="lightgray"))

    axes[0, 0].set_ylabel(rf"$\omega_{arm}$ (deg/s)")
    axes[1, 0].set_ylabel(rf"$\omega_{arm}$ (deg/s)")

    fig.tight_layout()

    if args.show:
        plt.show()
    else:
        out = aggregate_path(f"phase_portrait_arm{arm}.png")
        plt.savefig(out, dpi=150, bbox_inches="tight")
        mirror_to_ready(out)
        print(f"  wrote {out}")

if __name__ == "__main__":
    main()
