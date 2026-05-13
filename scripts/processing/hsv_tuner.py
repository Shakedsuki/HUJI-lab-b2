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
  - Save the calibrated values to a per-video file
    (data/hsv_<videostem>.json) so each video gets its own calibration.
    Pass --global to save to data/hsv_values.json instead, which acts as
    the fallback for any video without its own per-video file.

Why ring-based detection? Because the arm lengths are fixed:
    GREEN sits on a circle of radius ARM_LENGTH_PX around the pivot.
    RED   sits on a circle of radius ARM_LENGTH_PX around the green marker.
This collapses the search from ~921k pixels to ~1.2k per ring and is robust
to motion blur (no temporal model, no appearance drift).

Usage:
  python scripts/processing/hsv_tuner.py                                       # default video, save to global
  python scripts/processing/hsv_tuner.py data/videos/long_recording.mov             # save to per-video file
  python scripts/processing/hsv_tuner.py data/videos/long_recording.mov 200         # start at frame 200
  python scripts/processing/hsv_tuner.py data/videos/long_recording.mov --global    # force save to global

Keys
  marker     : G green   R red   LEFT-CLICK sample circle around cursor
  navigate   : a/d ±1   ←/→ ±50   SPACE pause/play
  view       : Z zoom loupe   +/- magnification 2x..8x   M overlay (full/min/clean)
  edit       : [/] shrink/grow click radius   C clear samples   T cycle ring tolerance
  commit     : S save HSV file   Q/ESC quit (prompts if unsaved)

