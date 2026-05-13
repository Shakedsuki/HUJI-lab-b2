"""
thresholds.py
--------------
Single source of truth for the verdict-band thresholds and bar-scale
constants used across track_one, render, and any other tooling that
reports on tracking quality.

Why this module exists
~~~~~~~~~~~~~~~~~~~~~~
PASS_DROPOUT_PCT, WARN_DROPOUT_PCT, PEAK_OMEGA_PHYSICAL, and
PEAK_OMEGA_ABSURD show up in two places: the verdict-computation logic
in track_one.compute_verdict, and any pretty-printing layer that
colour-codes those numbers (now scripts/utils/render.py). Defining
them in one module guarantees the verdict label and its visual
representation can never drift out of sync.

Constants are plain literals; importers use them via
`from scripts.utils.thresholds import PASS_DROPOUT_PCT` etc.

Conventions
~~~~~~~~~~~
- All percentages are 0-100 floats (NOT 0-1).
- All angular velocities are in degrees / second.
"""

import os as _os

_PHASE = _os.environ.get("CHAOS_PHASE", "phase1-free-swing")

# Verdict bands — applied to free-swing dropout %.
PASS_DROPOUT_PCT     = 5.0      # ≤ this → PASS
WARN_DROPOUT_PCT     = 10.0     # ≤ this → WARN; > this → FAIL

# Physical sanity bounds for arm-2 angular velocity in chaotic regime.
PEAK_OMEGA_PHYSICAL  = 1500.0   # rule-of-thumb maximum for real chaos
PEAK_OMEGA_ABSURD    = 4000.0   # above this is almost certainly tracker error

# Bar-scale maxima — used by render.py to fix the visual range so a
# single bar's length is comparable across tools and runs.
OMEGA_BAR_MAX        = 4000.0   # ω bars saturate at the absurd line
DROPOUT_BAR_MAX      = 15.0     # dropout bars saturate at 1.5× the WARN line

# Holding-phase noise floor: anything above this in holding is tracker
# noise (markers shouldn't move much before release). OMEGA_HOLD_THRESHOLD
# is the legacy name kept for the rich-bar tinting; OMEGA_CAP_HOLDING is
# the per-frame suspect-flagging cap used by verify_tracking. They are
# the same number, but each name carries a distinct intent so callers
# pick the one that matches the meaning at the call site.
OMEGA_HOLD_THRESHOLD = 100.0
OMEGA_CAP_HOLDING    = 100.0

# Rigid-body sanity: arm 2 is a physical rod, so the pixel distance
# between the green pivot and the red tip should be approximately
# constant. A frame whose arm-length deviates by more than this %
# of the median is flagged as a tracking error (caught even when
# dropout=0 and |ω| is below cap — different failure mode from the
# ω check).
ARM_LEN_THRESHOLD_PCT = 10.0

# Maximum |Δω| between consecutive clean frames in degrees/second.
# Physical Δω_max ≈ (g/L)·dt ≈ 27 °/s at 60fps; we use 200 to leave
# generous headroom for close-approach dynamics. Catches a different
# failure mode from the absolute ω cap: when the tracker latches onto
# a slow-moving wrong object, ω is small but the transition jump
# spikes Δω.
# Brief 6 calibration: 99th-percentile |Δω| on clean clips
# th1_p044_th2_m001 and th1_p047_th2_m002 measured at 102.9 and
# 94.2 °/s respectively — comfortably below 200, so the cap stays.
DELTA_OMEGA_CAP = 200.0

# Marker swap detection. If the cross-pairing distance (green→red',
# red→green') is less than SWAP_RATIO_THRESHOLD × the same-pairing
# distance (green→green', red→red'), the tracker has more likely
# swapped the marker labels than continued normal motion.
SWAP_RATIO_THRESHOLD = 0.7

# Brief 6 — physics checks
THETA_RESIDUAL_CAP_DEG    = 5.0    # ° prediction residual gate
# Brief 14 calibration (2026-05-02): on clean clips with SG-smoothed
# ω, p99 of E[i] / median(E[i-5:i]) is 1.38–1.68 and the maximum
# observed is 2.24. The previous 1.3 threshold flagged 3–6% of clean
# frames as spurious "spikes." Bumped to 2.0 — catches real
# wrong-target jumps (3-10× inflation) without firing on natural
# pendulum oscillation through swing extremes.
ENERGY_SPIKE_FACTOR       = 2.0
ENERGY_SMOOTH_WINDOW      = 5      # frames for rolling median baseline
ENERGY_RELEASE_HEADROOM   = 1.15   # E[i] ≤ E_release * this before flagging
PIVOT_DRIFT_WARN_PX       = 5.0    # px
PIVOT_DRIFT_FAIL_PX       = 15.0   # px

# Brief 6 Check D — trend arm-length
ARM_LENGTH_TREND_WINDOW   = 100    # frames per sliding window
ARM_LENGTH_TREND_DEV_PCT  = 5.0    # % deviation from reference window

# Brief 7 (absorbed) — IC-aware energy cap
# Phase 2 ARM_LENGTH_CM: measure physically in lab (ruler from pivot bolt to
# green marker center) and update the if-branch below.
if _PHASE == "phase2-motor-driven":
    ARM_LENGTH_CM = None   # TODO: measure Phase 2 arm length in cm
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
if _PHASE == "phase2-motor-driven":
    PIVOT         = (664, 330)
    ARM_LENGTH_PX = 153
else:
    PIVOT         = (608, 355)
    ARM_LENGTH_PX = 162
