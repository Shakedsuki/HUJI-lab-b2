"""
pendulum_tracker.py
-------------------
Tracks the two markers on a double pendulum video using OpenCV's built-in
CSRT (Channel and Spatial Reliability Tracking) appearance tracker.

  - GREEN marker : joint between arm 1 and arm 2
  - RED   marker : tip of arm 2

The YELLOW pivot is fixed at (608, 355) — never detected.

Reads/writes data/experiments.json automatically:
  - First run on a video : interactive ROI selection, saves ROIs + ICs to registry
  - Re-run on same video : loads stored ROIs, skips selectROI entirely

Outputs per video:
  data/<stem>_tracking.csv   — one row per frame
  output/<stem>_debug.mp4    — annotated debug video

Usage:
  python scripts/pendulum_tracker.py                         # uses DEFAULT_VIDEO
  python scripts/pendulum_tracker.py Videos/DSC_0139.mov     # any video

Dependencies:
  pip install opencv-contrib-python numpy scipy
"""

import cv2
import numpy as np
import csv
import os
import sys
import json
from scipy.signal import savgol_filter


# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
DEFAULT_VIDEO    = os.path.join(ROOT, r"Videos\DSC_0136.mov")
EXPERIMENTS_FILE = os.path.join(ROOT, r"data\experiments.json")

PIVOT            = (608, 355)
ARM_LENGTH_PX    = 188
ARM_TOLERANCE_PX = 50
MASK_RADIUS      = 376
ARM_LENGTH_CM    = 35.0
SCALE_CM_PER_PX  = 0.186
FPS_DEFAULT      = 59.94

SG_WINDOW        = 11
SG_POLY          = 3


# ─────────────────────────────────────────────
# EXPERIMENTS REGISTRY
# ─────────────────────────────────────────────