LEFT-CLICK draws a circle of the current radius (default 25 px,
adjustable with [ and ]) around the click point and keeps every
pixel whose HSV is close to the centre's. The HSV-similarity filter
discards background, so a generous radius is fine. The cursor shows
a live preview circle so you see what would be sampled before
clicking. Auto-advances to the next reference frame after each
successful sample.
"""

import cv2
import numpy as np
import json
import os
import sys

_HSV_TUNER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HSV_TUNER_DIR, os.pardir, "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from thresholds import PIVOT, ARM_LENGTH_PX  # noqa: E402

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

DEFAULT_VIDEO    = next(
    (os.path.join(VIDEOS_DIR, f) for f in sorted(os.listdir(VIDEOS_DIR))
     if f.lower().endswith(".mov")),
    None) if os.path.isdir(VIDEOS_DIR) else None

GLOBAL_HSV_FILE  = os.path.join(DATA_DIR, "hsv_values.json")
HSV_README       = os.path.join(DATA_DIR, "hsv_values_readme.txt")

def hsv_file_for_video(video_path, force_global=False):
    """
    Per-video HSV file path: data/hsv_<videostem>.json. With force_global
    or no video, returns the global path (data/hsv_values.json).
    """
    if force_global or not video_path:
        return GLOBAL_HSV_FILE
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(DATA_DIR, f"hsv_{stem}.json")

# Brief 10b: PIVOT and ARM_LENGTH_PX imported from thresholds.py above.

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

# Zoom loupe — magnified inset that follows the cursor so the user can
# pick individual marker pixels without misclicking onto neighbouring
# wall texture. Source region is INSET_PX/zoom_factor pixels wide in
# the original frame; the inset itself is drawn INSET_PX × INSET_PX.
INSET_PX        = 240
ZOOM_FACTORS    = [2, 3, 4, 6, 8]
DEFAULT_ZOOM_IDX = 2           # 4x magnification by default

# Overlay levels cycled by M:
#   0 = full     — rings + markers + labels + click crosshair (current default)
#   1 = minimal  — only the click crosshair, raw pixels otherwise
#   2 = clean    — raw frame with no overlays at all
OVERLAY_FULL, OVERLAY_MINIMAL, OVERLAY_CLEAN = 0, 1, 2
OVERLAY_LABELS = {OVERLAY_FULL: "FULL", OVERLAY_MINIMAL: "MIN",
                  OVERLAY_CLEAN: "CLEAN"}

# Circle / region sampling thresholds. After the user drags a circle,
# we keep only pixels whose HSV is within these deltas of the centre
# pixel — the rest (wall, arm shaft) get filtered out. The auto-
# suggester then operates on a relevant sample set, not on everything
# the circle happened to enclose.
CIRCLE_DELTA_H        = 12
CIRCLE_DELTA_S        = 50
CIRCLE_DELTA_V        = 50
CIRCLE_MAX_SAMPLES    = 80          # cap so one click doesn't drown out
                                    # earlier samples
CIRCLE_MIN_RADIUS_PX  = 4           # safety floor (used only if state
                                    # somehow ends up below it)

# Click-to-sample circle. LEFT-CLICK draws a circle of `click_radius`
# around the click and keeps every pixel whose HSV is close to the
# centre's. Cursor hover previews the circle so the user sees exactly
# what will be sampled before clicking. [ and ] adjust the radius.
CLICK_RADIUS_DEFAULT  = 25
CLICK_RADIUS_MIN      = 5
CLICK_RADIUS_MAX      = 60
CLICK_RADIUS_STEP     = 5

# Auto-advance reference frames — distributed across the clip so a
# single sampling pass naturally captures lighting variation. After
# every successful click sample we jump to the next entry in this
# queue; after the last entry we stop auto-advancing. Mode switch
# (G/R) and the C clear-key reset the queue to entry 0.
AUTO_ADVANCE_FRACTIONS = [0.10, 0.35, 0.65, 0.90]
SAMPLE_TARGET          = 6          # min samples per marker before "ready"

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

def largest_centroid(mask_uint8, min_area=10, max_radius=35):
    """
    Find the largest connected component in `mask_uint8` (0/255) and return
    its centroid (cx, cy) plus area, or (None, 0) if nothing meaningful.

    Uses connectedComponentsWithStats so we get the *true* pixel area of
    each blob and the moment-based centroid of those pixels. The earlier
    findContours + cv2.contourArea + cv2.moments(contour) approach had a
    silent failure mode for annular (ring-shaped) blobs: when the green or
    red HSV mask was permissive enough to fire on background pixels around
    the entire search ring, the resulting connected component traced an
    annulus. RETR_EXTERNAL returned a single outer contour whose enclosed
    polygon area = π·r² (pivot-to-outer-radius squared) — orders of magnitude
    larger than the actual lit-pixel count — and the moments of that polygon
    placed the centroid at the geometric center of the ring (i.e., the
    pivot). Both markers then collapsed to the pivot in the preview, the
    "th2" angle was meaningless, and the user couldn't tell from the overlay
    alone what had gone wrong.

    `max_radius` rejects blobs whose smallest enclosing circle is wider
    than this (px). Markers on this rig are ≤ ~25 px across, so 35 px is
    a safe ceiling that excludes annular-noise blobs (which would have
    radius ≥ ARM_LENGTH_PX + tolerance) without affecting real markers.
    """
    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask_uint8, connectivity=8)
    if n_labels < 2:  # only background
        return None, 0

    best_idx = -1
    best_area = 0
    for i in range(1, n_labels):  # skip background (label 0)
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        # Reject sprawling annular blobs by extent.
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        bbox_radius = 0.5 * float(np.hypot(w, h))
        if bbox_radius > max_radius:
            continue
        if area > best_area:
            best_area = area
            best_idx = i

    if best_idx < 0:
        return None, 0
    cx, cy = centroids[best_idx]
    return (int(round(cx)), int(round(cy))), best_area

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

def load_hsv_file(target_path):
    """
    Load HSV values from `target_path` if it exists. If not, fall back to
    the global file (when target is per-video) so the user starts from a
    sensible baseline rather than the hard-coded defaults. Returns a dict
    with the standard fields filled in.
    """
    candidates = [target_path]
    if target_path != GLOBAL_HSV_FILE:
        candidates.append(GLOBAL_HSV_FILE)

    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                print(f"Loaded HSV values from {path}")
                if "red" in data:
                    data["red"].setdefault("h_min2", DEFAULTS["red"]["h_min2"])
                    data["red"].setdefault("h_max2", DEFAULTS["red"]["h_max2"])
                data.setdefault("ring_tolerance", RING_TOLERANCES[DEFAULT_TOL_IDX])
                data.setdefault("arm_length_px", ARM_LENGTH_PX)
                return data
            except Exception as e:
                print(f"WARN: could not parse {path} ({e}) — trying next")

    return {
        "green":          dict(DEFAULTS["green"]),
        "red":            dict(DEFAULTS["red"]),
        "ring_tolerance": RING_TOLERANCES[DEFAULT_TOL_IDX],
        "arm_length_px":  ARM_LENGTH_PX,
    }

def save_hsv_file(state, target_path):
    """Write HSV calibration JSON plus the (global) human-readable readme."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    payload = {
        "green":          state["green"],
        "red":            state["red"],
        "ring_tolerance": state["ring_tolerance"],
        "arm_length_px":  ARM_LENGTH_PX,
    }
    with open(target_path, "w") as f:
        json.dump(payload, f, indent=2)
    # Readme describes the schema, not the values — write once globally.
    with open(HSV_README, "w") as f:
        f.write(_readme_text())
    print(f"Saved {target_path}")

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
    def __init__(self, target_path):
        self.mode               = "green"           # "green" or "red"
        self.frame_idx          = 0
        self.paused             = True              # pause by default
        self.tol_idx            = DEFAULT_TOL_IDX
        self.green_samples      = []                # [(H,S,V), ...]
        self.red_samples        = []
        self.last_click         = None              # (x_orig, y_orig) for crosshair
        self.last_sample_frame  = -1                # to fade the crosshair
        self.dirty              = False             # any unsaved changes?
        # Cursor tracking for the zoom loupe. cursor_orig is in the
        # original 1280x720 frame; cursor_disp is in display coords (the
        # 960x540 video sub-region). Both stay in sync via the mouse
        # callback handling EVENT_MOUSEMOVE.
        self.cursor_orig        = None
        self.cursor_disp        = None
        self.zoom_on            = False
        self.zoom_idx           = DEFAULT_ZOOM_IDX
        self.overlay_level      = OVERLAY_FULL
        # Click-to-sample radius. LEFT-CLICK samples a circle of this
        # radius (in original-frame pixels) around the click point.
        # [ and ] adjust it; the cursor preview shows the current value.
        self.click_radius       = CLICK_RADIUS_DEFAULT
        # Auto-advance reference queue. Populated in main() once total_frames
        # is known. Each successful click sample advances the pointer.
        self.ref_queue          = []
        self.ref_queue_idx      = 0
        # Where this session reads from / saves to. Per-video by default;
        # global with --global. Caller passes the resolved path.
        self.target_path        = target_path
        # `data` holds the saved/desired ranges plus tolerance — the active
        # trackbar values are pulled from cv2.getTrackbarPos each frame.
        self.data               = load_hsv_file(target_path)
        # Keep tol idx in sync with whatever was saved.
        if self.data["ring_tolerance"] in RING_TOLERANCES:
            self.tol_idx = RING_TOLERANCES.index(self.data["ring_tolerance"])

    @property
    def tolerance(self):
        return RING_TOLERANCES[self.tol_idx]

    @property
    def zoom_factor(self):
        return ZOOM_FACTORS[self.zoom_idx]

