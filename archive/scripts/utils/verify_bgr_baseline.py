"""
verify_bgr_baseline.py
----------------------
Regression check: assert that the integrated bgr_tracker.py produces
output identical to the frozen baselines from
scripts/utils/capture_bgr_baseline.py — which themselves are
provably what archive/cohen_get_video_coords.py (cohen) produces, because the
detection body is copy-pasted verbatim.

This is the acceptance gate for the BGR-tracker integration: if all
three baseline clips return MATCH, the refactor introduced no
behavioural drift from Cohen's standalone.

Per-row checks
~~~~~~~~~~~~~~
For every (baseline, tracking) row pair:
  1. frame index identical                                  (must)
  2. time_s within TIME_TOL_S                               (CSV precision)
  3. green pixel match after un-crop:                       (must)
       baseline.gx_crop + CROP_X_START == tracking.x_green
       baseline.gy_crop                == tracking.y_green
  4. red pixel match after un-crop                          (must)
  5. dropout pattern match: baseline has any-None cell      (must)
       ↔ tracking.dropout == 1
  6. theta1, theta2 within ANGLE_TOL_DEG of values computed
     from baseline pixels with the same compute_angle (PIVOT)
     used by bgr_tracker                                    (CSV precision)

Tolerances
~~~~~~~~~~
TIME_TOL_S    = 1e-4   # baseline writes .6f, tracking writes .5f
ANGLE_TOL_DEG = 2e-3   # tracking angles round to .3f → ≤ 5e-4 per side
Pixels: zero tolerance (integers, derived from the same BGR moments).

Usage
~~~~~
    python scripts/utils/verify_bgr_baseline.py --stem 4V_1.9Hz
    python scripts/utils/verify_bgr_baseline.py --all

Exit code 0 only when every checked clip returns MATCH.
"""

import argparse
import csv
import math
import os
import sys

os.environ.setdefault("CHAOS_PHASE", "week5-6-pendulum-motor-driven")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import PHASE_ROOT, MEAS_DIR, REPO_ROOT, clip_dir  # noqa: E402
from thresholds import PIVOT, CROP_X_START  # noqa: E402

BASELINES_DIR = os.path.join(PHASE_ROOT, "baselines")

TIME_TOL_S    = 1e-4
ANGLE_TOL_DEG = 2e-3


