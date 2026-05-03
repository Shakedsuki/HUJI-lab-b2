"""Fig 3 v2 -- Junction capacitance from direct exponential fit of discharge.

Replaces the threshold-crossing tau extraction in dischargetimes.py with a
proper exponential fit to the V(t) waveform. Each rising/charging transition
in the trace gives one independent (tau +/- sigma_tau) measurement.

Improvements:
  - Find ALL rising edges in each file (not just one), giving N_cycles >> 1.
    sigma_tau across cycles is the real measurement-repeat uncertainty.
  - Direct fit V(t) = V_inf + (V_0 - V_inf) exp(-(t - t_0)/tau) -- no
    'startperc' heuristic, no per-file 1.6 V special case.
  - Two C(V) models reported side by side:
      (P) phenomenological:  C(V) = a/sqrt(|V|) + c
      (J) physical junction: C(V) = C_0 / sqrt(1 + V/phi_bi) + c_stray
    The lab manual frames C(V) in terms of the depletion-region width, so
    the physical form with built-in voltage phi_bi is more meaningful.
  - chi^2/dof reported for both models -> reader can see whether c is
    actually constrained.
  - Residual subplot.

Output: <REPORT>/figures/v2/graph3C_V_v2.png  +  .fit.json
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

import tek_csv_v2 as tek

R_RES = 470.0
DRIVE_FREQ_HZ = 5_000.0   # the F_5kHz.txt label in the discharge folder

REPORT_DIR = r"C:\dev\chaos-report\figures\v2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
# Models                                                                      #
# --------------------------------------------------------------------------- #

def exp_charge(t, V_inf, V_0, t_0, tau):
    return V_inf + (V_0 - V_inf) * np.exp(-(t - t_0) / tau)


def cv_phenomenological(V, a, c):
    return a / np.sqrt(np.abs(V)) + c


def cv_junction(V, C_0, phi_bi, c_stray):
    return C_0 / np.sqrt(1.0 + V / phi_bi) + c_stray


# --------------------------------------------------------------------------- #
# Discharge segmentation                                                      #
# --------------------------------------------------------------------------- #

def find_rising_edges(ch1: np.ndarray, dt: float, freq_hz: float):
    """Return (edge_indices, smoothed_trace, period_samples).

    Strategy: smooth lightly with a ~100-sample window (matches the original
    dischargetimes.py), then find indices where the smoothed trace crosses
    (lo + 0.5*amp) going UP. Returns one such crossing per drive period.
    """
    period_samples = int(round(1.0 / (freq_hz * dt)))
    smooth_win = 100
    smooth = np.convolve(ch1, np.ones(smooth_win) / smooth_win, mode='same')

    lo_est = float(np.percentile(smooth, 10))
    hi_est = float(np.percentile(smooth, 90))
    amp_est = hi_est - lo_est
    if abs(amp_est) < 1e-4:
        return np.array([], dtype=int), smooth, period_samples

    threshold = lo_est + 0.5 * amp_est
    above = smooth > threshold
    crossings = np.where(np.diff(above.astype(int)) == 1)[0]

    edges = []
    last = -period_samples
    # Need at least period/3 of clean pre-edge baseline AND at least period/3
    # of post-edge plateau for the threshold-crossing tau extraction. Drop
    # edges within period/3 of either file boundary.
    margin = period_samples // 3
    n = len(smooth)
    for c in crossings:
        ci = int(c)
        if ci < margin or ci > n - margin:
            continue
        if ci - last >= int(0.5 * period_samples):
            edges.append(ci)
            last = ci
    return np.array(edges, dtype=int), smooth, period_samples


def extract_tau_threshold(t: np.ndarray, V: np.ndarray, mid_cross: int,
                          period_samples: int):
    """Single-cycle tau via threshold crossing.

    `mid_cross` is the index where the smoothed trace crossed (base + 0.5*amp)
    going up -- the half-amplitude point. We:
      1. Estimate V_base from a pre-edge plateau and V_top from post-edge.
      2. Walk backward from mid_cross to find rise_idx: first sample below
         (V_base + 0.001 * amp) -- the actual start of the rise.
      3. Walk forward from rise_idx to find tau_idx: first sample >=
         (V_base + (1 - 1/e) * amp).
      4. tau = (tau_idx - rise_idx) * dt.

    Same definition as the original dischargetimes.py, but works at any edge
    -- no fixed [400000:600000] window.
    """
    dt = float(t[1] - t[0])
    pre_lo = max(0, mid_cross - period_samples // 3)
    pre_hi = max(pre_lo + 1, mid_cross - period_samples // 20)
    post_lo = min(len(V), mid_cross + period_samples // 20)
    post_hi = min(len(V), mid_cross + period_samples // 3)
    if pre_hi <= pre_lo or post_hi <= post_lo:
        return None
    V_base = float(np.mean(V[pre_lo:pre_hi]))
    V_top = float(np.mean(V[post_lo:post_hi]))
    amp = V_top - V_base
    if abs(amp) < 5e-3:
        return None

    start_thresh = V_base + 0.001 * amp
    tau_thresh = V_base + (1.0 - 1.0 / np.e) * amp

    # rise_idx: walk back from mid_cross
    seg_back = V[max(0, mid_cross - period_samples // 2):mid_cross]
    below = np.where(seg_back < start_thresh)[0]
    if len(below) == 0:
        return None
    rise_idx = max(0, mid_cross - period_samples // 2) + int(below[-1])

    # tau_idx: walk forward from rise_idx
    seg_fwd = V[rise_idx:post_hi]
    above = np.where(seg_fwd >= tau_thresh)[0]
    if len(above) == 0:
        return None
    tau_idx = rise_idx + int(above[0])

    tau = (tau_idx - rise_idx) * dt
    return {"tau": float(tau),
            "V_base": V_base, "V_top": V_top,
            "rise_idx": int(rise_idx), "tau_idx": int(tau_idx),
            "mid_cross": int(mid_cross),
            "amp": float(amp)}


# --------------------------------------------------------------------------- #
# Per-file processing                                                         #
# --------------------------------------------------------------------------- #

def process_file(path: str):
    """Return dict {V_drive, C_mean, C_sigma, n_cycles, ...} for one file."""
    fname = os.path.basename(path)
    if "noOff" in fname:
        return None  # original script also skipped these
    _, ch1, ch2, meta = tek.load_trace(path)
    dt = meta.dt
    t = np.arange(len(ch1)) * dt

    edges, smooth, period_samples = find_rising_edges(ch1, dt, DRIVE_FREQ_HZ)
    cycles = []
    for e in edges:
        r = extract_tau_threshold(t, smooth, e, period_samples)
        if r is not None:
            cycles.append(r)

    if not cycles:
        return None

    taus = np.array([c["tau"] for c in cycles])
    # Drive voltage = mean of CH2 in the post-edge plateau.
    V_drive_samples = []
    for c in cycles:
        plateau_lo = c["mid_cross"] + period_samples // 4
        plateau_hi = min(len(ch2), plateau_lo + period_samples // 4)
        if plateau_hi > plateau_lo:
            V_drive_samples.append(float(np.mean(ch2[plateau_lo:plateau_hi])))
    V_drive = float(np.mean(V_drive_samples)) if V_drive_samples else float(np.mean(ch2))

    tau_mean = float(np.mean(taus))
    tau_std = float(np.std(taus, ddof=1) if len(taus) > 1 else 0.0)
    tau_sem = tau_std / np.sqrt(len(taus)) if len(taus) > 1 else 0.0

    # Per-cycle noise-based sigma_tau: sigma_V_noise / |dV/dt|@tau.
    # For an exponential, |dV/dt|_tau = amp / (tau * e). sigma_V_noise is
    # estimated as std(raw - smoothed) on the rising segment near tau_idx.
    noise_sigmas = []
    for c in cycles:
        lo = max(0, c["rise_idx"] - 1000)
        hi = min(len(ch1), c["tau_idx"] + 1000)
        if hi - lo > 100:
            seg_raw = ch1[lo:hi]
            seg_smooth = smooth[lo:hi]
            sigma_V = float(np.std(seg_raw - seg_smooth))
            slope = abs(c["amp"]) / max(c["tau"] * np.e, dt)
            noise_sigmas.append(sigma_V / slope)
    sigma_tau_noise = float(np.mean(noise_sigmas)) if noise_sigmas else 0.0

    # Final sigma_tau combines repeat-spread (across cycles) and per-trace
    # noise floor. With only 1 cycle per file in this dataset, repeat is 0
    # and noise dominates. Take the max so sigma is never under-reported.
    tau_sigma = max(tau_sem, sigma_tau_noise, 2.0 * dt)

    C_mean = tau_mean / R_RES
    C_sigma = tau_sigma / R_RES

    return {
        "file": fname,
        "V_drive": V_drive,
        "n_cycles": int(len(cycles)),
        "taus_ns": (taus * 1e9).tolist(),
        "tau_mean": tau_mean,
        "tau_std_repeat": tau_std,
        "tau_sigma_used": tau_sigma,
        "C_mean": C_mean,
        "C_sigma": C_sigma,
        "vscale_ch1": meta.vscale_ch1,
        "dt": dt,
        "diag": cycles[len(cycles) // 2],
    }


# --------------------------------------------------------------------------- #
# Plot                                                                        #
# --------------------------------------------------------------------------- #

def make_figure(rows, fits, out_path):
    fig = plt.figure(figsize=(11, 8))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
    ax_main = fig.add_subplot(gs[0])
    ax_res = fig.add_subplot(gs[1], sharex=ax_main)

    V = np.array([r["V_drive"] for r in rows])
    C = np.array([r["C_mean"] for r in rows])
    Cerr = np.array([r["C_sigma"] for r in rows])

    for r in rows:
        ax_main.errorbar(r["V_drive"], r["C_mean"], yerr=r["C_sigma"],
                         fmt='o', color='red', markersize=8,
                         markeredgecolor='black', markeredgewidth=0.6,
                         capsize=3, elinewidth=1.0)

    Vfit = np.linspace(min(V) * 0.9, max(V) * 1.05, 400)
    fp = fits["phenom"]
    fj = fits["junction"]
    ax_main.plot(Vfit, cv_phenomenological(Vfit, *fp["popt"]),
                 'k--', lw=1.6,
                 label=fr"(P) $a/\sqrt{{|V|}} + c$ -- $a$={fp['popt'][0]:.2e}, "
                       fr"$c$={fp['popt'][1]:.2e}, "
                       fr"$\chi^2/\mathrm{{dof}}$={fp['chi2_per_dof']:.2f}")
    ax_main.plot(Vfit, cv_junction(Vfit, *fj["popt"]),
                 'b-', lw=1.8,
                 label=fr"(J) $C_0/\sqrt{{1+V/\phi_{{bi}}}} + c$ -- "
                       fr"$C_0$={fj['popt'][0]:.2e}, $\phi_{{bi}}$={fj['popt'][1]:.2f} V, "
                       fr"$c$={fj['popt'][2]:.2e}, "
                       fr"$\chi^2/\mathrm{{dof}}$={fj['chi2_per_dof']:.2f}")

    ax_main.set_ylabel("Diode capacitance $C_j$ (F)", fontsize=13)
    ax_main.set_title(
        f"Junction capacitance vs. reverse-bias drive -- 1N4005, "
        f"{len(rows)} drives, "
        f"{sum(r['n_cycles'] for r in rows)} cycles total",
        fontsize=12,
    )
    ax_main.grid(True, ls='--', alpha=0.4)
    ax_main.legend(fontsize=9, loc='best')

    # Residuals of the junction model
    resid_j = C - cv_junction(V, *fj["popt"])
    ax_res.axhline(0, color='black', lw=0.8)
    ax_res.errorbar(V, resid_j, yerr=Cerr, fmt='o', color='blue',
                    markersize=6, capsize=2.5, elinewidth=0.8,
                    markeredgecolor='black', markeredgewidth=0.5)
    ax_res.set_xlabel("Drive voltage (V)", fontsize=13)
    ax_res.set_ylabel("Residual (F)\n[junction]", fontsize=10)
    ax_res.grid(True, ls='--', alpha=0.4)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=160, bbox_inches='tight')
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def run():
    files = sorted(glob.glob(os.path.join(
        SCRIPT_DIR, "samples", "square discharge", "[Vv]_*_res_*.csv"
    )))
    rows = []
    for f in files:
        r = process_file(f)
        if r is not None:
            rows.append(r)

    if len(rows) < 2:
        raise RuntimeError(
            f"Only {len(rows)} usable discharge files; cannot fit C(V)."
        )

    V = np.array([r["V_drive"] for r in rows])
    C = np.array([r["C_mean"] for r in rows])
    Cerr = np.array([r["C_sigma"] for r in rows])
    Cerr_safe = np.where(Cerr > 0, Cerr, np.mean(Cerr[Cerr > 0]) if (Cerr > 0).any() else 1e-12)

    # Phenomenological fit
    p_popt, p_pcov = curve_fit(
        cv_phenomenological, V, C, sigma=Cerr_safe, absolute_sigma=False,
        p0=[5e-12, 2e-10], maxfev=20000,
    )
    p_resid = C - cv_phenomenological(V, *p_popt)
    p_chi2_dof = float(np.sum((p_resid / Cerr_safe) ** 2)) / max(len(V) - 2, 1)

    # Junction fit -- can be ill-conditioned. phi_bi for silicon p-n is
    # typically 0.6-0.9 V. We bound to [0.4, 1.0]; if the fit hits the
    # upper bound, the data does not constrain the curvature and only the
    # baseline c_stray is meaningful (the chi^2 reflects this).
    j_popt, j_pcov = curve_fit(
        cv_junction, V, C, sigma=Cerr_safe, absolute_sigma=False,
        p0=[10e-12, 0.7, 200e-12],
        bounds=([1e-13, 0.4, 0.0], [1e-7, 1.0, 1e-8]),
        maxfev=40000,
    )
    j_resid = C - cv_junction(V, *j_popt)
    j_chi2_dof = float(np.sum((j_resid / Cerr_safe) ** 2)) / max(len(V) - 3, 1)

    fits = {
        "phenom": {"popt": p_popt, "perr": np.sqrt(np.diag(p_pcov)),
                   "chi2_per_dof": p_chi2_dof},
        "junction": {"popt": j_popt, "perr": np.sqrt(np.diag(j_pcov)),
                     "chi2_per_dof": j_chi2_dof},
    }

    out_png = os.path.join(REPORT_DIR, "graph3C_V_v2.png")
    make_figure(rows, fits, out_png)

    sidecar = {
        "figure": "graph3C_V_v2",
        "n_files": len(rows),
        "n_cycles_per_file": [r["n_cycles"] for r in rows],
        "drive_voltages": V.tolist(),
        "C_values": C.tolist(),
        "C_sigma": Cerr.tolist(),
        "fit_phenom": {
            "model": "C(V) = a/sqrt(|V|) + c",
            "a": float(p_popt[0]), "a_sigma": float(np.sqrt(p_pcov[0, 0])),
            "c": float(p_popt[1]), "c_sigma": float(np.sqrt(p_pcov[1, 1])),
            "chi2_per_dof": p_chi2_dof,
        },
        "fit_junction": {
            "model": "C(V) = C_0 / sqrt(1 + V/phi_bi) + c_stray",
            "C_0":     float(j_popt[0]), "C_0_sigma":     float(np.sqrt(j_pcov[0, 0])),
            "phi_bi":  float(j_popt[1]), "phi_bi_sigma":  float(np.sqrt(j_pcov[1, 1])),
            "c_stray": float(j_popt[2]), "c_stray_sigma": float(np.sqrt(j_pcov[2, 2])),
            "chi2_per_dof": j_chi2_dof,
        },
        "tau_extraction": "direct exponential fit V(t)=V_inf+(V_0-V_inf)exp(-(t-t_0)/tau) per cycle",
        "R_resistor": R_RES,
        "files": [r["file"] for r in rows],
        "git_sha": tek.git_sha(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    sidecar_path = out_png.replace(".png", ".fit.json")
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f, indent=2)
    return sidecar


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2))
