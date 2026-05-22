"""
paths.py
--------
Single source of truth for all phase-specific data paths.

Set the CHAOS_PHASE environment variable to switch between experiment phases:

    CHAOS_PHASE=week3-4-pendulum-free-swing
    CHAOS_PHASE=week5-6-pendulum-motor-driven     (default)

All experiment directories now live under ``experiments/`` at the repo root.
The legacy phase names from earlier refactor cycles still resolve to the
new directories transparently:

    phase1-free-swing            -> experiments/week3-4-pendulum-free-swing
    phase2-motor-driven          -> experiments/week5-6-pendulum-motor-driven
    week3-pendulum-free-swing    -> experiments/week3-4-pendulum-free-swing
    week4-pendulum-motor-driven  -> experiments/week5-6-pendulum-motor-driven

All pipeline scripts import DATA_DIR, MEAS_DIR, VIDEOS_DIR, FIGURES_DIR,
EXPERIMENTS, and the ``clip_dir(stem)`` resolver from here instead of
computing them independently.

REPO_ROOT is also exported for the rare case where a subprocess needs the
repo root (e.g. cwd= for a chaos.py invocation).

Measurement layout
~~~~~~~~~~~~~~~~~~
The driven phase (weeks 5-6) splits its measurements/ into week5/ and
week6/ sub-buckets — week 6 holds the 3.2V family (except 3.2V_1Hz),
week 5 holds everything else. The free-swing phase (weeks 3-4) keeps a
flat measurements/ layout.

Use ``clip_dir(stem)`` instead of ``os.path.join(MEAS_DIR, stem)`` so
both layouts work transparently.
"""

import os

# Repo root: scripts/utils/paths.py -> scripts/utils/ -> scripts/ -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))

EXPERIMENTS_ROOT = os.path.join(REPO_ROOT, "experiments")

# Canonical phase names (current).
PHASE_FREE   = "week3-4-pendulum-free-swing"
PHASE_DRIVEN = "week5-6-pendulum-motor-driven"

# Legacy-name aliases. Anything that still sets CHAOS_PHASE to a pre-refactor
# value (old shells, old docs, scripts not yet updated) resolves to the new
# experiments/<canonical> directory transparently.
_LEGACY_ALIASES = {
    "phase1-free-swing":           PHASE_FREE,
    "phase2-motor-driven":         PHASE_DRIVEN,
    "week3-pendulum-free-swing":   PHASE_FREE,
    "week4-pendulum-motor-driven": PHASE_DRIVEN,
}

_raw_phase = os.environ.get("CHAOS_PHASE", PHASE_DRIVEN)
PHASE      = _LEGACY_ALIASES.get(_raw_phase, _raw_phase)
PHASE_ROOT = os.path.join(EXPERIMENTS_ROOT, PHASE)

DATA_DIR    = os.path.join(PHASE_ROOT, "data")
MEAS_DIR    = os.path.join(PHASE_ROOT, "measurements")
FIGURES_DIR = os.path.join(PHASE_ROOT, "figures")
ANIMATIONS_DIR = os.path.join(PHASE_ROOT, "animations")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

# Driven phase stores videos directly under <phase>/videos/.
# Free-swing phase historically used <phase>/data/videos/; keep that on disk
# so existing tooling continues to work.
if PHASE == PHASE_DRIVEN:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "videos")
else:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "data", "videos")

# ── Week sub-buckets (driven phase only) ─────────────────────────────────────
# In the driven phase, measurements/ is split into week5/ and week6/.
# week6/ holds the 3.2V resonance sweep (except 3.2V_1Hz); week5/ holds the
# broader V/f survey.
MEAS_WEEK5 = os.path.join(MEAS_DIR, "week5")
MEAS_WEEK6 = os.path.join(MEAS_DIR, "week6")


def _bucket_for_new_clip(stem):
    """Pick the week bucket a brand-new clip should land in.

    Driven-phase routing rule: stems starting with "3.2V_" (except
    "3.2V_1Hz") are the week-6 resonance sweep; everything else lived
    in the broader week-5 V/f survey.
    """
    if stem.startswith("3.2V_") and stem != "3.2V_1Hz":
        return MEAS_WEEK6
    return MEAS_WEEK5


def clip_dir(stem):
    """Return the canonical measurements directory for a clip stem.

    Handles the driven-phase week5/week6 split transparently:
    1. If either week-bucket subdir already contains <stem>/, return it.
    2. Otherwise, for the driven phase, route a new clip into the
       correct bucket (see ``_bucket_for_new_clip``).
    3. For the free-swing phase, fall back to the flat MEAS_DIR/<stem>
       layout — there are no week-buckets there.
    """
    for bucket in (MEAS_WEEK5, MEAS_WEEK6):
        candidate = os.path.join(bucket, stem)
        if os.path.isdir(candidate):
            return candidate
    if PHASE == PHASE_DRIVEN:
        return os.path.join(_bucket_for_new_clip(stem), stem)
    return os.path.join(MEAS_DIR, stem)


def iter_clip_dirs():
    """Yield ``(stem, abs_dir)`` for every measurements directory in the
    current phase, regardless of bucket layout.

    Use this in place of ``os.listdir(MEAS_DIR)`` when you need to walk
    every clip — it handles the week5/week6 split for the driven phase
    and the flat layout for free-swing.
    """
    seen = set()
    # Bucketed layout first (driven phase).
    for bucket in (MEAS_WEEK5, MEAS_WEEK6):
        if not os.path.isdir(bucket):
            continue
        for name in sorted(os.listdir(bucket)):
            d = os.path.join(bucket, name)
            if os.path.isdir(d) and name not in seen:
                seen.add(name)
                yield name, d
    # Flat layout (free-swing phase, or pre-split driven clips).
    if os.path.isdir(MEAS_DIR):
        for name in sorted(os.listdir(MEAS_DIR)):
            if name in ("week5", "week6") or name in seen:
                continue
            d = os.path.join(MEAS_DIR, name)
            if os.path.isdir(d):
                yield name, d
