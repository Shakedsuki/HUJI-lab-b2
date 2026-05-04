# -*- coding: utf-8 -*-
"""
Ultimate Diode I-V Sweeper (Error Clouds and Shockley Fit)
"""
import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import numpy as np
from scipy.optimize import curve_fit
from tqdm import tqdm

# --- Plot Aesthetics ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'legend.fontsize': 10,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

# --- Theoretical Model ---
def shockley_equation(V_D, I_S, n):
    V_T = 0.02569 # Thermal voltage at 25c
    return I_S * (np.exp(V_D / (n * V_T)) - 1)

p = r"samples\triangle"
file_list = glob.glob(p + '\\f_*_V_*_res_*.csv')

fig, ax = plt.subplots()
ax.set_title("Diode I-V Continuous Characteristic Curve")
ax.set_xlabel("Diode Voltage (V)")
ax.set_ylabel("Diode Current (A)")
ax.grid(True, linestyle='--', alpha=0.7)

for i, file_path in tqdm(enumerate(file_list[:1])):
    filename = os.path.basename(file_path)

    parts = filename.split('_')
    try:
        freq = parts[1]
        v_value = float(parts[3][:-1])
        res_value = parts[5].replace('.csv', '')
    except Exception:
        continue

    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
    window = 3000
    
    # 1. Calculate Rolling Means & Errors
    diode_V = df[4].rolling(window=window).mean()
    circuit_V = df[10].rolling(window=window).mean()
    
    raw_resistor_I = (df[4] - df[10]) / 470.0
    resistor_I_err = raw_resistor_I.rolling(window=window).std()
    resistor_I = raw_resistor_I.rolling(window=window).mean()
    
    # 2. Filter NaNs and convert to NumPy
    valid_idx = ~np.isnan(diode_V) & ~np.isnan(resistor_I)
    
    v_plot = (-diode_V[valid_idx]).to_numpy()
    i_plot = resistor_I[valid_idx].to_numpy()
    i_err = resistor_I_err[valid_idx].to_numpy()
    
    # 3. Detect Forward vs Reverse Sweep using the gradient
    smoothed_driving = circuit_V[valid_idx].to_numpy()
    dV = np.gradient(smoothed_driving)
    
    forward_mask = dV > 0
    reverse_mask = dV < 0

    color = cm.turbo(i / max(1, len(file_list) - 1))
    
    # --- Helper to plot ONLY the error cloud ---
    def plot_sweep(mask, sweep_name, alpha_cloud):
        v_sweep = v_plot[mask]
        i_sweep = i_plot[mask]
        err_sweep = i_err[mask]
        
        sort_idx = np.argsort(v_sweep)
        v_sorted = v_sweep[sort_idx]
        i_sorted = i_sweep[sort_idx]
        err_sorted = err_sweep[sort_idx]
        
        label_text = f'Data'
        
        # THE FIX: Plot only the filled region (the cloud) and assign the label to it
        ax.fill_between(v_sorted, 
                        i_sorted - err_sorted, 
                        i_sorted + err_sorted, 
                        color=color, alpha=alpha_cloud, edgecolor='none', label=label_text)

    # Plot the separated sweeps (I bumped the alphas slightly so the clouds are bolder)
    plot_sweep(forward_mask, "Forward Sweep", 0.4)
    # plot_sweep(reverse_mask, "Reverse Sweep", 0.2) 

    # --- 4. SHOCKLEY CURVE FIT ---
    v_fit_data = v_plot[forward_mask]
    i_fit_data = i_plot[forward_mask]

    sort_idx = np.argsort(v_fit_data)
    v_fit_data = v_fit_data[sort_idx]
    i_fit_data = i_fit_data[sort_idx]

    try:
        popt, pcov = curve_fit(shockley_equation, v_fit_data, i_fit_data, 
                               p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0]))
        I_S_opt, n_opt = popt
        
        v_fit_line = np.linspace(0, max(v_fit_data), 200)
        i_fit_line = shockley_equation(v_fit_line, I_S_opt, n_opt)
        
        ax.plot(v_fit_line, i_fit_line, 'k--', linewidth=2, zorder=3, 
                label=f'Shockley Fit')
    except Exception as e:
        print(f"Warning: Could not compute Shockley fit. Error: {e}")

# Fix legend formatting so the cloud colors show up as solid blocks
leg = ax.legend(fontsize=10)
for legobj in leg.legend_handles:
    legobj.set_alpha(1.0)

plt.tight_layout()
plt.show()