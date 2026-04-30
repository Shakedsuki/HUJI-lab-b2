"""
pendulum_tracker.py
--------------------
Tracks the two colored markers on a double pendulum video:
  - GREEN dot  : joint between arm 1 and arm 2
  - RED dot    : tip of arm 2

The YELLOW pivot is fixed and hard-coded — no detection needed.

Outputs a CSV with one row per frame:
  frame, time_s, x_green, y_green, x_red, y_red,
  theta1_deg, theta2_deg, dropout_flag

Usage:
  python pendulum_tracker.py
  (edit the CONFIG section below before running)
"""

import cv2          # OpenCV — video reading, color detection, drawing
import numpy as np  # Numerical arrays (frames are numpy arrays)
import csv          # Writing output CSV
import os           # File path handling


# ─────────────────────────────────────────────
# CONFIG — edit these values before running
# ─────────────────────────────────────────────

VIDEO_PATH  = r"C:\dev\chaos\Videos\DSC_0136_trimmed.mov"
OUTPUT_CSV  = r"C:\dev\chaos\data\DSC_0136_tracking.csv"

# Fixed pivot pixel coordinates (yellow dot, hard-coded)
# Measured from static frame — never moves
PIVOT        = (608, 355)       # (x, y) in pixels

# Physical arm length in cm (both arms are equal)
ARM_LENGTH_CM = 35.0

# Pixel scale: how many cm per pixel
# Derived from: 22cm plate ≈ 118px  →  22/118 ≈ 0.186 cm/px
CM_PER_PIXEL  = 0.186

# Radius of circular mask in pixels
# = (arm1 + arm2) in cm / cm_per_pixel = 70 / 0.186 ≈ 376
MASK_RADIUS   = 376

# HSV color ranges — (Hue, Saturation, Value), each 0-179/255/255 in OpenCV
# Tuned using hsv_tuner.py on DSC_0136.mov
# GREEN marker
GREEN_LOWER = np.array([35,  30,  80])
GREEN_UPPER = np.array([80, 255, 255])

# RED marker — red wraps around in HSV so we need TWO ranges
RED_LOWER_1 = np.array([  0,  32,  72])
RED_UPPER_1 = np.array([ 10, 255, 255])
RED_LOWER_2 = np.array([165,  32,  72])
RED_UPPER_2 = np.array([179, 255, 255])

# Minimum blob area in pixels² — blobs smaller than this are ignored (noise)
MIN_BLOB_AREA = 30

# If True, writes a debug video showing the detected blobs and angles
WRITE_DEBUG_VIDEO = True
DEBUG_VIDEO_PATH  = r"C:\dev\chaos\output\DSC_0136_debug.mp4"


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def find_centroid(mask):
    """
    Given a binary mask (white = detected color, black = background),
    find the centroid (center of mass) of the largest blob.

    Returns (x, y) as integers, or None if no blob found.
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

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return (cx, cy)


def compute_angle(point_from, point_to):
    """
    Compute the angle of the vector (point_from → point_to)
    relative to straight downward (the resting position).

    Convention:
      - 0°   = arm pointing straight down
      - +90° = arm pointing right
      - -90° = arm pointing left
      - ±180° = arm pointing straight up

    Image y-axis points DOWN, so we use atan2(dx, dy) — not atan2(dy, dx).
    Returns angle in degrees.
    """
    dx = point_to[0] - point_from[0]
    dy = point_to[1] - point_from[1]
    angle_rad = np.arctan2(dx, dy)
    return np.degrees(angle_rad)


def build_circular_mask(frame_shape, center, radius):
    """
    Build a binary mask with a filled white circle.
    Restricts color detection to within the pendulum's reachable area.
    """
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

    print(f"Video: {width}x{height} @ {fps:.2f}fps, {total_frames} frames")

    frame_shape = (height, width)
    circle_mask = build_circular_mask(frame_shape, PIVOT, MASK_RADIUS)

    # Dilation kernel — expands blobs to recover motion-blurred markers
    kernel = np.ones((5, 5), np.uint8)

    writer = None
    if WRITE_DEBUG_VIDEO:
        os.makedirs(os.path.dirname(DEBUG_VIDEO_PATH), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(DEBUG_VIDEO_PATH, fourcc, fps, (width, height))

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    with open(OUTPUT_CSV, 'w', newline='') as csvfile:
        fieldnames = [
            'frame', 'time_s',
            'x_green', 'y_green',
            'x_red',   'y_red',
            'theta1_deg', 'theta2_deg',
            'dropout'
        ]
        writer_csv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer_csv.writeheader()

        frame_idx     = 0
        dropout_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # BGR → HSV
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Color masks
            mask_green = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)
            mask_red   = cv2.bitwise_or(
                cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1),
                cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
            )

            # Restrict to circular zone
            mask_green = cv2.bitwise_and(mask_green, circle_mask)
            mask_red   = cv2.bitwise_and(mask_red,   circle_mask)

            # Dilate to recover motion-blurred markers
            mask_green = cv2.dilate(mask_green, kernel, iterations=1)
            mask_red   = cv2.dilate(mask_red,   kernel, iterations=1)

            # Detect centroids
            green_pos = find_centroid(mask_green)
            red_pos   = find_centroid(mask_red)

            dropout = (green_pos is None or red_pos is None)
            if dropout:
                dropout_count += 1

            # Compute angles
            theta1 = compute_angle(PIVOT, green_pos)      if not dropout else None
            theta2 = compute_angle(green_pos, red_pos)    if not dropout else None

            # Write CSV row
            time_s = frame_idx / fps
            writer_csv.writerow({
                'frame':      frame_idx,
                'time_s':     round(time_s, 5),
                'x_green':    green_pos[0] if green_pos else '',
                'y_green':    green_pos[1] if green_pos else '',
                'x_red':      red_pos[0]   if red_pos   else '',
                'y_red':      red_pos[1]   if red_pos   else '',
                'theta1_deg': round(theta1, 3) if theta1 is not None else '',
                'theta2_deg': round(theta2, 3) if theta2 is not None else '',
                'dropout':    1 if dropout else 0
            })

            # Debug overlay
            if WRITE_DEBUG_VIDEO and writer:
                debug = frame.copy()
                cv2.circle(debug, PIVOT, MASK_RADIUS, (200, 200, 200), 1)
                cv2.circle(debug, PIVOT, 8, (0, 215, 255), -1)

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

                cv2.putText(debug, f"frame {frame_idx}/{total_frames}",
                           (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
                if dropout:
                    cv2.putText(debug, "DROPOUT", (10, 55),
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


if __name__ == "__main__":
    main()
