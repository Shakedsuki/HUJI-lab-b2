"""
tag_videos.py
--------------
Interactive tagger for assigning angle-based labels to each video.

For each untagged video:
  1. Shows a navigable frame — find the moment just after release
  2. LEFT  CLICK  on the GREEN marker  → computes theta1
     RIGHT CLICK  on the RED   marker  → computes theta2
  3. Angles are computed automatically from PIVOT + click positions
  4. Confirm with ENTER — saves to experiments.json

No manual angle typing. Angles are measured directly from the frame.

Naming convention written to experiments.json:
  config_description : "th1_p042_th2_m005"
  video_label        : "th1_p042_th2_m005_r2"   (with repeat suffix)
  p = positive, m = negative, zero-padded to 3 digits

Controls (frame window):
  A / D           : +-1 frame
  LEFT/RIGHT      : +-50 frames
  LEFT CLICK      : mark GREEN marker  (sets theta1)
  RIGHT CLICK     : mark RED   marker  (sets theta2)
  R               : reset both markers
  ENTER / SPACE   : confirm and save
  S               : skip this video
  Q / ESC         : quit session

Usage:
  python scripts/tag_videos.py
  python scripts/tag_videos.py --retag
"""

import cv2
import numpy as np
import os
import sys
import json
import glob
import math


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")

PIVOT            = (608, 355)   # fixed wall pivot in original 1280x720 frame
WIN              = "Tag Video  |  L-click=GREEN  R-click=RED  R=reset  ENTER=confirm  S=skip  Q=quit"

RETAG      = "--retag" in sys.argv
LONG_ONLY  = "--long"  in sys.argv   # target only long_recording.mov


# ─────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────

def load_registry():
    if os.path.exists(EXPERIMENTS_FILE):
        with open(EXPERIMENTS_FILE) as f:
            return json.load(f)
    return {}


def save_registry(reg):
    with open(EXPERIMENTS_FILE, 'w') as f:
        json.dump(reg, f, indent=2)


# ─────────────────────────────────────────────
# ANGLE COMPUTATION
# ─────────────────────────────────────────────

def compute_angle(point_from, point_to):
    """
    Angle of vector (from -> to) relative to straight DOWN.
    0 deg = hanging straight down.
    +90 deg = pointing right, -90 deg = pointing left.
    """
    dx = point_to[0] - point_from[0]
    dy = point_to[1] - point_from[1]   # y increases downward
    return math.degrees(math.atan2(dx, dy))


# ─────────────────────────────────────────────
# LABEL HELPERS
# ─────────────────────────────────────────────

def make_label(th1_deg, th2_deg):
    """
    "th1_p042_th2_m005"  from float angles.
    Rounded to nearest integer, p=positive, m=negative, zero-padded to 3.
    """
    def fmt(v):
        sign = 'p' if v >= 0 else 'm'
        return f"{sign}{abs(int(round(v))):03d}"
    return f"th1_{fmt(th1_deg)}_th2_{fmt(th2_deg)}"


def make_video_label(base, repeat):
    return f"{base}_r{repeat}" if repeat > 1 else base


# ─────────────────────────────────────────────
# FRAME TAGGER (interactive window)
# ─────────────────────────────────────────────

