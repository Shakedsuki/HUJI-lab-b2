"""
poincare.py
-----------
Poincare section for a tracked double-pendulum clip.

Cross-section:
    theta2_abs = 0,   d(theta2_abs)/dt > 0
i.e. every time the lower bob's absolute angle (theta1 + theta2) passes
through zero on its way up, we record a point (theta1, omega1).

For the 4D phase space (theta1, theta2, omega1, omega2) constrained to
the energy surface, this 1D section yields a 2D Poincare map. The
section condition is well-suited to the wall-mounted rig: theta2_abs = 0
means the lower arm is pointing straight down (rest-equilibrium of
the lower bob), and the upward-crossing direction breaks the symmetry.

Sub-frame interpolation: a linear root finder between consecutive
samples gives a Poincare point even when the section is crossed mid-
frame. This avoids the "ladder" artefact that pure-sample sections
produce on noisy experimental data.

Output: measurements/<stem>/poincare.png  (4-panel figure)
        measurements/<stem>/poincare.csv  (the points themselves)

Usage:
    python scripts/analysis/poincare.py --stem th1_p044_th2_m001
    python scripts/analysis/poincare.py measurements/<stem>/verification.csv
"""

import argparse
import csv
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402

def parse_args():
    p = argparse.ArgumentParser(
        description="Poincare section for a double-pendulum clip.")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to verification.csv (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p044_th2_m001.")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--no-csv", action="store_true",
                   help="Skip writing poincare.csv")
    return p.parse_args()

def resolve_io(args):
    if args.stem:
        meas = os.path.join(MEAS_DIR, args.stem)
        csv_path = os.path.join(meas, "verification.csv")
        out_dir  = meas
        label    = args.stem
    elif args.csv:
        csv_path = args.csv
        out_dir  = os.path.dirname(os.path.abspath(csv_path))
        label    = os.path.basename(out_dir)
    else:
        raise SystemExit("Need --stem or a CSV path.")
    if not os.path.exists(csv_path):
        raise SystemExit(f"CSV not found: {csv_path}")
    return csv_path, out_dir, label

