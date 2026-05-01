"""
csv_helpers.py
---------------
Shared CSV-row helpers used by interpolate_suspects, render, and any
other tool that needs to walk a tracking.csv / verification.csv and
distinguish clean rows from dropouts / suspects.

Why this module exists
~~~~~~~~~~~~~~~~~~~~~~
`is_clean_row` and `find_neighbours` define what counts as a "clean"
neighbour for interpolation. They originally lived in
interpolate_suspects.py, but render.py needs the same logic when it
displays an interpolation plan ("frame N's neighbours are M, K"), and
duplicating the predicates would let them drift out of sync. Hosting
them here lets every tool import the same definitions.

Conventions
~~~~~~~~~~~
- Rows are dicts (csv.DictReader output).
- Empty CSV cells parse as math.nan via to_float.
- "clean" = not a dropout, not a suspect, has a θ₂ value.
"""

import math


def to_float(v):
    """Parse a CSV cell to float; empty string → math.nan."""
    if v is None or v == "":
        return math.nan
    return float(v)


def is_clean_row(row):
    """A row is 'clean' if it's not a dropout AND not a suspect AND has
    a θ₂ value. Used when picking interpolation neighbours."""
    if str(row.get("dropout", "")).strip() == "1":
        return False
    if str(row.get("suspect", "")).strip() == "1":
        return False
    if not str(row.get("theta2_deg", "")).strip():
        return False
    return True


def find_neighbours(rows, target_idx):
    """
    Walk outward from target_idx, returning (prev_idx, next_idx) where
    each is the nearest clean neighbour, or None when no such neighbour
    exists in that direction.
    """
    prev_idx = None
    for j in range(target_idx - 1, -1, -1):
        if is_clean_row(rows[j]):
            prev_idx = j
            break
    next_idx = None
    for j in range(target_idx + 1, len(rows)):
        if is_clean_row(rows[j]):
            next_idx = j
            break
    return prev_idx, next_idx
