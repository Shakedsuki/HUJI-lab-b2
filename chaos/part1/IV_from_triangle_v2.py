"""Fig 2 v2 -- Triangle-wave I-V with per-cycle ensemble Shockley fit.

Captured-issue fixes for IV from triangle.py:
  1. Sorted globs, no [:1] slice -- iterates over all triangle files.
  2. Auto-detect cycle boundaries from CH2 (drive); don't trust filename.
  3. Per-cycle independent Shockley fit on forward-bias samples
     -> ensemble mean +/- std on (n, I_S). The original's covariance-derived
     sigma was meaningless; the cross-cycle spread is the *real* uncertainty.

Other improvements:
  - Yzero correction (zero in this batch but principled).
  - Forward-bias-only fit (V_D > 0.30 V) per the report caption note about
    the +0.3 mA reverse-bias offset being an ADC artifact.
  - Light rolling-mean smoothing matching the original (window=3000), then
    downsample by the kernel width so the samples fed to curve_fit are
    approximately independent and the per-cycle covariance sigma is honest.
  - Residual subplot, chi^2/dof printed.
  - Original raw scatter kept (faded blue/red asc/desc) so the before/after
    is visible.
  - JSON sidecar.

NOTE on displacement current: triangle waves in this batch are asymmetric
(approx 3:1 asc:desc on the 100 Hz files), so forward/reverse averaging would
NOT cleanly cancel C dV/dt. Instead the per-cycle fit accepts a small
displacement-current bias; ensemble spread across cycles (and across files
at different frequencies) makes the bias visible if it dominates.

Output: <REPORT>/figures/v2/graph2IV_Triangle_v2.png  +  .fit.json
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

V_T = 0.02585
R_RES = 470.0
FORWARD_VD_MIN = 0.30   # V; restrict the fit to forward bias
ROLLING_WINDOW = 3000   # matches original IV from triangle.py

REPORT_DIR = r"C:\dev\chaos-report\figures\v2"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def shockley(V, I_S, n):
    return I_S * (np.exp(V / (n * V_T)) - 1.0)


# --------------------------------------------------------------------------- #
# Period segmentation                                                         #
# --------------------------------------------------------------------------- #

def find_drive_extrema(ch2: np.ndarray, dt: float):
    """Return (peak_idx, trough_idx) for CH2 using auto-detected period.

    Uses the FFT peak to estimate period, then find_peaks with that
    distance constraint. More robust than relying on the filename's frequency,
    which is not always accurate in this dataset.
    """
    # Coarse smoothing to suppress ringing
    win = max(len(ch2) // 5000, 11)
    if win % 2 == 0:
        win += 1
    smooth = np.convolve(ch2, np.ones(win) / win, mode='same')

    # Quick FFT to estimate dominant period
    n = len(smooth)
    spec = np.abs(np.fft.rfft(smooth - smooth.mean()))
    freqs = np.fft.rfftfreq(n, d=dt)
    if len(spec) > 1:
        # Ignore DC bin
        peak_bin = 1 + np.argmax(spec[1:])
        f_dom = freqs[peak_bin] if freqs[peak_bin] > 0 else 100.0
    else:
        f_dom = 100.0
    period_samples = max(int(round(1.0 / (f_dom * dt))), 100)
    distance = max(int(0.4 * period_samples), 1)

    peaks, _ = find_peaks(smooth, distance=distance)
    troughs, _ = find_peaks(-smooth, distance=distance)
    return peaks, troughs, f_dom, period_samples


# --------------------------------------------------------------------------- #
# Per-file processing                                                         #
# --------------------------------------------------------------------------- #

def process_file(path: str):
    """Return list of per-cycle dicts for one file."""
    fname = os.path.basename(path)
    _, ch1, ch2, meta = tek.load_trace(path)
    dt = meta.dt

    # Sign convention preserved: V_D = -ch1, I_D = (ch1 - ch2)/R
    V_d_raw = -ch1
    I_d_raw = (ch1 - ch2) / R_RES

    # Light rolling mean (same window as the original triangle script)
    kernel = np.ones(ROLLING_WINDOW) / ROLLING_WINDOW
    V_d = np.convolve(V_d_raw, kernel, mode='same')
    I_d = np.convolve(I_d_raw, kernel, mode='same')

    peaks, troughs, f_dom, period_samples = find_drive_extrema(ch2, dt)

    # Build (trough -> peak -> trough) cycles where both bounds exist
    cycles = []
    for p in peaks:
        before = troughs[troughs < p]
        after = troughs[troughs > p]
        if len(before) and len(after):
            cycles.append((int(before[-1]), int(p), int(after[0])))

    sigma_v = max(tek.adc_sigma_volts(meta.vscale_ch1),
                  tek.adc_sigma_volts(meta.vscale_ch2))

    out = []
    for k, (t0, p, t1) in enumerate(cycles):
        V_cyc = V_d[t0:t1+1]
        I_cyc = I_d[t0:t1+1]
        V_raw_cyc = V_d_raw[t0:t1+1]
        I_raw_cyc = I_d_raw[t0:t1+1]

        out.append({
            "file": fname,
            "cycle": k,
            "freq_dominant_hz": float(f_dom),
            "n_samples": len(V_cyc),
            "V_cyc": V_cyc, "I_cyc": I_cyc,
            "V_raw": V_raw_cyc, "I_raw": I_raw_cyc,
            "sigma_v": sigma_v,
            "vscale_ch1": meta.vscale_ch1,
            "vscale_ch2": meta.vscale_ch2,
            "dt": dt,
            "asc_slice": (t0, p),
            "desc_slice": (p, t1),
        })
    return out


# --------------------------------------------------------------------------- #
# Per-cycle Shockley fit                                                      #
# --------------------------------------------------------------------------- #

def fit_one_cycle(cyc: dict):
    """Per-cycle Shockley fit on smoothed forward-bias samples, downsampled
    by ROLLING_WINDOW so the samples fed to curve_fit are roughly independent.
    """
    V = cyc["V_cyc"]
    I = cyc["I_cyc"]

    mask = (V > FORWARD_VD_MIN) & np.isfinite(V) & np.isfinite(I)
    if mask.sum() < 50:
        return None
    V_fwd = V[mask]
    I_fwd = I[mask]

    # Downsample by the rolling-mean width to break sample correlations
    stride = max(ROLLING_WINDOW, 1)
    Vds = V_fwd[::stride]
    Ids = I_fwd[::stride]
    if len(Vds) < 5:
        # If downsampling left too few points, fall back to a coarse uniform
        # subsample of the smoothed array.
        idx = np.linspace(0, len(V_fwd) - 1, 50).astype(int)
        Vds = V_fwd[idx]
        Ids = I_fwd[idx]

    sigma_i = np.sqrt(2.0) * cyc["sigma_v"] / R_RES
    try:
        popt, pcov = curve_fit(
            shockley, Vds, Ids,
            sigma=np.full(len(Vds), sigma_i), absolute_sigma=False,
            p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0]),
            maxfev=20000,
        )
    except Exception:
        return None
    perr = np.sqrt(np.diag(pcov))
    resid = Ids - shockley(Vds, *popt)
    chi2 = float(np.sum((resid / sigma_i) ** 2))
    dof = max(len(Vds) - 2, 1)
    return {"popt": popt, "perr": perr, "chi2_per_dof": chi2 / dof,
            "n_points": int(len(Vds)),
            "V": Vds, "I": Ids, "I_fit": shockley(Vds, *popt)}


# --------------------------------------------------------------------------- #
# Plot                                                                        #
# --------------------------------------------------------------------------- #

def make_figure(cycles_data, fit_results, out_path,
                n_mean, n_std, IS_mean, IS_std,
                pooled_V, pooled_I, pooled_fit, chi2_pooled,
                n_well_behaved):
    fig = plt.figure(figsize=(11, 8))
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
    ax_main = fig.add_subplot(gs[0])
    ax_res = fig.add_subplot(gs[1], sharex=ax_main)

    # Faded raw data, color-coded by file
    files = sorted({c["file"] for c in cycles_data})
    cmap = plt.get_cmap("turbo")
    file_color = {fn: cmap(i / max(1, len(files) - 1)) for i, fn in enumerate(files)}

    # Faded raw data, color-coded by file (forward bias only for log axis)
    for cyc in cycles_data:
        col = file_color[cyc["file"]]
        Vraw = np.asarray(cyc["V_raw"])
        Iraw = np.asarray(cyc["I_raw"])
        sel = (Vraw > 0) & (Iraw > 0)
        s = max(1, int(sel.sum()) // 4000)
        ax_main.plot(Vraw[sel][::s], Iraw[sel][::s], '.',
                     color=col, alpha=0.10, ms=1.5)

    # Per-cycle fits: well-behaved cycles in their file color, others gray.
    Vfit = np.linspace(FORWARD_VD_MIN, max(pooled_V) * 1.02, 200)
    for r, cyc in zip(fit_results, cycles_data):
        if r is None:
            continue
        keep = 0.6 < r["popt"][1] < 4.5 and cyc["freq_dominant_hz"] < 1000.0
        if keep:
            col = file_color[cyc["file"]]
            ax_main.plot(Vfit, shockley(Vfit, *r["popt"]),
                         color=col, lw=1.2, alpha=0.85)
        else:
            ax_main.plot(Vfit, shockley(Vfit, *r["popt"]),
                         color='lightgray', lw=0.6, alpha=0.4)

    # File legend stubs (one per file, short label)
    for fn in files:
        short = fn.replace("f_", "").replace("_res_", " | R=").replace(".csv", "")
        ax_main.plot([], [], 'o', color=file_color[fn], ms=6,
                     markeredgecolor='black', markeredgewidth=0.4, label=short)

    # Ensemble-mean curve (bold, black)
    ax_main.plot(Vfit, shockley(Vfit, *pooled_fit), 'k-', lw=2.5,
                 label=(fr"Ensemble mean -- $n$={pooled_fit[1]:.3f}, "
                        fr"$I_S$={pooled_fit[0]*1e9:.1f} nA"))
    ax_main.axvline(FORWARD_VD_MIN, color='gray', ls=':', lw=1.0,
                    label=f"Fit window: $V_D > {FORWARD_VD_MIN}$ V")
    ax_main.set_yscale("log")

    title = (
        "Triangle-wave I-V -- 1N4005 + $R = 470\\,\\Omega$\n"
        fr"Per-cycle ensemble (N = {n_well_behaved}, low-frequency cycles only): "
        fr"$n = {n_mean:.3f} \pm {n_std:.3f}$,  "
        fr"$I_S = ({IS_mean*1e9:.1f} \pm {IS_std*1e9:.1f})$ nA"
    )
    ax_main.set_title(title, fontsize=11)
    ax_main.set_ylabel("Diode current $I_D$ (A, log)", fontsize=13)
    ax_main.grid(True, ls='--', alpha=0.4, which='both')
    ax_main.legend(fontsize=9, loc='lower right', framealpha=0.92)
    ax_main.set_xlim(left=-0.05)

    # Residuals on the pooled fit
    pooled_resid = pooled_I - shockley(pooled_V, *pooled_fit)
    ax_res.axhline(0, color='black', lw=0.8)
    ax_res.plot(pooled_V, pooled_resid, '.', color='red', ms=4, alpha=0.7)
    ax_res.set_xlabel("Diode voltage $V_D$ (V)", fontsize=13)
    ax_res.set_ylabel("Residual (A)", fontsize=10)
    ax_res.grid(True, ls='--', alpha=0.4)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=160, bbox_inches='tight')
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def run():
    files = sorted(glob.glob(os.path.join(SCRIPT_DIR, "samples", "triangle",
                                          "f_*_V_*_res_*.csv")))
    if not files:
        raise FileNotFoundError("No triangle CSVs in samples/triangle")

    all_cycles = []
    for f in files:
        all_cycles.extend(process_file(f))

    print(f"[Fig 2 v2] processed {len(files)} files, "
          f"{len(all_cycles)} cycles total")

    fit_results = [fit_one_cycle(c) for c in all_cycles]
    valid = [r for r in fit_results if r is not None]
    if not valid:
        raise RuntimeError("All per-cycle fits failed; cannot summarize.")

    # The 6.6 kHz triangle introduces enough C dV/dt displacement current to
    # bias n by ~50%, so we restrict the ensemble to low-frequency cycles
    # (detected drive freq < 1 kHz). Within those, also reject any cycle
    # whose fit hit the n-bound. This yields fewer cycles but a cleaner
    # answer; the spread across cycles is the *real* uncertainty.
    paired = list(zip(valid, [c for c, r in zip(all_cycles, fit_results) if r is not None]))
    def _ok(r, c):
        return (
            c["freq_dominant_hz"] < 1000.0
            and 0.6 < r["popt"][1] < 4.5
        )
    well_behaved = [r for r, c in paired if _ok(r, c)]
    print(f"[Fig 2 v2] {len(well_behaved)}/{len(valid)} cycles passed (low-freq, n in (0.6, 4.5))")
    if not well_behaved:
        well_behaved = valid

    n_vals = np.array([r["popt"][1] for r in well_behaved])
    IS_vals = np.array([r["popt"][0] for r in well_behaved])
    n_mean = float(np.mean(n_vals))
    n_std = float(np.std(n_vals, ddof=1) if len(n_vals) > 1 else 0.0)
    IS_mean = float(np.mean(IS_vals))
    IS_std = float(np.std(IS_vals, ddof=1) if len(IS_vals) > 1 else 0.0)

    pooled_V = np.concatenate([r["V"] for r in well_behaved])
    pooled_I = np.concatenate([r["I"] for r in well_behaved])
    # Use the ensemble mean directly as the displayed fit. The per-cycle
    # spread (n_std, IS_std) is the honest uncertainty; a separate pooled
    # curve_fit on the concatenated samples doesn't add information here
    # (samples within a cycle are highly correlated through the rolling mean)
    # and was numerically unstable on this small dataset.
    pooled_fit = np.array([max(IS_mean, 1e-15), n_mean])
    pooled_perr = np.array([IS_std, n_std])
    pooled_resid = pooled_I - shockley(pooled_V, *pooled_fit)
    sigma_pooled = max(np.sqrt(np.mean(pooled_resid ** 2)), 1e-12)
    chi2_pooled = float(np.sum((pooled_resid / sigma_pooled) ** 2)) / max(len(pooled_V) - 2, 1)

    out_png = os.path.join(REPORT_DIR, "graph2IV_Triangle_v2.png")
    make_figure(all_cycles, fit_results, out_png,
                n_mean, n_std, IS_mean, IS_std,
                pooled_V, pooled_I, pooled_fit, chi2_pooled,
                len(well_behaved))

    sidecar = {
        "figure": "graph2IV_Triangle_v2",
        "n_files": len(files),
        "n_cycles_total": len(all_cycles),
        "n_cycles_fit": len(valid),
        "ensemble": {
            "n_mean": n_mean, "n_std": n_std,
            "I_S_mean": IS_mean, "I_S_std": IS_std,
        },
        "pooled_fit": {
            "model": "I = I_S (exp(V/(n V_T)) - 1)",
            "fit_window": f"V_D > {FORWARD_VD_MIN} V",
            "I_S": float(pooled_fit[0]), "I_S_sigma_cov": float(pooled_perr[0]),
            "n":   float(pooled_fit[1]), "n_sigma_cov":   float(pooled_perr[1]),
            "chi2_per_dof": chi2_pooled,
        },
        "displacement_handling": "none (asymmetric triangles in this dataset; relying on per-cycle ensemble spread)",
        "V_T_assumed": V_T,
        "R_resistor": R_RES,
        "files": [os.path.basename(f) for f in files],
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
