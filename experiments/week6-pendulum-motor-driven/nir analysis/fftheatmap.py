# -*- coding: utf-8 -*-
"""
Created on Tue May 26 15:45:07 2026

@author: cohen
"""

# -*- coding: utf-8 -*-
"""
Metric 6: Spectral Bifurcation Diagram (FFT Heatmap)
Maps the route to chaos by plotting FFT amplitude as a color map across driving frequencies.
"""

import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from scipy.interpolate import interp1d

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"

COL_TIME = "time_s"
COL_THETA2 = "theta2_deg"

TIME_WINDOW = 60.0     # Only analyze the last 20 seconds to avoid startup noise
MAX_FFT_FREQ = 3.0     # The maximum frequency to display on the Y-axis

# =============================================================================
# 2. DATA LOADING
# =============================================================================
def load_data():
    print("Scanning directories for CSV files...")
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    data_dict = {}
    for file_path in csv_files:
        folder_name = os.path.basename(os.path.dirname(file_path))
        match_freq = re.search(r'(\d+(?:\.\d+)?)\s*Hz', folder_name, re.IGNORECASE)
        if not match_freq: continue
        
        try:
            df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA2])
            data_dict[folder_name] = {
                't': df[COL_TIME].values, 
                'th2': df[COL_THETA2].values, 
                'freq_val': float(match_freq.group(1))
            }
        except Exception as e:
            pass
            
    print(f"Loaded data for {len(data_dict)} folders.")
    return data_dict

data_cache = load_data()

if not data_cache:
    print("No valid data found.")
    exit()

# Sort folders logically by driving frequency
sorted_folders = sorted(list(data_cache.keys()), key=lambda k: data_cache[k]['freq_val'])

# =============================================================================
# 3. FFT PROCESSING & MATRIX GENERATION
# =============================================================================
print("Computing FFTs and interpolating spectral matrix...")

# We need a unified Y-axis (Frequency Bins) because videos have slightly different lengths
unified_freqs = np.linspace(0.01, MAX_FFT_FREQ, 800) # Start slightly above 0 to avoid DC offset blowing up log scale

drive_freqs = []
Z_matrix = []

for folder_name in sorted_folders:
    t_raw = data_cache[folder_name]['t']
    th2_raw = data_cache[folder_name]['th2']
    drive_f = data_cache[folder_name]['freq_val']
    
    # 1. Unwrap Angle
    th2_u = np.rad2deg((np.deg2rad(th2_raw)))
    
    # 2. Transient Filter
    cutoff_time = t_raw.max() - min(TIME_WINDOW, t_raw.max() - t_raw.min())
    mask = t_raw >= cutoff_time
    t_filt = t_raw[mask]
    th2_filt = th2_u[mask]
    
    # 3. Remove DC Offset
    th2_centered = th2_filt - np.mean(th2_filt)
    
    # 4. Calculate FFT
    N = len(th2_centered)
    dt = np.mean(np.diff(t_filt))
    
    if N > 0 and dt > 0:
        yf = np.fft.rfft(th2_centered)
        xf = np.fft.rfftfreq(N, d=dt)
        amplitude = (2.0 / N) * np.abs(yf)
        
        # 5. Interpolate onto the unified frequency axis
        # Any frequency out of bounds of the video's Nyquist limit gets amplitude 0
        interp_func = interp1d(xf, amplitude, kind='linear', bounds_error=False, fill_value=1e-10)
        unified_amp = interp_func(unified_freqs)
        
        # Add a tiny noise floor to prevent log(0) errors in the colormap
        unified_amp = np.clip(unified_amp, a_min=1e-5, a_max=None)
        
        Z_matrix.append(unified_amp)
        drive_freqs.append(drive_f)

# Convert lists to NumPy arrays for plotting
# Transpose Z so that Y-axis is Response Frequency and X-axis is Driving Frequency
X = np.array(drive_freqs)
Y = unified_freqs
Z = np.array(Z_matrix).T 

# =============================================================================
# 4. DRAWING THE HEATMAP
# =============================================================================
fig, ax = plt.subplots(figsize=(14, 8))
fig.canvas.manager.set_window_title("Spectral Bifurcation Diagram")

ax.set_title("Spectral Bifurcation Diagram (FFT Waterfall Plot)\nColor Intensity = FFT Amplitude", fontsize=16, pad=15)
ax.set_xlabel("Driving Motor Frequency (Hz)", fontsize=14)
ax.set_ylabel("Pendulum Response Frequency (Hz)", fontsize=14)

# Create the heatmap. We use shading='nearest' to make the individual frequencies clear
# LogNorm creates the logarithmic color mapping to reveal the chaotic dust
c = ax.pcolormesh(X, Y, Z, cmap='inferno', shading='nearest')

# Add a colorbar to explain the intensities
cbar = fig.colorbar(c, ax=ax, pad=0.02)
cbar.set_label('FFT Amplitude (Log Scale)', fontsize=12)

# --- OVERLAY GUIDELINES ---
# Draw a diagonal line showing where the pendulum perfectly matches the motor (f = f_drive)
ax.plot(X, X, color='cyan', linestyle='--', linewidth=1.5, alpha=0.6, label='Primary Response ($f_{drive}$)')

# Draw a diagonal line showing the period-doubling frequency (f = f_drive / 2)
ax.plot(X, X/2.0, color='lime', linestyle=':', linewidth=1.5, alpha=0.8, label='Period-Doubling ($f_{drive}/2$)')

# Draw a line for the 3rd harmonic just in case the system hits non-linear resonance
ax.plot(X, X*3.0, color='white', linestyle=':', linewidth=1.0, alpha=0.4, label='3rd Harmonic ($3 \cdot f_{drive}$)')

ax.legend(loc='upper left', fontsize=11, facecolor='black', edgecolor='white', labelcolor='white')

# Tighten the limits to the exact data bounds
ax.set_xlim(X.min(), X.max())
ax.set_ylim(0, MAX_FFT_FREQ)

plt.tight_layout()
plt.show()