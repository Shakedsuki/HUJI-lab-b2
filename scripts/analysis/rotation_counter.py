"""
rotation_counter.py
-------------------
Interactive CW / CCW rotation counter for arm2 (lower pendulum, θ₂).

Opens a matplotlib GUI with a "transient cutoff" slider so you can trim the
initial settling period before counting turns.  Counts update live.

Usage
~~~~~
  python scripts/analysis/rotation_counter.py --stem 3.2V_1.20Hz

Controls
~~~~~~~~
  Slider  — drag to set the transient cutoff time t_start.
            Everything to the left of the dashed line is ignored.
  Counts displayed in the figure:
      CW turns  (θ₂ decreasing, i.e. turns_neg in the winding convention)
      CCW turns (θ₂ increasing, turns_pos)
      Net turns (CCW − CW, signed)
"""

import argparse
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("TkAgg")            # interactive backend; falls back gracefully
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir          # noqa: E402


# ─────────────────────────────────────────────────────
# DATA LOADING  (inline — avoids rotations.py Agg lock)
# ─────────────────────────────────────────────────────

_RUN_PHASES = ("driven", "free_swing")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    t, th2, om2 = [], [], []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        has_omega = "omega2_deg_s" in fields
        for r in reader:
            if r.get("phase") not in _RUN_PHASES:
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
            if has_omega:
                om2.append(_f(r.get("omega2_deg_s")))
    if len(t) < 30:
        raise SystemExit(f"too few clean frames ({len(t)}) in {csv_path}")
    t = np.array(t)
    th2 = np.array(th2)
    om2 = np.array(om2) if has_omega else None
    return t, th2, om2


# ─────────────────────────────────────────────────────
# ROTATION MATHS
# ─────────────────────────────────────────────────────

def unwrap_deg(phi_wrapped):
    return np.degrees(np.unwrap(np.radians(phi_wrapped)))


def count_turns(rel):
    """Hysteresis-free completed ±360° revolution counter.
    Returns (turns_ccw, turns_cw) as non-negative integers."""
    R = float(rel[0])
    ccw = cw = 0
    for x in rel.tolist():
        while x - R >= 360.0:
            ccw += 1
            R += 360.0
        while R - x >= 360.0:
            cw += 1
            R -= 360.0
    return ccw, cw


def compute_window(t, th2, t_start):
    mask = t >= t_start
    if mask.sum() < 10:
        return None
    t_w = t[mask]
    phi = unwrap_deg(th2[mask])
    rel = phi - phi[0]
    ccw, cw = count_turns(rel)
    net = (ccw - cw)
    return {
        "t": t_w,
        "rel": rel,
        "ccw": ccw,
        "cw": cw,
        "net": net,
        "n": int(mask.sum()),
        "dur": float(t_w[-1] - t_w[0]),
    }


# ─────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────

def launch_gui(stem, t, th2, om2):
    t0 = t - t[0]
    T = float(t0[-1])

    fig = plt.figure(figsize=(13, 8))
    fig.canvas.manager.set_window_title(f"Rotation counter — {stem}")

    # Layout: top = raw angle, mid = accumulated turns, bottom = slider
    ax_raw  = fig.add_axes([0.08, 0.60, 0.86, 0.33])
    ax_acc  = fig.add_axes([0.08, 0.22, 0.86, 0.33])
    ax_sl   = fig.add_axes([0.15, 0.07, 0.70, 0.04])

    slider = Slider(ax_sl, "t_start (s)", 0.0, T * 0.85,
                    valinit=0.0, valstep=max(T / 500, 0.05),
                    color="steelblue")

    # ── raw angle panel ──
    ax_raw.plot(t0, th2, color="tab:red", lw=0.7, alpha=0.85)
    vline_raw = ax_raw.axvline(0, color="k", lw=1.2, ls="--", alpha=0.7)
    span_raw  = ax_raw.axvspan(0, 0, color="0.88", zorder=0)
    ax_raw.set_ylabel(r"$\theta_2$ (deg, wrapped)")
    ax_raw.set_title(f"arm2  θ₂   —   {stem}", fontsize=10)
    ax_raw.set_xlim(0, T)
    ax_raw.grid(True, alpha=0.2)

    # ── accumulated turns panel ──
    phi_full = unwrap_deg(th2)
    rel_full = phi_full - phi_full[0]
    line_acc,  = ax_acc.plot(t0, rel_full / 360.0, color="tab:red", lw=0.9, label="full")
    line_win,  = ax_acc.plot([], [], color="tab:blue", lw=1.4, label="window")
    vline_acc  = ax_acc.axvline(0, color="k", lw=1.2, ls="--", alpha=0.7)
    span_acc   = ax_acc.axvspan(0, 0, color="0.88", zorder=0)
    ax_acc.axhline(0, color="0.5", lw=0.5)
    ax_acc.set_ylabel("accumulated angle (rev)")
    ax_acc.set_xlabel("t (s)")
    ax_acc.set_xlim(0, T)
    ax_acc.grid(True, alpha=0.2)
    ax_acc.legend(fontsize=8, loc="upper left")

    # count annotation
    ann = ax_acc.text(
        0.99, 0.97, "",
        transform=ax_acc.transAxes,
        ha="right", va="top",
        fontsize=12, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="0.7", alpha=0.9),
    )

    def _update_span(span, xmin, xmax):
        # Polygon vertices: bl, tl, tr, br
        verts = span.get_xy()
        verts[:, 0] = [xmin, xmin, xmax, xmax, xmin]
        span.set_xy(verts)

    def update(val):
        ts = float(slider.val)
        vline_raw.set_xdata([ts])
        vline_acc.set_xdata([ts])
        _update_span(span_raw, 0, ts)
        _update_span(span_acc, 0, ts)

        w = compute_window(t0, th2, ts)
        if w is None:
            ann.set_text("(window too short)")
            fig.canvas.draw_idle()
            return

        t_rel = w["t"] - w["t"][0]
        line_win.set_xdata(w["t"])
        line_win.set_ydata(w["rel"] / 360.0)

        ax_acc.relim()
        ax_acc.autoscale_view(scalex=False)

        rate_ccw = w["ccw"] / w["dur"] if w["dur"] > 0 else 0
        rate_cw  = w["cw"]  / w["dur"] if w["dur"] > 0 else 0
        ann.set_text(
            f"window  {ts:.1f}–{t0[-1]:.1f} s  ({w['dur']:.1f} s)\n"
            f"CCW  {w['ccw']:>3d} turns   ({rate_ccw:.2f} /s)\n"
            f"CW   {w['cw']:>3d} turns   ({rate_cw:.2f} /s)\n"
            f"Net  {w['net']:>+3d} turns"
        )
        fig.canvas.draw_idle()

    slider.on_changed(update)
    update(0.0)

    plt.show()


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stem", required=True,
                    help="clip stem, e.g. 3.2V_1.20Hz")
    args = ap.parse_args()

    cdir = clip_dir(args.stem)
    csv_path = None
    for name in ("verification.csv", "tracking.csv"):
        p = os.path.join(cdir, name)
        if os.path.exists(p):
            csv_path = p
            break
    if csv_path is None:
        raise SystemExit(f"no verification.csv / tracking.csv in {cdir}")

    print(f"loading {csv_path} …")
    t, th2, om2 = load_clip(csv_path)
    print(f"  {len(t)} clean frames, {t[-1]-t[0]:.1f} s")

    launch_gui(args.stem, t, th2, om2)


if __name__ == "__main__":
    main()
