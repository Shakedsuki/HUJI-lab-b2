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
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week5-pendulum-motor-driven\measurements"

COL_TIME = "time_s"
COL_THETA1 = "theta1_deg"
COL_THETA2 = "theta2_deg"

# =============================================================================
# 2. DATA LOADING & PROCESSING
# =============================================================================
def load_data():
    print("Scanning directories for CSV files...")
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    data_dict = {}
            
    for file_path in csv_files:
        folder_name = os.path.basename(os.path.dirname(file_path))
        
        match_freq = re.search(r'(\d+(?:\.\d+)?)\s*Hz', folder_name, re.IGNORECASE)
        match_volt = re.search(r'(\d+(?:\.\d+)?)\s*V', folder_name, re.IGNORECASE)
        
        if not match_freq or not match_volt:
            continue
            
        freq_val = float(match_freq.group(1))
        volt_val = float(match_volt.group(1))
        
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
            
            # Save scalar values into the dataframe
            df['volt'] = volt_val
            df['freq'] = freq_val 
            
            data_dict[folder_name] = df
            
        except Exception as e:
            print(f"Failed to process {file_path}: {e}")

    if not data_dict:
        raise ValueError("No matching CSV data found.")
        
    print(f"Loaded data for {len(data_dict)} folders.")
    return data_dict

data_cache = load_data()

# =============================================================================
# 3. GROUPING THE DATA
# =============================================================================
group_freq1 = []
group_volt4 = []
group_rest = []

# Sort folders into mutually exclusive groups
for folder_name, df in data_cache.items():
    freq = df['freq'].iloc[0]
    volt = df['volt'].iloc[0]
    
    if freq == 1.0:
        group_freq1.append((volt,freq,folder_name))
    if volt == 4.0:
        group_volt4.append((volt,freq,folder_name))
    if freq != 1.0 and volt!=4.0:
        group_rest.append(folder_name)
        
group_freq1=[i[2] for i in sorted(group_freq1)]
group_volt4=[i[2] for i in sorted(group_volt4)]
# =============================================================================
# 4. HELPER FUNCTIONS
# =============================================================================
def wrap_angle(angle_deg):
    return ((angle_deg + 180) % 360) - 180

def get_padded_limits(data_x, data_y, pad=0.1):
    if len(data_x) == 0 or len(data_y) == 0:
        return (0, 1), (0, 1)
        
    x_range = data_x.max() - data_x.min()
    y_range = data_y.max() - data_y.min()
    
    if x_range == 0: x_range = 1
    if y_range == 0: y_range = 1
        
    return (data_x.min() - pad*x_range, data_x.max() + pad*x_range), \
           (data_y.min() - pad*y_range, data_y.max() + pad*y_range)

# =============================================================================
# 5. WINDOW GENERATOR
# =============================================================================
def create_explorer_window(title_prefix, folder_list):
    """Generates an independent Matplotlib window with sliders for a given list of folders."""
    if not folder_list:
        print(f"Skipping '{title_prefix}' - No data matches this condition.")
        return None
        
    # Sort specifically for this group by frequency
    sorted_folders = sorted(folder_list, key=lambda k: data_cache[k]['freq'].iloc[0])
    
    fig, axs = plt.subplots(2, 2, figsize=(12, 8))
    fig.canvas.manager.set_window_title(f"{title_prefix}")
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

    ax_folder = fig.add_axes([0.15, 0.1, 0.7, 0.03])
    ax_offset = fig.add_axes([0.15, 0.05, 0.7, 0.03])

    slider_folder = Slider(ax_folder, 'Folder Select', 0, len(sorted_folders) - 1, valinit=0, valstep=1, valfmt='%0.0f')
    slider_offset = Slider(ax_offset, 'Phase Offset (%)', 0.0, 100.0, valinit=0.0, valfmt='%1.1f%%')

    # Use a dictionary to store state so the localized update function can modify it
    state = {'current_idx': -1}

    def update(val):
        idx = int(slider_folder.val)
        offset_pct = slider_offset.val / 100.0
        
        folder_name = sorted_folders[idx]
        slider_folder.valtext.set_text(folder_name)
        
        df = data_cache[folder_name]
        
        t = df['t'].values
        om1, om2 = df['om1'].values, df['om2'].values
        
        th1_wrap = wrap_angle(df['th1'].values)
        th2_wrap = wrap_angle(df['th2'].values)
        
        freq_val = df['freq'].iloc[0]
        T = 1.0 / freq_val
        
        t_min, t_max = t.min(), t.max()
        offset_time = offset_pct * T
        t_strobo = np.arange(t_min + offset_time, t_max, T)
        
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
            s_p1.set_offsets(np.empty((0, 2)))
            s_p2.set_offsets(np.empty((0, 2)))
            s_th.set_offsets(np.empty((0, 2)))
            s_om.set_offsets(np.empty((0, 2)))
        
        if idx != state['current_idx']:
            xlim, ylim = get_padded_limits(th1_wrap, om1)
            axs[0, 0].set(xlim=xlim, ylim=ylim)
            
            xlim, ylim = get_padded_limits(th2_wrap, om2)
            axs[0, 1].set(xlim=xlim, ylim=ylim)
            
            xlim, ylim = get_padded_limits(th1_wrap, th2_wrap)
            axs[1, 0].set(xlim=xlim, ylim=ylim)
            
            xlim, ylim = get_padded_limits(om1, om2)
            axs[1, 1].set(xlim=xlim, ylim=ylim)
            
            state['current_idx'] = idx
            fig.suptitle(f"{title_prefix} | Dataset: {folder_name}", fontsize=16)
            
        fig.canvas.draw_idle()

    slider_folder.on_changed(update)
    slider_offset.on_changed(update)

    update(0)
    
    # Crucial: Return the sliders so Python doesn't delete them from memory!
    return fig, (slider_folder, slider_offset)

# =============================================================================
# 6. EXECUTE AND SHOW ALL WINDOWS
# =============================================================================
# We must store the returned objects in a list to keep them "alive"
active_windows = []

win1 = create_explorer_window("Group: Frequency = 1 Hz", group_freq1)
if win1: active_windows.append(win1)

win2 = create_explorer_window("Group: Voltage = 4 V", group_volt4)
if win2: active_windows.append(win2)

win3 = create_explorer_window("Group: The Rest", group_rest)
if win3: active_windows.append(win3)

# Show all generated windows simultaneously
plt.show()