#!/usr/bin/env python3
"""
phase_analysis.py — cyclic (oscillator) phase + drive-relative phase.

Two phase quantities the unwrapped angle (rotations.py) does NOT give you:

  (#2) cyclic phase  ψ(t): the phase of the arm's *cycle*, advancing 2π per
       oscillation period even when the arm only swings and never loops.
       Extracted as the Hilbert protophase of the DE-TRENDED unwrapped
       angle — de-trending removes any net winding (leaving the
       oscillation) and sidesteps the ±180° wrap discontinuities that
       corrupt a Hilbert transform of the raw wrapped signal.

  (#3) drive-relative phase  Δφ(t) = ψ_arm(t) − 2π·f_drive·(t − t₀).
       For a periodically driven pendulum this is the phase-locking
       diagnostic: Δφ flat/bounded ⇒ the arm is phase-locked to the motor;
       a steady slope ⇒ it slips at rate (arm_freq − f_drive).

Computed per arm: upper (θ₁) and lower (θ₂, lab-frame absolute — θ₂ is
already absolute in this rig, so it is NOT θ₁+θ₂).

Caveat: the cyclic phase is well-posed for oscillatory motion. When an arm
is deep in a looping/chaotic regime the de-trended residual is itself
chaotic, so ψ is a protophase (the *rotation* there is better read from
rotations.py's accumulated angle / winding number).

Usage:
  python scripts/analysis/phase_analysis.py --stem 3.2V_1.20Hz
  python scripts/analysis/phase_analysis.py --stem 3.2V_1.20Hz --transient 8

Output:
  measurements/<stem>/phase.json
  figures/phase/<stem>_phase.png
"""

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
from scipy import signal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir, EXPERIMENTS          # noqa: E402
from figures_paths import figure_path            # noqa: E402
from driven_helpers import parse_stem            # noqa: E402

RUN_PHASES = ("driven", "free_swing")

# (key, label, mathlabel, color)
ARMS = (
    ("upper", "upper θ₁",  r"upper $\theta_1$", "tab:blue"),
    ("lower", "lower θ₂",  r"lower $\theta_2$", "tab:red"),
)

