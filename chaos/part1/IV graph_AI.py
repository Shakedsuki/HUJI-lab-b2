# -*- coding: utf-8 -*-
"""
Updated Diode I-V Curve Plotter with Error Analysis & Shockley Fit
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import numpy as np
import itertools
from scipy.optimize import curve_fit
from tqdm import tqdm

# --- Professional Plot Aesthetics ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'legend.fontsize': 10,
    'lines.linewidth': 2,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

# --- Shockley Diode Equation ---
# V_T is the thermal voltage (approx 25.85 mV at 300K)
def shockley_equation(V_D, I_S, n):
    V_T = 0.02585 
    return I_S * (np.exp(V_D / (n * V_T)) - 1)

p = r"samples\square"
file_list = glob.glob(os.path.join(p, 'V_*_res_*.csv'))

# --- NEW: Sort the files numerically by voltage ---
def extract_v_value(file_path):
    filename = os.path.basename(file_path)
    parts = filename.split('_')
    try:
        # Extract the number just like in your loop
        return int(parts[1][:-2]) / 1000
    except Exception:
        return float('inf') # Put files that don't match the naming scheme at the end

# Sort the list using the custom function
file_list = sorted(file_list, key=extract_v_value)
# --------------------------------------------------


fig, ax = plt.subplots()
ax.set_title("Diode I-V Characteristic Curve")
ax.set_xlabel("Diode Voltage (V)")
ax.set_ylabel("Diode Current (A)")
ax.grid(True, linestyle='--', alpha=0.7)

V_means = []
I_means = []
Source_Vs = [] # Track source voltages to filter corrupted data later

for i, file_path in tqdm(enumerate(file_list)):
    filename = os.path.basename(file_path)
    
    parts = filename.split('_')
    try:
        v_value = int(parts[1][:-2]) / 1000
        res_value = parts[3].replace('.csv', '')
    except Exception:
        continue 
    
    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
    
    samples_range_list = list(itertools.chain(range(100000, 200000)))#, range(380000, 480000), range(660000, 760000)))
    
    mask = df.index.isin(samples_range_list)
    diode_V = df.loc[mask, 4]
    circuit_V = df.loc[mask, 10]
    
    resistor_V = diode_V - circuit_V
    resistor_I = resistor_V / 470.0
    
    v_mean = -np.average(diode_V)
    i_mean = np.average(resistor_I)
    
    v_err = np.std(diode_V)
    i_err = np.std(resistor_I)
    
    V_means.append(v_mean)
    I_means.append(i_mean)
    Source_Vs.append(v_value)
    
    color = cm.turbo(i / max(1, len(file_list) - 1))
    
    # Plot data points with error bars (zorder=2 keeps them on top of the fit line)
    ax.errorbar(v_mean, i_mean, 
                xerr=v_err, yerr=i_err, 
                fmt='o', color=color, markersize=1,
                capsize=4, elinewidth=1.5, markeredgewidth=1.5, zorder=2,
                label=f'Source vpp: {v_value}V')
    
    # ax.annotate(f'{v_value}V', (v_mean, i_mean), 
    #             textcoords="offset points", xytext=(10, -5), 
    #             color=color, fontsize=9, verticalalignment='center')

# --- Perform Shockley Curve Fitting ---
# Only use data points where the oscilloscope didn't suffer from massive offset errors (Source V <= 3.0V)
valid_V_D = [v for idx, v in enumerate(V_means) if Source_Vs[idx] <= 2.0]
valid_I_D = [i for idx, i in enumerate(I_means) if Source_Vs[idx] <= 2.0]

try:
    # p0 = initial guesses (I_S = 1nA, n = 1.5). Bounds prevent wild mathematical divergence.
    popt, pcov = curve_fit(shockley_equation, valid_V_D, valid_I_D, 
                           p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0]))
    I_S_opt, n_opt = popt
    
    # Generate a smooth array of X values to draw the fitted line
    v_fit = np.linspace(0, max(valid_V_D) + 0.02, 200)
    i_fit = shockley_equation(v_fit, I_S_opt, n_opt)
    
    # Plot the mathematical fit as a smooth dashed line behind the data points
    ax.plot(v_fit, i_fit, 'k--', alpha=0.6, linewidth=2, zorder=1, 
            label=f'Shockley Fit')#\n$n$ = {n_opt:.2f}\n$I_S$ = {I_S_opt:.2e} A')
except Exception as e:
    print(f"Warning: Could not compute Shockley curve fit. Error: {e}")

# Place legend outside the plot area
ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', borderaxespad=0.)

plt.tight_layout()
plt.show()