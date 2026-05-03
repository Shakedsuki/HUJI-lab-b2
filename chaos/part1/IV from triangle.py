# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 11:56:00 2026

@author: cohen
"""
import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import numpy as np
import itertools
from tqdm import tqdm
from scipy.optimize import curve_fit # ADDED FOR FIT

# ADDED FOR FIT: Shockley Equation definition
def shockley(V_D, I_S, n):
    V_T = 0.02585
    return I_S * (np.exp(V_D / (n * V_T)) - 1)

plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'legend.fontsize': 10,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

p=r"samples\triangle"
file_list = glob.glob(p + '\\f_*_V_*_res_*.csv')

fig, ax = plt.subplots()
ax.set_title("Diode I-V Characteristic Curve From Triangle Wave Voltage")
ax.set_xlabel("Diode Voltage (V)")
ax.set_ylabel("Diode Current (A)")
ax.grid(True, linestyle='--', alpha=0.7)


for i, file_path in tqdm(enumerate(file_list[:1])):
    filename = os.path.basename(file_path)

    parts = filename.split('_')
    freq=parts[1]
    v_value = float(parts[3][:-1])
    res_value = parts[5].replace('.csv', '')

    df = pd.read_csv(file_path,header=None, usecols=[3, 4, 9, 10])
    window=3000
    
    diode_V=df[4].rolling(window=window).mean()
    resistor_V=diode_V-df[10].rolling(window=window).mean()
    resistor_I=resistor_V/470.0
    
    # I.append(np.average(resistor_I))
    # V.append(-np.average(diode_V))
    # plt.figure(figsize=(10, 6))
    # plt.title(filename)
    plt.plot(-diode_V,resistor_I, label="Raw Data") # Added label for the legend
    
    # === ADDED FOR FIT: Start ===
    # curve_fit will crash if it sees NaN values from the rolling window, so we drop them first
    valid_mask = ~diode_V.isna() & ~resistor_I.isna()
    v_valid = -diode_V[valid_mask]
    i_valid = resistor_I[valid_mask]
    
    try:
        # Perform the mathematical fit
        popt, _ = curve_fit(shockley, v_valid, i_valid, p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0]))
        
        # Generate a clean, smooth line for plotting the theoretical curve
        v_fit = np.linspace(v_valid.min(), v_valid.max(), 200)
        i_fit = shockley(v_fit, *popt)
        
        # Plot the fit as a dashed black line
        plt.plot(v_fit, i_fit, 'k--', linewidth=2, label=f'Shockley Fit')
    except Exception as e:
        print(f"Fit failed for {filename}: {e}")
    # === ADDED FOR FIT: End ===
    
    # color = cm.turbo(i / max(1, len(file_list) - 1))
    # #plt.plot([V[-1]],[I[-1]],'.', label=f'V: {v_value/1000} | Res: {res_value}',color=color,markersize=15)
    # plt.plot(resistor_I, label=f'f: {freq} | V: {v_value/1000} | Res: {res_value}',color=color)
    # plt.plot(diode_V, label=f'V: {v_value/1000} | Res: {res_value}')
    # label_text = f'  f: {freq} | V: {v_value/1000} | Res: {res_value}'
    # plt.text(V[-1], I[-1], label_text, color=color, fontsize=10, verticalalignment='center')
#
# plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=12)
# plt.tight_layout()
plt.legend( fontsize=12)
plt.show()