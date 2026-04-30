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
  python scripts/analysis/phase_panels.py
  Optionally pass a CSV path as argument:
  python scripts/analysis/phase_panels.py C:/dev/chaos/data/long_recording_tracking.csv
"""

import sys
import os
import csv
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import savgol_filter


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV = r"C:\dev\chaos\data\long_recording_tracking.csv"
OUTPUT_DIR  = r"C:\dev\chaos\data\figures"

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
    Returns om1, om2 in deg/s.
    """
    dt = np.mean(np.diff(t))   # mean frame interval (should be ~1/60 s)

    om1 = savgol_filter(th1, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    return om1, om2


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

def make_figure(t, th1, th2, om1, om2, label, out_path):
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
    ax1.plot(t, th1, color=COLOR_ARM1, lw=0.9)
    ax1.axhline(0, color='gray', lw=0.5, ls='--')
    ax1.set_xlabel('t (s)')
    ax1.set_ylabel('θ₁ (deg)')
    ax1.set_title('Arm 1 angle vs time')
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: theta2(t) ──────────────────────
    ax2.plot(t, th2, color=COLOR_ARM2, lw=0.9)
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

    # ── Save ────────────────────────────────────
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Figure saved to: {out_path}")
    plt.show()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV

    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    print(f"Loading {csv_path} ...")
    t, th1, th2 = load_csv(csv_path)
    print(f"  {len(t)} clean free-swing frames  "
          f"({t[-1]:.2f}s of data)")
    print(f"  θ₁: [{th1.min():.1f}°, {th1.max():.1f}°]")
    print(f"  θ₂: [{th2.min():.1f}°, {th2.max():.1f}°]")

    om1, om2 = compute_velocities(t, th1, th2)
    print(f"  ω₁: [{om1.min():.0f}, {om1.max():.0f}] deg/s")
    print(f"  ω₂: [{om2.min():.0f}, {om2.max():.0f}] deg/s")

    label    = os.path.basename(csv_path)
    out_path = os.path.join(OUTPUT_DIR, label.replace('.csv', '_sanity.png'))

    make_figure(t, th1, th2, om1, om2, label, out_path)


if __name__ == "__main__":
    main()
