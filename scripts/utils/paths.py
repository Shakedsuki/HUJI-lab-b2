"""
paths.py
--------
Single source of truth for all phase-specific data paths.

Set the CHAOS_PHASE environment variable to switch between experiment phases:

    CHAOS_PHASE=week3-4-pendulum-free-swing       (default)
    CHAOS_PHASE=week5-6-pendulum-motor-driven

All experiment directories now live under ``experiments/`` at the repo root.
The legacy phase names from earlier refactor cycles still resolve to the
new directories transparently:

    phase1-free-swing            -> experiments/week3-4-pendulum-free-swing
    phase2-motor-driven          -> experiments/week5-6-pendulum-motor-driven
    week3-pendulum-free-swing    -> experiments/week3-4-pendulum-free-swing
    week4-pendulum-motor-driven  -> experiments/week5-6-pendulum-motor-driven

All pipeline scripts import DATA_DIR, MEAS_DIR, VIDEOS_DIR, FIGURES_DIR,
and EXPERIMENTS from here instead of computing them independently.

REPO_ROOT is also exported for the rare case where a subprocess needs the
repo root (e.g. cwd= for a chaos.py invocation).
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

_raw_phase = os.environ.get("CHAOS_PHASE", PHASE_FREE)
PHASE      = _LEGACY_ALIASES.get(_raw_phase, _raw_phase)
PHASE_ROOT = os.path.join(EXPERIMENTS_ROOT, PHASE)

DATA_DIR    = os.path.join(PHASE_ROOT, "data")
MEAS_DIR    = os.path.join(PHASE_ROOT, "measurements")
FIGURES_DIR = os.path.join(PHASE_ROOT, "figures")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

# Driven phase stores videos directly under <phase>/videos/.
# Free-swing phase historically used <phase>/data/videos/; keep that on disk
# so existing tooling continues to work.
if PHASE == PHASE_DRIVEN:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "videos")
else:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "data", "videos")
