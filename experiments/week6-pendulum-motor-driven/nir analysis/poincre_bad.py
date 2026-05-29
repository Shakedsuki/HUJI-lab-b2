# -*- coding: utf-8 -*-
"""
Created on Mon May 25 15:24:34 2026

@author: cohen
"""

"""
Double Pendulum – Interactive Phase Space Explorer
===================================================
Usage:
    python phase_space_explorer.py [root_dir]

root_dir  – folder that contains one sub-folder per run, e.g.
            3.2V_0.9Hz/tracking.csv
            3.2V_0.91Hz/tracking.csv   …
            Defaults to the current working directory.

CSV columns expected (as produced by your tracker):
    frame, time_s, phase, x_green, y_green, x_red, y_red,
    theta1_deg, theta2_deg, dropout

Controls:
    • Check-boxes (left)  – show / hide individual drive frequencies
    • Slider (bottom)     – shift the stroboscopic phase offset (0 → 1 period)

Four phase-space panels:
    θ₁ vs ω₁  |  θ₂ vs ω₂
    θ₁ vs θ₂  |  ω₁ vs ω₂
"""

import os
import re
import sys
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import CheckButtons, Slider
from scipy.signal import savgol_filter

# ── Configuration ─────────────────────────────────────────────────────────────
SAVGOL_WINDOW = 15          # Savitzky-Golay window for dθ/dt  (must be odd)
SAVGOL_POLY   = 3           # polynomial order
FADE_ALPHA    = 0.09        # opacity of background trajectory
FADE_SIZE     = 1.0         # point size of background trajectory
STROB_ALPHA   = 0.95        # opacity of stroboscopic highlights
STROB_SIZE    = 24          # marker size of stroboscopic highlights
STROB_EDGE    = 0.35        # white edge width on stroboscopic markers
BG_COLOR      = '#0b0b14'
PANEL_COLOR   = '#10101e'
GRID_COLOR    = '#1e1e38'
CMAP          = plt.cm.plasma   # colormap: one colour per frequency

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_freq(folder_name: str) -> float | None:
    """Extract drive frequency from folder name like '3.2V_1.15Hz'."""
    m = re.search(r'_([\d.]+)[Hh]z', folder_name)
    return float(m.group(1)) if m else None


def load_datasets(root: str) -> dict:
    """
    Walk *root*, load every tracking.csv found in a frequency-named sub-folder.
    Returns  { freq_float: { 't', 'θ1', 'θ2', 'ω1', 'ω2' } }
    """
    out = {}
    entries = sorted(
        (e for e in os.scandir(root) if e.is_dir()),
        key=lambda e: e.name
    )
    for entry in entries:
        freq = parse_freq(entry.name)
        if freq is None:
            continue
        csv_path = os.path.join(entry.path, 'tracking.csv')
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            print(f"[warn] could not read {csv_path}: {exc}")
            continue

        df = df[df['dropout'] == 0].reset_index(drop=True)
        t  = df['time_s'].to_numpy(dtype=float)
        θ1 = df['theta1_deg'].to_numpy(dtype=float)
        θ2 = df['theta2_deg'].to_numpy(dtype=float)

        if len(t) < SAVGOL_WINDOW + 2:
            print(f"[warn] {entry.name}: too few points, skipping")
            continue

        dt = float(np.median(np.diff(t)))
        ω1 = savgol_filter(θ1, SAVGOL_WINDOW, SAVGOL_POLY, deriv=1, delta=dt)
        ω2 = savgol_filter(θ2, SAVGOL_WINDOW, SAVGOL_POLY, deriv=1, delta=dt)

        out[freq] = dict(t=t, θ1=θ1, θ2=θ2, ω1=ω1, ω2=ω2)
        print(f"  loaded  {entry.name:<25}  n={len(t)}  dt≈{dt*1000:.2f} ms")

    return out


def strob_indices(t: np.ndarray, freq: float, phase_offset: float) -> np.ndarray:
    """
    Return frame indices nearest to stroboscopic times:
        t_n = t[0] + phase_offset * T  +  n * T
    Uses np.searchsorted so it works even when the video frame-rate
    is not a multiple of the drive frequency.
    """
    T       = 1.0 / freq
    t_start = t[0] + phase_offset * T
    # targets spread across the whole recording
    targets = np.arange(t_start, t[-1] + T * 0.5, T)
    idx     = np.searchsorted(t, targets)
    idx     = np.clip(idx, 0, len(t) - 1)
    # keep only indices where the nearest sample is within half a period
    keep    = np.abs(t[idx] - targets) < T * 0.5
    return np.unique(idx[keep])


