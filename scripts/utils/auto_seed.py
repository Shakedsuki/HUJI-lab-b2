"""
auto_seed.py
------------
Brief 15 — derive chaos fix seeds programmatically from violation
clusters, eliminating human clicking when the failure mode is small
local drift (rather than far-off latches like skin or jacket).

For each cluster of suspect frames in verification.csv:
  - find the nearest clean frame BEFORE the cluster
  - find the nearest clean frame AFTER the cluster
  - linearly interpolate the green and red marker pixel positions
    at the cluster's first frame
  - save those as a seed in seeds.json (merging with any existing
    human-placed seeds — auto-seeds never overwrite manual ones)

Then re-run ring_tracker with --strict-physics --seeds-file. The
30-frame strict-physics window per seed propagates the corrected
position forward.

Limits:
  - Doesn't help when the tracker is latched far away (50+ px). The
    interpolated position would still land near the wrong object;
    only a human click pulls the marker back.
  - Skips clusters at the very start or end of the run when one of
    the neighbour frames is out of range.
  - No-op when verification.csv has no suspect clusters.

Usage:
    chaos auto-seed <stem>           — generate seeds + re-track + re-verify
    chaos auto-seed <stem> --dry-run — print the seed plan, don't write or run
    chaos auto-seed <stem> --no-track — write seeds.json, skip the re-track
"""

import argparse
import csv
import datetime
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT             = r"C:\dev\chaos"
DATA_DIR         = os.path.join(ROOT, "data")
MEAS_DIR         = os.path.join(ROOT, "measurements")
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
TRACKER_SCRIPT   = os.path.join(ROOT, "scripts", "processing",
                                "ring_tracker.py")
VERIFY_SCRIPT    = os.path.join(ROOT, "scripts", "processing",
                                "verify_tracking.py")


def parse_args():
    p = argparse.ArgumentParser(
        description="Auto-derive chaos fix seeds from violation "
                    "clusters and re-track with strict-physics.")
    p.add_argument("stem", help="config_description, e.g. th1_p138_th2_m002")
    p.add_argument("--gap", type=int, default=10, metavar="FRAMES",
                   help="frames within this gap count as the same "
                        "cluster (default 10)")
    p.add_argument("--max-clean-distance", type=int, default=20,
                   metavar="FRAMES",
                   help="max distance to search for a clean anchor "
                        "frame on each side (default 20)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the seed plan; do not write seeds.json "
                        "or re-track")
    p.add_argument("--no-track", action="store_true",
                   help="write seeds.json but skip the re-track + verify")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="ω cap for the verify step (default 2500)")
    return p.parse_args()


def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_entry_by_stem(reg, stem):
    for k, e in reg.items():
        if e.get("config_description") == stem:
            return k, e
    if stem in reg:
        return stem, reg[stem]
    return None, None


# ─────────────────────────────────────────────
# CSV PARSING
# ─────────────────────────────────────────────

def load_tracking_rows(path):
    """Returns a list of dicts indexed by frame number with the
    columns we need for interpolation."""
    rows = {}
    with open(path, "r", newline="") as f:
        for r in csv.DictReader(f):
            try:
                fr = int(r["frame"])
            except (KeyError, ValueError):
                continue
            try:
                rows[fr] = {
                    "frame":    fr,
                    "dropout":  int(r.get("dropout") or 0),
                    "x_green":  float(r["x_green"]) if r.get("x_green") else None,
                    "y_green":  float(r["y_green"]) if r.get("y_green") else None,
                    "x_red":    float(r["x_red"])   if r.get("x_red")   else None,
                    "y_red":    float(r["y_red"])   if r.get("y_red")   else None,
                }
            except (ValueError, KeyError):
                continue
    return rows


def find_suspect_frames(verification_path, arm_dev_threshold=10.0):
    """Return a sorted list of frame numbers that need a seed:
       - suspect=1 (any check fired)
       - OR arm_dev_pct > threshold (per-frame rigid-body violation;
         not currently merged into the suspect column in verify_tracking,
         but auto_seed should still target these clusters)
       AND dropout=0 (we need a row to override)."""
    out = set()
    with open(verification_path, "r", newline="") as f:
        for r in csv.DictReader(f):
            try:
                fr = int(r["frame"])
                if int(r.get("dropout") or 0):
                    continue
                if int(r.get("suspect") or 0) == 1:
                    out.add(fr); continue
                try:
                    if float(r.get("arm_dev_pct") or 0) > arm_dev_threshold:
                        out.add(fr)
                except (ValueError, TypeError):
                    pass
            except (ValueError, KeyError):
                continue
    return sorted(out)


def clusterize(frames, gap):
    """Group consecutive frames within `gap` of each other into the
    same cluster. Returns a list of [first, last] pairs."""
    if not frames:
        return []
    frames = sorted(frames)
    out = [[frames[0], frames[0]]]
    for f in frames[1:]:
        if f - out[-1][1] <= gap:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


