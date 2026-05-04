# -*- coding: utf-8 -*-
"""
AM Sweep Bifurcation (High-Resolution Direct Mapping)
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import numpy as np
from scipy.signal import find_peaks
from scipy.optimize import curve_fit
from tqdm import tqdm

# --- Plot Aesthetics (Bumped to ultra-high resolution) ---
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'figure.figsize': (12, 7), # Made slightly wider to stretch out the X-axis
    'figure.dpi': 300 # Doubled DPI for publication-quality crispness
})

def sine_envelope(t, amp, freq, phase, offset):
    return amp * np.sin(2.0 * np.pi * freq * t + phase) + offset

p = r"samples\Bifurcation_map_cheat" 
file_list = glob.glob(os.path.join(p, '*.csv'))

for file_path in tqdm(file_list[:1]): 
    filename = os.path.basename(file_path)

    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])

    # 1. LIGHT SMOOTHING 
    window = 5
    diode_V_raw = df[4].rolling(window=window).mean()
    circuit_V_raw = df[10].rolling(window=window).mean()

    valid_idx = ~diode_V_raw.isna() & ~circuit_V_raw.isna()
    diode_V = diode_V_raw[valid_idx].to_numpy()
    circuit_V = -circuit_V_raw[valid_idx].to_numpy() 

    # --- 2. FIT THE MATHEMATICAL SINE ENVELOPE ---
    drive_prominence = 0.5 * np.std(circuit_V)
    drive_peaks_idx, _ = find_peaks(circuit_V, prominence=drive_prominence)
    drive_peaks_val = circuit_V[drive_peaks_idx]

    guess_offset = np.mean(drive_peaks_val)
    guess_amp = (np.max(drive_peaks_val) - np.min(drive_peaks_val)) / 2.0
    
    zero_crossings = np.where(np.diff(np.sign(drive_peaks_val - guess_offset)))[0]
    if len(zero_crossings) >= 2:
        guess_period = 2.0 * np.mean(np.diff(drive_peaks_idx[zero_crossings]))
        guess_freq = 1.0 / guess_period
    else:
        guess_freq = 1.0 / len(circuit_V) 

    p0 = [guess_amp, guess_freq, 0.0, guess_offset]

    try:
        popt, pcov = curve_fit(sine_envelope, drive_peaks_idx, drive_peaks_val)#, p0=p0)
        t_array = np.arange(len(circuit_V))
        full_envelope = sine_envelope(t_array, *popt)
    except Exception as e:
        print(f"Warning: Envelope fit failed for {filename}. ({e})")
        continue 

    dV_env = np.gradient(full_envelope)
    forward_mask = dV_env > 0

    # --- 3. EXTRACT DIODE PEAKS ---
    diode_peaks_idx, _ = find_peaks(diode_V, prominence=0.05)
    diode_peaks_val = diode_V[diode_peaks_idx]
    
    # 4. DIRECT MAPPING (The massive resolution upgrade)
    # No more binning! We just look at exactly where the envelope was at the moment of the peak.
    peak_env_v = full_envelope[diode_peaks_idx]
    peak_is_forward = forward_mask[diode_peaks_idx]

    x_fwd = peak_env_v[peak_is_forward]
    y_fwd = diode_peaks_val[peak_is_forward]

    # --- 5. ULTRA-CRISP PLOTTING ---
    fig, ax = plt.subplots()
    ax.set_title(f"High-Res AM Bifurcation Diagram\n({filename})")
    ax.set_xlabel("Theoretical Driving Amplitude (V)")
    ax.set_ylabel("Peak Diode Voltage ($V_D$)")

    # Using marker=',' (pixel) and an incredibly low alpha to create physical ink density
    ax.plot(x_fwd, y_fwd, 
            marker=',', linestyle='none', color='black', alpha=1, label="Amplitude Increasing")

    leg = ax.legend(loc='upper left', fontsize=10)
    for legobj in leg.legend_handles:
        legobj.set_marker('.') # Make the legend use a visible dot
        legobj.set_markersize(8)
        legobj.set_alpha(1.0)

    ax.grid(True, linestyle=':', alpha=0.4) # Lightened the grid so it doesn't distract
    plt.tight_layout()
    plt.show()