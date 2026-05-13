"""
fix_green_swaps.py
-------------------
Repair *green-marker* wrong-object latches in tracking.csv.

Why this exists
~~~~~~~~~~~~~~~
`interpolate_suspects.py` only fixes suspects whose θ₂ is wrong while
the green marker's pixel position is still correct (it interpolates θ₂
and back-projects to red). When the *green* marker latches onto a wall
artefact mid-swing, the pixel position itself is wrong, the back-
projected θ₁ is wrong, and θ₂ is computed from broken positions. That
class of error stays invisible to the red-only interpolator.

Detection (geometric, not omega-based)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Green is constrained to the ring of radius ARM_LENGTH_PX around PIVOT.
Any row where (x_green, y_green) is outside that ring (±25 px tol) is
a swap row. Note: |ω₂| spikes occur at the *recovery* edge of swap
clusters, not on the swap rows themselves, so omega-based detection
mis-identifies which row to fix. The geometric criterion is the right
primitive.

Repair policy (cluster-size aware)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Short cluster (<= --interp-max frames, default 3):
    Linearly interpolate θ₁ and θ₂ in angle-space (short-way around
    the wrap), then back-project (x_green, y_green) onto the ring and
    (x_red, y_red) onto the lower-arm ring around green. This is
    geometrically correct and kinematically smooth.

Long cluster (> --interp-max frames):
    Mark every row as dropout=1, NaN out positions and angles. We
    don't have enough information to fabricate the marker position
    over a long gap, and a chaotic trajectory diverges meaningfully
    over 0.3+ second windows.

Both policies are followed by a `verify_tracking --no-plot` re-run to
refresh the verification.csv suspect flags.

Usage
~~~~~
    # Auto-fix every clip's off-ring rows (every clip with tracking.csv):
    python scripts/processing/fix_green_swaps.py --all

    # Fix one clip:
    python scripts/processing/fix_green_swaps.py --stem th1_m179_th2_p089

    # Show plan without writing:
    python scripts/processing/fix_green_swaps.py --all --dry-run

    # Don't interpolate at all — mark every off-ring row as dropout:
    python scripts/processing/fix_green_swaps.py --all --interp-max 0
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

VERIFY_SCRIPT    = os.path.join(REPO_ROOT, "scripts", "processing",
                                "verify_tracking.py")

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS
from thresholds import PIVOT, ARM_LENGTH_PX  # noqa: E402

RING_TOL_PX = 25  # off-ring threshold in pixels

# ─────────────────────────────────────────────
# GEOMETRY
# ─────────────────────────────────────────────

def to_float(v):
    if v is None or v == "":
        return math.nan
    try:
        return float(v)
    except ValueError:
        return math.nan

def green_radius(x_green, y_green):
    return math.hypot(x_green - PIVOT[0], y_green - PIVOT[1])

def is_off_ring(x_green, y_green):
    if math.isnan(x_green) or math.isnan(y_green):
        return False  # NaN = dropout, not a swap (handled separately)
    return abs(green_radius(x_green, y_green) - ARM_LENGTH_PX) > RING_TOL_PX

def green_xy_from_theta1(theta1_deg):
    """Back-project (x_green, y_green) from θ₁ given PIVOT, ARM_LENGTH_PX.
    Convention: 0=down, +90=right (matches ring_tracker.compute_angle)."""
    rad = math.radians(theta1_deg)
    return (PIVOT[0] + ARM_LENGTH_PX * math.sin(rad),
            PIVOT[1] + ARM_LENGTH_PX * math.cos(rad))

def red_xy_from_theta(x_green, y_green, theta1_deg, theta2_deg):
    """Back-project (x_red, y_red) on the lower-arm ring around green.
    Lower arm absolute angle = θ₁ + θ₂."""
    rad = math.radians(theta1_deg + theta2_deg)
    return (x_green + ARM_LENGTH_PX * math.sin(rad),
            y_green + ARM_LENGTH_PX * math.cos(rad))

def short_way(a0, a1):
    """Return (a0, a1') such that a1' is on the short path from a0 to a1.
    Used so linear interpolation across a ±180 wrap goes through the
    correct half of the circle."""
    delta = ((a1 - a0 + 180.0) % 360.0) - 180.0
    return a0, a0 + delta

def lerp(t, t0, v0, t1, v1):
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

# ─────────────────────────────────────────────
# CLUSTERING
# ─────────────────────────────────────────────

def find_off_ring_clusters(rows, gap=3):
    """Walk rows in order; return list of [start_idx, end_idx]
    inclusive for each contiguous (gap-merged) run of off-ring rows.
    Only considers rows in phase=='free_swing'."""
    indices = []
    for i, r in enumerate(rows):
        if r.get("phase") != "free_swing":
            continue
        xg = to_float(r.get("x_green", ""))
        yg = to_float(r.get("y_green", ""))
        if is_off_ring(xg, yg):
            indices.append(i)
    if not indices:
        return []
    clusters = [[indices[0], indices[0]]]
    for i in indices[1:]:
        if i - clusters[-1][1] <= gap:
            clusters[-1][1] = i
        else:
            clusters.append([i, i])
    return clusters

def find_clean_anchor(rows, idx, direction, max_search=30):
    """Walk rows[idx ± step] until we find a row whose green is
    on-ring AND not a dropout. Returns idx or None.
    direction: -1 = backwards, +1 = forwards."""
    n = len(rows)
    for j in range(idx + direction, idx + direction * (max_search + 1),
                   direction):
        if j < 0 or j >= n:
            return None
        r = rows[j]
        if str(r.get("dropout", "")).strip() == "1":
            continue
        if r.get("phase") != "free_swing":
            continue
        xg = to_float(r.get("x_green", ""))
        yg = to_float(r.get("y_green", ""))
        if math.isnan(xg) or math.isnan(yg):
            continue
        if is_off_ring(xg, yg):
            continue
        return j
    return None

# ─────────────────────────────────────────────
# REPAIR
# ─────────────────────────────────────────────

def interpolate_cluster(rows, cluster_start, cluster_end):
    """Interpolate θ₁ and θ₂ across rows[cluster_start..cluster_end]
    using the nearest clean anchors on each side.
    Returns (n_interpolated, message).
    """
    prev_i = find_clean_anchor(rows, cluster_start, -1)
    next_i = find_clean_anchor(rows, cluster_end, +1)
    if prev_i is None or next_i is None:
        return 0, "no clean anchors"

    p, n = rows[prev_i], rows[next_i]
    th1_p = to_float(p["theta1_deg"]); th1_n = to_float(n["theta1_deg"])
    th2_p = to_float(p["theta2_deg"]); th2_n = to_float(n["theta2_deg"])
    if any(math.isnan(v) for v in (th1_p, th1_n, th2_p, th2_n)):
        return 0, "anchor has NaN angle"
    t_p = to_float(p["time_s"]);   t_n = to_float(n["time_s"])

    a0, a1 = short_way(th1_p, th1_n)
    b0, b1 = short_way(th2_p, th2_n)

    n_done = 0
    for i in range(cluster_start, cluster_end + 1):
        target = rows[i]
        t = to_float(target["time_s"])
        th1 = lerp(t, t_p, a0, t_n, a1)
        th2 = lerp(t, t_p, b0, t_n, b1)
        th1_w = ((th1 + 180.0) % 360.0) - 180.0
        th2_w = ((th2 + 180.0) % 360.0) - 180.0
        xg, yg = green_xy_from_theta1(th1_w)
        xr, yr = red_xy_from_theta(xg, yg, th1_w, th2_w)
        target["x_green"]    = f"{xg:.2f}"
        target["y_green"]    = f"{yg:.2f}"
        target["x_red"]      = f"{xr:.2f}"
        target["y_red"]      = f"{yr:.2f}"
        target["theta1_deg"] = f"{th1_w:.4f}"
        target["theta2_deg"] = f"{th2_w:.4f}"
        target["dropout"]    = "0"
        n_done += 1
    return n_done, f"interp anchors f{rows[prev_i]['frame']}..f{rows[next_i]['frame']}"

def mark_dropout(rows, cluster_start, cluster_end):
    n_done = 0
    for i in range(cluster_start, cluster_end + 1):
        target = rows[i]
        target["x_green"]    = ""
        target["y_green"]    = ""
        target["x_red"]      = ""
        target["y_red"]      = ""
        target["theta1_deg"] = ""
        target["theta2_deg"] = ""
        target["dropout"]    = "1"
        n_done += 1
    return n_done

# ─────────────────────────────────────────────
# CSV I/O
# ─────────────────────────────────────────────

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

# ─────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────

def update_registry(stem, n_interp, n_dropped, n_long_clusters):
    if not os.path.exists(EXPERIMENTS_FILE):
        return
    with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
        reg = json.load(f)
    target_key = next(
        (k for k, e in reg.items() if e.get("config_description") == stem),
        None)
    if target_key is None:
        return
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    e = reg[target_key]
    e["green_swap_fix_date"]      = today
    e["green_swap_interpolated"]  = n_interp
    e["green_swap_dropped"]       = n_dropped
    e["green_swap_long_clusters"] = n_long_clusters
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)

# ─────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────

def fix_clip(stem, dry_run=False, reverify=True, interp_max=3, gap=3):
    meas = os.path.join(MEAS_DIR, stem)
    csv_path = os.path.join(meas, "tracking.csv")
    if not os.path.exists(csv_path):
        print(f"  [SKIP] {stem}: tracking.csv missing")
        return 0, 0, 0

    rows, fields = load_csv(csv_path)
    clusters = find_off_ring_clusters(rows, gap=gap)
    if not clusters:
        print(f"  {stem}: no off-ring rows.")
        return 0, 0, 0

    short = [c for c in clusters if (c[1] - c[0] + 1) <= interp_max]
    long_ = [c for c in clusters if (c[1] - c[0] + 1) > interp_max]
    n_short_frames = sum(c[1] - c[0] + 1 for c in short)
    n_long_frames  = sum(c[1] - c[0] + 1 for c in long_)

    print(f"  {stem}:")
    print(f"    {len(clusters)} off-ring cluster(s)  "
          f"({n_short_frames + n_long_frames} frame(s))")
    print(f"      short (<= {interp_max}f): {len(short):>3} clusters, "
          f"{n_short_frames} frame(s) -> interpolate")
    print(f"      long  (> {interp_max}f): {len(long_):>3} clusters, "
          f"{n_long_frames} frame(s) -> mark dropout")

    n_interp = n_dropped = 0
    skipped = 0
    for cs, ce in short:
        n, msg = interpolate_cluster(rows, cs, ce)
        if n == 0:
            skipped += (ce - cs + 1)
        n_interp += n
    for cs, ce in long_:
        n_dropped += mark_dropout(rows, cs, ce)

    if dry_run:
        print(f"    [DRY-RUN] not writing  "
              f"(would interp {n_interp}, drop {n_dropped})")
        return n_interp, n_dropped, len(long_)

    if n_interp == 0 and n_dropped == 0:
        return 0, 0, 0

    bak = csv_path + ".bak_green_swap_" + datetime.datetime.now().strftime(
        "%Y%m%dT%H%M%S")
    shutil.copy2(csv_path, bak)
    write_csv(csv_path, rows, fields)
    print(f"    wrote {csv_path}  (backup: {os.path.basename(bak)})")
    update_registry(stem, n_interp, n_dropped, len(long_))

    if reverify:
        subprocess.run(
            [sys.executable, VERIFY_SCRIPT, "--stem", stem, "--no-plot"],
            cwd=REPO_ROOT, check=False, capture_output=True)
        print(f"    re-verified")

    return n_interp, n_dropped, len(long_)

def parse_args():
    p = argparse.ArgumentParser(
        description="Repair green-marker wrong-object latches geometrically.")
    p.add_argument("--stem", help="config_description")
    p.add_argument("--all", action="store_true",
                   help="process every clip with a tracking.csv")
    p.add_argument("--filter", help="only stems containing SUBSTR (with --all)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-reverify", action="store_true")
    p.add_argument("--interp-max", type=int, default=3,
                   help="max cluster size in frames eligible for interpolation "
                        "(default 3); larger clusters are marked dropout. "
                        "Set 0 to never interpolate.")
    p.add_argument("--gap", type=int, default=3,
                   help="merge off-ring rows separated by <= GAP frames "
                        "into one cluster (default 3)")
    return p.parse_args()

def all_stems_with_tracking():
    out = []
    for d in sorted(os.listdir(MEAS_DIR)):
        if os.path.exists(os.path.join(MEAS_DIR, d, "tracking.csv")):
            out.append(d)
    return out

def main():
    args = parse_args()

    if args.all:
        stems = all_stems_with_tracking()
        if args.filter:
            stems = [s for s in stems if args.filter in s]
    elif args.stem:
        stems = [args.stem]
    else:
        raise SystemExit("Need --all or --stem.")

    print(f"fix_green_swaps.py")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'IN-PLACE'}  "
          f"interp-max={args.interp_max}  gap={args.gap}")
    print(f"Plan: {len(stems)} clip(s)")
    print()

    tot_interp = tot_dropped = tot_long = 0
    n_modified = 0
    for stem in stems:
        ni, nd, nl = fix_clip(stem, dry_run=args.dry_run,
                              reverify=not args.no_reverify,
                              interp_max=args.interp_max,
                              gap=args.gap)
        tot_interp  += ni
        tot_dropped += nd
        tot_long    += nl
        if ni > 0 or nd > 0:
            n_modified += 1

    print()
    print(f"Total: interpolated {tot_interp} frame(s), "
          f"dropped {tot_dropped} frame(s), "
          f"{tot_long} long cluster(s) marked dropout. "
          f"{n_modified} clip(s) modified.")

if __name__ == "__main__":
    main()
