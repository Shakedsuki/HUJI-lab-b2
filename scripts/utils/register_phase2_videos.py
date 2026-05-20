"""
register_phase2_videos.py
-------------------------
Scan week4-pendulum-motor-driven/videos/ for .mov files and add a pre-tracking
entry to experiments.json for any clip that isn't already registered.

Idempotent — existing entries are never modified. Designed to be re-run
whenever a fresh batch of clips is dropped into the videos directory.

The registry entries it creates carry the minimum metadata that the
rest of the pipeline expects to find BEFORE tracking:

    video_file          - <stem>.mov
    config_description  - <stem>
    drive_voltage_v     - parsed from stem via driven_helpers.parse_stem
    drive_freq_hz       - parsed from stem
    repeat_number       - parsed from stem (default 1)
    arm_length_cm       - thresholds.ARM_LENGTH_CM
    arm_length_px       - thresholds.ARM_LENGTH_PX
    pivot_px            - list(thresholds.PIVOT)
    scale_cm_per_px     - arm_length_cm / arm_length_px
    measurements_dir    - measurements/<stem>
    csv_file            - tracking.csv
    tracking_quality    - "untracked"
    notes               - ""
    tag_frame           - 0   (Phase 2: pendulum is driven from frame 0)

Post-tracking fields (theta1_release, omega1_release, dropout_rate_pct,
energy_proxy, ...) are NOT populated here — bgr_tracker writes those
when the clip is actually tracked.

Usage
~~~~~
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/register_phase2_videos.py            # scan + add
    CHAOS_PHASE=week4-pendulum-motor-driven \\
        python scripts/utils/register_phase2_videos.py --dry-run  # just report
"""

import argparse
import datetime
import json
import os
import shutil
import sys

os.environ.setdefault("CHAOS_PHASE", "week4-pendulum-motor-driven")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from thresholds import PIVOT, ARM_LENGTH_PX, ARM_LENGTH_CM  # noqa: E402
from driven_helpers import parse_stem  # noqa: E402

SCALE_CM_PER_PX = round(ARM_LENGTH_CM / ARM_LENGTH_PX, 4)


def load_registry():
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(reg):
    os.makedirs(os.path.dirname(EXPERIMENTS), exist_ok=True)
    with open(EXPERIMENTS, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def stems_in_videos_dir():
    """Return sorted list of <stem> for every .mov in VIDEOS_DIR."""
    if not os.path.isdir(VIDEOS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(VIDEOS_DIR)):
        if not name.lower().endswith(".mov"):
            continue
        out.append(os.path.splitext(name)[0])
    return out


def existing_stems(reg):
    """Set of stems already registered (by config_description OR key)."""
    out = set()
    for k, e in reg.items():
        cd = e.get("config_description")
        if cd:
            out.add(cd)
        out.add(k)
    return out


def make_entry(stem):
    """Build a pre-tracking entry for `stem`. Returns None if the stem
    doesn't parse as a Phase 2 clip name."""
    try:
        parsed = parse_stem(stem)
    except ValueError:
        return None

    return {
        "video_file":         f"{stem}.mov",
        "config_description": stem,
        "drive_voltage_v":    parsed["v_drill_v"],
        "drive_freq_hz":      parsed["f_drive_hz"],
        "repeat_number":      parsed["repeat"] or 1,
        "arm_length_cm":      ARM_LENGTH_CM,
        "arm_length_px":      ARM_LENGTH_PX,
        "pivot_px":           list(PIVOT),
        "scale_cm_per_px":    SCALE_CM_PER_PX,
        "measurements_dir":   f"measurements/{stem}",
        "csv_file":           "tracking.csv",
        "tracking_quality":   "untracked",
        "notes":              "",
        "tag_frame":          0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be added; don't write registry.")
    args = ap.parse_args()

    reg = load_registry()
    existing = existing_stems(reg)
    found = stems_in_videos_dir()

    to_add = []
    unparseable = []
    already = []
    for stem in found:
        if stem in existing:
            already.append(stem)
            continue
        entry = make_entry(stem)
        if entry is None:
            unparseable.append(stem)
            continue
        to_add.append((stem, entry))

    print()
    print("=" * 70)
    print(f"register_phase2_videos  ({'DRY-RUN' if args.dry_run else 'WRITE'})")
    print("=" * 70)
    print(f"  videos dir : {os.path.relpath(VIDEOS_DIR, REPO_ROOT)}")
    print(f"  registry   : {os.path.relpath(EXPERIMENTS, REPO_ROOT)}")
    print()
    print(f"  found in videos dir : {len(found)}")
    print(f"  already registered  : {len(already)}")
    print(f"  unparseable names   : {len(unparseable)}")
    print(f"  to add              : {len(to_add)}")
    print()

    if unparseable:
        print("UNPARSEABLE (skipped):")
        for s in unparseable:
            print(f"  - {s}")
        print()

    if not to_add:
        print("Nothing to add.")
        return 0

    print("WILL ADD:")
    for stem, entry in to_add:
        print(f"  + {stem:<22}  V={entry['drive_voltage_v']:<5}  "
              f"f={entry['drive_freq_hz']} Hz  rep={entry['repeat_number']}")

    if args.dry_run:
        print()
        print("DRY-RUN — registry unchanged.")
        return 0

    # Back up registry before mutating.
    suffix = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = EXPERIMENTS + f".register_{suffix}.bak"
    shutil.copy2(EXPERIMENTS, bak)
    print()
    print(f"Registry backed up: {os.path.relpath(bak, REPO_ROOT)}")

    for stem, entry in to_add:
        reg[stem] = entry
    save_registry(reg)

    print(f"Added {len(to_add)} entries. Registry now has {len(reg)} clips.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
