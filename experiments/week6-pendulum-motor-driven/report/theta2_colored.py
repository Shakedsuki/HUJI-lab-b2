"""
Slide-12 (עיבוד נתונים) theta2-vs-time figure, restyled.

Sibling of Nir's theta2.py (left untouched). Same data/layout, but:
  * y-axis fixed to the full -180..180 deg range,
  * chaotic panel (middle) drawn in red, non-chaotic panels (top/bottom) green,
  * portable BASE_DIR (relative to this file) and a savefig so it regenerates
    the PNG headlessly.
"""
import os
import re
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# =============================================================================
# 1. CONFIGURATION
# =============================================================================
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "measurements")
OUT_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theta2_timeseries_colored.png")
T = 10
COL_TIME = "time_s"
COL_THETA2 = "theta2_deg"

# Frequencies, top -> bottom (match the slide labels).
CHOSEN_FREQS = [0.9, 1.19, 1.34]
# Per-panel colour: top & bottom are non-chaotic (green), middle is chaotic (red).
PANEL_COLORS = ["green", "red", "green"]

# --- PLOT SETTINGS ---
MARKER_SIZE = 4         # Size of the scatter points (smaller -> less dense)
LABEL_FONT_SIZE = 28    # Size of the X and Y axis titles
TICK_FONT_SIZE = 24     # Size of the numbers on the axes
TICK_PAD = 10           # Gap between tick numbers and the axis
LABEL_PAD = 14          # Gap between axis title and the tick numbers
HSPACE = 0.45           # Vertical breathing room between subplots
Y_LIM = (-185, 185)
Y_TICKS = [-180, 0, 180]
# ---------------------

csv_files = glob.glob(os.path.join(BASE_DIR, "*", "tracking.csv"), recursive=True)

# =============================================================================
# 2. CALCULATE BASELINE ERROR (First 10s of the first frequency file)
# =============================================================================
theta2_error = 0.0

for file_path in csv_files:
    match = re.search(r"(\d+(?:\.\d+)?)\s*Hz", file_path, re.IGNORECASE)
    if match and float(match.group(1)) == CHOSEN_FREQS[0]:
        try:
            df_err = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA2])
            t_min = df_err[COL_TIME].min()
            df_first_10 = df_err[df_err[COL_TIME] <= (t_min + 10)]
            theta2_error = df_first_10[COL_THETA2].std()
            print(f"Calculated baseline error (std dev): {theta2_error:.4f} deg from {file_path}")
        except Exception as e:
            print(f"Failed to calculate error from {file_path}: {e}")
        break

# =============================================================================
# 3. LOAD & PLOT
# =============================================================================
fig, axs = plt.subplots(
    len(CHOSEN_FREQS), 1,
    figsize=(10, 3.2 * len(CHOSEN_FREQS)),
    sharex=True,
    gridspec_kw={"hspace": HSPACE},
)
axs = np.atleast_1d(axs)

for i, target_freq in enumerate(CHOSEN_FREQS):
    ax = axs[i]
    color = PANEL_COLORS[i]

    for file_path in csv_files:
        match = re.search(r"(\d+(?:\.\d+)?)\s*Hz", file_path, re.IGNORECASE)
        if match and float(match.group(1)) == target_freq:
            try:
                df = pd.read_csv(file_path).dropna(subset=[COL_TIME, COL_THETA2])

                t_max = df[COL_TIME].max()
                df_last_20 = df[df[COL_TIME] >= (t_max - T)].copy()

                time_shared = df_last_20[COL_TIME] - df_last_20[COL_TIME].min()
                theta2 = df_last_20[COL_THETA2]

                ax.errorbar(
                    time_shared,
                    theta2,
                    yerr=theta2_error,
                    fmt=".",
                    markersize=MARKER_SIZE,
                    color=color,        # chaotic -> red, non-chaotic -> green
                    ecolor="gray",
                    elinewidth=1,
                    capsize=2,
                    alpha=0.8,
                )
            except Exception as e:
                print(f"Failed to process {file_path}: {e}")
            break

    # =========================================================================
    # 4. FORMATTING
    # =========================================================================
    # Only the middle panel carries the y-axis label (top/bottom are redundant).
    if i == len(CHOSEN_FREQS) // 2:
        ax.set_ylabel(f"$\\theta_2$ (deg)", fontsize=LABEL_FONT_SIZE, labelpad=LABEL_PAD)
    ax.set_ylim(*Y_LIM)
    ax.set_yticks(Y_TICKS)
    ax.tick_params(axis="both", which="major", labelsize=TICK_FONT_SIZE, pad=TICK_PAD)

axs[-1].set_xlabel("Time (s)", fontsize=LABEL_FONT_SIZE, labelpad=LABEL_PAD)

fig.savefig(OUT_PNG, dpi=200, bbox_inches="tight")
print(f"Saved figure -> {OUT_PNG}")
