# -*- coding: utf-8 -*-
"""
Created on Wed May 27 17:57:07 2026

@author: cohen
"""

# -*- coding: utf-8 -*-
"""
Metric 8: Average Energy vs. Driving Frequency (Interactive Resonance & Virial Ratio)
Includes sliders for Transient Filtering and Radio Buttons for Rod Selection.
"""

import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, RadioButtons

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"

COL_TIME = "time_s"
COL_THETA1 = "theta1_deg"
COL_THETA2 = "theta2_deg"

# PHYSICAL CONSTANTS
M1 = 0.1   # Mass of top rod (kg)
M2 = 0.1   # Mass of bottom rod (kg)
L1 = 0.27  # FULL Length of top rod (meters)
L2 = 0.27  # FULL Length of bottom rod (meters)
G = 9.81   # Gravity (m/s^2)

# =============================================================================
# 2. DATA PROCESSING & ENERGY CACHING
# =============================================================================
def load_and_cache_energies():
    print("Scanning directories and caching full energy arrays...")
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    cache = {}
    
    for file_path in csv_files:
        folder_name = os.path.basename(os.path.dirname(file_path))
        match_freq = re.search(r'(\d+(?:\.\d+)?)\s*Hz', folder_name, re.IGNORECASE)
        
        if not match_freq: continue
        freq_val = float(match_freq.group(1))
        
        try:
            df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA1, COL_THETA2])
            time = df[COL_TIME].values
            
            th1_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA1].values)))
            th2_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA2].values)))
            
            omega1 = np.gradient(th1_u, time)
            omega2 = np.gradient(th2_u, time)

            th1_rad = np.deg2rad(th1_u)
            th2_rad = np.deg2rad(th2_u)
            om1_rad = np.deg2rad(omega1)
            om2_rad = np.deg2rad(omega2)
            
            # --- CALCULATE FULL ARRAYS ---
            T1 = (1.0 / 6.0) * M1 * (L1**2) * (om1_rad**2)
            T2 = 0.5 * M2 * (L1**2) * (om1_rad**2) + \
                 (1.0 / 6.0) * M2 * (L2**2) * (om2_rad**2) + \
                 0.5 * M2 * L1 * L2 * om1_rad * om2_rad * np.cos(th1_rad - th2_rad)
                 
            U1 = M1 * G * (L1 / 2.0) * (1 - np.cos(th1_rad))
            U2 = M2 * G * (L1 * (1 - np.cos(th1_rad)) + (L2 / 2.0) * (1 - np.cos(th2_rad)))
            
            cache[freq_val] = {
                'time': time,
                'T1': T1, 'T2': T2,
                'U1': U1, 'U2': U2
            }
            
        except Exception as e:
            print(f"Failed {file_path}: {e}")

    return cache

energy_cache = load_and_cache_energies()

if not energy_cache:
    print("No valid data found to plot.")
    exit()

sorted_freqs = sorted(list(energy_cache.keys()))

# =============================================================================
# 3. INTERACTIVE PLOTTING UI
# =============================================================================
fig, ax1 = plt.subplots(figsize=(14, 8))
fig.canvas.manager.set_window_title("Interactive Energy Explorer")
plt.subplots_adjust(bottom=0.20, right=0.85) # Make room for slider and radio buttons

# Secondary axis for the ratio
ax2 = ax1.twinx()

# --- SETUP UI CONTROLS ---
# Slider for % of points from the end
ax_slider = plt.axes([0.10, 0.08, 0.65, 0.03])
slider_keep = Slider(ax_slider, 'Steady State Window\n(% from end)', 5.0, 100.0, valinit=30.0, valstep=1.0)

# Radio Buttons for Rod Selection
ax_radio = plt.axes([0.87, 0.45, 0.11, 0.15], facecolor='whitesmoke')
radio_mode = RadioButtons(ax_radio, ('Both Rods', 'Top Rod', 'Bottom Rod'))

