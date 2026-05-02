# -*- coding: utf-8 -*-
"""
RLD Circuit — Continuous Bifurcation Map from AM-Modulated Sweep
=================================================================
Produces both a 2D matplotlib plot (report-ready) and an interactive
3D plotly HTML (for exploration and rotation).

Measurement setup
-----------------
  - Circuit    : R (470 Ω) + L (100 mH) + diode (1N4005) in series
  - Source     : sinusoidal carrier (~34 kHz) with slowly varying
                 amplitude modulated by a 0.7 Hz triangle envelope
  - Peak amp.  : 7 V  (filename encodes this)
  - Scope      : Tektronix DPO3014, 1 MS/s, 1 M samples (= 1 s window)
  - CH1        : diode node voltage
  - CH2        : source voltage (carries AM envelope information)

CSV format
----------
  - Rows 0–16  : oscilloscope metadata (header)
  - Row 17 on  : data  →  col[3] = time (s),  col[4] = CH1 (V),
                           col[10] = CH2 (V)
  - Yzero offsets must be added to the raw stored voltages (see below).

Physics
-------
  The peak diode voltage sampled once per carrier cycle is a discrete-time
  dynamical system  V_{n+1} = F(V_n, A),  where A is the instantaneous
  drive amplitude and F is the Poincaré map of the RLD circuit.
  This script reads off the orbit of F as A slowly sweeps, yielding the
  bifurcation diagram without any manual amplitude stepping.

Output
------
  - 2D scatter plot  (matplotlib PNG, saved next to data in DATA_DIR)
  - 3D interactive   (plotly HTML, saved next to this script — tracked by git
                      and served via GitHub Pages)

Error note
----------
  Peak voltage uncertainty is dominated by oscilloscope ADC quantization
  (~80 mV per step at 2 V/div, 8-bit resolution). Envelope amplitude
  uncertainty is negligible (Hilbert transform on 1 M samples).

@author: cohen + claude
"""

import os
import csv
import glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from scipy.signal import find_peaks, hilbert
from scipy.ndimage import uniform_filter1d

# Directory containing this script — used for HTML output so it stays
# tracked by git and is not buried inside the gitignored samples/ tree.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

DATA_DIR      = r"samples\AM"          # folder containing 7V.csv
FILE_PATTERN  = "7V.csv"              # single recording (7V_2.csv is identical)

# Oscilloscope Yzero offsets (read from CSV metadata, row 13)
# Actual voltage = stored value + YZERO
YZERO_CH1     = -2.78   # V
YZERO_CH2     =  4.18   # V

SAMPLE_RATE   = 1e6     # Hz  (1 MS/s)
DT            = 1.0 / SAMPLE_RATE   # s per sample  (1 μs)

# Carrier frequency estimate (used to set peak-finding minimum distance)
F_CARRIER_HZ  = 34_000  # Hz  — confirmed by FFT
MIN_PEAK_DIST = int(0.6 / F_CARRIER_HZ / DT)   # 0.6 × one carrier period

# Peak prominence threshold (V) — rejects noise below this height
PEAK_PROMINENCE = 0.15

# Minimum peak voltage to keep — filters out negative-half-cycle peaks
# (the carrier oscillates; reverse-bias peaks cluster at ~ -3.6 V and are
#  not part of the forward-bias bifurcation cascade we want to show).
PEAK_MIN_VOLTAGE = -1.0  # V

# Envelope smoothing window (samples)
# Should be >> carrier period (29 samples) but << AM period (~700 000 samples)
ENVELOPE_SMOOTH = 500    # samples  ≈ 0.5 ms

# Direction smoothing window for gradient calculation
DIRECTION_SMOOTH = 5000  # samples  ≈ 5 ms

# Plotting: stride keeps scatter plots fast without losing structure
PLOT_STRIDE   = 3        # use every Nth peak point

# Circuit label shown in the subplot title
CIRCUIT_LABEL = "1N4005 diode  |  L = 100 mH  |  R = 470 Ω  |  $A_\\mathrm{peak}$ = 7 V"

# Approximate bifurcation amplitudes (V) — from visual inspection of the map.
# Vertical dashed lines will be drawn at these positions.
# Update these after inspecting the plot if needed.
BIFURCATION_AMPLITUDES = {
    "Period 1→2": 3.0,
    "Period 2→4": 3.5,
}

# ── PLOT AESTHETICS ───────────────────────────────────────────────────────────

plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 13,
    'legend.fontsize': 10,
    'figure.dpi': 150,
})

COLOR_RISING  = 'steelblue'
COLOR_FALLING = 'crimson'

# ── FUNCTIONS ─────────────────────────────────────────────────────────────────

def load_csv(path):
    """
    Parse a Tektronix DPO CSV file.

    Returns
    -------
    t   : np.ndarray  — time axis (s)
    ch1 : np.ndarray  — CH1 voltage after Yzero correction (V)
    ch2 : np.ndarray  — CH2 voltage after Yzero correction (V)
    """
    t, ch1, ch2 = [], [], []
    with open(path, 'r', errors='replace') as f:
        reader = csv.reader(f)
        rows   = list(reader)

    for row in rows[17:]:
        try:
            t.append(float(row[3]))
            ch1.append(float(row[4])  + YZERO_CH1)
            ch2.append(float(row[10]) + YZERO_CH2)
        except (ValueError, IndexError):
            pass

    return np.array(t), np.array(ch1), np.array(ch2)


def hilbert_envelope(ch2):
    """
    Instantaneous amplitude envelope of CH2 via the analytic signal.

    The carrier is removed by subtracting the mean before applying the
    Hilbert transform; the result is the slowly-varying amplitude A(t).
    """
    analytic = hilbert(ch2 - ch2.mean())
    env      = np.abs(analytic)
    return uniform_filter1d(env, size=ENVELOPE_SMOOTH)


def extract_peaks(ch1):
    """
    Find local maxima of the diode voltage (one per carrier cycle).
    Peaks below PEAK_MIN_VOLTAGE are discarded — these are reverse-bias
    half-cycle peaks that are not part of the forward-bias bifurcation cascade.
    """
    peaks, _ = find_peaks(ch1,
                          distance=MIN_PEAK_DIST,
                          prominence=PEAK_PROMINENCE)
    peaks = peaks[ch1[peaks] >= PEAK_MIN_VOLTAGE]
    return peaks


