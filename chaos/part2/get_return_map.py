# -*- coding: utf-8 -*-
"""
RLD Circuit Bifurcation Analysis
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import numpy as np
from tqdm import tqdm
from scipy.signal import find_peaks # ADDED FOR PEAK EXTRACTION

# --- Plot Aesthetics ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

p = r"samples"
file_list = glob.glob(os.path.join(p, '5700*.csv'))

# Lists to hold data for the bifurcation diagram
bifurcation_V = []
bifurcation_peaks = []

# Figure 1: Waveforms (Optional, kept for your verification)
plt.figure()
plt.title("Return maps for various driving voltages")
plt.xlabel("$V_n$")
plt.ylabel("$V_{n+1}$")

for i, file_path in enumerate(tqdm(file_list)):
    filename = os.path.basename(file_path)
    
    parts = filename.split('.')
    try:
        v_value = int(parts[0][:-2]) / 1000
    except ValueError:
        continue # Skip files that don't match the naming scheme

    # Read data
    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])

    # Smooth the data and DROP NaNs (find_peaks will crash if it sees NaNs)
    diode_V = df[4].rolling(window=100).mean().dropna()

    # --- 1. PEAK EXTRACTION ---
    # Adjust 'prominence' if it picks up micro-spikes. 
    # Prominence of 0.05 ensures it only grabs distinct structural peaks.
    peaks, _ = find_peaks(diode_V, prominence=0.05) 
    cutoff = np.median(np.diff(peaks))
    p=diode_V.iloc[[peaks[0]]].values
    i=1
    while i<len(peaks):
        if peaks[i]-peaks[i-1]>cutoff/2.0:
            if peaks[i]-peaks[i-1]>3.0*cutoff/2:
                p=np.concatenate((p,[np.min(diode_V)]))
            p=np.concatenate((p,diode_V.iloc[[peaks[i]]].values))
        i+=1
    
    plt.plot(p[:-1],p[1:],'.')
    
    # # Get the actual voltage values at those peak indices
    # peak_values = diode_V.iloc[peaks].values
    
    # # --- 2. TRANSIENT REMOVAL ---
    # # Discard the first 20% of peaks to let the chaotic circuit settle
    # if len(peak_values) > 0:
    #     transient_cutoff = int(0.2 * len(peak_values))
    #     stable_peaks = peak_values[transient_cutoff:]
        
    #     # Store for the bifurcation plot
    #     bifurcation_V.extend([v_value] * len(stable_peaks))
    #     bifurcation_peaks.extend(stable_peaks)

    # # Plot only a subset of the waveforms so it doesn't become a solid block of ink
    # if i % max(1, len(file_list) // 10) == 0:
    #     color = cm.turbo(i / max(1, len(file_list) - 1))
    #     # Plotting just the first 5000 points so you can actually see the waves
    #     plt.plot(diode_V.values[:5000], label=f'V: {v_value}', color=color, alpha=0.7)

plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=10)
plt.tight_layout()
plt.show()

# --- 3. BIFURCATION DIAGRAM PLOT ---
plt.figure()
plt.title("RLD Circuit Bifurcation Diagram")
plt.xlabel("Driving Voltage Amplitude (V)")
plt.ylabel("Peak Diode Voltage (V)")

# The secret to a good bifurcation diagram is using tiny markers (markersize=1)
# and high transparency (alpha=0.1) so density naturally creates darker regions.
plt.plot(bifurcation_V, bifurcation_peaks, '.', markersize=3, color='black', alpha=1)#0.1)

plt.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
plt.show()