def load_clean(csv_path):
    """Load the free-swing rows. Returns (t, th1, th2, om1, om2) in
    seconds and degrees / deg-per-sec, with NaN at gap rows."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") != "free_swing":
                continue
            try:
                rows.append((
                    float(r["time_s"]),
                    float(r["theta1_deg"]),
                    float(r["theta2_deg"]),
                    float(r["omega1_deg_s"]),
                    float(r["omega2_deg_s"]),
                ))
            except (ValueError, KeyError):
                # Drop gap / malformed rows.
                continue
    if len(rows) < 50:
        raise SystemExit(f"Too few free-swing rows ({len(rows)}) in {csv_path}.")
    arr = np.array(rows, dtype=float)
    t   = arr[:, 0] - arr[0, 0]
    return t, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]

def upward_zero_crossings(s):
    """Return the index pairs (i-1, i) where s changes sign from
    negative to positive between samples i-1 and i. Equality at i-1
    handled by the strict less-than to avoid double-counting plateaus."""
    s = np.asarray(s, dtype=float)
    sign_prev = s[:-1]
    sign_next = s[1:]
    mask = (sign_prev < 0) & (sign_next >= 0)
    return np.where(mask)[0]

def lerp_at_crossing(s_prev, s_next, x_prev, x_next):
    """Linear interpolation: find x at the moment s crosses zero
    between (s_prev, x_prev) and (s_next, x_next)."""
    denom = s_next - s_prev
    if denom == 0:
        return x_prev
    frac = -s_prev / denom    # in [0, 1] when s_prev < 0 < s_next
    return x_prev + frac * (x_next - x_prev)

def poincare_points(t, th1, th2, om1, om2):
    """
    Section: theta2_abs == 0  (i.e. theta1 + theta2 == 0),
             with the section crossed in the +theta2_abs direction
             (omega1 + omega2 > 0).

    Returns (t_cross, th1_cross, om1_cross) arrays.
    """
    th2_abs = th1 + th2
    # Wrap to (-180, 180] so the absolute angle is well defined.
    th2_abs_unwrap = np.degrees(np.unwrap(np.radians(th2_abs)))
    # Pick the same wrapping for theta1 — interpolation is straightforward
    # on the unwrapped representation, then we re-wrap at the end.
    th1_unwrap = np.degrees(np.unwrap(np.radians(th1)))

    # Use the non-unwrapped (modulo 360) section to find crossings
    # near the rest position. We look for sign changes of
    # ((th1+th2) wrapped to (-180,180]).
    th2_abs_wrapped = ((th1 + th2 + 180) % 360) - 180

    idx = upward_zero_crossings(th2_abs_wrapped)
    # Filter spurious crossings produced by the wrap discontinuity:
    # a real upward zero crossing has |th2_abs_wrapped[prev]| AND
    # |th2_abs_wrapped[next]| both small (< 30 deg, say). At ±180
    # wraps the wrapped series can swing -180 -> +180 in one frame,
    # which the upward-crossing test would otherwise pick up.
    keep = []
    for i in idx:
        if abs(th2_abs_wrapped[i]) < 30 and abs(th2_abs_wrapped[i + 1]) < 30:
            keep.append(i)
    idx = np.array(keep, dtype=int)

    if len(idx) == 0:
        return np.array([]), np.array([]), np.array([])

    t_cross   = []
    th1_cross = []
    om1_cross = []
    for i in idx:
        s0, s1 = th2_abs_wrapped[i], th2_abs_wrapped[i + 1]
        # Direction filter: omega2_abs = om1 + om2 > 0 at the crossing.
        if (om1[i] + om2[i]) <= 0 and (om1[i + 1] + om2[i + 1]) <= 0:
            continue
        frac  = -s0 / (s1 - s0) if (s1 - s0) != 0 else 0.0
        tc    = t[i]   + frac * (t[i + 1]   - t[i])
        th1c  = th1_unwrap[i] + frac * (th1_unwrap[i + 1] - th1_unwrap[i])
        om1c  = om1[i] + frac * (om1[i + 1] - om1[i])
        # Re-wrap theta1 to (-180, 180].
        th1c = ((th1c + 180) % 360) - 180
        t_cross.append(tc)
        th1_cross.append(th1c)
        om1_cross.append(om1c)

    return (np.array(t_cross),
            np.array(th1_cross),
            np.array(om1_cross))

def make_figure(t, th1, th2, om1, om2,
                t_p, th1_p, om1_p, label, out_path):
    fig = plt.figure(figsize=(15, 10))
    gs  = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.28,
                           left=0.07, right=0.97, top=0.95, bottom=0.07)

    ax_main = fig.add_subplot(gs[:, 0])
    ax_tl   = fig.add_subplot(gs[0, 1])
    ax_full = fig.add_subplot(gs[1, 1])

    # Main panel: Poincare section coloured by time.
    if len(t_p) > 0:
        sc = ax_main.scatter(th1_p, om1_p, c=t_p,
                             cmap=plt.cm.viridis, s=14, alpha=0.85)
        plt.colorbar(sc, ax=ax_main, label="t (s)", shrink=0.85)
    ax_main.axhline(0, color="gray", lw=0.5, ls="--")
    ax_main.axvline(0, color="gray", lw=0.5, ls="--")
    ax_main.set_xlabel("theta1 (deg)  [at section]")
    ax_main.set_ylabel("omega1 (deg/s)  [at section]")
    ax_main.set_title(
        f"Poincare section:  theta1+theta2 = 0,  d/dt > 0   (n={len(t_p)})")
    ax_main.grid(True, alpha=0.3)

    # Top right: theta1 of section points vs time (orbit-by-orbit drift).
    if len(t_p) > 0:
        ax_tl.scatter(t_p, th1_p, c=t_p, cmap=plt.cm.viridis, s=10)
    ax_tl.set_xlabel("t (s)")
    ax_tl.set_ylabel("theta1 (deg) at section")
    ax_tl.set_title("Section points vs time")
    ax_tl.axhline(0, color="gray", lw=0.5, ls="--")
    ax_tl.grid(True, alpha=0.3)

    # Bottom right: full theta1 phase portrait with section line.
    ax_full.scatter(th1, om1, c=t, cmap=plt.cm.Greys,
                    s=1, alpha=0.5)
    if len(t_p) > 0:
        ax_full.scatter(th1_p, om1_p, color="tab:red", s=18,
                        label="section points", zorder=5)
    ax_full.set_xlabel("theta1 (deg)")
    ax_full.set_ylabel("omega1 (deg/s)")
    ax_full.set_title("Full phase portrait + section overlay")
    ax_full.axhline(0, color="gray", lw=0.5, ls="--")
    ax_full.axvline(0, color="gray", lw=0.5, ls="--")
    ax_full.grid(True, alpha=0.3)
    if len(t_p) > 0:
        ax_full.legend(loc="upper right", fontsize=9)

    fig.suptitle(f"Poincare section — {label}", fontsize=14, y=0.995)
    fig.savefig(out_path, dpi=130)
    mirror_to_ready(out_path)
    plt.close(fig)

def main():
    args = parse_args()
    csv_path, out_dir, label = resolve_io(args)
    print(f"Reading {csv_path} ...")
    t, th1, th2, om1, om2 = load_clean(csv_path)
    print(f"  {len(t)} clean free-swing rows, t_max = {t[-1]:.2f}s")

    t_p, th1_p, om1_p = poincare_points(t, th1, th2, om1, om2)
    print(f"  {len(t_p)} Poincare crossings  (theta2_abs = 0, d/dt > 0)")

    if not args.no_csv:
        out_csv = os.path.join(out_dir, "poincare.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "theta1_deg", "omega1_deg_s"])
            for tc, th, om in zip(t_p, th1_p, om1_p):
                w.writerow([f"{tc:.4f}", f"{th:.4f}", f"{om:.4f}"])
        print(f"  wrote {out_csv}")

    if not args.no_plot:
        out_png = figure_path("poincare", label)
        make_figure(t, th1, th2, om1, om2,
                    t_p, th1_p, om1_p, label, out_png)
        print(f"  wrote {out_png}")

if __name__ == "__main__":
    main()
