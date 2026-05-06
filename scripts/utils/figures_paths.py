"""
figures_paths.py
-----------------
Single source of truth for where analysis scripts write their figure
outputs. Per-clip figures live at:

    figures/<type>/<stem>_<type>.<ext>

So `figures/lyapunov/th1_p044_th2_m001_lyapunov.png` is the Lyapunov
plot for that clip; `figures/poincare/<stem>_poincare.png` is its
Poincaré section; and so on. The redundant <type> suffix means the
filename remains self-describing if it gets copied out of its folder
(into a lab report, slides, etc.). Aggregate (cross-clip) plots go in
`figures/aggregate/`.

Why this layout:
  - Browse all Lyapunov plots in one folder, all Poincaré sections in
    another — natural for picking lab-report figures.
  - File-name = stem, so the per-clip identity is preserved.
  - Data (tracking.csv, verification.csv, registry, seeds.json) stays
    in measurements/<stem>/ — clean separation of data vs visuals.

Used by: phase_panels.py, phase_3d.py, phase_animation.py, poincare.py,
lyapunov.py, verify_tracking.py, chaos_analyze.py, friction_fit.py,
combined_video.py, ring_tracker.py (debug.mp4), friction_compare.py.
"""

import os


# scripts/utils/figures_paths.py → scripts/ → repo root
ROOT        = os.path.dirname(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__))))
FIGURES_DIR = os.path.join(ROOT, "figures")
AGGREGATE   = os.path.join(FIGURES_DIR, "aggregate")


# Canonical figure type names.  Keep the set deliberately small — adding
# a new type here is the only place that needs to change when a new
# analysis script ships a new figure.
FIGURE_TYPES = {
    "phase_panels",
    "phase_3d_trajectory",
    "phase_3d_rotation",
    "phase_animation",
    "poincare",
    "lyapunov",
    "verification",
    "chaos_analyze",
    "friction_fit",
    "combined",
    "debug",
}


def figure_path(figure_type, stem, ext="png"):
    """Return the canonical filesystem path for a per-clip figure.

    Creates the parent directory if it doesn't exist.

    Args:
        figure_type: one of FIGURE_TYPES (e.g. "lyapunov", "poincare").
        stem:        config_description, e.g. "th1_p044_th2_m001".
        ext:         file extension without the dot, e.g. "png" or "mp4".

    Returns:
        Absolute path: <ROOT>/figures/<figure_type>/<stem>_<figure_type>.<ext>
    """
    if figure_type not in FIGURE_TYPES:
        # Don't hard-fail — just warn and proceed. New scripts can add
        # new types without touching this module first.
        pass
    out_dir = os.path.join(FIGURES_DIR, figure_type)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{stem}_{figure_type}.{ext}")


def aggregate_path(filename):
    """Return the canonical path for a cross-clip aggregate figure.

    Args:
        filename: full filename including extension, e.g.
                  "lyapunov_vs_amplitude.png".

    Returns:
        Absolute path: <ROOT>/figures/aggregate/<filename>
    """
    os.makedirs(AGGREGATE, exist_ok=True)
    return os.path.join(AGGREGATE, filename)
