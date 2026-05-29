# -*- coding: utf-8 -*-
"""
Created on Mon May 25 15:50:44 2026

@author: cohen
"""

import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"  # Directory containing your folders (e.g., ".")

# Update these strings to match the exact column headers in your CSV files
COL_TIME = "time_s"
COL_THETA1 = "theta1_deg"
COL_THETA2 = "theta2_deg"

# =============================================================================
# 2. DATA PROCESSING & PHASE EXTRACTION
# =============================================================================
def load_and_prepare_data():
    print("Scanning directories and computing base phases...")
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    data_cache = {}
    
    for file_path in csv_files:
        match = re.search(r'(\d+(?:\.\d+)?)\s*Hz', file_path, re.IGNORECASE)
        if not match: continue
        freq = float(match.group(1))
        
        try:
            df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA1, COL_THETA2])
            time = df[COL_TIME].values
            
            # 1. Continuous Angular Velocity (Omega 2)
            th2_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA2].values)))
            omega2 = np.gradient(th2_u, time)
            
            # 2. Extract optimal base phase from Theta 1
            th1 = df[COL_THETA1].values
            th1_centered = th1 - np.mean(th1)
            omega_drive = 2 * np.pi * freq
            
            sin_proj = np.sum(th1_centered * np.sin(omega_drive * time))
            cos_proj = np.sum(th1_centered * np.cos(omega_drive * time))
            phi = np.arctan2(cos_proj, sin_proj)
            
            # 3. Calculate Period and Base Time Offset
            T = 1.0 / freq
            t_offset_base = (-phi / omega_drive) % T 
            
            # 4. Save to cache for fast interactive redrawing
            data_cache[freq] = {
                'time': time,
                'om2': omega2,
                'T': T,
                't_offset_base': t_offset_base
            }
                
        except Exception as e:
            print(f"Failed {file_path}: {e}")

    return data_cache

data_cache = load_and_prepare_data()

if not data_cache:
    print("No valid data found to plot. Check directories and CSV format.")
    exit()

# =============================================================================
# 3. INTERACTIVE BIFURCATION DIAGRAM SETUP
# =============================================================================
fig, ax = plt.subplots(figsize=(14, 8))
fig.canvas.manager.set_window_title("Interactive Bifurcation Diagram")
plt.subplots_adjust(bottom=0.25) # Make room for sliders

ax.set_title("Experimental Bifurcation Diagram: Route to Chaos", fontsize=16)
ax.set_xlabel("Driving Frequency (Hz)", fontsize=14)
ax.set_ylabel(r"Stroboscopic Angular Velocity $\omega_2$ (deg/s)", fontsize=14)
ax.grid(True, alpha=0.3)

# Initialize scatter plot with BIGGER points (s=20)
scatter = ax.scatter([], [], s=20, color='black', alpha=0.5, edgecolors='none')

# Lock the X-axis statically based on the minimum and maximum frequencies we have
freqs = list(data_cache.keys())
x_pad = (max(freqs) - min(freqs)) * 0.05
ax.set_xlim(min(freqs) - x_pad, max(freqs) + x_pad)

# =============================================================================
# 4. SLIDERS & UPDATE LOGIC
# =============================================================================
ax_phase = plt.axes([0.15, 0.1, 0.7, 0.03])
ax_keep = plt.axes([0.15, 0.05, 0.7, 0.03])

# Slider 1: Shifts the phase relative to the calculated optimum (-50% to +50% of the period)
slider_phase = Slider(ax_phase, 'Phase Offset tuning (%)', -50.0, 50.0, valinit=0.0, valfmt='%1.1f%%')

# Slider 2: Determines what portion of the video to keep (e.g. 50% means keep ONLY the last 50%)
slider_keep = Slider(ax_keep, 'Keep Last (%)', 5.0, 100.0, valinit=50.0, valfmt='%1.0f%%')

def update(val):
    phase_shift_pct = slider_phase.val / 100.0
    keep_pct = slider_keep.val / 100.0
    
    all_points = []
    
    for freq, data in data_cache.items():
        t = data['time']
        om2 = data['om2']
        T = data['T']
        base_offset = data['t_offset_base']
        
        # Calculate final offset including user manual tuning
        t_offset = (base_offset + phase_shift_pct * T) % T
        
        # Generate perfect stroboscopic points
        t_strobo = np.arange(t.min() + t_offset, t.max(), T)
        
        # --- TRANSIENT FILTER ---
        # Calculate exactly when to start sampling based on the 'Keep' slider
        video_duration = t.max() - t.min()
        cutoff_time = t.max() - (keep_pct * video_duration)
        
        # Throw away points before the cutoff time
        t_strobo_filtered = t_strobo[t_strobo >= cutoff_time]
        
        if len(t_strobo_filtered) > 0:
            om2_sampled = np.interp(t_strobo_filtered, t, om2)
            # Create pairs of [Frequency, Sampled_Omega2] for the scatter plot
            freq_column = np.full_like(om2_sampled, freq)
            all_points.append(np.c_[freq_column, om2_sampled])
            
    if all_points:
        # Stack all points into one big array and update the scatter plot
        offsets = np.vstack(all_points)
        scatter.set_offsets(offsets)
        
        # Dynamically Autoscale the Y-axis (since X is locked)
        y_min, y_max = offsets[:, 1].min(), offsets[:, 1].max()
        y_pad = (y_max - y_min) * 0.1
        if y_pad == 0: y_pad = 10
        ax.set_ylim(y_min - y_pad, y_max + y_pad)
    else:
        # If sliders cause zero points to remain, clear graph
        scatter.set_offsets(np.empty((0, 2)))
        
    fig.canvas.draw_idle()

slider_phase.on_changed(update)
slider_keep.on_changed(update)

# Initialize
update(0)
plt.show()