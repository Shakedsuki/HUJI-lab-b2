"""
pendulum_tracker.py
--------------------
VERSION = "1.3.0"
Changes:
  1.0.0 — initial tracker, HSV detection + circular mask + CSV export
  1.1.0 — updated HSV thresholds (S min 30/32, V min 72) + dilation
  1.2.0 — geometric validation: rejects detections violating arm length constraint
  1.3.0 — temporal continuity constraint: rejects detections too far from previous frame
--------------------
Tracks the two colored markers on a double pendulum video:
  - GREEN dot  : joint between arm 1 and arm 2
  - RED dot    : tip of arm 2

The YELLOW pivot is fixed and hard-coded — no detection needed.

Outputs a CSV with one row per frame:
  frame, time_s, x_green, y_green, x_red, y_red,
  theta1_deg, theta2_deg, phase, dropout

phase:
  'holding'    — before RELEASE_FRAME (person still holding pendulum)
  'free_swing' — from RELEASE_FRAME onward (free dynamics)

Usage:
  python scripts/pendulum_tracker.py
  Set RELEASE_FRAME in CONFIG after watching the debug video.
"""

import cv2
import numpy as np
import csv
import os


# ─────────────────────────────────────────────
# CONFIG — edit these values before running
# ─────────────────────────────────────────────

VIDEO_PATH  = r"C:\dev\chaos\Videos\DSC_0136.mov"
OUTPUT_CSV  = r"C:\dev\chaos\data\DSC_0136_tracking.csv"

# Fixed pivot pixel coordinates (yellow dot — never moves)
PIVOT = (608, 355)

# Physical arm length in cm (both arms equal)
ARM_LENGTH_CM = 35.0

# Pixel scale: 22cm plate ≈ 118px → 22/118 ≈ 0.186 cm/px
CM_PER_PIXEL = 0.186

# Arm length in pixels — used for geometric validation
ARM_LENGTH_PX = ARM_LENGTH_CM / CM_PER_PIXEL   # ≈ 188px

# Geometric validation tolerance in pixels
# A detection is rejected if its distance from the expected point
# differs by more than this amount. ±50px ≈ ±9cm — generous enough
# to handle tracking noise, strict enough to reject body false positives.
ARM_TOLERANCE_PX = 50

# Temporal continuity constraint — max pixels a marker can move per frame.
# Physics basis: max tip speed at full energy ≈ sqrt(2*g*2L) ≈ 3.7 m/s
# At 0.186 cm/px and 59.94fps → max ~33 px/frame. We use 60 for safety margin.
# The person's hand is always 200+ px away from the last known marker position,
# so this constraint cleanly rejects false positives during the release period.
MAX_DISPLACEMENT_PX = 60

# Radius of circular mask in pixels (= total arm reach)
MASK_RADIUS = 376

# HSV color ranges — tuned using hsv_tuner.py on DSC_0136.mov
GREEN_LOWER = np.array([35,  30,  80])
GREEN_UPPER = np.array([80, 255, 255])

RED_LOWER_1 = np.array([  0,  32,  72])
RED_UPPER_1 = np.array([ 10, 255, 255])
RED_LOWER_2 = np.array([165,  32,  72])
RED_UPPER_2 = np.array([179, 255, 255])

# Minimum blob area in pixels²
MIN_BLOB_AREA = 30

# Release frame — the frame where the person lets go of the pendulum.
# Set this AFTER watching the debug video once.
# Everything before this frame is tagged 'holding' in the CSV.
# Set to 0 if unknown (all frames tagged 'free_swing').
RELEASE_FRAME = 0

