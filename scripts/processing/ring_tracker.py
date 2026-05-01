"""
ring_tracker.py
---------------
Robust ring tracker for the wall-mounted double pendulum. Stacks four
weak filters that AND together so each individual filter can be lax:

    motion (median-frame background subtraction)
        AND
    ring (geometric: marker on a circle of fixed arm length)
        AND
    colour (HSV from data/hsv_values.json)
        AND
    angular arc (temporal prediction from previous angle + ω·dt)

If the strict pipeline fails for a frame, we step down a graceful chain:
    1. motion ∩ ring ∩ colour ∩ arc                    (strict)
    2. motion ∩ ring ∩ colour                          (drop arc)
    3. motion ∩ ring ∩ arc                             (drop colour — for blur)
    4. ring ∩ colour                                   (drop motion — static frames)
    5. motion ∩ ring                                   (last resort: pick the
                                                        biggest moving thing
                                                        on the ring)

Why this works for our specific rig:
  * Camera is fixed → background subtraction is reliable.
  * Pendulum is the only moving object → motion mask = pendulum mask.
  * Pivot and arm lengths are known → 1-D ring search instead of 2-D.
  * Free-swing is smooth → previous angle + velocity predicts the next angle
    within a small arc, even at the worst (the pendulum hits maybe 30°/frame
    at 60fps even in the wildest fall).

I/O:
    Reads:   data/hsv_values.json,  data/experiments.json
    Writes:  measurements/<config_description>/tracking.csv
                                            (frame, time_s, phase, x_green,
                                             y_green, x_red, y_red, theta1_deg,
                                             theta2_deg, dropout)
             measurements/<config_description>/debug.mp4
                                            (annotated debug video)
             data/experiments.json          (entry updated, tracker='ring',
                                             measurements_dir set)

Usage:
    python scripts/processing/ring_tracker.py                            # opens a file picker rooted at Videos/
    python scripts/processing/ring_tracker.py Videos/long_recording.mov  # explicit path
    python scripts/processing/ring_tracker.py --browse                   # force the picker even if a path is given
    python scripts/processing/ring_tracker.py Videos/long_recording.mov --no-debug

Sources behind the design choices:
    PyImageSearch ball-tracking (GaussianBlur + erode/dilate + minEnclosingCircle)
    OpenCV background-subtraction tutorial (motion masking on fixed cameras)
    HardwareX double-pendulum paper (centroid via cv2.moments)
"""

import cv2
import numpy as np
import csv
import math
import os
import re
import subprocess
import sys
import json
from scipy.signal import savgol_filter

# Reuse the tracked/pending helpers from scripts/utils/video_status.py
# instead of duplicating them. ring_tracker.py is a script (never imported),
# so a one-shot sys.path insertion is fine. Compute the path relative to
# this file so the import works from any worktree, not just master.
_SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
_UTILS_DIR      = os.path.abspath(os.path.join(_SCRIPT_DIR, os.pardir, "utils"))
HSV_TUNER_PATH  = os.path.join(_SCRIPT_DIR, "hsv_tuner.py")
sys.path.insert(0, _UTILS_DIR)
from video_status import (         # noqa: E402  (after sys.path tweak)
    is_tracked,
    status_summary,
    print_status,
)


# ─────────────────────────────────────────────
# PATHS / CONSTANTS
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
DATA_DIR         = os.path.join(ROOT, "data")
MEASUREMENTS_DIR = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
GLOBAL_HSV_FILE  = os.path.join(DATA_DIR, "hsv_values.json")


def measurements_dir_for(config_description):
    """
    Absolute path to the measurements folder for a given
    config_description. Creates the folder if it doesn't exist.
    Example: measurements_dir_for("th1_p044_th2_m001")
             -> "C:\\dev\\chaos\\measurements\\th1_p044_th2_m001"
    """
    d = os.path.join(MEASUREMENTS_DIR, config_description)
    os.makedirs(d, exist_ok=True)
    return d


def derive_config_description(stem, video_path, existing_entry):
    """
    Resolve the canonical config_description for a tracking run.
    Precedence:
      1. existing_entry["config_description"] when non-empty
      2. video filename stem when it matches th1_[pm]NNN_th2_[pm]NNN[_rN]
      3. fall back to the stem itself (so we always have a folder name)
    """
    if existing_entry:
        cd = existing_entry.get("config_description")
        if cd:
            return cd
    if FILENAME_ANGLE_PATTERN.search(stem):
        return stem
    return stem


def hsv_file_for_video(video_path):
    """
    Per-video HSV file path: data/hsv_<videostem>.json.
    Mirrors the helper of the same name in hsv_tuner.py.
    """
    if not video_path:
        return GLOBAL_HSV_FILE
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(DATA_DIR, f"hsv_{stem}.json")

PIVOT            = (608, 355)
ARM_LENGTH_PX    = 188
ARM_TOLERANCE_PX = 50
ARM_LENGTH_CM    = 35.0
SCALE_CM_PER_PX  = 0.186
FPS_DEFAULT      = 59.94

DEFAULT_RING_TOL = 30
MIN_BLOB_AREA    = 8

# Picker-only: if the video filename encodes initial angles
# (th1_pXXX_th2_pYYY.mov), the picker uses them as a position prior so
# blobs far from the expected marker location are rejected — eliminating
# face/skin false positives at the held-pendulum starting frames.
FILENAME_ANGLE_PATTERN = re.compile(
    r"th1_([pm])(\d+)_th2_([pm])(\d+)", re.IGNORECASE,
)
PICKER_ANCHOR_MAX_DIST = 70   # px tolerance around the expected position


def parse_initial_angles(video_path):
    """
    Parse a filename like 'th1_p180_th2_m045.mov' into (th1_deg, th2_deg).
    'p' = positive, 'm' = negative. Returns None if no match — falls back
    to the unconstrained picker behaviour.
    """
    m = FILENAME_ANGLE_PATTERN.search(os.path.basename(video_path))
    if not m:
        return None
    sign1, deg1, sign2, deg2 = m.groups()
    th1 = float(deg1) * (-1.0 if sign1.lower() == "m" else 1.0)
    th2 = float(deg2) * (-1.0 if sign2.lower() == "m" else 1.0)
    return th1, th2


def expected_marker_positions(th1_deg, th2_deg):
    """
    Convert filename-encoded initial angles into expected pixel positions
    for the green and red markers. Uses the same convention as
    compute_angle (0 = down, +90 = right, ±180 = up).
    """
    g_x = PIVOT[0] + ARM_LENGTH_PX * math.sin(math.radians(th1_deg))
    g_y = PIVOT[1] + ARM_LENGTH_PX * math.cos(math.radians(th1_deg))
    expected_green = (int(round(g_x)), int(round(g_y)))

    r_x = g_x + ARM_LENGTH_PX * math.sin(math.radians(th2_deg))
    r_y = g_y + ARM_LENGTH_PX * math.cos(math.radians(th2_deg))
    expected_red = (int(round(r_x)), int(round(r_y)))
    return expected_green, expected_red

SG_WINDOW = 11
SG_POLY   = 3

# Pre-track HSV adequacy probe — sample N frames evenly, run
# (HSV mask) ∩ (ring) on each, count how often each marker detects.
# Below ADEQUACY_ABORT_PCT we abort and tell the user to re-run hsv_tuner;
# below ADEQUACY_WARN_PCT we warn and proceed. The probe also doubles as
# an inline reminder of which file (per-video vs global) is in use.
ADEQUACY_SAMPLES   = 30
ADEQUACY_WARN_PCT  = 70.0
ADEQUACY_ABORT_PCT = 40.0


def hsv_adequacy_probe(cap, total_frames, hsv_values, ring_tolerance,
                       use_filename_prior, video_path):
    """
    Sample ADEQUACY_SAMPLES frames evenly across the video and report
    how many produce a clean (green AND red, geometry-valid) detection
    using the same HSV+ring pipeline the tracker will use frame-by-frame.

    Returns (verdict, both_pct, green_pct, red_pct), where verdict is
    one of "ABORT", "WARN", "OK". The caller decides what to do.
    """
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pivot_dist, _ = precompute_pivot_grids(width, height, PIVOT)
    pivot_ring    = make_ring_uint8(pivot_dist, ARM_LENGTH_PX, ring_tolerance)

    initial_angles = (parse_initial_angles(video_path)
                      if use_filename_prior else None)
    if initial_angles is not None:
        expected_green, _ = expected_marker_positions(*initial_angles)
    else:
        expected_green = None

    sample_indices = np.linspace(0, total_frames - 1,
                                 min(ADEQUACY_SAMPLES, total_frames),
                                 dtype=int)
    n_total = len(sample_indices)
    n_green = n_red = n_both = 0

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if not ret:
            continue
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        green_color = color_mask_green(hsv, hsv_values["green"])
        green_combined = cv2.bitwise_and(green_color, pivot_ring)
        green_pos = best_blob(
            green_combined,
            anchor=expected_green,
            max_dist=(PICKER_ANCHOR_MAX_DIST if expected_green else None),
        )
        if green_pos is None:
            continue
        n_green += 1

        # Red ring is centred on green.
        local_dist, _ = precompute_pivot_grids(width, height, green_pos)
        red_ring   = make_ring_uint8(local_dist, ARM_LENGTH_PX,
                                     ring_tolerance)
        red_color  = color_mask_red(hsv, hsv_values["red"])
        red_combined = cv2.bitwise_and(red_color, red_ring)
        red_pos = best_blob(red_combined)
        if red_pos is None:
            continue
        n_red += 1

        # Geometric sanity check (same as the tracker uses).
        green_pos_v, red_pos_v = validate_geometry(green_pos, red_pos)
        if green_pos_v is not None and red_pos_v is not None:
            n_both += 1

    both_pct  = 100.0 * n_both  / n_total if n_total else 0.0
    green_pct = 100.0 * n_green / n_total if n_total else 0.0
    red_pct   = 100.0 * n_red   / n_total if n_total else 0.0

    if both_pct < ADEQUACY_ABORT_PCT:
        verdict = "ABORT"
    elif both_pct < ADEQUACY_WARN_PCT:
        verdict = "WARN"
    else:
        verdict = "OK"

    return verdict, both_pct, green_pct, red_pct