def display_to_frame(x_disp, y_disp):
    """Map a click in the 960x540 video sub-area back to original 1280x720."""
    if x_disp >= VIDEO_DISP_W or y_disp >= VIDEO_DISP_H:
        return None
    x_orig = int(round(x_disp / DISPLAY_SCALE))
    y_orig = int(round(y_disp / DISPLAY_SCALE))
    x_orig = max(0, min(FRAME_W - 1, x_orig))
    y_orig = max(0, min(FRAME_H - 1, y_orig))
    return (x_orig, y_orig)

def sample_circle_region(hsv_full, center_orig, radius_orig):
    """
    Return a list of (H, S, V) samples drawn from the circle of radius
    `radius_orig` around `center_orig` in the original-frame HSV image.
    Filters to pixels whose HSV is "close" to the centre pixel
    (|ΔH|<CIRCLE_DELTA_H, ΔS<CIRCLE_DELTA_S, ΔV<CIRCLE_DELTA_V) so wall
    / arm-shaft pixels enclosed by a sloppy circle don't pollute the
    range. Subsamples to CIRCLE_MAX_SAMPLES if more pixels survive.
    Hue distance accounts for the [0, 180) wrap.
    """
    if radius_orig < CIRCLE_MIN_RADIUS_PX:
        return [], 0  # ignore accidental tiny drags

    cx, cy = center_orig
    h, w = hsv_full.shape[:2]
    x0 = max(0, cx - radius_orig)
    y0 = max(0, cy - radius_orig)
    x1 = min(w, cx + radius_orig + 1)
    y1 = min(h, cy + radius_orig + 1)
    sub = hsv_full[y0:y1, x0:x1]
    sub_cy = cy - y0
    sub_cx = cx - x0

    # Mask: pixels inside the circle.
    ys, xs = np.indices(sub.shape[:2], dtype=np.int32)
    dist2 = (xs - sub_cx) ** 2 + (ys - sub_cy) ** 2
    in_circle = dist2 <= radius_orig ** 2

    if not in_circle.any():
        return [], 0

    # Centre pixel HSV is the colour seed.
    seed_h, seed_s, seed_v = (int(v) for v in hsv_full[cy, cx])

    H = sub[..., 0].astype(np.int32)
    S = sub[..., 1].astype(np.int32)
    V = sub[..., 2].astype(np.int32)

    # Hue distance with wraparound at 180.
    d_hue = np.minimum(np.abs(H - seed_h), 180 - np.abs(H - seed_h))
    keep = (in_circle &
            (d_hue <= CIRCLE_DELTA_H) &
            (np.abs(S - seed_s) <= CIRCLE_DELTA_S) &
            (np.abs(V - seed_v) <= CIRCLE_DELTA_V))

    n_kept = int(keep.sum())
    if n_kept == 0:
        return [], 0

    h_kept = H[keep]
    s_kept = S[keep]
    v_kept = V[keep]

    # Subsample to a sensible cap so one drag doesn't dominate the
    # auto-suggester's input over earlier point clicks.
    n_take = min(CIRCLE_MAX_SAMPLES, n_kept)
    if n_take < n_kept:
        idx = np.random.default_rng(seed=cx * 31 + cy).choice(
            n_kept, size=n_take, replace=False)
        h_kept = h_kept[idx]
        s_kept = s_kept[idx]
        v_kept = v_kept[idx]

    samples = list(zip(h_kept.tolist(), s_kept.tolist(), v_kept.tolist()))
    return samples, n_kept

