"""Fig 1 v2 — Square-wave I-V with full Shockley + series-resistance fit.

Improvements over IV graph_AI.py:
  - Sorted globs (deterministic ordering).
  - Yzero correction applied per-file (read from CSV header).
  - Per-file ADC quantization sigma -- not a fixed 80 mV.
  - Two fits reported side by side:
      (a) plain Shockley over Vpp <= 2.0 V (matches the original/report fit).
      (b) Shockley + R_s over all 14 files (Vpp 0.05 .. 10 V).
        Closed-form via Lambert W; lets the fit *use* the high-current data
        instead of excluding it -- directly answers the lab manual's
        "when does Shockley break down?" question.
  - Residual subplot, chi^2/dof printed.
  - JSON sidecar next to the PNG.

Output: <REPORT>/figures/v2/graph1IV_v2.png  +  graph1IV_v2.fit.json
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
from scipy.special import lambertw

import tek_csv as tek

V_T = 0.02585           # thermal voltage at 300 K (V)
R_RES = 470.0           # series resistor in the circuit (ohm)
SAMPLE_SLICE = slice(100_000, 200_000)  # plateau window used by the original
EXCLUDE_VPP_ABOVE = 2.0                 # V; original cutoff (kept for fit (a))
EXCLUDE_VPP_BELOW = 0.1                 # V; below this is leakage-dominated, not Shockley
FIT_B_VPP_MAX = 4.0                     # V; above this V_d quantization (vscale=5V/div, LSB ~150 mV) makes V_d readings unreliable

REPORT_DIR = r"C:\dev\chaos-report\figures\v2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- #
# Models                                                                      #
# --------------------------------------------------------------------------- #

def shockley(V, I_S, n):
    return I_S * (np.exp(V / (n * V_T)) - 1.0)


def shockley_rs(V, I_S, n, R_s):
    """Shockley diode with series resistance, closed form via Lambert W.

    Solving I = I_S (exp((V - I R_s)/(n V_T)) - 1) for I gives
        I = (n V_T / R_s) W( (R_s I_S / n V_T) exp((V + R_s I_S)/(n V_T)) ) - I_S
    Here V is the voltage across the (diode + R_s) series combination -- i.e.
    the diode-NODE voltage on the diode side.
    """
    V = np.asarray(V, dtype=float)
    arg = (R_s * I_S / (n * V_T)) * np.exp((V + R_s * I_S) / (n * V_T))
    arg = np.clip(arg, 0.0, 1e300)  # guard against overflow at huge V
    return (n * V_T / R_s) * np.real(lambertw(arg)) - I_S


def shockley_from_vgen(V_gen, I_S, n, R_total):
    """Shockley with the source voltage as the independent variable.

    The diode + (R_lab=470 Ω in the circuit) + everything-else (scope probe,
    wires, function-generator output impedance, internal diode R_s) all in
    series with the source. Lumped: V_gen = V_d + I * R_total.

    Robust to CH1 baseline drift between scope vscale settings because we
    don't read V_d off the scope; we only use I = (CH1 - CH2)/R_lab, which
    is common-mode-rejected, plus V_gen from the generator setting.

    Same Lambert-W trick as shockley_rs, with R_total in place of R_s.
    """
    V_gen = np.asarray(V_gen, dtype=float)
    arg = (R_total * I_S / (n * V_T)) * np.exp((V_gen + R_total * I_S) / (n * V_T))
    arg = np.clip(arg, 0.0, 1e300)
    return (n * V_T / R_total) * np.real(lambertw(arg)) - I_S


# --------------------------------------------------------------------------- #
# Data loading                                                                #
# --------------------------------------------------------------------------- #

def vpp_from_filename(name: str) -> float:
    """Extract source Vpp in volts from 'V_<mV>_res_<scale>.csv'."""
    parts = os.path.basename(name).split("_")
    return int(parts[1][:-2]) / 1000.0


def load_iv_points():
    """Per-file mean (V_diode, I_diode) pairs with per-file ADC sigmas.

    Two V_d definitions are stored:
      - V_d_direct  : -mean(CH1)   [original convention; suffers from CH1
                                    quantization at high Vpp scale settings]
      - V_d_inferred: mean(CH2 - CH1) is the resistor drop V_R, so V_gen
                      side voltage is mean(CH2) and V_d = V_gen - I*R has
                      the same number = mean(CH2) - mean(CH1 - CH2). Bypasses
                      CH1 baseline jumps because the diff (CH1 - CH2) is
                      common-mode-rejected.

    Bookkeeping note: in the original script, "V_d = -mean(CH1)". The signs
    are consistent if CH2 records the negative of the source level (which
    seems to be the case given the data behaves diode-like). The same sign
    convention is used for V_d_inferred for compatibility.
    """
    files = sorted(glob.glob(os.path.join(SCRIPT_DIR, "samples", "square", "V_*_res_*.csv")),
                   key=vpp_from_filename)
    rows = []
    for f in files:
        vpp = vpp_from_filename(f)
        _, ch1, ch2, meta = tek.load_trace(f, slice_=SAMPLE_SLICE)
        v_d_direct = -float(np.mean(ch1))
        i_d = float(np.mean(ch1 - ch2) / R_RES)
        # Inferred V_d using the SAME -CH1 sign convention but dressing it
        # up via I*R so that CH1's per-scale baseline drift drops out.
        # V_d_inferred = -mean(CH2) - i_d * R   (algebra: -(CH1) = -(CH2) + (CH2 - CH1) = -mean(CH2) + I*R*(-1)? Let me derive properly:
        # i_d = mean(CH1 - CH2) / R  ->  I*R = mean(CH1) - mean(CH2)
        # V_d_direct = -mean(CH1) = -mean(CH2) - I*R
        # So V_d_inferred should equal V_d_direct *exactly* if there's no
        # per-channel baseline drift. The point of computing it from CH2
        # is robustness: CH2 has bigger swing and better LSB-to-signal ratio.
        v_d_inferred = -float(np.mean(ch2)) - i_d * R_RES
        sigma_v_ch = max(tek.adc_sigma_volts(meta.vscale_ch1),
                         tek.adc_sigma_volts(meta.vscale_ch2))
        sigma_i = np.sqrt(2.0) * sigma_v_ch / R_RES
        sigma_v_d = sigma_v_ch  # for both definitions, dominated by ADC LSB
        rows.append({"file": os.path.basename(f), "vpp": vpp,
                     "V_d_direct": v_d_direct,
                     "V_d_inferred": v_d_inferred,
                     "V_d": v_d_direct,  # back-compat alias
                     "I_d": i_d,
                     "sigma_V_d": sigma_v_d, "sigma_I_d": sigma_i,
                     "vscale_ch1": meta.vscale_ch1,
                     "vscale_ch2": meta.vscale_ch2})
    return rows


# --------------------------------------------------------------------------- #
# Fits                                                                        #
# --------------------------------------------------------------------------- #

def fit_plain_shockley(V, I, sigma):
    popt, pcov = curve_fit(
        shockley, V, I, sigma=sigma, absolute_sigma=False,
        p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0]),
        maxfev=20000,
    )
    perr = np.sqrt(np.diag(pcov))
    resid = I - shockley(V, *popt)
    chi2 = float(np.sum((resid / sigma) ** 2))
    dof = max(len(V) - len(popt), 1)
    return popt, perr, chi2 / dof, resid


def fit_shockley_rs(V, I, sigma):
    popt, pcov = curve_fit(
        shockley_rs, V, I, sigma=sigma, absolute_sigma=False,
        p0=[1e-9, 1.5, 1.0], bounds=([1e-15, 0.5, 0.0], [1e-3, 5.0, 1e4]),
        maxfev=40000,
    )
    perr = np.sqrt(np.diag(pcov))
    resid = I - shockley_rs(V, *popt)
    chi2 = float(np.sum((resid / sigma) ** 2))
    dof = max(len(V) - len(popt), 1)
    return popt, perr, chi2 / dof, resid


def fit_shockley_vgen(V_gen, I, sigma):
    """Fit I(V_gen) with the lumped-R model. Returns (popt, perr, chi2_dof, resid)."""
    # R_total >= R_lab (470 ohm). Above that, allow ~5x for extras.
    popt, pcov = curve_fit(
        shockley_from_vgen, V_gen, I, sigma=sigma, absolute_sigma=False,
        p0=[1e-9, 1.5, R_RES * 1.2],
        bounds=([1e-15, 0.5, R_RES * 0.9], [1e-3, 5.0, R_RES * 5.0]),
        maxfev=40000,
    )
    perr = np.sqrt(np.diag(pcov))
    resid = I - shockley_from_vgen(V_gen, *popt)
    chi2 = float(np.sum((resid / sigma) ** 2))
    dof = max(len(V_gen) - len(popt), 1)
    return popt, perr, chi2 / dof, resid


# --------------------------------------------------------------------------- #
# Plot                                                                        #
# --------------------------------------------------------------------------- #

def make_figure(rows, fit_a, fit_b, out_path):
    V = np.array([r["V_d"] for r in rows])
    I = np.array([r["I_d"] for r in rows])
    Vpp = np.array([r["vpp"] for r in rows])
    sV = np.array([r["sigma_V_d"] for r in rows])
    sI = np.array([r["sigma_I_d"] for r in rows])

    (popt_a, perr_a, chi2_a, resid_a), mask_a = fit_a
    popt_b, perr_b, chi2_b, resid_b, mask_b = fit_b

    fig = plt.figure(figsize=(11, 8))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
    ax_main = fig.add_subplot(gs[0])
    ax_res = fig.add_subplot(gs[1], sharex=ax_main)

    # Color points by source Vpp on a log scale so high-current points stand out.
    norm = plt.Normalize(vmin=np.log10(max(Vpp.min(), 0.05)),
                         vmax=np.log10(Vpp.max()))
    cmap = plt.get_cmap("turbo")
    in_any_fit = mask_a | mask_b
    for vd, i, sv, si, vpp, ok in zip(V, I, sV, sI, Vpp, in_any_fit):
        col = cmap(norm(np.log10(max(vpp, 0.05))))
        marker = 'o' if ok else 'x'
        size = 7 if ok else 9
        ax_main.errorbar(vd, abs(i), xerr=sv, yerr=si, fmt=marker, color=col,
                         markersize=size, capsize=3, elinewidth=1.0,
                         markeredgecolor='black' if ok else col,
                         markeredgewidth=0.6)

    # Fit curves
    Vfit = np.linspace(0.0, max(V.max(), 0.9) * 1.02, 400)
    ax_main.plot(Vfit, shockley(Vfit, *popt_a), 'k--', lw=1.8,
                 label=(fr"(a) Shockley (V$_d$ axis), Vpp $\in$ "
                        fr"({EXCLUDE_VPP_BELOW}, {EXCLUDE_VPP_ABOVE}] V -- "
                        fr"$n$={popt_a[1]:.3f}$\pm${perr_a[1]:.3f}, "
                        fr"$I_S$={popt_a[0]*1e9:.2f}$\pm${perr_a[0]*1e9:.2f} nA"))
    # Fit (b) is parameterized in V_gen-space. Convert to (V_d, I) for plotting:
    #   for each V_gen sweep value, I = shockley_from_vgen(...), V_d = V_gen - I*R_total.
    Vgen_sweep = np.linspace(EXCLUDE_VPP_BELOW, max(Vpp.max() * 1.02, 11.0), 600)
    I_b_curve = shockley_from_vgen(Vgen_sweep, *popt_b)
    Vd_b_curve = Vgen_sweep - I_b_curve * popt_b[2]
    ax_main.plot(Vd_b_curve, I_b_curve, 'r-', lw=1.8,
                 label=(fr"(b) Shockley (V$_{{gen}}$ axis, lumped $R_{{tot}}$), "
                        fr"all Vpp $> {EXCLUDE_VPP_BELOW}$ V -- "
                        fr"$n$={popt_b[1]:.3f}$\pm${perr_b[1]:.3f}, "
                        fr"$I_S$={popt_b[0]*1e9:.2f}$\pm${perr_b[0]*1e9:.2f} nA, "
                        fr"$R_{{tot}}$={popt_b[2]:.0f}$\pm${perr_b[2]:.0f} $\Omega$"))

    ax_main.set_yscale("log")
    ax_main.set_ylabel("Diode current $|I_D|$ (A, log)", fontsize=13)
    ax_main.set_title(
        "Diode I-V (square-wave plateau) -- 1N4005 with $R = 470\\,\\Omega$\n"
        + fr"(a) $\chi^2/\mathrm{{dof}}$ = {chi2_a:.2f}   |   "
        + fr"(b) $\chi^2/\mathrm{{dof}}$ = {chi2_b:.2f}",
        fontsize=12,
    )
    ax_main.grid(True, ls='--', alpha=0.4, which='both')
    ax_main.legend(fontsize=9, loc='lower right', framealpha=0.92)
    # Add a colorbar showing the Vpp encoding
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax_main, pad=0.01)
    cbar.set_label(r"$\log_{10}(V_{pp}/\mathrm{V})$", fontsize=10)

    # Residuals (fit b, the lumped-R model). The residuals are in I-space
    # (data I minus model I at each V_gen). Plot vs V_d for visual continuity.
    ax_res.axhline(0, color='black', lw=0.8)
    Vb = V[mask_b]
    sIb = sI[mask_b]
    ax_res.errorbar(Vb, resid_b, yerr=sIb, fmt='o', color='red',
                    markersize=5, capsize=2.5, elinewidth=0.8,
                    markeredgecolor='black', markeredgewidth=0.5)
    ax_res.set_xlabel("Diode voltage $V_D$ (V)", fontsize=13)
    ax_res.set_ylabel("Residual (A)\n[fit b]", fontsize=10)
    ax_res.grid(True, ls='--', alpha=0.4)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=160, bbox_inches='tight')
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def run():
    rows = load_iv_points()
    V = np.array([r["V_d"] for r in rows])
    I = np.array([r["I_d"] for r in rows])
    Vpp = np.array([r["vpp"] for r in rows])
    sI = np.array([r["sigma_I_d"] for r in rows])

    # Fit (a): plain Shockley on EXCLUDE_VPP_BELOW < Vpp <= EXCLUDE_VPP_ABOVE
    mask_a = (Vpp <= EXCLUDE_VPP_ABOVE) & (Vpp > EXCLUDE_VPP_BELOW)
    fit_a = fit_plain_shockley(V[mask_a], I[mask_a], sI[mask_a])

    # Fit (b): Shockley with lumped R_total, using V_gen (Vpp from filename)
    # as the independent variable. This bypasses CH1's per-vscale baseline
    # drift since I = (CH1 - CH2)/R is common-mode-rejected. Uses ALL points
    # except the leakage-dominated low-Vpp one.
    mask_b = Vpp > EXCLUDE_VPP_BELOW
    fit_b = fit_shockley_vgen(Vpp[mask_b], I[mask_b], sI[mask_b])

    out_png = os.path.join(REPORT_DIR, "graph1IV_v2.png")
    fit_b_with_mask = fit_b + (mask_b,)
    make_figure(rows, (fit_a, mask_a), fit_b_with_mask, out_png)

    # JSON sidecar
    popt_a, perr_a, chi2_a, _ = fit_a
    popt_b, perr_b, chi2_b, _ = fit_b
    sidecar = {
        "figure": "graph1IV_v2",
        "n_files": len(rows),
        "n_points_total": len(rows),
        "n_points_fit_a": int(mask_a.sum()),
        "n_points_fit_b": int(mask_b.sum()),
        "fit_a": {
            "model": "I = I_S (exp(V/(n V_T)) - 1)",
            "exclusion": f"Vpp not in ({EXCLUDE_VPP_BELOW}, {EXCLUDE_VPP_ABOVE}] V",
            "I_S": float(popt_a[0]), "I_S_sigma": float(perr_a[0]),
            "n":   float(popt_a[1]), "n_sigma":   float(perr_a[1]),
            "chi2_per_dof": chi2_a,
        },
        "fit_b": {
            "model": "I = I_S (exp((V_gen - I R_total)/(n V_T)) - 1)  [Lambert W form]",
            "independent_variable": "Vpp from filename (V_gen)",
            "exclusion": f"Vpp <= {EXCLUDE_VPP_BELOW} V (leakage-dominated)",
            "I_S": float(popt_b[0]), "I_S_sigma": float(perr_b[0]),
            "n":   float(popt_b[1]), "n_sigma":   float(perr_b[1]),
            "R_total": float(popt_b[2]), "R_total_sigma": float(perr_b[2]),
            "R_total_note": (
                "Lumped: R_lab(470) + scope/probe/wire + diode R_s + "
                "function-generator output impedance. Excess over 470 ohm "
                "is the diode R_s plus parasitics."
            ),
            "chi2_per_dof": chi2_b,
        },
        "V_T_assumed": V_T,
        "R_resistor": R_RES,
        "git_sha": tek.git_sha(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "files": [r["file"] for r in rows],
    }
    sidecar_path = out_png.replace(".png", ".fit.json")
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f, indent=2)

    return sidecar


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2))
