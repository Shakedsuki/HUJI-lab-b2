"""
chaos_analyze.py
----------------
Chaos physics analysis for a tracked double-pendulum clip. Reads
measurements/<stem>/verification.csv (produced by verify_tracking.py)
and computes two tiers of measures:

  Tier 1 — topological (fast, no heavy math):
    max |θ₂_abs|, arm-2 full rotations, fraction inverted,
    E_release, E_inversion threshold (= 4·g·L ≈ 13.72 J/kg),
    E_peak / E_inversion ratio.

  Tier 2 — statistical:
    0-1 test for chaos (Gottwald & Melbourne, Proc. R. Soc. A, 2004):
      applied to θ₁(t), θ₂(t), and θ₂_abs(t).  K → 1 = chaos,
      K → 0 = regular.  Uses FFT-based MSD for O(N log N) performance.
    Spectral entropy of θ₁ and θ₂ normalised to [0, 1]:
      0 = pure sinusoid, 1 = white noise.

Combines measures into one of three verdicts: CHAOTIC, BORDERLINE,
or REGULAR.  Prints a verdict card to stdout and (unless --no-plot)
writes measurements/<stem>/chaos_analyze.png with:
  left  — θ₂_abs(t) timeline coloured by E / E_inversion
  right — power spectrum of θ₂(t) on log-log axes

Usage:
    chaos analyze <stem>
    python scripts/analysis/chaos_analyze.py <stem>

Reference:
    Gottwald G. A. & Melbourne I. (2004). A new test for chaos in
    deterministic systems. Proc. R. Soc. A, 460, 603–611.
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from figures_paths import figure_path, mirror_to_journal  # noqa: E402


# scripts/analysis/ → scripts/ → repo root
ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__))))
MEAS_DIR = os.path.join(ROOT, "measurements")

# Rod-pendulum physical constants (Brief 9 formula, mirrors friction_fit.py).
_L = 0.35   # arm length in metres
_G = 9.8    # gravitational acceleration m/s²

# Energy threshold for both arms simultaneously inverted from rest:
#   PE_max = g*(3L/2)*(1-cos 180°) + g*(L/2)*(1-cos 180°)
#          = g*(3L/2)*2 + g*(L/2)*2 = 4*g*L
E_INVERSION = 4.0 * _G * _L   # ≈ 13.72 J/kg per unit mass


# ─────────────────────────────────────────────
# ENERGY FORMULA  (identical to friction_fit.py)
# ─────────────────────────────────────────────

def E_per_frame(th1_deg, th2_deg, om1_dps, om2_dps):
    th1_r     = np.radians(th1_deg)
    th2_abs_r = np.radians(th1_deg + th2_deg)
    th2_rel_r = np.radians(th2_deg)
    w1_r      = np.radians(om1_dps)
    w2_abs_r  = np.radians(om1_dps + om2_dps)
    PE = (_G * (3.0 * _L / 2.0) * (1.0 - np.cos(th1_r))
        + _G * (_L / 2.0)       * (1.0 - np.cos(th2_abs_r)))
    KE = _L**2 * (
          (2.0 / 3.0) * w1_r**2
        + 0.5         * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1.0 / 6.0) * w2_abs_r**2)
    return KE + PE


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def load_free_swing(csv_path):
    """
    Read verification.csv and return arrays for the free_swing phase,
    filtered to non-dropout, non-NaN rows.
    Raises ValueError when fewer than 30 valid frames remain.
    """
    df   = pd.read_csv(csv_path)
    free = df[df["phase"] == "free_swing"].copy().reset_index(drop=True)

    om1 = pd.to_numeric(free["omega1_deg_s"], errors="coerce")
    om2 = pd.to_numeric(free["omega2_deg_s"], errors="coerce")
    th1 = pd.to_numeric(free["theta1_deg"],   errors="coerce")
    th2 = pd.to_numeric(free["theta2_deg"],   errors="coerce")
    t   = pd.to_numeric(free["time_s"],       errors="coerce")

    valid = ~(om1.isna() | om2.isna() | th1.isna() | th2.isna() | t.isna())
    if "dropout" in free.columns:
        try:
            valid = valid & (free["dropout"].fillna(0).astype(float).astype(int) == 0)
        except (ValueError, TypeError):
            pass

    n = int(valid.sum())
    if n < 30:
        raise ValueError(
            f"only {n} valid free_swing frames — too few to analyse")

    return {
        "time_s":   t[valid].values.astype(float),
        "th1":      th1[valid].values.astype(float),
        "th2":      th2[valid].values.astype(float),
        "om1":      om1[valid].values.astype(float),
        "om2":      om2[valid].values.astype(float),
        "n_frames": n,
    }


# ─────────────────────────────────────────────
# TIER 1 — TOPOLOGICAL MEASURES
# ─────────────────────────────────────────────

def compute_topological(data):
    """Return dict of Tier-1 topological measures + per-frame arrays for plotting."""
    th1 = data["th1"]
    th2 = data["th2"]
    om1 = data["om1"]
    om2 = data["om2"]
    t   = data["time_s"]

    theta2_abs = th1 + th2

    max_theta2_abs = float(np.max(np.abs(theta2_abs)))
    frac_inverted  = float(np.mean(np.abs(theta2_abs) > 90.0))

    # Net arm-2 rotations via unwrapped angle
    unwrapped = np.unwrap(np.radians(theta2_abs))
    net_rad   = float(unwrapped[-1] - unwrapped[0])
    n_arm2_rotations = int(abs(net_rad) / (2.0 * np.pi))

    # E_release: p99 of first 100 clean frames (mirrors verify_tracking reference)
    n_ref    = min(100, len(th1))
    E_ref    = E_per_frame(th1[:n_ref], th2[:n_ref], om1[:n_ref], om2[:n_ref])
    E_release = float(np.percentile(E_ref, 99))

    # E for all frames (used for E_peak and for plot colouring)
    E_trace = E_per_frame(th1, th2, om1, om2)
    E_peak  = float(np.max(E_trace))

    E_ratio_release = E_release / E_INVERSION
    E_ratio_peak    = E_peak    / E_INVERSION

    return {
        # Per-frame arrays (for plotting)
        "theta2_abs":    theta2_abs,
        "E_trace":       E_trace,
        "E_ratio_trace": E_trace / E_INVERSION,
        "time_s":        t,
        "th1":           th1,
        "th2":           th2,
        # Scalar measures
        "max_theta2_abs":    max_theta2_abs,
        "frac_inverted":     frac_inverted,
        "n_arm2_rotations":  n_arm2_rotations,
        "E_release":         E_release,
        "E_peak":            E_peak,
        "E_ratio_release":   E_ratio_release,
        "E_ratio_peak":      E_ratio_peak,
    }


# ─────────────────────────────────────────────
# TIER 2 — STATISTICAL MEASURES
# ─────────────────────────────────────────────

def k01_test(x, c_values=None, n_c=50):
    """
    0-1 test for chaos (Gottwald & Melbourne 2004).

    Returns median K over n_c random c values drawn from [π/5, 4π/5].
    K → 1 means chaos; K → 0 means regular.

    Uses FFT-based mean-square-displacement computation so the inner
    lag loop is O(N log N) per c value rather than O(N²/10).
    """
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    N = len(x)
    if N < 20:
        return float("nan")

    if c_values is None:
        rng      = np.random.default_rng(42)
        c_values = rng.uniform(np.pi / 5.0, 4.0 * np.pi / 5.0, n_c)

    n_cut = N // 10
    if n_cut < 3:
        return float("nan")

    t   = np.arange(n_cut, dtype=float)
    ns  = np.arange(1, n_cut)
    cnt = (N - ns).astype(float)

    # Next power-of-two ≥ 2N for linear autocorrelation via FFT
    n_fft = 1 << int(np.ceil(np.log2(2 * N)))

    Ks = []
    for c in c_values:
        idx = np.arange(1, N + 1, dtype=float)
        p   = np.cumsum(x * np.cos(idx * c))
        q   = np.cumsum(x * np.sin(idx * c))

        # Vectorised MSD[n] for all lags at once via FFT autocorrelation.
        # ac_p[n] = sum_{j=0}^{N-n-1} p[j]*p[j+n]  (linear autocorrelation)
        fp   = np.fft.rfft(p, n=n_fft)
        fq   = np.fft.rfft(q, n=n_fft)
        ac_p = np.fft.irfft(fp * np.conj(fp), n=n_fft)[:N].real
        ac_q = np.fft.irfft(fq * np.conj(fq), n=n_fft)[:N].real

        # Cumulative sums of squares for boundary terms
        cs_p2 = np.concatenate([[0.0], np.cumsum(p ** 2)])
        cs_q2 = np.concatenate([[0.0], np.cumsum(q ** 2)])

        # sum p[n:]^2 + sum p[:N-n]^2  (= right half + left half)
        s_p = (cs_p2[N] - cs_p2[ns]) + cs_p2[N - ns]
        s_q = (cs_q2[N] - cs_q2[ns]) + cs_q2[N - ns]

        M      = np.zeros(n_cut)
        M[1:]  = (s_p - 2.0 * ac_p[ns] + s_q - 2.0 * ac_q[ns]) / cnt

        # Oscillatory correction (≈ 0 because x is already mean-subtracted)
        denom = 1.0 - np.cos(c)
        Vosc  = ((x.mean() ** 2) * (1.0 - np.cos(t * c)) / denom
                 if abs(denom) > 1e-12 else np.zeros(n_cut))
        D = M - Vosc

        if np.std(D) > 0:
            K = float(np.corrcoef(t, D)[0, 1])
            if not np.isnan(K):
                Ks.append(K)

    return float(np.median(Ks)) if Ks else float("nan")


def spectral_entropy_norm(x):
    """
    Spectral entropy of x, normalised by log2(number of frequency bins).
    Result in [0, 1]: 0 = pure sinusoid, 1 = white noise.
    """
    x = np.asarray(x, dtype=float)
    N = len(x)
    if N < 4:
        return float("nan")
    spec = np.abs(np.fft.rfft(x - x.mean())) ** 2
    spec = spec[1:]   # drop DC
    s    = spec.sum()
    if s == 0.0:
        return float("nan")
    spec = spec / s
    H    = -float(np.sum(spec * np.log2(spec + 1e-12)))
    return H / np.log2(len(spec))


def compute_statistical(topo, n_c=50):
    """Return dict of Tier-2 statistical measures."""
    th1        = topo["th1"]
    th2        = topo["th2"]
    theta2_abs = topo["theta2_abs"]

    K_th1    = k01_test(th1,        n_c=n_c)
    K_th2    = k01_test(th2,        n_c=n_c)
    K_th2abs = k01_test(theta2_abs, n_c=n_c)

    Ks      = [k for k in (K_th1, K_th2, K_th2abs) if not np.isnan(k)]
    K_chaos = float(np.median(Ks)) if Ks else float("nan")

    H_th1 = spectral_entropy_norm(th1)
    H_th2 = spectral_entropy_norm(th2)

    return {
        "K_theta1":                  K_th1,
        "K_theta2":                  K_th2,
        "K_theta2_abs":              K_th2abs,
        "K_chaos":                   K_chaos,
        "spectral_entropy_th1_norm": H_th1,
        "spectral_entropy_th2_norm": H_th2,
    }


# ─────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────

def compute_verdict(topo, stat):
    """
    Combine Tier-1 and Tier-2 measures into one of three labels:
    CHAOTIC, BORDERLINE, or REGULAR.

    Returns (verdict, reasons) in the same style as compute_verdict in
    track_one.py: reasons explain which conditions fired.
    """
    max_th2 = topo["max_theta2_abs"]
    n_rot   = topo["n_arm2_rotations"]
    E_ratio = topo["E_ratio_peak"]
    K       = stat["K_chaos"]
    H_th2   = stat["spectral_entropy_th2_norm"]

    reasons    = []
    is_chaotic = False

    # ── CHAOTIC — any one condition is sufficient ─────────────────────
    if max_th2 > 170.0 and not np.isnan(K) and K > 0.5:
        reasons.append(
            f"full arm-2 inversions (max |θ₂_abs| = {max_th2:.1f}°) "
            f"with K = {K:.2f} > 0.5")
        is_chaotic = True

    if not np.isnan(E_ratio) and E_ratio > 1.2 and not np.isnan(K) and K > 0.5:
        reasons.append(
            f"E_peak / E_inversion = {E_ratio:.2f} > 1.2 "
            f"with K = {K:.2f} > 0.5")
        is_chaotic = True

    if n_rot > 0 and not np.isnan(K) and K > 0.4:
        reasons.append(
            f"{n_rot} full arm-2 rotation(s) with K = {K:.2f} > 0.4")
        is_chaotic = True

    if is_chaotic:
        return "CHAOTIC", reasons

    # ── REGULAR ───────────────────────────────────────────────────────
    if max_th2 < 90.0:
        reasons.append(
            f"arm-2 stays below inversion threshold "
            f"(max |θ₂_abs| = {max_th2:.1f}° < 90°)")
        return "REGULAR", reasons

    if not np.isnan(K) and K < 0.3 and not np.isnan(H_th2) and H_th2 < 0.4:
        reasons.append(
            f"K = {K:.2f} < 0.3 and spectral entropy = {H_th2:.2f} < 0.4")
        return "REGULAR", reasons

    # ── BORDERLINE ────────────────────────────────────────────────────
    k_str = f"{K:.2f}" if not np.isnan(K) else "n/a"
    reasons.append(
        f"below inversion threshold but K > 0.3 "
        f"(max |θ₂_abs| = {max_th2:.1f}°, K = {k_str})")
    if not np.isnan(H_th2):
        band  = "broadband" if H_th2 >= 0.5 else "transitional"
        reasons.append(
            f"spectral entropy in {band} band "
            f"(θ₂ norm. entropy = {H_th2:.2f})")
    return "BORDERLINE", reasons


# ─────────────────────────────────────────────
# OUTPUT — VERDICT CARD
# ─────────────────────────────────────────────

def _fmt(v, fmt=".3f"):
    return format(v, fmt) if not (isinstance(v, float) and np.isnan(v)) else "n/a"


def print_card(stem, topo, stat, verdict, reasons):
    sep = "=" * 72
    print()
    print(sep)
    print(f"  Chaos analysis — {stem}")
    print(sep)
    print()
    print(f"  Topological:")
    print(f"    max |θ₂_abs|              {topo['max_theta2_abs']:>7.1f}°")
    print(f"    arm-2 full rotations      {topo['n_arm2_rotations']:>7d}")
    print(f"    fraction inverted         {topo['frac_inverted']*100:>7.1f}%")
    print(f"    E_release / E_inversion   {_fmt(topo['E_ratio_release'],'.2f'):>7}")
    print(f"    E_peak   / E_inversion    {_fmt(topo['E_ratio_peak'],  '.2f'):>7}")
    print()
    print(f"  Statistical:")
    print(f"    K (0-1 test, θ₁)          {_fmt(stat['K_theta1']):>7}")
    print(f"    K (0-1 test, θ₂)          {_fmt(stat['K_theta2']):>7}")
    print(f"    K (0-1 test, θ₂_abs)      {_fmt(stat['K_theta2_abs']):>7}")
    print(f"    K_chaos (median)          {_fmt(stat['K_chaos']):>7}")
    print(f"    spectral entropy θ₁ (norm) {_fmt(stat['spectral_entropy_th1_norm']):>6}")
    print(f"    spectral entropy θ₂ (norm) {_fmt(stat['spectral_entropy_th2_norm']):>6}")
    print()
    print(f"  VERDICT: {verdict}")
    for r in reasons:
        print(f"    • {r}")
    print()


# ─────────────────────────────────────────────
# OUTPUT — PLOT
# ─────────────────────────────────────────────

def make_plot(stem, topo, stat, out_path):
    t          = topo["time_s"] - topo["time_s"][0]
    theta2_abs = topo["theta2_abs"]
    E_ratio    = topo["E_ratio_trace"]
    th2        = topo["th2"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # ── Left panel: θ₂_abs(t) coloured by E / E_inversion ────────────
    ax   = axes[0]
    pts  = np.stack([t, theta2_abs], axis=1).reshape(-1, 1, 2)
    segs = np.concatenate([pts[:-1], pts[1:]], axis=1)
    vmax = max(1.0, float(np.percentile(E_ratio, 99)))
    norm = Normalize(vmin=0.0, vmax=vmax)
    lc   = LineCollection(segs, cmap="viridis", norm=norm, linewidth=0.8, alpha=0.9)
    lc.set_array(E_ratio[:-1])
    ax.add_collection(lc)
    ax.set_xlim(t[0], t[-1])
    y_pad = max(10.0, (theta2_abs.max() - theta2_abs.min()) * 0.05)
    ax.set_ylim(theta2_abs.min() - y_pad, theta2_abs.max() + y_pad)
    fig.colorbar(lc, ax=ax, label="E / E_inversion")
    for hval, col, lbl in (
        ( 90,  "tomato",   "±90° (inversion threshold)"),
        (-90,  "tomato",   ""),
        ( 180, "darkred",  "±180° (fully inverted)"),
        (-180, "darkred",  ""),
    ):
        ax.axhline(hval, color=col, lw=0.9, ls="--", alpha=0.75,
                   label=lbl if lbl else "_nolegend_")
    ax.set_xlabel("time from release (s)")
    ax.set_ylabel("θ₂_abs (deg)")
    ax.set_title(f"{stem}\nθ₂_abs(t)  —  coloured by E / E_inv")
    ax.grid(alpha=0.25)
    handles = [plt.Line2D([0], [0], color="tomato",  ls="--", lw=0.9,
                          label="±90° inversion threshold"),
               plt.Line2D([0], [0], color="darkred", ls="--", lw=0.9,
                          label="±180° fully inverted")]
    ax.legend(handles=handles, loc="upper right", fontsize=7)

    # ── Right panel: power spectrum of θ₂(t) on log-log axes ─────────
    ax = axes[1]
    N  = len(th2)
    if N > 1:
        dt   = float(np.median(np.diff(topo["time_s"])))
        freq = np.fft.rfftfreq(N, d=max(dt, 1e-6))
        spec = np.abs(np.fft.rfft(th2 - th2.mean())) ** 2
        mask = (freq > 0) & (spec > 0)
        if mask.any():
            ax.loglog(freq[mask], spec[mask],
                      color="royalblue", lw=0.6, alpha=0.85)
    K_str = f"{stat['K_chaos']:.2f}" if not np.isnan(stat["K_chaos"]) else "n/a"
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("power (deg²)")
    ax.set_title(
        f"power spectrum of θ₂(t)\n"
        f"(broadband = chaotic, sharp peaks = regular)   K = {K_str}")
    ax.grid(alpha=0.25, which="both")

    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    mirror_to_journal(out_path)
    plt.close(fig)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Chaos physics analysis: 0-1 test, spectral entropy, "
                    "inversion statistics.  Verdict: CHAOTIC / BORDERLINE / REGULAR.")
    p.add_argument("stem", metavar="<stem>",
                   help="config_description, e.g. th1_p180_th2_m179")
    p.add_argument("--no-plot", action="store_true",
                   help="skip writing measurements/<stem>/chaos_analyze.png")
    p.add_argument("--n-c", type=int, default=50, metavar="N",
                   help="random c values for the 0-1 test "
                        "(default 50; fewer = faster, more = more robust)")
    return p.parse_args()


def main():
    args     = parse_args()
    stem     = args.stem
    csv_path = os.path.join(MEAS_DIR, stem, "verification.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found")
        return 1

    try:
        data = load_free_swing(csv_path)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"  {stem}: {data['n_frames']} free_swing frames, "
          f"duration {data['time_s'][-1] - data['time_s'][0]:.1f} s")

    topo            = compute_topological(data)
    stat            = compute_statistical(topo, n_c=args.n_c)
    verdict, reasons = compute_verdict(topo, stat)

    print_card(stem, topo, stat, verdict, reasons)

    if not args.no_plot:
        out_png = figure_path("chaos_analyze", stem)
        make_plot(stem, topo, stat, out_png)
        print(f"  Plot: {out_png}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
