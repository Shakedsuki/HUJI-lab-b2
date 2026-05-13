"""
interpolate_suspects.py
------------------------
Replace the |ω| > cap suspect frames flagged by verify_tracking.py with
linear interpolation between nearest clean neighbours, then re-verify.

Why this exists
~~~~~~~~~~~~~~~
The fallback chain in ring_tracker can occasionally latch onto a fixed
wall artifact when the red marker is lost during the highest-energy
chaotic phase of free swing. These false-positive detections sit at
dropout=0 (the tracker reported a confident position) but produce 30°+
single-frame angle jumps and |ω₂| spikes far above the physical
~1500 °/s ceiling — verify_tracking surfaces them as suspect=1.

Re-tracking the whole video is expensive (long_recording is 1.2 GB) and
buys back at most a few dozen frames. Interpolating those frames in
place preserves the rest of the high-quality tracking and is reversible
(the original CSV is backed up).

Geometry
~~~~~~~~
We interpolate θ₂ linearly in time between neighbours, then back-project
to (x_red, y_red) using the actual x_green, y_green at the suspect frame
and the fixed arm length. If green is also missing at the suspect frame,
we mark the row dropout=1 instead of fabricating a green position.

Usage
~~~~~
    python scripts/processing/interpolate_suspects.py --stem th1_p180_th2_m179
    python scripts/processing/interpolate_suspects.py --stem th1_p180_th2_m179 --dry-run
    python scripts/processing/interpolate_suspects.py --stem th1_p180_th2_m179 --omega-cap 2500
"""

import argparse
import csv
import datetime
import json
import math
import os
import shutil
import subprocess
import sys

# Force UTF-8 stdout so unicode glyphs (θ, ω) don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

# ─────────────────────────────────────────────
# CONSTANTS  (mirror ring_tracker.py)
# ─────────────────────────────────────────────

VERIFY_SCRIPT    = os.path.join(REPO_ROOT, "scripts", "processing",
                                "verify_tracking.py")

EXPERIMENTS_FILE = EXPERIMENTS
from render import render_interpolation_plan  # noqa: E402
# Brief 10b: ARM_LENGTH_PX lives in thresholds.py.
from thresholds import ARM_LENGTH_PX  # noqa: E402

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Interpolate suspect frames in a tracking CSV.")
    p.add_argument("--stem", required=True,
                   help="config_description, e.g. th1_p180_th2_m179.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would change but do not modify files.")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="deg/s threshold passed to the re-verification "
                        "step (default 2500).")
    return p.parse_args()

def load_csv_rows(path):
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    return rows, fieldnames

