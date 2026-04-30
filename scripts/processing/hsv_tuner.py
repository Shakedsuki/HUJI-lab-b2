"""
hsv_tuner.py
------------
Interactive HSV calibration tool for the double-pendulum tracking pipeline.

Lets the user:
  - Scrub through a video frame by frame
  - Click pixels with an eyedropper to sample marker colours
  - Auto-suggest HSV ranges from the sampled points
  - Fine-tune ranges with sliders
  - Preview ring-based detection live (one ring around the pivot for the
    GREEN marker, a second ring centred on the green marker for the RED
    marker)
  - Save the calibrated values to data/hsv_values.json so that
    ring_tracker.py can pick them up.

Why ring-based detection? Because the arm lengths are fixed:
    GREEN sits on a circle of radius ARM_LENGTH_PX around the pivot.
    RED   sits on a circle of radius ARM_LENGTH_PX around the green marker.
This collapses the search from ~921k pixels to ~1.2k per ring and is robust
to motion blur (no temporal model, no appearance drift).

Usage:
  python scripts/processing/hsv_tuner.py
  python scripts/processing/hsv_tuner.py Videos/long_recording.mov
  python scripts/processing/hsv_tuner.py Videos/long_recording.mov 200    # start frame

Keys:
  G / R          switch active marker (GREEN / RED)
  A / D          step  ±1 frame
  LEFT / RIGHT   step  ±50 frames
  SPACE          pause / play
  LEFT-CLICK     sample HSV at the cursor (auto-suggest after >=5 samples)
  C              clear sampled points for the active marker
  T              cycle ring tolerance (20 -> 30 -> 40 px)
  S              save data/hsv_values.json
  Q / ESC        quit (prompts to save if there are unsaved changes)
"""

import cv2
import numpy as np
import json
import os
import sys


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

ROOT          = r"C:\dev\chaos"
DEFAULT_VIDEO = os.path.join(ROOT, r"Videos\long_recording.mov")
HSV_FILE      = os.path.join(ROOT, r"data\hsv_values.json")
HSV_README    = os.path.join(ROOT, r"data\hsv_values_readme.txt")

PIVOT          = (608, 355)        # fixed pivot in original 1280x720 coords
ARM_LENGTH_PX  = 188               # default — override with --arm-length N

# Original frame dimensions (we know the rig: 1280x720 @ 59.94fps).
FRAME_W = 1280
FRAME_H = 720

# Display layout:
#   total window = 1280 x 720
#   left panel   = 960  x 720  (top 540 = scaled video, bottom 180 = info bar)
#   right panel  = 320  x 720  (binary mask preview)
DISPLAY_W       = 1280
DISPLAY_H       = 720
LEFT_W          = 960
RIGHT_W         = 320
VIDEO_DISP_W    = 960
VIDEO_DISP_H    = 540        # uniform scaling: 1280x720 -> 960x540 (factor 0.75)
DISPLAY_SCALE   = VIDEO_DISP_W / FRAME_W       # 0.75

WINDOW_MAIN     = "HSV Tuner"
WINDOW_CTRL     = "HSV Controls"

# Ring tolerances we cycle through with the T key.
RING_TOLERANCES = [20, 30, 40]
DEFAULT_TOL_IDX = 1            # start at 30 px

# Default HSV ranges — sensible starting points for the green/red gaff tape.
DEFAULTS = {
    "green": {"h_min": 40, "h_max": 80,  "s_min": 50, "s_max": 255,
              "v_min": 50, "v_max": 255},
    "red":   {"h_min": 0,  "h_max": 10,  "s_min": 80, "s_max": 255,
              "v_min": 80, "v_max": 255, "h_min2": 170, "h_max2": 180},
}

# Auto-suggest padding (added/subtracted around the sampled min/max).
PAD_H = 15
PAD_S = 20
PAD_V = 20
MIN_SAMPLES_FOR_AUTO = 5

# Trackbar names — order matters for readability in the controls window.
BARS_GREEN = ["H_min", "H_max", "S_min", "S_max", "V_min", "V_max"]
BARS_RED   = BARS_GREEN + ["H_min2", "H_max2"]


