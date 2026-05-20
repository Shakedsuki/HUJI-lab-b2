"""
bgr_tracker.py
--------------
Phase 2 marker tracker: BGR colour thresholding + image moments,
wrapping Cohen's detection logic (week4-pendulum-motor-driven/legacy/get_video_coords.py — preserved
verbatim as the regression reference inside
scripts/utils/capture_bgr_baseline.py) inside canonical pipeline I/O.

What it does
~~~~~~~~~~~~
For each frame of the input video:
  cropped = frame[:, CROP_X_START:CROP_X_END, :]
  green   = centroid of moments(inRange(BGR, GREEN_BGR_LO, GREEN_BGR_HI))
  red     = centroid from the first non-empty mask in RED_BGR_RANGES

Centroids are un-cropped (gx_orig = gx_crop + CROP_X_START) before
being written so the canonical PIVOT (663, 332) and ARM_LENGTH_PX (153)
from thresholds.py apply unchanged to downstream verification, geometry
checks, and analysis. Angles are computed with the same compute_angle
convention as ring_tracker (0° = straight down, +90 = right).

What it does NOT do (by design)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  * No HSV. No motion mask. No ring/arc filters. No CSRT seeds.
  * No init/release frame distinction — Phase 2 is continuously driven,
    every frame is tagged 'free_swing'.
  * No debug.mp4 — combined.mp4 from the analysis layer covers post-hoc
    visualization.
  * No HSV adequacy probe — the BGR colour ranges are fixed in
    thresholds.py and not tuned per clip.

I/O
~~~
Reads:  week4-pendulum-motor-driven/videos/<video_file>
        week4-pendulum-motor-driven/data/experiments.json
Writes: week4-pendulum-motor-driven/measurements/<stem>/tracking.csv
            schema: frame, time_s, phase, x_green, y_green, x_red, y_red,
                    theta1_deg, theta2_deg, dropout
                    (matches ring_tracker.py — verify_tracking and the
                     rest of the pipeline consume this unchanged)
        week4-pendulum-motor-driven/data/experiments.json
            entry updated: tracker='bgr', dropout_rate_pct, n_free_frames,
            theta/omega_release, energy_proxy, duration_s, ...

Usage
~~~~~
    # Phase 2 default invocation (track_one passes the positional path):
    python scripts/processing/bgr_tracker.py week4-pendulum-motor-driven/videos/4V_1.9Hz.mov --force

    # Or by stem, when called directly:
    python scripts/processing/bgr_tracker.py --stem 4V_1.9Hz --force

The --no-debug / --skip-probe / --yes-to-warn flags are accepted as
no-ops so this script is a drop-in replacement for ring_tracker.py in
the track_one.py invocation chain.
"""

import argparse
import csv
import json
import math
import os
import sys

import cv2
import numpy as np
from tqdm import tqdm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_UTILS_DIR  = os.path.abspath(os.path.join(_SCRIPT_DIR, os.pardir, "utils"))
sys.path.insert(0, _UTILS_DIR)
from paths import VIDEOS_DIR, MEAS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from thresholds import (  # noqa: E402
    PIVOT,
    ARM_LENGTH_PX,
    ARM_LENGTH_CM,
    CROP_X_START,
    CROP_X_END,
    GREEN_BGR_LO,
    GREEN_BGR_HI,
    RED_BGR_RANGES,
)

SCALE_CM_PER_PX  = ARM_LENGTH_CM / ARM_LENGTH_PX
FPS_DEFAULT      = 59.94

