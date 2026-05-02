# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 12:34:58 2026

@author: cohen
"""

import glob
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tqdm import tqdm
from scipy.optimize import curve_fit


def inv_sqrt(x, a, c):
    return a / np.sqrt(x) + c


R = 470.0
DT = 4e-10  # sample interval (s)

p = r"samples\square discharge"
file_list = glob.glob(p + "\\V_*_res_*.csv") + glob.glob(p + "\\v_*_res_*.csv")
file_list = sorted(set(file_list))

plt.figure(figsize=(10, 6))
plt.title("Capacitance vs. Voltage")

C, V, C_err = [], [], []

for i, file_path in enumerate(tqdm(file_list)):
    if "noOff" in file_path:
        continue

    filename = os.path.basename(file_path)
    parts = filename.split("_")

    window = 100
    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
    diode_V = df[4][400000:600000]
    circuit_V = df[10][400000:600000]
    base = np.average(diode_V[:50000])
    top = np.average(diode_V[-50000:])
    v = np.average(circuit_V[-50000:])

    diode_V_raw = np.array(diode_V)
    diode_V_smooth = np.array(diode_V.rolling(window=window).mean())

    startperc = 0.03 if "noOff" in file_path else 0.001
    if "1.6" in file_path:
        startperc = 0.0045

    amp = top - base
    try:
        riseind = np.where(diode_V_smooth <= base + amp * startperc)[-1][-1]
        tauind = np.where(diode_V_smooth <= base + amp * (1 - np.exp(-1)))[-1][-1]
    except IndexError:
        continue

    tau = (tauind - riseind) * DT
    capacitance = tau / R

    # --- Uncertainty propagation: sigma_C = sigma_tau / R --------------------
    # Estimate sigma_tau from the noise in the smoothed discharge trace.
    # sigma_tau ~ sigma_V / |dV/dt| evaluated near the tau-crossing.
    # For an exponential V(t) = base + amp*(1 - exp(-t/tau)), dV/dt|_tau = amp/(tau*e).
    seg_lo = max(riseind, tauind - 5000)
    seg_hi = min(len(diode_V_raw), tauind + 5000)
    seg_raw = diode_V_raw[seg_lo:seg_hi]
    seg_smooth = diode_V_smooth[seg_lo:seg_hi]
    valid = ~np.isnan(seg_smooth)
    sigma_V = np.std(seg_raw[valid] - seg_smooth[valid]) if valid.any() else 0.0

    slope = abs(amp) / (tau * np.e) if tau > 0 else np.inf
    sigma_tau = sigma_V / slope if slope > 0 else 0.0
    sigma_C = sigma_tau / R

    plt.errorbar(v, capacitance, yerr=sigma_C, fmt='o', color="red",
                 markersize=8, markeredgecolor='black',
                 capsize=3, elinewidth=1.2, ecolor='black')
    C.append(capacitance)
    V.append(v)
    C_err.append(sigma_C)

x = np.linspace(min(V), max(V), 200)
popt, pcov = curve_fit(inv_sqrt, V, C, p0=[5e-10, 5e-10],
                       sigma=C_err if all(e > 0 for e in C_err) else None,
                       absolute_sigma=False)
plt.plot(x, inv_sqrt(x, *popt), 'k--', linewidth=2,
         label=fr'$a/\sqrt{{|V|}} + c$  (a={popt[0]:.2e}, c={popt[1]:.2e})')

plt.xlabel("Voltage (V)")
plt.ylabel("Diode Capacitance (F)")
plt.legend(fontsize=12)
plt.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()

OUT = r"C:\dev\chaos-report\figures\graph3C_V.png"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
plt.savefig(OUT, dpi=150)
print(f"Saved figure to {OUT}")
print(f"Fit: a = {popt[0]:.4e} F*sqrt(V), c = {popt[1]:.4e} F")
