# -*- coding: utf-8 -*-
"""
RLD Circuit — Continuous Bifurcation Map from AM-Modulated Sweep
=================================================================
Produces a 2D matplotlib figure (report-ready) and an interactive
3D plotly HTML (for exploration and rotation).

The 2D figure shows all detected peaks (unfiltered) — including both
the forward-bias bifurcation cascade and the ~-3.6 V reverse-bias cluster.
The 3D HTML uses only forward-bias peaks (V > PEAK_MIN_VOLTAGE) for clarity.

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
  - 2D scatter plot  (matplotlib PNG, saved to DATA_DIR, unfiltered)
  - 3D interactive   (plotly HTML, saved next to this script — tracked by git
                      and served via GitHub Pages, filtered to forward-bias only)

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
from scipy.signal import find_peaks, hilbert
from scipy.ndimage import uniform_filter1d

# Directory containing this script — HTML is saved here so it stays
# tracked by git and is not buried inside the gitignored samples/ tree.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

DATA_DIR      = r"chaos\part2\samples\AM"
FILE_PATTERN  = "7V.csv"          # single recording (7V_2.csv is identical)

# Oscilloscope Yzero offsets (read from CSV metadata, row 13)
# Actual voltage = stored value + YZERO
YZERO_CH1     = -2.78   # V
YZERO_CH2     =  4.18   # V

SAMPLE_RATE   = 1e6     # Hz  (1 MS/s)
DT            = 1.0 / SAMPLE_RATE   # s per sample  (1 μs)

# Carrier frequency — sets peak-finding minimum distance
F_CARRIER_HZ  = 34_000  # Hz  (confirmed by FFT)
MIN_PEAK_DIST = int(0.6 / F_CARRIER_HZ / DT)   # ≈ 0.6 × carrier period

# Peak prominence threshold — rejects noise spikes below this height
PEAK_PROMINENCE = 0.15  # V

# Voltage threshold for the 3D HTML only — separates the two peak families:
#   forward-bias peaks  : ~  -1 V … +5.4 V  (bifurcation cascade)
#   reverse-bias peaks  : ~ -3.6 V           (diode hard-blocked, constant)
# The 2D plot is always unfiltered. Any value in [-2.8, -2.0] cleanly
# separates the two families (gap between them is ~1 V wide).
PEAK_MIN_VOLTAGE = -2.8  # V  (applied to 3D only)

# Envelope smoothing
ENVELOPE_SMOOTH  = 500   # samples ≈ 0.5 ms
DIRECTION_SMOOTH = 5000  # samples ≈ 5 ms

# Scatter plot stride — use every Nth peak for speed without losing structure
PLOT_STRIDE = 3

# Circuit description for plot titles
CIRCUIT_LABEL = (
    "1N4005 diode  |  L = 100 mH  |  R = 470 Ω  |  "
    r"$A_\mathrm{peak}$ = 7 V"
)

# Approximate bifurcation amplitudes (V) — dashed guide-lines on the 2D plot.
# Estimated from visual inspection; update after examining the figure.
BIFURCATION_AMPLITUDES = {
    "Period 1→2": 3.0,
    "Period 2→4": 3.5,
}

# ── PLOT AESTHETICS ───────────────────────────────────────────────────────────

plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 13,
    'axes.titlesize': 12,
    'legend.fontsize': 10,
    'figure.dpi': 150,
})

COLOR_RISING  = 'steelblue'
COLOR_FALLING = 'crimson'

# ── FUNCTIONS ─────────────────────────────────────────────────────────────────

def load_csv(path):
    """Parse a Tektronix DPO CSV. Returns (t, ch1, ch2) as numpy arrays."""
    t, ch1, ch2 = [], [], []
    with open(path, 'r', errors='replace') as f:
        rows = list(csv.reader(f))
    for row in rows[17:]:
        try:
            t.append(float(row[3]))
            ch1.append(float(row[4])  + YZERO_CH1)
            ch2.append(float(row[10]) + YZERO_CH2)
        except (ValueError, IndexError):
            pass
    return np.array(t), np.array(ch1), np.array(ch2)


def hilbert_envelope(ch2):
    """Instantaneous amplitude envelope via analytic signal of zero-meaned CH2."""
    env = np.abs(hilbert(ch2 - ch2.mean()))
    return uniform_filter1d(env, size=ENVELOPE_SMOOTH)


def extract_peaks(ch1, min_voltage=None):
    """
    Find diode voltage local maxima (one per carrier cycle).

    Parameters
    ----------
    min_voltage : float or None
        If given, discard peaks below this voltage.
        Pass None for fully unfiltered output.
    """
    peaks, _ = find_peaks(ch1, distance=MIN_PEAK_DIST, prominence=PEAK_PROMINENCE)
    if min_voltage is not None:
        peaks = peaks[ch1[peaks] >= min_voltage]
    return peaks


def sweep_direction(env, peaks):
    """True where the AM envelope gradient is positive (amplitude rising)."""
    denv = np.gradient(uniform_filter1d(env, size=DIRECTION_SMOOTH))
    return denv[peaks] >= 0


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    file_list = sorted(glob.glob(os.path.join(DATA_DIR, FILE_PATTERN)))
    if not file_list:
        raise FileNotFoundError(f"No files matching '{FILE_PATTERN}' in '{DATA_DIR}'")

    print(f"Found {len(file_list)} file(s): {[os.path.basename(f) for f in file_list]}")

    path  = file_list[0]
    label = os.path.splitext(os.path.basename(path))[0]
    print(f"  Loading {label}...", end=" ", flush=True)

    t, ch1, ch2 = load_csv(path)
    env          = hilbert_envelope(ch2)

    # Unfiltered — 2D plot shows everything
    peaks_all  = extract_peaks(ch1, min_voltage=None)
    rising_all = sweep_direction(env, peaks_all)

    # Filtered — 3D HTML uses forward-bias peaks only
    peaks_filt  = extract_peaks(ch1, min_voltage=PEAK_MIN_VOLTAGE)
    rising_filt = sweep_direction(env, peaks_filt)

    print(
        f"{len(peaks_all)} peaks total  |  "
        f"{len(peaks_filt)} forward-bias (V > {PEAK_MIN_VOLTAGE} V)"
    )

    # ── 2D PLOT — single panel, unfiltered ────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 7))

    fig.suptitle(
        'RLD Circuit — Continuous Bifurcation Map',
        fontsize=15, fontweight='bold', y=0.99
    )
    ax.set_title(
        CIRCUIT_LABEL + '\n'
        r'AM sweep: carrier $\approx$ 34 kHz,  $f_\mathrm{AM} \approx$ 0.7 Hz',
        fontsize=11, pad=10
    )

    for mask, color, dlabel in [
            ( rising_all, COLOR_RISING,  'Amplitude increasing'),
            (~rising_all, COLOR_FALLING, 'Amplitude decreasing')]:
        idx = peaks_all[mask][::PLOT_STRIDE]
        ax.scatter(env[idx], ch1[idx],
                   s=2, alpha=0.5, color=color,
                   label=dlabel, rasterized=True)

    # Bifurcation guide-lines
    for blabel, amp in BIFURCATION_AMPLITUDES.items():
        ax.axvline(amp, color='black', linestyle='--', linewidth=0.9, alpha=0.55)
        ax.text(amp + 0.03, 0.97, blabel,
                transform=ax.get_xaxis_transform(),
                fontsize=9, color='black', alpha=0.75,
                rotation=90, va='top', ha='left')

    ax.set_xlabel('Drive Envelope Amplitude (V)', fontsize=13)
    ax.set_ylabel('Diode Peak Voltage (V)', fontsize=13)
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.legend(fontsize=10, loc='upper left', framealpha=0.9)

    plt.tight_layout()
    out_2d = os.path.join(DATA_DIR, 'bifurcation_continuous_2D.png')
    plt.savefig(out_2d, dpi=180, bbox_inches='tight')
    print(f"\nSaved 2D plot → {out_2d}")
    plt.show()

    # ── 3D PLOTLY — filtered data only ────────────────────────────────────────
    try:
        import plotly.graph_objects as go

        fig3d = go.Figure()
        for mask, color, dlabel in [
                ( rising_filt, 'steelblue', 'Amplitude increasing'),
                (~rising_filt, 'crimson',   'Amplitude decreasing')]:
            idx = peaks_filt[mask][::PLOT_STRIDE]
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
                '<sup>1N4005 | L = 100 mH | R = 470 Ω | '
                'Carrier ≈ 34 kHz | AM ≈ 0.7 Hz | A_peak = 7 V | '
                f'forward-bias peaks only (V > {PEAK_MIN_VOLTAGE} V)</sup>'
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
        print("plotly not installed — skipping 3D plot.  pip install plotly")


if __name__ == "__main__":
    main()