def main():
    # ── Parse CLI ────────────────────────────────────────────────────────
    raw_args   = sys.argv[1:]
    flags      = [a for a in raw_args if a.startswith("--")]
    positional = [a for a in raw_args if not a.startswith("--")]
    force_global = "--global" in flags

    video_path = positional[0] if positional else DEFAULT_VIDEO
    if not os.path.isabs(video_path):
        video_path = os.path.join(REPO_ROOT, video_path)
    if not os.path.exists(video_path):
        print(f"ERROR: video not found: {video_path}")
        return

    start_frame = 0
    if len(positional) > 1:
        try:
            start_frame = int(positional[1])
        except ValueError:
            print(f"WARN: bad start frame '{positional[1]}', using 0")

    # Resolve the per-video / global HSV path that this session will read
    # from on launch and write to on save.
    target_path = hsv_file_for_video(video_path, force_global=force_global)
    target_kind = "GLOBAL" if target_path == GLOBAL_HSV_FILE else "PER-VIDEO"

    # ── Open video ───────────────────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: could not open video: {video_path}")
        return
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 59.94

    bar = "=" * 72
    print(bar)
    print(f"hsv_tuner.py  —  {os.path.basename(video_path)}")
    print(bar)
    print("Why")
    print("  Sample green and red marker pixels in this clip's lighting so")
    print("  the tracker can find them. (Run when HSV adequacy ABORTed.)")
    print()
    print("Steps")
    print(f"  1. Hover the cursor over the GREEN marker — a {CLICK_RADIUS_DEFAULT}px circle")
    print(f"     previews what would be sampled. Adjust with [/] if needed.")
    print(f"  2. LEFT-CLICK to sample. Auto-advances to the next reference")
    print(f"     frame ({len(AUTO_ADVANCE_FRACTIONS)} total — covers lighting variation).")
    print(f"  3. After ≥{SAMPLE_TARGET} green samples, press R and repeat for RED.")
    print(f"  4. Scrub the clip; rings should lock on the markers.")
    print()
    print("Done when")
    print(f"  GREEN ≥{SAMPLE_TARGET}, RED ≥{SAMPLE_TARGET}, rings track during scrub. Then S → Q.")
    print()
    print("Keys")
    print("  marker     : G green   R red   LEFT-CLICK sample circle around cursor")
    print("  navigate   : a/d ±1   ←/→ ±50   SPACE pause/play")
    print("  view       : Z zoom loupe   +/- magnification 2x..8x   "
          "M overlay (full/min/clean)")
    print("  edit       : [/] shrink/grow click radius   C clear samples   "
          "T cycle ring tolerance")
    print("  commit     : S save HSV file   Q/ESC quit")
    print()
    print("Status")
    print(f"  video      : {video_path}")
    print(f"  frames     : {total_frames}   fps: {fps:.2f}")
    print(f"  HSV file   : {target_path}   [{target_kind}]")
    print()

    state = TunerState(target_path)
    # Auto-advance reference queue spans the clip evenly.
    state.ref_queue = sorted({
        max(0, min(total_frames - 1, int(f * total_frames)))
        for f in AUTO_ADVANCE_FRACTIONS
    })
    # Start at the first reference frame (or wherever caller asked).
    state.frame_idx = (start_frame if start_frame else state.ref_queue[0]
                       if state.ref_queue else 0)
    state.frame_idx = max(0, min(total_frames - 1, state.frame_idx))

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
        # Always track cursor position so the hover preview + loupe
        # follow the cursor.
        mapped = display_to_frame(x, y)
        if mapped is not None:
            state.cursor_disp = (x, y)
            state.cursor_orig = mapped
        else:
            state.cursor_disp = None
            state.cursor_orig = None

        # Sample on a left-click. Centre = click point, radius =
        # state.click_radius. The HSV-similarity filter inside
        # sample_circle_region drops pixels far from the centre's HSV,
        # so the radius can be generous without polluting the bucket.
        if event != cv2.EVENT_LBUTTONDOWN or mapped is None:
            return
        if state.current_hsv is None:
            return

        cc = mapped
        rr = max(CIRCLE_MIN_RADIUS_PX, int(state.click_radius))
        samples, n_kept = sample_circle_region(state.current_hsv, cc, rr)
        if not samples:
            print(f"  click @ ({cc[0]},{cc[1]}) r={rr}px — "
                  f"no pixels matched the centre's HSV "
                  f"(try a different spot or adjust [/])")
            return
        bucket = (state.green_samples if state.mode == "green"
                  else state.red_samples)
        bucket.extend(samples)
        state.last_click        = cc
        state.last_sample_frame = state.frame_idx
        print(f"  click @ ({cc[0]},{cc[1]}) r={rr}px — "
              f"{n_kept} pixels matched, {len(samples)} added "
              f"({state.mode} count: {len(bucket)})")

        suggestion = suggest_from_samples(bucket, state.mode)
        if suggestion is not None:
            print(f"  auto-suggest ({state.mode}): {suggestion}")
            state.data[state.mode].update(suggestion)
            push_cfg_to_trackbars(state.data[state.mode], state.mode)
            state.dirty = True

        # Auto-advance to the next reference frame, if any remain.
        if (state.ref_queue
                and state.ref_queue_idx + 1 < len(state.ref_queue)):
            state.ref_queue_idx += 1
            state.frame_idx = state.ref_queue[state.ref_queue_idx]
            print(f"  → auto-advance to reference frame "
                  f"{state.frame_idx} "
                  f"({state.ref_queue_idx + 1}/{len(state.ref_queue)})")

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
        # The zoom-loupe inset is built from the RAW frame (pre-overlay)
        # below, so make a copy for the inset before any drawing.
        raw_frame_for_zoom = frame.copy() if state.zoom_on else None
        overlay = frame.copy()

        # Marker overlays (rings, lines, labels) only at OVERLAY_FULL.
        if state.overlay_level == OVERLAY_FULL:
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

        # Click crosshair shown at FULL and MINIMAL — useful for verifying
        # which pixel the last sample came from. Hidden only at CLEAN.
        if (state.overlay_level != OVERLAY_CLEAN
                and state.last_click is not None):
            cx, cy = state.last_click
            cv2.drawMarker(overlay, (cx, cy), (255, 255, 255),
                           cv2.MARKER_CROSS, 18, 2)

        # Hover preview — show the click-sample circle at the cursor so
        # the user sees exactly what would be sampled before clicking.
        # Drawn in mode colour with a thin outline; suppressed at CLEAN
        # so the user can verify mask quality unobstructed.
        if (state.overlay_level != OVERLAY_CLEAN
                and state.cursor_orig is not None):
            ring_color = ((0, 255, 0) if state.mode == "green"
                          else (0, 0, 255))
            cv2.circle(overlay, state.cursor_orig,
                       int(state.click_radius), ring_color, 1)

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

        # ── Zoom loupe — magnified inset following the cursor ─────────
        # Helps the user click individual marker pixels without
        # misclicking onto neighbouring wall texture or arm shaft.
        # The inset is drawn on the LEFT panel (display coordinates),
        # but its source pixels come from the RAW frame so the loupe
        # doesn't include the rings/lines from the overlay.
        if (state.zoom_on and state.cursor_orig is not None
                and raw_frame_for_zoom is not None):
            zf  = state.zoom_factor
            src = INSET_PX // zf            # source region size (px in original frame)
            cx, cy = state.cursor_orig
            x0 = max(0, min(FRAME_W - src, cx - src // 2))
            y0 = max(0, min(FRAME_H - src, cy - src // 2))
            crop = raw_frame_for_zoom[y0:y0 + src, x0:x0 + src]
            inset = cv2.resize(crop, (INSET_PX, INSET_PX),
                               interpolation=cv2.INTER_NEAREST)
            # Crosshair at the inset centre (= cursor position).
            mid = INSET_PX // 2
            cv2.drawMarker(inset, (mid, mid), (255, 255, 255),
                           cv2.MARKER_CROSS, 24, 1)

            # Project the click-sample preview circle into the loupe so
            # the user can see exactly what pixels would be sampled,
            # zoomed. The circle is centred on the cursor, which is
            # exactly the inset's middle (mid, mid) by construction.
            ring_color = ((0, 255, 0) if state.mode == "green"
                          else (0, 0, 255))
            cv2.circle(inset, (mid, mid),
                       int(state.click_radius) * zf, ring_color, 1)

            cv2.rectangle(inset, (0, 0),
                          (INSET_PX - 1, INSET_PX - 1), (255, 255, 255), 2)
            cv2.putText(inset, f"ZOOM {zf}x",
                        (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 2)

            # Place the inset in the top-left corner of the video region.
            # Avoid covering the marker area in the centre of the frame.
            ix, iy = 5, 5
            left_panel[iy:iy + INSET_PX, ix:ix + INSET_PX] = inset

        # ── Goal ribbon — top-center of the video panel ────────────────
        # Sits between the zoom-inset (top-left, eats x ≤ 250 when on)
        # and the mode badge (top-right, eats x ≥ 830). Two lines:
        # GOAL (mode-dependent imperative) and PROGRESS (sample counts +
        # auto-advance pointer + S-to-save once both targets met).
        n_g = len(state.green_samples)
        n_r = len(state.red_samples)
        ready = n_g >= SAMPLE_TARGET and n_r >= SAMPLE_TARGET
        if state.mode == "green":
            goal_text = (f"GOAL: click the GREEN marker  "
                         f"(circle r={int(state.click_radius)}px, [/] adjust)")
        else:
            goal_text = (f"GOAL: click the RED marker  "
                         f"(circle r={int(state.click_radius)}px, [/] adjust)")
        if ready:
            goal_text = "READY: scrub the clip — rings should lock on markers"

        g_chk = " OK" if n_g >= SAMPLE_TARGET else ""
        r_chk = " OK" if n_r >= SAMPLE_TARGET else ""
        progress = (f"GREEN {n_g}/{SAMPLE_TARGET}+{g_chk}   "
                    f"RED {n_r}/{SAMPLE_TARGET}+{r_chk}")
        if state.ref_queue:
            progress += (f"   frame {state.ref_queue_idx + 1}/"
                         f"{len(state.ref_queue)}")
        if ready:
            progress += "   ->  press S to save"

        rib_x0, rib_y0 = 252, 4
        rib_x1, rib_y1 = VIDEO_DISP_W - 135, 50
        cv2.rectangle(left_panel, (rib_x0, rib_y0), (rib_x1, rib_y1),
                      (40, 40, 40), -1)
        cv2.rectangle(left_panel, (rib_x0, rib_y0), (rib_x1, rib_y1),
                      (220, 220, 220), 1)
        cv2.putText(left_panel, goal_text,
                    (rib_x0 + 10, rib_y0 + 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 2)
        cv2.putText(left_panel, progress,
                    (rib_x0 + 10, rib_y0 + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (200, 220, 200) if ready else (220, 220, 220), 1)

        # Mode badge at top-right of the video region.
        mode_color = (0, 255, 0) if state.mode == "green" else (0, 0, 255)
        cv2.rectangle(left_panel, (VIDEO_DISP_W - 130, 5),
                      (VIDEO_DISP_W - 5, 35), mode_color, -1)
        cv2.putText(left_panel, f"MODE: {state.mode.upper()}",
                    (VIDEO_DISP_W - 122, 27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

        # Overlay-level badge below the mode badge (small, easy to ignore
        # when full but visible enough that the user knows why the rings
        # have disappeared in MINIMAL/CLEAN mode).
        if state.overlay_level != OVERLAY_FULL:
            badge_y = 42
            cv2.rectangle(left_panel, (VIDEO_DISP_W - 130, badge_y),
                          (VIDEO_DISP_W - 5, badge_y + 24),
                          (60, 60, 60), -1)
            cv2.putText(left_panel,
                        f"OVERLAY: {OVERLAY_LABELS[state.overlay_level]}",
                        (VIDEO_DISP_W - 122, badge_y + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (220, 220, 220), 1)

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
                    save_hsv_file(state.data, state.target_path)
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
            # Restart the auto-advance queue for the new colour pass.
            if state.ref_queue:
                state.ref_queue_idx = 0
                state.frame_idx = state.ref_queue[0]
            print(f"Mode -> GREEN  (auto-advance queue reset to frame "
                  f"{state.frame_idx})")
            continue

        if k in (ord("r"), ord("R")) and state.mode != "red":
            state.mode = "red"
            build_controls_window(state.mode)
            push_cfg_to_trackbars(state.data["red"], "red")
            if state.ref_queue:
                state.ref_queue_idx = 0
                state.frame_idx = state.ref_queue[0]
            print(f"Mode -> RED  (auto-advance queue reset to frame "
                  f"{state.frame_idx})")
            continue

        if k in (ord("c"), ord("C")):
            if state.mode == "green":
                state.green_samples.clear()
            else:
                state.red_samples.clear()
            # Clearing implies a fresh sampling pass; restart the queue.
            if state.ref_queue:
                state.ref_queue_idx = 0
                state.frame_idx = state.ref_queue[0]
            print(f"Cleared samples for {state.mode.upper()}  "
                  f"(auto-advance queue reset)")
            continue

        if k in (ord("t"), ord("T")):
            state.tol_idx = (state.tol_idx + 1) % len(RING_TOLERANCES)
            state.data["ring_tolerance"] = state.tolerance
            state.dirty = True
            print(f"Ring tolerance -> {state.tolerance}px")
            continue

        if k in (ord("s"), ord("S")):
            state.data["ring_tolerance"] = state.tolerance
            save_hsv_file(state.data, state.target_path)
            state.dirty = False
            continue

        if k in (ord("z"), ord("Z")):
            state.zoom_on = not state.zoom_on
            print(f"Zoom loupe -> {'ON' if state.zoom_on else 'OFF'} "
                  f"({state.zoom_factor}x)")
            continue

        if k in (ord("m"), ord("M")):
            state.overlay_level = (state.overlay_level + 1) % 3
            print(f"Overlay -> {OVERLAY_LABELS[state.overlay_level]}")
            continue

        if k in (ord("+"), ord("=")):
            state.zoom_idx = min(len(ZOOM_FACTORS) - 1, state.zoom_idx + 1)
            print(f"Zoom magnification -> {state.zoom_factor}x")
            continue

        if k in (ord("-"), ord("_")):
            state.zoom_idx = max(0, state.zoom_idx - 1)
            print(f"Zoom magnification -> {state.zoom_factor}x")
            continue

        if k == ord("["):
            state.click_radius = max(CLICK_RADIUS_MIN,
                                     state.click_radius - CLICK_RADIUS_STEP)
            print(f"Click sample radius -> {state.click_radius}px")
            continue

        if k == ord("]"):
            state.click_radius = min(CLICK_RADIUS_MAX,
                                     state.click_radius + CLICK_RADIUS_STEP)
            print(f"Click sample radius -> {state.click_radius}px")
            continue

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