# Tuning knobs ────────────────────────────────
BG_SAMPLES        = 60       # frames sampled for the median background
BG_DIFF_THRESH    = 22       # grayscale |frame - bg| threshold
GAUSS_KSIZE       = (5, 5)   # blur applied before everything

# Arc filter (degrees)
ARC_HALF_BASE     = 25.0     # half-width when ω = 0
ARC_OMEGA_FACTOR  = 1.5      # widens with |ω|·dt

# Angular velocity smoothing
EMA_ALPHA         = 0.5
MAX_OMEGA_DEG_S   = 3500.0   # safety cap on ω estimate (3500 deg/s ~ 60 deg/frame@60fps)

# Blob shape gates (px)
MIN_BLOB_RADIUS   = 2.5
MAX_BLOB_RADIUS   = 35.0

# Anchor proximity gates for the riskier fallback stages. Without these
# the no-colour and ring+motion fallbacks can latch onto a chunk of arm
# shaft that happens to lie on the ring; gating by distance to the
# predicted anchor prevents the silent false positives that show up
# downstream as |ω| spikes.
MAX_DIST_NO_COLOUR   = 35.0    # stage 3: motion ∩ ring ∩ arc
MAX_DIST_RING_MOTION = 25.0    # stage 5: motion ∩ ring (last resort)

# Strict-physics mode (--strict-physics or active inside the post-seed
# window). Applies an angular gate to every fallback stage and refuses
# to fall through to a weaker detection when the gate fails — the row
# becomes dropout=1 instead. The gate width scales with the predictor's
# current ω so it doesn't lock the tracker out during real chaotic
# bursts.
STRICT_ARC_BASE_DEG    = 25.0
STRICT_ARC_OMEGA_K     = 1.5    # gate radius = base + k * |ω| * dt
STRICT_POST_SEED_FRAMES = 30    # how many frames to keep strict mode on after a seed
STRICT_PIXEL_FLOOR_PX  = 18.0   # pixel-distance gate floor for slow / sleeping predictor


# ─────────────────────────────────────────────
# REGISTRY I/O  (mirrors ring_tracker.py)
# ─────────────────────────────────────────────

def load_registry():
    if os.path.exists(EXPERIMENTS_FILE):
        with open(EXPERIMENTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_registry(reg):
    os.makedirs(os.path.dirname(EXPERIMENTS_FILE), exist_ok=True)
    with open(EXPERIMENTS_FILE, "w") as f:
        json.dump(reg, f, indent=2)
    print(f"Registry updated: {EXPERIMENTS_FILE}")


def update_registry(reg, key, video_file, init_frame, release_frame,
                    config_description, ring_tolerance,
                    th1_rel, th2_rel, om1_rel, om2_rel,
                    n_free, dropout_pct, duration_s,
                    video_fps, existing_entry=None):
    t0_offset_s = round(release_frame / video_fps, 5)
    th1r = np.radians(th1_rel); th2r = np.radians(th2_rel)
    om1r = np.radians(om1_rel); om2r = np.radians(om2_rel)
    energy_proxy = round(float(om1r**2 + om2r**2
                               - 2 * np.cos(th1r) - np.cos(th2r)), 4)

    # Preserve any caller-supplied fields that aren't computed here
    # (theta1_measured, theta2_measured, repeat_number, video_label,
    # tag_frame, green_click_px, red_click_px). They're set by other
    # tools (ring_picker, manual editing) and shouldn't be lost.
    base = dict(existing_entry) if existing_entry else {}

    base.update({
        "video_file":         os.path.basename(video_file),
        "init_frame":         init_frame,
        "release_frame":      release_frame,
        "green_roi":          None,
        "red_roi":            None,
        "tracker":            "ring",
        "arm_length_px":      ARM_LENGTH_PX,
        "ring_tolerance":     ring_tolerance,
        "theta1_release":     round(th1_rel, 4),
        "theta2_release":     round(th2_rel, 4),
        "omega1_release":     round(om1_rel, 4),
        "omega2_release":     round(om2_rel, 4),
        "energy_proxy":       energy_proxy,
        "t0_offset_s":        t0_offset_s,
        "duration_s":         round(duration_s, 3),
        "n_free_frames":      n_free,
        "dropout_rate_pct":   round(dropout_pct, 2),
        "arm_length_cm":      ARM_LENGTH_CM,
        "pivot_px":           list(PIVOT),
        "scale_cm_per_px":    SCALE_CM_PER_PX,
        "csv_file":           "tracking.csv",
        "measurements_dir":   f"measurements/{config_description}",
        "config_description": config_description,
        "tracking_quality":   base.get("tracking_quality", "good"),
        "notes":              base.get("notes", ""),
    })
    reg[key] = base
    return base


# ─────────────────────────────────────────────
# GEOMETRY HELPERS
# ─────────────────────────────────────────────

def strict_pixel_radius(predictor, dt):
    """
    Pixel-distance gate radius for strict-physics mode.

    Angular budget = STRICT_ARC_BASE_DEG + STRICT_ARC_OMEGA_K * |ω| * dt
    Convert to arc length on the arm-length ring: r_px ≈ ARM_LENGTH_PX *
    radians(angular_budget). Falls back to a pixel-floor when the
    predictor isn't yet alive (no ω estimate yet).
    """
    if not predictor.alive:
        return STRICT_PIXEL_FLOOR_PX
    angle_budget = (STRICT_ARC_BASE_DEG +
                    STRICT_ARC_OMEGA_K * abs(predictor.omega) * dt)
    return max(STRICT_PIXEL_FLOOR_PX,
               ARM_LENGTH_PX * np.radians(angle_budget))


def load_seeds(path):
    """
    Load a seeds.json file: returns dict {frame_idx -> seed_record}.
    Returns {} if the file doesn't exist or is malformed.

    seeds.json schema:
      {"seeds":
        [{"frame": 130, "green_xy":[722, 470], "red_xy":[810, 580]},
         ...],
       "strict_physics_window": 30,
       "notes": "..."}
    """
    if not path or not os.path.exists(path):
        return {}, None
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARN: could not load seeds.json ({e}); ignoring.")
        return {}, None

    by_frame = {}
    for s in data.get("seeds", []):
        try:
            frame = int(s["frame"])
            green_xy = tuple(int(v) for v in s["green_xy"]) if s.get("green_xy") else None
            red_xy   = tuple(int(v) for v in s["red_xy"])   if s.get("red_xy")   else None
        except (KeyError, ValueError, TypeError):
            continue
        by_frame[frame] = {"green_xy": green_xy, "red_xy": red_xy}
    return by_frame, data


def euclid(p1, p2):
    return float(np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2))


