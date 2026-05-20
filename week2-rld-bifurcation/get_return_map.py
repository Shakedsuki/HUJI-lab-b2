# -*- coding: utf-8 -*-
"""
RLD Circuit Bifurcation Analysis (Return Maps with Colorbar)
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import matplotlib.colors as mcolors # ADDED FOR COLORBAR
import numpy as np
from tqdm import tqdm
from scipy.signal import find_peaks

# --- Plot Aesthetics ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

p = r"samples"
file_list = glob.glob(os.path.join(p, '*.csv'))

def extract_v_value(file_path):
    filename = os.path.basename(file_path)
    parts = filename.split('.')
    try:
        return int(parts[0][:-2]) / 1000
    except ValueError:
        return float('inf')

# Sort the list using the custom function
file_list = sorted(file_list, key=extract_v_value)

# --- NEW: Setup Colorbar Normalization ---
# Extract all valid voltages to find the minimum and maximum for the colorbar scale
v_values = [extract_v_value(f) for f in file_list if extract_v_value(f) != float('inf')]
min_v, max_v = min(v_values), max(v_values)

# Create a normalizer and set the colormap
norm = mcolors.Normalize(vmin=min_v, vmax=max_v)
cmap = cm.turbo

# Figure Setup
fig, ax = plt.subplots()
ax.set_title("Return maps for various driving voltages")
ax.set_xlabel("$V_n$")
ax.set_ylabel("$V_{n+1}$")

for j, file_path in enumerate(tqdm(file_list)):
    filename = os.path.basename(file_path)
    
    parts = filename.split('.')
    try:
        v_value = int(parts[0][:-2]) / 1000
    except ValueError:
        continue # Skip files that don't match the naming scheme

    # Read data
    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])

    # Smooth the data and DROP NaNs
    diode_V = df[4].rolling(window=100).mean().dropna()

    # --- 1. PEAK EXTRACTION ---
    peaks, _ = find_peaks(diode_V, prominence=0.05) 
    
    # Safety check: if the signal has no peaks, skip to prevent a crash
    if len(peaks) < 2:
        continue
        
    cutoff = np.median(np.diff(peaks))
    min_diode_v = np.min(diode_V) 
    
    # FIX 2: Convert Pandas Series to a raw NumPy array for lightning-fast indexing
    diode_v_array = diode_V.to_numpy()
    
    # FIX 3: Use a standard Python list to append items (np.concatenate is an O(N^2) memory killer)
    p_vals_list = [diode_v_array[peaks[0]]]
    
    for i in range(1, len(peaks)):
        peak_diff = peaks[i] - peaks[i-1]
        
        if peak_diff > cutoff / 2.0:
            if peak_diff > 3.0 * cutoff / 2.0:
                p_vals_list.append(min_diode_v)
                
            p_vals_list.append(diode_v_array[peaks[i]])

    # Convert back to a NumPy array exactly once at the very end
    p_vals = np.array(p_vals_list)
    
    # --- NEW: Assign Color by Voltage ---
    # Instead of mapping color by loop index 'j', we map it to the actual voltage value.
    # This prevents color stretching if your files aren't perfectly linearly spaced!
    color = cmap(norm(v_value))

    # Plotted with a slightly smaller marker and alpha for a cleaner scatter plot
    ax.plot(p_vals[:-1], p_vals[1:], '.', color=color, markersize=5)

# --- NEW: Add the Colorbar ---
# We use ScalarMappable to link the colormap and our min/max normalizer to the colorbar
sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
sm.set_array([]) # Required for older matplotlib versions
cbar = fig.colorbar(sm, ax=ax)
cbar.set_label('Driving Voltage Amplitude (V)')

plt.tight_layout()
plt.show()