"""
video_status.py
---------------
Print which videos in Videos/ have been tracked vs. which are still pending.

A video is "tracked" if it has an entry in data/experiments.json with
release_frame and theta1_release populated and a tracking.csv at the
entry's measurements_dir path. "Pending" means the file exists in
Videos/ but isn't recorded as tracked.

Run on its own to see the breakdown:

    python scripts/utils/video_status.py

Or import the helpers from ring_tracker.py — they share the same logic
(duplicated rather than imported, to keep ring_tracker self-contained
and avoid Python package plumbing).
"""

import json
import os
import sys
from pathlib import Path


# ─────────────────────────────────────────────
# CONSTANTS  (mirrors ring_tracker.py)
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")
MEASUREMENTS_DIR = os.path.join(ROOT, "measurements")

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v"}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def list_videos(videos_dir=VIDEOS_DIR):
    """Sorted list of video file paths in `videos_dir` (top level only)."""
    if not os.path.isdir(videos_dir):
        return []
    out = []
    for name in sorted(os.listdir(videos_dir), key=str.lower):
        full = os.path.join(videos_dir, name)
        if os.path.isfile(full) and Path(name).suffix.lower() in VIDEO_EXTS:
            out.append(full)
    return out


def load_registry(path=EXPERIMENTS_FILE):
    """Load experiments.json. Returns {} if absent or malformed."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def is_tracked(stem, registry, root=ROOT):
    """
    A video is "tracked" if its registry entry has:
      - release_frame populated
      - theta1_release populated (i.e. ICs were extracted from a real run)
      - a measurements_dir whose tracking.csv exists on disk
    """
    entry = _resolve_entry(stem, registry)
    if not entry:
        return False
    if entry.get("release_frame") is None:
        return False
    if entry.get("theta1_release") is None:
        return False
    meas_dir = entry.get("measurements_dir")
    if not meas_dir:
        return False
    csv_basename = entry.get("csv_file") or "tracking.csv"
    return os.path.exists(os.path.join(root, meas_dir, csv_basename))


def _resolve_entry(stem, registry):
    """
    Return the registry entry for `stem`, looking it up by either the
    legacy registry key (e.g. DSC_0136) or the video filename stem
    (which after migration is the config_description for most entries).
    Returns None if no match.
    """
    # Direct key hit (legacy DSC-style keys).
    if stem in registry:
        return registry[stem]
    # Otherwise scan: a video named th1_p044_th2_m001.mov can be
    # registered under key DSC_0136 with video_file=th1_p044_th2_m001.mov.
    for entry in registry.values():
        video_file = entry.get("video_file") or ""
        if Path(video_file).stem == stem:
            return entry
        if entry.get("config_description") == stem:
            return entry
    return None


def status_breakdown(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    """Return (tracked_paths, pending_paths) — both sorted lists."""
    registry = load_registry(registry_path)
    videos   = list_videos(videos_dir)
    tracked, pending = [], []
    for v in videos:
        stem = Path(v).stem
        (tracked if is_tracked(stem, registry) else pending).append(v)
    return tracked, pending


def status_summary(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    """One-liner suitable for printing before opening a picker."""
    t, p = status_breakdown(videos_dir, registry_path)
    return f"Tracked: {len(t)}   Pending: {len(p)}   (total: {len(t) + len(p)})"


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def print_status(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    tracked, pending = status_breakdown(videos_dir, registry_path)
    total = len(tracked) + len(pending)
    print(f"Videos directory: {videos_dir}")
    print(f"Total: {total}   Tracked: {len(tracked)}   Pending: {len(pending)}")
    print()

    print(f"  TRACKED  ({len(tracked)})")
    if tracked:
        registry = load_registry(registry_path)
        for v in tracked:
            stem  = Path(v).stem
            entry = _resolve_entry(stem, registry) or {}
            th1   = entry.get("theta1_release", 0)
            th2   = entry.get("theta2_release", 0)
            drop  = entry.get("dropout_rate_pct", "?")
            drop_str = f"{drop}%" if isinstance(drop, (int, float)) else str(drop)
            meas_dir = entry.get("measurements_dir", "?")
            print(f"    [+] {os.path.basename(v):<42}  "
                  f"th1={th1:>7.2f}  th2={th2:>7.2f}  drop={drop_str}  "
                  f"({meas_dir})")
    else:
        print("    (none)")

    print()
    print(f"  PENDING  ({len(pending)})")
    if pending:
        for v in pending:
            print(f"    [ ] {os.path.basename(v)}")
    else:
        print("    (none — all videos tracked)")


if __name__ == "__main__":
    print_status()
