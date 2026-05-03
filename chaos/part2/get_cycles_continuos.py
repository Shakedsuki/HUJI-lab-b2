# -*- coding: utf-8 -*-
"""
Created on Sat May  2 19:02:10 2026

@author: cohen
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import numpy as np
from scipy.signal import find_peaks
from tqdm import tqdm

# --- Plot Aesthetics ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'figure.figsize': (10, 6),
    'figure.dpi': 150
})

# Update this path to wherever your AM sample is stored
p = r"samples\Bifurcation_map_cheat" 
file_list = glob.glob(os.path.join(p, '*.csv'))
for file_path in tqdm(file_list[:1]): 
    filename = os.path.basename(file_path)

    # Read data
    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])

    # --- 1. LIGHT SMOOTHING ---
    # We use a very small window to remove digital fuzz without flattening the chaotic peaks.
    window = 5
    diode_V_raw = df[4].rolling(window=window).mean()
    circuit_V_raw = df[10].rolling(window=window).mean()

    valid_idx = ~diode_V_raw.isna() & ~circuit_V_raw.isna()
    diode_V = diode_V_raw[valid_idx].to_numpy()
    circuit_V = -circuit_V_raw[valid_idx].to_numpy()

    # --- 2. DEFINE THE DRIVING CYCLES ---
    # We find the peaks of the driving wave to act as the "boundaries" for each cycle.
    # Dynamic prominence automatically scales to your signal's noise floor.
    drive_prominence = 0.5 * np.std(circuit_V)
    cycle_boundaries_idx, _ = find_peaks(circuit_V, prominence=drive_prominence)

    peak_Vd = []
    V_drive_amp = []

    # --- 3. CYCLE-BY-CYCLE EXTRACTION (The Core Fix) ---
    for i in range(len(cycle_boundaries_idx) - 10):
        start_idx = cycle_boundaries_idx[i]
        end_idx = cycle_boundaries_idx[i+10]
        
        # Isolate the data for this specific single wave cycle
        cycle_diode = diode_V[start_idx:end_idx]
        cycle_drive = circuit_V[start_idx:end_idx]
        
        a,_=find_peaks(cycle_diode,prominence=0.05)
        
        true_amplitude = (np.max(cycle_drive)) 
        
        for i in a:
            peak_Vd.append(cycle_diode[i])
            V_drive_amp.append(true_amplitude)
            
        
        # Append exactly ONE maximum diode voltage per cycle
        peak_Vd.append(np.max(cycle_diode))
        
        # Calculate the true Peak-to-Peak driving amplitude for this cycle
        # Dividing by 2 gives us the amplitude from zero (the true envelope)
        
        V_drive_amp.append(true_amplitude)

    peak_Vd = np.array(peak_Vd)
    V_drive_amp = np.array(V_drive_amp)

    # --- 4. HYSTERESIS SPLIT ---
    # Because V_drive_amp traces the AM envelope, its gradient tells us 
    # if the AM wave is currently growing or shrinking.
    dV_drive = np.gradient(V_drive_amp)
    forward_mask = dV_drive > 0
    reverse_mask = dV_drive < 0

    # --- 5. PLOTTING ---
    fig, ax = plt.subplots()
    ax.set_title(f"AM Sweep Bifurcation Diagram\n({filename})")
    ax.set_xlabel("True Driving Amplitude (V)")
    ax.set_ylabel("Peak Diode Voltage ($V_D$)")

    # Plot Forward Sweep (AM Amplitude Increasing)
    ax.plot(V_drive_amp[forward_mask], peak_Vd[forward_mask], 
            '.', markersize=5, color='blue', alpha=0.2, label="Amplitude Increasing")
    
    # Plot Reverse Sweep (AM Amplitude Decreasing)
    # ax.plot(V_drive_amp[reverse_mask], peak_Vd[reverse_mask], 
    #         '.', markersize=5, color='red', alpha=0.2, label="Amplitude Decreasing")

    # Override legend markers to be visible
    leg = ax.legend(loc='upper left', fontsize=10)
    for legobj in leg.legend_handles:
        legobj.set_markersize(8)
        legobj.set_alpha(1.0)

    ax.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.show()