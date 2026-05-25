#!/usr/bin/env python3
"""
theta2_timeseries.py — high-resolution lower-arm angle theta2(t) comparison.

Stacks the raw lower-arm angle theta2(t) for several clips so the
regular <-> chaotic texture change is directly legible. This is the
"Figure 1" view: pick a couple of off-resonance (regular) clips and a
couple of in-band (chaotic) clips from a frequency sweep and show how
the time trace itself changes character.

Layout: one row per clip.
  - left  column: the FULL clip (overview) — shared y in [-180, 180],
    so you can see whether the arm stays in libration or wraps over the
    top. The zoom window is shaded.
  - right column: a ZOOM window (default 5-20 s), y auto-scaled, so the
    individual oscillations are resolved — a clean sinusoid for regular
    motion, a non-repeating trace for chaos.

theta2 is the lower arm's ABSOLUTE lab-frame angle (green->red marker
direction), already in [-180, 180] in the tracking output. Wrap
discontinuities at +-180 are masked (NaN) so the line is not drawn as a
vertical streak across the panel.

Per-row annotations (D2, lambda1, loops, regime) are pulled from the
aggregate chaos_sweep_*.csv if present, so the figure self-labels with
the canonical metrics rather than recomputing them.

Usage
~~~~~
  python scripts/analysis/theta2_timeseries.py
  python scripts/analysis/theta2_timeseries.py \
      --stems 3.2V_0.93Hz,3.2V_1.15Hz,3.2V_1.20Hz,3.2V_1.34Hz
  python scripts/analysis/theta2_timeseries.py --zoom 10-25
  python scripts/analysis/theta2_timeseries.py --unwrap   # cumulative angle

Output
~~~~~~
  figures/aggregate/theta2_timeseries_<family>.png
"""

import argparse
import csv
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import clip_dir                       # noqa: E402
from figures_paths import aggregate_path, AGGREGATE  # noqa: E402

DEFAULT_STEMS = ["3.2V_0.93Hz", "3.2V_1.15Hz", "3.2V_1.20Hz", "3.2V_1.34Hz"]

# regime colours echo the repo convention: green = regular, red = chaotic
COL_REGULAR = "#2e8b57"
COL_CHAOTIC = "#c0392b"
COL_UNKNOWN = "#555555"
D2_CHAOS_THRESHOLD = 1.8   # D2 below this -> regular limit cycle; above -> chaotic


def parse_args():
    p = argparse.ArgumentParser(description="High-res theta2(t) comparison.")
    p.add_argument("--stems", default=None,
                   help="comma-separated clip stems (default: 2 regular + "
                        "2 chaotic from the 3.2V sweep)")
    p.add_argument("--zoom", default="5-20",
                   help="zoom window in seconds, e.g. '10-25' (default 5-20)")
    p.add_argument("--unwrap", action="store_true",
                   help="plot cumulative (unwrapped) theta2 instead of wrapped "
                        "+-180; reveals net tumbling")
    p.add_argument("--out", default=None, help="output png path override")
    return p.parse_args()


def stem_freq(stem):
    m = re.search(r"_(\d+(?:\.\d+)?)Hz", stem)
    return float(m.group(1)) if m else 0.0


def family_label(stems):
    m = re.match(r"([0-9.]+V)", stems[0])
    return m.group(1) if m else "set"


def load_metrics():
    """stem -> {D2, lambda1, loops, f_drive_hz} from aggregate chaos_sweep_*.csv."""
    out = {}
    for path in glob.glob(os.path.join(AGGREGATE, "chaos_sweep_*.csv")):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    out[r["stem"]] = r
        except (OSError, KeyError):
            continue
    return out


def load_theta2(stem):
    path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    t, th = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("driven", "free_swing"):
                continue
            try:
                t.append(float(r["time_s"]))
                th.append(float(r["theta2_deg"]))
            except (KeyError, ValueError):
                continue
    if not t:
        raise ValueError(f"no rows in {path}")
    t = np.asarray(t, dtype=float)
    th = np.asarray(th, dtype=float)
    return t - t[0], th


def mask_wraps(y, thresh=180.0):
    """Break the line (NaN) wherever |dy| exceeds thresh, so the +-180 wrap
    is not drawn as a vertical streak. Returns a copy."""
    y = y.astype(float).copy()
    jumps = np.where(np.abs(np.diff(y)) > thresh)[0]
    y[jumps] = np.nan
    return y


def classify(meta):
    if meta is None:
        return "?", COL_UNKNOWN
    try:
        d2 = float(meta["D2"])
    except (KeyError, ValueError, TypeError):
        return "?", COL_UNKNOWN
    if d2 >= D2_CHAOS_THRESHOLD:
        return "CHAOTIC", COL_CHAOTIC
    return "REGULAR", COL_REGULAR