class FrameTagger:
    """
    Manages the interactive tagging window state.
    """
    def __init__(self):
        self.green_pos = None   # (x, y) in frame coords
        self.red_pos   = None
        self.frame_raw = None   # current raw frame (unmodified)

    def reset(self):
        self.green_pos = None
        self.red_pos   = None

    @property
    def theta1(self):
        if self.green_pos is None:
            return None
        return compute_angle(PIVOT, self.green_pos)

    @property
    def theta2(self):
        if self.green_pos is None or self.red_pos is None:
            return None
        return compute_angle(self.green_pos, self.red_pos)

    @property
    def both_set(self):
        return self.green_pos is not None and self.red_pos is not None

    def draw(self, frame_idx, total, fps):
        """Build the display frame with overlays."""
        if self.frame_raw is None:
            return None

        display = self.frame_raw.copy()
        t = frame_idx / fps

        # ── Fixed pivot (yellow) ──
        cv2.circle(display, PIVOT, 8, (0, 215, 255), -1, lineType=cv2.LINE_AA)

        # ── Green marker + arm 1 ──
        if self.green_pos:
            cv2.line(display, PIVOT, self.green_pos,
                     (0, 200, 0), 2, lineType=cv2.LINE_AA)
            cv2.circle(display, self.green_pos, 10,
                       (0, 255, 0), 2, lineType=cv2.LINE_AA)
            cv2.circle(display, self.green_pos, 3,
                       (0, 255, 0), -1, lineType=cv2.LINE_AA)
            th1 = self.theta1
            cv2.putText(display, f"th1={th1:+.1f} deg",
                        (self.green_pos[0] + 12, self.green_pos[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1,
                        lineType=cv2.LINE_AA)

        # ── Red marker + arm 2 ──
        if self.red_pos:
            if self.green_pos:
                cv2.line(display, self.green_pos, self.red_pos,
                         (0, 0, 200), 2, lineType=cv2.LINE_AA)
            cv2.circle(display, self.red_pos, 10,
                       (0, 0, 255), 2, lineType=cv2.LINE_AA)
            cv2.circle(display, self.red_pos, 3,
                       (0, 0, 255), -1, lineType=cv2.LINE_AA)
            th2 = self.theta2
            if th2 is not None:
                cv2.putText(display, f"th2={th2:+.1f} deg",
                            (self.red_pos[0] + 12, self.red_pos[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1,
                            lineType=cv2.LINE_AA)

        # ── Status bar ──
        g_status = f"th1={self.theta1:+.1f}" if self.theta1 is not None else "L-click=GREEN"
        r_status = f"th2={self.theta2:+.1f}" if self.theta2 is not None else "R-click=RED"
        ready    = "  >>  ENTER to confirm" if self.both_set else ""

        # ── Status bar at BOTTOM so top of frame is never obscured ──
        bar_y = 720 - 75   # top of the status strip
        overlay = display.copy()
        cv2.rectangle(overlay, (0, bar_y), (1280, 720), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.75, display, 0.25, 0, display)

        cv2.putText(display,
                    f"frame {frame_idx}/{total}   t={t:.2f}s   "
                    f"A/D=+-1   <-/->=+-50   R=reset   S=skip   Q=quit",
                    (10, bar_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                    (180, 180, 180), 1, lineType=cv2.LINE_AA)

        col_g = (0, 255, 0)   if self.green_pos else (120, 120, 120)
        col_r = (80, 80, 255) if self.red_pos   else (120, 120, 120)

        cv2.putText(display, g_status,
                    (10, bar_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    col_g, 1, lineType=cv2.LINE_AA)
        cv2.putText(display, r_status,
                    (300, bar_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    col_r, 1, lineType=cv2.LINE_AA)
        if ready:
            cv2.putText(display, ready,
                        (580, bar_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                        (0, 255, 255), 1, lineType=cv2.LINE_AA)

        return display


def run_tagger(video_path, stem):
    """
    Open the interactive tagging window for one video.

    Returns:
      dict  with theta1, theta2, frame_idx, green_pos, red_pos on confirm
      None  if skipped
      -1    if quit session
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  ERROR: cannot open {video_path}")
        return None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS) or 60.0

    # Start ~2s in — usually after person has set the IC but before release
    frame_idx = min(int(fps * 2), total - 1)

    tagger = FrameTagger()

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1280, 720)

    # ── Mouse callback ──────────────────────────────────────────────────
    def on_mouse(event, x, y, flags, param):
        # Map display coords to frame coords (window may be resized)
        rect = cv2.getWindowImageRect(WIN)
        if rect[2] <= 0 or rect[3] <= 0:
            return
        fx = int((x - rect[0]) * 1280 / rect[2])
        fy = int((y - rect[1]) * 720  / rect[3])
        fx = max(0, min(fx, 1279))
        fy = max(0, min(fy, 719))

        if event == cv2.EVENT_LBUTTONDOWN:
            tagger.green_pos = (fx, fy)
        elif event == cv2.EVENT_RBUTTONDOWN:
            tagger.red_pos = (fx, fy)

        # Redraw immediately
        disp = tagger.draw(frame_idx, total, fps)
        if disp is not None:
            cv2.imshow(WIN, disp)

    cv2.setMouseCallback(WIN, on_mouse)

    result = None

    while True:
        frame_idx = max(0, min(frame_idx, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            frame_idx = max(0, frame_idx - 1)
            continue

        tagger.frame_raw = frame.copy()
        cv2.imshow(WIN, tagger.draw(frame_idx, total, fps))

        key = cv2.waitKey(30) & 0xFF

        if key in (13, 32):           # ENTER / SPACE
            if tagger.both_set:
                result = {
                    "frame_idx":  frame_idx,
                    "theta1":     tagger.theta1,
                    "theta2":     tagger.theta2,
                    "green_pos":  tagger.green_pos,
                    "red_pos":    tagger.red_pos,
                }
                break
            else:
                # Flash a reminder if markers not set
                cv2.putText(tagger.frame_raw,
                            "Click GREEN (L) and RED (R) markers first",
                            (10, 360), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                            (0, 80, 255), 2, lineType=cv2.LINE_AA)
                cv2.imshow(WIN, tagger.frame_raw)

        elif key == ord('r'):         # reset markers
            tagger.reset()

        elif key == ord('s'):         # skip
            result = None
            break

        elif key in (ord('q'), 27):   # quit session
            result = -1
            break

        elif key == ord('d'):
            frame_idx += 1
        elif key == ord('a'):
            frame_idx -= 1
        elif key == 83 or key == 3:   # RIGHT arrow
            frame_idx += 50
        elif key == 81 or key == 2:   # LEFT arrow
            frame_idx -= 50

    cap.release()
    cv2.destroyWindow(WIN)
    return result


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    reg = load_registry()

    all_movs = sorted(glob.glob(os.path.join(VIDEOS_DIR, "*.mov")))

    if LONG_ONLY:
        # Target only the long recording
        videos = [v for v in all_movs
                  if 'long' in os.path.basename(v).lower()]
    else:
        # Normal run — exclude trimmed and long recording
        videos = [
            v for v in all_movs
            if 'trimmed' not in os.path.basename(v).lower()
            and 'long'    not in os.path.basename(v).lower()
        ]

    print(f"Found {len(videos)} videos.")
    print("Controls: LEFT CLICK = green marker   RIGHT CLICK = red marker")
    print("          A/D = +-1 frame   arrows = +-50   ENTER = confirm   S = skip\n")

    tagged  = 0
    skipped = 0
    already = 0

    for video_path in videos:
        stem  = os.path.splitext(os.path.basename(video_path))[0]
        entry = reg.get(stem, {})

        if not RETAG and entry.get("config_description"):
            print(f"  {stem:20s}  already tagged: {entry['config_description']}")
            already += 1
            continue

        print(f"\n{'─'*60}")
        print(f"  {stem}  ({os.path.getsize(video_path)/1e6:.0f} MB)")
        if entry.get("theta1_release"):
            print(f"  Previously tracked: "
                  f"th1={entry['theta1_release']:.1f}  "
                  f"th2={entry['theta2_release']:.1f}")

        result = run_tagger(video_path, stem)

        if result == -1:
            print("\nSession ended. Progress saved.")
            break

        if result is None:
            print(f"  Skipped {stem}")
            skipped += 1
            continue

        th1 = result["theta1"]
        th2 = result["theta2"]
        base  = make_label(th1, th2)

        # Ask for repeat number
        while True:
            raw = input(f"\n  Repeat number for {base}? (1 = first/only): ").strip()
            try:
                repeat = int(raw) if raw else 1
                if repeat >= 1:
                    break
            except ValueError:
                pass
            print("  enter an integer >= 1")

        label = make_video_label(base, repeat)

        # Update registry
        if stem not in reg:
            reg[stem] = {"video_file": os.path.basename(video_path)}

        reg[stem].update({
            "config_description": base,
            "video_label":        label,
            "theta1_measured":    round(th1, 2),
            "theta2_measured":    round(th2, 2),
            "repeat_number":      repeat,
            "tag_frame":          result["frame_idx"],
            "green_click_px":     list(result["green_pos"]),
            "red_click_px":       list(result["red_pos"]),
        })

        save_registry(reg)
        print(f"  Saved: {label}  "
              f"(th1={th1:+.1f} deg,  th2={th2:+.1f} deg)")

        # ── Rename video file ─────────────────────────────────────────
        # Long recording keeps its descriptive name — skip rename
        is_long = 'long' in os.path.basename(video_path).lower()

        if is_long:
            reg[stem]["is_long_recording"] = True
            reg[stem]["video_file"] = os.path.basename(video_path)
            save_registry(reg)
            print(f"  Long recording — keeping original filename")
        else:
            new_filename = label + ".mov"
            new_path     = os.path.join(VIDEOS_DIR, new_filename)

            if os.path.normpath(new_path) == os.path.normpath(video_path):
                print(f"  File already named correctly: {new_filename}")
            elif os.path.exists(new_path):
                print(f"  WARNING: {new_filename} already exists — not renaming.")
                print(f"  Increment the repeat number if this is a different run.")
            else:
                os.rename(video_path, new_path)
                reg[stem]["video_file"] = new_filename
                save_registry(reg)
                print(f"  Renamed: {os.path.basename(video_path)} -> {new_filename}")

        tagged += 1

    print(f"\n{'='*60}")
    print(f"Done.  Tagged: {tagged}   Skipped: {skipped}   Already done: {already}")


if __name__ == "__main__":
    main()