def update(val=None):
    keep_pct = slider_keep.val
    mode = radio_mode.value_selected
    
    frequencies = []
    avg_totals = []
    avg_Ts = []
    avg_Us = []
    ratios_TU = []
    
    # 1. Process data based on UI states
    for freq in sorted_freqs:
        data = energy_cache[freq]
        time = data['time']
        
        # Determine slicing mask
        video_duration = time.max() - time.min()
        cutoff_time = time.max() - ((keep_pct / 100.0) * video_duration)
        mask = time >= cutoff_time
        
        # Select Rod logic
        if mode == 'Both Rods':
            T = data['T1'] + data['T2']
            U = data['U1'] + data['U2']
        elif mode == 'Top Rod':
            T = data['T1']
            U = data['U1']
        elif mode == 'Bottom Rod':
            T = data['T2']
            U = data['U2']
            
        T_filt = T[mask]
        U_filt = U[mask]
        Total_filt = T_filt + U_filt
        
        avg_tot = np.mean(Total_filt)
        avg_T = np.mean(T_filt)
        avg_U = np.mean(U_filt)
        ratio_TU = avg_T / avg_U if avg_U > 1e-10 else 0
        
        frequencies.append(freq)
        avg_totals.append(avg_tot)
        avg_Ts.append(avg_T)
        avg_Us.append(avg_U)
        ratios_TU.append(ratio_TU)
        
    # 2. Clear and Redraw Graph
    ax1.clear()
    ax2.clear()
    
    # Titles and Labels
    ax1.set_title(f"Energy and T/U Ratio ({mode})\nSteady State: Final {keep_pct:.1f}% of video", fontsize=15, pad=15)
    ax1.set_xlabel("Driving Motor Frequency (Hz)", fontsize=13)
    ax1.set_ylabel("Average Energy (Joules)", fontsize=13)
    ax2.set_ylabel("Energy Ratio (T / U)", fontsize=13, color='purple')

    # Draw Primary Energy Lines
    l1, = ax1.plot(frequencies, avg_totals, color='black', linestyle='-', linewidth=2.5, alpha=0.8, label='Total Energy ($E$)')
    ax1.scatter(frequencies, avg_totals, color='black', s=50, zorder=5)

    l2, = ax1.plot(frequencies, avg_Ts, color='blue', linestyle='--', linewidth=2, alpha=0.8, label='Kinetic Energy ($T$)')
    ax1.scatter(frequencies, avg_Ts, color='blue', s=40, zorder=5)

    l3, = ax1.plot(frequencies, avg_Us, color='green', linestyle='-.', linewidth=2, alpha=0.8, label='Potential Energy ($U$)')
    ax1.scatter(frequencies, avg_Us, color='green', s=40, zorder=5)

    # Draw Ratio Line
    l4, = ax2.plot(frequencies, ratios_TU, color='purple', linestyle=':', linewidth=2.5, alpha=0.9, label='T/U Ratio')
    ax2.scatter(frequencies, ratios_TU, color='purple', s=50, marker='s', zorder=5) 
    ax2.tick_params(axis='y', labelcolor='purple')

    # Faint Ratio Baseline
    ax2.axhline(1.0, color='purple', linestyle='-', linewidth=1.5, alpha=0.2)
    ax2.text(frequencies[0], 1.01, ' Ideal Harmonic Oscillator (Ratio = 1.0)', color='purple', alpha=0.5, fontsize=10, va='bottom')

    # Highlight Resonance Peak
    max_idx = np.argmax(avg_totals)
    max_f = frequencies[max_idx]
    max_tot = avg_totals[max_idx]

    ax1.annotate(f"Resonance Peak\n{max_f} Hz", 
                 xy=(max_f, max_tot), 
                 xytext=(0, 20), textcoords='offset points', 
                 ha='center', va='bottom', fontsize=11, fontweight='bold', color='black',
                 arrowprops=dict(arrowstyle="->", color='black', lw=1.5))

    # Formatting and Auto-scaling
    ax1.grid(True, linestyle='--', alpha=0.5)
    
    # Merge Legends
    lines = [l1, l2, l3, l4]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left', fontsize=11, framealpha=0.9)

    ax1.set_xlim(min(frequencies) - 0.05, max(frequencies) + 0.05)
    ax1.set_ylim(0, max(avg_totals) * 1.15) 
    
    max_ratio = max(ratios_TU)
    min_ratio = min(ratios_TU)
    ax2.set_ylim(min(0.5, min_ratio - 0.2), max(1.5, max_ratio + 0.2))
    
    fig.canvas.draw_idle()

# Hook up events
slider_keep.on_changed(update)
radio_mode.on_clicked(update)

# Initial draw
update()
plt.show()