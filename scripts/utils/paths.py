"""
paths.py
--------
Single source of truth for all phase-specific data paths.

Set the CHAOS_PHASE environment variable to switch between experiment phases:

    CHAOS_PHASE=week3-4-pendulum-free-swing
    CHAOS_PHASE=week5-pendulum-motor-driven       broad V/f survey
    CHAOS_PHASE=week6-pendulum-motor-driven       3.2V resonance sweep (default)

All experiment directories live under ``experiments/`` at the repo root.
Legacy phase names still resolve transparently — the pre-split combined
driven phase ``week5-6-pendulum-motor-driven`` now aliases to week6:

    phase1-free-swing             -> week3-4-pendulum-free-swing
    phase2-motor-driven           -> week6-pendulum-motor-driven
    week4-pendulum-motor-driven   -> week6-pendulum-motor-driven
    week5-6-pendulum-motor-driven -> week6-pendulum-motor-driven

All pipeline scripts import DATA_DIR, MEAS_DIR, VIDEOS_DIR, FIGURES_DIR,
ANIMATIONS_DIR, EXPERIMENTS, and the ``clip_dir(stem)`` resolver from here
instead of computing them independently.

REPO_ROOT is also exported for the rare case where a subprocess needs the
repo root (e.g. cwd= for a chaos.py invocation).

Layout
~~~~~~
Each phase is a single week with a flat ``measurements/<stem>/`` layout.
Static figures live in ``figures/<type>/``; animations (mp4) in
``animations/<type>/``; source clips in ``videos/`` (free-swing uses
``data/videos/``).

Source clips can also live outside the repo: set ``CHAOS_VIDEOS_DIR`` (env) or
use the shell's ``/load`` command to point the loader at an external folder per
phase (stored in a gitignored ``.video_sources.json``) without copying files in.
"""

import os
import json

# Repo root: scripts/utils/paths.py -> scripts/utils/ -> scripts/ -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))

EXPERIMENTS_ROOT = os.path.join(REPO_ROOT, "experiments")

# Canonical phase names (current).
PHASE_FREE   = "week3-4-pendulum-free-swing"
PHASE_WEEK5  = "week5-pendulum-motor-driven"
PHASE_WEEK6  = "week6-pendulum-motor-driven"
# Legacy combined driven phase (pre week5/week6 split); aliases to week6.
PHASE_DRIVEN = "week5-6-pendulum-motor-driven"

# Legacy-name aliases. Anything that still sets CHAOS_PHASE to a pre-refactor
# value (old shells, old docs, scripts not yet updated) resolves to the new
# experiments/<canonical> directory transparently.
_LEGACY_ALIASES = {
    "phase1-free-swing":           PHASE_FREE,
    "phase2-motor-driven":         PHASE_WEEK6,
    "week3-pendulum-free-swing":   PHASE_FREE,
    "week4-pendulum-motor-driven": PHASE_WEEK6,
    PHASE_DRIVEN:                  PHASE_WEEK6,
}

_raw_phase = os.environ.get("CHAOS_PHASE", PHASE_WEEK6)
PHASE      = _LEGACY_ALIASES.get(_raw_phase, _raw_phase)
PHASE_ROOT = os.path.join(EXPERIMENTS_ROOT, PHASE)

DATA_DIR    = os.path.join(PHASE_ROOT, "data")
MEAS_DIR    = os.path.join(PHASE_ROOT, "measurements")
FIGURES_DIR = os.path.join(PHASE_ROOT, "figures")
ANIMATIONS_DIR = os.path.join(PHASE_ROOT, "animations")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

# External video-source override: a user whose raw clips live outside the repo
# (e.g. a fresh clone with the videos in some other folder) can point the loader
# at them per phase, without copying files in. CHAOS_VIDEOS_DIR (env) wins as a
# one-shot override; otherwise a gitignored {phase: dir} map in .video_sources.json
# at the repo root is consulted. Falls back to the in-repo layout when neither is set.
VIDEO_SOURCES_FILE = os.path.join(REPO_ROOT, ".video_sources.json")

def _load_video_sources():
    try:
        with open(VIDEO_SOURCES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def get_video_source(phase=None):
    """External override dir for a phase, or None if it uses the in-repo layout."""
    env = os.environ.get("CHAOS_VIDEOS_DIR")
    if env:
        return env
    return _load_video_sources().get(phase or PHASE)

def set_video_source(directory, phase=None):
    """Persist an external video dir for a phase (writes .video_sources.json)."""
    data = _load_video_sources()
    data[phase or PHASE] = directory
    with open(VIDEO_SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def clear_video_source(phase=None):
    """Drop a phase's external override (revert to the in-repo layout)."""
    data = _load_video_sources()
    if (phase or PHASE) in data:
        del data[phase or PHASE]
        with open(VIDEO_SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# Driven phase stores videos directly under <phase>/videos/; free-swing uses
# <phase>/data/videos/. An external override (above) replaces either.
_override = get_video_source(PHASE)
if _override:
    VIDEOS_DIR = _override
elif PHASE == PHASE_FREE:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "data", "videos")
else:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "videos")

def clip_dir(stem):
    """Return the measurements directory for a clip stem: measurements/<stem>/.
    Each phase is a single week (no sub-buckets) since the week5/week6 split."""
    return os.path.join(MEAS_DIR, stem)


def iter_clip_dirs():
    """Yield ``(stem, abs_dir)`` for every measurements directory in the
    current phase. Use in place of ``os.listdir(MEAS_DIR)``."""
    if not os.path.isdir(MEAS_DIR):
        return
    for name in sorted(os.listdir(MEAS_DIR)):
        d = os.path.join(MEAS_DIR, name)
        if os.path.isdir(d):
            yield name, d