def write_csv_rows(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

# to_float / is_clean_row / find_neighbours moved to scripts/utils/
# csv_helpers.py so render.py can share the same predicates without
# importing interpolate_suspects (which would create a layering cycle).
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from csv_helpers import (  # noqa: E402
    to_float,
    is_clean_row,
    find_neighbours,
)

def linear_interp(t, t0, v0, t1, v1):
    """Linear interpolation; falls back to v0 if t1 == t0."""
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

def interp_theta2(prev_row, next_row, target_row):
    """
    Interpolate θ₂ at target_row's time between prev/next clean rows.
    Either neighbour may be None (handled with constant extrapolation).
    Returns float in degrees, or None if both neighbours are None.
    """
    t = to_float(target_row["time_s"])
    if prev_row is None and next_row is None:
        return None
    if prev_row is None:
        return to_float(next_row["theta2_deg"])
    if next_row is None:
        return to_float(prev_row["theta2_deg"])
    t0 = to_float(prev_row["time_s"])
    t1 = to_float(next_row["time_s"])
    v0 = to_float(prev_row["theta2_deg"])
    v1 = to_float(next_row["theta2_deg"])
    # Unwrap once across ±180 so the interpolation goes the short way.
    delta = ((v1 - v0 + 180.0) % 360.0) - 180.0
    interp = linear_interp(t, t0, v0, t1, v0 + delta)
    return ((interp + 180.0) % 360.0) - 180.0

def red_pos_from_geometry(x_green, y_green, theta2_deg):
    """
    Reproject (x_red, y_red) from green's pixel position and θ₂. Uses
    the same convention as ring_tracker.compute_angle:
      0 = down, +90 = right, ±180 = up.
    Returns integer pixel coordinates.
    """
    rad = math.radians(theta2_deg)
    x = x_green + ARM_LENGTH_PX * math.sin(rad)
    y = y_green + ARM_LENGTH_PX * math.cos(rad)
    return int(round(x)), int(round(y))

def update_registry_after_interp(stem, n_interpolated, n_unresolvable):
    """Add suspect_frames_interpolated + interpolation_date for stem."""
    if not os.path.exists(EXPERIMENTS_FILE):
        return
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        reg = json.load(f)
    target_key = None
    for k, e in reg.items():
        if e.get("config_description") == stem:
            target_key = k
            break
    if target_key is None:
        print(f"WARN: no registry entry has config_description '{stem}'; "
              f"not updating experiments.json.")
        return
    iso = datetime.datetime.now().strftime("%Y-%m-%d")
    reg[target_key]["suspect_frames_interpolated"] = n_interpolated
    reg[target_key]["interpolation_date"]           = iso
    if n_unresolvable:
        reg[target_key]["suspect_frames_unresolvable"] = n_unresolvable
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)
    print(f"Registry updated: '{target_key}' "
          f"(suspect_frames_interpolated={n_interpolated}, date={iso}).")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    meas_dir = os.path.join(MEAS_DIR, args.stem)
    csv_path  = os.path.join(meas_dir, "tracking.csv")
    verif_csv = os.path.join(meas_dir, "verification.csv")

    if not os.path.exists(csv_path):
        print(f"ERROR: tracking CSV not found: {csv_path}")
        return 1
    if not os.path.exists(verif_csv):
        print(f"ERROR: verification.csv not found: {verif_csv}")
        print("  Run: python scripts/processing/verify_tracking.py "
              f"--stem {args.stem}")
        return 1

    print(f"interpolate_suspects.py")
    print(f"Stem   : {args.stem}")
    print(f"CSV    : {csv_path}")
    print(f"Verif  : {verif_csv}")
    print(f"Mode   : {'DRY-RUN (no writes)' if args.dry_run else 'in-place'}")
    print()

    # ── Load both CSVs ─────────────────────────────────────────────────
    track_rows, track_fields = load_csv_rows(csv_path)
    verif_rows, _            = load_csv_rows(verif_csv)

    if len(track_rows) != len(verif_rows):
        print(f"WARN: tracking rows ({len(track_rows)}) != verification "
              f"rows ({len(verif_rows)}); aligning by frame index.")
    # Always build by frame, never positional — keeps render and the
    # interpolation walk in agreement even when the two CSVs drift
    # in row count (e.g., after a partial re-track).
    verif_by_frame = {int(r["frame"]): r for r in verif_rows}

    # ── Stamp tracking rows with suspect status from verification ────
    # (verify_tracking.py uses time-derivative ω which is a row-level fact;
    # we attach it temporarily so is_clean_row sees it.)
    for row in track_rows:
        vrow = verif_by_frame.get(int(row["frame"]))
        if vrow is None:
            row["suspect"] = "0"
            continue
        row["suspect"] = vrow.get("suspect", "0")

    suspect_idxs = [i for i, r in enumerate(track_rows)
                    if str(r.get("suspect", "")).strip() == "1"]

    if not suspect_idxs:
        print("No suspect frames found — nothing to interpolate.")
        return 0

    # ── Plan table (delegated to render so it matches the verdict
    # panel's visual style). ────────────────────────────────────────
    render_interpolation_plan(
        suspect_idxs,
        track_rows,
        verif_by_frame,
        dry_run=args.dry_run,
    )

    # ── Compute interpolated values ────────────────────────────────────
    n_interpolated   = 0
    n_unresolvable   = 0
    interpolated_log = []

    for i in suspect_idxs:
        target = track_rows[i]
        prev_idx, next_idx = find_neighbours(track_rows, i)
        prev_row = track_rows[prev_idx] if prev_idx is not None else None
        next_row = track_rows[next_idx] if next_idx is not None else None

        # If green is missing at the suspect frame we cannot back-project
        # red — flag it as a genuine dropout instead of fabricating data.
        x_green = to_float(target.get("x_green", ""))
        y_green = to_float(target.get("y_green", ""))
        if math.isnan(x_green) or math.isnan(y_green):
            n_unresolvable += 1
            interpolated_log.append((int(target["frame"]),
                                     "unresolvable (green missing)"))
            target["x_red"]      = ""
            target["y_red"]      = ""
            target["theta2_deg"] = ""
            target["dropout"]    = "1"
            continue

        theta2 = interp_theta2(prev_row, next_row, target)
        if theta2 is None:
            n_unresolvable += 1
            interpolated_log.append((int(target["frame"]),
                                     "unresolvable (no neighbours)"))
            continue

        x_red, y_red = red_pos_from_geometry(x_green, y_green, theta2)
        old_th2 = target.get("theta2_deg") or "—"
        target["theta2_deg"] = f"{theta2:.3f}"
        target["x_red"]      = str(x_red)
        target["y_red"]      = str(y_red)
        target["dropout"]    = "0"
        n_interpolated += 1
        interpolated_log.append((int(target["frame"]),
                                 f"θ₂ {old_th2} → {theta2:.3f}  "
                                 f"red→({x_red},{y_red})"))

    print()
    print(f"Plan: interpolate {n_interpolated} frames, "
          f"{n_unresolvable} unresolvable (kept as dropouts).")
    print(f"Sample of interpolations:")
    for frame_no, msg in interpolated_log[:8]:
        print(f"  f{frame_no}: {msg}")
    if len(interpolated_log) > 8:
        print(f"  ... and {len(interpolated_log) - 8} more")
    print()

    if args.dry_run:
        print("DRY-RUN — no files written.")
        return 0

    # ── Strip the temporary `suspect` column before writing ───────────
    for r in track_rows:
        r.pop("suspect", None)

    # ── Back up the original CSV ───────────────────────────────────────
    backup_path = csv_path + ".bak"
    if os.path.exists(backup_path):
        print(f"Backup already exists: {backup_path} (leaving in place)")
    else:
        shutil.copy2(csv_path, backup_path)
        print(f"Backup written: {backup_path}")

    # ── Write corrected CSV in place ──────────────────────────────────
    write_csv_rows(csv_path, track_rows, track_fields)
    print(f"Corrected CSV: {csv_path}")

    # ── Update registry ───────────────────────────────────────────────
    update_registry_after_interp(args.stem, n_interpolated, n_unresolvable)

    # ── Re-run verification ───────────────────────────────────────────
    print()
    print("=" * 60)
    print("Re-running verify_tracking.py for confirmation ...")
    print("=" * 60)
    rc = subprocess.run(
        [sys.executable, VERIFY_SCRIPT, "--stem", args.stem,
         "--omega-cap", str(args.omega_cap), "--no-plot"],
        cwd=REPO_ROOT,
    ).returncode

    # ── Final summary ─────────────────────────────────────────────────
    print()
    print(f"Interpolated {n_interpolated} frames. {n_unresolvable} "
          f"unresolvable. Backup at {os.path.relpath(backup_path, REPO_ROOT)}.")
    return 0 if rc == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
