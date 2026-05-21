"""
driven_helpers.py
-----------------
Shared utilities for Phase 2 motor-driven double-pendulum analysis.

Used by:
  scripts/analysis/driven_poincare.py     (single-clip stroboscopic section)
  scripts/analysis/driven_bifurcation.py  (multi-clip parameter sweep)

What's here:
  parse_stem(stem)            -> (V_drill_v, f_drive_hz)
  load_driven_csv(csv_path)   -> (t, th1, th2, om1, om2)
  strobe_sample(t, th1, om1, f_drive, transient_s)
                              -> (t_strobe, th1_strobe, om1_strobe)
  winding_number(t, th1, f_drive, max_denom)
                              -> rational ratio f_peak/f_drive (or NaN)

Conventions
~~~~~~~~~~~
- Stem format: "<V>V_<f>Hz" (or with repeat suffix "_N").  Examples:
  "3V_0.5Hz", "3.6V_1Hz", "2.4V_1Hz_1", "2.45V_1Hz", "3V_0.25Hz".
- Phase 2 verification.csv writes `phase == "driven"` for the driven
  portion (legacy CSVs use "free_swing"). load_driven_csv accepts both
  labels by default.
- Angles in degrees, omegas in deg/s, time in seconds (zero-based).
"""

import csv
import os
import re

import numpy as np


# Matches "<V>V_<f>Hz" with optional "_<repeat>" suffix.
# Groups: 1 = voltage, 2 = frequency, 3 = optional repeat number.
_STEM_RE = re.compile(
    r"^(?P<v>\d+(?:\.\d+)?)V_(?P<f>\d+(?:\.\d+)?)Hz(?:_(?P<rep>\d+))?$"
)


def parse_stem(stem):
    """Extract (V_drill_v, f_drive_hz) from a Phase 2 clip stem.

    Args:
        stem: e.g. "3V_0.5Hz", "3.6V_1Hz", "2.4V_1Hz_1".

    Returns:
        dict with keys 'v_drill_v' (float), 'f_drive_hz' (float),
        'repeat' (int or None).

    Raises:
        ValueError if stem does not match the expected format.
    """
    m = _STEM_RE.match(stem)
    if not m:
        raise ValueError(
            f"Stem {stem!r} does not match '<V>V_<f>Hz[_N]' format.")
    return {
        "v_drill_v":   float(m.group("v")),
        "f_drive_hz":  float(m.group("f")),
        "repeat":      int(m.group("rep")) if m.group("rep") else None,
    }


_DRIVEN_PHASE_LABELS = ("driven", "free_swing")


def load_driven_csv(csv_path, phase_label=None):
    """Load a Phase 2 verification.csv.

    Filters rows where the `phase` column is one of the running-phase
    labels. The tracker writes "driven" since 2026-05-21 but older
    CSVs still tag those rows as "free_swing"; both are accepted by
    default. Drops rows with malformed numeric fields.

    Args:
        csv_path:    path to measurements/<stem>/verification.csv.
        phase_label: row filter on the `phase` column. None (default)
                     accepts both "driven" and legacy "free_swing".
                     Pass an explicit string to restrict to one label.

    Returns:
        (t, th1, th2, om1, om2) numpy arrays, time zero-based.

    Raises:
        SystemExit if too few rows are loaded (< 50).
    """
    if phase_label is None:
        accepted = set(_DRIVEN_PHASE_LABELS)
    else:
        accepted = {phase_label}
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in accepted:
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
                continue
    if len(rows) < 50:
        raise SystemExit(
            f"Too few rows matching {sorted(accepted)} "
            f"({len(rows)}) in {csv_path}.")
    arr = np.array(rows, dtype=float)
    t = arr[:, 0] - arr[0, 0]
    return t, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]