def compute_angle(p_from, p_to):
    """0° = straight down; +90 = right. Matches bgr_tracker.compute_angle."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return math.degrees(math.atan2(dx, dy))


def _maybe_int(s):
    return int(s) if s != "" else None


def _maybe_float(s):
    return float(s) if s != "" else None


def load_baseline(stem):
    path = os.path.join(BASELINES_DIR, stem, "centroids.csv")
    if not os.path.exists(path):
        raise SystemExit(f"ERROR: baseline not found: {path}")
    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "frame":   int(r["frame"]),
                "time_s":  float(r["time_s"]),
                "gx_crop": _maybe_int(r["gx_crop"]),
                "gy_crop": _maybe_int(r["gy_crop"]),
                "rx_crop": _maybe_int(r["rx_crop"]),
                "ry_crop": _maybe_int(r["ry_crop"]),
            })
    return rows


def load_tracking(stem):
    path = os.path.join(clip_dir(stem), "tracking.csv")
    if not os.path.exists(path):
        raise SystemExit(f"ERROR: tracking.csv not found: {path}")
    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "frame":      int(r["frame"]),
                "time_s":     float(r["time_s"]),
                "phase":      r["phase"],
                "x_green":    _maybe_int(r["x_green"]),
                "y_green":    _maybe_int(r["y_green"]),
                "x_red":      _maybe_int(r["x_red"]),
                "y_red":      _maybe_int(r["y_red"]),
                "theta1_deg": _maybe_float(r["theta1_deg"]),
                "theta2_deg": _maybe_float(r["theta2_deg"]),
                "dropout":    int(r["dropout"]),
            })
    return rows


def verify_one(stem):
    print(f"verify  {stem}")
    baseline = load_baseline(stem)
    tracking = load_tracking(stem)

    if len(baseline) != len(tracking):
        print(f"  FAIL — row count: baseline={len(baseline)}  tracking={len(tracking)}")
        return False

    fails = []
    n_pixel_ok = n_dropout_ok = n_angle_ok = 0

    for i, (b, t) in enumerate(zip(baseline, tracking)):
        if b["frame"] != t["frame"]:
            fails.append((i, f"frame index mismatch: baseline={b['frame']}  tracking={t['frame']}"))
            continue

        if abs(b["time_s"] - t["time_s"]) > TIME_TOL_S:
            fails.append((i, f"time_s diff {abs(b['time_s'] - t['time_s']):.2e} > {TIME_TOL_S}"))

        # Un-crop baseline pixels (X-only crop; Y is unchanged).
        bgx = b["gx_crop"] + CROP_X_START if b["gx_crop"] is not None else None
        bgy = b["gy_crop"]
        brx = b["rx_crop"] + CROP_X_START if b["rx_crop"] is not None else None
        bry = b["ry_crop"]

        # Pixel equality (integer match).
        if bgx == t["x_green"] and bgy == t["y_green"]:
            n_pixel_ok += 1
        else:
            fails.append((i, f"green pixel: baseline=({bgx},{bgy})  tracking=({t['x_green']},{t['y_green']})"))
        if brx == t["x_red"] and bry == t["y_red"]:
            n_pixel_ok += 1
        else:
            fails.append((i, f"red pixel: baseline=({brx},{bry})  tracking=({t['x_red']},{t['y_red']})"))

        # Dropout pattern.
        baseline_dropout = (bgx is None or brx is None)
        tracking_dropout = (t["dropout"] == 1)
        if baseline_dropout == tracking_dropout:
            n_dropout_ok += 1
        else:
            fails.append((i, f"dropout: baseline={'drop' if baseline_dropout else 'keep'}  tracking={t['dropout']}"))

        # Angles — only meaningful when both markers found.
        if bgx is not None and brx is not None and t["theta1_deg"] is not None:
            expected_t1 = compute_angle(PIVOT, (bgx, bgy))
            expected_t2 = compute_angle((bgx, bgy), (brx, bry))
            d1 = abs(expected_t1 - t["theta1_deg"])
            d2 = abs(expected_t2 - t["theta2_deg"])
            if d1 <= ANGLE_TOL_DEG and d2 <= ANGLE_TOL_DEG:
                n_angle_ok += 1
            else:
                fails.append((i, f"angle: Δθ1={d1:.4f}  Δθ2={d2:.4f}  "
                                 f"(expected {expected_t1:.3f}/{expected_t2:.3f}, "
                                 f"got {t['theta1_deg']:.3f}/{t['theta2_deg']:.3f})"))

    n_total = len(baseline)
    n_both_found = sum(1 for b in baseline
                       if b["gx_crop"] is not None and b["rx_crop"] is not None)

    if fails:
        print(f"  FAIL — {len(fails)} mismatches across {n_total} rows")
        for i, msg in fails[:8]:
            print(f"    row {i}: {msg}")
        if len(fails) > 8:
            print(f"    ... and {len(fails) - 8} more")
        return False

    print(f"  MATCH — {n_total} rows")
    print(f"    pixel pairs:    {n_pixel_ok}/{2 * n_total} identical")
    print(f"    dropout flags:  {n_dropout_ok}/{n_total} identical")
    print(f"    angle pairs:    {n_angle_ok}/{n_both_found} within {ANGLE_TOL_DEG}°")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stem", help="Single clip to verify.")
    g.add_argument("--all", action="store_true",
                   help="Verify every stem with a baseline directory.")
    args = ap.parse_args()

    if args.all:
        if not os.path.isdir(BASELINES_DIR):
            print(f"ERROR: {BASELINES_DIR} does not exist.")
            return 2
        stems = sorted(d for d in os.listdir(BASELINES_DIR)
                       if os.path.isdir(os.path.join(BASELINES_DIR, d)))
        if not stems:
            print(f"ERROR: no baselines under {BASELINES_DIR}")
            return 2
    else:
        stems = [args.stem]

    print()
    print("=" * 70)
    print("verify_bgr_baseline  — diff bgr_tracker output against frozen baselines")
    print("=" * 70)

    results = []
    for s in stems:
        ok = verify_one(s)
        results.append((s, ok))
        print()

    n_pass = sum(1 for _, ok in results if ok)
    print("=" * 70)
    print(f"Summary: {n_pass}/{len(results)} MATCH")
    print("=" * 70)
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
