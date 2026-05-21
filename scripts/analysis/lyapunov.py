"""
lyapunov.py
-----------
Largest Lyapunov exponent (lambda_1) from a single experimental time
series, using Rosenstein et al.'s algorithm (Physica D, 1993).

Pipeline
~~~~~~~~
1. Read free-swing theta1(t) from verification.csv. Unwrap so jumps
   across +-180 do not create phantom discontinuities.
2. Build a time-delay embedding:
       y(t_i) = [ x(t_i), x(t_i + tau), ..., x(t_i + (m-1)*tau) ]
   Embedding dim m is fixed at 5 (a safe choice for a chaotic system
   whose true phase space is 4D); tau is auto-picked from the first
   1/e crossing of the autocorrelation, clamped to [3, 30] frames.
3. For each embedded point j, find the nearest neighbor index n(j)
   in Euclidean distance, subject to a Theiler window |j - n(j)| > W
   (W = roughly one oscillation period in samples).
4. Track the divergence d_j(k) = || y(t_{j+k}) - y(t_{n(j)+k}) ||
   for k = 0, 1, ..., k_max. Average ln d_j(k) over j -> S(k).
5. Slope of S(k) vs k * dt over the early linear regime is lambda_1
   (in units of 1/s).

Output
~~~~~~
  measurements/<stem>/lyapunov.png  (4-panel figure)
  Prints lambda_1 and tau, m, W to stdout.

Usage
~~~~~
  python scripts/analysis/lyapunov.py --stem th1_p044_th2_m001
  python scripts/analysis/lyapunov.py --stem th1_p180_th2_m179 \
    --emb-dim 6 --tau 8 --k-max 200

References
~~~~~~~~~~
Rosenstein, Collins & De Luca (1993). A practical method for calculating
largest Lyapunov exponents from small data sets. Physica D, 65, 117-134.
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
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402

def parse_args():
    p = argparse.ArgumentParser(
        description="Rosenstein largest Lyapunov estimator.")
    p.add_argument("csv", nargs="?", default=None,
                   help="verification.csv (positional)")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p044_th2_m001")
    p.add_argument("--emb-dim", type=int, default=5,
                   help="embedding dimension m (default 5)")
    p.add_argument("--tau", type=int, default=None,
                   help="embedding delay in frames; auto-pick if omitted")
    p.add_argument("--k-max", type=int, default=120,
                   help="max divergence horizon in frames (default 120)")
    p.add_argument("--theiler", type=int, default=None,
                   help="Theiler window in frames; auto = ~1 period")
    p.add_argument("--fit-range", type=str, default=None,
                   help="frames over which to fit the slope, e.g. '5-40'")
    p.add_argument("--use-omega", action="store_true",
                   help="embed omega1 instead of theta1")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()

def resolve_io(args):
    if args.stem:
        meas = clip_dir(args.stem)
        return os.path.join(meas, "verification.csv"), meas, args.stem
    if args.csv:
        out_dir = os.path.dirname(os.path.abspath(args.csv))
        return args.csv, out_dir, os.path.basename(out_dir)
    raise SystemExit("Need --stem or a CSV path.")

def load_series(csv_path, use_omega=False):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") != "free_swing":
                continue
            try:
                rows.append((
                    float(r["time_s"]),
                    float(r["theta1_deg"]),
                    float(r["omega1_deg_s"]),
                ))
            except (ValueError, KeyError):
                continue
    if len(rows) < 200:
        raise SystemExit(f"Too few free-swing rows ({len(rows)}).")
    arr = np.array(rows, dtype=float)
    t   = arr[:, 0] - arr[0, 0]
    th  = arr[:, 1]
    om  = arr[:, 2]
    th  = np.degrees(np.unwrap(np.radians(th)))
    return t, om if use_omega else th

def autocorr_first_drop(x, threshold=1.0 / np.e, lag_max=None):
    """First lag at which the (normalised) autocorrelation drops below
    threshold. Default threshold 1/e per Abarbanel's recipe."""
    x = x - np.mean(x)
    n = len(x)
    if lag_max is None:
        lag_max = min(n // 4, 500)
    var = np.dot(x, x) / n
    if var == 0:
        return 5
    for lag in range(1, lag_max):
        ac = np.dot(x[:n - lag], x[lag:]) / ((n - lag) * var)
        if ac < threshold:
            return max(lag, 1)
    return lag_max

def estimate_period_frames(t, x):
    """Crude period estimate: dominant non-DC FFT bin."""
    dt = float(np.mean(np.diff(t)))
    n  = len(x)
    fft = np.fft.rfft(x - np.mean(x))
    freqs = np.fft.rfftfreq(n, d=dt)
    if len(fft) < 2:
        return 60
    power = np.abs(fft[1:]) ** 2
    if power.sum() == 0:
        return 60
    f_peak = freqs[1 + np.argmax(power)]
    if f_peak <= 0:
        return 60
    return max(int(round(1.0 / f_peak / dt)), 6)

def embed(x, m, tau):
    """Time-delay embedding. Returns array of shape (N - (m-1)*tau, m)."""
    N = len(x) - (m - 1) * tau
    out = np.empty((N, m), dtype=float)
    for j in range(m):
        out[:, j] = x[j * tau : j * tau + N]
    return out

def rosenstein(emb, theiler, k_max):
    """
    Returns S(k), the average ln distance to the nearest neighbor at
    horizon k frames, k = 0..k_max. Theiler exclusion: skip neighbors
    within +-theiler frames.
    """
    N = emb.shape[0]
    tree = cKDTree(emb)

    # For each point, find nearest non-Theiler neighbor.
    nn = np.full(N, -1, dtype=int)
    # Query enough neighbors to satisfy the Theiler window.
    # Empirically ~50 covers all but pathological cases.
    K = min(50, N - 1)
    dists, idxs = tree.query(emb, k=K + 1)
    for i in range(N):
        for j_rank in range(1, K + 1):
            cand = idxs[i, j_rank]
            if abs(cand - i) > theiler and dists[i, j_rank] > 0:
                nn[i] = cand
                break

    # Track divergence over k = 0..k_max.
    valid_max = N - 1
    S = np.full(k_max + 1, np.nan, dtype=float)
    for k in range(k_max + 1):
        log_dists = []
        for i in range(N - k):
            j = nn[i]
            if j < 0 or j + k >= N:
                continue
            d = np.linalg.norm(emb[i + k] - emb[j + k])
            if d > 0:
                log_dists.append(np.log(d))
        if log_dists:
            S[k] = np.mean(log_dists)
    return S

def linear_fit_slope(x, y, lo, hi):
    mask = np.arange(len(y))
    sel  = (mask >= lo) & (mask <= hi) & np.isfinite(y)
    if sel.sum() < 5:
        return float("nan"), float("nan"), float("nan")
    coef = np.polyfit(x[sel], y[sel], 1)
    slope, intercept = coef
    yhat = np.polyval(coef, x[sel])
    ss_res = np.sum((y[sel] - yhat) ** 2)
    ss_tot = np.sum((y[sel] - y[sel].mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return slope, intercept, r2

def auto_fit_range(S, k_max):
    """Pick the linear stretch as: skip the first ~3 frames (transient
    initialisation), end at the first sign of saturation (sample-to-
    sample increase < 0.005). Returns (lo, hi)."""
    finite_idx = np.where(np.isfinite(S))[0]
    if len(finite_idx) < 10:
        return 0, k_max
    lo = max(int(0.05 * k_max), 3)
    # Saturation when smoothed slope drops below 5% of early slope.
    # Light smoothing.
    smooth = np.convolve(S, np.ones(5) / 5.0, mode="same")
    early_slope = (smooth[lo + 5] - smooth[lo]) / 5.0
    hi = k_max
    for k in range(lo + 10, k_max - 5):
        local = (smooth[k + 5] - smooth[k]) / 5.0
        if early_slope > 0 and local < 0.05 * early_slope:
            hi = k
            break
    # Hard floor: need at least ~10 frames of post-transient signal,
    # otherwise we extend even at the risk of crossing into saturation
    # (the user can override with --fit-range).
    if hi - lo < 10:
        hi = min(k_max, lo + 10)
    return lo, hi

def make_figure(t, x, S, dt, tau, m, theiler,
                slope, intercept, r2, fit_lo, fit_hi,
                label, out_path):
    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.28,
                          left=0.07, right=0.97, top=0.93, bottom=0.07)
    ax_ts   = fig.add_subplot(gs[0, 0])
    ax_div  = fig.add_subplot(gs[0, 1])
    ax_emb  = fig.add_subplot(gs[1, 0])
    ax_meta = fig.add_subplot(gs[1, 1]); ax_meta.axis("off")

    # Time series.
    ax_ts.plot(t, x, lw=0.7, color="tab:blue")
    ax_ts.set_xlabel("t (s)")
    ax_ts.set_ylabel("theta1 unwrapped (deg)")
    ax_ts.set_title("Free-swing time series")
    ax_ts.grid(True, alpha=0.3)

    # Divergence curve.
    k = np.arange(len(S))
    t_k = k * dt
    ax_div.plot(t_k, S, color="tab:gray", lw=1, label="<ln d>(k)")
    if np.isfinite(slope):
        ax_div.plot(t_k[fit_lo:fit_hi + 1],
                    intercept + slope * t_k[fit_lo:fit_hi + 1],
                    color="tab:red", lw=2,
                    label=f"fit  slope = {slope:.3f}/s")
    ax_div.axvspan(t_k[fit_lo], t_k[fit_hi], color="tab:red", alpha=0.08)
    ax_div.set_xlabel("k * dt   (s)")
    ax_div.set_ylabel("<ln d(k)>")
    ax_div.set_title("Divergence curve")
    ax_div.legend(loc="lower right", fontsize=10)
    ax_div.grid(True, alpha=0.3)

    # 2D projection of the embedding.
    emb = embed(x, m=2, tau=tau)
    ax_emb.scatter(emb[:, 0], emb[:, 1], s=1, alpha=0.5, color="tab:purple")
    ax_emb.set_xlabel(f"x(t)")
    ax_emb.set_ylabel(f"x(t + {tau} frames)")
    ax_emb.set_title("Delay embedding (m=2 projection)")
    ax_emb.grid(True, alpha=0.3)

    # Metadata box.
    lines = [
        f"Stem            : {label}",
        f"Sampling dt     : {dt*1000:.2f} ms",
        f"Embedding dim m : {m}",
        f"Embedding tau   : {tau} frames  ({tau*dt*1000:.1f} ms)",
        f"Theiler window  : {theiler} frames",
        f"Fit range       : k = {fit_lo}..{fit_hi}",
        f"slope (lambda_1): {slope:+.4f} /s     R^2 = {r2:.3f}",
        f"Lyap. timescale : {1/slope:.2f} s" if (
            np.isfinite(slope) and slope > 0) else "Lyap. timescale : n/a",
        "",
        "Interpretation",
        "  lambda_1 > 0  -> chaotic (positive divergence)",
        "  lambda_1 ~ 0  -> regular / quasi-periodic",
        "  lambda_1 < 0  -> dissipative / attracted to fixed point",
    ]
    ax_meta.text(0.0, 0.95, "\n".join(lines),
                 family="monospace", fontsize=11, va="top")

    fig.suptitle(f"Largest Lyapunov exponent (Rosenstein) — {label}",
                 fontsize=14, y=0.98)
    fig.savefig(out_path, dpi=130)
    mirror_to_ready(out_path)
    plt.close(fig)

def main():
    args = parse_args()
    csv_path, out_dir, label = resolve_io(args)
    print(f"Reading {csv_path} ...")
    t, x = load_series(csv_path, use_omega=args.use_omega)
    dt = float(np.mean(np.diff(t)))
    print(f"  {len(x)} samples, dt = {dt*1000:.2f} ms, t_max = {t[-1]:.2f}s")

    # Auto-pick tau and Theiler if not given.
    if args.tau is None:
        tau = autocorr_first_drop(x)
        tau = max(3, min(tau, 30))
        print(f"  auto tau   = {tau} frames  (1/e of autocorrelation)")
    else:
        tau = args.tau
        print(f"  tau        = {tau} frames  (user-set)")

    if args.theiler is None:
        period = estimate_period_frames(t, x)
        # For chaotic clips the FFT peak drifts to spurious low-frequency
        # bins. Cap at 200 frames (~3.3s at 60fps), well above the rod
        # pendulum's natural period (~1.2s = 72 frames).
        theiler = max(min(period, 200), 30)
        print(f"  auto Theiler window = {theiler} frames  "
              f"(period estimate {period}, capped at 200)")
    else:
        theiler = args.theiler

    m = args.emb_dim
    print(f"  embedding dim m = {m}")

    emb = embed(x, m, tau)
    if emb.shape[0] < 2 * theiler:
        raise SystemExit(
            f"Embedded length {emb.shape[0]} too small for Theiler {theiler}.")

    print(f"  computing nearest-neighbor divergence ...")
    S = rosenstein(emb, theiler=theiler, k_max=args.k_max)

    if args.fit_range:
        lo_s, hi_s = args.fit_range.split("-")
        fit_lo, fit_hi = int(lo_s), int(hi_s)
    else:
        fit_lo, fit_hi = auto_fit_range(S, args.k_max)
    print(f"  fitting slope over k = {fit_lo}..{fit_hi}")

    k = np.arange(len(S))
    slope, intercept, r2 = linear_fit_slope(k * dt, S, fit_lo, fit_hi)
    print(f"  lambda_1 = {slope:+.4f} /s     R^2 = {r2:.3f}")
    if np.isfinite(slope) and slope > 0:
        print(f"  Lyapunov timescale 1/lambda_1 = {1/slope:.2f} s")

    if not args.no_plot:
        out_png = figure_path("lyapunov", label)
        make_figure(t, x, S, dt, tau, m, theiler,
                    slope, intercept, r2, fit_lo, fit_hi,
                    label, out_png)
        print(f"  wrote {out_png}")

if __name__ == "__main__":
    main()