# ─────────────────────────────────────────────
# RING / MASK HELPERS
# ─────────────────────────────────────────────

def precompute_distance_grid(width, height, center):
    """
    Return a float32 (height, width) array where each cell holds the
    Euclidean distance from that pixel to `center`.

    We compute this once for the static pivot and once per frame for the
    moving green centre — both are cheap (~10 ms on 1280x720).
    """
    ys, xs = np.indices((height, width), dtype=np.float32)
    return np.sqrt((xs - center[0])**2 + (ys - center[1])**2)


def ring_mask_from_distance(dist_grid, radius, tolerance):
    """Boolean mask where dist_grid is within radius +- tolerance."""
    return (np.abs(dist_grid - radius) < tolerance)


def color_mask_green(hsv_img, cfg):
    """Single-range HSV mask for the green marker."""
    lo = np.array([cfg["h_min"], cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi = np.array([cfg["h_max"], cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    return cv2.inRange(hsv_img, lo, hi)


def color_mask_red(hsv_img, cfg):
    """
    Two-range HSV mask for red (red wraps around H=0).
    Resulting mask = (H in [h_min, h_max]) OR (H in [h_min2, h_max2])
    intersected with the same S/V range.
    """
    lo1 = np.array([cfg["h_min"],  cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi1 = np.array([cfg["h_max"],  cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    lo2 = np.array([cfg["h_min2"], cfg["s_min"], cfg["v_min"]], dtype=np.uint8)
    hi2 = np.array([cfg["h_max2"], cfg["s_max"], cfg["v_max"]], dtype=np.uint8)
    m1 = cv2.inRange(hsv_img, lo1, hi1)
    m2 = cv2.inRange(hsv_img, lo2, hi2)
    return cv2.bitwise_or(m1, m2)


def largest_centroid(mask_uint8, min_area=10):
    """
    Find the largest connected component in `mask_uint8` (0/255) and return
    its centroid (cx, cy) plus area, or (None, 0) if nothing meaningful.
    """
    contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0
    best = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(best)
    if area < min_area:
        return None, 0
    M = cv2.moments(best)
    if M["m00"] == 0:
        return None, 0
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return (cx, cy), int(area)


# ─────────────────────────────────────────────
# ANGLE HELPER
# ─────────────────────────────────────────────

def compute_angle(p_from, p_to):
    """0 deg = straight down, +90 = right, -90 = left, +/-180 = up."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return float(np.degrees(np.arctan2(dx, dy)))


# ─────────────────────────────────────────────
# TRACKBAR PLUMBING
# ─────────────────────────────────────────────

def _noop(_):
    """Trackbar callback placeholder — we read positions on demand."""
    pass


def build_controls_window(mode):
    """
    (Re)create the HSV Controls window with the right set of trackbars
    for the given mode. Called whenever the active marker changes.
    """
    # Destroy and recreate so we can switch between 6 and 8 trackbars cleanly.
    try:
        cv2.destroyWindow(WINDOW_CTRL)
    except cv2.error:
        pass
    cv2.namedWindow(WINDOW_CTRL, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_CTRL, 480, 360)

    bars = BARS_GREEN if mode == "green" else BARS_RED
    for name in bars:
        # Hue uses 0..179 in OpenCV; saturation & value 0..255.
        max_val = 179 if name.startswith("H") else 255
        cv2.createTrackbar(name, WINDOW_CTRL, 0, max_val, _noop)


def push_cfg_to_trackbars(cfg, mode):
    """Force trackbar positions to match the dict cfg for the active mode."""
    bars = BARS_GREEN if mode == "green" else BARS_RED
    keys = ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max",
            "h_min2", "h_max2"]
    for name, key in zip(bars, keys):
        if key in cfg:
            cv2.setTrackbarPos(name, WINDOW_CTRL, int(cfg[key]))


def read_cfg_from_trackbars(mode):
    """Return a fresh cfg dict reflecting the current trackbar positions."""
    bars = BARS_GREEN if mode == "green" else BARS_RED
    keys = ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max",
            "h_min2", "h_max2"]
    cfg = {}
    for name, key in zip(bars, keys):
        cfg[key] = cv2.getTrackbarPos(name, WINDOW_CTRL)
    return cfg


# ─────────────────────────────────────────────
# AUTO-SUGGEST FROM SAMPLES
# ─────────────────────────────────────────────

def suggest_from_samples(samples, mode):
    """
    Given a list of (H,S,V) samples, return a cfg dict with padded ranges.
    For red: also splits the hue distribution around 0 so wraparound works.

    Returns None if there aren't enough samples.
    """
    if len(samples) < MIN_SAMPLES_FOR_AUTO:
        return None

    arr = np.asarray(samples, dtype=np.int32)
    H, S, V = arr[:, 0], arr[:, 1], arr[:, 2]

    s_min = int(np.clip(S.min() - PAD_S,   0, 255))
    s_max = int(np.clip(S.max() + PAD_S,   0, 255))
    v_min = int(np.clip(V.min() - PAD_V,   0, 255))
    v_max = int(np.clip(V.max() + PAD_V,   0, 255))

    if mode == "green":
        h_min = int(np.clip(H.min() - PAD_H, 0, 179))
        h_max = int(np.clip(H.max() + PAD_H, 0, 179))
        return {"h_min": h_min, "h_max": h_max,
                "s_min": s_min, "s_max": s_max,
                "v_min": v_min, "v_max": v_max}

    # Red: hue wraps around 0/180. Split samples into "low" (0..30) and
    # "high" (150..179) buckets and build two ranges. If everything sits in
    # one bucket, we simply zero out the other range.
    low_mask  = H <= 30
    high_mask = H >= 150
    h_min1 = h_max1 = 0
    h_min2 = h_max2 = 0
    if np.any(low_mask):
        h_min1 = int(np.clip(H[low_mask].min() - PAD_H, 0, 179))
        h_max1 = int(np.clip(H[low_mask].max() + PAD_H, 0, 179))
    if np.any(high_mask):
        h_min2 = int(np.clip(H[high_mask].min() - PAD_H, 0, 179))
        h_max2 = int(np.clip(H[high_mask].max() + PAD_H, 0, 179))

    # If only one wraparound range is populated, give the other an empty
    # interval that matches nothing (e.g. h_min2=180, h_max2=180 — inRange
    # returns 0 for any pixel).
    if h_min1 == h_max1 == 0 and not np.any(low_mask):
        h_min1, h_max1 = 0, 0
    if not np.any(high_mask):
        h_min2, h_max2 = 180, 180

    return {"h_min": h_min1, "h_max": h_max1,
            "s_min": s_min,  "s_max": s_max,
            "v_min": v_min,  "v_max": v_max,
            "h_min2": h_min2, "h_max2": h_max2}


# ─────────────────────────────────────────────
# JSON I/O
# ─────────────────────────────────────────────

def load_hsv_file():
    """Load existing hsv_values.json if it exists, else return defaults."""
    if os.path.exists(HSV_FILE):
        try:
            with open(HSV_FILE, "r") as f:
                data = json.load(f)
            print(f"Loaded existing HSV values from {HSV_FILE}")
            # Make sure the wraparound keys exist for red.
            if "red" in data:
                data["red"].setdefault("h_min2", DEFAULTS["red"]["h_min2"])
                data["red"].setdefault("h_max2", DEFAULTS["red"]["h_max2"])
            data.setdefault("ring_tolerance", RING_TOLERANCES[DEFAULT_TOL_IDX])
            data.setdefault("arm_length_px", ARM_LENGTH_PX)
            return data
        except Exception as e:
            print(f"WARN: could not parse {HSV_FILE} ({e}) — using defaults")
    return {
        "green":          dict(DEFAULTS["green"]),
        "red":            dict(DEFAULTS["red"]),
        "ring_tolerance": RING_TOLERANCES[DEFAULT_TOL_IDX],
        "arm_length_px":  ARM_LENGTH_PX,
    }


def save_hsv_file(state):
    """Write data/hsv_values.json plus a human-readable readme."""
    os.makedirs(os.path.dirname(HSV_FILE), exist_ok=True)
    payload = {
        "green":          state["green"],
        "red":            state["red"],
        "ring_tolerance": state["ring_tolerance"],
        "arm_length_px":  ARM_LENGTH_PX,
    }
    with open(HSV_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    with open(HSV_README, "w") as f:
        f.write(_readme_text())
    print(f"Saved {HSV_FILE}")


def _readme_text():
    return (
        "hsv_values.json\n"
        "===============\n\n"
        "Calibrated HSV ranges and ring parameters for ring_tracker.py.\n\n"
        "Fields\n"
        "------\n"
        "green / red       per-marker HSV ranges. OpenCV uses H in [0, 179],\n"
        "                  S and V in [0, 255].\n"
        "  h_min, h_max    hue range\n"
        "  s_min, s_max    saturation range\n"
        "  v_min, v_max    value (brightness) range\n"
        "  h_min2, h_max2  (red only) second hue range to handle wraparound\n"
        "                  near 0/180. Detection mask = (H in [h_min,h_max])\n"
        "                  OR (H in [h_min2,h_max2]), AND saturation/value\n"
        "                  within the configured range.\n\n"
        "ring_tolerance    width (in pixels) of the search annulus around\n"
        "                  the expected arm length. Detection only considers\n"
        "                  pixels within +/- this tolerance of the radius.\n\n"
        "arm_length_px     fixed arm length in pixels for both arms (~188).\n"
    )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

class TunerState:
    """Mutable state shared across the main loop and the mouse callback."""
    def __init__(self):
        self.mode               = "green"           # "green" or "red"
        self.frame_idx          = 0
        self.paused             = True              # pause by default
        self.tol_idx            = DEFAULT_TOL_IDX
        self.green_samples      = []                # [(H,S,V), ...]
        self.red_samples        = []
        self.last_click         = None              # (x_orig, y_orig) for crosshair
        self.last_sample_frame  = -1                # to fade the crosshair
        self.dirty              = False             # any unsaved changes?
        # `data` holds the saved/desired ranges plus tolerance — the active
        # trackbar values are pulled from cv2.getTrackbarPos each frame.
        self.data               = load_hsv_file()
        # Keep tol idx in sync with whatever was saved.
        if self.data["ring_tolerance"] in RING_TOLERANCES:
            self.tol_idx = RING_TOLERANCES.index(self.data["ring_tolerance"])

    @property
    def tolerance(self):
        return RING_TOLERANCES[self.tol_idx]


def display_to_frame(x_disp, y_disp):
    """Map a click in the 960x540 video sub-area back to original 1280x720."""
    if x_disp >= VIDEO_DISP_W or y_disp >= VIDEO_DISP_H:
        return None
    x_orig = int(round(x_disp / DISPLAY_SCALE))
    y_orig = int(round(y_disp / DISPLAY_SCALE))
    x_orig = max(0, min(FRAME_W - 1, x_orig))
    y_orig = max(0, min(FRAME_H - 1, y_orig))
    return (x_orig, y_orig)


def main():
    # ── Parse CLI ────────────────────────────────────────────────────────
    video_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    if not os.path.isabs(video_path):
        video_path = os.path.join(ROOT, video_path)
    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return

    start_frame = 0
    if len(sys.argv) > 2:
        try:
            start_frame = int(sys.argv[2])
        except ValueError:
            print(f"WARN: bad start frame '{sys.argv[2]}', using 0")

    # ── Open video ───────────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: could not open video: {video_path}")
        return
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 59.94

    print("hsv_tuner.py")
    print(f"Video : {video_path}")
    print(f"Frames: {total_frames}  fps: {fps:.2f}")
    print(f"HSV   : {HSV_FILE}")
    print()
    print("Keys: G/R switch marker  A/D step 1  ←/→ step 50  SPACE pause")
    print("      LEFT-CLICK sample  C clear samples  T cycle tolerance")
    print("      S save  Q/ESC quit")
    print()

    state = TunerState()
    state.frame_idx = max(0, min(total_frames - 1, start_frame))

    # Precompute the static pivot distance grid once — used for the green ring.
    pivot_dist_grid = precompute_distance_grid(FRAME_W, FRAME_H, PIVOT)

    # ── Windows + trackbars ──────────────────────────────────────────────
    cv2.namedWindow(WINDOW_MAIN, cv2.WINDOW_AUTOSIZE)
    build_controls_window(state.mode)
    push_cfg_to_trackbars(state.data["green"], "green")

    # ── Mouse callback (eyedropper) ──────────────────────────────────────
    # We need access to the current frame's HSV image; stash it on state.
    state.current_hsv = None

    def on_mouse(event, x, y, flags, _userdata):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        mapped = display_to_frame(x, y)
        if mapped is None:
            return
        ox, oy = mapped
        state.last_click        = (ox, oy)
        state.last_sample_frame = state.frame_idx
        if state.current_hsv is None:
            return
        h, s, v = state.current_hsv[oy, ox]
        sample  = (int(h), int(s), int(v))
        bucket  = (state.green_samples if state.mode == "green"
                   else state.red_samples)
        bucket.append(sample)
        print(f"  sampled @ ({ox},{oy})  H={h}  S={s}  V={v}  "
              f"({state.mode} count: {len(bucket)})")

        # Auto-suggest once we have enough points.
        suggestion = suggest_from_samples(bucket, state.mode)
        if suggestion is not None:
            print(f"  auto-suggest ({state.mode}): {suggestion}")
            state.data[state.mode].update(suggestion)
            push_cfg_to_trackbars(state.data[state.mode], state.mode)
            state.dirty = True

    cv2.setMouseCallback(WINDOW_MAIN, on_mouse)

    # ── Main loop ────────────────────────────────────────────────────────
    last_loaded_idx = -1
    cached_frame   = None
    while True:
        # Read frame only when the index changes — avoids re-decoding while paused.
        if state.frame_idx != last_loaded_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, state.frame_idx)
            ret, frame = cap.read()
            if not ret:
                # Couldn't read — clamp index to the last good frame and retry.
                state.frame_idx = max(0, min(total_frames - 1,
                                             state.frame_idx - 1))
                continue
            cached_frame    = frame
            last_loaded_idx = state.frame_idx

        frame = cached_frame.copy()
        hsv_full = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        state.current_hsv = hsv_full

        # Pull current trackbar values into the active marker's cfg, so any
        # manual slider tweaks are reflected immediately.
        live_cfg = read_cfg_from_trackbars(state.mode)
        # Make sure missing red wraparound keys aren't forwarded for green.
        state.data[state.mode].update(live_cfg)
        if state.mode == "green":
            # Strip any stale wraparound keys for green.
            state.data["green"].pop("h_min2", None)
            state.data["green"].pop("h_max2", None)

        # ── Build the green ring detection ──────────────────────────────
        green_ring = ring_mask_from_distance(pivot_dist_grid,
                                             ARM_LENGTH_PX, state.tolerance)
        green_color = color_mask_green(hsv_full, state.data["green"])
        green_combined = cv2.bitwise_and(green_color,
                                         green_color,
                                         mask=green_ring.astype(np.uint8) * 255)
        green_pos, green_area = largest_centroid(green_combined, min_area=10)
        green_pixel_count = int(np.count_nonzero(green_combined))

        # ── Red detection (depends on green being found) ────────────────
        red_pos = None
        red_area = 0
        red_pixel_count = 0
        red_combined = None
        if green_pos is not None:
            local_dist = precompute_distance_grid(FRAME_W, FRAME_H, green_pos)
            red_ring = ring_mask_from_distance(local_dist, ARM_LENGTH_PX,
                                               state.tolerance)
            red_cfg = state.data["red"]
            # Be defensive: if the red config is missing wraparound keys,
            # fall back to defaults so the mask call doesn't blow up.
            for k in ("h_min2", "h_max2"):
                red_cfg.setdefault(k, DEFAULTS["red"][k])
            red_color = color_mask_red(hsv_full, red_cfg)
            red_combined = cv2.bitwise_and(red_color, red_color,
                                           mask=red_ring.astype(np.uint8) * 255)
            red_pos, red_area = largest_centroid(red_combined, min_area=10)
            red_pixel_count = int(np.count_nonzero(red_combined))

        # ── Draw overlays on the original frame ─────────────────────────
        overlay = frame.copy()

        # Pivot dot.
        cv2.circle(overlay, PIVOT, 8, (0, 215, 255), -1)

        # Green ring.
        cv2.circle(overlay, PIVOT, ARM_LENGTH_PX, (0, 200, 0), 1)

        if green_pos is not None:
            cv2.line(overlay, PIVOT, green_pos, (0, 255, 0), 2)
            cv2.circle(overlay, green_pos, 8, (0, 255, 0), -1)
            theta1 = compute_angle(PIVOT, green_pos)
            cv2.putText(overlay, f"th1={theta1:.1f}",
                        (green_pos[0] + 10, green_pos[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            # Red ring (centred on green).
            cv2.circle(overlay, green_pos, ARM_LENGTH_PX, (0, 0, 200), 1)

            if red_pos is not None:
                cv2.line(overlay, green_pos, red_pos, (0, 0, 255), 2)
                cv2.circle(overlay, red_pos, 8, (0, 0, 255), -1)
                theta2 = compute_angle(green_pos, red_pos)
                cv2.putText(overlay, f"th2={theta2:.1f}",
                            (red_pos[0] + 10, red_pos[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Crosshair on the most recent click (so the user sees what they sampled).
        if state.last_click is not None:
            cx, cy = state.last_click
            cv2.drawMarker(overlay, (cx, cy), (255, 255, 255),
                           cv2.MARKER_CROSS, 18, 2)

        # Frame number / timestamp at the BOTTOM of the frame (per spec).
        ts = state.frame_idx / fps
        bottom_text = (f"frame {state.frame_idx}/{total_frames - 1}   "
                       f"t={ts:.3f}s   tol={state.tolerance}px")
        cv2.putText(overlay, bottom_text,
                    (10, FRAME_H - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Scale the annotated frame to the display panel (uniform 0.75).
        scaled = cv2.resize(overlay, (VIDEO_DISP_W, VIDEO_DISP_H),
                            interpolation=cv2.INTER_AREA)

        # Build the left panel: scaled video on top, info bar below.
        left_panel = np.zeros((DISPLAY_H, LEFT_W, 3), dtype=np.uint8)
        left_panel[:VIDEO_DISP_H, :VIDEO_DISP_W] = scaled

        # Mode badge at top-right of the video region.
        mode_color = (0, 255, 0) if state.mode == "green" else (0, 0, 255)
        cv2.rectangle(left_panel, (VIDEO_DISP_W - 130, 5),
                      (VIDEO_DISP_W - 5, 35), mode_color, -1)
        cv2.putText(left_panel, f"MODE: {state.mode.upper()}",
                    (VIDEO_DISP_W - 122, 27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

        # Status line (just below the video).
        n_g = len(state.green_samples)
        n_r = len(state.red_samples)
        status_lines = [
            (f"samples  GREEN: {n_g}   RED: {n_r}", (240, 240, 240)),
            (f"green ring px: {green_pixel_count}    "
             f"red ring px: {red_pixel_count}",        (200, 200, 200)),
        ]
        if green_pos is None:
            status_lines.append(("DROPOUT: green not found", (80, 80, 255)))
        elif red_pos is None:
            status_lines.append(("DROPOUT: red not found",   (80, 80, 255)))

        if state.paused:
            status_lines.append(("[PAUSED]", (0, 255, 255)))

        if state.dirty:
            status_lines.append(("UNSAVED CHANGES — press S to save",
                                 (0, 215, 255)))

        y = VIDEO_DISP_H + 30
        for txt, col in status_lines:
            cv2.putText(left_panel, txt, (15, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 2)
            y += 30

        # ── Build the right panel (mask preview) ────────────────────────
        active_mask = green_combined if state.mode == "green" else (
            red_combined if red_combined is not None
            else np.zeros((FRAME_H, FRAME_W), dtype=np.uint8))
        # Stretch to fill 320x720. Non-uniform stretch is fine here; the user
        # only needs to see the shape of the detection.
        mask_disp = cv2.resize(active_mask, (RIGHT_W, DISPLAY_H),
                               interpolation=cv2.INTER_NEAREST)
        right_panel = cv2.cvtColor(mask_disp, cv2.COLOR_GRAY2BGR)
        cv2.putText(right_panel, f"{state.mode.upper()} mask",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (0, 255, 0) if state.mode == "green" else (0, 0, 255), 2)

        # Combine.
        display = np.hstack([left_panel, right_panel])
        cv2.imshow(WINDOW_MAIN, display)

        # ── Key handling ────────────────────────────────────────────────
        # waitKey delay: 1ms while playing, 30ms while paused (keeps the UI
        # responsive without spinning at 100% CPU).
        delay = 1 if not state.paused else 30
        key   = cv2.waitKey(delay) & 0xFFFF       # 0xFFFF preserves arrow codes

        if key == 0xFFFF:
            # No key pressed — auto-advance if playing.
            if not state.paused:
                state.frame_idx = min(state.frame_idx + 1, total_frames - 1)
                if state.frame_idx == total_frames - 1:
                    state.paused = True
            continue

        k = key & 0xFF

        # ESC or Q — quit (ask to save first if dirty).
        if k == 27 or k in (ord("q"), ord("Q")):
            if state.dirty:
                ans = input("Unsaved changes. Save before quitting? [y/N]: ")
                if ans.strip().lower().startswith("y"):
                    state.data["ring_tolerance"] = state.tolerance
                    save_hsv_file(state.data)
            break

        if k == ord(" "):
            state.paused = not state.paused
            continue

        if k in (ord("a"), ord("A")):
            state.frame_idx = max(0, state.frame_idx - 1)
            state.paused = True
            continue

        if k in (ord("d"), ord("D")):
            state.frame_idx = min(total_frames - 1, state.frame_idx + 1)
            state.paused = True
            continue

        # Arrow keys: codes vary across OS/builds. The full 16-bit codes for
        # cv2.waitKeyEx are 2424832 (left) / 2555904 (right); for waitKey&0xFFFF
        # they're commonly 81/83 on Linux, 0x250000-stripped values on Windows.
        # To stay portable we accept both 81/83 and 'h'/'l' (vim style) too.
        if k in (81, ord("h")):                  # LEFT
            state.frame_idx = max(0, state.frame_idx - 50)
            state.paused = True
            continue
        if k in (83, ord("l")):                  # RIGHT
            state.frame_idx = min(total_frames - 1, state.frame_idx + 50)
            state.paused = True
            continue

        if k in (ord("g"), ord("G")) and state.mode != "green":
            state.mode = "green"
            build_controls_window(state.mode)
            push_cfg_to_trackbars(state.data["green"], "green")
            print("Mode -> GREEN")
            continue

        if k in (ord("r"), ord("R")) and state.mode != "red":
            state.mode = "red"
            build_controls_window(state.mode)
            push_cfg_to_trackbars(state.data["red"], "red")
            print("Mode -> RED")
            continue

        if k in (ord("c"), ord("C")):
            if state.mode == "green":
                state.green_samples.clear()
            else:
                state.red_samples.clear()
            print(f"Cleared samples for {state.mode.upper()}")
            continue

        if k in (ord("t"), ord("T")):
            state.tol_idx = (state.tol_idx + 1) % len(RING_TOLERANCES)
            state.data["ring_tolerance"] = state.tolerance
            state.dirty = True
            print(f"Ring tolerance -> {state.tolerance}px")
            continue

        if k in (ord("s"), ord("S")):
            state.data["ring_tolerance"] = state.tolerance
            save_hsv_file(state.data)
            state.dirty = False
            continue

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
