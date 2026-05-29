# -*- coding: utf-8 -*-
"""
Created on Mon May 25 15:09:15 2026

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
# 1. CONFIGURATION (Adjust these to match your exact CSV format)
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"  # Directory containing your folders (e.g., ".")

# Update these strings to match the exact column headers in your CSV files
COL_TIME = "time_s"
COL_THETA1 = "theta1_deg"
COL_THETA2 = "theta2_deg"

# If your CSV already has angular velocities, put the column names here.
# If they are missing (set to None), the script will calculate them using derivatives.
COL_OMEGA1 = None 
COL_OMEGA2 = None

# =============================================================================
# 2. DATA LOADING & PROCESSING
# =============================================================================
def load_data():
    print("Scanning directories for CSV files...")
    # Find all CSV files in subdirectories
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    data_dict = {}
            
    for file_path in csv_files:
        match = re.search(r'(\d+(?:\.\d+)?)\s*Hz', file_path, re.IGNORECASE)
        if not match:
            continue
            
        freq = float(match.group(1))
        
        try:
            df = pd.read_csv(file_path)
            df = df.dropna(subset=[COL_TIME, COL_THETA1, COL_THETA2])
            time = df[COL_TIME].values
            
            # Phase unwrap
            th1_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA1].values)))
            th2_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA2].values)))
            
            # Derivatives on unwrapped data
            omega1 = np.gradient(th1_u, time)
            omega2 = np.gradient(th2_u, time)

            df['th1_unwrap'] = th1_u
            df['th2_unwrap'] = th2_u
            df['om1'] = omega1
            df['om2'] = omega2
            df['th1'] = df[COL_THETA1]
            df['th2'] = df[COL_THETA2]
            df['t'] = time
            
            data_dict[freq] = df
            
        except Exception as e:
            print(f"Failed to process {file_path}: {e}")

    if not data_dict:
        raise ValueError("No matching CSV data found.")
        
    print(f"Loaded data for {len(data_dict)} frequencies.")
    return data_dict

data_cache = load_data()
sorted_freqs = sorted(list(data_cache.keys()))

# =============================================================================
# 3. INTERACTIVE PLOT SETUP
# =============================================================================
fig, axs = plt.subplots(2, 2, figsize=(12, 8))
fig.canvas.manager.set_window_title("Double Pendulum Phase Space Explorer")
plt.subplots_adjust(bottom=0.25, hspace=0.3, wspace=0.3)

axs[0, 0].set_title("Pendulum 1: Theta vs Omega")
axs[0, 0].set_xlabel(r"$\theta_1$ (deg)")
axs[0, 0].set_ylabel(r"$\omega_1$ (deg/s)")

axs[0, 1].set_title("Pendulum 2: Theta vs Omega")
axs[0, 1].set_xlabel(r"$\theta_2$ (deg)")
axs[0, 1].set_ylabel(r"$\omega_2$ (deg/s)")

axs[1, 0].set_title("Configuration Space: Angles")
axs[1, 0].set_xlabel(r"$\theta_1$ (deg)")
axs[1, 0].set_ylabel(r"$\theta_2$ (deg)")

axs[1, 1].set_title("Momentum Space: Angular Velocities")
axs[1, 1].set_xlabel(r"$\omega_1$ (deg/s)")
axs[1, 1].set_ylabel(r"$\omega_2$ (deg/s)")

bg_kwargs = {'color': 'gray', 'alpha': 0.3, 's': 2}
l_p1 = axs[0, 0].scatter([], [], **bg_kwargs)
l_p2 = axs[0, 1].scatter([], [], **bg_kwargs)
l_th = axs[1, 0].scatter([], [], **bg_kwargs)
l_om = axs[1, 1].scatter([], [], **bg_kwargs)

scat_kwargs = {'color': 'red', 's': 30, 'zorder': 5, 'edgecolors': 'black'}
s_p1 = axs[0, 0].scatter([], [], **scat_kwargs)
s_p2 = axs[0, 1].scatter([], [], **scat_kwargs)
s_th = axs[1, 0].scatter([], [], **scat_kwargs)
s_om = axs[1, 1].scatter([], [], **scat_kwargs)

# =============================================================================
# 4. SLIDERS & UPDATE LOGIC
# =============================================================================
ax_freq = plt.axes([0.15, 0.1, 0.7, 0.03])
ax_offset = plt.axes([0.15, 0.05, 0.7, 0.03])

slider_freq = Slider(ax_freq, 'Freq Select', 0, len(sorted_freqs) - 1, valinit=0, valstep=1, valfmt='%0.0f')
slider_offset = Slider(ax_offset, 'Phase Offset (%)', 0.0, 100.0, valinit=0.0, valfmt='%1.1f%%')

current_freq_idx = -1

def wrap_angle(angle_deg):
    return ((angle_deg + 180) % 360) - 180

def get_padded_limits(data_x, data_y, pad=0.1):
    """Helper function to manually calculate bounding boxes for scatter plots"""
    if len(data_x) == 0 or len(data_y) == 0:
        return (0, 1), (0, 1)
        
    x_range = data_x.max() - data_x.min()
    y_range = data_y.max() - data_y.min()
    
    # Prevent crashing if range is exactly 0
    if x_range == 0: x_range = 1
    if y_range == 0: y_range = 1
        
    return (data_x.min() - pad*x_range, data_x.max() + pad*x_range), \
           (data_y.min() - pad*y_range, data_y.max() + pad*y_range)

def update(val):
    global current_freq_idx
    
    idx = int(slider_freq.val)
    offset_pct = slider_offset.val / 100.0
    freq = sorted_freqs[idx]
    
    slider_freq.valtext.set_text(f"{freq} Hz")
    
    df = data_cache[freq]
    t = df['t'].values
    om1, om2 = df['om1'].values, df['om2'].values
    
    th1_wrap = wrap_angle(df['th1'].values)
    th2_wrap = wrap_angle(df['th2'].values)
    
    T = 1.0 / freq
    t_min, t_max = t.min(), t.max()
    offset_time = offset_pct * T
    t_strobo = np.arange(t_min + offset_time, t_max, T)
    
    # Safety check: if time array is too short for strobing, pass empty arrays
    if len(t_strobo) > 0:
        th1_u_s = np.interp(t_strobo, t, df['th1_unwrap'].values)
        th2_u_s = np.interp(t_strobo, t, df['th2_unwrap'].values)
        th1_s = wrap_angle(th1_u_s)
        th2_s = wrap_angle(th2_u_s)
        om1_s = np.interp(t_strobo, t, om1)
        om2_s = np.interp(t_strobo, t, om2)
    else:
        th1_s, th2_s, om1_s, om2_s = [], [], [], []
    
    l_p1.set_offsets(np.c_[th1_wrap, om1])
    l_p2.set_offsets(np.c_[th2_wrap, om2])
    l_th.set_offsets(np.c_[th1_wrap, th2_wrap])
    l_om.set_offsets(np.c_[om1, om2])
    
    if len(th1_s) > 0:
        s_p1.set_offsets(np.c_[th1_s, om1_s])
        s_p2.set_offsets(np.c_[th2_s, om2_s])
        s_th.set_offsets(np.c_[th1_s, th2_s])
        s_om.set_offsets(np.c_[om1_s, om2_s])
    else:
        # Clear scatter points if no strobing hits
        s_p1.set_offsets(np.empty((0, 2)))
        s_p2.set_offsets(np.empty((0, 2)))
        s_th.set_offsets(np.empty((0, 2)))
        s_om.set_offsets(np.empty((0, 2)))
    
    # --- The Fix: Manual Autoscaling ---
    if idx != current_freq_idx:
        xlim, ylim = get_padded_limits(th1_wrap, om1)
        axs[0, 0].set(xlim=xlim, ylim=ylim)
        
        xlim, ylim = get_padded_limits(th2_wrap, om2)
        axs[0, 1].set(xlim=xlim, ylim=ylim)
        
        xlim, ylim = get_padded_limits(th1_wrap, th2_wrap)
        axs[1, 0].set(xlim=xlim, ylim=ylim)
        
        xlim, ylim = get_padded_limits(om1, om2)
        axs[1, 1].set(xlim=xlim, ylim=ylim)
        
        current_freq_idx = idx
        fig.suptitle(f"Driving Frequency: {freq} Hz", fontsize=16)
        
    fig.canvas.draw_idle()

slider_freq.on_changed(update)
slider_offset.on_changed(update)

update(0)
plt.show()