"""
lyapunov_focused.py
--------------------
Two-panel focused Lyapunov-exponent figure.

Left panel : Rosenstein log<d(k)> divergence curves overlaid for the
             4-amplitude ladder (regular / transitional / strongly
             chaotic / fully chaotic). Each curve is colored by
             amplitude; the linear-fit window is overlaid.

Right panel: λ₁ vs |θ₁(0)| scatter for every clip in
             data/lyapunov_summary.csv with R² ≥ 0.7. The 4 ladder
             clips are highlighted with larger markers + amplitude
             labels. Color = R² (so the cleanest fits are visually
             emphasized).

Filters out low-R² clips so the figure only shows publication-quality
fits. No tracker-quality labels appear on the figure.
"""

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

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
from lyapunov import (  # noqa: E402
    load_series, autocorr_first_drop, estimate_period_frames,
    embed, rosenstein, auto_fit_range, linear_fit_slope,
)

PANELS = [
    {"stem": "th1_p044_th2_m001", "label": "Regular"},
    {"stem": "th1_p082_th2_p001", "label": "Transitional"},
    {"stem": "th1_p138_th2_m002", "label": "Strongly chaotic"},
    {"stem": "th1_p180_th2_m179", "label": "Fully chaotic"},
]

K_MAX  = 120
EMB_M  = 5
R2_MIN = 0.70   # filter for the right-panel scatter

def compute_curve(stem):
    """Returns dict with t_k, S, fit_lo, fit_hi, slope, intercept, r2, dt."""
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv):
        return None
    t, x = load_series(csv, use_omega=False)
    dt = float(np.mean(np.diff(t)))
    tau = max(3, min(autocorr_first_drop(x), 30))
    period = estimate_period_frames(t, x)
    theiler = max(min(period, 200), 30)
    emb = embed(x, m=EMB_M, tau=tau)
    S = rosenstein(emb, theiler=theiler, k_max=K_MAX)
    lo, hi = auto_fit_range(S, K_MAX)
    k = np.arange(len(S))
    t_k = k * dt
    slope, intercept, r2 = linear_fit_slope(t_k, S, lo, hi)
    return {
        "t_k": t_k, "S": S, "fit_lo": lo, "fit_hi": hi,
        "slope": slope, "intercept": intercept, "r2": r2, "dt": dt,
    }

def main():
    # ── Right panel: full scatter ──
    df = pd.read_csv(LYAP_CSV).dropna(subset=["lambda1", "r2", "amplitude"])
    df_clean = df[df["r2"] >= R2_MIN].copy()
    print(f"  scatter: {len(df_clean)}/{len(df)} clips above R² ≥ {R2_MIN}")

    # ── Left panel: 4 Rosenstein curves ──
    lyap = {row["stem"]: row for _, row in df.iterrows()}
    curves = []
    for p in PANELS:
        print(f"  computing rosenstein on {p['stem']}…", flush=True)
        c = compute_curve(p["stem"])
        if c is None:
            print(f"    SKIP (no verification.csv)")
            continue
        amp = float(lyap.get(p["stem"], {}).get("amplitude", float("nan")))
        curves.append({**p, "amp": amp, **c})

    # Color scale: amplitude across the 4 ladder clips
    amps_ladder = [c["amp"] for c in curves]
    cnorm_l = mcolors.Normalize(vmin=min(amps_ladder), vmax=max(amps_ladder))
    cmap_l  = cm.viridis

    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(13, 6))

    for c in curves:
        col = cmap_l(cnorm_l(c["amp"]))
        ax_l.plot(c["t_k"], c["S"], color=col, lw=1.5, alpha=0.55)
        if np.isfinite(c["slope"]):
            tk = c["t_k"][c["fit_lo"]:c["fit_hi"] + 1]
            ax_l.plot(tk, c["intercept"] + c["slope"] * tk,
                      color=col, lw=2.5,
                      label=rf"$\theta_1(0)$={c['amp']:.0f}°  "
                            rf"$\lambda_1$={c['slope']:+.2f}/s")
    ax_l.set_xlabel(r"horizon $k\cdot dt$ (s)")
    ax_l.set_ylabel(r"$\langle \ln d(k) \rangle$")
    ax_l.set_title("Rosenstein divergence curves", fontsize=11)
    ax_l.grid(alpha=0.3)
    ax_l.legend(loc="lower right", fontsize=9)

    # Right scatter — viridis throughout for colormap consistency
    sc = ax_r.scatter(df_clean["amplitude"], df_clean["lambda1"],
                       c=df_clean["r2"], cmap="viridis", vmin=0.7, vmax=1.0,
                       s=55, edgecolor="black", linewidth=0.4)
    cb = plt.colorbar(sc, ax=ax_r, label=r"fit $R^2$", shrink=0.85)

    # Highlight ladder clips
    for c in curves:
        ax_r.scatter([c["amp"]], [c["slope"]], s=180,
                     facecolor="none", edgecolor="crimson", linewidth=1.6,
                     zorder=10)
        ax_r.annotate(c["label"], (c["amp"], c["slope"]),
                      textcoords="offset points", xytext=(8, 8),
                      fontsize=9, color="crimson")

    ax_r.axhline(0, color="gray", lw=0.5, linestyle="--", alpha=0.6)
    ax_r.set_xlabel(r"$|\theta_1(0)|$  (deg)")
    ax_r.set_ylabel(r"$\lambda_1$ (Rosenstein)  (1/s)")
    ax_r.set_title(rf"$\lambda_1$ vs amplitude  ($N$={len(df_clean)},  "
                    rf"$R^2 \geq {R2_MIN:.1f}$)", fontsize=11)
    ax_r.grid(alpha=0.3)

    fig.tight_layout()

    out = aggregate_path("lyapunov_focused.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    mirror_to_ready(out)
    print(f"  wrote {out}")

if __name__ == "__main__":
    main()
