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
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import savgol_filter

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from figures_paths import figure_path  # noqa: E402


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ROOT        = r"C:\dev\chaos"
DEFAULT_CSV = os.path.join(ROOT, "measurements", "th1_p180_th2_m179",
                           "tracking.csv")
LEGACY_OUT  = os.path.join(ROOT, "data", "figures")


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
        meas_dir = os.path.join(ROOT, "measurements", args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            print(f"ERROR: tracking.csv not found for stem '{args.stem}'")
            print(f"  Expected: {csv_path}")
            sys.exit(1)
        return csv_path, meas_dir, args.stem, True

    if args.csv:
        csv_path = args.csv if os.path.isabs(args.csv) \
                   else os.path.join(ROOT, args.csv)
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
        if r['phase'] == 'free_swing'
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

    # Colour maps: colour by time so we can see temporal evolution
    norm = plt.Normalize(t.min(), t.max())
    cmap = plt.cm.plasma

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
    # Configuration space — scatter coloured by time
    sc = ax3.scatter(th1, th2, c=t, cmap=plt.cm.Blues,
                     s=2, alpha=0.8, norm=norm)
    ax3.set_xlabel('θ₁ (deg)')
    ax3.set_ylabel('θ₂ (deg)')
    ax3.set_title('Configuration space  θ₁ vs θ₂')
    ax3.grid(True, alpha=0.3)
    plt.colorbar(sc, ax=ax3, label='t (s)', shrink=0.85)

    # ── Panel 4: Phase portrait arm 1 ───────────
    sc4 = ax4.scatter(th1, om1, c=t, cmap=plt.cm.Greens,
                      s=2, alpha=0.8, norm=norm)
    ax4.set_xlabel('θ₁ (deg)')
    ax4.set_ylabel('ω₁ (deg/s)')
    ax4.set_title('Phase portrait — arm 1')
    ax4.axhline(0, color='gray', lw=0.5, ls='--')
    ax4.axvline(0, color='gray', lw=0.5, ls='--')
    ax4.grid(True, alpha=0.3)
    plt.colorbar(sc4, ax=ax4, label='t (s)', shrink=0.85)

    # ── Panel 5: Phase portrait arm 2 ───────────
    sc5 = ax5.scatter(th2, om2, c=t, cmap=plt.cm.Reds,
                      s=2, alpha=0.8, norm=norm)
    ax5.set_xlabel('θ₂ (deg)')
    ax5.set_ylabel('ω₂ (deg/s)')
    ax5.set_title('Phase portrait — arm 2')
    ax5.axhline(0, color='gray', lw=0.5, ls='--')
    ax5.axvline(0, color='gray', lw=0.5, ls='--')
    ax5.grid(True, alpha=0.3)
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
        print(f"Figure saved to: {out_path}")
    else:
        plt.show()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    csv_path, output_dir, stem, force_save = resolve_paths(args)

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    ext = os.path.splitext(csv_path)[1].lower()
    if ext != ".csv":
        print(f"ERROR: expected a tracking CSV, got '{csv_path}' (extension '{ext}').")
        print("       This script reads the per-frame angle CSV, not videos.")
        print(f"       Try:  python {os.path.basename(__file__)} --stem <config_description>")
        sys.exit(2)

    print(f"Loading {csv_path} ...")
    t, th1, th2 = load_csv(csv_path)
    print(f"  {len(t)} clean free-swing frames  "
          f"({t[-1]:.2f}s of data)")
    print(f"  θ₁: [{th1.min():.1f}°, {th1.max():.1f}°]")
    print(f"  θ₂: [{th2.min():.1f}°, {th2.max():.1f}°]")

    om1, om2 = compute_velocities(t, th1, th2)
    print(f"  ω₁: [{om1.min():.0f}, {om1.max():.0f}] deg/s")
    print(f"  ω₂: [{om2.min():.0f}, {om2.max():.0f}] deg/s")

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
