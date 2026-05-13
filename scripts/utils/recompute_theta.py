"""
recompute_theta.py
------------------
Recompute theta1_deg in an existing tracking.csv from x_green/y_green
and the current PIVOT. Use this after PIVOT or ARM_LENGTH_PX changes
in thresholds.py to refresh stored angles WITHOUT re-running the
ring tracker (marker pixel positions are unaffected by the constant).

theta2_deg is already independent of PIVOT (it's the angle from the
green marker to the red marker), so we leave it alone.

After running this on a measurement, re-run the downstream stages:
  python -m chaos verify  --stem <stem>
  python -m chaos analyze --stem <stem>
  python -m chaos render  --stem <stem>     (combined.mp4)

Usage:
  python scripts/utils/recompute_theta.py --stem th1_p180_th2_m179
  python scripts/utils/recompute_theta.py --all
"""

import argparse
import csv
import math
import os
import shutil
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from paths import MEAS_DIR, REPO_ROOT  # noqa: E402
from thresholds import PIVOT  # noqa: E402


def recompute_one(meas_dir: str) -> tuple[int, int]:
    """
    Recompute theta1_deg in <meas_dir>/tracking.csv. Returns
    (n_updated, n_total) — frames where theta1 was rewritten and total
    frames in the CSV. Rotates an existing .bak out of the way first.
    """
    csv_path = os.path.join(meas_dir, "tracking.csv")
    if not os.path.exists(csv_path):
        return (0, 0)

    bak_path = csv_path + ".prepivotfix.bak"
    if not os.path.exists(bak_path):
        shutil.copy2(csv_path, bak_path)

    with open(csv_path, "r", newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(csv.DictReader(open(csv_path)).fieldnames or [])

    if not rows or "x_green" not in fieldnames or "theta1_deg" not in fieldnames:
        return (0, len(rows))

    n_updated = 0
    for r in rows:
        gx = r.get("x_green", "")
        gy = r.get("y_green", "")
        if not gx or not gy:
            continue
        try:
            gxf = float(gx)
            gyf = float(gy)
        except ValueError:
            continue
        # 0° = down, +90° = right, -90° = left, ±180° = up
        # (mirrors compute_angle in ring_tracker.py)
        dx = gxf - PIVOT[0]
        dy = gyf - PIVOT[1]
        new_th1 = math.degrees(math.atan2(dx, dy))
        r["theta1_deg"] = f"{new_th1:.6f}"
        n_updated += 1

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    return (n_updated, len(rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--stem", help="config_description, e.g. th1_p180_th2_m179")
    grp.add_argument("--all", action="store_true",
                     help="recompute every measurement folder under measurements/")
    args = ap.parse_args()

    print(f"Using PIVOT = {PIVOT}")

    meas_root = MEAS_DIR
    if args.stem:
        targets = [args.stem]
    else:
        targets = sorted(d for d in os.listdir(meas_root)
                         if os.path.isdir(os.path.join(meas_root, d)))

    for stem in targets:
        meas_dir = os.path.join(meas_root, stem)
        n_upd, n_tot = recompute_one(meas_dir)
        if n_tot == 0:
            print(f"  {stem}: skipped (no tracking.csv)")
        else:
            print(f"  {stem}: updated {n_upd}/{n_tot} rows")


if __name__ == "__main__":
    main()