def strobe_sample(t, th1, om1, f_drive, transient_s=5.0):
    """Sample (theta1, omega1) at t = n / f_drive (one point per drive
    period), linearly interpolating between adjacent frames.

    Args:
        t:           time array (seconds, zero-based).
        th1, om1:    theta1, omega1 arrays (same length as t).
        f_drive:     drive frequency in Hz.
        transient_s: seconds to skip at the start (let the attractor settle).

    Returns:
        (t_strobe, th1_strobe, om1_strobe) numpy arrays.  May be empty
        if the data window is shorter than transient_s + 1/f_drive.
    """
    if f_drive <= 0:
        raise ValueError(f"f_drive must be positive, got {f_drive}.")

    T = 1.0 / f_drive
    t_min = t[0] + transient_s
    t_max = t[-1]
    if t_max <= t_min + T:
        return np.array([]), np.array([]), np.array([])

    # First strobe at the smallest n*T >= t_min.
    n0 = int(np.ceil(t_min / T))
    n1 = int(np.floor(t_max / T))
    sample_times = np.arange(n0, n1 + 1) * T

    # numpy.interp handles linear interpolation; arrays are monotone in t.
    th1_s = np.interp(sample_times, t, th1)
    om1_s = np.interp(sample_times, t, om1)
    return sample_times, th1_s, om1_s


def winding_number(t, th1, f_drive, max_denom=6, transient_s=5.0):
    """Estimate f_pendulum / f_drive via FFT of theta1(t).

    Picks the dominant spectral peak (excluding DC) and divides by
    f_drive. The ratio is rounded to the nearest rational with
    denominator <= max_denom (Stern-Brocot via fractions.Fraction).

    Args:
        t:           time array (seconds, uniform spacing assumed).
        th1:         theta1 array (degrees).
        f_drive:     drive frequency in Hz.
        max_denom:   denominator ceiling for the rational fit.
        transient_s: seconds to skip at the start.

    Returns:
        (raw_ratio, rational_ratio) — both floats. Returns
        (np.nan, np.nan) if no clear peak is found.
    """
    from fractions import Fraction

    if len(t) < 32 or f_drive <= 0:
        return np.nan, np.nan

    mask = t >= (t[0] + transient_s)
    if mask.sum() < 32:
        return np.nan, np.nan
    t_s = t[mask]
    x = th1[mask] - np.mean(th1[mask])

    # Sample rate from median dt (robust to occasional gaps).
    dt = float(np.median(np.diff(t_s)))
    if dt <= 0:
        return np.nan, np.nan
    fs = 1.0 / dt

    # FFT.  Take the magnitude of the positive-frequency half.
    n = len(x)
    spec = np.abs(np.fft.rfft(x * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=dt)

    # Ignore DC and frequencies above Nyquist/2 (avoid aliasing edge).
    valid = (freqs > 0.05) & (freqs < fs / 2.5)
    if not valid.any():
        return np.nan, np.nan
    spec_valid = spec[valid]
    freqs_valid = freqs[valid]
    if spec_valid.max() <= 0:
        return np.nan, np.nan

    f_peak = freqs_valid[int(np.argmax(spec_valid))]
    raw = f_peak / f_drive
    rational = float(Fraction(raw).limit_denominator(max_denom))
    return raw, rational


def list_tracked_clips(experiments_dict, measurements_dir):
    """Return [(stem, exp_entry)] for every clip whose verification.csv
    exists on disk.  Sorted by (f_drive_hz, v_drill_v) for stable output.

    Args:
        experiments_dict: parsed experiments.json contents.
        measurements_dir: absolute path to experiments/week5-6-pendulum-motor-driven/measurements.

    Returns:
        list of (stem, entry_dict) tuples.
    """
    out = []
    for stem, entry in experiments_dict.items():
        vc = os.path.join(measurements_dir, stem, "verification.csv")
        if not os.path.exists(vc):
            continue
        out.append((stem, entry))
    out.sort(key=lambda kv: (
        kv[1].get("drive_freq_hz", 0.0),
        kv[1].get("drive_voltage_v", 0.0),
    ))
    return out
