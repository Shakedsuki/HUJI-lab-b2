"""
analysis_plot.py
-----------------
Physics sanity check for double pendulum tracking data.

Produces a 6-panel figure:
  1. theta1(t) — arm 1 angle vs time
  2. theta2(t) — arm 2 angle vs time
  3. Phase portrait arm 1: theta1 vs omega1
  4. Phase portrait arm 2: theta2 vs omega2
  5. Configuration space:   theta1 vs theta2
  6. Poincare-style return map: theta1[n+1] vs theta1[n]  (at omega1 sign changes)

Angular velocities computed via Savitzky-Golay derivative (window=11, poly=3).

Usage:
  # Mode 1 — measurement folder (preferred for pipeline use):
  python scripts/analysis/phase_panels.py --stem th1_p044_th2_m001

  # Mode 2 — explicit CSV path:
  python scripts/analysis/phase_panels.py measurements/th1_p044_th2_m001/tracking.csv

  # Mode 3 — interactive plt.show() (no args):
  python scripts/analysis/phase_panels.py
"""

import sys

# Force UTF-8 stdout so unicode glyphs (θ, ω) don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
import os
import csv

from rich.console import Console
console = Console()
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import savgol_filter

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV = os.path.join(MEAS_DIR, "th1_p180_th2_m179", "tracking.csv")

def parse_args():
    p = argparse.ArgumentParser(
        description="6-panel physics sanity figure.")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to tracking CSV (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p044_th2_m001. "
                        "Resolves CSV and output dir from measurements/.")
    p.add_argument("--save", action="store_true",
                   help="Save PNG instead of plt.show().")
    return p.parse_args()