# Heuristic locking tolerances (on the settled window).
LOCK_SLIP_TOL = 0.05    # |net slip| in cycles/s below which we call it ~locked
LOCK_SPAN_TOL = 1.5     # drive-relative phase must stay within this many cycles


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    """Clean (t, th1, th2) arrays: running phase, dropout 0, finite angles."""
    t, th1, th2 = [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            a, b, tt = _f(r.get("theta1_deg")), _f(r.get("theta2_deg")), _f(r.get("time_s"))
            if np.isfinite(a) and np.isfinite(b) and np.isfinite(tt):
                t.append(tt); th1.append(a); th2.append(b)
    if len(t) < 64:
        raise ValueError(f"only {len(t)} clean frames in {csv_path} (need >= 64)")
    return np.array(t), np.array(th1), np.array(th2)


def arm_angle(th1, th2, arm):
    if arm == "upper":
        return th1
    if arm == "lower":
        return th2            # θ₂ is already lab-frame absolute
    raise ValueError(arm)


def resolve_f_drive(stem, override):
    if override is not None:
        return override
    if os.path.exists(EXPERIMENTS):
        try:
            with open(EXPERIMENTS, encoding="utf-8") as f:
                exp = json.load(f)
            e = exp.get(stem) or next(
                (v for v in exp.values() if v.get("config_description") == stem), None)
            if e and e.get("drive_freq_hz"):
                return float(e["drive_freq_hz"])
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return parse_stem(stem)["f_drive_hz"]


# ─────────────────────────────────────────────
# PHASE MATH
# ─────────────────────────────────────────────

def cyclic_phase(theta_deg):
    """(#2) Cyclic/oscillator phase ψ(t) via Hilbert of the de-trended
    unwrapped angle. Returns (psi_unwrapped_rad, residual_deg)."""
    phi = np.unwrap(np.radians(np.asarray(theta_deg, float)))   # continuous
    resid = signal.detrend(phi, type="linear")                  # strip winding
    psi = np.unwrap(np.angle(signal.hilbert(resid)))            # protophase
    return psi, np.degrees(resid)


def drive_relative(t, psi, f_drive):
    """(#3) Δφ(t) = ψ_arm − 2π·f_drive·(t − t0)."""
    psi_drive = 2.0 * np.pi * f_drive * (t - t[0])
    return psi - psi_drive, psi_drive


def phase_metrics(t, psi, dphi, f_drive, transient_s):
    """Settled-window scalars: arm frequency, ratio to drive, slip rate,
    drive-relative span, heuristic locked flag."""
    m = t >= (t[0] + transient_s)
    if m.sum() < 16:
        m = np.ones_like(t, dtype=bool)
    tt = t[m]
    dur = float(tt[-1] - tt[0]) or 1.0
    arm_freq = float(psi[m][-1] - psi[m][0]) / (2 * np.pi * dur)
    slip_rate = float(dphi[m][-1] - dphi[m][0]) / (2 * np.pi * dur)   # cycles/s
    span = float(dphi[m].max() - dphi[m].min()) / (2 * np.pi)         # cycles
    ratio = arm_freq / f_drive if f_drive else float("nan")
    locked = bool(abs(slip_rate) < LOCK_SLIP_TOL and span < LOCK_SPAN_TOL)
    return {
        "arm_freq_hz":            arm_freq,
        "freq_ratio_to_drive":    ratio,
        "slip_rate_cycles_per_s": slip_rate,
        "dphi_span_cycles":       span,
        "phase_locked":           locked,
    }


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

def print_table(stem, f_drive, res):
    t = Table(title=f"phase — {stem}   (f_drive = {f_drive:g} Hz)",
              box=rich.box.SIMPLE_HEAD, title_style="bold cyan")
    t.add_column("arm")
    t.add_column("arm freq (Hz)", justify="right")
    t.add_column("ratio f/f_drive", justify="right")
    t.add_column("slip (cyc/s)", justify="right")
    t.add_column("Δφ span (cyc)", justify="right")
    t.add_column("locked?", justify="right")
    for key, label, _mlab, _c in ARMS:
        m = res[key]
        lk = "[green]locked[/]" if m["phase_locked"] else "[yellow]slipping[/]"
        t.add_row(label,
                  f"{m['arm_freq_hz']:.3f}",
                  f"{m['freq_ratio_to_drive']:.3f}",
                  f"{m['slip_rate_cycles_per_s']:+.3f}",
                  f"{m['dphi_span_cycles']:.1f}",
                  lk)
    console.print(t)
    console.print("  [dim]locked = drive-relative phase Δφ stays flat/bounded; "
                  "ratio ≈ simple rational ⇒ n:m lock[/]")


def make_figure(stem, f_drive, t, traces, res, out_path):
    t0 = t - t[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Top: drive-relative phase Δφ (cycles) — the locking diagnostic.
    for key, _label, mlab, color in ARMS:
        m = res[key]
        ax1.plot(t0, traces[key]["dphi"] / (2 * np.pi), color=color, lw=1.0,
                 label=f"{mlab}  (ratio {m['freq_ratio_to_drive']:.2f}, "
                       f"slip {m['slip_rate_cycles_per_s']:+.3f} cyc/s, "
                       f"{'locked' if m['phase_locked'] else 'slipping'})")
    ax1.axhline(0, color="0.6", lw=0.6)
    ax1.set_ylabel("drive-relative phase  Δφ / 2π  (cycles)")
    ax1.set_title(f"Phase locking — {stem}   "
                  f"(f_drive = {f_drive:g} Hz;  flat = locked, sloped = slipping)")
    ax1.grid(True, alpha=0.25)
    ax1.legend(fontsize=8, loc="best")

    # Bottom: cyclic phase ψ (cycles) vs the drive phase (dashed).
    for key, _label, mlab, color in ARMS:
        ax2.plot(t0, traces[key]["psi"] / (2 * np.pi), color=color, lw=1.0,
                 label=f"{mlab} cyclic ψ")
    ax2.plot(t0, traces["_drive"] / (2 * np.pi), color="0.4", lw=1.0, ls="--",
             label="drive  2π·f·t")
    ax2.set_ylabel("cyclic phase  ψ / 2π  (cycles)")
    ax2.set_xlabel("t (s)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(fontsize=8, loc="best")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True, help="clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at start for the metrics (default: 5)")
    p.add_argument("--f-drive", type=float, default=None, dest="f_drive",
                   help="override drive frequency (Hz)")
    return p.parse_args()


def main():
    args = parse_args()
    stem = args.stem
    cdir = clip_dir(stem)
    csv_path = next((os.path.join(cdir, n) for n in
                     ("verification.csv", "tracking.csv")
                     if os.path.exists(os.path.join(cdir, n))), None)
    if csv_path is None:
        raise SystemExit(f"no verification.csv / tracking.csv in {cdir}")

    f_drive = resolve_f_drive(stem, args.f_drive)
    if not f_drive or f_drive <= 0:
        raise SystemExit(f"could not resolve a positive drive frequency for {stem}")

    t, th1, th2 = load_clip(csv_path)

    res, traces = {}, {}
    for key, _label, _mlab, _c in ARMS:
        psi, _resid = cyclic_phase(arm_angle(th1, th2, key))
        dphi, psi_drive = drive_relative(t, psi, f_drive)
        res[key] = phase_metrics(t, psi, dphi, f_drive, args.transient)
        traces[key] = {"psi": psi, "dphi": dphi}
    traces["_drive"] = 2.0 * np.pi * f_drive * (t - t[0])

    print_table(stem, f_drive, res)

    out = {
        "stem": stem,
        "source": os.path.basename(csv_path),
        "drive_freq_hz": f_drive,
        "transient_s": args.transient,
        "n_frames": int(len(t)),
        "duration_s": float(t[-1] - t[0]),
        "arms": res,
    }
    out_json = os.path.join(cdir, "phase.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    console.print(f"  [dim]→ {out_json}[/]")

    out_png = figure_path("phase", stem)
    make_figure(stem, f_drive, t, traces, res, out_png)
    console.print(f"  [dim]→ {out_png}[/]")


if __name__ == "__main__":
    main()