def get_xy(data: dict, panel_idx: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (x, y) arrays for the given panel."""
    match panel_idx:
        case 0: return data['θ1'], data['ω1']
        case 1: return data['θ2'], data['ω2']
        case 2: return data['θ1'], data['θ2']
        case _: return data['ω1'], data['ω2']


# ── Load ──────────────────────────────────────────────────────────────────────
root     = r"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\experiments\week6-pendulum-motor-driven\measurements"  # Directory containing your folders (e.g., ".")

print(f"Scanning  {os.path.abspath(root)}")
datasets = load_datasets(root)

if not datasets:
    sys.exit("No datasets found. "
             "Make sure sub-folders follow the pattern  *_<freq>Hz  "
             "and each contains  tracking.csv")

freqs   = sorted(datasets.keys())
N       = len(freqs)
f_colors = {f: CMAP(i / max(N - 1, 1)) for i, f in enumerate(freqs)}

print(f"\n{N} frequencies loaded: {[f'{f:.3g} Hz' for f in freqs]}")

# ── Figure layout ─────────────────────────────────────────────────────────────
plt.style.use('dark_background')
fig = plt.figure(figsize=(17, 9.5), facecolor=BG_COLOR)
fig.suptitle(
    "Double Pendulum  ·  Phase Space Explorer  ·  3.2 V drive",
    color='white', fontsize=12, y=0.995, fontweight='bold'
)

# GridSpec:  [ checkboxes | 2×2 panels | legend ]
#            [            | slider     |        ]
gs = gridspec.GridSpec(
    3, 3, figure=fig,
    left=0.17, right=0.98, top=0.97, bottom=0.07,
    wspace=0.40, hspace=0.50,
    width_ratios=[1, 1, 0.38],
    height_ratios=[1, 1, 0.06]
)

ax_panels = [
    fig.add_subplot(gs[0, 0]),   # θ₁ vs ω₁
    fig.add_subplot(gs[0, 1]),   # θ₂ vs ω₂
    fig.add_subplot(gs[1, 0]),   # θ₁ vs θ₂
    fig.add_subplot(gs[1, 1]),   # ω₁ vs ω₂
]
ax_legend = fig.add_subplot(gs[0:2, 2])
ax_slider = fig.add_subplot(gs[2, 0:2])

PANEL_CFG = [
    ("Pendulum 1  —  θ₁ vs ω₁", "θ₁  (°)",   "ω₁  (°/s)"),
    ("Pendulum 2  —  θ₂ vs ω₂", "θ₂  (°)",   "ω₂  (°/s)"),
    ("Coupled angles  —  θ₁ vs θ₂", "θ₁  (°)", "θ₂  (°)"),
    ("Coupled rates   —  ω₁ vs ω₂", "ω₁  (°/s)", "ω₂  (°/s)"),
]


def style_panel(ax, title, xl, yl):
    ax.set_facecolor(PANEL_COLOR)
    ax.set_title(title, color='white', fontsize=8.5, pad=4, fontweight='semibold')
    ax.set_xlabel(xl, color='#999999', fontsize=7.5, labelpad=2)
    ax.set_ylabel(yl, color='#999999', fontsize=7.5, labelpad=2)
    ax.tick_params(colors='#777777', labelsize=6.5)
    for sp in ax.spines.values():
        sp.set_edgecolor('#2a2a50')
    ax.grid(True, color=GRID_COLOR, linewidth=0.5, alpha=0.7)


for ax, (title, xl, yl) in zip(ax_panels, PANEL_CFG):
    style_panel(ax, title, xl, yl)

# Legend / info panel
ax_legend.axis('off')
ax_legend.set_facecolor(BG_COLOR)
ax_legend.set_title("Drive frequency", color='white', fontsize=8,
                    pad=6, fontweight='semibold', loc='left', x=0.05)

for f in freqs:
    ax_legend.plot([], [], 'o', color=f_colors[f], markersize=5.5,
                   label=f"{f:.3g} Hz")
leg = ax_legend.legend(
    loc='upper left', fontsize=6.8, framealpha=0,
    labelcolor='white', handlelength=0.8, handletextpad=0.6,
    borderpad=0.3, labelspacing=0.35,
    ncols=2 if N > 14 else 1,
    bbox_to_anchor=(0.02, 0.97)
)

# Slider
slider = Slider(
    ax_slider, 'Strobe  phase  offset',
    0.0, 1.0, valinit=0.0,
    color='#5566ff', track_color='#1c1c38'
)
slider.label.set_color('white')
slider.label.set_fontsize(8)
slider.valtext.set_color('#aaaacc')
slider.valtext.set_fontsize(8)

# Annotation for stroboscopic count
strob_text = ax_slider.text(
    0.5, -0.65, '', transform=ax_slider.transAxes,
    ha='center', va='top', color='#8888bb', fontsize=7
)

# ── CheckButtons ──────────────────────────────────────────────────────────────
cb_labels  = [f"{f:.3g} Hz" for f in freqs]
cb_checked = [True] * N

ax_chk = fig.add_axes([0.005, 0.07, 0.155, 0.90], facecolor=BG_COLOR)
ax_chk.set_title("Frequencies", color='white', fontsize=8,
                  pad=4, fontweight='semibold')

chk = CheckButtons(
    ax_chk, cb_labels, cb_checked,
    frame_props=dict(
        edgecolor=[f_colors[f] for f in freqs],
        facecolor=[BG_COLOR] * N,
        linewidth=1.4,
    ),
    check_props=dict(
        color=[f_colors[f] for f in freqs],
        linewidth=1.8,
    ),
)
for lbl in chk.labels:
    lbl.set_color('white')
    lbl.set_fontsize(7.0)

# ── Scatter store ─────────────────────────────────────────────────────────────
# bg_sc[f][panel_idx]    – faded background  (created once, visibility toggled)
# strob_sc[f][panel_idx] – stroboscopic dots (removed & recreated on offset change)
bg_sc:    dict[float, list] = {}
strob_sc: dict[float, list] = {}


def _add_bg(f: float) -> None:
    d     = datasets[f]
    scs   = []
    for ai, ax in enumerate(ax_panels):
        x, y = get_xy(d, ai)
        sc = ax.scatter(
            x, y,
            s=FADE_SIZE, alpha=FADE_ALPHA,
            color=f_colors[f], linewidths=0, rasterized=True
        )
        scs.append(sc)
    bg_sc[f] = scs


def _add_strob(f: float, phase: float) -> None:
    d   = datasets[f]
    idx = strob_indices(d['t'], f, phase)
    scs = []
    for ai, ax in enumerate(ax_panels):
        x, y = get_xy(d, ai)
        sc = ax.scatter(
            x[idx], y[idx],
            s=STROB_SIZE, alpha=STROB_ALPHA,
            color=f_colors[f],
            edgecolors='white', linewidths=STROB_EDGE,
            zorder=5, rasterized=False
        )
        scs.append(sc)
    strob_sc[f] = scs
    return len(idx)


def _remove_strob(f: float) -> None:
    if f in strob_sc:
        for sc in strob_sc[f]:
            sc.remove()
        del strob_sc[f]


def _active_freqs() -> list[float]:
    return [f for f, on in zip(freqs, chk.get_status()) if on]


def _update_strob_text(phase: float) -> None:
    active = _active_freqs()
    if not active:
        strob_text.set_text('')
        return
    # Show how many stroboscopic points are visible for each active freq
    parts = []
    for f in active:
        n = len(strob_indices(datasets[f]['t'], f, phase))
        parts.append(f"{f:.3g} Hz → {n} pts")
    strob_text.set_text('  |  '.join(parts))


# ── Callbacks ─────────────────────────────────────────────────────────────────

def on_slider(val: float) -> None:
    """Recompute and redraw only the stroboscopic markers."""
    active = set(_active_freqs())
    # Remove all existing strob scatters
    for f in list(strob_sc.keys()):
        _remove_strob(f)
    # Recreate for active frequencies
    for f in active:
        _add_strob(f, val)
    _update_strob_text(val)
    fig.canvas.draw_idle()


def on_check(label: str) -> None:
    """Toggle background + strobe for the clicked frequency."""
    idx = cb_labels.index(label)
    f   = freqs[idx]
    is_on = chk.get_status()[idx]

    # Toggle background
    for sc in bg_sc[f]:
        sc.set_visible(is_on)

    # Toggle stroboscopic dots
    if is_on:
        _add_strob(f, slider.val)
    else:
        _remove_strob(f)

    _update_strob_text(slider.val)
    fig.canvas.draw_idle()


# ── Initialise plots ──────────────────────────────────────────────────────────
print("\nRendering background trajectories …")
for f in freqs:
    _add_bg(f)

print("Adding stroboscopic markers …")
for f in freqs:
    _add_strob(f, 0.0)

_update_strob_text(0.0)

slider.on_changed(on_slider)
chk.on_clicked(on_check)

print("Ready — showing window.\n")
plt.show()