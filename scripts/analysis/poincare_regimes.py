"""
poincare_regimes.py
--------------------
Focused 4-panel Poincaré-section ladder showing the periodic→chaotic
transition across factor-of-2 amplitude steps.

Same (θ₁, ω₁) axes across all panels so the eye can directly compare
how the section structure expands into phase space as amplitude grows.
Crossings are colored by time index. Per-panel annotation: regime
label + amplitude + crossing count + Lyapunov λ₁ with R².

Section condition: θ₁+θ₂=0, upward (d(θ₁+θ₂)/dt > 0).

No tracker-quality labels (WARN/PASS/FAIL) appear on the figure —
only physics-meaningful metrics.
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

# Factor-of-2 amplitude ladder. All clips have clean Lyapunov fits
# (R² > 0.6) and no tracker FAIL flags.
PANELS = [
    {"stem": "th1_p044_th2_m001", "label": "Regular"},
    {"stem": "th1_p082_th2_p001", "label": "Transitional"},
    {"stem": "th1_p138_th2_m002", "label": "Strongly chaotic"},
    {"stem": "th1_p180_th2_m179", "label": "Fully chaotic"},
]

def load_lyap_index():
    """Returns dict stem -> {lambda1, r2, amplitude}."""
    if not os.path.exists(LYAP_CSV):
        return {}
    df = pd.read_csv(LYAP_CSV)
    out = {}
    for _, row in df.iterrows():
        out[row["stem"]] = {
            "lambda1":   float(row.get("lambda1", float("nan"))),
            "r2":        float(row.get("r2", float("nan"))),
            "amplitude": float(row.get("amplitude", float("nan"))),
        }
    return out

def load_poincare(stem):
    p = os.path.join(MEAS_DIR, stem, "poincare.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    return df if len(df) else None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true",
                          help="plt.show() instead of save")
    args = parser.parse_args()

    lyap = load_lyap_index()
    panel_data = []
    for p in PANELS:
        df = load_poincare(p["stem"])
        if df is None:
            print(f"WARNING: no poincare.csv for {p['stem']}")
            continue
        panel_data.append({**p, "df": df, **lyap.get(p["stem"], {})})

    if not panel_data:
        print("ERROR: no panel data found")
        sys.exit(1)

    # Shared axis ranges from the union of all crossings
    all_th = np.concatenate([d["df"]["theta1_deg"].to_numpy() for d in panel_data])
    all_om = np.concatenate([d["df"]["omega1_deg_s"].to_numpy() for d in panel_data])
    th_pad = 0.08 * (all_th.max() - all_th.min())
    om_pad = 0.08 * (all_om.max() - all_om.min())
    xlim = (all_th.min() - th_pad, all_th.max() + th_pad)
    ylim = (all_om.min() - om_pad, all_om.max() + om_pad)

    fig, axes = plt.subplots(2, 2, figsize=(11, 10),
                                 sharex=True, sharey=True)
    axes_flat = axes.ravel()

    for ax, d in zip(axes_flat, panel_data):
        df = d["df"]
        t  = df["t_s"].to_numpy()
        norm   = mcolors.Normalize(vmin=t.min(), vmax=t.max())
        colors = cm.viridis(norm(t))
        ax.scatter(df["theta1_deg"], df["omega1_deg_s"],
                   c=colors, s=22, edgecolor="black", linewidth=0.3,
                   alpha=0.85)
        ax.axhline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.axvline(0, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
        ax.grid(alpha=0.2)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_xlabel(r"$\theta_1$ at section (deg)")

        amp = d.get("amplitude", float("nan"))
        lam = d.get("lambda1",   float("nan"))
        n   = len(df)
        # Compact one-line title: regime · amplitude · N crossings
        ax.set_title(rf"{d['label']}  ·  $\theta_1(0)={amp:.0f}^\circ$  ·  $N$={n}",
                     fontsize=11)
        # λ annotation in upper-right corner
        if not np.isnan(lam):
            ax.text(0.97, 0.97, rf"$\lambda_1={lam:+.2f}$/s",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=10, family="monospace",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="white", alpha=0.8,
                              edgecolor="lightgray"))

    # Y-axis label only on the left column
    axes[0, 0].set_ylabel(r"$\omega_1$ at section (deg/s)")
    axes[1, 0].set_ylabel(r"$\omega_1$ at section (deg/s)")

    fig.tight_layout()

    if args.show:
        plt.show()
    else:
        out = aggregate_path("poincare_regimes.png")
        plt.savefig(out, dpi=150, bbox_inches="tight")
        mirror_to_ready(out)
        print(f"  wrote {out}")

if __name__ == "__main__":
    main()
