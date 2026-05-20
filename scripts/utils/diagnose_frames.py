"""
diagnose_frames.py
-------------------
Render a small grid of video frames with the tracked marker positions
overlaid as cross-hairs (green and red). Pure visualization — reads
the already-produced tracking.csv, doesn't change any tracking logic.

Designed for "show me what the tracker actually found on this clip"
sanity checks. Useful when scan_tracking_quality flags a FAIL and
you want to see whether the red marker really wandered onto the
wrong blob.

What it draws on each frame:
  - GREEN cross-hair at (x_green, y_green)
  - RED cross-hair at (x_red, y_red)
  - Faint dashed line connecting them (the "arm 2" the tracker sees)
  - Frame number, time, theta1/theta2 readout in the corner

Frame selection (default):
  Picks 6 frames: frame 0, then ±2 around the worst |ω₂| spike (from
  verification.csv), then the last frame. Override with --frames N1,N2,...

Usage
~~~~~
    python scripts/utils/diagnose_frames.py --stem 3.2V_0.91Hz
    python scripts/utils/diagnose_frames.py --stem 4V_1.9Hz
    python scripts/utils/diagnose_frames.py --stem 3.2V_0.91Hz \\
        --frames 100,300,995,1000,2000

Output
~~~~~~
    measurements/<stem>/diagnostic.png
"""

import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import VIDEOS_DIR, MEAS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from thresholds import (  # noqa: E402
    CROP_X_START, CROP_X_END,
    PIVOT, ARM_LENGTH_PX,
)


GREEN_BGR = (60, 220, 60)
RED_BGR   = (60, 60, 240)
WHITE_BGR = (255, 255, 255)
BLACK_BGR = (0, 0, 0)

# Display crop: extend slightly beyond the BGR detection window so the
# pivot and a margin around the swing arc are visible, but don't show
# the entire 1920-wide frame.
DISPLAY_MARGIN_PX = 40
# Vertical extent: pivot ± 2.5 × ARM_LENGTH_PX covers the full reach of
# the double pendulum even when both arms swing fully through inverted.
DISPLAY_Y_RADIUS = int(2.5 * ARM_LENGTH_PX)


def load_registry():
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_entry(stem):
    reg = load_registry()
    for k, e in reg.items():
        if e.get("config_description") == stem or k == stem:
            return e
    raise SystemExit(f"ERROR: stem {stem!r} not in registry")


def load_tracking(meas_dir):
    path = os.path.join(meas_dir, "tracking.csv")
    if not os.path.exists(path):
        raise SystemExit(f"ERROR: tracking.csv not found at {path}")
    rows = []
    with open(path, "r") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def find_worst_om2_frame(meas_dir):
    """Return (frame_idx, |ω₂|) of the worst spike in verification.csv,
    or (None, 0.0) if no verification.csv exists."""
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return None, 0.0
    worst_frame = None
    worst_om2 = 0.0
    with open(path, "r") as f:
        for r in csv.DictReader(f):
            try:
                om2 = abs(float(r.get("omega2_deg_s") or 0))
            except ValueError:
                continue
            if om2 > worst_om2:
                worst_om2 = om2
                worst_frame = int(r["frame"])
    return worst_frame, worst_om2


def default_frame_picks(n_total, worst_frame):
    if worst_frame is None:
        worst_frame = n_total // 2
    picks = [0,
             max(0, worst_frame - 2),
             max(0, worst_frame - 1),
             worst_frame,
             min(n_total - 1, worst_frame + 1),
             min(n_total - 1, worst_frame + 2),
             n_total - 1]
    # Dedupe + clip + sort
    return sorted(set(p for p in picks if 0 <= p < n_total))


def draw_marker_crosshair(img, x, y, color, size=22, thickness=3):
    cv2.circle(img, (x, y), 12, color, thickness)
    cv2.line(img, (x - size, y), (x + size, y), color, 1)
    cv2.line(img, (x, y - size), (x, y + size), color, 1)