# Pre-build numpy arrays once at module load (cv2.inRange wants ndarray).
_GREEN_LO_NP = np.array(GREEN_BGR_LO, dtype=np.uint8)
_GREEN_HI_NP = np.array(GREEN_BGR_HI, dtype=np.uint8)
_RED_RANGES_NP = [(np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
                  for lo, hi in RED_BGR_RANGES]


# ─────────────────────────────────────────────
# ANGLE CONVENTION (matches ring_tracker.compute_angle)
# ─────────────────────────────────────────────

def compute_angle(p_from, p_to):
    """0° = straight down; +90 = right, -90 = left, ±180 = up."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return float(np.degrees(np.arctan2(dx, dy)))


def angular_diff(a, b):
    """Signed (a − b) wrapped to [-180, 180]."""
    return ((a - b + 180.0) % 360.0) - 180.0


# ─────────────────────────────────────────────
# DETECTION CORE (mirrors get_video_coords.py per-frame body)
# ─────────────────────────────────────────────

def detect_markers_bgr(frame):
    """Return (gx_crop, gy_crop, rx_crop, ry_crop) for one frame.

    Centroids are in CROPPED-frame coords (zero at column CROP_X_START
    in the original frame). Any component is None when its mask had no
    pixels. Mirrors week4-pendulum-motor-driven/legacy/get_video_coords.py lines 42-69 exactly.
    """
    cropped = frame[:, CROP_X_START:CROP_X_END, :]

    M_g = cv2.moments(cv2.inRange(cropped, _GREEN_LO_NP, _GREEN_HI_NP))
    gx = int(M_g['m10'] / M_g['m00']) if M_g['m00'] > 0 else None
    gy = int(M_g['m01'] / M_g['m00']) if M_g['m00'] > 0 else None

    rx = ry = None
    for lo_np, hi_np in _RED_RANGES_NP:
        M_r = cv2.moments(cv2.inRange(cropped, lo_np, hi_np))
        if M_r['m00'] > 0:
            rx = int(M_r['m10'] / M_r['m00'])
            ry = int(M_r['m01'] / M_r['m00'])
            break

    return gx, gy, rx, ry


# ─────────────────────────────────────────────
# REGISTRY I/O
# ─────────────────────────────────────────────

def load_registry():
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(reg):
    os.makedirs(os.path.dirname(EXPERIMENTS), exist_ok=True)
    with open(EXPERIMENTS, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def find_entry(reg, *, stem=None, video_filename=None):
    """Locate the registry (key, entry) for a given stem or video filename.
    Returns (None, None) on miss."""
    if stem:
        for k, e in reg.items():
            if e.get("config_description") == stem:
                return k, e
        if stem in reg:
            return stem, reg[stem]
    if video_filename:
        for k, e in reg.items():
            if e.get("video_file") == video_filename:
                return k, e
    return None, None


def resolve_inputs(args):
    """Return (video_path, stem, key, entry).

    Priority:
      * --stem given      → look up registry by config_description, get video
      * positional video  → derive filename, look up registry by video_file
                             (or fall back to filename stem)
    """
    reg = load_registry()

    if args.stem:
        key, entry = find_entry(reg, stem=args.stem)
        if entry is None:
            print(f"ERROR: no registry entry with config_description '{args.stem}'")
            sys.exit(2)
        video_file = entry.get("video_file") or f"{args.stem}.mov"
        video_path = os.path.join(VIDEOS_DIR, video_file)
        return video_path, args.stem, key, entry, reg

    if args.video:
        video_path = args.video
        if not os.path.isabs(video_path):
            video_path = os.path.join(REPO_ROOT, video_path)
        if not os.path.exists(video_path):
            print(f"ERROR: video not found: {video_path}")
            sys.exit(2)
        video_filename = os.path.basename(video_path)
        key, entry = find_entry(reg, video_filename=video_filename)
        if entry is None:
            stem = os.path.splitext(video_filename)[0]
            print(f"WARN: video '{video_filename}' has no registry entry; "
                  f"will create one keyed '{stem}'.")
            key = stem
            entry = {}
        stem = entry.get("config_description") or os.path.splitext(video_filename)[0]
        return video_path, stem, key, entry, reg

    print("ERROR: provide --stem or a positional video path.")
    sys.exit(2)


def update_registry_entry(reg, key, entry, *, video_file, stem,
                          n_total, n_drop, dropout_pct, duration_s,
                          th1_rel, th2_rel, om1_rel, om2_rel):
    th1r = math.radians(th1_rel); th2r = math.radians(th2_rel)
    om1r = math.radians(om1_rel); om2r = math.radians(om2_rel)
    energy_proxy = round(float(om1r**2 + om2r**2
                               - 2 * math.cos(th1r) - math.cos(th2r)), 4)

    base = dict(entry) if entry else {}
    base.update({
        "video_file":         video_file,
        "init_frame":         0,
        "release_frame":      0,
        "green_roi":          None,
        "red_roi":            None,
        "tracker":            "bgr",
        "arm_length_px":      ARM_LENGTH_PX,
        "arm_length_cm":      ARM_LENGTH_CM,
        "pivot_px":           list(PIVOT),
        "scale_cm_per_px":    round(SCALE_CM_PER_PX, 4),
        "theta1_release":     round(th1_rel, 4),
        "theta2_release":     round(th2_rel, 4),
        "omega1_release":     round(om1_rel, 4),
        "omega2_release":     round(om2_rel, 4),
        "energy_proxy":       energy_proxy,
        "t0_offset_s":        0.0,
        "duration_s":         round(duration_s, 3),
        "n_free_frames":      n_total,
        "dropout_rate_pct":   round(dropout_pct, 2),
        "csv_file":           "tracking.csv",
        "measurements_dir":   f"measurements/{stem}",
        "config_description": stem,
        "tracking_quality":   base.get("tracking_quality", "good"),
        "notes":              base.get("notes", ""),
    })
    reg[key] = base


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    ap = argparse.ArgumentParser(
        description="Phase 2 BGR marker tracker (wraps Cohen's "
                    "get_video_coords detection in pipeline I/O).")
    ap.add_argument("video", nargs="?",
                    help="Path to video file (absolute or repo-relative). "
                         "If omitted, use --stem.")
    ap.add_argument("--stem",
                    help="config_description (registry key) for the clip.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing tracking.csv.")
    # Compatibility no-ops — accepted so this script is drop-in for the
    # ring_tracker invocation in track_one.py.
    ap.add_argument("--no-debug", action="store_true",
                    help="(no-op) bgr_tracker produces no debug video.")
    ap.add_argument("--skip-probe", action="store_true",
                    help="(no-op) bgr_tracker has no HSV adequacy probe.")
    ap.add_argument("--yes-to-warn", action="store_true",
                    help="(no-op) bgr_tracker has no HSV adequacy WARN.")
    return ap.parse_args()


def main():
    args = parse_args()
    video_path, stem, key, entry, reg = resolve_inputs(args)

    out_dir = os.path.join(MEAS_DIR, stem)
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "tracking.csv")

    if os.path.exists(out_csv) and not args.force:
        print(f"ERROR: {out_csv} exists. Pass --force to overwrite.")
        return 1

    print()
    print("=" * 70)
    print(f"bgr_tracker  stem={stem}")
    print(f"  video : {os.path.relpath(video_path, REPO_ROOT)}")
    print(f"  out   : {os.path.relpath(out_csv, REPO_ROOT)}")
    print(f"  pivot : {PIVOT}  (orig coords)  → cropped: "
          f"({PIVOT[0] - CROP_X_START}, {PIVOT[1]})")
    print(f"  arm_L : {ARM_LENGTH_PX}px / {ARM_LENGTH_CM}cm")
    print("=" * 70)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cannot open {video_path}")
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_DEFAULT
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dt = 1.0 / fps
    print(f"  fps={fps:.3f}  frames={total_frames}  dt={dt:.5f}s")
    print()

    rows = []
    n_drop = 0

    with tqdm(total=total_frames, desc="bgr_tracker") as pbar:
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            pbar.update(1)

            time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            gx_c, gy_c, rx_c, ry_c = detect_markers_bgr(frame)

            green_ok = gx_c is not None and gy_c is not None
            red_ok   = rx_c is not None and ry_c is not None

            # Record each marker independently — matches Cohen's
            # standalone behaviour, which preserves a red detection
            # even when green is missing (and vice versa). Theta1
            # requires green; theta2 requires both. dropout=1 fires
            # whenever either marker is missing, per the ring_tracker
            # CSV convention that downstream code expects.
            if green_ok:
                gx = gx_c + CROP_X_START
                gy = gy_c
                theta1 = compute_angle(PIVOT, (gx, gy))
            else:
                gx = gy = None
                theta1 = None

            if red_ok:
                rx = rx_c + CROP_X_START
                ry = ry_c
            else:
                rx = ry = None

            if green_ok and red_ok:
                theta2 = compute_angle((gx, gy), (rx, ry))
            else:
                theta2 = None

            dropout = 0 if (green_ok and red_ok) else 1
            if dropout:
                n_drop += 1

            rows.append({
                "frame":      frame_idx,
                "time_s":     round(time_sec, 5),
                "phase":      "free_swing",
                "x_green":    "" if gx is None else gx,
                "y_green":    "" if gy is None else gy,
                "x_red":      "" if rx is None else rx,
                "y_red":      "" if ry is None else ry,
                "theta1_deg": "" if theta1 is None else f"{theta1:.3f}",
                "theta2_deg": "" if theta2 is None else f"{theta2:.3f}",
                "dropout":    dropout,
            })
            frame_idx += 1

    cap.release()

    n_total = len(rows)
    if n_total == 0:
        print("ERROR: no frames read from video.")
        return 2

    # Write tracking.csv (canonical schema).
    fieldnames = ["frame", "time_s", "phase",
                  "x_green", "y_green", "x_red", "y_red",
                  "theta1_deg", "theta2_deg", "dropout"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    dropout_pct = 100.0 * n_drop / n_total
    duration_s  = n_total / fps

    # ── Initial-frame physics for registry. ─────────────────────────────
    # Phase 2 has no holding/release distinction; "release" = first
    # usable (non-dropout) frame. ω at "release" is the angular velocity
    # from that frame to the next clean one.
    r0 = next((r for r in rows if r["dropout"] == 0), None)
    if r0 is None:
        print("ERROR: every frame is a dropout — refusing to update registry.")
        return 3
    th1_rel = float(r0["theta1_deg"])
    th2_rel = float(r0["theta2_deg"])

    om1_rel = om2_rel = 0.0
    i0 = r0["frame"]
    for r in rows[i0 + 1:]:
        if r["dropout"] == 0:
            dt_pair = (r["time_s"] - r0["time_s"]) or dt
            om1_rel = angular_diff(float(r["theta1_deg"]), th1_rel) / dt_pair
            om2_rel = angular_diff(float(r["theta2_deg"]), th2_rel) / dt_pair
            break

    update_registry_entry(
        reg, key, entry,
        video_file=os.path.basename(video_path),
        stem=stem,
        n_total=n_total, n_drop=n_drop, dropout_pct=dropout_pct,
        duration_s=duration_s,
        th1_rel=th1_rel, th2_rel=th2_rel,
        om1_rel=om1_rel, om2_rel=om2_rel,
    )
    save_registry(reg)

    print()
    print(f"Wrote {n_total} rows  dropout={n_drop} ({dropout_pct:.2f}%)")
    print(f"Registry updated: {os.path.relpath(EXPERIMENTS, REPO_ROOT)}  (tracker=bgr)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
