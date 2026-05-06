"""
group_overlay.py
-----------------
Aggregate visual: take a curated set of clips with similar initial
conditions and produce the canonical sensitivity-to-IC diagnostics:

    1. theta_1(t) overlay — every clip on one panel, time-aligned to
       release. Visually you see them coincide for ~ a Lyapunov time
       then exponentially diverge.

    2. theta_2(t) overlay — same for the lower arm.

    3. Pairwise divergence Delta_ij(t) = sqrt((th1_i - th1_j)^2 +
       (th2_i - th2_j)^2) (degrees). Plotted on log-y. Average over
       all C(N,2) pairs gives <ln Delta>(t); slope of the early-time
       linear regime is an empirical lambda_1 estimate independent
       of the Rosenstein single-trajectory algorithm.

    4. Phase-portrait overlay (theta_1 vs omega_1) — every clip's
       trajectory on one panel, semi-transparent, coloured by clip.

Inputs: measurements/<stem>/verification.csv for each stem in the
group. The script time-aligns each trajectory to its first non-NaN
free_swing frame so all clips start from t=0.

Output:
    figures/aggregate/group_overlay_<group>.png

Usage:
    # Predefined group (matches curate_set.py groups):
    python scripts/analysis/group_overlay.py --group group_a

    # Custom set:
    python scripts/analysis/group_overlay.py \
        --stems th1_p091_th2_m001,th1_p092_th2_m002,th1_p092_th2_p000

    # Override window length:
    python scripts/analysis/group_overlay.py --group group_a --max-time 8
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


ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.abspath(__file__))))
MEAS_DIR = os.path.join(ROOT, "measurements")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

# Mirror curate_set.py groups so callers can use either name.
GROUPS = {
    # th1_p093_th2_m002 dropped 2026-05-06 — residual ω at release.
    "group_a": [
        "th1_p091_th2_m001",
        "th1_p092_th2_m002",
        "th1_p092_th2_p000",
        "th1_p093_th2_m000",
        "th1_p094_th2_p000",
    ],
    "tier_1": [
        "th1_p044_th2_m001",
        "th1_p056_th2_m001",
        "th1_p082_th2_p001",
        "th1_p180_th2_m179",
    ],
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--group", choices=list(GROUPS),
                   help="predefined curated set")
    p.add_argument("--stems",
                   help="comma-separated stems (overrides --group)")
    p.add_argument("--max-time", type=float, default=None,
                   help="cap the analysis window in seconds")
    p.add_argument("--fit-lo", type=float, default=0.3,
                   help="fit window start in seconds (default 0.3). Tighten "
                        "to skip the non-linear transient if pair separations "
                        "are not infinitesimal at t=0.")
    p.add_argument("--fit-hi", type=float, default=1.5,
                   help="fit window end in seconds (default 1.5)")
    p.add_argument("--out-name", default=None,
                   help="output filename (default: group_overlay_<group>.png)")
    return p.parse_args()


def resolve_stems(args):
    if args.stems:
        return [s.strip() for s in args.stems.split(",") if s.strip()]
    if args.group:
        return list(GROUPS[args.group])
    raise SystemExit("Need --group or --stems.")


def load_traj(stem):
    """Load free_swing (t, th1, th2) for a clip. NaN-pad gap rows so
    overlapping clips can be array-aligned by frame index."""
    path = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(path):
        return None
    t, th1, th2 = [], [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") != "free_swing":
                continue
            try:
                ts = float(r["time_s"])
            except (KeyError, ValueError):
                continue
            try:
                a = float(r["theta1_deg"])
                b = float(r["theta2_deg"])
            except (KeyError, ValueError):
                a = np.nan; b = np.nan
            t.append(ts); th1.append(a); th2.append(b)
    if len(t) < 30:
        return None
    t = np.array(t); th1 = np.array(th1); th2 = np.array(th2)
    t = t - t[0]
    return t, th1, th2


def time_aligned(rows, max_time=None):
    """Resample each clip onto a common time grid (the densest one's dt
    over the shortest one's t_max)."""
    dt = float(np.median(np.diff(rows[0]["t"])))
    t_max = min(r["t"][-1] for r in rows)
    if max_time is not None:
        t_max = min(t_max, max_time)
    grid = np.arange(0, t_max, dt)
    out = []
    for r in rows:
        # Linear-interp onto the common grid; NaNs in source -> NaNs out.
        # Unwrap to ensure interpolation respects the ±180 wrap.
        th1u = np.degrees(np.unwrap(np.radians(np.where(np.isnan(r["th1"]),
                                                         0, r["th1"]))))
        th2u = np.degrees(np.unwrap(np.radians(np.where(np.isnan(r["th2"]),
                                                         0, r["th2"]))))
        nan_mask = np.isnan(r["th1"]) | np.isnan(r["th2"])
        th1u[nan_mask] = np.nan
        th2u[nan_mask] = np.nan
        out.append({
            "stem": r["stem"],
            "t":    grid,
            "th1":  np.interp(grid, r["t"], th1u),
            "th2":  np.interp(grid, r["t"], th2u),
        })
    return out


def pairwise_divergence(rows):
    """For every pair (i,j), Delta_ij(t) = sqrt(dth1^2 + dth2^2) in degrees.
    Returns array of shape (n_pairs, n_t)."""
    n = len(rows)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            dth1 = rows[i]["th1"] - rows[j]["th1"]
            dth2 = rows[i]["th2"] - rows[j]["th2"]
            d    = np.sqrt(dth1 ** 2 + dth2 ** 2)
            pairs.append(d)
    return np.array(pairs)


def fit_divergence_slope(t, d_pairs, fit_lo_s=0.3, fit_hi_s=1.5):
    """Fit <ln Delta>(t) over a chosen window. Returns (slope, r2,
    mean_log_d, fit_window_indices)."""
    # Replace zeros with the smallest positive divergence in each pair to
    # avoid log(0) artefacts when two clips happen to coincide at t=0.
    d_clip = np.where(d_pairs > 0, d_pairs, np.nan)
    log_d_per_pair = np.log(d_clip)
    mean_log_d = np.nanmean(log_d_per_pair, axis=0)

    lo = int(fit_lo_s / (t[1] - t[0]))
    hi = int(fit_hi_s / (t[1] - t[0]))
    hi = min(hi, len(t) - 2)
    if hi - lo < 5:
        return float("nan"), float("nan"), mean_log_d, (lo, hi)

    x = t[lo:hi + 1]
    y = mean_log_d[lo:hi + 1]
    valid = np.isfinite(y)
    if valid.sum() < 5:
        return float("nan"), float("nan"), mean_log_d, (lo, hi)
    coef = np.polyfit(x[valid], y[valid], 1)
    slope = float(coef[0])
    yhat = np.polyval(coef, x[valid])
    ss_res = np.sum((y[valid] - yhat) ** 2)
    ss_tot = np.sum((y[valid] - y[valid].mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return slope, r2, mean_log_d, (lo, hi)


def make_figure(rows, out_path, label, fit_lo=0.3, fit_hi=1.5):
    n = len(rows)
    t = rows[0]["t"]
    cmap = plt.cm.tab10
    colors = [cmap(i / max(1, n - 1)) for i in range(n)]

    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(3, 2, hspace=0.32, wspace=0.22,
                          left=0.07, right=0.97, top=0.95, bottom=0.06)
    ax_th1 = fig.add_subplot(gs[0, 0])
    ax_th2 = fig.add_subplot(gs[0, 1])
    ax_div = fig.add_subplot(gs[1, :])
    ax_pp  = fig.add_subplot(gs[2, :])

    # ── theta1(t) overlay ──────────────────────────────────────────────
    for r, c in zip(rows, colors):
        ax_th1.plot(t, r["th1"], color=c, lw=0.9, label=r["stem"], alpha=0.85)
    ax_th1.set_xlabel("t (s)")
    ax_th1.set_ylabel(r"$\theta_1$ (deg)")
    ax_th1.set_title(r"$\theta_1(t)$ overlay  —  similar IC, divergent paths")
    ax_th1.grid(True, alpha=0.3)
    ax_th1.legend(loc="upper right", fontsize=7, ncol=2)

    # ── theta2(t) overlay ──────────────────────────────────────────────
    for r, c in zip(rows, colors):
        ax_th2.plot(t, r["th2"], color=c, lw=0.9, alpha=0.85)
    ax_th2.set_xlabel("t (s)")
    ax_th2.set_ylabel(r"$\theta_2$ (deg)")
    ax_th2.set_title(r"$\theta_2(t)$ overlay")
    ax_th2.grid(True, alpha=0.3)

    # ── Pairwise divergence ────────────────────────────────────────────
    d_pairs = pairwise_divergence(rows)
    slope, r2, mean_log_d, (lo, hi) = fit_divergence_slope(
        t, d_pairs, fit_lo_s=fit_lo, fit_hi_s=fit_hi)

    for d in d_pairs:
        ax_div.plot(t, np.where(d > 0, d, np.nan),
                    color="black", lw=0.5, alpha=0.25)
    # Mean curve in log space.
    mean_d = np.exp(mean_log_d)
    ax_div.plot(t, mean_d, color="tab:red", lw=2,
                label=r"$\langle \Delta \rangle$  (geometric mean)")
    if np.isfinite(slope):
        intercept = mean_log_d[lo] - slope * t[lo]
        x_fit = t[lo:hi + 1]
        y_fit = np.exp(intercept + slope * x_fit)
        ax_div.plot(x_fit, y_fit, color="tab:blue", lw=2.2, ls="--",
                    label=f"fit  λ₁ ≈ {slope:.3f} /s   R² = {r2:.2f}")
        ax_div.axvspan(t[lo], t[hi], color="tab:blue", alpha=0.07)
    ax_div.set_yscale("log")
    ax_div.set_xlabel("t (s)")
    ax_div.set_ylabel(r"pair separation  $\Delta_{ij}$  (deg, log scale)")
    ax_div.set_title(
        f"Pairwise divergence  ({len(d_pairs)} pairs, "
        f"empirical λ₁ from twin-trial slope)")
    ax_div.legend(loc="lower right")
    ax_div.grid(True, alpha=0.3, which="both")

    # ── Phase portrait overlay (theta1 vs theta2) ─────────────────────
    for r, c in zip(rows, colors):
        ax_pp.plot(r["th1"], r["th2"], color=c, lw=0.4, alpha=0.5)
    ax_pp.set_xlabel(r"$\theta_1$ (deg)")
    ax_pp.set_ylabel(r"$\theta_2$ (deg)")
    ax_pp.set_title("Configuration-space overlay (all clips, same colour scheme)")
    ax_pp.grid(True, alpha=0.3)

    fig.suptitle(
        f"Sensitivity to initial conditions — {label}  ({n} clips, "
        f"|θ₁|≈90°, |θ₂|≈0°)",
        fontsize=13, y=0.985)
    plt.savefig(out_path, dpi=140)
    mirror_to_ready(out_path)
    plt.close(fig)
    return slope, r2


def main():
    args = parse_args()
    stems = resolve_stems(args)
    print(f"group_overlay.py — {len(stems)} clips")

    raw = []
    for stem in stems:
        d = load_traj(stem)
        if d is None:
            print(f"  [skip] {stem}: no usable verification.csv")
            continue
        t, th1, th2 = d
        raw.append({"stem": stem, "t": t, "th1": th1, "th2": th2})

    if len(raw) < 2:
        print("  fewer than 2 usable clips — nothing to overlay.")
        return

    print(f"  loaded {len(raw)} trajectories")
    rows = time_aligned(raw, max_time=args.max_time)
    print(f"  common time grid: 0 → {rows[0]['t'][-1]:.2f}s, "
          f"dt = {(rows[0]['t'][1] - rows[0]['t'][0])*1000:.2f}ms")

    label = args.group or "custom set"
    out_name = args.out_name or f"group_overlay_{args.group or 'custom'}.png"
    slope, r2 = make_figure(rows, aggregate_path(out_name), label,
                            fit_lo=args.fit_lo, fit_hi=args.fit_hi)
    print(f"  empirical λ₁ from twin-trial divergence: "
          f"{slope:+.3f} /s  (R² = {r2:.2f})")
    print(f"  wrote {aggregate_path(out_name)}")


if __name__ == "__main__":
    main()
