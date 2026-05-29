"""
rotation_counter.py
-------------------
Interactive CW / CCW rotation counter for arm2 (lower pendulum, theta2),
across a whole drive-voltage family.

Plots the number of completed clockwise (CW) and counter-clockwise (CCW)
turns that arm2 makes, with drive frequency on the x-axis, for every clip
at one voltage (default 3.2 V).

The start of each run contains a transient before the pendulum settles onto
its attractor. A slider trims it: drag "transient cut" to set how many
seconds to discard from the start of every clip before counting, and the
whole sweep recomputes and redraws live so you can find the right window.

Turn-counting convention
~~~~~~~~~~~~~~~~~~~~~~~~~
theta2 (atan2 output, wrapped to (-180, 180]) is unwrapped once, then a
hysteresis-free counter logs one CCW turn each time the angle advances a
full +360 deg past a ratcheting reference, one CW turn each -360 deg. An
arm oscillating below 360 deg amplitude logs nothing; a full back-and-forth
loop logs one each way. Matches scripts/analysis/rotations.py.

Usage
~~~~~
  python scripts/analysis/rotation_counter.py
  python scripts/analysis/rotation_counter.py --voltage 4.0
"""

import argparse
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("TkAgg")            # interactive GUI backend
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir, iter_clip_dirs       # noqa: E402
from driven_helpers import parse_stem            # noqa: E402


RUN_PHASES = ("driven", "free_swing")


# ─────────────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_theta2(csv_path):
    """Clean (t0, theta2) arrays for arm2. Time zero-based. None if sparse."""
    t, th2 = [], []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            tt, th = _f(r.get("time_s")), _f(r.get("theta2_deg"))
            if not (np.isfinite(tt) and np.isfinite(th)):
                continue
            t.append(tt)
            th2.append(th)
    if len(t) < 30:
        return None
    t = np.array(t)
    return t - t[0], np.array(th2)


def load_family(voltage):
    """Preload every clip at `voltage`: [{f, stem, t0, phi, dur}, ...].

    phi is the unwrapped theta2 (degrees), computed once so the slider can
    re-slice and recount cheaply without touching disk.
    """
    fam = []
    for stem, _cdir in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        cdir = clip_dir(stem)
        csv_path = next(
            (os.path.join(cdir, n) for n in ("verification.csv", "tracking.csv")
             if os.path.exists(os.path.join(cdir, n))), None)
        if csv_path is None:
            continue
        loaded = load_theta2(csv_path)
        if loaded is None:
            print(f"  skip {stem}: too few clean frames")
            continue
        t0, th2 = loaded
        phi = np.degrees(np.unwrap(np.radians(th2)))
        fam.append({"f": meta["f_drive_hz"], "stem": stem,
                    "t0": t0, "phi": phi, "dur": float(t0[-1])})
    fam.sort(key=lambda c: c["f"])
    return fam


# ─────────────────────────────────────────────────────
# COUNTING
# ─────────────────────────────────────────────────────

def count_turns(phi_window):
    """(ccw, cw) completed +/-360 deg revolutions over an unwrapped slice.
    Hysteresis on a ratcheting reference; re-zeroed at the slice start."""
    rel = phi_window - phi_window[0]
    R = 0.0
    ccw = cw = 0
    for x in rel.tolist():
        while x - R >= 360.0:
            ccw += 1
            R += 360.0
        while R - x >= 360.0:
            cw += 1
            R -= 360.0
    return ccw, cw


def turns_after(clip, t_start):
    """(ccw, cw) for one clip counting only t >= t_start. None if too short."""
    mask = clip["t0"] >= t_start
    if mask.sum() < 10:
        return None
    return count_turns(clip["phi"][mask])


# ─────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────

def launch_gui(fam, voltage):
    freqs = np.array([c["f"] for c in fam])
    min_dur = min(c["dur"] for c in fam)
    max_cut = max(min_dur * 0.7, 1.0)     # keep >=30% of the shortest clip
    init_cut = min(5.0, max_cut)

    fig, ax = plt.subplots(figsize=(12, 7))
    fig.subplots_adjust(bottom=0.20)
    fig.canvas.manager.set_window_title(
        f"arm2 rotation counter — {voltage:g} V family")

    ccw_line, = ax.plot(freqs, np.zeros_like(freqs), "-o",
                        color="tab:blue", ms=5, lw=1.3, label="CCW (+)")
    cw_line,  = ax.plot(freqs, np.zeros_like(freqs), "-o",
                        color="tab:red",  ms=5, lw=1.3, label="CW (-)")
    ax.set_xlabel("drive frequency (Hz)")
    ax.set_ylabel(r"completed turns of arm2 ($\theta_2$)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")

    ax_sl = fig.add_axes([0.15, 0.06, 0.70, 0.035])
    slider = Slider(ax_sl, "transient cut (s)", 0.0, max_cut,
                    valinit=init_cut, valstep=max(max_cut / 400, 0.05),
                    color="steelblue")

    def update(_):
        ts = float(slider.val)
        ccw_vals, cw_vals = [], []
        for c in fam:
            res = turns_after(c, ts)
            if res is None:
                ccw_vals.append(np.nan); cw_vals.append(np.nan)
            else:
                ccw_vals.append(res[0]); cw_vals.append(res[1])
        ccw_vals = np.array(ccw_vals, float)
        cw_vals = np.array(cw_vals, float)

        ccw_line.set_ydata(ccw_vals)
        cw_line.set_ydata(cw_vals)
        top = np.nanmax(np.concatenate([ccw_vals, cw_vals, [1.0]]))
        ax.set_ylim(0, top * 1.1)
        ax.set_title(
            f"arm2 ($\\theta_2$) rotations — {voltage:g} V family   "
            f"(transient {ts:.1f} s trimmed)", fontsize=11)
        fig.canvas.draw_idle()

    slider.on_changed(update)
    update(None)
    plt.show()


# ─────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voltage", type=float, default=3.2,
                    help="drive voltage family to plot (default: 3.2)")
    args = ap.parse_args()

    print(f"loading {args.voltage:g} V family ...")
    fam = load_family(args.voltage)
    if not fam:
        raise SystemExit(f"no clips found at {args.voltage:g} V")
    print(f"  {len(fam)} clips, {fam[0]['f']:g}-{fam[-1]['f']:g} Hz")

    launch_gui(fam, args.voltage)


if __name__ == "__main__":
    main()
