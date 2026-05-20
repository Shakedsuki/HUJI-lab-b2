"""
capture_bgr_baseline.py
-----------------------
Capture a per-frame BGR-centroid baseline for one Week 4 clip using the
detection logic from week4-pendulum-motor-driven/legacy/get_video_coords.py,
verbatim.

Why this exists
~~~~~~~~~~~~~~~
The integration of get_video_coords.py into the pipeline (as
scripts/processing/bgr_tracker.py) is a refactor: the BGR detection
math doesn't change, only its plumbing does. To prove the refactor is
correct, we freeze what the standalone script produces today and diff
the wrapped tracker's output against it.

The per-frame body of the main loop (mask construction, fallback chain,
moment-centroid extraction) is COPY-PASTED from
week4-pendulum-motor-driven/legacy/get_video_coords.py lines 16-93. The
ONLY behavioural changes vs. the standalone:
  * video path comes from --stem instead of being hardcoded
  * a frame index counter is maintained (it's not used inside the
    detection block — only for the CSV output)
  * the `data` list is written to a CSV at the end

Output: week4-pendulum-motor-driven/baselines/<stem>/centroids.csv
        columns: frame, time_s, gx_crop, gy_crop, rx_crop, ry_crop
        - Pixel coords are in the CROPPED frame (350:950 column range),
          matching what the standalone script computes.
        - Empty cell = no detection (None in the standalone).

Usage
~~~~~
    python scripts/utils/capture_bgr_baseline.py --stem 4V_1.9Hz
"""

import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np
from tqdm import tqdm

os.environ.setdefault("CHAOS_PHASE", "week4-pendulum-motor-driven")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import VIDEOS_DIR, PHASE_ROOT, EXPERIMENTS, REPO_ROOT  # noqa: E402

BASELINES_DIR = os.path.join(PHASE_ROOT, "baselines")


def resolve_video(stem):
    """Resolve --stem to an absolute video path via the registry, falling
    back to VIDEOS_DIR/<stem>.mov."""
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, "r", encoding="utf-8") as f:
            reg = json.load(f)
        for k, e in reg.items():
            if e.get("config_description") == stem or k == stem:
                vf = e.get("video_file")
                if vf:
                    return os.path.join(VIDEOS_DIR, vf)
    candidate = os.path.join(VIDEOS_DIR, f"{stem}.mov")
    if os.path.exists(candidate):
        return candidate
    raise SystemExit(f"ERROR: could not resolve video for stem '{stem}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", required=True,
                    help="Phase 2 clip stem, e.g. 4V_1.9Hz")
    args = ap.parse_args()

    video_path = resolve_video(args.stem)
    out_dir = os.path.join(BASELINES_DIR, args.stem)
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "centroids.csv")

    print(f"Baseline capture: {args.stem}")
    print(f"  video: {os.path.relpath(video_path, REPO_ROOT)}")
    print(f"  out:   {os.path.relpath(out_csv, REPO_ROOT)}")

    # ============================================================
    # BEGIN VERBATIM BLOCK
    # Copy-pasted from week4-pendulum-motor-driven/legacy/get_video_coords.py lines 16-93.
    # Only difference: video path is `video_path` (arg) instead of the
    # hardcoded literal, and `frame_idx` is tracked for the CSV.
    # DO NOT REFACTOR THIS BLOCK — it is the regression reference.
    # ============================================================

    # Open video
    cap = cv2.VideoCapture(video_path)
    data = []

    # Define HSV color ranges for Green and Red
    # Note: Red wraps around the hue channel (0-10 and 160-180)
    green_lower, green_upper = np.array([0, 100, 0]), np.array([70, 255, 90])
    red_lower1, red_upper1 = np.array([0, 0, 100]), np.array([45, 75, 255])
    red_lower2, red_upper2 = np.array([0, 0, 110]), np.array([60, 80, 255])
    red_lower3, red_upper3 = np.array([0, 0, 125]), np.array([75, 95, 255])
    # red_lower2, red_upper2 = np.array([160, 100, 100]), np.array([180, 255, 255])

    # skip_frames=1000

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    pbar = tqdm(total=total_frames, desc="Processing Video")

    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        # if skip_frames>0:
        #     skip_frames-=1
        #     continue

        pbar.update(1)

        time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        # hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        frame=frame[:,350:950,:]
        # Create masks
        mask_g = cv2.inRange(frame, green_lower, green_upper)
        mask_r = cv2.inRange(frame, red_lower1, red_upper1)
        mask_r2 = cv2.inRange(frame, red_lower2, red_upper2)
        mask_r3 = cv2.inRange(frame, red_lower3, red_upper3)
        # mask_r = cv2.bitwise_or(cv2.inRange(hsv, red_lower1, red_upper1),
                                # cv2.inRange(hsv, red_lower2, red_upper2))

        # Calculate centers using image moments
        M_g = cv2.moments(mask_g)
        M_r = cv2.moments(mask_r)
        M_r2 = cv2.moments(mask_r2)
        M_r3 = cv2.moments(mask_r3)

        # Avoid division by zero if the color is obscured/missing
        gx = int(M_g['m10']/M_g['m00']) if M_g['m00'] > 0 else None
        gy = int(M_g['m01']/M_g['m00']) if M_g['m00'] > 0 else None
        rx = int(M_r['m10']/M_r['m00']) if M_r['m00'] > 0 else None
        ry = int(M_r['m01']/M_r['m00']) if M_r['m00'] > 0 else None
        if rx is None or ry is None:
            rx = int(M_r2['m10']/M_r2['m00']) if M_r2['m00'] > 0 else None
            ry = int(M_r2['m01']/M_r2['m00']) if M_r2['m00'] > 0 else None
        if rx is None or ry is None:
            rx = int(M_r3['m10']/M_r3['m00']) if M_r3['m00'] > 0 else None
            ry = int(M_r3['m01']/M_r3['m00']) if M_r3['m00'] > 0 else None

        data.append([frame_idx, time_sec, gx, gy, rx, ry])
        frame_idx += 1

    # Clean up
    cap.release()
    cv2.destroyAllWindows()

    # ============================================================
    # END VERBATIM BLOCK
    # ============================================================

    pbar.close()

    # Write baseline CSV — empty cell for None centroids.
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "gx_crop", "gy_crop", "rx_crop", "ry_crop"])
        for row in data:
            fi, t, gx, gy, rx, ry = row
            w.writerow([
                fi,
                f"{t:.6f}",
                "" if gx is None else gx,
                "" if gy is None else gy,
                "" if rx is None else rx,
                "" if ry is None else ry,
            ])

    n_total = len(data)
    n_green_miss = sum(1 for r in data if r[2] is None or r[3] is None)
    n_red_miss   = sum(1 for r in data if r[4] is None or r[5] is None)
    n_both_ok    = sum(1 for r in data
                       if r[2] is not None and r[3] is not None
                       and r[4] is not None and r[5] is not None)
    print()
    print(f"Wrote {n_total} rows to {os.path.relpath(out_csv, REPO_ROOT)}")
    if n_total:
        print(f"  green misses: {n_green_miss}  ({100*n_green_miss/n_total:.2f}%)")
        print(f"  red misses:   {n_red_miss}    ({100*n_red_miss/n_total:.2f}%)")
        print(f"  both found:   {n_both_ok}     ({100*n_both_ok/n_total:.2f}%)")


if __name__ == "__main__":
    main()