# ─────────────────────────────────────────────
# CLEAN-NEIGHBOUR LOOKUP
# ─────────────────────────────────────────────

def is_clean_row(row):
    """A row is 'clean' for anchor purposes when not a dropout and
    has all four marker pixels."""
    if row is None or row["dropout"]:
        return False
    return all(row.get(k) is not None for k in
               ("x_green", "y_green", "x_red", "y_red"))


def find_clean_anchor_before(rows, start_frame, max_back, suspect_set):
    """Walk backward from start_frame-1, return the first frame whose
    row is clean AND not itself a suspect. Returns None on miss."""
    for f in range(start_frame - 1, max(-1, start_frame - 1 - max_back), -1):
        if f in suspect_set:
            continue
        if is_clean_row(rows.get(f)):
            return f
    return None


def find_clean_anchor_after(rows, end_frame, max_forward, suspect_set,
                            max_frame):
    """Walk forward from end_frame+1, return the first frame whose
    row is clean AND not itself a suspect. Returns None on miss."""
    for f in range(end_frame + 1,
                   min(max_frame + 1, end_frame + 1 + max_forward)):
        if f in suspect_set:
            continue
        if is_clean_row(rows.get(f)):
            return f
    return None


# ─────────────────────────────────────────────
# SEED CONSTRUCTION
# ─────────────────────────────────────────────

def interp_xy(rows, before_f, after_f, target_f):
    """Linear-interpolate (x,y) for green and red between two anchor
    frames."""
    a = rows[before_f]
    b = rows[after_f]
    span = b["frame"] - a["frame"]
    t = (target_f - a["frame"]) / span if span else 0.0
    def lerp(x0, x1):
        return x0 + (x1 - x0) * t
    return (
        (int(round(lerp(a["x_green"], b["x_green"]))),
         int(round(lerp(a["y_green"], b["y_green"])))),
        (int(round(lerp(a["x_red"],   b["x_red"]))),
         int(round(lerp(a["y_red"],   b["y_red"])))),
    )


def build_auto_seeds(rows, suspect_frames, gap, max_dist):
    """For each cluster of suspect frames, derive one seed at the
    cluster's first frame using interpolation between clean
    anchors. Returns (auto_seeds, plan) where plan is a list of
    diagnostics rows for the dry-run print."""
    suspect_set = set(suspect_frames)
    clusters = clusterize(suspect_frames, gap=gap)
    if not clusters:
        return [], []
    max_frame = max(rows.keys()) if rows else 0

    auto = []
    plan = []
    for cluster_first, cluster_last in clusters:
        before = find_clean_anchor_before(
            rows, cluster_first, max_dist, suspect_set)
        after = find_clean_anchor_after(
            rows, cluster_last, max_dist, suspect_set, max_frame)
        if before is None or after is None:
            plan.append({
                "cluster":  (cluster_first, cluster_last),
                "before":   before,
                "after":    after,
                "skip":     True,
                "reason":   "no clean anchor within window",
            })
            continue
        green_xy, red_xy = interp_xy(rows, before, after, cluster_first)
        auto.append({
            "frame":    cluster_first,
            "green_xy": list(green_xy),
            "red_xy":   list(red_xy),
        })
        plan.append({
            "cluster":  (cluster_first, cluster_last),
            "before":   before,
            "after":    after,
            "skip":     False,
            "frame":    cluster_first,
            "green_xy": green_xy,
            "red_xy":   red_xy,
            "size":     cluster_last - cluster_first + 1,
        })
    return auto, plan


# ─────────────────────────────────────────────
# SEEDS.JSON I/O
# ─────────────────────────────────────────────

def load_existing_seeds(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("seeds", []))
    except (OSError, json.JSONDecodeError):
        return []


def merge_seeds(existing, auto):
    """Merge auto-seeds into existing seeds. Existing seeds win on
    frame collision — the human's click is always more reliable
    than interpolation."""
    by_frame = {s["frame"]: s for s in existing}
    n_added = 0
    for s in auto:
        if s["frame"] not in by_frame:
            by_frame[s["frame"]] = {
                **s,
                "source": "auto-seed",
            }
            n_added += 1
    return sorted(by_frame.values(), key=lambda s: s["frame"]), n_added


