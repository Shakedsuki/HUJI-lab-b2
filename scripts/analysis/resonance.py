#!/usr/bin/env python3
"""
resonance.py — driven-pendulum resonance sweep.

Holds drive voltage fixed and sweeps drive frequency (the week6 3.2V
family by default), measuring the steady-state response of the system vs
f_drive. The response peaks at the resonance frequency f0.

The driven oscillator is the UPPER arm (θ₁); its amplitude/velocity
response vs f_drive is the classic resonance curve. The lower arm (θ₂,
already absolute) is the chaotic responder — its activity marks the band
where the drive pumps it over the top.

Per clip (steady-state window, transient skipped):
  theta1_rms_deg     RMS oscillation amplitude of the upper arm  (resonance)
  theta1_peak_deg    99th-pct |θ₁ − mean|                        (peak amp)
  omega1_rms_deg_s   RMS angular velocity of the upper arm        (velocity
                     resonance — peaks sharply near f0)
  theta2_rms_deg     RMS of θ₂ − mean (lower arm; saturates in the band)
  omega2_rms_deg_s   RMS lower-arm velocity (large in the chaotic band)
  resp_freq_hz       dominant FFT frequency of θ₁
  freq_ratio         resp_freq / f_drive  (≈ 1 ⇒ 1:1 locked)

ω is computed from the angle (gradient of the unwrapped signal) so the
result does not depend on whether verification.csv exists.

Outputs:
  figures/aggregate/resonance_<V>V.png   (response curves vs f_drive)
  figures/aggregate/resonance_<V>V.csv

Usage:
  python scripts/analysis/resonance.py
  python scripts/analysis/resonance.py --voltage 4.0   # CHAOS_PHASE=week5
  python scripts/analysis/resonance.py --transient 8
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

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir, iter_clip_dirs       # noqa: E402
from figures_paths import aggregate_path          # noqa: E402
from driven_helpers import parse_stem             # noqa: E402

RUN_PHASES = ("driven", "free_swing")


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    """Clean (t, th1, th2): running phase, dropout 0, finite angles."""
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
        raise ValueError(f"only {len(t)} clean frames in {csv_path}")
    return np.array(t), np.array(th1), np.array(th2)


def _omega(t, theta_deg):
    """dθ/dt (deg/s) from the unwrapped angle — source-independent."""
    phi = np.degrees(np.unwrap(np.radians(theta_deg)))
    return np.gradient(phi, t)


def fft_peak_freq(t, x):
    """Dominant spectral frequency of x (Hz), excluding DC."""
    n = len(x)
    if n < 32:
        return np.nan
    dt = float(np.median(np.diff(t)))
    if dt <= 0:
        return np.nan
    spec = np.abs(np.fft.rfft((x - np.mean(x)) * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=dt)
    valid = (freqs > 0.05) & (freqs < (1.0 / dt) / 2.5)
    if not valid.any() or spec[valid].max() <= 0:
        return np.nan
    return float(freqs[valid][int(np.argmax(spec[valid]))])


def response_metrics(t, th1, th2, f_drive, transient_s):
    m = t >= (t[0] + transient_s)
    if m.sum() < 32:
        m = np.ones_like(t, dtype=bool)
    tt, t1, t2 = t[m], th1[m], th2[m]
    om1, om2 = _omega(t, th1)[m], _omega(t, th2)[m]

    t1c = t1 - np.mean(t1)
    t2c = t2 - np.mean(t2)
    resp_freq = fft_peak_freq(tt, t1c)
    return {
        "theta1_rms_deg":   float(np.sqrt(np.mean(t1c ** 2))),
        "theta1_peak_deg":  float(np.percentile(np.abs(t1c), 99)),
        "omega1_rms_deg_s": float(np.sqrt(np.mean(om1 ** 2))),
        "theta2_rms_deg":   float(np.sqrt(np.mean(t2c ** 2))),
        "omega2_rms_deg_s": float(np.sqrt(np.mean(om2 ** 2))),
        "resp_freq_hz":     resp_freq,
        "freq_ratio":       (resp_freq / f_drive) if f_drive else np.nan,
    }


def collect(voltage, transient_s):
    """Sorted [(f_drive, stem, metrics)] for clips at `voltage`."""
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
        except ValueError as e:
            console.print(f"  [yellow]skip {stem}: {e}[/]")
            continue
        rows.append((meta["f_drive_hz"], stem,
                     response_metrics(t, th1, th2, meta["f_drive_hz"], transient_s)))
    rows.sort(key=lambda r: r[0])
    return rows


# ─────────────────────────────────────────────
# RESONANCE ESTIMATE
# ─────────────────────────────────────────────

def estimate_f0_q(freqs, resp):
    """Peak frequency f0 and a rough Q = f0 / FWHM from a response curve.
    FWHM = contiguous span around the peak above peak/√2 (amplitude
    half-power). Rough for a nonlinear band — report with a caveat."""
    f = np.asarray(freqs, float)
    y = np.asarray(resp, float)
    ok = np.isfinite(y)
    if ok.sum() < 3:
        return np.nan, np.nan, np.nan
    i0 = int(np.nanargmax(np.where(ok, y, -np.inf)))
    f0, peak = f[i0], y[i0]
    half = peak / np.sqrt(2.0)
    lo = i0
    while lo > 0 and np.isfinite(y[lo - 1]) and y[lo - 1] >= half:
        lo -= 1
    hi = i0
    while hi < len(f) - 1 and np.isfinite(y[hi + 1]) and y[hi + 1] >= half:
        hi += 1
    fwhm = f[hi] - f[lo]
    q = (f0 / fwhm) if fwhm > 0 else np.nan
    return float(f0), float(q), float(fwhm)


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

def print_table(rows, voltage, f0, q):
    t = Table(title=f"resonance sweep — {voltage:g} V",
              box=rich.box.SIMPLE_HEAD, title_style="bold cyan")
    t.add_column("f (Hz)", justify="right")
    t.add_column("stem")
    t.add_column("θ₁ rms°", justify="right")
    t.add_column("ω₁ rms°/s", justify="right")
    t.add_column("ω₂ rms°/s", justify="right")
    t.add_column("f_resp/f_drv", justify="right")
    for f_hz, stem, m in rows:
        t.add_row(f"{f_hz:g}", stem,
                  f"{m['theta1_rms_deg']:.1f}",
                  f"{m['omega1_rms_deg_s']:.0f}",
                  f"{m['omega2_rms_deg_s']:.0f}",
                  f"{m['freq_ratio']:.2f}")
    console.print(t)
    qtxt = f"{q:.1f}" if np.isfinite(q) else "—"
    console.print(f"  [bold]resonance f₀ ≈ {f0:.3f} Hz[/]  "
                  f"[dim](peak θ₁ amplitude; rough Q ≈ {qtxt})[/]")
    console.print("  [dim]nonlinear band — f₀ is the amplitude peak, Q is approximate[/]")


def make_figure(rows, voltage, f0, q, out_path):
    f = np.array([r[0] for r in rows])
    th1_rms = np.array([r[2]["theta1_rms_deg"] for r in rows])
    th1_pk  = np.array([r[2]["theta1_peak_deg"] for r in rows])
    om1_rms = np.array([r[2]["omega1_rms_deg_s"] for r in rows])
    om2_rms = np.array([r[2]["omega2_rms_deg_s"] for r in rows])
    ratio   = np.array([r[2]["freq_ratio"] for r in rows])

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 11), sharex=True)

    # (a) upper-arm amplitude response — the resonance curve.
    ax1.plot(f, th1_rms, "-o", color="tab:blue", ms=4, label="θ₁ RMS")
    ax1.plot(f, th1_pk, "-", color="tab:blue", alpha=0.35, label="θ₁ peak (p99)")
    ax1.axvline(f0, color="0.5", ls="--", lw=1,
                label=f"f₀ ≈ {f0:.3f} Hz")
    ax1.set_ylabel("upper-arm amplitude θ₁ (deg)")
    qtxt = f"{q:.1f}" if np.isfinite(q) else "—"
    ax1.set_title(f"Resonance sweep — {voltage:g} V   "
                  f"(f₀ ≈ {f0:.3f} Hz, rough Q ≈ {qtxt})")
    ax1.grid(True, alpha=0.25)
    ax1.legend(fontsize=8)

    # (b) velocity response: upper (sharp resonance) + lower (chaotic band).
    ax2.plot(f, om1_rms, "-o", color="tab:red", ms=4, label="ω₁ RMS (upper)")
    ax2.plot(f, om2_rms, "--s", color="tab:orange", ms=3, alpha=0.7,
             label="ω₂ RMS (lower, chaotic activity)")
    ax2.axvline(f0, color="0.5", ls="--", lw=1)
    ax2.set_ylabel("velocity RMS (deg/s)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(fontsize=8)

    # (c) response/drive frequency ratio — the 1:1 locking band.
    ax3.plot(f, ratio, "-o", color="tab:green", ms=4)
    for rr in (0.5, 2.0):
        ax3.axhline(rr, color="0.85", lw=0.6, ls=":")
    ax3.axhline(1.0, color="0.6", lw=0.8, ls=":")
    ax3.axvline(f0, color="0.5", ls="--", lw=1)
    ax3.set_ylim(0, 2.5)   # fixed so 1:1 lock reads flat; n:m departures show
    ax3.set_ylabel("f_resp / f_drive")
    ax3.set_xlabel("drive frequency (Hz)")
    ax3.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def write_csv(rows, voltage, out_path):
    cols = ["theta1_rms_deg", "theta1_peak_deg", "omega1_rms_deg_s",
            "theta2_rms_deg", "omega2_rms_deg_s", "resp_freq_hz", "freq_ratio"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stem", "f_drive_hz", "v_drill_v"] + cols)
        for f_hz, stem, m in rows:
            w.writerow([stem, f"{f_hz:g}", f"{voltage:g}"]
                       + [f"{m[c]:.4f}" for c in cols])


# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--voltage", type=float, default=3.2,
                   help="drive voltage to sweep (default: 3.2)")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start of each clip (default: 5)")
    return p.parse_args()


def main():
    args = parse_args()
    rows = collect(args.voltage, args.transient)
    if not rows:
        raise SystemExit(f"no clips found at {args.voltage:g} V")

    f = [r[0] for r in rows]
    f0, q, _fwhm = estimate_f0_q(f, [r[2]["theta1_rms_deg"] for r in rows])

    print_table(rows, args.voltage, f0, q)
    csv_out = aggregate_path(f"resonance_{args.voltage:g}V.csv")
    write_csv(rows, args.voltage, csv_out)
    png_out = aggregate_path(f"resonance_{args.voltage:g}V.png")
    make_figure(rows, args.voltage, f0, q, png_out)
    console.print(f"  [dim]{len(rows)} clips → {csv_out}[/]")
    console.print(f"  [dim]→ {png_out}[/]")


if __name__ == "__main__":
    main()
