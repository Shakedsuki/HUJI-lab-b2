"""
friction_fit.py
---------------
Fit a friction model to a tracked clip's energy decay. Reads
measurements/<stem>/verification.csv (which has SG-smoothed ω in
omega1_deg_s and omega2_deg_s columns), computes mechanical energy
per frame using the rod-pendulum formula (Brief 9), and fits both:

  exponential decay:  E(t) = E0 * exp(-t/τ)        (Stokes / linear drag)
  power-law decay:    E(t) = E0 * (1 - t/T)**n     (general)

Reports both fits' parameters and R², picks the better one, and
writes measurements/<stem>/friction_fit.png with E(t) + fit
overlaid.

Usage:
    chaos friction-fit <stem>
    python scripts/analysis/friction_fit.py --stem <stem>
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

from scipy.optimize import curve_fit


ROOT     = r"C:\dev\chaos"
MEAS_DIR = os.path.join(ROOT, "measurements")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import figure_path, mirror_to_journal  # noqa: E402


# Rod-pendulum total mechanical energy. Mirrors verify_tracking's
# compute_frame_energy so the fit is consistent with the verdict
# layer.
def E_per_frame(th1_deg, th2_deg, om1_dps, om2_dps, L=0.35, g=9.8):
    th1_r = np.radians(th1_deg)
    th2_abs_r = np.radians(th1_deg + th2_deg)
    th2_rel_r = np.radians(th2_deg)
    w1_r = np.radians(om1_dps)
    w2_abs_r = np.radians(om1_dps + om2_dps)
    PE = (g * (3.0 * L / 2.0) * (1.0 - np.cos(th1_r))
        + g * (L / 2.0)       * (1.0 - np.cos(th2_abs_r)))
    KE = L**2 * (
          (2.0 / 3.0) * w1_r**2
        + 0.5         * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1.0 / 6.0) * w2_abs_r**2)
    return KE + PE


def smooth_envelope(t, e, window_s=0.5):
    """Return a moving-window mean of e over `window_s` seconds.
    The mean smooths out the per-frame oscillation between PE and KE
    that you see at twice the swing frequency, leaving the slow
    envelope you actually want to fit.

    Window is converted to a sample count from the median dt."""
    if len(t) < 3:
        return e
    dt = float(np.median(np.diff(t)))
    win = max(3, int(round(window_s / dt)) | 1)   # odd
    if win >= len(e):
        return np.full_like(e, e.mean())
    out = np.copy(e)
    half = win // 2
    cumsum = np.concatenate([[0.0], np.cumsum(e)])
    for i in range(len(e)):
        a = max(0, i - half)
        b = min(len(e), i + half + 1)
        out[i] = (cumsum[b] - cumsum[a]) / (b - a)
    return out


def fit_models(t, e):
    """Fit exponential and power-law decay to (t, e) where t starts
    at 0. Returns dict with params + R² for each."""
    out = {}

    # Exponential: E(t) = E0 * exp(-t/τ)
    def expo(t, E0, tau):
        return E0 * np.exp(-t / tau)

    try:
        p, _ = curve_fit(expo, t, e,
                         p0=(e[0], (t[-1] - t[0]) * 5),
                         bounds=([0, 1e-3], [np.inf, np.inf]))
        E_fit = expo(t, *p)
        ss_res = np.sum((e - E_fit) ** 2)
        ss_tot = np.sum((e - e.mean()) ** 2)
        out["exponential"] = {
            "E0":   float(p[0]),
            "tau":  float(p[1]),
            "r2":   float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
            "fit":  E_fit,
        }
    except Exception as ex:
        out["exponential"] = {"error": str(ex)}

    # Power-law: E(t) = E0 * (1 + t/τ)**(-n)  (always-positive, no
    # blow-up at t→T endpoint). Equivalent to a 1/t-style decay for
    # large n, exponential-like for small.
    def power(t, E0, tau, n):
        return E0 * (1 + t / tau) ** (-n)

    try:
        p, _ = curve_fit(power, t, e,
                         p0=(e[0], (t[-1] - t[0]) * 2, 1.0),
                         bounds=([0, 1e-3, 0.1], [np.inf, np.inf, 10]))
        E_fit = power(t, *p)
        ss_res = np.sum((e - E_fit) ** 2)
        ss_tot = np.sum((e - e.mean()) ** 2)
        out["power"] = {
            "E0":   float(p[0]),
            "tau":  float(p[1]),
            "n":    float(p[2]),
            "r2":   float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
            "fit":  E_fit,
        }
    except Exception as ex:
        out["power"] = {"error": str(ex)}

    return out


def parse_args():
    p = argparse.ArgumentParser(
        description="Fit a friction model to a clip's energy decay.")
    p.add_argument("--stem", required=True, metavar="<stem>")
    p.add_argument("--smooth-window", type=float, default=2.0,
                   metavar="SECONDS",
                   help="moving-mean window for the energy envelope "
                        "(default 2.0s; should be 1-2 swing periods to "
                        "fully average out PE↔KE oscillation)")
    p.add_argument("--no-plot", action="store_true",
                   help="skip writing friction_fit.png")
    return p.parse_args()


def main():
    args = parse_args()
    csv_path = os.path.join(MEAS_DIR, args.stem, "verification.csv")
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found")
        return 1

    df = pd.read_csv(csv_path)
    free = df[df["phase"] == "free_swing"].copy().reset_index(drop=True)
    if len(free) < 30:
        print(f"ERROR: only {len(free)} free_swing frames — too few to fit")
        return 1

    om1 = pd.to_numeric(free["omega1_deg_s"], errors="coerce")
    om2 = pd.to_numeric(free["omega2_deg_s"], errors="coerce")
    valid = (~om1.isna() & ~om2.isna()
             & ~free["theta1_deg"].isna() & ~free["theta2_deg"].isna())
    if valid.sum() < 30:
        print(f"ERROR: only {valid.sum()} valid frames after filtering NaN")
        return 1

    t  = free.loc[valid, "time_s"].values - free.loc[valid, "time_s"].iloc[0]
    e  = E_per_frame(free.loc[valid, "theta1_deg"].values,
                     free.loc[valid, "theta2_deg"].values,
                     om1[valid].values, om2[valid].values)
    e_smooth = smooth_envelope(t, e, window_s=args.smooth_window)

    fits = fit_models(t, e_smooth)
    best_model = max(
        (m for m in fits if "r2" in fits[m]),
        key=lambda m: fits[m]["r2"], default=None)

    print()
    print("=" * 72)
    print(f"  Friction fit — {args.stem}")
    print("=" * 72)
    print(f"  Free-swing duration: {t[-1]:.2f} s   ({len(t)} frames)")
    print(f"  E(t=0):  {e_smooth[0]:.4f}  J/kg")
    print(f"  E(t=T):  {e_smooth[-1]:.4f}  J/kg")
    print(f"  Total drift: {100*(e_smooth[-1] - e_smooth[0])/e_smooth[0]:+.1f}%")
    print()

    print("  Fit results:")
    print(f"  {'model':14s}  {'parameters':40s}  {'R²':>6s}")
    print("  " + "-" * 70)
    for name, fit in fits.items():
        if "error" in fit:
            print(f"  {name:14s}  ERROR: {fit['error'][:40]}")
            continue
        if name == "exponential":
            params = (f"E₀={fit['E0']:.3f}, τ={fit['tau']:.2f}s "
                      f"(half-life {fit['tau']*0.693:.2f}s)")
        elif name == "power":
            params = f"E₀={fit['E0']:.3f}, τ={fit['tau']:.2f}s, n={fit['n']:.2f}"
        else:
            params = str(fit)[:40]
        marker = " ←" if name == best_model else ""
        print(f"  {name:14s}  {params:40s}  {fit['r2']:>6.4f}{marker}")

    if best_model:
        print(f"\n  Best fit: {best_model}  (R² = {fits[best_model]['r2']:.4f})")
        if best_model == "exponential":
            tau = fits["exponential"]["tau"]
            print(f"\n  Physical interpretation:")
            print(f"  Energy half-life is {tau*0.693:.2f}s — energy halves "
                  f"every {tau*0.693:.1f}s.")
            print(f"  An exponential decay corresponds to a friction force "
                  f"linear in velocity (Stokes drag).")
            print(f"  Total fraction lost over run: "
                  f"{100*(1 - np.exp(-t[-1]/tau)):.1f}%")

    if not args.no_plot:
        out_png = figure_path("friction_fit", args.stem)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(t, e, lw=0.5, color="lightgray", label="raw E(t)")
        ax.plot(t, e_smooth, lw=1.0, color="black",
                label=f"envelope ({args.smooth_window}s window)")
        for name, fit in fits.items():
            if "fit" in fit:
                ls = "-" if name == best_model else "--"
                lw = 1.5 if name == best_model else 1.0
                ax.plot(t, fit["fit"], lw=lw, ls=ls,
                        label=f"{name} fit (R²={fit['r2']:.3f})")
        ax.set_xlabel("time (s, from release)")
        ax.set_ylabel("mechanical energy (J / kg per arm)")
        ax.set_title(f"{args.stem}  —  energy decay")
        ax.legend(loc="best")
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=140)
        mirror_to_journal(out_png)
        plt.close(fig)
        print(f"\n  Plot: {out_png}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