def metric_caption(meta):
    if meta is None:
        return ""
    def g(k):
        try:
            return float(meta[k])
        except (KeyError, ValueError, TypeError):
            return float("nan")
    d2, lam, loops = g("D2"), g("lambda1"), g("loops")
    bits = []
    if np.isfinite(d2):
        bits.append(rf"$D_2$={d2:.2f}")
    if np.isfinite(lam):
        bits.append(rf"$\lambda_1$={lam:+.2f}/s")
    if np.isfinite(loops):
        bits.append(rf"loops={loops:.0f}")
    return "   ".join(bits)


def main():
    args = parse_args()
    stems = ([s.strip() for s in args.stems.split(",")]
             if args.stems else list(DEFAULT_STEMS))
    stems.sort(key=stem_freq)

    try:
        zlo, zhi = (float(x) for x in args.zoom.split("-"))
    except ValueError:
        raise SystemExit(f"bad --zoom '{args.zoom}', expected 'A-B'")

    metrics = load_metrics()

    clips = []
    for stem in stems:
        try:
            t, th = load_theta2(stem)
        except (FileNotFoundError, ValueError) as e:
            print(f"  skip {stem}: {e}")
            continue
        clips.append((stem, t, th, metrics.get(stem)))
    if not clips:
        raise SystemExit("no clips loaded.")

    n = len(clips)
    fig, axes = plt.subplots(
        n, 2, figsize=(14, 2.5 * n), dpi=200, squeeze=False,
        gridspec_kw={"width_ratios": [2.3, 1.0]})

    ylabel = r"$\theta_2$ cumulative (deg)" if args.unwrap else r"$\theta_2$ (deg)"

    for i, (stem, t, th, meta) in enumerate(clips):
        regime, col = classify(meta)
        freq = stem_freq(stem)
        if args.unwrap:
            series = np.degrees(np.unwrap(np.radians(th)))
            ov = series
        else:
            series = th
            ov = mask_wraps(series)

        ax_ov, ax_zm = axes[i, 0], axes[i, 1]

        # overview (full clip)
        ax_ov.plot(t, ov, lw=0.5, color=col, solid_capstyle="round")
        ax_ov.axvspan(zlo, zhi, color="0.82", alpha=0.6, zorder=0, lw=0)
        ax_ov.set_ylabel(ylabel, fontsize=10)
        ax_ov.grid(True, alpha=0.25)
        ax_ov.set_xlim(t[0], t[-1])
        if not args.unwrap:
            ax_ov.set_ylim(-188, 188)
            ax_ov.set_yticks([-180, -90, 0, 90, 180])
        title = f"{freq:g} Hz    {regime}"
        ax_ov.set_title(title, loc="left", color=col, fontsize=12,
                        fontweight="bold")
        cap = metric_caption(meta)
        if cap:
            ax_ov.text(0.995, 0.04, cap, transform=ax_ov.transAxes,
                       ha="right", va="bottom", fontsize=9, color="0.25",
                       bbox=dict(boxstyle="round,pad=0.25", fc="white",
                                 ec="0.8", alpha=0.85))

        # zoom window
        zsel = (t >= zlo) & (t <= zhi)
        if not args.unwrap:
            zy = mask_wraps(series[zsel]) if zsel.any() else series[zsel]
        else:
            zy = series[zsel]
        ax_zm.plot(t[zsel], zy, lw=0.8, color=col, solid_capstyle="round")
        ax_zm.grid(True, alpha=0.25)
        ax_zm.set_xlim(zlo, min(zhi, t[-1]))
        if i == 0:
            ax_zm.set_title(f"zoom: {zlo:g}-{zhi:g} s", loc="left",
                            fontsize=11, color="0.3")

        if i == n - 1:
            ax_ov.set_xlabel("time (s)", fontsize=10)
            ax_zm.set_xlabel("time (s)", fontsize=10)

    sub = "cumulative angle" if args.unwrap else r"wrapped to $\pm180\degree$"
    fig.suptitle(
        rf"Lower-arm angle $\theta_2(t)$ — regular vs chaotic across drive "
        rf"frequency  ({family_label(stems)} sweep, {sub})",
        fontsize=14, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.985))

    suffix = "_cumulative" if args.unwrap else ""
    out = args.out or aggregate_path(
        f"theta2_timeseries_{family_label(stems)}{suffix}.png")
    fig.savefig(out, dpi=200)
    plt.close(fig)

    print(f"clips: {', '.join(s for s, *_ in clips)}")
    print(f"zoom : {zlo:g}-{zhi:g} s")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
