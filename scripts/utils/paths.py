"""
paths.py
--------
Single source of truth for all phase-specific data paths.

Set the CHAOS_PHASE environment variable to switch between experiment phases:

    CHAOS_PHASE=phase1-free-swing   (default)
    CHAOS_PHASE=phase2-motor-driven

All pipeline scripts import DATA_DIR, MEAS_DIR, VIDEOS_DIR, FIGURES_DIR,
and EXPERIMENTS from here instead of computing them independently.

REPO_ROOT is also exported for the rare case where a subprocess needs the
repo root (e.g. cwd= for a chaos.py invocation).
"""

import os

# Repo root: scripts/utils/paths.py -> scripts/utils/ -> scripts/ -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))

PHASE      = os.environ.get("CHAOS_PHASE", "phase1-free-swing")
PHASE_ROOT = os.path.join(REPO_ROOT, PHASE)

DATA_DIR    = os.path.join(PHASE_ROOT, "data")
MEAS_DIR    = os.path.join(PHASE_ROOT, "measurements")
FIGURES_DIR = os.path.join(PHASE_ROOT, "figures")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

# Phase 2 stores videos directly under phase2-motor-driven/videos/ (not data/videos/).
if PHASE == "phase2-motor-driven":
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "videos")
else:
    VIDEOS_DIR = os.path.join(PHASE_ROOT, "data", "videos")
