#!/usr/bin/env python3
"""
dimension.py — fractal dimension of the attractor.

The third defining signature of chaos (after a positive Lyapunov exponent
and a continuous power spectrum): a *strange* attractor has a NON-INTEGER
dimension. Two estimates, both from the measured trajectory:

  D2    correlation dimension (Grassberger–Procaccia): slope of the
        correlation integral  log C(r) vs log r  on a delay embedding of
        ω₂(t), the lower-arm angular velocity. ω₂ stays stationary even
        when the arm circulates, so D2 is well-defined whether the arm
        librates or rotates — embedding the unbounded angle would be
        drift-dominated and inflate the slope past the embedding
        dimension. The headline number; estimates the full attractor dim.
  D_box box-counting (Minkowski) dimension on the 2-D (θ₂, ω₂) attractor
        projection:  log N(ε) vs log(1/ε).  The method named in the lab
        guide; capped at 2 (it is a 2-D projection).

Reading: a periodic / phase-locked limit cycle → D ≈ 1 (a closed loop);
a strange attractor → fractional D (e.g. D2 ~ 2–3 in the embedding,
D_box ~ 1.5–2 in the projection).

θ₂ is already the lower arm's absolute lab-frame angle; ω₂ is computed
from it (gradient of the unwrapped angle), so no verification.csv needed.

Outputs:
  measurements/<stem>/dimension.json
  figures/dimension/<stem>_dimension.png   (attractor + scaling fits)

Usage:
  python scripts/analysis/dimension.py --stem 3.2V_1.20Hz
  python scripts/analysis/dimension.py --stem 3.2V_1.20Hz --m 6 --transient 8
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

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir             # noqa: E402
from figures_paths import figure_path  # noqa: E402

RUN_PHASES = ("driven", "free_swing")


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    """Clean (t, th2) — running phase, dropout 0, finite. (θ₂ absolute.)"""
    t, th2 = [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            b, tt = _f(r.get("theta2_deg")), _f(r.get("time_s"))
            if np.isfinite(b) and np.isfinite(tt):
                t.append(tt); th2.append(b)
    if len(t) < 200:
        raise ValueError(f"only {len(t)} clean frames in {csv_path} (need >= 200)")
    return np.array(t), np.array(th2)


# ─────────────────────────────────────────────
# EMBEDDING + DELAY
# ─────────────────────────────────────────────

def autocorr_tau(x, max_frac=0.25):
    """Delay τ (frames) = first 1/e crossing of the autocorrelation."""
    x = np.asarray(x, float) - np.mean(x)
    n = len(x)
    ac = np.correlate(x, x, mode="full")[n - 1:]
    if ac[0] == 0:
        return 1
    ac = ac / ac[0]
    below = np.where(ac < 1.0 / np.e)[0]
    tau = int(below[0]) if len(below) else max(1, n // 50)
    return max(1, min(tau, int(n * max_frac)))


def embed(x, m, tau):
    """Time-delay embedding → (N-(m-1)τ, m)."""
    x = np.asarray(x, float)
    n = len(x) - (m - 1) * tau
    return np.column_stack([x[i * tau: i * tau + n] for i in range(m)])


# ─────────────────────────────────────────────
# DIMENSION ESTIMATORS
# ─────────────────────────────────────────────

def _fit_loglog(xv, yv, mask):
    """Slope + R² of log(yv) vs log(xv) over `mask`."""
    lx, ly = np.log(xv[mask]), np.log(yv[mask])
    a = np.polyfit(lx, ly, 1)
    pred = np.polyval(a, lx)
    ss_res = float(np.sum((ly - pred) ** 2))
    ss_tot = float(np.sum((ly - ly.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(a[0]), float(a[1]), r2


def correlation_dimension(X, theiler, n_pairs=300000, seed=0):
    """Grassberger–Procaccia: correlation integral C(r) on sampled,
    Theiler-excluded point pairs; D2 = slope of log C vs log r in the
    scaling region (C in [0.01, 0.3])."""
    N = len(X)
    rng = np.random.default_rng(seed)
    i = rng.integers(0, N, n_pairs)
    j = rng.integers(0, N, n_pairs)
    keep = np.abs(i - j) > theiler
    i, j = i[keep], j[keep]
    d = np.sqrt(np.sum((X[i] - X[j]) ** 2, axis=1))
    d = d[d > 0]
    if len(d) < 1000:
        return None
    rmin, rmax = np.percentile(d, 1), np.percentile(d, 80)
    rs = np.logspace(np.log10(rmin), np.log10(rmax), 28)
    C = np.array([(d < r).mean() for r in rs])
    mask = (C >= 0.01) & (C <= 0.3) & (C > 0)
    if mask.sum() < 4:
        mask = C > 0
    D2, _b, r2 = _fit_loglog(rs, C, mask)
    return {"rs": rs, "C": C, "D2": D2, "r2": r2,
            "fit_lo": float(rs[mask].min()), "fit_hi": float(rs[mask].max())}


def box_counting_dimension(pts, grid_offset=0.0):
    """Box-counting on a normalized point cloud: N(ε) occupied cells at
    grid size 2^k; D_box = slope of log N vs log(1/ε) before saturation.
    grid_offset (sub-cell, in [0,1)) shifts the grid origin — used to bootstrap
    a D_box uncertainty (box-counting is otherwise deterministic)."""
    mn, mx = pts.min(0), pts.max(0)
    span = np.where(mx > mn, mx - mn, 1.0)
    p = (pts - mn) / span
    npts = len(pts)
    sizes, Ns = [], []
    for k in range(1, 10):
        nb = 2 ** k
        cells = np.floor((p + grid_offset) * nb).astype(np.int64)
        cells = np.clip(cells, 0, nb - 1)
        n_occ = len(np.unique(cells[:, 0] * nb + cells[:, 1]))
        sizes.append(1.0 / nb)
        Ns.append(n_occ)
    sizes, Ns = np.array(sizes, float), np.array(Ns, float)
    inv_eps = 1.0 / sizes
    mask = (Ns > 4) & (Ns < 0.6 * npts)
    if mask.sum() < 3:
        mask = Ns > 1
    Dbox, _b, r2 = _fit_loglog(inv_eps, Ns, mask)
    return {"sizes": sizes, "Ns": Ns, "Dbox": Dbox, "r2": r2,
            "inv_eps": inv_eps, "mask": mask}


def correlation_dimension_with_ci(X, theiler, n_pairs=300000, n_bootstrap=10):
    """correlation_dimension over n_bootstrap pair-sampling seeds. Returns the
    last valid result dict with D2 set to the bootstrap MEAN and an added
    'D2_sigma' (std across seeds); None if no seed produced a valid estimate."""
    D2s, last = [], None
    for seed in range(n_bootstrap):
        res = correlation_dimension(X, theiler, n_pairs=n_pairs, seed=seed)
        if res is not None and np.isfinite(res["D2"]):
            D2s.append(res["D2"]); last = res
    if last is None:
        return None
    last = dict(last)
    last["D2_sigma"] = float(np.std(D2s)) if len(D2s) > 1 else float("nan")
    last["D2"] = float(np.mean(D2s))
    return last


def box_counting_with_ci(pts, n_offsets=10):
    """Box-counting over n_offsets perturbed grid origins. Returns the
    zero-offset result dict with Dbox set to the offset MEAN and an added
    'Dbox_sigma' (std across offsets)."""
    base = box_counting_dimension(pts, grid_offset=0.0)
    Dboxes = []
    for i in range(n_offsets):
        off = float(np.random.default_rng(i).uniform(0.0, 1.0))
        res = box_counting_dimension(pts, grid_offset=off)
        if np.isfinite(res["Dbox"]):
            Dboxes.append(res["Dbox"])
    base = dict(base)
    base["Dbox_sigma"] = float(np.std(Dboxes)) if len(Dboxes) > 1 else float("nan")
    if Dboxes:
        base["Dbox"] = float(np.mean(Dboxes))
    return base


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

def print_table(stem, m, tau, corr, box):
    t = Table(title=f"dimension — {stem}", box=rich.box.SIMPLE_HEAD,
              title_style="bold cyan")
    t.add_column("estimator"); t.add_column("dimension", justify="right")
    t.add_column("R²", justify="right"); t.add_column("notes", style="dim")
    if corr:
        d2 = (f"{corr['D2']:.2f} ± {corr['D2_sigma']:.2f}"
              if np.isfinite(corr.get('D2_sigma', float('nan'))) else f"{corr['D2']:.2f}")
        t.add_row("D₂ correlation", d2, f"{corr['r2']:.3f}", f"GP, embed m={m} τ={tau}")
    db = (f"{box['Dbox']:.2f} ± {box['Dbox_sigma']:.2f}"
          if np.isfinite(box.get('Dbox_sigma', float('nan'))) else f"{box['Dbox']:.2f}")
    t.add_row("D_box box-count", db, f"{box['r2']:.3f}", "(θ₂, ω₂) 2-D projection, ≤2")
    console.print(t)
    console.print("  [dim]≈1 ⇒ limit cycle (periodic);  fractional ⇒ strange "
                  "attractor (chaos)[/]")


def make_figure(stem, t, th2, om2, m, tau, corr, box, out_path):
    fig, ((a, b), (c, d)) = plt.subplots(2, 2, figsize=(13, 11))
    tc = t - t[0]
    d2_lbl = (f"D₂ = {corr['D2']:.2f} ± {corr['D2_sigma']:.2f}"
              if corr and np.isfinite(corr.get('D2_sigma', float('nan')))
              else (f"D₂ = {corr['D2']:.2f}" if corr else "D₂ = —"))
    db_lbl = (f"D_box = {box['Dbox']:.2f} ± {box['Dbox_sigma']:.2f}"
              if np.isfinite(box.get('Dbox_sigma', float('nan'))) else f"D_box = {box['Dbox']:.2f}")

    # (a) reconstructed attractor — delay embedding ω₂(t) vs ω₂(t+τ)
    #     (ω₂ is the observable used for D₂: stationary under circulation)
    x0, x1 = om2[:-tau], om2[tau:]
    a.scatter(x0, x1, c=tc[:len(x0)], cmap="viridis", s=2, alpha=0.4,
              edgecolors="none")
    a.set_xlabel("ω₂(t) (deg/s)"); a.set_ylabel(f"ω₂(t+τ)  (τ={tau})")
    a.set_title("reconstructed attractor (ω₂ delay embedding)")
    a.grid(True, alpha=0.2)

    # (b) physical attractor — θ₂ vs ω₂
    b.scatter(th2, om2, c=tc, cmap="viridis", s=2, alpha=0.4, edgecolors="none")
    b.set_xlabel("θ₂ (deg)"); b.set_ylabel("ω₂ (deg/s)")
    b.set_title("phase-space attractor (θ₂, ω₂)")
    b.grid(True, alpha=0.2)

    # (c) correlation integral
    if corr:
        c.loglog(corr["rs"], corr["C"], "o", color="tab:blue", ms=4)
        fitmask = (corr["rs"] >= corr["fit_lo"]) & (corr["rs"] <= corr["fit_hi"])
        rr = corr["rs"][fitmask]
        if len(rr):
            Cfit = corr["C"][fitmask][0] * (rr / rr[0]) ** corr["D2"]
            c.loglog(rr, Cfit, "-", color="tab:red", lw=2,
                     label=f"{d2_lbl}  (R²={corr['r2']:.3f})")
        c.legend(fontsize=9)
    c.set_xlabel("r"); c.set_ylabel("C(r)")
    c.set_title("correlation integral (Grassberger–Procaccia)")
    c.grid(True, which="both", alpha=0.2)

    # (d) box counting
    d.loglog(box["inv_eps"], box["Ns"], "o", color="tab:green", ms=4)
    mfit = box["mask"]
    ie = box["inv_eps"][mfit]
    if len(ie):
        Nfit = box["Ns"][mfit][0] * (ie / ie[0]) ** box["Dbox"]
        d.loglog(ie, Nfit, "-", color="tab:red", lw=2,
                 label=f"{db_lbl}  (R²={box['r2']:.3f})")
        d.legend(fontsize=9)
    d.set_xlabel("1/ε"); d.set_ylabel("N(ε) occupied boxes")
    d.set_title("box-counting (θ₂, ω₂ projection)")
    d.grid(True, which="both", alpha=0.2)

    fig.suptitle(f"Attractor dimension — {stem}   ({d2_lbl}, {db_lbl})",
                 fontsize=13, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ─────────────────────────────────────────────

def compute(stem, m, tau_arg, transient_s, seed=0):
    """Shared entry: returns (t, th2, om2, m, tau, corr, box)."""
    cdir = clip_dir(stem)
    csv_path = next((os.path.join(cdir, n) for n in
                     ("verification.csv", "tracking.csv")
                     if os.path.exists(os.path.join(cdir, n))), None)
    if csv_path is None:
        raise SystemExit(f"no verification.csv / tracking.csv in {cdir}")

    t, th2 = load_clip(csv_path)
    keep = t >= (t[0] + transient_s)
    if keep.sum() > 200:
        t, th2 = t[keep], th2[keep]

    phi = np.degrees(np.unwrap(np.radians(th2)))   # continuous angle, for ω
    om2 = np.gradient(phi, t)
    # Embed the angular VELOCITY ω₂, not the angle: ω₂ is stationary even
    # when the lower arm circulates, whereas the unwrapped angle drifts
    # without bound and makes the delay-embedding drift-dominated (which
    # inflates the GP slope past the embedding dimension on rotating clips).
    tau = tau_arg or autocorr_tau(om2)

    X = embed(om2, m, tau)
    dt = float(np.median(np.diff(t)))
    theiler = max(tau, int(round(0.5 / dt)) if dt > 0 else tau)  # ~0.5 s
    corr = correlation_dimension_with_ci(X, theiler)
    box = box_counting_with_ci(np.column_stack([th2, om2]))
    return t, th2, om2, m, tau, corr, box


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True, help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--m", type=int, default=5, help="embedding dimension (default 5)")
    p.add_argument("--tau", type=int, default=None, help="delay in frames (auto if omitted)")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start (default 5)")
    return p.parse_args()


def main():
    args = parse_args()
    stem = args.stem
    t, th2, om2, m, tau, corr, box = compute(stem, args.m, args.tau, args.transient)

    print_table(stem, m, tau, corr, box)

    out = {
        "stem": stem, "embedding_m": m, "delay_tau": tau,
        "n_points": int(len(th2)),
        "D2_correlation": (corr["D2"] if corr else None),
        "D2_sigma": (corr.get("D2_sigma") if corr else None),
        "D2_r2": (corr["r2"] if corr else None),
        "D_box": box["Dbox"], "D_box_sigma": box.get("Dbox_sigma"),
        "D_box_r2": box["r2"],
    }
    out_json = os.path.join(clip_dir(stem), "dimension.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    console.print(f"  [dim]→ {out_json}[/]")

    out_png = figure_path("dimension", stem)
    make_figure(stem, t, th2, om2, m, tau, corr, box, out_png)
    console.print(f"  [dim]→ {out_png}[/]")


if __name__ == "__main__":
    main()
