# -*- coding: utf-8 -*-
"""
RLD Circuit — Continuous Bifurcation Map from AM-Modulated Sweep
=================================================================
Produces both a 2D matplotlib figure (report-ready) and an interactive
3D plotly HTML (for exploration and rotation).

The 2D figure contains two side-by-side panels:
  Left  — unfiltered: all detected peaks including the ~-3.6 V
           reverse-bias cluster, for completeness and transparency.
  Right — filtered: only forward-bias peaks (V_peak > PEAK_MIN_VOLTAGE),
           so the bifurcation cascade fills the full y-axis.

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
  - 2D figure with two panels (matplotlib PNG, saved to DATA_DIR)
  - 3D interactive HTML (saved next to this script — tracked by git
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
from scipy.signal import find_peaks, hilbert
from scipy.ndimage import uniform_filter1d

# Directory containing this script — HTML is saved here so it stays
# tracked by git and is not buried inside the gitignored samples/ tree.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

DATA_DIR      = r"samples\AM"
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

# Voltage threshold separating the two peak families:
#   forward-bias peaks  : ~  -1 V … +5.4 V   (show bifurcation cascade)
#   reverse-bias peaks  : ~ -3.6 V            (diode hard-blocked, constant)
# The gap between the families is ~1 V wide; any threshold in [-2.8, -2.0]
# cleanly separates them.
PEAK_MIN_VOLTAGE = -2.8  # V  — applied in the filtered panel only

# Envelope smoothing
ENVELOPE_SMOOTH  = 500   # samples ≈ 0.5 ms
DIRECTION_SMOOTH = 5000  # samples ≈ 5 ms

# Scatter plot stride — keep every Nth peak for speed
PLOT_STRIDE = 3

# Circuit description shown in plot titles
CIRCUIT_LABEL = (
    "1N4005 diode  |  L = 100 mH  |  R = 470 Ω  |  "
    r"$A_\mathrm{peak}$ = 7 V"
)

# Approximate bifurcation amplitudes for dashed guide-lines (V).
# Estimated from visual inspection — update after examining the filtered panel.
BIFURCATION_AMPLITUDES = {
    "Period 1→2": 3.0,
    "Period 2→4": 3.5,
}

# ── PLOT AESTHETICS ───────────────────────────────────────────────────────────

plt.rcParams.update({
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 12,
    'legend.fontsize': 9,
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
        If given, discard peaks below this voltage (reverse-bias filter).
        Pass None for the unfiltered version.
    """
    peaks, _ = find_peaks(ch1, distance=MIN_PEAK_DIST, prominence=PEAK_PROMINENCE)
    if min_voltage is not None:
        peaks = peaks[ch1[peaks] >= min_voltage]
    return peaks


def sweep_direction(env, peaks):
    """True where the AM envelope gradient is positive (amplitude rising)."""
    denv = np.gradient(uniform_filter1d(env, size=DIRECTION_SMOOTH))
    return denv[peaks] >= 0


