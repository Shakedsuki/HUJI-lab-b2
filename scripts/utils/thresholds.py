"""
thresholds.py
--------------
Single source of truth for the verdict threshold and the BGR-tracker
crop / colour constants used across the pipeline.

Verdict is binary: PASS or FAIL.
  * dropout > DROPOUT_FAIL_PCT  → FAIL
  * otherwise                   → PASS

That's it. One criterion.

Conventions
~~~~~~~~~~~
- All percentages are 0-100 floats (NOT 0-1).
- All angular velocities are in degrees / second.
"""

import os as _os

# Canonical phase names — mirror scripts/utils/paths.py exactly.
_PHASE_FREE   = "week3-4-pendulum-free-swing"
_PHASE_WEEK5  = "week5-pendulum-motor-driven"
_PHASE_WEEK6  = "week6-pendulum-motor-driven"
_PHASE_DRIVEN = "week5-6-pendulum-motor-driven"  # legacy combined; aliases to week6

# Legacy-name aliases mirror scripts/utils/paths.py — keep in sync.
_LEGACY_ALIASES = {
    "phase1-free-swing":           _PHASE_FREE,
    "phase2-motor-driven":         _PHASE_WEEK6,
    "week3-pendulum-free-swing":   _PHASE_FREE,
    "week4-pendulum-motor-driven": _PHASE_WEEK6,
    _PHASE_DRIVEN:                 _PHASE_WEEK6,
}
_raw_phase = _os.environ.get("CHAOS_PHASE", _PHASE_WEEK6)
_PHASE     = _LEGACY_ALIASES.get(_raw_phase, _raw_phase)
_IS_DRIVEN = _PHASE != _PHASE_FREE   # any motor-driven phase (week5 or week6)

# Verdict threshold — single criterion.
DROPOUT_FAIL_PCT     = 5.0      # > this → FAIL

# Bar-scale maximum — used by render.py to size the dropout bar in
# the verdict card so the bar length is comparable across runs.
DROPOUT_BAR_MAX      = 7.5      # 1.5× the FAIL line

# ARM_LENGTH_CM: physical arm length, used by analysis scripts that
# convert pixel measurements to physical units. Phase-aware because the
# Week 3 rig used a 35 cm arm and the Week 4 rig was repositioned with
# a 33.1 cm effective length (see PIVOT/ARM_LENGTH_PX block below for
# the derivation).
if _IS_DRIVEN:
    # Cross-phase digital calibration (2026-05-13):
    # Phase 1 scale = 35.0 cm / 162 px = 0.2160 cm/px.
    # Phase 2 ARM_LENGTH_PX = 153 px (circle fit, p95 residual 2.0 px).
    # PIVOT shift Phase1->Phase2 is only 56px right / 25px up — rig repositioned,
    # camera distance unchanged. => 153 * 0.2160 = 33.1 cm.
    ARM_LENGTH_CM = 33.1
else:
    ARM_LENGTH_CM = 35.0   # Phase 1, physical arm length in cm

# Fixed pivot pixel location and arm length — sole source of truth
# for all geometry in the pipeline. Imported by ring_tracker.py and
# verify_tracking.py; do not redefine locally.
#
# Phase 1 calibration (2026-05-02): circle fit on three clips,
#   th1_p044_th2_m001  center (607.91, 357.06)  r = 158.85 px
#   th1_p047_th2_m002  center (608.64, 355.13)  r = 161.21 px
#   th1_p180_th2_m179  center (608.44, 355.43)  r = 161.94 px  (std 0.46 px)
# Values rounded from the long-recording fit (highest angular coverage).
#
# Phase 2 calibration (2026-05-13): circle fit on three driven clips,
#   3V_1Hz.mov + 4V_1Hz.mov + 4V_2Hz.mov
#   center (663.7, 329.7)  r = 153.0 px
#   fit residuals: std=0.58px  median=0.81px  p95=2.01px  (3308 inliers)
if _IS_DRIVEN:
    PIVOT         = (663, 332)   # refined by hsv_tuner P-key (2026-05-13)
    ARM_LENGTH_PX = 153
else:
    PIVOT         = (608, 355)
    ARM_LENGTH_PX = 162

# 3.2V sweep was recorded after the rig was repositioned (~80 px left,
# ~5 % scale change). Green-trace circle fit on 3.2V_0.91Hz and
# 3.2V_1.34Hz gives center (583, 331) with radius 161 px, residual
# std 0.58–0.68 px. 3.2V_1Hz predates the sweep and uses the original
# rig — exclude it explicitly in get_pivot_arm() below.
PIVOT_3_2V         = (583, 331)
ARM_LENGTH_PX_3_2V = 161


def get_pivot_arm(stem):
    """Return (pivot, arm_length_px) for a clip stem.

    Per-batch rig calibration. Most consumers (bgr_tracker,
    combined_video.make_left_panel, overlay_video) call this with the
    clip's stem; defaults to the canonical PIVOT/ARM_LENGTH_PX above
    when stem is None or doesn't match a known batch prefix.
    """
    if stem and stem.startswith("3.2V_") and stem != "3.2V_1Hz":
        return PIVOT_3_2V, ARM_LENGTH_PX_3_2V
    return PIVOT, ARM_LENGTH_PX

# BGR tracker crop window — Cohen's original X-only crop from
# chaos/get_video_coords.py. No Y bound: any Y crop tight enough to
# exclude the upper wall fabric on low-amplitude 3.2V clips also cut
# off legitimate red-marker positions in high-amplitude clips like
# 4V_0.6Hz (98% → 75% both-found regression). Reverted in PR #43.
CROP_X_START = 350
CROP_X_END   = 950

# BGR colour ranges (NOT HSV). cv2.inRange-compatible (lo, hi) tuples.
# Both green and red use sequential fallback ranges — first non-empty
# mask wins — so the strict primary range governs the ~96% of frames
# with a sharp marker and a looser range only ever runs on a frame the
# primary already missed (zero change to frames the primary detects).
#
# GREEN_BGR_RANGES: the primary box is the sharp-marker green. The
# fallback drops the G floor (100->80) and lifts the B/R ceilings to
# catch the marker on high-speed frames where motion blur dims and
# desaturates green just past the primary box (measured on 4V low-freq
# clips: blurred-green pixels fall to G~=87, R~=108). It recovers 100%
# of those blur dropouts as tight ~2k-px blobs at the true position;
# loosening further (G floor <=70) floods the reachable disc with
# background, so the fallback stops at this one widened step.
GREEN_BGR_LO = (0, 100, 0)
GREEN_BGR_HI = (70, 255, 90)
GREEN_BGR_RANGES = (
    (GREEN_BGR_LO, GREEN_BGR_HI),    # primary: sharp marker
    ((0, 80, 0), (90, 255, 115)),    # fallback: motion-blurred marker
)
RED_BGR_RANGES = (
    ((0, 0, 100), (45, 75, 255)),
    ((0, 0, 110), (60, 80, 255)),
    ((0, 0, 125), (75, 95, 255)),
)
