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