def sweep_direction(env, peaks):
    """
    Boolean mask: True where the AM envelope is rising at each peak.

    A long smoothing window is used so the gradient reflects the global
    AM trend rather than carrier-cycle-to-cycle fluctuations.
    """
    env_smooth = uniform_filter1d(env, size=DIRECTION_SMOOTH)
    denv       = np.gradient(env_smooth)
    return denv[peaks] >= 0


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    file_list = sorted(glob.glob(os.path.join(DATA_DIR, FILE_PATTERN)))
    if not file_list:
        raise FileNotFoundError(f"No files matching '{FILE_PATTERN}' in '{DATA_DIR}'")

    print(f"Found {len(file_list)} file(s): {[os.path.basename(f) for f in file_list]}")

    datasets = []
    for path in file_list:
        label = os.path.splitext(os.path.basename(path))[0]
        print(f"  Loading {label}...", end=" ")

        t, ch1, ch2 = load_csv(path)
        env          = hilbert_envelope(ch2)
        peaks        = extract_peaks(ch1)
        rising       = sweep_direction(env, peaks)

        print(f"{len(peaks)} peaks  |  "
              f"rising={rising.sum()}  falling={(~rising).sum()}  |  "
              f"amp=[{env[peaks].min():.2f}, {env[peaks].max():.2f}] V  |  "
              f"diode peak=[{ch1[peaks].min():.2f}, {ch1[peaks].max():.2f}] V")

        datasets.append({
            'label':  label,
            't':      t,
            'ch1':    ch1,
            'env':    env,
            'peaks':  peaks,
            'rising': rising,
        })

    # ── 2D MATPLOTLIB PLOT ────────────────────────────────────────────────────
    fig = plt.figure(figsize=(12, 7))
    ax  = fig.add_subplot(111)

    fig.suptitle(
        'RLD Circuit — Continuous Bifurcation Map',
        fontsize=15, fontweight='bold', y=0.98
    )
    ax.set_title(
        CIRCUIT_LABEL + '\n' +
        r'AM sweep: carrier $\approx$ 34 kHz, $f_\mathrm{AM} \approx$ 0.7 Hz',
        fontsize=11, pad=10
    )

    for ds in datasets:
        pk  = ds['peaks']
        up  = ds['rising']
        env = ds['env']
        ch1 = ds['ch1']

        for mask, color, dlabel in [
                ( up, COLOR_RISING,
                  'Amplitude increasing'),
                (~up, COLOR_FALLING,
                  'Amplitude decreasing  (hysteresis visible at low drive)')]:
            idx = pk[mask][::PLOT_STRIDE]
            ax.scatter(env[idx], ch1[idx],
                       s=2, alpha=0.5, color=color,
                       label=dlabel, rasterized=True)

    # ── Bifurcation lines ──────────────────────────────────────────────────
    y_top = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 5.5
    for label, amp in BIFURCATION_AMPLITUDES.items():
        ax.axvline(amp, color='black', linestyle='--', linewidth=1.0, alpha=0.6)
        ax.text(amp + 0.03, 0.97, label,
                transform=ax.get_xaxis_transform(),
                fontsize=9, color='black', alpha=0.8,
                rotation=90, va='top', ha='left')

    # ── Hysteresis annotation ──────────────────────────────────────────────
    ax.annotate(
        'Hysteresis\n(upswing ≠ downswing)',
        xy=(1.05, 0.35), xytext=(1.4, 1.3),
        xycoords='data', textcoords='data',
        fontsize=9, color='black',
        arrowprops=dict(arrowstyle='->', color='black',
                        connectionstyle='arc3,rad=0.3'),
        bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='grey', alpha=0.8)
    )

    ax.set_xlabel('Drive Envelope Amplitude (V)', fontsize=13)
    ax.set_ylabel('Diode Peak Voltage (V)', fontsize=13)
    ax.grid(True, linestyle='--', alpha=0.3)

    handles, labels = ax.get_legend_handles_labels()
    # Deduplicate (multiple datasets would repeat labels)
    seen = {}
    for h, l in zip(handles, labels):
        if l not in seen:
            seen[l] = h
    ax.legend(seen.values(), seen.keys(), fontsize=10, loc='upper left',
              framealpha=0.9)

    plt.tight_layout()
    out_2d = os.path.join(DATA_DIR, 'bifurcation_continuous_2D.png')
    plt.savefig(out_2d, dpi=180, bbox_inches='tight')
    print(f"\nSaved 2D plot → {out_2d}")
    plt.show()

    # ── 3D PLOTLY INTERACTIVE PLOT ────────────────────────────────────────────
    try:
        import plotly.graph_objects as go

        fig3d = go.Figure()

        for ds in datasets:
            pk  = ds['peaks']
            up  = ds['rising']
            env = ds['env']
            ch1 = ds['ch1']
            t   = ds['t']

            for mask, color, dlabel in [
                    ( up, 'steelblue', 'Amplitude increasing'),
                    (~up, 'crimson',   'Amplitude decreasing')]:
                idx = pk[mask][::PLOT_STRIDE]
                fig3d.add_trace(go.Scatter3d(
                    x=t[idx] * 1e3,
                    y=env[idx],
                    z=ch1[idx],
                    mode='markers',
                    marker=dict(size=1.5, color=color, opacity=0.4),
                    name=dlabel,
                ))

        fig3d.update_layout(
            title=(
                'RLD Circuit — Continuous Bifurcation Map<br>'
                '<sup>1N4005 diode | L = 100 mH | R = 470 Ω | '
                'Carrier ≈ 34 kHz | AM ≈ 0.7 Hz | A_peak = 7 V</sup>'
            ),
            scene=dict(
                xaxis_title='Time (ms)',
                yaxis_title='Drive Amplitude (V)',
                zaxis_title='Diode Peak Voltage (V)',
                camera=dict(eye=dict(x=1.6, y=-1.8, z=0.7)),
            ),
            legend=dict(itemsizing='constant'),
            margin=dict(l=0, r=0, t=80, b=0),
            width=1100, height=700,
        )

        # Save next to this script (tracked by git, served via GitHub Pages).
        # include_plotlyjs='cdn' keeps the file ~130 KB instead of ~3 MB.
        out_3d = os.path.join(SCRIPT_DIR, 'bifurcation_continuous_3D.html')
        fig3d.write_html(out_3d, include_plotlyjs='cdn')
        print(f"Saved 3D interactive plot → {out_3d}")
        print("Commit and push, then view at:")
        print("  https://shakedsuki.github.io/HUJI-lab-b2/chaos/chaos/part2/bifurcation_continuous_3D.html")

    except ImportError:
        print("plotly not installed — skipping 3D plot.")
        print("Install with:  pip install plotly")


if __name__ == "__main__":
    main()
