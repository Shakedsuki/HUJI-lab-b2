"""
hsv_tuner.py
-------------
Interactive HSV range tuner for the pendulum tracker.

Opens a specific frame from the video and shows:
  - Left panel:  original frame with circular mask boundary drawn
  - Middle panel: GREEN detection mask (white = detected)
  - Right panel:  RED detection mask   (white = detected)

Use the trackbars to adjust HSV ranges live until both markers
are cleanly detected (solid white blobs, no noise).

Controls:
  - Trackbars: adjust H/S/V min and max for green and red
  - Keys:
      LEFT / RIGHT arrow : go back / forward 10 frames
      A / D              : go back / forward 1 frame
      SPACE              : jump to a specific frame number
      S                  : save current HSV values to hsv_values.txt
      Q or ESC           : quit

Usage:
  python hsv_tuner.py
  (edit the CONFIG section below)
"""

import cv2
import numpy as np

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
VIDEO_PATH  = r"C:\dev\chaos\Videos\DSC_0136.mov"
PIVOT       = (608, 355)
MASK_RADIUS = 376
START_FRAME = 400        # Start at the dropout cliff — change as needed


# ─────────────────────────────────────────────
# WINDOW AND TRACKBAR SETUP
# ─────────────────────────────────────────────
WIN = "HSV Tuner  |  LEFT/RIGHT=±10 frames  A/D=±1 frame  S=save  Q=quit"
cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WIN, 1400, 500)

# Green trackbars  (H: 0-179, S: 0-255, V: 0-255)
cv2.createTrackbar("G  H min", WIN,  35, 179, lambda x: None)
cv2.createTrackbar("G  H max", WIN,  80, 179, lambda x: None)
cv2.createTrackbar("G  S min", WIN,  30, 255, lambda x: None)
cv2.createTrackbar("G  S max", WIN, 255, 255, lambda x: None)
cv2.createTrackbar("G  V min", WIN,  80, 255, lambda x: None)
cv2.createTrackbar("G  V max", WIN, 255, 255, lambda x: None)

# Red trackbars (range 1 only — range 2 mirrors it symmetrically)
cv2.createTrackbar("R  H min", WIN,   0, 179, lambda x: None)
cv2.createTrackbar("R  H max", WIN,  10, 179, lambda x: None)
cv2.createTrackbar("R  S min", WIN,  32, 255, lambda x: None)
cv2.createTrackbar("R  S max", WIN, 255, 255, lambda x: None)
cv2.createTrackbar("R  V min", WIN,  72, 255, lambda x: None)
cv2.createTrackbar("R  V max", WIN, 255, 255, lambda x: None)


# ─────────────────────────────────────────────
# HELPER: build circular mask
# ─────────────────────────────────────────────
def build_circular_mask(shape, center, radius):
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.circle(mask, center, radius, 255, -1)
    return mask


