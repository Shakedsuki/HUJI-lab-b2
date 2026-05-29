#!/usr/bin/env python3
"""
report_common.py — shared conventions for the final-report figures.

Everything the report's figure scripts need to agree on lives here, so the
measurements stay homogeneous across plots. The central piece is the
time-slice rule (``tail_window``): every report figure analyses the SAME
part of each clip — the last ``window_s`` seconds, anchored at the end of
the recording (after transients have died) — mirroring the slice the FFT
waterfall (``spectral_waterfall.py``) already uses. The window LENGTH may
differ per figure (the FFT wants ~60 s for frequency resolution; a θ₂
trace wants ~10 s to stay readable), but the slicing RULE is identical.

This module also wires the repo's ``scripts/utils`` onto sys.path so report
scripts can reuse ``paths`` (clip_dir, MEAS_DIR) without copying it.
"""

import glob
import os
import re
import sys

import numpy as np

# --- make the repo's scripts/utils importable from reports/final/scripts/ ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
_UTILS = os.path.join(_REPO_ROOT, "scripts", "utils")
if _UTILS not in sys.path:
    sys.path.insert(0, _UTILS)

from paths import MEAS_DIR, clip_dir            # noqa: E402

# report output lives one level up from this scripts/ dir
FIGURES_DIR = os.path.normpath(os.path.join(_HERE, "..", "figures"))
DATA_DIR = os.path.normpath(os.path.join(_HERE, "..", "data"))

# --- homogenised analysis window -------------------------------------------
# Default for time-domain report figures. The FFT waterfall overrides this
# with its own (longer) window for frequency resolution, but via tail_window
# so the "last N seconds, anchored at the end" rule stays identical.
TIME_WINDOW_S = 10.0

# regime palette — repo convention: green = regular, red = chaotic
COL_REGULAR = "#2e8b57"
COL_CHAOTIC = "#c0392b"
COL_UNKNOWN = "#555555"
D2_CHAOS_THRESHOLD = 1.8   # D2 below -> regular limit cycle; above -> chaotic


def tail_window(t, *arrays, window_s=TIME_WINDOW_S, rezero=True):
    """Keep the LAST ``window_s`` seconds of a clip, anchored at ``t.max()``.

    This is the report-wide time-slice rule, mirrored from the FFT waterfall:
        cutoff = t.max() - min(window_s, span);  keep t >= cutoff
    so we always look at steady-state behaviour, never the startup transient.

    Parameters
    ----------
    t : array of times (s), assumed monotonically increasing
    *arrays : any number of equal-length series to slice with the same mask
    window_s : window length in seconds (default TIME_WINDOW_S = 10)
    rezero : if True, shift the returned time axis so it starts at 0
             (the report's θ₂ panels use a 0–window_s axis).

    Returns
    -------
    (t_sliced, *arrays_sliced) — same arity as the inputs.
    """
    t = np.asarray(t, dtype=float)
    if t.size == 0:
        return (t, *[np.asarray(a, float) for a in arrays])
    span = t.max() - t.min()
    cutoff = t.max() - min(window_s, span)
    mask = t >= cutoff
    t_out = t[mask]
    if rezero and t_out.size:
        t_out = t_out - t_out[0]
    outs = [np.asarray(a, dtype=float)[mask] for a in arrays]
    return (t_out, *outs)


def stem_freq(stem):
    """Drive frequency (Hz) parsed from a clip stem, e.g. 3.2V_1.20Hz -> 1.20.
    Handles trailing take indices like 3.2V_1.33Hz_2."""
    m = re.search(r"_(\d+(?:\.\d+)?)Hz", stem)
    return float(m.group(1)) if m else 0.0


def list_clips(require="verification.csv"):
    """Every clip stem in the active phase that has ``require`` on disk,
    sorted by drive frequency (then stem, so _1/_2 takes stay ordered)."""
    stems = []
    for path in glob.glob(os.path.join(MEAS_DIR, "*", require)):
        stems.append(os.path.basename(os.path.dirname(path)))
    return sorted(stems, key=lambda s: (stem_freq(s), s))


def select_low_mid_high(stems=None):
    """Pick (lowest-freq, middle-of-sweep, highest-freq) clips.

    'middle' is the median position in the frequency-sorted list — squarely
    in the chaotic core of the 3.2 V sweep — not the value-midpoint, so the
    figure reads as a beginning / middle / end progression.
    """
    if stems is None:
        stems = list_clips()
    if len(stems) < 3:
        raise ValueError(f"need >=3 clips, found {len(stems)}: {stems}")
    return [stems[0], stems[len(stems) // 2], stems[-1]]


def select_evenly(n, stems=None):
    """Pick n clips evenly spaced across the frequency-sorted sweep, endpoints
    included — a left-to-right sample of the route to chaos. Dedupes if n is
    large relative to the clip count."""
    if stems is None:
        stems = list_clips()
    if len(stems) < n:
        raise ValueError(f"need >={n} clips, found {len(stems)}")
    idx = [round(i * (len(stems) - 1) / (n - 1)) for i in range(n)]
    out, seen = [], set()
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(stems[i])
    return out


def load_metrics():
    """stem -> row dict from the aggregate chaos_sweep_*.csv (D2, lambda1...).
    Returns {} if no such csv is found."""
    import csv
    sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts", "utils"))
    try:
        from figures_paths import AGGREGATE
    except ImportError:
        return {}
    out = {}
    for path in glob.glob(os.path.join(AGGREGATE, "chaos_sweep_*.csv")):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    out[r["stem"]] = r
        except (OSError, KeyError):
            continue
    return out


def classify(meta):
    """(regime_label, colour) from a metrics row dict (or None)."""
    if meta is None:
        return "?", COL_UNKNOWN
    try:
        d2 = float(meta["D2"])
    except (KeyError, ValueError, TypeError):
        return "?", COL_UNKNOWN
    if d2 >= D2_CHAOS_THRESHOLD:
        return "CHAOTIC", COL_CHAOTIC
    return "REGULAR", COL_REGULAR
