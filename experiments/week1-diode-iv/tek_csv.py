"""Tektronix DPO CSV loader for the v2 part1 scripts.

The Tek CSV format used in this experiment interleaves per-channel metadata
in cols 0-2 and 6-8 with data in cols 3-4 (CH1) and 9-10 (CH2). Header rows
0-15 carry parameters we need: sample interval, vertical scale, Yzero offset.

Real voltage on each channel = stored_value + Yzero.

Returns
-------
parse_metadata(path) -> dict with keys:
    dt              : float, seconds per sample
    yzero_ch1       : float, V (additive correction for CH1)
    yzero_ch2       : float, V (additive correction for CH2)
    vscale_ch1      : float, V/div (used for ADC-quantization sigma)
    vscale_ch2      : float, V/div
    record_length   : int, number of data rows
    note            : str, scope timestamp/instrument note (or empty)

load_trace(path, slice_=None) -> (t, ch1, ch2)
    With Yzero already applied. Optionally slice rows.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np


# Metadata appears in the FIRST column of header rows.
# We scan rows 0..16 and pull values by label; row indices vary between
# scope captures so label-based extraction is more robust than fixed indices.
_META_LABELS = {
    "Sample Interval": "dt",
    "Record Length":   "record_length",
    "Vertical Scale":  "vscale",
    "Vertical Offset": "voffset",
    "Yzero":           "yzero",
    "Note":            "note",
}


@dataclass
class TekMeta:
    dt: float
    yzero_ch1: float
    yzero_ch2: float
    vscale_ch1: float
    vscale_ch2: float
    record_length: int
    note: str = ""


def parse_metadata(path: str) -> TekMeta:
    """Read scope metadata from the first ~16 rows of a Tek DPO CSV.

    CH1 metadata lives in cols 0..2; CH2 metadata mirrors it in cols 6..8.
    """
    ch1, ch2 = {}, {}
    with open(path, "r", errors="replace") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i > 17:
                break
            if len(row) < 9:
                continue
            label_ch1, value_ch1 = row[0], row[1] if len(row) > 1 else ""
            label_ch2, value_ch2 = row[6], row[7] if len(row) > 7 else ""
            if label_ch1 in _META_LABELS:
                ch1[_META_LABELS[label_ch1]] = value_ch1
            if label_ch2 in _META_LABELS:
                ch2[_META_LABELS[label_ch2]] = value_ch2

    def _f(d: dict, key: str, default=0.0) -> float:
        try:
            return float(d.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _i(d: dict, key: str, default=0) -> int:
        try:
            return int(float(d.get(key, default)))
        except (TypeError, ValueError):
            return int(default)

    return TekMeta(
        dt=_f(ch1, "dt", default=1e-9),
        yzero_ch1=_f(ch1, "yzero", 0.0),
        yzero_ch2=_f(ch2, "yzero", 0.0),
        vscale_ch1=_f(ch1, "vscale", 1.0),
        vscale_ch2=_f(ch2, "vscale", 1.0),
        record_length=_i(ch1, "record_length", 1_000_000),
        note=str(ch1.get("note", "")),
    )


def load_trace(path: str, slice_: Optional[slice] = None):
    """Load (t, ch1, ch2) with Yzero correction applied.

    `slice_` applies to the *data* rows only (after header skip).
    Uses pandas under the hood for speed; values are pulled from cols 3, 4, 10.
    """
    import pandas as pd

    meta = parse_metadata(path)
    df = pd.read_csv(path, header=None, usecols=[3, 4, 10],
                     dtype={3: float, 4: float, 10: float},
                     low_memory=False, on_bad_lines="skip")
    df = df.dropna()
    if slice_ is not None:
        df = df.iloc[slice_]
    t = df[3].to_numpy()
    ch1 = df[4].to_numpy() + meta.yzero_ch1
    ch2 = df[10].to_numpy() + meta.yzero_ch2
    return t, ch1, ch2, meta


def adc_sigma_volts(vscale_per_div: float, n_div: float = 8.0,
                    n_levels: float = 256.0) -> float:
    """1-sigma ADC quantization noise: vscale * n_div / n_levels / sqrt(12).

    Tek DPO3014 is 8-bit, full vertical screen ≈ 8 divisions.
    """
    return vscale_per_div * n_div / n_levels / np.sqrt(12.0)


def git_sha() -> str:
    """Best-effort short git SHA of the working tree, '' if unavailable."""
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return ""