# ─────────────────────────────────────────────
# HELPER: process one frame and return display image
# ─────────────────────────────────────────────
def process_frame(frame, circle_mask):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    g_h_min = cv2.getTrackbarPos("G  H min", WIN)
    g_h_max = cv2.getTrackbarPos("G  H max", WIN)
    g_s_min = cv2.getTrackbarPos("G  S min", WIN)
    g_s_max = cv2.getTrackbarPos("G  S max", WIN)
    g_v_min = cv2.getTrackbarPos("G  V min", WIN)
    g_v_max = cv2.getTrackbarPos("G  V max", WIN)

    r_h_min = cv2.getTrackbarPos("R  H min", WIN)
    r_h_max = cv2.getTrackbarPos("R  H max", WIN)
    r_s_min = cv2.getTrackbarPos("R  S min", WIN)
    r_s_max = cv2.getTrackbarPos("R  S max", WIN)
    r_v_min = cv2.getTrackbarPos("R  V min", WIN)
    r_v_max = cv2.getTrackbarPos("R  V max", WIN)

    mask_green = cv2.inRange(hsv,
        np.array([g_h_min, g_s_min, g_v_min]),
        np.array([g_h_max, g_s_max, g_v_max]))

    mask_red = cv2.bitwise_or(
        cv2.inRange(hsv,
            np.array([r_h_min, r_s_min, r_v_min]),
            np.array([r_h_max, r_s_max, r_v_max])),
        cv2.inRange(hsv,
            np.array([179 - r_h_max, r_s_min, r_v_min]),
            np.array([179,           r_s_max, r_v_max]))
    )

    mask_green = cv2.bitwise_and(mask_green, circle_mask)
    mask_red   = cv2.bitwise_and(mask_red,   circle_mask)

    display = frame.copy()
    cv2.circle(display, PIVOT, MASK_RADIUS, (200, 200, 200), 1)
    cv2.circle(display, PIVOT, 8, (0, 215, 255), -1)

    for mask, color, label in [
        (mask_green, (0, 255, 0), "G"),
        (mask_red,   (0, 0, 255), "R"),
    ]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > 30:
                M = cv2.moments(largest)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    cv2.circle(display, (cx, cy), 10, color, 2)
                    cv2.putText(display, label, (cx+12, cy),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            else:
                cv2.putText(display, f"{label}: blob too small",
                           (10, 680), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        else:
            cv2.putText(display, f"{label}: NOT DETECTED",
                       (10, 660 if label == "G" else 680),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    mask_green_bgr = cv2.cvtColor(mask_green, cv2.COLOR_GRAY2BGR)
    mask_red_bgr   = cv2.cvtColor(mask_red,   cv2.COLOR_GRAY2BGR)

    cv2.putText(display,        "ORIGINAL + DETECTION",
               (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
    cv2.putText(mask_green_bgr, "GREEN MASK",
               (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 1)
    cv2.putText(mask_red_bgr,   "RED MASK",
               (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 1)

    w = frame.shape[1] // 3
    h = frame.shape[0]
    return np.hstack([
        cv2.resize(display,        (w, h)),
        cv2.resize(mask_green_bgr, (w, h)),
        cv2.resize(mask_red_bgr,   (w, h)),
    ])


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def main():
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"ERROR: Could not open {VIDEO_PATH}")
        return

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    circle_mask = build_circular_mask((h, w), PIVOT, MASK_RADIUS)
    frame_idx   = START_FRAME

    print(f"Video loaded: {total} frames @ {fps:.2f}fps")
    print("Controls: LEFT/RIGHT=±10  A/D=±1  S=save HSV  Q=quit")

    while True:
        frame_idx = max(0, min(frame_idx, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()

        if not ret:
            frame_idx += 1
            continue

        time_s = frame_idx / fps
        cv2.putText(frame, f"frame {frame_idx}/{total}  t={time_s:.2f}s",
                   (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

        cv2.imshow(WIN, process_frame(frame, circle_mask))

        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == 27:
            break
        elif key == 83 or key == 3:
            frame_idx += 10
        elif key == 81 or key == 2:
            frame_idx -= 10
        elif key == ord('d'):
            frame_idx += 1
        elif key == ord('a'):
            frame_idx -= 1
        elif key == ord(' '):
            try:
                frame_idx = int(input("Jump to frame number: "))
            except ValueError:
                print("Invalid frame number")
        elif key == ord('s'):
            vals = {
                "GREEN_LOWER": (cv2.getTrackbarPos("G  H min", WIN),
                                cv2.getTrackbarPos("G  S min", WIN),
                                cv2.getTrackbarPos("G  V min", WIN)),
                "GREEN_UPPER": (cv2.getTrackbarPos("G  H max", WIN),
                                cv2.getTrackbarPos("G  S max", WIN),
                                cv2.getTrackbarPos("G  V max", WIN)),
                "RED_LOWER_1": (cv2.getTrackbarPos("R  H min", WIN),
                                cv2.getTrackbarPos("R  S min", WIN),
                                cv2.getTrackbarPos("R  V min", WIN)),
                "RED_UPPER_1": (cv2.getTrackbarPos("R  H max", WIN),
                                cv2.getTrackbarPos("R  S max", WIN),
                                cv2.getTrackbarPos("R  V max", WIN)),
            }
            with open(r"C:\dev\chaos\scripts\hsv_values.txt", "w") as f:
                for k, v in vals.items():
                    f.write(f"{k} = np.array({list(v)})\n")
            print("Saved to hsv_values.txt")
            for k, v in vals.items():
                print(f"  {k} = {v}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