def save_seeds(path, seeds):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "seeds": [
            {
                "frame":    s["frame"],
                "green_xy": list(s["green_xy"]) if s.get("green_xy") else None,
                "red_xy":   list(s["red_xy"])   if s.get("red_xy")   else None,
                **({"source": s["source"]} if s.get("source") else {}),
            }
            for s in seeds
        ],
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "notes":    ("Created by auto_seed.py (some seeds may be "
                     "interpolated from violation clusters; manual "
                     "seeds preserved verbatim)"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ─────────────────────────────────────────────
# RE-TRACK + RE-VERIFY
# ─────────────────────────────────────────────

def run_retrack_and_verify(stem, seeds_path, earliest_seed, omega_cap):
    """Mirrors manual_correction.run_track_and_verify but headless —
    no interactive picker, just pipe the seeds we already wrote."""
    reg = load_registry()
    _, entry = find_entry_by_stem(reg, stem)
    if not entry:
        print(f"ERROR: no registry entry for stem {stem}")
        return 2
    video_filename = entry.get("video_file")
    if not video_filename:
        print(f"ERROR: no video_file in registry for {stem}")
        return 2
    video_path = os.path.join(VIDEOS_DIR, video_filename)
    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return 2

    have_existing = os.path.exists(
        os.path.join(MEAS_DIR, stem, "tracking.csv"))
    use_from_frame = (earliest_seed > 0 and have_existing)

    print()
    print("─" * 70)
    if use_from_frame:
        print(f"Re-tracking {stem} from frame {earliest_seed} with "
              f"strict-physics (rows 0..{earliest_seed - 1} preserved)...")
    else:
        print(f"Tracking {stem} from scratch with strict-physics + seeds...")
    print("─" * 70)

    cmd = [sys.executable, TRACKER_SCRIPT, video_path,
           "--no-debug", "--force",
           "--seeds-file", seeds_path,
           "--strict-physics",
           "--skip-probe"]
    if use_from_frame:
        cmd += ["--from-frame", str(earliest_seed)]

    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        print(f"ring_tracker exit {rc} — aborting before verify.")
        return rc

    print()
    print("─" * 70)
    print("Re-running verify_tracking ...")
    print("─" * 70)
    rc = subprocess.run(
        [sys.executable, VERIFY_SCRIPT,
         "--stem", stem,
         "--omega-cap", str(omega_cap),
         "--no-plot"],
        cwd=ROOT).returncode
    return rc


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    meas_dir = os.path.join(MEAS_DIR, args.stem)
    track_path = os.path.join(meas_dir, "tracking.csv")
    verif_path = os.path.join(meas_dir, "verification.csv")
    seeds_path = os.path.join(meas_dir, "seeds.json")

    if not os.path.exists(track_path):
        print(f"ERROR: {track_path} not found")
        return 1
    if not os.path.exists(verif_path):
        print(f"ERROR: {verif_path} not found — run chaos verify first")
        return 1

    rows = load_tracking_rows(track_path)
    suspect_frames = find_suspect_frames(verif_path)

    if not suspect_frames:
        print(f"  {args.stem}: no suspect frames — nothing to seed.")
        return 0

    auto_seeds, plan = build_auto_seeds(
        rows, suspect_frames, gap=args.gap,
        max_dist=args.max_clean_distance)

    print()
    print(f"  {args.stem}")
    print(f"  {len(suspect_frames)} suspect frames in "
          f"{len(plan)} cluster(s)")
    print()
    print(f"  {'cluster':>20s}  {'size':>5s}  {'anchor before':>14s}  "
          f"{'anchor after':>13s}  seed (frame, green, red)")
    print("  " + "-" * 100)
    for p in plan:
        cs, ce = p["cluster"]
        bf = p["before"] if p["before"] is not None else "—"
        af = p["after"]  if p["after"]  is not None else "—"
        if p["skip"]:
            print(f"  [{cs:>5d}, {ce:>5d}]   {ce-cs+1:>5d}  "
                  f"{str(bf):>14s}  {str(af):>13s}  "
                  f"SKIPPED ({p['reason']})")
        else:
            print(f"  [{cs:>5d}, {ce:>5d}]   {p['size']:>5d}  "
                  f"{bf:>14d}  {af:>13d}  "
                  f"@ {p['frame']}  green={p['green_xy']}  red={p['red_xy']}")
    n_skipped = sum(1 for p in plan if p["skip"])
    print()
    print(f"  → {len(auto_seeds)} auto-seed(s) generated, "
          f"{n_skipped} cluster(s) skipped")

    if args.dry_run:
        print(f"  (dry-run: nothing written, no re-track.)")
        return 0

    if not auto_seeds:
        print(f"  Nothing to do.")
        return 0

    existing = load_existing_seeds(seeds_path)
    merged, n_added = merge_seeds(existing, auto_seeds)

    if n_added == 0:
        print(f"  All {len(auto_seeds)} auto-seed frames already exist "
              f"in seeds.json (manual seeds win); nothing new to write.")
        return 0

    save_seeds(seeds_path, merged)
    print(f"  Wrote {seeds_path}: "
          f"{n_added} auto-seed(s) added, "
          f"{len(existing)} existing seed(s) preserved.")

    if args.no_track:
        print(f"  (--no-track: skipping re-track + verify.)")
        return 0

    earliest_seed = min(s["frame"] for s in merged)
    rc = run_retrack_and_verify(args.stem, seeds_path,
                                earliest_seed, args.omega_cap)
    if rc != 0:
        print(f"  Re-track or verify exited rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
