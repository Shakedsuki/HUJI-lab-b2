"""
pendulum_tracker.py
-------------------
Tracks the two markers on a double pendulum video using OpenCV's built-in
CSRT (Channel and Spatial Reliability Tracking) appearance tracker.

  - GREEN marker : joint between arm 1 and arm 2
  - RED   marker : tip of arm 2

The YELLOW pivot is fixed at (608, 355) — never detected.

Outputs a CSV with one row per frame:
  frame, time_s, phase, x_green, y_green, x_red, y_red,
  theta1_deg, theta2_deg, dropout

phase:
  'holding'    — before RELEASE_FRAME (person still holding pendulum)
  'free_swing' — from RELEASE_FRAME onward (free dynamics)

Dependencies:
  pip install opencv-contrib-python numpy
  (must be opencv-contrib-python — contrib has the trackers)

Usage:
  python scripts/pendulum_tracker.py

When prompted to draw ROIs, include generous background padding around
each marker (2-3x the marker size). Tight bboxes cause CSRT to lose lock
under motion blur.
"""

import cv2
import numpy as np
import csv
import os


# ─────────────────────────────────────────────
# CONFIG — fixed parameters
# ─────────────────────────────────────────────

VIDEO_PATH       = r"C:\dev\chaos\Videos\DSC_0136.mov"
OUTPUT_CSV       = r"C:\dev\chaos\data\DSC_0136_tracking.csv"
DEBUG_VIDEO_PATH = r"C:\dev\chaos\output\DSC_0136_debug.mp4"

PIVOT            = (608, 355)   # fixed wall mount pixel coordinates
ARM_LENGTH_PX    = 188          # ≈ 35cm / 0.186 cm/px
ARM_TOLERANCE_PX = 50           # geometric validation tolerance
MASK_RADIUS      = 376          # circular search zone radius
FPS              = 59.94


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def dist(p1, p2):
    return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def compute_angle(point_from, point_to):
    """
    Angle of vector (point_from → point_to) relative to straight down.
    0° = down, +90° = right, -90° = left, ±180° = up. Image y-axis is DOWN.
    """
    dx = point_to[0] - point_from[0]
    dy = point_to[1] - point_from[1]
    return np.degrees(np.arctan2(dx, dy))


def bbox_centroid(bbox):
    x, y, w, h = bbox
    return (int(x + w / 2), int(y + h / 2))


