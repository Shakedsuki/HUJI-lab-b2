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
from matplotlib.widgets import Slider
from scipy.interpolate import interp1d

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"

COL_TIME = "time_s"
COL_THETA2 = "theta2_deg"

TIME_WINDOW = 60.0     # Only analyze the last 20 seconds to avoid startup noise
MAX_FFT_FREQ = 20.5     # The maximum frequency to display on the Y-axis

# --- PLOT SETTINGS ---
LABEL_FONT_SIZE = 18    # Size of the X and Y axis titles
TICK_FONT_SIZE = 14     # Size of the numbers on the axes
# ---------------------

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

unified_freqs = np.linspace(0.01, MAX_FFT_FREQ, 800) 

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
        interp_func = interp1d(xf, amplitude, kind='linear', bounds_error=False, fill_value=1e-10)
        unified_amp = interp_func(unified_freqs)
        
        # Clip at a lower bound to avoid plotting absolute zero, but keep it linear
        unified_amp = np.clip(unified_amp, a_min=0, a_max=None)
        
        Z_matrix.append(unified_amp)
        drive_freqs.append(drive_f)

X = np.array(drive_freqs)
Y = unified_freqs
Z = np.array(Z_matrix).T 

# =============================================================================
# 4. DRAWING THE HEATMAP
# =============================================================================
fig, ax = plt.subplots(figsize=(14, 8))
fig.canvas.manager.set_window_title("Spectral Bifurcation Diagram")

# Make room at the bottom of the figure for the sliders
plt.subplots_adjust(bottom=0.25)

# Axis titles with larger fonts
ax.set_xlabel("Driving Motor Frequency (Hz)", fontsize=LABEL_FONT_SIZE)
ax.set_ylabel("Pendulum Response Frequency (Hz)", fontsize=LABEL_FONT_SIZE)

# Tick marks with larger fonts
ax.tick_params(axis='both', which='major', labelsize=TICK_FONT_SIZE)

# Linear scale heatmap
c = ax.pcolormesh(X, Y, Z, cmap='inferno', shading='nearest', vmin=Z.min(), vmax=Z.max())

# Colorbar with increased font size
cbar = fig.colorbar(c, ax=ax, pad=0.02)
cbar.set_label('FFT Amplitude (Linear Scale)', fontsize=TICK_FONT_SIZE)
cbar.ax.tick_params(labelsize=TICK_FONT_SIZE)

# --- OVERLAY GUIDELINES ---
# Kept ONLY the y=x line, made it thicker (linewidth=3.0) and more translucent (alpha=0.3)
ax.plot(X, X, color='cyan', linestyle='--', linewidth=3.0, alpha=0.3)

ax.set_xlim(X.min(), X.max())
ax.set_ylim(0, MAX_FFT_FREQ)

# =============================================================================
# 5. INTERACTIVE COLORMAP SLIDERS
# =============================================================================
z_min = Z.min()
z_max = Z.max()

# Define the coordinates for the slider axes [left, bottom, width, height]
ax_vmin = plt.axes([0.15, 0.1, 0.65, 0.03])
ax_vmax = plt.axes([0.15, 0.05, 0.65, 0.03])

# Create the sliders 
slider_vmin = Slider(ax_vmin, 'Min Amp', z_min, z_max, valinit=z_min)
slider_vmax = Slider(ax_vmax, 'Max Amp', z_min, z_max, valinit=z_max)

# Function to run when a slider is moved
def update_colormap(val):
    v_min = slider_vmin.val
    v_max = slider_vmax.val
    
    # Prevent Matplotlib errors by forcing vmin to always be less than vmax
    if v_min >= v_max:
        v_min = v_max * 0.99
        
    c.set_clim(vmin=v_min, vmax=v_max)
    fig.canvas.draw_idle()

# Connect the update function to the sliders
slider_vmin.on_changed(update_colormap)
slider_vmax.on_changed(update_colormap)

plt.show()