def resolve_paths(args):
    """Returns (csv_path, output_dir, stem_label, force_save)."""
    if args.stem:
        meas_dir = clip_dir(args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            console.print(f"[red]ERROR:[/] tracking.csv not found for stem '{args.stem}'")
            console.print(f"  [dim]Expected: {csv_path}[/]")
            sys.exit(1)
        return csv_path, meas_dir, args.stem, True

    if args.csv:
        csv_path = args.csv if os.path.isabs(args.csv) \
                   else os.path.join(REPO_ROOT, args.csv)
        output_dir = os.path.dirname(csv_path) or LEGACY_OUT
        stem_label = os.path.basename(output_dir) or \
                     os.path.splitext(os.path.basename(csv_path))[0]
        return csv_path, output_dir, stem_label, args.save

    return DEFAULT_CSV, LEGACY_OUT, "long_recording", args.save

# Savitzky-Golay parameters
SG_WINDOW = 11   # must be odd
SG_POLY   = 3    # polynomial order

FPS = 59.94      # used only if CSV timestamps look wrong

# Canonical color scheme
COLOR_CONFIG = 'tab:blue'    # configuration space
COLOR_ARM1   = 'tab:green'   # arm 1 / green physical marker
COLOR_ARM2   = 'tab:red'     # arm 2 / red physical marker

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

def load_csv(path):
    """
    Load tracking CSV. Returns arrays for the FREE_SWING phase only.
    Skips dropout frames for clean analysis.
    """
    rows = list(csv.DictReader(open(path)))

    free = [
        r for r in rows
        if r['phase'] in ('free_swing', 'driven')
        and r['dropout'] == '0'
        and r['theta1_deg'] != ''
        and r['theta2_deg'] != ''
    ]

    if not free:
        raise ValueError("No clean free_swing frames found in CSV.")

    t   = np.array([float(r['time_s'])     for r in free])
    th1 = np.array([float(r['theta1_deg']) for r in free])
    th2 = np.array([float(r['theta2_deg']) for r in free])

    # Normalise time to start at 0
    t = t - t[0]

    return t, th1, th2

# ─────────────────────────────────────────────
# DERIVATIVES
# ─────────────────────────────────────────────

def compute_velocities(t, th1, th2):
    """
    Compute angular velocities using Savitzky-Golay differentiation.

    Critical: the angles in the CSV are wrapped to [-180, 180]. SG'ing the
    wrapped series produces ~360°/frame phantom spikes at every wrap,
    which smear into 5000+ deg/s plateaus when the SG window crosses one.
    We np.unwrap first so the derivative reflects the physical pendulum
    motion across the inverted position.

    Returns om1, om2 in deg/s.
    """
    dt = np.mean(np.diff(t))   # mean frame interval (should be ~1/60 s)

    th1u = np.degrees(np.unwrap(np.radians(th1)))
    th2u = np.degrees(np.unwrap(np.radians(th2)))

    om1 = savgol_filter(th1u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    return om1, om2

# ─────────────────────────────────────────────
# WRAP-AWARE LINE PLOTTING
# ─────────────────────────────────────────────

def wrap_break_mask(theta, threshold=180.0):
    """Boolean mask of length N-1 marking positions where consecutive
    samples jump by more than `threshold` degrees (= a wrap discontinuity)."""
    return np.abs(np.diff(theta)) > threshold

def insert_breaks(arrays, break_mask):
    """
    Insert NaN at the positions indicated by break_mask in each array of
    `arrays` (all arrays must have the same length N; mask has length N-1).
    matplotlib renders NaN as a gap, breaking the connecting line cleanly.
    """
    if not break_mask.any():
        return tuple(np.asarray(a, dtype=float) for a in arrays)
    break_idx = np.where(break_mask)[0]
    out = []
    for a in arrays:
        a = np.asarray(a, dtype=float)
        pieces, last = [], 0
        for bi in break_idx:
            pieces.append(a[last:bi + 1])
            pieces.append(np.array([np.nan]))
            last = bi + 1
        pieces.append(a[last:])
        out.append(np.concatenate(pieces))
    return tuple(out)

# ─────────────────────────────────────────────
# POINCARE SECTION
# ─────────────────────────────────────────────

def poincare_crossings(th1, om1):
    """
    Find indices where omega1 crosses zero from positive to negative
    (downward crossing of theta1 velocity).
    Returns theta1 values at successive crossings: (th1[n], th1[n+1]).
    """
    crossings = []
    for i in range(1, len(om1)):
        if om1[i - 1] > 0 and om1[i] <= 0:   # sign change
            crossings.append(th1[i])

    if len(crossings) < 2:
        return np.array([]), np.array([])

    return np.array(crossings[:-1]), np.array(crossings[1:])

# ─────────────────────────────────────────────
# PER-PANEL DRAWS  (shared by the 6-panel figure and the palette tiles)
# ─────────────────────────────────────────────
# compact=True strips labels/colourbars/ticks for small aggregate tiles
# (cf. theta2_timeseries.draw_theta2); the full form IS the per-clip figure,
# so the palette can never drift from what each clip actually looks like.

def _compact_ax(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_linewidth(0.5)

def draw_phase1(ax, t, th1, om1, *, compact=False):
    """Phase portrait — arm 1 (θ₁ vs ω₁), green. Returns the scatter handle
    (None when compact) so the caller can attach a colourbar."""
    if compact:
        ax.scatter(th1, om1, c=COLOR_ARM1, s=1, alpha=0.35, linewidths=0)
        ax.axhline(0, color='0.85', lw=0.4)
        ax.axvline(0, color='0.85', lw=0.4)
        _compact_ax(ax)
        return None
    norm = plt.Normalize(t.min(), t.max())
    sc = ax.scatter(th1, om1, c=t, cmap=plt.cm.Greens, s=2, alpha=0.8, norm=norm)
    ax.set_xlabel('θ₁ (deg)')
    ax.set_ylabel('ω₁ (deg/s)')
    ax.set_title('Phase portrait — arm 1')
    ax.axhline(0, color='gray', lw=0.5, ls='--')
    ax.axvline(0, color='gray', lw=0.5, ls='--')
    ax.grid(True, alpha=0.3)
    return sc

def draw_phase2(ax, t, th2, om2, *, compact=False):
    """Phase portrait — arm 2 (θ₂ vs ω₂), red."""
    if compact:
        ax.scatter(th2, om2, c=COLOR_ARM2, s=1, alpha=0.35, linewidths=0)
        ax.axhline(0, color='0.85', lw=0.4)
        ax.axvline(0, color='0.85', lw=0.4)
        _compact_ax(ax)
        return None
    norm = plt.Normalize(t.min(), t.max())
    sc = ax.scatter(th2, om2, c=t, cmap=plt.cm.Reds, s=2, alpha=0.8, norm=norm)
    ax.set_xlabel('θ₂ (deg)')
    ax.set_ylabel('ω₂ (deg/s)')
    ax.set_title('Phase portrait — arm 2')
    ax.axhline(0, color='gray', lw=0.5, ls='--')
    ax.axvline(0, color='gray', lw=0.5, ls='--')
    ax.grid(True, alpha=0.3)
    return sc

def draw_config(ax, t, th1, th2, *, compact=False):
    """Configuration space θ₁ vs θ₂, time-coloured (blue)."""
    if compact:
        ax.scatter(th1, th2, c=COLOR_CONFIG, s=1, alpha=0.35, linewidths=0)
        _compact_ax(ax)
        return None
    norm = plt.Normalize(t.min(), t.max())
    sc = ax.scatter(th1, th2, c=t, cmap=plt.cm.Blues, s=2, alpha=0.8, norm=norm)
    ax.set_xlabel('θ₁ (deg)')
    ax.set_ylabel('θ₂ (deg)')
    ax.set_title('Configuration space  θ₁ vs θ₂')
    ax.grid(True, alpha=0.3)
    return sc

# ─────────────────────────────────────────────
# PLOT
# ─────────────────────────────────────────────

def make_figure(t, th1, th2, om1, om2, label, out_path, force_save):
    fig = plt.figure(figsize=(16, 10))

    gs = gridspec.GridSpec(2, 3, figure=fig,
                           hspace=0.42, wspace=0.35,
                           left=0.07, right=0.97,
                           top=0.97, bottom=0.08)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[0, 2])
    ax4 = fig.add_subplot(gs[1, 0])
    ax5 = fig.add_subplot(gs[1, 1])
    ax6 = fig.add_subplot(gs[1, 2])

    # ── Panel 1: theta1(t) ──────────────────────
    # Insert NaN at ±180° wraps so the line breaks instead of streaking
    # vertically across the plot at every inverted-angle crossing.
    # insert_breaks lengthens BOTH arrays in sync, so plot t_b vs theta_b.
    diff_th1 = np.abs(np.diff(th1)) > 180
    diff_th2 = np.abs(np.diff(th2)) > 180
    t1_b, th1_b = insert_breaks([t, th1], diff_th1)
    t2_b, th2_b = insert_breaks([t, th2], diff_th2)

    ax1.plot(t1_b, th1_b, color=COLOR_ARM1, lw=0.9)
    ax1.axhline(0, color='gray', lw=0.5, ls='--')
    ax1.set_xlabel('t (s)')
    ax1.set_ylabel('θ₁ (deg)')
    ax1.set_title('Arm 1 angle vs time')
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: theta2(t) ──────────────────────
    ax2.plot(t2_b, th2_b, color=COLOR_ARM2, lw=0.9)
    ax2.axhline(0, color='gray', lw=0.5, ls='--')
    ax2.set_xlabel('t (s)')
    ax2.set_ylabel('θ₂ (deg)')
    ax2.set_title('Arm 2 angle vs time')
    ax2.grid(True, alpha=0.3)

    # ── Panel 3: theta1 vs theta2 ───────────────
    sc = draw_config(ax3, t, th1, th2)
    plt.colorbar(sc, ax=ax3, label='t (s)', shrink=0.85)

    # ── Panel 4: Phase portrait arm 1 ───────────
    sc4 = draw_phase1(ax4, t, th1, om1)
    plt.colorbar(sc4, ax=ax4, label='t (s)', shrink=0.85)

    # ── Panel 5: Phase portrait arm 2 ───────────
    sc5 = draw_phase2(ax5, t, th2, om2)
    plt.colorbar(sc5, ax=ax5, label='t (s)', shrink=0.85)

    # ── Panel 6: Poincaré return map ─────────────
    p0, p1 = poincare_crossings(th1, om1)
    if len(p0) > 0:
        ax6.scatter(p0, p1, color='tab:purple', s=20, zorder=3)
        ax6.plot([p0.min(), p0.max()],
                 [p0.min(), p0.max()],
                 color='gray', lw=0.7, ls='--', label='identity line')
        ax6.set_xlabel('θ₁[n]  (deg)')
        ax6.set_ylabel('θ₁[n+1]  (deg)')
        ax6.set_title(f'Poincaré return map  (n={len(p0)} crossings)')
        ax6.legend(fontsize=8)
        ax6.grid(True, alpha=0.3)
    else:
        ax6.text(0.5, 0.5, 'Not enough\nomega1 crossings',
                 ha='center', va='center', transform=ax6.transAxes,
                 fontsize=11, color='gray')
        ax6.set_title('Poincaré return map')

    # ── Save / show ─────────────────────────────
    if force_save:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        mirror_to_ready(out_path)
        console.print(f"  [dim]Saved → {out_path}[/]")
    else:
        plt.show()

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    csv_path, output_dir, stem, force_save = resolve_paths(args)

    if not os.path.exists(csv_path):
        console.print(f"[red]ERROR:[/] CSV not found: [dim]{csv_path}[/]")
        sys.exit(1)

    ext = os.path.splitext(csv_path)[1].lower()
    if ext != ".csv":
        console.print(f"[red]ERROR:[/] expected a tracking CSV, got [dim]{csv_path}[/] (extension '{ext}').")
        console.print(f"  [dim]Try:  python {os.path.basename(__file__)} --stem <config_description>[/]")
        sys.exit(2)

    console.print(f"  [dim]Loading {csv_path} …[/]")
    t, th1, th2 = load_csv(csv_path)

    om1, om2 = compute_velocities(t, th1, th2)

    from rich.table import Table
    import rich.box
    tbl = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    tbl.add_column(style="dim", min_width=20)
    tbl.add_column(style="white", justify="right")
    tbl.add_row("frames",
                f"{len(t)}  [dim]({t[-1]:.2f} s)[/]")
    tbl.add_row("θ₁ range",
                f"[{th1.min():.1f}°, {th1.max():.1f}°]")
    tbl.add_row("θ₂ range",
                f"[{th2.min():.1f}°, {th2.max():.1f}°]")
    tbl.add_row("ω₁ range",
                f"[{om1.min():.0f}, {om1.max():.0f}] deg/s")
    tbl.add_row("ω₂ range",
                f"[{om2.min():.0f}, {om2.max():.0f}] deg/s")
    console.print(tbl)

    # Canonical figure path: figures/phase_panels/<stem>_phase_panels.png.
    # Falls back to the local output_dir for ad-hoc CSV-only invocations
    # that don't have a stem/registry entry.
    if force_save and args.stem:
        out_path = figure_path("phase_panels", args.stem)
    elif force_save and (os.path.basename(os.path.dirname(output_dir))
                         == "measurements"):
        out_path = figure_path("phase_panels",
                               os.path.basename(output_dir))
    else:
        out_path = os.path.join(output_dir, f"{stem}_sanity.png")

    make_figure(t, th1, th2, om1, om2, stem, out_path, force_save)

if __name__ == "__main__":
    main()