def load_registry():
    """Load experiments.json. Returns empty dict if file doesn't exist."""
    if os.path.exists(EXPERIMENTS_FILE):
        with open(EXPERIMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_registry(reg):
    """Save experiments.json with readable formatting."""
    os.makedirs(os.path.dirname(EXPERIMENTS_FILE), exist_ok=True)
    with open(EXPERIMENTS_FILE, 'w') as f:
        json.dump(reg, f, indent=2)
    print(f"Registry updated: {EXPERIMENTS_FILE}")


def update_registry(reg, key, video_file, init_frame, release_frame,
                    green_roi, red_roi, csv_file,
                    th1_rel, th2_rel, om1_rel, om2_rel,
                    n_free, dropout_pct, duration_s,
                    video_fps, existing_entry=None):
    """
    Write or update one entry in the registry.
    Preserves manually set fields (config_description, notes, tracking_quality)
    if an existing entry is passed.
    """
    t0_offset_s = round(release_frame / video_fps, 5)

    # Normalized energy proxy: E ~ om1^2 + om2^2 - 2cos(th1) - cos(th2)
    # (equal masses, equal arm lengths, dimensionless)
    th1r = np.radians(th1_rel); th2r = np.radians(th2_rel)
    om1r = np.radians(om1_rel); om2r = np.radians(om2_rel)
    energy_proxy = round(float(om1r**2 + om2r**2
                               - 2*np.cos(th1r) - np.cos(th2r)), 4)

    entry = {
        "video_file":       os.path.basename(video_file),
        "init_frame":       init_frame,
        "release_frame":    release_frame,
        "green_roi":        list(green_roi),
        "red_roi":          list(red_roi),
        "theta1_release":   round(th1_rel, 4),
        "theta2_release":   round(th2_rel, 4),
        "omega1_release":   round(om1_rel, 4),
        "omega2_release":   round(om2_rel, 4),
        "energy_proxy":     energy_proxy,
        "t0_offset_s":      t0_offset_s,
        "duration_s":       round(duration_s, 3),
        "n_free_frames":    n_free,
        "dropout_rate_pct": round(dropout_pct, 2),
        "arm_length_cm":    ARM_LENGTH_CM,
        "pivot_px":         list(PIVOT),
        "scale_cm_per_px":  SCALE_CM_PER_PX,
        "csv_file":         os.path.basename(csv_file),
        # Preserve manually set fields from existing entry
        "config_description": (existing_entry or {}).get("config_description", ""),
        "tracking_quality":   (existing_entry or {}).get("tracking_quality", "good"),
        "notes":              (existing_entry or {}).get("notes", ""),
    }
    reg[key] = entry
    return entry


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def dist(p1, p2):
    return np.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def compute_angle(point_from, point_to):
    dx = point_to[0] - point_from[0]
    dy = point_to[1] - point_from[1]
    return np.degrees(np.arctan2(dx, dy))


def bbox_centroid(bbox):
    x, y, w, h = bbox
    return (int(x + w/2), int(y + h/2))


def validate_geometry(green_pos, red_pos):
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
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError("Install opencv-contrib-python, not opencv-python")


def draw_dashed_circle(img, center, radius, color, thickness=1, dash_len=10):
    n = max(8, int(2*np.pi*radius/dash_len))
    for i in range(0, n, 2):
        a1 = 360.0*i/n; a2 = 360.0*(i+1)/n
        cv2.ellipse(img, center, (radius,radius), 0, a1, a2, color, thickness)


def extract_ic_from_csv(csv_path, release_frame, video_fps):
    """
    Read the CSV and extract IC values (theta, omega) at the release frame.
    Returns (th1, th2, om1, om2, n_free, dropout_pct, duration_s).
    """
    rows = list(csv.DictReader(open(csv_path)))
    free = [r for r in rows
            if r['phase'] == 'free_swing'
            and r['dropout'] == '0'
            and r['theta1_deg']]

    if not free:
        return 0, 0, 0, 0, 0, 100.0, 0.0

    t   = np.array([float(r['time_s'])     for r in free])
    th1 = np.array([float(r['theta1_deg']) for r in free])
    th2 = np.array([float(r['theta2_deg']) for r in free])
    dt  = np.mean(np.diff(t)) if len(t) > 1 else 1/video_fps

    om1 = savgol_filter(th1, min(SG_WINDOW, len(th1)//2*2+1), SG_POLY,
                        deriv=1, delta=dt)
    om2 = savgol_filter(th2, min(SG_WINDOW, len(th2)//2*2+1), SG_POLY,
                        deriv=1, delta=dt)

    n_free_total  = len([r for r in rows if r['phase'] == 'free_swing'])
    n_dropout     = len([r for r in rows
                         if r['phase'] == 'free_swing' and r['dropout'] == '1'])
    dropout_pct   = 100*n_dropout/n_free_total if n_free_total else 100.0
    duration_s    = float(rows[-1]['time_s']) - float(free[0]['time_s'])

    return (float(th1[0]), float(th2[0]),
            float(om1[0]), float(om2[0]),
            n_free_total, dropout_pct, duration_s)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    # ── Video path from CLI or default ──────────────────────────────────
    video_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    if not os.path.isabs(video_path):
        video_path = os.path.join(ROOT, video_path)
    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return

    stem       = os.path.splitext(os.path.basename(video_path))[0]
    output_csv = os.path.join(ROOT, "data",   f"{stem}_tracking.csv")
    debug_mp4  = os.path.join(ROOT, "output", f"{stem}_debug.mp4")

    print(f"pendulum_tracker.py")
    print(f"Video : {video_path}")
    print(f"CSV   : {output_csv}")

    # ── Load registry ───────────────────────────────────────────────────
    reg            = load_registry()
    existing_entry = reg.get(stem)
    stored_rois    = (existing_entry is not None
                      and existing_entry.get("green_roi") is not None
                      and existing_entry.get("red_roi")   is not None)

    if existing_entry:
        print(f"\nFound existing registry entry for {stem}:")
        print(f"  release_frame = {existing_entry['release_frame']}")
        print(f"  IC: th1={existing_entry['theta1_release']:.2f}  "
              f"th2={existing_entry['theta2_release']:.2f}  "
              f"E={existing_entry['energy_proxy']:.3f}")
        if stored_rois:
            print("  ROIs stored — skipping selectROI")

    # ── Open video ───────────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: could not open video: {video_path}")
        return

    video_fps    = cap.get(cv2.CAP_PROP_FPS) or FPS_DEFAULT
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"\nVideo: {width}x{height} @ {video_fps:.2f}fps, {total_frames} frames")

    # ── Init frame ───────────────────────────────────────────────────────
    if existing_entry:
        init_frame = existing_entry["init_frame"]
        print(f"Init frame loaded from registry: {init_frame}")
    else:
        while True:
            try:
                val = input("\nInit frame (first frame where both markers visible): ").strip()
                init_frame = int(val)
                if 0 <= init_frame < total_frames:
                    break
                print(f"  must be in [0, {total_frames-1}]")
            except ValueError:
                print("  enter an integer")

    cap.set(cv2.CAP_PROP_POS_FRAMES, init_frame)
    ret, init_img = cap.read()
    if not ret:
        print(f"ERROR: could not read frame {init_frame}")
        cap.release()
        return

    # ── ROI selection ────────────────────────────────────────────────────
    if stored_rois:
        green_roi = tuple(existing_entry["green_roi"])
        red_roi   = tuple(existing_entry["red_roi"])
        print(f"ROIs loaded — GREEN {green_roi}  RED {red_roi}")
    else:
        print("\nDraw box around GREEN marker — press ENTER/SPACE to confirm")
        green_roi = cv2.selectROI("Select GREEN", init_img,
                                  fromCenter=False, showCrosshair=True)
        cv2.destroyWindow("Select GREEN")
        if green_roi == (0,0,0,0):
            print("ERROR: no GREEN ROI selected"); cap.release(); return

        print("Draw box around RED marker — press ENTER/SPACE to confirm")
        red_roi = cv2.selectROI("Select RED", init_img,
                                fromCenter=False, showCrosshair=True)
        cv2.destroyWindow("Select RED")
        if red_roi == (0,0,0,0):
            print("ERROR: no RED ROI selected"); cap.release(); return

    # ── Release frame ────────────────────────────────────────────────────
    if existing_entry:
        release_frame = existing_entry["release_frame"]
        print(f"Release frame loaded from registry: {release_frame}")
    else:
        while True:
            try:
                val = input("\nRelease frame (frame where pendulum is let go): ").strip()
                release_frame = int(val)
                if 0 <= release_frame < total_frames:
                    break
                print(f"  must be in [0, {total_frames-1}]")
            except ValueError:
                print("  enter an integer")

    print(f"Release frame: {release_frame}  (t={release_frame/video_fps:.3f}s)")

    # ── Initialize trackers ──────────────────────────────────────────────
    tracker_green = make_csrt()
    tracker_red   = make_csrt()
    tracker_green.init(init_img, green_roi)
    tracker_red.init(init_img,   red_roi)

    # ── Set up outputs ───────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    os.makedirs(os.path.dirname(debug_mp4),  exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(debug_mp4, fourcc, video_fps, (width, height))

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    dropout_total = dropout_holding = dropout_free = 0

    with open(output_csv, 'w', newline='') as csvfile:
        fieldnames = ['frame','time_s','phase',
                      'x_green','y_green','x_red','y_red',
                      'theta1_deg','theta2_deg','dropout']
        wcsv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        wcsv.writeheader()

        for frame_idx in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break

            phase = 'holding' if frame_idx < release_frame else 'free_swing'

            ok_g, bbox_g = tracker_green.update(frame)
            ok_r, bbox_r = tracker_red.update(frame)

            green_pos = bbox_centroid(bbox_g) if ok_g else None
            red_pos   = bbox_centroid(bbox_r) if ok_r else None
            green_pos, red_pos = validate_geometry(green_pos, red_pos)

            dropout = (green_pos is None or red_pos is None)
            if dropout:
                dropout_total += 1
                if phase == 'holding': dropout_holding += 1
                else:                  dropout_free    += 1

            theta1 = compute_angle(PIVOT, green_pos)       if green_pos else None
            theta2 = compute_angle(green_pos, red_pos) \
                     if (green_pos and red_pos) else None

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

            # Debug overlay
            debug = frame.copy()
            draw_dashed_circle(debug, PIVOT, MASK_RADIUS, (255,255,255), 1, 14)
            cv2.circle(debug, PIVOT, 8, (0,215,255), -1)

            phase_col  = (100,255,100) if phase == 'free_swing' else (100,100,255)
            phase_text = "FREE_SWING" if phase == 'free_swing' else "HOLDING"
            cv2.putText(debug, phase_text, (10,55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, phase_col, 2)

            if green_pos:
                cv2.line(debug, PIVOT, green_pos, (0,255,0), 2)
                cv2.circle(debug, green_pos, 8, (0,255,0), -1)
                if theta1 is not None:
                    cv2.putText(debug, f"th1={theta1:.1f}",
                                (green_pos[0]+10, green_pos[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
            if red_pos:
                cv2.circle(debug, red_pos, 8, (0,0,255), -1)
                if green_pos:
                    cv2.line(debug, green_pos, red_pos, (0,0,200), 2)
                if theta2 is not None:
                    cv2.putText(debug, f"th2={theta2:.1f}",
                                (red_pos[0]+10, red_pos[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)

            cv2.putText(debug, f"frame {frame_idx}/{total_frames}  t={time_s:.2f}s",
                        (10,25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
            if dropout:
                cv2.putText(debug, "DROPOUT", (10,85),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            writer.write(debug)

            if frame_idx % 100 == 0:
                print(f"  {frame_idx}/{total_frames} "
                      f"({100*frame_idx//total_frames}%)  "
                      f"dropouts: {dropout_total}", end='\r')

    cap.release()
    writer.release()

    free_n = max(0, total_frames - release_frame)
    def pct(n, d): return f"{100*n/d:.1f}%" if d else "n/a"

    print(f"\nDone. {total_frames} frames.")
    print(f"Dropouts: {dropout_total} total  |  "
          f"holding {pct(dropout_holding, release_frame)}  |  "
          f"free_swing {pct(dropout_free, free_n)}")
    print(f"CSV   : {output_csv}")
    print(f"Debug : {debug_mp4}")

    # ── Extract ICs and update registry ─────────────────────────────────
    print("\nExtracting initial conditions from CSV ...")
    th1r, th2r, om1r, om2r, n_free, d_pct, dur = \
        extract_ic_from_csv(output_csv, release_frame, video_fps)

    print(f"  th1={th1r:.3f}  th2={th2r:.3f}  "
          f"om1={om1r:.3f}  om2={om2r:.3f}")

    reg = load_registry()   # reload in case of concurrent edits
    update_registry(
        reg, stem, video_path,
        init_frame, release_frame,
        green_roi, red_roi, output_csv,
        th1r, th2r, om1r, om2r,
        n_free, d_pct, dur,
        video_fps, existing_entry=reg.get(stem)
    )
    save_registry(reg)


if __name__ == "__main__":
    main()