def scatter_panel(ax, env, ch1, peaks, rising, title, annotate_hysteresis=False):
    """
    Draw one bifurcation scatter panel onto ax.

    Parameters
    ----------
    annotate_hysteresis : bool
        If True, add the hysteresis arrow annotation.
    """
    for mask, color, dlabel in [
            ( rising, COLOR_RISING,  'Amplitude increasing'),
            (~rising, COLOR_FALLING,
             'Amplitude decreasing  (hysteresis at low drive)')]:
        idx = peaks[mask][::PLOT_STRIDE]
        ax.scatter(env[idx], ch1[idx],
                   s=2, alpha=0.5, color=color,
                   label=dlabel, rasterized=True)

    # Bifurcation guide-lines
    for label, amp in BIFURCATION_AMPLITUDES.items():
        ax.axvline(amp, color='black', linestyle='--', linewidth=0.9, alpha=0.55)
        ax.text(amp + 0.03, 0.97, label,
                transform=ax.get_xaxis_transform(),
                fontsize=8, color='black', alpha=0.75,
                rotation=90, va='top', ha='left')

    if annotate_hysteresis:
        ax.annotate(
            'Hysteresis\n(upswing ≠ downswing)',
            xy=(1.0, -0.7), xytext=(1.6, -0.4),
            xycoords='data', textcoords='data',
            fontsize=8, color='black',
            arrowprops=dict(arrowstyle='->', color='black',
                            connectionstyle='arc3,rad=-0.2'),
            bbox=dict(boxstyle='round,pad=0.3', fc='white', ec='grey', alpha=0.85)
        )

    ax.set_title(title, fontsize=11, pad=8)
    ax.set_xlabel('Drive Envelope Amplitude (V)')
    ax.set_ylabel('Diode Peak Voltage (V)')
    ax.grid(True, linestyle='--', alpha=0.3)

    handles, labels = ax.get_legend_handles_labels()
    seen = {}
    for h, l in zip(handles, labels):
        if l not in seen:
            seen[l] = h
    ax.legend(seen.values(), seen.keys(), fontsize=8, loc='upper left',
              framealpha=0.9)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    file_list = sorted(glob.glob(os.path.join(DATA_DIR, FILE_PATTERN)))
    if not file_list:
        raise FileNotFoundError(f"No files matching '{FILE_PATTERN}' in '{DATA_DIR}'")

    print(f"Found {len(file_list)} file(s): {[os.path.basename(f) for f in file_list]}")

    # Use only the first file (7V_2.csv confirmed identical to 7V.csv)
    path  = file_list[0]
    label = os.path.splitext(os.path.basename(path))[0]
    print(f"  Loading {label}...", end=" ", flush=True)

    t, ch1, ch2 = load_csv(path)
    env          = hilbert_envelope(ch2)

    peaks_all      = extract_peaks(ch1, min_voltage=None)
    peaks_filtered = extract_peaks(ch1, min_voltage=PEAK_MIN_VOLTAGE)

    rising_all      = sweep_direction(env, peaks_all)
    rising_filtered = sweep_direction(env, peaks_filtered)

    print(
        f"{len(peaks_all)} peaks total  |  "
        f"{len(peaks_filtered)} after filter (V > {PEAK_MIN_VOLTAGE} V)"
    )

    # ── 2D FIGURE: two side-by-side panels ────────────────────────────────────
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(16, 7),
                                             sharey=False)

    fig.suptitle(
        'RLD Circuit — Continuous Bifurcation Map\n' + CIRCUIT_LABEL + '\n'
        r'AM sweep: carrier $\approx$ 34 kHz,  $f_\mathrm{AM} \approx$ 0.7 Hz',
        fontsize=13, fontweight='bold', y=1.01
    )

    scatter_panel(
        ax_left,  env, ch1, peaks_all,      rising_all,
        title='All peaks  (unfiltered)',
        annotate_hysteresis=False,
    )

    scatter_panel(
        ax_right, env, ch1, peaks_filtered, rising_filtered,
        title=f'Forward-bias peaks only  ($V_\\mathrm{{peak}} > {PEAK_MIN_VOLTAGE}$ V)',
        annotate_hysteresis=True,
    )

    # Shared note about the reverse-bias cluster
    fig.text(
        0.5, -0.02,
        f'Left panel: reverse-bias peaks cluster at ≈ −3.6 V (diode hard-blocked, constant with amplitude) '
        f'are excluded in the right panel by the threshold V > {PEAK_MIN_VOLTAGE} V.',
        ha='center', fontsize=9, color='grey', style='italic'
    )

    plt.tight_layout()
    out_2d = os.path.join(DATA_DIR, 'bifurcation_continuous_2D.png')
    plt.savefig(out_2d, dpi=180, bbox_inches='tight')
    print(f"\nSaved 2D figure → {out_2d}")
    plt.show()

    # ── 3D PLOTLY: filtered data only (cleaner for interactive exploration) ───
    try:
        import plotly.graph_objects as go

        fig3d = go.Figure()
        for mask, color, dlabel in [
                ( rising_filtered, 'steelblue', 'Amplitude increasing'),
                (~rising_filtered, 'crimson',   'Amplitude decreasing')]:
            idx = peaks_filtered[mask][::PLOT_STRIDE]
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

        out_3d = os.path.join(SCRIPT_DIR, 'bifurcation_continuous_3D.html')
        # include_plotlyjs=True inlines plotly.js (~3 MB) so the file is fully
        # self-contained — works offline and is immune to CDN URL changes.
        fig3d.write_html(out_3d, include_plotlyjs=True)
        print(f"Saved 3D interactive plot → {out_3d}")
        print("Commit and push, then view at:")
        print("  https://shakedsuki.github.io/HUJI-lab-b2/")

    except ImportError:
        print("plotly not installed — skipping 3D plot.  pip install plotly")


if __name__ == "__main__":
    main()