def overlay_text(img, lines, anchor=(10, 30), font_scale=0.7):
    for i, txt in enumerate(lines):
        org = (anchor[0], anchor[1] + i * 28)
        cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    BLACK_BGR, 3, cv2.LINE_AA)
        cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    WHITE_BGR, 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stem", required=True,
                    help="clip stem, e.g. 3.2V_0.91Hz")
    ap.add_argument("--frames", default=None,
                    help="comma-separated frame indices; default picks "
                         "0, ±2 around the worst |ω₂| frame, last frame")
    ap.add_argument("--cols", type=int, default=3,
                    help="number of grid columns (default 3)")
    ap.add_argument("--scale", type=float, default=0.6,
                    help="per-panel resize factor (default 0.6)")
    ap.add_argument("--no-crop", action="store_true",
                    help="show the full original frame instead of the "
                         "detection window (default: crop to "
                         "Cohen's [CROP_X_START:CROP_X_END] window + "
                         "pivot-relative Y margin)")
    args = ap.parse_args()

    entry    = resolve_entry(args.stem)
    meas_dir = os.path.join(MEAS_DIR, args.stem)
    tracking = load_tracking(meas_dir)
    rows_by_frame = {int(r["frame"]): r for r in tracking}
    n_total  = len(tracking)
    worst_frame, worst_om2 = find_worst_om2_frame(meas_dir)

    # Frame selection.
    if args.frames:
        frame_idxs = [int(s.strip()) for s in args.frames.split(",")]
    else:
        frame_idxs = default_frame_picks(n_total, worst_frame)

    video_file = entry.get("video_file") or f"{args.stem}.mov"
    video_path = os.path.join(VIDEOS_DIR, video_file)
    if not os.path.exists(video_path):
        raise SystemExit(f"ERROR: video missing: {video_path}")

    print(f"diagnose_frames  {args.stem}")
    print(f"  video        : {os.path.relpath(video_path, REPO_ROOT)}")
    print(f"  total frames : {n_total}")
    if worst_frame is not None:
        print(f"  worst |ω₂|   : {worst_om2:.0f} °/s at frame {worst_frame}")
    print(f"  frames shown : {frame_idxs}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open video")

    # Display crop: a few px wider than the BGR window so the edge is
    # visible, and a vertical band centred on the pivot.
    if args.no_crop:
        display_box = None
    else:
        full_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        full_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        x0 = max(0, CROP_X_START - DISPLAY_MARGIN_PX)
        x1 = min(full_w, CROP_X_END + DISPLAY_MARGIN_PX)
        y0 = max(0, PIVOT[1] - DISPLAY_Y_RADIUS)
        y1 = min(full_h, PIVOT[1] + DISPLAY_Y_RADIUS)
        display_box = (x0, y0, x1, y1)
        print(f"  display crop : x[{x0}:{x1}]  y[{y0}:{y1}]  "
              f"({x1-x0}×{y1-y0})")

    panels = []
    for idx in frame_idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            print(f"  WARN: could not read frame {idx}")
            continue
        r = rows_by_frame.get(idx, {})

        # Pull tracked positions (may be empty strings on dropout rows).
        gx_s = r.get("x_green", "")
        gy_s = r.get("y_green", "")
        rx_s = r.get("x_red", "")
        ry_s = r.get("y_red", "")
        gx = int(gx_s) if gx_s else None
        gy = int(gy_s) if gy_s else None
        rx = int(rx_s) if rx_s else None
        ry = int(ry_s) if ry_s else None

        # Connect arm 2 (green → red) so eye can see what the tracker
        # thinks the rigid rod looks like this frame.
        if gx is not None and rx is not None:
            cv2.line(frame, (gx, gy), (rx, ry), (180, 180, 180), 2,
                     cv2.LINE_AA)

        if gx is not None:
            draw_marker_crosshair(frame, gx, gy, GREEN_BGR)
        if rx is not None:
            draw_marker_crosshair(frame, rx, ry, RED_BGR)

        # Compute arm length for the readout (px between green and red).
        arm_len = None
        if gx is not None and rx is not None:
            arm_len = float(np.hypot(rx - gx, ry - gy))

        th1 = r.get("theta1_deg", "—")
        th2 = r.get("theta2_deg", "—")
        time_s = float(r.get("time_s", 0)) if r.get("time_s") else 0.0
        dropout = r.get("dropout", "0")

        label = [
            f"{args.stem}  frame {idx}  (t={time_s:.2f}s)",
            f"green=({gx},{gy})  red=({rx},{ry})",
            f"arm_len={arm_len:.1f}px " if arm_len is not None else "arm_len=—",
            f"theta1={th1}  theta2={th2}  dropout={dropout}",
        ]
        if idx == worst_frame:
            label.append(f"  *** worst |omega2|: {worst_om2:.0f} deg/s ***")

        # Draw the BGR detection window outline so it's clear what
        # region the tracker actually operates on.
        cv2.rectangle(frame, (CROP_X_START, 0),
                      (CROP_X_END, frame.shape[0]),
                      (200, 200, 200), 1)

        overlay_text(frame, label)

        # Crop the display region so the panel is centred on the
        # pendulum's reach (default) rather than the full 1920-wide
        # frame. Detection logic is unchanged — this is purely for
        # the visualization.
        if display_box is not None:
            x0, y0, x1, y1 = display_box
            frame = frame[y0:y1, x0:x1]

        # Resize.
        new_w = int(frame.shape[1] * args.scale)
        new_h = int(frame.shape[0] * args.scale)
        panels.append(cv2.resize(frame, (new_w, new_h)))

    cap.release()

    if not panels:
        raise SystemExit("ERROR: no frames rendered")

    # Build grid.
    cols = args.cols
    rows_n = (len(panels) + cols - 1) // cols
    ph, pw = panels[0].shape[:2]
    grid = np.zeros((rows_n * ph, cols * pw, 3), dtype=np.uint8)
    for i, p in enumerate(panels):
        r_idx, c_idx = i // cols, i % cols
        # Pad last row's empties if needed
        if p.shape[:2] != (ph, pw):
            p = cv2.resize(p, (pw, ph))
        grid[r_idx * ph:(r_idx + 1) * ph,
             c_idx * pw:(c_idx + 1) * pw] = p

    out_path = os.path.join(meas_dir, "diagnostic.png")
    cv2.imwrite(out_path, grid)
    print(f"Wrote: {os.path.relpath(out_path, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
