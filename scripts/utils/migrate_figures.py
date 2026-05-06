"""
migrate_figures.py
-------------------
One-shot migration: move existing per-clip figure files from
measurements/<stem>/ into the new figures/<type>/<stem>_<type>.<ext>
layout. Run once after the figure-paths refactor; idempotent — running
again on already-migrated state is a no-op.

Also moves data/figures/* → figures/aggregate/*.

Usage:
    python scripts/utils/migrate_figures.py            # do the move
    python scripts/utils/migrate_figures.py --dry-run  # show plan only
"""

import argparse
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT       = os.path.dirname(os.path.dirname(os.path.dirname(
                 os.path.abspath(__file__))))
MEAS_DIR   = os.path.join(ROOT, "measurements")
FIGS_DIR   = os.path.join(ROOT, "figures")
DATA_FIG   = os.path.join(ROOT, "data", "figures")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import figure_path, aggregate_path  # noqa: E402


# (filename in measurements/<stem>/, figure_type, ext)
PER_CLIP_FILES = [
    ("phase_panels.png",          "phase_panels",         "png"),
    ("phase_3d_trajectory.png",   "phase_3d_trajectory",  "png"),
    ("phase_3d_rotation.mp4",     "phase_3d_rotation",    "mp4"),
    ("phase_animation.mp4",       "phase_animation",      "mp4"),
    ("poincare.png",              "poincare",             "png"),
    ("lyapunov.png",              "lyapunov",             "png"),
    ("verification.png",          "verification",         "png"),
    ("chaos_analyze.png",         "chaos_analyze",        "png"),
    ("friction_fit.png",          "friction_fit",         "png"),
    ("combined.mp4",              "combined",             "mp4"),
    ("debug.mp4",                 "debug",                "mp4"),
]


def migrate_per_clip(dry_run=False):
    """For every measurements/<stem>/<file>, move to the new figures
    layout. Returns (moved, skipped) counts."""
    moved = skipped = 0
    if not os.path.isdir(MEAS_DIR):
        print(f"  measurements/ not found: {MEAS_DIR}")
        return 0, 0
    for stem in sorted(os.listdir(MEAS_DIR)):
        meas = os.path.join(MEAS_DIR, stem)
        if not os.path.isdir(meas):
            continue
        for src_name, fig_type, ext in PER_CLIP_FILES:
            src = os.path.join(meas, src_name)
            if not os.path.exists(src):
                continue
            dst = figure_path(fig_type, stem, ext=ext)
            if os.path.exists(dst):
                # Already migrated — leave the new file in place, drop
                # the old one to avoid drift.
                if not dry_run:
                    os.remove(src)
                print(f"  [DUP rm src] {src} (dst exists)")
                skipped += 1
                continue
            if dry_run:
                print(f"  [DRY] {src}\n    -> {dst}")
            else:
                shutil.move(src, dst)
                print(f"  [MV] {src}\n    -> {dst}")
            moved += 1
    return moved, skipped


def migrate_aggregate(dry_run=False):
    """Move data/figures/* into figures/aggregate/."""
    if not os.path.isdir(DATA_FIG):
        return 0
    moved = 0
    for name in sorted(os.listdir(DATA_FIG)):
        src = os.path.join(DATA_FIG, name)
        if not os.path.isfile(src):
            continue
        dst = aggregate_path(name)
        if os.path.exists(dst):
            if not dry_run:
                os.remove(src)
            print(f"  [DUP rm src] {src} (dst exists)")
            continue
        if dry_run:
            print(f"  [DRY] {src}\n    -> {dst}")
        else:
            shutil.move(src, dst)
            print(f"  [MV] {src}\n    -> {dst}")
        moved += 1
    # Remove now-empty data/figures dir.
    if not dry_run and os.path.isdir(DATA_FIG):
        try:
            os.rmdir(DATA_FIG)
            print(f"  [RMDIR] {DATA_FIG}")
        except OSError:
            pass
    return moved


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    print(f"migrate_figures.py  ({'DRY-RUN' if args.dry_run else 'IN-PLACE'})")
    print()

    print("=== Per-clip figures ===")
    moved, skipped = migrate_per_clip(dry_run=args.dry_run)

    print()
    print("=== Aggregate figures ===")
    agg_moved = migrate_aggregate(dry_run=args.dry_run)

    print()
    print(f"Done.  per-clip: moved {moved}, skipped {skipped}.  "
          f"aggregate: moved {agg_moved}.")


if __name__ == "__main__":
    main()