def compute_angle(p_from, p_to):
    """0° = straight down; +90 = right, -90 = left, ±180 = up."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return float(np.degrees(np.arctan2(dx, dy)))


def angular_diff(a, b):
    """Signed (a − b) wrapped to [-180, 180]."""
    return ((a - b + 180.0) % 360.0) - 180.0


def draw_dashed_circle(img, center, radius, color, thickness=1, dash_len=10):
    n = max(8, int(2 * np.pi * radius / dash_len))
    for i in range(0, n, 2):
        a1 = 360.0 * i / n
        a2 = 360.0 * (i + 1) / n
        cv2.ellipse(img, center, (radius, radius), 0, a1, a2, color, thickness)


def validate_geometry(green_pos, red_pos):
    if green_pos is not None:
        if abs(euclid(PIVOT, green_pos) - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            green_pos = None
    if red_pos is not None and green_pos is not None:
        if abs(euclid(green_pos, red_pos) - ARM_LENGTH_PX) > ARM_TOLERANCE_PX:
            red_pos = None
    elif green_pos is None:
        red_pos = None
    return green_pos, red_pos


# ─────────────────────────────────────────────
# HSV LOADING + MASKS
# ─────────────────────────────────────────────

def load_hsv_values(video_path=None):
    """
    Load HSV calibration. Tries the per-video file first
    (data/hsv_<videostem>.json), falling back to the global
    data/hsv_values.json. Returns the dict and the path it loaded from
    (so the caller can print it). Aborts if neither file exists.
    """
    candidates = []
    if video_path:
        candidates.append(hsv_file_for_video(video_path))
    candidates.append(GLOBAL_HSV_FILE)

    for path in candidates:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            for k in ("green", "red"):
                if k not in data:
                    print(f"ERROR: {path} is missing '{k}' section")
                    sys.exit(1)
            data["red"].setdefault("h_min2", 170)
            data["red"].setdefault("h_max2", 180)
            data.setdefault("ring_tolerance", DEFAULT_RING_TOL)
            data["_hsv_path"] = path           # so the caller can report it
            return data

    print("ERROR: no HSV calibration found.")
    print(f"  Tried: {', '.join(candidates)}")
    print("Run scripts/processing/hsv_tuner.py to calibrate marker colours.")
    sys.exit(1)


def color_mask_green(hsv, cfg):
    lo = np.array([cfg["h_min"], cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi = np.array([cfg["h_max"], cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    return cv2.inRange(hsv, lo, hi)


def color_mask_red(hsv, cfg):
    lo1 = np.array([cfg["h_min"],  cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi1 = np.array([cfg["h_max"],  cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    lo2 = np.array([cfg["h_min2"], cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi2 = np.array([cfg["h_max2"], cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    m1 = cv2.inRange(hsv, lo1, hi1)
    m2 = cv2.inRange(hsv, lo2, hi2)
    return cv2.bitwise_or(m1, m2)


# ─────────────────────────────────────────────
# STATIC BACKGROUND VIA TEMPORAL MEDIAN
# ─────────────────────────────────────────────

def compute_static_background(cap, total_frames, n_samples=BG_SAMPLES):
    """
    Sample n_samples frames evenly across the video and take the per-pixel
    median. Because the pendulum is in a different position in most samples,
    the median converges to the static wall — no need for a "no-pendulum"
    calibration video.
    """
    n_samples = max(15, min(n_samples, total_frames))
    sample_indices = np.linspace(0, total_frames - 1, n_samples, dtype=int)
    print(f"\nBuilding static background from {n_samples} sampled frames ...")

    samples = []
    for i, idx in enumerate(sample_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret:
            samples.append(frame)
        if (i + 1) % 10 == 0:
            print(f"  sampled {i + 1}/{n_samples}", end="\r")

    if not samples:
        raise RuntimeError("Could not read any frames for background.")

    stack = np.stack(samples, axis=0)
    bg = np.median(stack, axis=0).astype(np.uint8)
    bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    print(f"\nStatic background ready ({bg.shape[1]}x{bg.shape[0]}).")
    return bg, bg_gray


def motion_mask(frame_blurred, bg_gray, threshold=BG_DIFF_THRESH):
    """
    Grayscale absolute difference vs the static background, thresholded,
    then opened to kill speckle. uint8 0/255.
    """
    gray = cv2.cvtColor(frame_blurred, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray, bg_gray)
    _, fg = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
    return fg


# ─────────────────────────────────────────────
# RING + ARC MASKS
# ─────────────────────────────────────────────

def precompute_pivot_grids(width, height, center):
    """
    Return (dist_grid, angle_grid).
      dist_grid  : float32 (h, w) — Euclidean distance from each pixel to center
      angle_grid : float32 (h, w) — angle in our convention (0=down, +90=right)
    Computed once per static center; for the green ring the pivot is fixed
    so we reuse this every frame.
    """
    ys, xs = np.indices((height, width), dtype=np.float32)
    dx = xs - center[0]
    dy = ys - center[1]
    dist_grid  = np.sqrt(dx * dx + dy * dy)
    angle_grid = np.degrees(np.arctan2(dx, dy))
    return dist_grid, angle_grid


def make_ring_uint8(dist_grid, radius, tolerance):
    return ((np.abs(dist_grid - radius) < tolerance).astype(np.uint8)) * 255


def make_arc_uint8(angle_grid, theta_pred_deg, half_width_deg):
    """Pixels whose grid-angle is within ±half_width of theta_pred (mod 360)."""
    diff = ((angle_grid - theta_pred_deg + 180.0) % 360.0) - 180.0
    return ((np.abs(diff) < half_width_deg).astype(np.uint8)) * 255


# ─────────────────────────────────────────────
# BLOB SCORING
# ─────────────────────────────────────────────

def best_blob(mask, anchor=None, max_dist=None,
              min_area=MIN_BLOB_AREA,
              min_radius=MIN_BLOB_RADIUS,
              max_radius=MAX_BLOB_RADIUS):
    """
    Return centroid of the best blob in `mask` or None.

    `anchor`   (x, y) — when given, the score is area / (1 + dist_to_anchor)
                        so we prefer blobs near a predicted location.
                        When None, biggest wins.
    `max_dist` px     — when given (and `anchor` is also given), reject any
                        candidate farther than this from the anchor. Used in
                        the riskier fallback stages (no-colour, ring+motion)
                        to prevent the tracker from latching onto a chunk of
                        arm shaft far from the predicted marker location.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = None
    best_score = -1.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        (_, _), r = cv2.minEnclosingCircle(c)
        if r < min_radius or r > max_radius:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]

        if anchor is None:
            score = area
        else:
            d = float(np.hypot(cx - anchor[0], cy - anchor[1]))
            if max_dist is not None and d > max_dist:
                continue
            score = area / (1.0 + d)

        if score > best_score:
            best_score = score
            best = (int(round(cx)), int(round(cy)))
    return best


# ─────────────────────────────────────────────
# ANGULAR PREDICTOR (Kalman-lite)
# ─────────────────────────────────────────────

class AngularPredictor:
    """
    Tracks an unwrapped cumulative angle (degrees) and angular velocity
    (deg/s). Velocity is EMA-smoothed and clipped to MAX_OMEGA_DEG_S.

    Public interface:
        predict(dt)        → predicted angle (unwrapped) for next frame, or None
        observe(theta, dt) → fold a new measurement into the state
        coast(dt)          → no measurement available; advance by ω·dt
        wrapped()          → predicted angle wrapped to [-180, 180], or None
    """

    def __init__(self):
        self.theta_acc = None
        self.omega     = 0.0
        self.alive     = False

    def predict(self, dt):
        if not self.alive:
            return None
        return self.theta_acc + self.omega * dt

    def wrapped_predict(self, dt):
        p = self.predict(dt)
        if p is None:
            return None
        return ((p + 180.0) % 360.0) - 180.0

    def observe(self, theta_obs_deg, dt):
        if not self.alive:
            self.theta_acc = float(theta_obs_deg)
            self.omega     = 0.0
            self.alive     = True
            return
        # Unwrap obs against current prediction so ω doesn't jump 360°/frame.
        pred  = self.theta_acc + self.omega * dt
        delta = ((theta_obs_deg - pred + 180.0) % 360.0) - 180.0
        new_theta = pred + delta

        omega_raw = (new_theta - self.theta_acc) / dt
        omega_raw = float(np.clip(omega_raw,
                                  -MAX_OMEGA_DEG_S, MAX_OMEGA_DEG_S))
        self.omega     = EMA_ALPHA * omega_raw + (1 - EMA_ALPHA) * self.omega
        self.theta_acc = new_theta

    def coast(self, dt):
        if self.alive:
            self.theta_acc += self.omega * dt
            # Keep ω as-is — it's our best guess until a fresh measurement.

    def arc_half_width(self, dt):
        return ARC_HALF_BASE + ARC_OMEGA_FACTOR * abs(self.omega) * dt


# ─────────────────────────────────────────────
# DETECTION CHAIN — GREEN
# ─────────────────────────────────────────────

def detect_green(hsv_blurred, fg_mask,
                 pivot_ring_uint8, pivot_angle_grid,
                 hsv_values, predictor, dt, strict=False):
    """
    Try the strict pipeline first, then fall back through progressively
    looser combinations. Returns (green_pos, used_fallback_str).

    When `strict=True`, every fallback stage is anchor-gated by
    `strict_pixel_radius(predictor, dt)` and the chain refuses to
    return a candidate that's outside the gate. If no stage produces an
    in-gate candidate, returns (None, "fail-strict") so the caller
    records dropout=1 instead of accepting an unphysical jump.
    """
    color_mask = color_mask_green(hsv_blurred, hsv_values["green"])

    # Build masks once.
    ring_color  = cv2.bitwise_and(pivot_ring_uint8, color_mask)
    ring_motion = cv2.bitwise_and(pivot_ring_uint8, fg_mask)

    # Predicted angle / arc.
    pred = predictor.wrapped_predict(dt)
    if pred is not None:
        arc = make_arc_uint8(pivot_angle_grid, pred,
                             predictor.arc_half_width(dt))
        ring_arc = cv2.bitwise_and(pivot_ring_uint8, arc)
        anchor = (int(round(PIVOT[0] + ARM_LENGTH_PX
                             * np.sin(np.radians(pred)))),
                  int(round(PIVOT[1] + ARM_LENGTH_PX
                             * np.cos(np.radians(pred)))))
    else:
        ring_arc = None
        anchor   = None

    # Strict-physics gate: a single max-distance applied to every stage.
    # Use it as max_dist for stages that don't already have a tighter one.
    strict_max = strict_pixel_radius(predictor, dt) if strict else None

    def gate(default):
        """Pick the tighter of the strict gate and a stage's own gate."""
        if strict_max is None:
            return default
        if default is None:
            return strict_max
        return min(default, strict_max)

    # Strict 1: ring ∩ motion ∩ colour ∩ arc
    if ring_arc is not None:
        m = cv2.bitwise_and(cv2.bitwise_and(ring_motion, color_mask), ring_arc)
        pos = best_blob(m, anchor=anchor, max_dist=gate(None))
        if pos is not None:
            return pos, "strict"

    # 2: ring ∩ motion ∩ colour
    m = cv2.bitwise_and(ring_motion, color_mask)
    pos = best_blob(m, anchor=anchor, max_dist=gate(None))
    if pos is not None:
        return pos, "no-arc"

    # 3: ring ∩ motion ∩ arc  (drop colour — typical motion-blur recovery)
    # Gate by anchor distance so we don't latch onto a chunk of arm shaft
    # that happens to lie on the ring far from the predicted angle.
    if ring_arc is not None and anchor is not None:
        m = cv2.bitwise_and(ring_motion, ring_arc)
        pos = best_blob(m, anchor=anchor, max_dist=gate(MAX_DIST_NO_COLOUR))
        if pos is not None:
            return pos, "no-colour"

    # 4: ring ∩ colour  (drop motion — useful while pendulum is held still)
    m = ring_color
    pos = best_blob(m, anchor=anchor, max_dist=gate(None))
    if pos is not None:
        return pos, "no-motion"

    # 5: ring ∩ motion  (last resort — any moving thing on the ring).
    # Tightest anchor gate of the chain; without it this branch is the
    # main source of silent false positives.
    if anchor is not None:
        pos = best_blob(ring_motion, anchor=anchor,
                        max_dist=gate(MAX_DIST_RING_MOTION))
        if pos is not None:
            return pos, "ring+motion"

    return None, "fail-strict" if strict else "fail"


