# -*- coding: utf-8 -*-
"""
Created on Mon May 25 15:41:01 2026

@author: cohen
"""

import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"  # Directory containing your folders (e.g., ".")

# Update these strings to match the exact column headers in your CSV files
COL_TIME = "time_s"
COL_THETA1 = "theta1_deg"
COL_THETA2 = "theta2_deg"

# =============================================================================
# 2. DATA PROCESSING & PHASE RECOVERY
# =============================================================================
def load_and_align_data():
    print("Scanning directories and aligning phases...")
    csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)
    
    bifurcation_data = [] # Will hold tuples of (Frequency, Sampled_Omega2)
    
    for file_path in csv_files:
        match = re.search(r'(\d+(?:\.\d+)?)\s*Hz', file_path, re.IGNORECASE)
        if not match: continue
        freq = float(match.group(1))
        
        try:
            df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA1, COL_THETA2])
            time = df[COL_TIME].values
            
            # 1. Unwrap phase and calculate continuous velocity
            th2_u = np.rad2deg(np.unwrap(np.deg2rad(df[COL_THETA2].values)))
            omega2 = np.gradient(th2_u, time)
            
            # --- THE PHASE ALIGNMENT TRICK ---
            # 2. Isolate the dominant driving signal in Theta 1
            th1 = df[COL_THETA1].values
            th1_centered = th1 - np.mean(th1) # Remove DC offset/gravity sag
            omega_drive = 2 * np.pi * freq
            
            # 3. Project against perfect sine/cosine to find the phase angle (phi)
            sin_proj = np.sum(th1_centered * np.sin(omega_drive * time))
            cos_proj = np.sum(th1_centered * np.cos(omega_drive * time))
            phi = np.arctan2(cos_proj, sin_proj)
            
            # 4. Calculate exactly how many seconds to delay to reach Phase 0
            T = 1.0 / freq
            t_offset = (-phi / omega_drive) % T 
            
            # 5. Stroboscopic Sampling
            # Start at t_min + our aligned offset, step by exactly 1 Period (T)
            t_strobo = np.arange(time.min() + t_offset, time.max(), T)
            
            # Interpolate the angular velocity at these exact aligned timestamps
            # We skip the first few seconds (transients) to let the pendulum settle into its attractor
            transient_cutoff = time.min() + 5.0 # Skip first 5 seconds
            t_strobo_steady = t_strobo[t_strobo > transient_cutoff]
            
            if len(t_strobo_steady) > 0:
                om2_sampled = np.interp(t_strobo_steady, time, omega2)
                bifurcation_data.append((freq, om2_sampled))
                
        except Exception as e:
            print(f"Failed {file_path}: {e}")

    # Sort by frequency
    bifurcation_data.sort(key=lambda x: x[0])
    return bifurcation_data

# =============================================================================
# 3. DRAWING THE BIFURCATION DIAGRAM
# =============================================================================
data = load_and_align_data()

if not data:
    print("No valid data found to plot.")
    exit()

plt.figure(figsize=(14, 8))
plt.title("Experimental Bifurcation Diagram: Double Pendulum Route to Chaos", fontsize=16)
plt.xlabel("Driving Frequency (Hz)", fontsize=14)
plt.ylabel(r"Stroboscopic Angular Velocity $\omega_2$ (deg/s)", fontsize=14)

# Plotting the data
for freq, om2_samples in data:
    # We plot the frequency as the X coordinate, and all sampled omegas as Y coordinates.
    # We use very small, slightly transparent dots. When they overlap in a periodic limit cycle, 
    # they look like a solid dot. When chaotic, they form a vertical line of dust.
    plt.scatter([freq] * len(om2_samples), om2_samples, 
                s=5, color='black', alpha=0.4, edgecolors='none')

plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()