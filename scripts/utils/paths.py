"""
paths.py
--------
Single source of truth for all phase-specific data paths.

Set the CHAOS_PHASE environment variable to switch between experiment phases:

    CHAOS_PHASE=week3-pendulum-free-swing       (default)
    CHAOS_PHASE=week4-pendulum-motor-driven

The legacy phase names from before the week-based refactor still resolve to
the new directories for one transition cycle:

    phase1-free-swing  -> week3-pendulum-free-swing
    phase2-motor-driven -> week4-pendulum-motor-driven

All pipeline scripts import DATA_DIR, MEAS_DIR, VIDEOS_DIR, FIGURES_DIR,
and EXPERIMENTS from here instead of computing them independently.

REPO_ROOT is also exported for the rare case where a subprocess needs the
repo root (e.g. cwd= for a chaos.py invocation).
"""

import os

# Repo root: scripts/utils/paths.py -> scripts/utils/ -> scripts/ -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))

# Legacy-name aliases for the pre-refactor CHAOS_PHASE values. Anything
# that still sets CHAOS_PHASE=phase1-free-swing / phase2-motor-driven
# (old shells, old docs, scripts not yet updated) resolves to the new
# week-based directory transparently. Drop after the next release cycle.
_LEGACY_ALIASES = {
    "phase1-free-swing":  "week3-pendulum-free-swing",
    "phase2-motor-driven": "week4-pendulum-motor-driven",
}

_raw_phase = os.environ.get("CHAOS_PHASE", "week3-pendulum-free-swing")
PHASE      = _LEGACY_ALIASES.get(_raw_phase, _raw_phase)
PHASE_ROOT = os.path.join(REPO_ROOT, PHASE)

DATA_DIR    = os.path.join(PHASE_ROOT, "data")
MEAS_DIR    = os.path.join(PHASE_ROOT, "measurements")
FIGURES_DIR = os.path.join(PHASE_ROOT, "figures")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

# Week 4 stores videos directly under week4-pendulum-motor-driven/videos/
# (not data/videos/). Week 3 keeps them under data/videos/ for backward
# compatibility with the existing tooling.
if PHASE == "week4-pendulum-motor-driven":
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "videos")
else:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "data", "videos")