def detect_red(hsv_blurred, fg_mask, frame_shape,
               green_pos, ring_tolerance,
               hsv_values, predictor, dt, strict=False):
    """
    Same fallback chain as green, but the ring is centred on green_pos and
    must be built per-frame. We restrict the heavy distance/angle math to
    a bounding box around green_pos to keep this fast.

    `strict` is the same hard-gate flag as detect_green: each stage gets
    capped by strict_pixel_radius, and the chain returns None instead of
    falling through when the gate fails on every stage.
    """
    if green_pos is None:
        return None, "skip-no-green"

    h, w = frame_shape[:2]
    color_mask = color_mask_red(hsv_blurred, hsv_values["red"])

    # ── Local ring + angle grids restricted to a bounding box ──
    pad = ARM_LENGTH_PX + ring_tolerance + 10
    x0 = max(0, green_pos[0] - pad)
    y0 = max(0, green_pos[1] - pad)
    x1 = min(w, green_pos[0] + pad + 1)
    y1 = min(h, green_pos[1] + pad + 1)

    ys, xs = np.indices((y1 - y0, x1 - x0), dtype=np.float32)
    dx_local = xs - (green_pos[0] - x0)
    dy_local = ys - (green_pos[1] - y0)
    dist_local  = np.sqrt(dx_local * dx_local + dy_local * dy_local)
    angle_local = np.degrees(np.arctan2(dx_local, dy_local))

    ring_local = ((np.abs(dist_local - ARM_LENGTH_PX) < ring_tolerance)
                  .astype(np.uint8)) * 255

    # Lift the local ring back into a full-frame mask so the rest of the
    # pipeline doesn't have to know about the bounding box.
    ring_full = np.zeros((h, w), dtype=np.uint8)
    ring_full[y0:y1, x0:x1] = ring_local

    ring_color  = cv2.bitwise_and(ring_full, color_mask)
    ring_motion = cv2.bitwise_and(ring_full, fg_mask)

    pred = predictor.wrapped_predict(dt)
    if pred is not None:
        arc_local = ((np.abs(((angle_local - pred + 180.0) % 360.0) - 180.0)
                      < predictor.arc_half_width(dt)).astype(np.uint8)) * 255
        ring_arc = np.zeros((h, w), dtype=np.uint8)
        ring_arc[y0:y1, x0:x1] = cv2.bitwise_and(ring_local, arc_local)
        anchor = (int(round(green_pos[0] + ARM_LENGTH_PX
                             * np.sin(np.radians(pred)))),
                  int(round(green_pos[1] + ARM_LENGTH_PX
                             * np.cos(np.radians(pred)))))
    else:
        ring_arc = None
        anchor   = None

    strict_max = strict_pixel_radius(predictor, dt) if strict else None

    def gate(default):
        if strict_max is None:
            return default
        if default is None:
            return strict_max
        return min(default, strict_max)

    # Strict 1
    if ring_arc is not None:
        m = cv2.bitwise_and(cv2.bitwise_and(ring_motion, color_mask), ring_arc)
        pos = best_blob(m, anchor=anchor, max_dist=gate(None))
        if pos is not None:
            return pos, "strict"

    # 2
    m = cv2.bitwise_and(ring_motion, color_mask)
    pos = best_blob(m, anchor=anchor, max_dist=gate(None))
    if pos is not None:
        return pos, "no-arc"

    # 3 — drop colour. Tighten with anchor gate to prevent arm-shaft latch.
    if ring_arc is not None and anchor is not None:
        m = cv2.bitwise_and(ring_motion, ring_arc)
        pos = best_blob(m, anchor=anchor, max_dist=gate(MAX_DIST_NO_COLOUR))
        if pos is not None:
            return pos, "no-colour"

    # 4 — drop motion (static frames during holding).
    pos = best_blob(ring_color, anchor=anchor, max_dist=gate(None))
    if pos is not None:
        return pos, "no-motion"

    # 5 — last resort, motion ∩ ring only. Tightest anchor gate.
    if anchor is not None:
        pos = best_blob(ring_motion, anchor=anchor,
                        max_dist=gate(MAX_DIST_RING_MOTION))
        if pos is not None:
            return pos, "ring+motion"

    return None, "fail-strict" if strict else "fail"


# ─────────────────────────────────────────────
# IC EXTRACTION
# ─────────────────────────────────────────────

