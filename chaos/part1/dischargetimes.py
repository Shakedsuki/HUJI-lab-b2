# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 12:34:58 2026

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
from scipy.optimize import curve_fit

def inv_sqrt(x, a, c):
    return a / np.sqrt(x) + c

plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'legend.fontsize': 10,
    'lines.linewidth': 2,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

p=r"samples\square discharge"
file_list = glob.glob(p + '\\V_*_res_*.csv')
fig, ax = plt.subplots()
plt.title("Capacitance for Voltage")
ax.set_xlabel("Diode Voltage (V)")
ax.set_ylabel("Diode Capacitance (F)")
ax.grid(True, linestyle='--', alpha=0.7)

C=[]
V=[]
for i, file_path in enumerate(tqdm(file_list)):

    if "noOff" in file_path:
        continue
    
    filename = os.path.basename(file_path)

    parts = filename.split('_')
    v_value = float(parts[1][:-1])
    res_value = parts[3].replace('.csv', '')
    window=100
    df = pd.read_csv(file_path,header=None, usecols=[3, 4, 9, 10])
    
    diode_V=df[4][400000:600000]
    circuit_V=df[10][400000:600000]
    
    base=np.average(diode_V[:50000])
    top=np.average(diode_V[-50000:])
    v=np.average(circuit_V[-50000:])
    
    # --- ADDED: X-Axis Error (Standard deviation of the voltage noise) ---
    v_err = np.std(circuit_V[-50000:])
    
    diode_V=np.array(diode_V.rolling(window=window).mean())
    startperc=0.03 if "noOff" in file_path else 0.001
    if "1.6" in file_path:
        startperc=0.0045
    
    amp=top-base
    riseind=np.where(diode_V<=base+amp*startperc)[-1][-1]
    tauind=np.where(diode_V<=base+amp*(1-np.exp(-1)))[-1][-1]
    
    tau=(tauind-riseind)*4e-10
    capacitence=tau/470.0
    
    # --- ADDED: Y-Axis Error (Accounting for index timing uncertainty of +/- 2 samples) ---
    c_err = (0.5 * 4e-10) / 470.0 
    
    # --- CHANGED: Replaced plt.plot with ax.errorbar ---
    label_text = "Measured Data" if len(C) == 0 else "" # Only label once for the legend
    ax.errorbar(v, capacitence, xerr=v_err, yerr=c_err, 
                fmt='o', color="red", 
                markersize=1, markeredgecolor='black', capsize=4, label=label_text)
    
    C.append(capacitence)
    V.append(v)

# --- MOVED: Fit plotting before plt.show() so it actually appears ---
x=np.linspace(min(V),max(V), 200) # Added 200 to make the line smooth
try:
    popt, pcov = curve_fit(inv_sqrt,V,C,p0=[5e-10,5e-10])
    ax.plot(x, inv_sqrt(x, *popt), 'k--', label=f'Fit ($a/\\sqrt{{x}}+c$)')
except Exception as e:
    print(f"Fit failed: {e}")

ax.legend(fontsize=12)
plt.tight_layout()
plt.show()