def validate_geometry(green_pos, red_pos):
    """
    Reject centroids that violate the rigid-arm length constraint.
    Returns (green_pos, red_pos) with invalid points set to None.
    """
    if green_pos is not None:
        if abs(dist(PIVOT, green_pos) - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            green_pos = None

    if red_pos is not None and green_pos is not None:
        if abs(dist(green_pos, red_pos) - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            red_pos = None
    elif green_pos is None:
        red_pos = None

    return green_pos, red_pos


def make_csrt():
    """Create a CSRT tracker, supporting both legacy and modern OpenCV APIs."""
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError(
        "cv2.TrackerCSRT_create not found. Install opencv-contrib-python "
        "(not opencv-python): pip install opencv-contrib-python"
    )


def draw_dashed_circle(img, center, radius, color, thickness=1, dash_len=10):
    """Approximate a dashed circle by drawing short arcs."""
    n = max(8, int(2 * np.pi * radius / dash_len))
    for i in range(0, n, 2):
        a1 = 360.0 * i / n
        a2 = 360.0 * (i + 1) / n
        cv2.ellipse(img, center, (radius, radius), 0, a1, a2, color, thickness)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("pendulum_tracker.py  (CSRT appearance tracker)")

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"ERROR: could not open video: {VIDEO_PATH}")
        return

    video_fps    = cap.get(cv2.CAP_PROP_FPS) or FPS
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Video: {width}x{height} @ {video_fps:.2f}fps, {total_frames} frames")
    print(f"Arm length: {ARM_LENGTH_PX}px  tolerance: ±{ARM_TOLERANCE_PX}px")

    # ── Startup: ask for init frame ──
    while True:
        try:
            init_frame = int(input(
                "\nEnter the initialization frame number "
                "(first frame where both markers are visible): "
            ).strip())
            if 0 <= init_frame < total_frames:
                break
            print(f"  out of range; must be in [0, {total_frames - 1}]")
        except ValueError:
            print("  enter an integer")

    # Seek to init frame and grab it
    cap.set(cv2.CAP_PROP_POS_FRAMES, init_frame)
    ret, init_img = cap.read()
    if not ret:
        print(f"ERROR: could not read frame {init_frame}")
        cap.release()
        return

    # ── ROI selection: GREEN ──
    print("\nDraw box around GREEN marker, press ENTER/SPACE to confirm "
          "(c to cancel)")
    green_roi = cv2.selectROI("Select GREEN", init_img,
                              fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Select GREEN")
    if green_roi == (0, 0, 0, 0):
        print("ERROR: no GREEN ROI selected; aborting")
        cap.release()
        return

    # ── ROI selection: RED ──
    print("Draw box around RED marker, press ENTER/SPACE to confirm "
          "(c to cancel)")
    red_roi = cv2.selectROI("Select RED", init_img,
                            fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Select RED")
    if red_roi == (0, 0, 0, 0):
        print("ERROR: no RED ROI selected; aborting")
        cap.release()
        return

    # ── Initialize the two CSRT trackers ──
    tracker_green = make_csrt()
    tracker_red   = make_csrt()
    tracker_green.init(init_img, green_roi)
    tracker_red.init(init_img,   red_roi)

    print(f"Trackers initialized at frame {init_frame}")
    print(f"  GREEN ROI: {green_roi}  centroid: {bbox_centroid(green_roi)}")
    print(f"  RED   ROI: {red_roi}  centroid: {bbox_centroid(red_roi)}")

    # ── Ask for release frame ──
    while True:
        try:
            release_frame = int(input(
                "\nEnter RELEASE_FRAME (frame where pendulum is let go): "
            ).strip())
            if 0 <= release_frame < total_frames:
                break
            print(f"  out of range; must be in [0, {total_frames - 1}]")
        except ValueError:
            print("  enter an integer")

    print(f"Release frame: {release_frame} (t={release_frame / video_fps:.3f}s)")

    # ── Set up outputs ──
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    os.makedirs(os.path.dirname(DEBUG_VIDEO_PATH), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(DEBUG_VIDEO_PATH, fourcc, video_fps, (width, height))

    # ── Rewind to frame 0 — process ALL frames ──
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    dropout_total    = 0
    dropout_holding  = 0
    dropout_free     = 0

    with open(OUTPUT_CSV, 'w', newline='') as csvfile:
        fieldnames = [
            'frame', 'time_s', 'phase',
            'x_green', 'y_green',
            'x_red',   'y_red',
            'theta1_deg', 'theta2_deg',
            'dropout'
        ]
        wcsv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        wcsv.writeheader()

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            phase = 'holding' if frame_idx < release_frame else 'free_swing'

            # ── Run trackers ──
            ok_g, bbox_g = tracker_green.update(frame)
            ok_r, bbox_r = tracker_red.update(frame)

            green_pos = bbox_centroid(bbox_g) if ok_g else None
            red_pos   = bbox_centroid(bbox_r) if ok_r else None

            # ── Geometric validation ──
            green_pos, red_pos = validate_geometry(green_pos, red_pos)

            dropout = (green_pos is None or red_pos is None)
            if dropout:
                dropout_total += 1
                if phase == 'holding':
                    dropout_holding += 1
                else:
                    dropout_free += 1

            theta1 = compute_angle(PIVOT, green_pos)   if green_pos else None
            theta2 = (compute_angle(green_pos, red_pos)
                      if (green_pos and red_pos) else None)

            time_s = frame_idx / video_fps
            wcsv.writerow({
                'frame':      frame_idx,
                'time_s':     round(time_s, 5),
                'phase':      phase,
                'x_green':    green_pos[0] if green_pos else '',
                'y_green':    green_pos[1] if green_pos else '',
                'x_red':      red_pos[0]   if red_pos   else '',
                'y_red':      red_pos[1]   if red_pos   else '',
                'theta1_deg': round(theta1, 3) if theta1 is not None else '',
                'theta2_deg': round(theta2, 3) if theta2 is not None else '',
                'dropout':    1 if dropout else 0,
            })

            # ── Debug overlay ──
            debug = frame.copy()

            # Dashed search-zone circle (white)
            draw_dashed_circle(debug, PIVOT, MASK_RADIUS, (255, 255, 255), 1, 14)

            # Yellow pivot
            cv2.circle(debug, PIVOT, 8, (0, 215, 255), -1)

            # Phase label
            if phase == 'holding':
                phase_color = (100, 100, 255)
                phase_text  = "HOLDING"
            else:
                phase_color = (100, 255, 100)
                phase_text  = "FREE_SWING"
            cv2.putText(debug, phase_text, (10, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, phase_color, 2)

            # Green arm
            if green_pos is not None:
                cv2.line(debug, PIVOT, green_pos, (0, 255, 0), 2)
                cv2.circle(debug, green_pos, 8, (0, 255, 0), -1)
                if theta1 is not None:
                    cv2.putText(debug, f"th1={theta1:.1f}",
                                (green_pos[0] + 10, green_pos[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Red arm
            if red_pos is not None:
                cv2.circle(debug, red_pos, 8, (0, 0, 255), -1)
                if green_pos is not None:
                    cv2.line(debug, green_pos, red_pos, (0, 0, 255), 2)
                if theta2 is not None:
                    cv2.putText(debug, f"th2={theta2:.1f}",
                                (red_pos[0] + 10, red_pos[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # Frame counter
            cv2.putText(debug, f"frame {frame_idx}/{total_frames}  t={time_s:.2f}s",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            if dropout:
                cv2.putText(debug, "DROPOUT", (10, 85),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            writer.write(debug)

            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"  Processed {frame_idx}/{total_frames} frames "
                      f"({100 * frame_idx // total_frames}%)  "
                      f"dropouts: {dropout_total}")

    cap.release()
    writer.release()

    holding_n = release_frame
    free_n    = max(0, total_frames - release_frame)

    def pct(num, den):
        return f"{100 * num / den:.1f}%" if den > 0 else "n/a"

    print(f"\nDone. {total_frames} frames processed.")
    print(f"Dropouts total:    {dropout_total} ({pct(dropout_total, total_frames)})")
    print(f"  holding:    {dropout_holding}/{holding_n} "
          f"({pct(dropout_holding, holding_n)})")
    print(f"  free_swing: {dropout_free}/{free_n} "
          f"({pct(dropout_free, free_n)})")
    print(f"CSV saved to:         {OUTPUT_CSV}")
    print(f"Debug video saved to: {DEBUG_VIDEO_PATH}")


if __name__ == "__main__":
    main()
