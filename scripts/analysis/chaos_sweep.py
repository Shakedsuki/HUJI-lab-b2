#!/usr/bin/env python3
"""
chaos_sweep.py — route-to-chaos summary across a drive-frequency sweep.

Holds drive voltage fixed (the week6 3.2V family by default) and, for every
clip, collects the headline diagnostics on one axis vs f_drive — the
single "where does it go chaotic" picture for the report:

  loops        total 360° turns of the lower arm (rotations.py)
  D2           correlation dimension of the attractor (dimension.py) —
               ~1 periodic, fractional => strange attractor
  theta1_rms   upper-arm response amplitude (resonance)
  freq_ratio   response/drive frequency of the upper arm (=1 => 1:1 locked)
  slip         drive-relative phase slip rate of the upper arm (phase.py)
  lambda1      largest Lyapunov exponent (optional, --with-lyap; slow)

Each per-clip number reuses its standalone script, so this stays a single
source of truth.

Outputs:
  figures/aggregate/chaos_sweep_<V>V.png   (panels vs f_drive)
  figures/aggregate/chaos_sweep_<V>V.csv   (per-clip table)

Usage:
  python scripts/analysis/chaos_sweep.py
  python scripts/analysis/chaos_sweep.py --voltage 4.0   # CHAOS_PHASE=week5
  python scripts/analysis/chaos_sweep.py --with-lyap     # add lambda1 (slow)
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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rich.console import Console
from rich.table import Table
import rich.box

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
sys.path.insert(0, _HERE)
from paths import clip_dir, iter_clip_dirs        # noqa: E402
from figures_paths import aggregate_path           # noqa: E402
from driven_helpers import parse_stem              # noqa: E402
from rotations import winding_metrics              # noqa: E402
from phase_analysis import cyclic_phase, drive_relative, phase_metrics  # noqa: E402
from dimension import embed, autocorr_tau, correlation_dimension        # noqa: E402

console = Console()
RUN_PHASES = ("driven", "free_swing")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def read_lyap_json(cdir):
    """λ₁ from a clip's lyapunov.json (the canonical per-clip value written by
    lyapunov.py), or NaN if the file is missing/unreadable."""
    path = os.path.join(cdir, "lyapunov.json")
    if not os.path.exists(path):
        return np.nan
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f).get("lambda1")
        return float(v) if v is not None else np.nan
    except (ValueError, OSError):
        return np.nan


def load_clip(csv_path):
    """Clean (t, th1, th2)."""
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
    if len(t) < 200:
        raise ValueError(f"only {len(t)} clean frames")
    return np.array(t), np.array(th1), np.array(th2)


def clip_metrics(t, th1, th2, f_drive, transient_s, with_lyap):
    keep = t >= (t[0] + transient_s)
    if keep.sum() > 200:
        t, th1, th2 = t[keep], th1[keep], th2[keep]

    # loops — lower arm (theta2 absolute)
    wm = winding_metrics(th2)

    # resonance amplitude — upper arm
    th1_rms = float(np.sqrt(np.mean((th1 - th1.mean()) ** 2)))

    # phase locking — upper arm vs drive
    psi = cyclic_phase(th1)[0]
    dphi, _ = drive_relative(t, psi, f_drive)
    pm = phase_metrics(t, psi, dphi, f_drive, 0.0)

    # correlation dimension — lower-arm attractor. Embed the angular
    # VELOCITY ω₂ (stationary under circulation); embedding the unbounded
    # unwrapped angle is drift-dominated and inflates D₂ past m on the
    # rotating/chaotic clips. Mirrors dimension.compute() (single source).
    phi2 = np.degrees(np.unwrap(np.radians(th2)))
    om2 = np.gradient(phi2, t)
    tau = autocorr_tau(om2)
    dt = float(np.median(np.diff(t)))
    theiler = max(tau, int(round(0.5 / dt)) if dt > 0 else tau)
    corr = correlation_dimension(embed(om2, 5, tau), theiler, n_pairs=150000)
    d2 = corr["D2"] if corr else np.nan

    # λ₁ is read from each clip's lyapunov.json in collect() (the canonical
    # per-clip value from lyapunov.py); never recomputed here.
    lam = np.nan

    return {
        "loops":       wm["total_turns"],
        "net_turns":   wm["net_turns"],
        "D2":          d2,
        "theta1_rms":  th1_rms,
        "freq_ratio":  pm["freq_ratio_to_drive"],
        "slip":        pm["slip_rate_cycles_per_s"],
        "lambda1":     lam,
    }


def collect(voltage, transient_s, with_lyap):
    rows = []
    for stem, _dir in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        cdir = clip_dir(stem)
        csv_path = next((os.path.join(cdir, n) for n in
                         ("verification.csv", "tracking.csv")
                         if os.path.exists(os.path.join(cdir, n))), None)
        if csv_path is None:
            continue
        try:
            t, th1, th2 = load_clip(csv_path)
            m = clip_metrics(t, th1, th2, meta["f_drive_hz"], transient_s, with_lyap)
        except (ValueError, SystemExit) as e:
            console.print(f"  [yellow]skip {stem}: {e}[/]")
            continue
        m["lambda1"] = read_lyap_json(cdir)
        console.print(f"  [dim]{stem:<16} D2={m['D2']:.2f} loops={m['loops']:.0f} "
                      f"ratio={m['freq_ratio']:.2f}[/]")
        rows.append((meta["f_drive_hz"], stem, m))
    rows.sort(key=lambda r: r[0])
    return rows


def make_figure(rows, voltage, with_lyap, out_path):
    f = np.array([r[0] for r in rows])
    g = lambda k: np.array([r[2][k] for r in rows])
    panels = [("D2", "correlation dim D₂", "tab:purple", 1.0),
              ("loops", "lower-arm loops", "tab:red", None),
              ("theta1_rms", "upper-arm θ₁ RMS (deg)", "tab:blue", None),
              ("freq_ratio", "f_resp / f_drive (θ₁)", "tab:green", 1.0)]
    lam_arr = np.array([r[2].get("lambda1", np.nan) for r in rows], dtype=float)
    if np.isfinite(lam_arr).any():
        panels.append(("lambda1", "λ₁ (1/s)", "tab:orange", 0.0))
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.4 * n), sharex=True)
    for ax, (key, ylab, color, ref) in zip(np.atleast_1d(axes), panels):
        ax.plot(f, g(key), "-o", color=color, ms=4)
        if ref is not None:
            ax.axhline(ref, color="0.6", lw=0.8, ls=":")
        ax.set_ylabel(ylab)
        ax.grid(True, alpha=0.25)
    np.atleast_1d(axes)[0].set_title(
        f"Route to chaos — {voltage:g} V   (per-clip diagnostics vs drive frequency)")
    np.atleast_1d(axes)[-1].set_xlabel("drive frequency (Hz)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def write_csv(rows, voltage, out_path):
    cols = ["loops", "net_turns", "D2", "theta1_rms", "freq_ratio", "slip", "lambda1"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stem", "f_drive_hz", "v_drill_v"] + cols)
        for f_hz, stem, m in rows:
            w.writerow([stem, f"{f_hz:g}", f"{voltage:g}"]
                       + [("" if not np.isfinite(m[c]) else f"{m[c]:.4f}") for c in cols])


def print_table(rows, voltage):
    t = Table(title=f"chaos sweep — {voltage:g} V", box=rich.box.SIMPLE_HEAD,
              title_style="bold cyan")
    for c in ("f (Hz)", "stem", "D₂", "loops", "θ₁ rms", "ratio"):
        t.add_column(c, justify="right" if c != "stem" else "left")
    for f_hz, stem, m in rows:
        d2 = f"{m['D2']:.2f}" if np.isfinite(m["D2"]) else "—"
        t.add_row(f"{f_hz:g}", stem, d2, f"{m['loops']:.0f}",
                  f"{m['theta1_rms']:.0f}", f"{m['freq_ratio']:.2f}")
    console.print(t)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2)
    p.add_argument("--transient", type=float, default=5.0)
    p.add_argument("--with-lyap", action="store_true", dest="with_lyap",
                   help="also compute lambda1 per clip (slow)")
    args = p.parse_args()

    rows = collect(args.voltage, args.transient, args.with_lyap)
    if not rows:
        raise SystemExit(f"no clips at {args.voltage:g} V")

    print_table(rows, args.voltage)
    csv_out = aggregate_path(f"chaos_sweep_{args.voltage:g}V.csv")
    write_csv(rows, args.voltage, csv_out)
    png_out = aggregate_path(f"chaos_sweep_{args.voltage:g}V.png")
    make_figure(rows, args.voltage, args.with_lyap, png_out)
    console.print(f"  [dim]{len(rows)} clips → {csv_out}[/]")
    console.print(f"  [dim]→ {png_out}[/]")


if __name__ == "__main__":
    main()
