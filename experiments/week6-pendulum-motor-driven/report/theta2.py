import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"
T = 10
COL_TIME = "time_s"
COL_THETA2 = "theta2_deg"

# Define the exact frequencies you want to plot
CHOSEN_FREQS = [0.9, 1.26, 1.34] # Replace these with your desired frequencies

# --- PLOT SETTINGS ---
MARKER_SIZE = 7         # Size of the scatter points
LABEL_FONT_SIZE = 18    # Size of the X and Y axis titles
TICK_FONT_SIZE = 14     # Size of the numbers on the axes
# ---------------------

csv_files = glob.glob(os.path.join(BASE_DIR, '*', 'tracking.csv'), recursive=True)

# =============================================================================
# 2. CALCULATE BASELINE ERROR (First 10s of the first frequency file)
# =============================================================================
theta2_error = 0.0

for file_path in csv_files:
    match = re.search(r'(\d+(?:\.\d+)?)\s*Hz', file_path, re.IGNORECASE)
    if match and float(match.group(1)) == CHOSEN_FREQS[0]:
        try:
            df_err = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA2])
            
            # Isolate the first 10 seconds
            t_min = df_err[COL_TIME].min()
            df_first_10 = df_err[df_err[COL_TIME] <= (t_min + 10)]
            
            # Standard deviation represents the measurement noise/error
            theta2_error = df_first_10[COL_THETA2].std()
            print(f"Calculated baseline error (std dev): {theta2_error:.4f} deg from {file_path}")
            
        except Exception as e:
            print(f"Failed to calculate error from {file_path}: {e}")
        
        break

# =============================================================================
# 3. LOAD & PLOT
# =============================================================================
fig, axs = plt.subplots(len(CHOSEN_FREQS), 1, figsize=(10, 3 * len(CHOSEN_FREQS)), sharex=True)
axs = np.atleast_1d(axs)

for i, target_freq in enumerate(CHOSEN_FREQS):
    ax = axs[i]
    
    for file_path in csv_files:
        match = re.search(r'(\d+(?:\.\d+)?)\s*Hz', file_path, re.IGNORECASE)
        if match and float(match.group(1)) == target_freq:
            
            try:
                df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA2])
                
                t_max = df[COL_TIME].max()
                df_last_20 = df[df[COL_TIME] >= (t_max - T)].copy()
                
                time_shared = df_last_20[COL_TIME] - df_last_20[COL_TIME].min()
                theta2 = df_last_20[COL_THETA2]
                
                # Apply MARKER_SIZE here
                ax.errorbar(
                    time_shared, 
                    theta2, 
                    yerr=theta2_error, 
                    fmt='.', 
                    markersize=MARKER_SIZE, # <--- Configured point size applied here
                    ecolor='gray',     
                    elinewidth=1,      
                    capsize=2,         
                    alpha=0.8          
                )
                
            except Exception as e:
                print(f"Failed to process {file_path}: {e}")
            
            break 

    # =========================================================================
    # 4. FORMATTING
    # =========================================================================
    # Apply LABEL_FONT_SIZE to Y-axis
    ax.set_ylabel(f"$\\theta_2$ (deg)", fontsize=LABEL_FONT_SIZE)
    
    # Apply TICK_FONT_SIZE to the axis numbers
    ax.tick_params(axis='both', which='major', labelsize=TICK_FONT_SIZE)

# Apply LABEL_FONT_SIZE to the X-axis on the bottom-most subplot
axs[-1].set_xlabel("Time (s)", fontsize=LABEL_FONT_SIZE)

plt.tight_layout()
plt.show()