def extract_ic_from_csv(csv_path, release_frame, video_fps):
    rows = list(csv.DictReader(open(csv_path)))
    free = [r for r in rows
            if r["phase"] == "free_swing"
            and r["dropout"] == "0"
            and r["theta1_deg"]]

    if not free:
        return 0, 0, 0, 0, 0, 100.0, 0.0

    t   = np.array([float(r["time_s"])     for r in free])
    th1 = np.array([float(r["theta1_deg"]) for r in free])
    th2 = np.array([float(r["theta2_deg"]) for r in free])
    dt  = np.mean(np.diff(t)) if len(t) > 1 else 1.0 / video_fps

    win = min(SG_WINDOW, len(th1) // 2 * 2 + 1)
    if win > len(th1) or win <= SG_POLY:
        om1 = np.gradient(th1, dt)
        om2 = np.gradient(th2, dt)
    else:
        om1 = savgol_filter(th1, win, SG_POLY, deriv=1, delta=dt)
        om2 = savgol_filter(th2, win, SG_POLY, deriv=1, delta=dt)

    n_free_total = len([r for r in rows if r["phase"] == "free_swing"])
    n_dropout    = len([r for r in rows
                        if r["phase"] == "free_swing" and r["dropout"] == "1"])
    dropout_pct  = 100 * n_dropout / n_free_total if n_free_total else 100.0
    duration_s   = float(rows[-1]["time_s"]) - float(free[0]["time_s"])

    return (float(th1[0]), float(th2[0]),
            float(om1[0]), float(om2[0]),
            n_free_total, dropout_pct, duration_s)


# ─────────────────────────────────────────────
# VIDEO PICKER
# ─────────────────────────────────────────────

def pick_video_interactive():
    """
    Open a Tk file dialog rooted at Videos/. Returns the chosen absolute
    path or None if the user cancelled. Falls back gracefully (returns
    None with a printed hint) on systems where Tk isn't available.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter is not available — pass a video path on the command line.")
        return None

    initialdir = VIDEOS_DIR if os.path.isdir(VIDEOS_DIR) else ROOT

    root = tk.Tk()
    root.withdraw()                      # hide the empty Tk root window
    try:
        root.attributes("-topmost", True)   # bring the dialog to the front
    except tk.TclError:
        pass
    chosen = filedialog.askopenfilename(
        parent=root,
        title="Select pendulum video to track",
        initialdir=initialdir,
        filetypes=[
            ("Video files", "*.mov *.mp4 *.avi *.mkv *.m4v"),
            ("All files",   "*.*"),
        ],
    )
    root.destroy()
    return chosen if chosen else None


# ─────────────────────────────────────────────
# SMART INIT/RELEASE FRAME SUGGESTIONS
# ─────────────────────────────────────────────

def suggest_frame_candidates(video_path, total_frames, hsv_values,
                             ring_tolerance, use_filename_prior,
                             tag_frame_hint=None,
                             scan_step=3, max_scan=400):
    """
    Walk forward from frame 0 (or near tag_frame_hint, if provided) and
    return suggested (init_frame, release_frame).

    init_frame: first frame where green AND red both detect cleanly with
                the filename position prior (the picker pre-positions to
                this).

    release_frame: first frame after init where green's between-frame
                pixel motion exceeds RELEASE_MOTION_PX_THRESHOLD,
                signalling the user has let go of the pendulum.

    Returns (init_suggestion, release_suggestion) — either may be None if
    the scan couldn't find a candidate within `max_scan` evaluated frames.
    The scan is sparse (every `scan_step`th frame) for speed. The picker
    can refine from the suggestion.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, None
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pivot_dist, _ = precompute_pivot_grids(width, height, PIVOT)
    pivot_ring    = make_ring_uint8(pivot_dist, ARM_LENGTH_PX, ring_tolerance)

    initial_angles = (parse_initial_angles(video_path)
                      if use_filename_prior else None)
    expected_green = (expected_marker_positions(*initial_angles)[0]
                      if initial_angles else None)

    # Search anchor: start near tag_frame_hint when provided so we don't
    # waste cycles on the inevitable pre-tag dropout window.
    if tag_frame_hint is not None:
        start_search = max(0, int(tag_frame_hint) - 30)
    else:
        start_search = 0
    end_search = min(total_frames, start_search + max_scan)

    init_suggestion = None
    last_green_pos  = None

    # Phase 1: find init candidate — first cleanly-detected green+red pair.
    for idx in range(start_search, end_search, scan_step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        green_color = color_mask_green(hsv, hsv_values["green"])
        green_combined = cv2.bitwise_and(green_color, pivot_ring)
        green_pos = best_blob(
            green_combined,
            anchor=expected_green,
            max_dist=(PICKER_ANCHOR_MAX_DIST if expected_green else None),
        )
        if green_pos is None:
            continue

        local_dist, _ = precompute_pivot_grids(width, height, green_pos)
        red_ring  = make_ring_uint8(local_dist, ARM_LENGTH_PX, ring_tolerance)
        red_color = color_mask_red(hsv, hsv_values["red"])
        red_pos   = best_blob(cv2.bitwise_and(red_color, red_ring))
        green_pos_v, red_pos_v = validate_geometry(green_pos, red_pos)
        if green_pos_v is None or red_pos_v is None:
            continue

        init_suggestion = idx
        last_green_pos  = green_pos_v
        break

    # Phase 2: find release candidate — first frame where green's
    # between-frame pixel motion exceeds the threshold. We compare green
    # positions at coarse intervals; once motion is detected, refine to
    # the exact crossing frame.
    RELEASE_MOTION_PX_THRESHOLD = 4.0   # green moves ~4 px between scan steps
    release_suggestion = None
    if init_suggestion is not None and last_green_pos is not None:
        prev_pos = last_green_pos
        prev_idx = init_suggestion
        for idx in range(init_suggestion + scan_step,
                          min(total_frames, init_suggestion + 600),
                          scan_step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            green_color = color_mask_green(hsv, hsv_values["green"])
            green_combined = cv2.bitwise_and(green_color, pivot_ring)
            green_pos = best_blob(
                green_combined,
                anchor=prev_pos,
                max_dist=PICKER_ANCHOR_MAX_DIST,
            )
            if green_pos is None:
                continue
            d = float(np.hypot(green_pos[0] - prev_pos[0],
                               green_pos[1] - prev_pos[1]))
            if d > RELEASE_MOTION_PX_THRESHOLD:
                # Motion crossed the threshold sometime between prev_idx
                # and idx. The first "moving" frame is ≥ prev_idx+1; we
                # report prev_idx (the last clearly-static frame), so the
                # picker pre-positions just before motion starts.
                release_suggestion = prev_idx
                break
            prev_pos = green_pos
            prev_idx = idx

    cap.release()
    return init_suggestion, release_suggestion


# ─────────────────────────────────────────────
# VISUAL FRAME PICKER  (init_frame / release_frame)
# ─────────────────────────────────────────────

def pick_frame_interactive(video_path, label, fps, total_frames,
                           hsv_values, ring_tolerance, start_frame=0,
                           use_filename_prior=True):
    """
    Open a navigable cv2 window to pick a single frame from `video_path`.
    Live HSV detection (ring ∩ colour, no motion mask) is overlaid on each
    frame, so the picker doubles as the HSV-adequacy check: if the markers
    don't light up while you scrub, the calibration is stale.

    Keys:
        a / d        ±1 frame
        A / D        ±10 frames
        z / x        ±100 frames
        ENTER        confirm
        ESC          cancel

    Returns the chosen frame index, or None if the user cancels.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  WARN: couldn't open {video_path} for the frame picker")
        return None

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    pivot_dist, _ = precompute_pivot_grids(width, height, PIVOT)
    pivot_ring    = make_ring_uint8(pivot_dist, ARM_LENGTH_PX, ring_tolerance)

    # ── Filename position prior ──
    # If the video filename encodes its initial angles (th1_pXXX_th2_pYYY),
    # use them as anchors so blobs far from the expected marker positions
    # are rejected. This is what fixes the "red mask matches the user's
    # face" failure on inverted-start clips: the face is far from where
    # the red sticker is supposed to be at frame 0, even though it sits
    # on the search ring around green.
    initial_angles = (parse_initial_angles(video_path)
                      if use_filename_prior else None)
    if initial_angles is not None:
        expected_green, expected_red = expected_marker_positions(*initial_angles)
        prior_status = (f"prior: th1={initial_angles[0]:+.0f}  "
                        f"th2={initial_angles[1]:+.0f}  "
                        f"(blobs > {PICKER_ANCHOR_MAX_DIST}px from expected rejected)")
    else:
        expected_green = expected_red = None
        prior_status   = "no filename prior — pure HSV+ring matching"

    # Plain ASCII dash — em-dash mojibakes to "â€"" through cv2's window
    # title encoding on Windows.
    win_title = f"Pick {label} - {os.path.basename(video_path)}"
    cv2.namedWindow(win_title, cv2.WINDOW_AUTOSIZE)

    DISP_W, DISP_H = 960, 540

    idx       = max(0, min(total_frames - 1, start_frame))
    last_idx  = -1
    cached    = None
    chosen    = None

    while True:
        # Re-decode only when the index changes.
        if idx != last_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                idx = max(0, min(total_frames - 1, idx - 1))
                continue
            cached   = frame
            last_idx = idx

        frame = cached.copy()

        # ── Live HSV detection (ring + colour, no motion mask) ──
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        green_color    = color_mask_green(hsv, hsv_values["green"])
        green_combined = cv2.bitwise_and(green_color, pivot_ring)
        green_pos      = best_blob(
            green_combined,
            anchor=expected_green,
            max_dist=(PICKER_ANCHOR_MAX_DIST if expected_green else None),
        )

        # If anchored detection found nothing, try unanchored as a hint
        # that the prior is wrong (e.g. wrong frame, or rig moved).
        green_pos_unanchored = None
        if green_pos is None and expected_green is not None:
            green_pos_unanchored = best_blob(green_combined)

        red_pos = None
        red_pos_unanchored = None
        if green_pos is not None:
            local_dist, _ = precompute_pivot_grids(width, height, green_pos)
            red_ring      = make_ring_uint8(local_dist, ARM_LENGTH_PX,
                                            ring_tolerance)
            red_color     = color_mask_red(hsv, hsv_values["red"])
            red_combined  = cv2.bitwise_and(red_color, red_ring)
            # Recompute expected_red from the actual green so any
            # green-detection drift carries through.
            if initial_angles is not None:
                _, exp_red_dyn = expected_marker_positions(*initial_angles)
                exp_red_dyn = (
                    int(round(green_pos[0] + ARM_LENGTH_PX
                              * math.sin(math.radians(initial_angles[1])))),
                    int(round(green_pos[1] + ARM_LENGTH_PX
                              * math.cos(math.radians(initial_angles[1])))),
                )
            else:
                exp_red_dyn = None
            red_pos = best_blob(
                red_combined,
                anchor=exp_red_dyn,
                max_dist=(PICKER_ANCHOR_MAX_DIST if exp_red_dyn else None),
            )
            if red_pos is None and exp_red_dyn is not None:
                red_pos_unanchored = best_blob(red_combined)

        green_pos, red_pos = validate_geometry(green_pos, red_pos)

        # ── Overlay on the original-resolution frame ──
        cv2.circle(frame, PIVOT, 8, (0, 215, 255), -1)
        cv2.circle(frame, PIVOT, ARM_LENGTH_PX, (0, 200, 0), 1)

        # Draw the expected (filename-prior) marker positions as cyan
        # crosshairs so the user can see where the picker is looking.
        if expected_green is not None:
            cv2.drawMarker(frame, expected_green, (255, 255, 0),
                           cv2.MARKER_TILTED_CROSS, 18, 2)
        if green_pos is not None and initial_angles is not None:
            # exp_red_dyn was computed above
            cv2.drawMarker(frame, exp_red_dyn, (255, 200, 0),
                           cv2.MARKER_TILTED_CROSS, 18, 2)

        # Show rejected (unanchored) detections as faint grey dots so the
        # user can see WHY the prior is helping.
        if green_pos_unanchored is not None:
            cv2.circle(frame, green_pos_unanchored, 6, (120, 120, 120), 1)
        if red_pos_unanchored is not None:
            cv2.circle(frame, red_pos_unanchored, 6, (120, 120, 120), 1)

        if green_pos is not None:
            cv2.line(frame, PIVOT, green_pos, (0, 255, 0), 2)
            cv2.circle(frame, green_pos, 8, (0, 255, 0), -1)
            cv2.circle(frame, green_pos, ARM_LENGTH_PX, (0, 0, 200), 1)
            if red_pos is not None:
                cv2.line(frame, green_pos, red_pos, (0, 0, 200), 2)
                cv2.circle(frame, red_pos, 8, (0, 0, 255), -1)

        # Status banner — also signals HSV adequacy and prior agreement.
        if green_pos is not None and red_pos is not None:
            status_txt, status_col = "[+] both markers detected", (0, 220, 0)
        elif green_pos is not None and red_pos_unanchored is not None:
            status_txt = ("[!] red blob is far from filename prior — "
                          "wrong frame? scrub forward, or press T to retune")
            status_col = (0, 165, 255)
        elif green_pos is not None:
            status_txt = "[!] green ok, red missing (occluded? or HSV stale)"
            status_col = (0, 200, 255)
        elif green_pos_unanchored is not None:
            status_txt = ("[!] green blob is far from filename prior — "
                          "wrong frame, rig moved, or HSV stale")
            status_col = (0, 165, 255)
        else:
            status_txt = "[X] green not found - wrong frame, or HSV stale"
            status_col = (0, 0, 255)

        # Resize to display.
        disp = cv2.resize(frame, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)

        cv2.putText(disp, f"PICK {label.upper()}", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(disp, status_txt, (10, 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_col, 2)
        cv2.putText(disp, prior_status, (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 255), 1)
        cv2.putText(disp,
                    "a/d +-1   A/D +-10   z/x +-100   T re-tune HSV   ENTER confirm   ESC cancel",
                    (10, DISP_H - 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
        cv2.putText(disp,
                    f"frame {idx}/{total_frames - 1}   t={idx / fps:.3f}s",
                    (10, DISP_H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        cv2.imshow(win_title, disp)
        k = cv2.waitKey(0) & 0xFF

        if k in (13, 10):                       # ENTER
            chosen = idx
            break
        if k == 27:                              # ESC
            break
        if k == ord("a"):
            idx = max(0, idx - 1)
        elif k == ord("d"):
            idx = min(total_frames - 1, idx + 1)
        elif k == ord("A"):
            idx = max(0, idx - 10)
        elif k == ord("D"):
            idx = min(total_frames - 1, idx + 10)
        elif k == ord("z"):
            idx = max(0, idx - 100)
        elif k == ord("x"):
            idx = min(total_frames - 1, idx + 100)
        elif k in (ord("t"), ord("T")):
            # Hand off to hsv_tuner on the current frame. After it exits,
            # reload HSV calibration in place and rebuild the green ring
            # mask so the picker resumes with the new values.
            cv2.destroyWindow(win_title)
            cap.release()
            print(f"\n  Launching hsv_tuner on '{os.path.basename(video_path)}' "
                  f"@ frame {idx} ...")
            try:
                subprocess.run(
                    [sys.executable, HSV_TUNER_PATH, video_path, str(idx)],
                    check=False,
                )
            except FileNotFoundError:
                print(f"  ERROR: could not launch {HSV_TUNER_PATH}")

            # Reload HSV calibration into the same dict the caller holds.
            # Pass video_path so we get the per-video file the tuner just wrote.
            new_hsv = load_hsv_values(video_path)
            hsv_values.clear()
            hsv_values.update(new_hsv)
            ring_tolerance = int(new_hsv.get("ring_tolerance", DEFAULT_RING_TOL))

            # Rebuild the green ring mask at the new tolerance.
            pivot_ring = make_ring_uint8(pivot_dist, ARM_LENGTH_PX,
                                         ring_tolerance)

            # Reopen the picker. last_idx = -1 forces a re-decode + re-detect.
            cap = cv2.VideoCapture(video_path)
            cv2.namedWindow(win_title, cv2.WINDOW_AUTOSIZE)
            last_idx = -1
            print(f"  Reloaded HSV (ring tolerance = {ring_tolerance}px). "
                  f"Resuming picker.\n")

    cap.release()
    cv2.destroyWindow(win_title)
    return chosen


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    no_debug      = "--no-debug"     in flags
    force_browse  = "--browse"       in flags
    show_status   = "--status"       in flags
    force_run     = "--force"        in flags
    no_prior      = "--no-prior"     in flags
    skip_probe    = "--skip-probe"   in flags
    yes_to_warn   = "--yes-to-warn"  in flags
    strict_phys   = "--strict-physics" in flags

    # --seeds-file <path>: extract value (or auto-detect <meas_dir>/seeds.json).
    seeds_file_arg = None
    for i, f in enumerate(sys.argv[1:]):
        if f == "--seeds-file" and i + 1 < len(sys.argv) - 1:
            seeds_file_arg = sys.argv[i + 2]
            break

    # --from-frame N: extract value.
    from_frame_arg = None
    for i, f in enumerate(sys.argv[1:]):
        if f == "--from-frame" and i + 1 < len(sys.argv) - 1:
            try:
                from_frame_arg = int(sys.argv[i + 2])
            except ValueError:
                print(f"WARN: --from-frame expects an int, got '{sys.argv[i+2]}'")
            break

    # --status mode: print the tracked/pending breakdown and exit.
    if show_status:
        print_status()
        return

    # When no positional path is given, print a one-line tracking-status
    # banner before the picker opens, so the user knows what's left.
    if not args or force_browse:
        print(status_summary())

    if args and not force_browse:
        video_path = args[0]
        if not os.path.isabs(video_path):
            video_path = os.path.join(ROOT, video_path)
    else:
        video_path = pick_video_interactive()
        if not video_path:
            print("No video selected — cancelled.")
            return

    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return

    stem = os.path.splitext(os.path.basename(video_path))[0]

    # Resolve config_description before computing output paths so all
    # outputs land in the canonical measurements/<config> folder.
    reg_preview     = load_registry()
    existing_preview = reg_preview.get(stem)
    config_desc     = derive_config_description(stem, video_path,
                                                existing_preview)
    meas_dir        = measurements_dir_for(config_desc)
    output_csv      = os.path.join(meas_dir, "tracking.csv")
    debug_mp4       = os.path.join(meas_dir, "debug.mp4")

    print("ring_tracker.py")
    print(f"Video  : {video_path}")
    print(f"Folder : {meas_dir}")
    print(f"CSV    : {output_csv}")

    # ── Already tracked? Confirm re-run unless --force was passed. ──
    reg = load_registry()
    if is_tracked(stem, reg, root=ROOT) and not force_run:
        e = reg[stem]
        print(f"\n[+] '{stem}' is already tracked")
        print(f"    init_frame    = {e.get('init_frame')}")
        print(f"    release_frame = {e.get('release_frame')}")
        if e.get("theta1_release") is not None:
            print(f"    th1={e['theta1_release']:.2f}  "
                  f"th2={e['theta2_release']:.2f}  "
                  f"E={e.get('energy_proxy', '?')}")
        if e.get("dropout_rate_pct") is not None:
            print(f"    dropout       = {e['dropout_rate_pct']}%")
        ans = input("\nRe-run tracking? [y/N]: ").strip().lower()
        if not ans.startswith("y"):
            print("Cancelled.")
            return

    hsv_values     = load_hsv_values(video_path)
    ring_tolerance = int(hsv_values.get("ring_tolerance", DEFAULT_RING_TOL))
    hsv_kind       = ("PER-VIDEO" if hsv_values["_hsv_path"] != GLOBAL_HSV_FILE
                      else "GLOBAL")
    print(f"HSV   : {hsv_values['_hsv_path']}  [{hsv_kind}]  "
          f"(ring tolerance = {ring_tolerance}px)")

    existing_entry = reg.get(stem)
    if existing_entry:
        print(f"\nFound existing registry entry for {stem}:")
        if existing_entry.get("init_frame") is not None:
            print(f"  init_frame    = {existing_entry['init_frame']}")
        if existing_entry.get("release_frame") is not None:
            print(f"  release_frame = {existing_entry['release_frame']}")

    # ── Open video ───────────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: could not open video: {video_path}")
        return
    video_fps    = cap.get(cv2.CAP_PROP_FPS) or FPS_DEFAULT
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dt           = 1.0 / video_fps
    print(f"\nVideo: {width}x{height} @ {video_fps:.2f}fps, {total_frames} frames")

    # ── HSV adequacy probe — fail fast before launching a 3-min track. ──
    if not skip_probe:
        print("\nProbing HSV adequacy (sampling 30 frames) ...")
        verdict, both_pct, green_pct, red_pct = hsv_adequacy_probe(
            cap, total_frames, hsv_values, ring_tolerance,
            use_filename_prior=not no_prior, video_path=video_path,
        )
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # rewind after sampling

        flag = {"OK": "[OK]", "WARN": "[WARN]", "ABORT": "[ABORT]"}[verdict]
        print(f"  {flag} both markers: {both_pct:.0f}%   "
              f"green-only: {green_pct:.0f}%   red-only: {red_pct:.0f}%")

        if verdict == "ABORT":
            print(f"\nHSV adequacy below {ADEQUACY_ABORT_PCT:.0f}% — "
                  f"calibration is too poor to track this clip.")
            print(f"  Re-run: python scripts/processing/hsv_tuner.py "
                  f"{video_path}")
            print("  Then re-launch ring_tracker. Pass --skip-probe to "
                  "override.")
            cap.release()
            # Non-zero exit so track_one and bulk_track see this as a
            # failure and surface the real cause instead of cascading
            # into a missing-CSV error downstream.
            sys.exit(2)
        if verdict == "WARN" and not yes_to_warn:
            ans = input(f"\nHSV adequacy below {ADEQUACY_WARN_PCT:.0f}% "
                        f"({both_pct:.0f}%). Continue anyway? [y/N]: ").strip().lower()
            if not ans.startswith("y"):
                print("Cancelled. Suggested next step: hsv_tuner.py on this video.")
                cap.release()
                sys.exit(3)

    # ── Resolve seeds-file path. Auto-detect if --seeds-file wasn't
    # passed: <meas_dir>/seeds.json. Falls back to no seeds when absent.
    seeds_path = seeds_file_arg
    if seeds_path is None:
        candidate = os.path.join(meas_dir, "seeds.json")
        if os.path.exists(candidate):
            seeds_path = candidate
    seeds_by_frame, _seeds_meta = load_seeds(seeds_path)
    if seeds_by_frame:
        print(f"\nLoaded {len(seeds_by_frame)} seed(s) from "
              f"{os.path.relpath(seeds_path, ROOT)}")

    # When --from-frame=N is given AND N > 0, we preserve rows
    # 0..N-1 from the existing CSV and re-track only frames N..end.
    # In that case the picker is skipped (init/release must already be
    # in the registry) since this is a resume of an earlier track.
    #
    # --from-frame=0 is the degenerate case: zero rows to preserve. We
    # treat it as equivalent to no --from-frame at all, so the picker
    # still runs (or skips) per the normal logic, and a missing CSV is
    # fine.
    resume_from = from_frame_arg if (from_frame_arg and from_frame_arg > 0) else None
    resume_skip_picker = resume_from is not None
    existing_csv_rows = []
    if resume_from is not None:
        if not os.path.exists(output_csv):
            print(f"ERROR: --from-frame={resume_from} requires an existing "
                  f"tracking.csv at {output_csv} to preserve rows from.")
            cap.release()
            sys.exit(2)
        with open(output_csv, "r", newline="") as f:
            existing_csv_rows = list(csv.DictReader(f))
        if not (existing_entry
                and existing_entry.get("init_frame") is not None
                and existing_entry.get("release_frame") is not None):
            print(f"ERROR: --from-frame requires init_frame and "
                  f"release_frame in the registry; aborting.")
            cap.release()
            sys.exit(2)
        print(f"\nResuming tracking from frame {resume_from}; preserving "
              f"{resume_from} rows from existing tracking.csv.")
        if strict_phys:
            print("Strict-physics gate ENABLED for the entire resume range.")
    elif from_frame_arg == 0:
        print("\nNote: --from-frame=0 is a no-op; tracking from scratch "
              "(seeds and --strict-physics still apply).")

    # ── Smart pre-positioning for the picker ─────────────────────────────
    # Compute candidate init/release frames once, before either picker
    # opens. The picker uses the candidate as its starting frame so the
    # user typically just confirms with ENTER instead of scrubbing.
    init_suggestion = release_suggestion = None
    need_pick_init    = (not resume_skip_picker) and not (existing_entry and
                              existing_entry.get("init_frame") is not None)
    need_pick_release = (not resume_skip_picker) and not (existing_entry and
                              existing_entry.get("release_frame") is not None)
    if need_pick_init or need_pick_release:
        tag_hint = (existing_entry or {}).get("tag_frame")
        print(f"\nScanning for smart init/release suggestions"
              f"{f' (anchored at tag_frame={tag_hint})' if tag_hint is not None else ''} ...")
        init_suggestion, release_suggestion = suggest_frame_candidates(
            video_path, total_frames, hsv_values, ring_tolerance,
            use_filename_prior=not no_prior,
            tag_frame_hint=tag_hint,
        )
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # rewind after scan
        if init_suggestion is not None:
            print(f"  init suggestion: frame {init_suggestion} "
                  f"(t={init_suggestion / video_fps:.3f}s) — first clean detection")
        else:
            print("  init suggestion: none (HSV may need retuning).")
        if release_suggestion is not None:
            print(f"  release suggestion: frame {release_suggestion} "
                  f"(t={release_suggestion / video_fps:.3f}s) — last static frame before motion")
        else:
            print("  release suggestion: none (no motion threshold crossed within scan).")

    # ── Init frame: registry → visual picker (pre-positioned) ────────────
    if existing_entry and existing_entry.get("init_frame") is not None:
        init_frame = int(existing_entry["init_frame"])
        print(f"Init frame loaded from registry: {init_frame}")
    else:
        start_at = init_suggestion if init_suggestion is not None else 0
        print(f"\nOpening visual picker for INIT FRAME (start at {start_at}) ...")
        init_frame = pick_frame_interactive(
            video_path, "init frame", video_fps, total_frames,
            hsv_values, ring_tolerance, start_frame=start_at,
            use_filename_prior=not no_prior,
        )
        if init_frame is None:
            print("Cancelled — no init frame selected.")
            cap.release()
            return
        print(f"Init frame selected: {init_frame}")
        # The picker may have updated HSV calibration via the T hotkey;
        # refresh ring_tolerance so the rest of the run uses the new value.
        ring_tolerance = int(hsv_values.get("ring_tolerance", DEFAULT_RING_TOL))

    # ── Release frame: registry → visual picker (pre-positioned) ─────────
    if existing_entry and existing_entry.get("release_frame") is not None:
        release_frame = int(existing_entry["release_frame"])
        print(f"Release frame loaded from registry: {release_frame}")
    else:
        start_at = (release_suggestion if release_suggestion is not None
                    else init_frame)
        print(f"\nOpening visual picker for RELEASE FRAME (start at {start_at}) ...")
        release_frame = pick_frame_interactive(
            video_path, "release frame", video_fps, total_frames,
            hsv_values, ring_tolerance, start_frame=start_at,
            use_filename_prior=not no_prior,
        )
        if release_frame is None:
            print("Cancelled — no release frame selected.")
            cap.release()
            return
        print(f"Release frame selected: {release_frame}")
        # Pick up any tuning the user did via T during release-frame picking.
        ring_tolerance = int(hsv_values.get("ring_tolerance", DEFAULT_RING_TOL))
    print(f"Release frame: {release_frame}  (t={release_frame / video_fps:.3f}s)")

    # ── Build static background (median of sampled frames) ───────────────
    bg_bgr, bg_gray = compute_static_background(cap, total_frames)

    # ── Precompute static masks for the green ring ───────────────────────
    pivot_dist, pivot_angle = precompute_pivot_grids(width, height, PIVOT)
    pivot_ring_uint8 = make_ring_uint8(pivot_dist,
                                       ARM_LENGTH_PX, ring_tolerance)

    # ── Outputs ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    os.makedirs(os.path.dirname(debug_mp4),  exist_ok=True)
    writer = None
    if not no_debug:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(debug_mp4, fourcc, video_fps, (width, height))
    else:
        print("Debug video disabled (--no-debug)")

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # ── Per-marker predictors ────────────────────────────────────────────
    pred1 = AngularPredictor()
    pred2 = AngularPredictor()

    # Seed the predictors from green_click_px / red_click_px when the
    # registry has them (recorded by the video-tagger). Without seeding,
    # the arc filter is asleep on the very first detection attempt and
    # the strict pipeline can't fire until a marker has been observed
    # twice. Seeding gives the strict path a chance from frame 1.
    #
    # We only seed when init_frame is at (or right next to) tag_frame —
    # otherwise the seed angle reflects a moment far from where tracking
    # actually starts, and the first real observation would compute a
    # bogus ω from the stale baseline. SEED_MAX_GAP gates this.
    SEED_MAX_GAP = 3
    seeded_from  = []
    if existing_entry:
        tag_frame = existing_entry.get("tag_frame")
        gap_ok = (tag_frame is not None
                  and abs(int(tag_frame) - int(init_frame)) <= SEED_MAX_GAP)
        gpx = existing_entry.get("green_click_px")
        rpx = existing_entry.get("red_click_px")
        if gap_ok and isinstance(gpx, (list, tuple)) and len(gpx) == 2:
            theta1_seed = compute_angle(PIVOT, tuple(gpx))
            pred1.observe(theta1_seed, dt)
            seeded_from.append(
                f"green_click_px={tuple(gpx)} -> th1={theta1_seed:.1f}")
        if (gap_ok and isinstance(gpx, (list, tuple)) and len(gpx) == 2
                and isinstance(rpx, (list, tuple)) and len(rpx) == 2):
            theta2_seed = compute_angle(tuple(gpx), tuple(rpx))
            pred2.observe(theta2_seed, dt)
            seeded_from.append(
                f"red_click_px={tuple(rpx)} -> th2={theta2_seed:.1f}")
        if not gap_ok and (gpx or rpx):
            print(f"\nNote: skipping click_px seeding (tag_frame={tag_frame}, "
                  f"init_frame={init_frame}, gap > {SEED_MAX_GAP}).")
    if seeded_from:
        print(f"\nPredictors seeded from registry click_px (tag-frame "
              f"and init-frame are within {SEED_MAX_GAP}):")
        for line in seeded_from:
            print(f"  {line}")

    # ── Counters ────────────────────────────────────────────────────────
    dropout_total = dropout_holding = dropout_free = 0
    fallback_counts_g = {"strict": 0, "no-arc": 0, "no-colour": 0,
                         "no-motion": 0, "ring+motion": 0, "fail": 0}
    fallback_counts_r = {"strict": 0, "no-arc": 0, "no-colour": 0,
                         "no-motion": 0, "ring+motion": 0,
                         "skip-no-green": 0, "fail": 0}

    progress_interval = 500 if total_frames >= 5000 else 100

    # Strict-physics window — frames at which strict mode is active. The
    # CLI flag --strict-physics keeps it active for the whole run; each
    # seed extends the window by STRICT_POST_SEED_FRAMES from its frame.
    # When neither is set, strict mode is off everywhere.
    strict_until = -1
    if strict_phys:
        strict_until = total_frames + 1
    fallback_counts_g["fail-strict"] = 0
    fallback_counts_r["fail-strict"] = 0

    with open(output_csv, "w", newline="") as csvfile:
        fieldnames = ["frame", "time_s", "phase",
                      "x_green", "y_green", "x_red", "y_red",
                      "theta1_deg", "theta2_deg", "dropout"]
        wcsv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        wcsv.writeheader()

        # Map preserved rows by frame for fast lookup when --from-frame
        # is in effect. We replay them verbatim into the new CSV.
        existing_by_frame = {}
        if resume_from is not None:
            for r in existing_csv_rows:
                try:
                    existing_by_frame[int(r["frame"])] = r
                except (KeyError, ValueError):
                    continue

        for frame_idx in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break

            phase  = "holding" if frame_idx < release_frame else "free_swing"
            time_s = frame_idx / video_fps

            # ── --from-frame: replay preserved rows verbatim. We still
            # consume the frame from cv2 (cap.read above) so the iterator
            # advances; we just don't run detection.
            if resume_from is not None and frame_idx < resume_from:
                if frame_idx in existing_by_frame:
                    wcsv.writerow(existing_by_frame[frame_idx])
                    # Re-seed the predictor from the preserved row so the
                    # transition into the live-tracked range is smooth.
                    er = existing_by_frame[frame_idx]
                    try:
                        gx = float(er.get("x_green", "")) if er.get("x_green") else None
                        gy = float(er.get("y_green", "")) if er.get("y_green") else None
                        rx = float(er.get("x_red", ""))   if er.get("x_red")   else None
                        ry = float(er.get("y_red", ""))   if er.get("y_red")   else None
                    except (TypeError, ValueError):
                        gx = gy = rx = ry = None
                    if gx is not None and gy is not None:
                        pred1.observe(compute_angle(PIVOT, (gx, gy)), dt)
                        if rx is not None and ry is not None:
                            pred2.observe(compute_angle((gx, gy), (rx, ry)), dt)
                else:
                    # No preserved row for this frame — write a dropout.
                    wcsv.writerow({
                        "frame": frame_idx, "time_s": round(time_s, 5),
                        "phase": phase, "x_green": "", "y_green": "",
                        "x_red": "", "y_red": "",
                        "theta1_deg": "", "theta2_deg": "", "dropout": 1,
                    })
                continue

            # ── Honour any seed at this frame: write the seed row,
            # re-anchor the predictors, and (re)open the strict-physics
            # window for the next STRICT_POST_SEED_FRAMES frames.
            if frame_idx in seeds_by_frame:
                seed = seeds_by_frame[frame_idx]
                gxy = seed.get("green_xy")
                rxy = seed.get("red_xy")
                seed_th1 = compute_angle(PIVOT, gxy) if gxy else None
                seed_th2 = (compute_angle(gxy, rxy)
                            if (gxy and rxy) else None)
                if gxy is not None:
                    pred1.observe(seed_th1, dt)
                if gxy is not None and rxy is not None:
                    pred2.observe(seed_th2, dt)
                # Open / extend the strict-physics window past this seed.
                strict_until = max(strict_until,
                                   frame_idx + STRICT_POST_SEED_FRAMES)
                wcsv.writerow({
                    "frame":      frame_idx,
                    "time_s":     round(time_s, 5),
                    "phase":      phase,
                    "x_green":    gxy[0] if gxy else "",
                    "y_green":    gxy[1] if gxy else "",
                    "x_red":      rxy[0] if rxy else "",
                    "y_red":      rxy[1] if rxy else "",
                    "theta1_deg": round(seed_th1, 3) if seed_th1 is not None else "",
                    "theta2_deg": round(seed_th2, 3) if seed_th2 is not None else "",
                    "dropout":    0 if (gxy and rxy) else 1,
                })
                continue

            # ── Pre-init: write dropout, do not detect ──────────────────
            if frame_idx < init_frame:
                wcsv.writerow({
                    "frame": frame_idx, "time_s": round(time_s, 5),
                    "phase": phase, "x_green": "", "y_green": "",
                    "x_red": "", "y_red": "",
                    "theta1_deg": "", "theta2_deg": "", "dropout": 1,
                })
                dropout_total += 1
                if phase == "holding": dropout_holding += 1
                else:                  dropout_free    += 1

                if writer is not None:
                    debug = frame.copy()
                    cv2.putText(debug, "PRE-INIT (skipped)", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv2.putText(debug, f"frame {frame_idx}/{total_frames}",
                                (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                (255, 255, 255), 1)
                    writer.write(debug)

                if frame_idx % progress_interval == 0:
                    print(f"  {frame_idx}/{total_frames} "
                          f"({100 * frame_idx // total_frames}%)  "
                          f"dropouts: {dropout_total}", end="\r")
                continue

            # ── Pre-process ────────────────────────────────────────────
            blurred = cv2.GaussianBlur(frame, GAUSS_KSIZE, 0)
            hsv     = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
            fg_mask = motion_mask(blurred, bg_gray, BG_DIFF_THRESH)

            strict_now = (frame_idx <= strict_until)

            # ── Detect green ───────────────────────────────────────────
            green_pos, fb_g = detect_green(
                hsv, fg_mask,
                pivot_ring_uint8, pivot_angle,
                hsv_values, pred1, dt,
                strict=strict_now,
            )
            fallback_counts_g[fb_g] = fallback_counts_g.get(fb_g, 0) + 1

            # ── Detect red (depends on green) ──────────────────────────
            red_pos, fb_r = detect_red(
                hsv, fg_mask, frame.shape,
                green_pos, ring_tolerance,
                hsv_values, pred2, dt,
                strict=strict_now,
            )
            fallback_counts_r[fb_r] = fallback_counts_r.get(fb_r, 0) + 1

            # ── Geometric sanity ───────────────────────────────────────
            green_pos, red_pos = validate_geometry(green_pos, red_pos)

            # ── Update predictors ──────────────────────────────────────
            if green_pos is not None:
                pred1.observe(compute_angle(PIVOT, green_pos), dt)
            else:
                pred1.coast(dt)
            if green_pos is not None and red_pos is not None:
                pred2.observe(compute_angle(green_pos, red_pos), dt)
            else:
                pred2.coast(dt)

            dropout = (green_pos is None or red_pos is None)
            if dropout:
                dropout_total += 1
                if phase == "holding": dropout_holding += 1
                else:                  dropout_free    += 1

            theta1 = compute_angle(PIVOT, green_pos)        if green_pos else None
            theta2 = (compute_angle(green_pos, red_pos)
                      if (green_pos and red_pos) else None)

            wcsv.writerow({
                "frame":      frame_idx,
                "time_s":     round(time_s, 5),
                "phase":      phase,
                "x_green":    green_pos[0] if green_pos else "",
                "y_green":    green_pos[1] if green_pos else "",
                "x_red":      red_pos[0]   if red_pos   else "",
                "y_red":      red_pos[1]   if red_pos   else "",
                "theta1_deg": round(theta1, 3) if theta1 is not None else "",
                "theta2_deg": round(theta2, 3) if theta2 is not None else "",
                "dropout":    1 if dropout else 0,
            })

            # ── Debug overlay ──────────────────────────────────────────
            if writer is not None:
                debug = frame.copy()

                # Static reference + search rings.
                draw_dashed_circle(debug, PIVOT, 2 * ARM_LENGTH_PX,
                                   (255, 255, 255), 1, 14)
                cv2.circle(debug, PIVOT, ARM_LENGTH_PX, (0, 200, 0), 1)
                if green_pos is not None:
                    cv2.circle(debug, green_pos, ARM_LENGTH_PX,
                               (0, 0, 200), 1)

                # Predicted angle markers.
                if pred1.alive:
                    p1w = pred1.wrapped_predict(dt)
                    if p1w is not None:
                        px = int(PIVOT[0] + ARM_LENGTH_PX
                                 * np.sin(np.radians(p1w)))
                        py = int(PIVOT[1] + ARM_LENGTH_PX
                                 * np.cos(np.radians(p1w)))
                        cv2.drawMarker(debug, (px, py), (0, 255, 255),
                                       cv2.MARKER_TILTED_CROSS, 14, 1)
                if pred2.alive and green_pos is not None:
                    p2w = pred2.wrapped_predict(dt)
                    if p2w is not None:
                        px = int(green_pos[0] + ARM_LENGTH_PX
                                 * np.sin(np.radians(p2w)))
                        py = int(green_pos[1] + ARM_LENGTH_PX
                                 * np.cos(np.radians(p2w)))
                        cv2.drawMarker(debug, (px, py), (180, 180, 0),
                                       cv2.MARKER_TILTED_CROSS, 14, 1)

                cv2.circle(debug, PIVOT, 8, (0, 215, 255), -1)

                phase_col = ((100, 255, 100) if phase == "free_swing"
                             else (100, 100, 255))
                cv2.putText(debug, phase.upper(), (10, 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, phase_col, 2)

                if green_pos is not None:
                    cv2.line(debug, PIVOT, green_pos, (0, 255, 0), 2)
                    cv2.circle(debug, green_pos, 8, (0, 255, 0), -1)
                    if theta1 is not None:
                        cv2.putText(debug, f"th1={theta1:.1f}",
                                    (green_pos[0] + 10, green_pos[1]),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 255, 0), 1)
                if red_pos is not None:
                    cv2.circle(debug, red_pos, 8, (0, 0, 255), -1)
                    if green_pos is not None:
                        cv2.line(debug, green_pos, red_pos, (0, 0, 200), 2)
                    if theta2 is not None:
                        cv2.putText(debug, f"th2={theta2:.1f}",
                                    (red_pos[0] + 10, red_pos[1]),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 0, 255), 1)

                cv2.putText(debug,
                            f"frame {frame_idx}/{total_frames}  t={time_s:.2f}s",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (255, 255, 255), 1)
                cv2.putText(debug,
                            f"tol={ring_tolerance}  g:{fb_g}  r:{fb_r}",
                            (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (200, 200, 200), 1)
                if dropout:
                    cv2.putText(debug, "DROPOUT", (10, 85),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                writer.write(debug)

            if frame_idx % progress_interval == 0:
                print(f"  {frame_idx}/{total_frames} "
                      f"({100 * frame_idx // total_frames}%)  "
                      f"dropouts: {dropout_total}", end="\r")

    cap.release()
    if writer is not None:
        writer.release()

    # ── Summary ──────────────────────────────────────────────────────────
    free_n = max(0, total_frames - release_frame)

    def pct(n, d):
        return f"{100 * n / d:.1f}%" if d else "n/a"

    print(f"\nDone. {total_frames} frames.")
    print(f"Dropouts: {dropout_total} total  |  "
          f"holding {pct(dropout_holding, release_frame)}  |  "
          f"free_swing {pct(dropout_free, free_n)}")
    print("Green fallback chain breakdown:")
    for k, v in fallback_counts_g.items():
        print(f"  {k:>14}: {v}")
    print("Red fallback chain breakdown:")
    for k, v in fallback_counts_r.items():
        print(f"  {k:>14}: {v}")
    print(f"CSV   : {output_csv}")
    if writer is not None:
        print(f"Debug : {debug_mp4}")

    # ── ICs + registry ───────────────────────────────────────────────────
    print("\nExtracting initial conditions from CSV ...")
    th1r, th2r, om1r, om2r, n_free, d_pct, dur = \
        extract_ic_from_csv(output_csv, release_frame, video_fps)
    print(f"  th1={th1r:.3f}  th2={th2r:.3f}  "
          f"om1={om1r:.3f}  om2={om2r:.3f}")

    reg = load_registry()
    update_registry(
        reg, stem, video_path,
        init_frame, release_frame,
        config_desc, ring_tolerance,
        th1r, th2r, om1r, om2r,
        n_free, d_pct, dur,
        video_fps, existing_entry=reg.get(stem),
    )
    save_registry(reg)


if __name__ == "__main__":
    main()