# Debug video output
WRITE_DEBUG_VIDEO = True
DEBUG_VIDEO_PATH  = r"C:\dev\chaos\output\DSC_0136_debug.mp4"


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def find_centroid(mask):
    """
    Find centroid of the largest blob in a binary mask.
    Returns (x, y) or None if no valid blob found.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < MIN_BLOB_AREA:
        return None

    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None

    return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))


def dist(p1, p2):
    """Euclidean distance between two (x, y) points."""
    return np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)


def validate_geometry(green_pos, red_pos):
    """
    Reject detections that violate the known arm length constraint.

    The arms are rigid — both are 35cm ≈ 188px.
    Any detection more than ARM_TOLERANCE_PX away from the expected
    distance is physically impossible and must be a false positive
    (e.g. a pixel on the person's body that happens to be green/red).

    Returns (green_pos, red_pos) with invalid detections set to None.
    """
    # Validate green: must be ~ARM_LENGTH_PX from pivot
    if green_pos is not None:
        d = dist(PIVOT, green_pos)
        if abs(d - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            green_pos = None   # reject — too far or too close to pivot

    # Validate red: must be ~ARM_LENGTH_PX from green
    # (only meaningful if green was already validated)
    if red_pos is not None and green_pos is not None:
        d = dist(green_pos, red_pos)
        if abs(d - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            red_pos = None     # reject — arm 2 length doesn't match
    elif green_pos is None:
        red_pos = None         # can't validate red without green anchor

    return green_pos, red_pos


def check_temporal_continuity(new_pos, prev_pos):
    """
    Reject a detection if it is too far from the marker's previous position.
    Between consecutive frames at 60fps, a marker cannot move more than
    MAX_DISPLACEMENT_PX pixels — this is enforced by the physics of the system.

    Returns new_pos if valid, None if rejected.
    If prev_pos is None (first frames), no constraint is applied.
    """
    if prev_pos is None:
        return new_pos   # no prior — can't constrain yet
    if new_pos is None:
        return None
    if dist(new_pos, prev_pos) > MAX_DISPLACEMENT_PX:
        return None      # reject — impossible displacement between frames
    return new_pos


def compute_angle(point_from, point_to):
    """
    Angle of vector (point_from → point_to) relative to straight down.
    Convention: 0° = down, +90° = right, -90° = left, ±180° = up.
    Image y-axis points DOWN → use atan2(dx, dy).
    Returns degrees.
    """
    dx = point_to[0] - point_from[0]
    dy = point_to[1] - point_from[1]
    return np.degrees(np.arctan2(dx, dy))


def build_circular_mask(frame_shape, center, radius):
    """Binary circular mask — restricts detection to reachable zone."""
    mask = np.zeros(frame_shape[:2], dtype=np.uint8)
    cv2.circle(mask, center, radius, 255, -1)
    return mask


# ─────────────────────────────────────────────
# MAIN TRACKING LOOP
# ─────────────────────────────────────────────

def main():
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"ERROR: Could not open video: {VIDEO_PATH}")
        return

    fps          = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"pendulum_tracker.py  v1.3.0")
    print(f"Video: {width}x{height} @ {fps:.2f}fps, {total_frames} frames")
    print(f"Arm length: {ARM_LENGTH_PX:.1f}px  tolerance: ±{ARM_TOLERANCE_PX}px")
    if RELEASE_FRAME > 0:
        print(f"Release frame: {RELEASE_FRAME} (t={RELEASE_FRAME/fps:.3f}s)")
    else:
        print("Release frame: not set — all frames tagged as free_swing")

    circle_mask = build_circular_mask((height, width), PIVOT, MASK_RADIUS)
    kernel      = np.ones((5, 5), np.uint8)   # dilation kernel

    writer = None
    if WRITE_DEBUG_VIDEO:
        os.makedirs(os.path.dirname(DEBUG_VIDEO_PATH), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(DEBUG_VIDEO_PATH, fourcc, fps, (width, height))

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    with open(OUTPUT_CSV, 'w', newline='') as csvfile:
        fieldnames = [
            'frame', 'time_s', 'phase',
            'x_green', 'y_green',
            'x_red',   'y_red',
            'theta1_deg', 'theta2_deg',
            'dropout'
        ]
        writer_csv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer_csv.writeheader()

        frame_idx     = 0
        dropout_count = 0
        prev_green    = None   # last known valid green position
        prev_red      = None   # last known valid red position

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # ── Phase tag ──
            if RELEASE_FRAME > 0 and frame_idx < RELEASE_FRAME:
                phase = 'holding'
            else:
                phase = 'free_swing'

            # ── BGR → HSV ──
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # ── Color masks ──
            mask_green = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)
            mask_red   = cv2.bitwise_or(
                cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1),
                cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
            )

            # ── Restrict to circular zone ──
            mask_green = cv2.bitwise_and(mask_green, circle_mask)
            mask_red   = cv2.bitwise_and(mask_red,   circle_mask)

            # ── Dilate to recover motion-blurred markers ──
            mask_green = cv2.dilate(mask_green, kernel, iterations=1)
            mask_red   = cv2.dilate(mask_red,   kernel, iterations=1)

            # ── Find centroids ──
            green_pos = find_centroid(mask_green)
            red_pos   = find_centroid(mask_red)

            # ── Geometric validation ──
            # Rejects detections that don't match the known arm lengths.
            green_pos, red_pos = validate_geometry(green_pos, red_pos)

            # ── Temporal continuity constraint ──
            # Rejects detections that are too far from the previous frame's
            # position. Eliminates false positives (e.g. person's hand during
            # release) that happen to pass the geometric distance check.
            green_pos = check_temporal_continuity(green_pos, prev_green)
            red_pos   = check_temporal_continuity(red_pos,   prev_red)

            dropout = (green_pos is None or red_pos is None)
            if dropout:
                dropout_count += 1
            else:
                # Update previous positions only on successful detection
                prev_green = green_pos
                prev_red   = red_pos

            # ── Compute angles ──
            theta1 = compute_angle(PIVOT, green_pos)     if not dropout else None
            theta2 = compute_angle(green_pos, red_pos)   if not dropout else None

            # ── Write CSV row ──
            time_s = frame_idx / fps
            writer_csv.writerow({
                'frame':      frame_idx,
                'time_s':     round(time_s, 5),
                'phase':      phase,
                'x_green':    green_pos[0] if green_pos else '',
                'y_green':    green_pos[1] if green_pos else '',
                'x_red':      red_pos[0]   if red_pos   else '',
                'y_red':      red_pos[1]   if red_pos   else '',
                'theta1_deg': round(theta1, 3) if theta1 is not None else '',
                'theta2_deg': round(theta2, 3) if theta2 is not None else '',
                'dropout':    1 if dropout else 0
            })

            # ── Debug overlay ──
            if WRITE_DEBUG_VIDEO and writer:
                debug = frame.copy()

                # Circle boundary
                cv2.circle(debug, PIVOT, MASK_RADIUS, (200, 200, 200), 1)

                # Fixed pivot (yellow)
                cv2.circle(debug, PIVOT, 8, (0, 215, 255), -1)

                # Phase label
                phase_color = (100, 100, 255) if phase == 'holding' else (100, 255, 100)
                cv2.putText(debug, phase.upper(), (10, 55),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, phase_color, 2)

                if green_pos:
                    cv2.circle(debug, green_pos, 8, (0, 255, 0), -1)
                    cv2.line(debug, PIVOT, green_pos, (0, 255, 0), 2)
                    if theta1 is not None:
                        cv2.putText(debug, f"th1={theta1:.1f}",
                                   (green_pos[0]+10, green_pos[1]),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)

                if red_pos:
                    cv2.circle(debug, red_pos, 8, (0, 0, 255), -1)

                if green_pos and red_pos:
                    cv2.line(debug, green_pos, red_pos, (0, 0, 255), 2)
                    if theta2 is not None:
                        cv2.putText(debug, f"th2={theta2:.1f}",
                                   (red_pos[0]+10, red_pos[1]),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

                # Frame info
                cv2.putText(debug, f"frame {frame_idx}/{total_frames}  t={time_s:.2f}s",
                           (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)

                if dropout:
                    cv2.putText(debug, "DROPOUT", (10, 85),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                writer.write(debug)

            frame_idx += 1
            if frame_idx % 100 == 0:
                print(f"  Processed {frame_idx}/{total_frames} frames "
                      f"({100*frame_idx//total_frames}%)  "
                      f"dropouts so far: {dropout_count}")

    cap.release()
    if writer:
        writer.release()

    print(f"\nDone. {total_frames} frames processed.")
    print(f"Dropouts: {dropout_count} ({100*dropout_count/total_frames:.1f}%)")
    print(f"CSV saved to:         {OUTPUT_CSV}")
    if WRITE_DEBUG_VIDEO:
        print(f"Debug video saved to: {DEBUG_VIDEO_PATH}")
    if RELEASE_FRAME == 0:
        print("\nNext step: watch the debug video, find the release frame,")
        print("then set RELEASE_FRAME in CONFIG and re-run.")


if __name__ == "__main__":
    main()
