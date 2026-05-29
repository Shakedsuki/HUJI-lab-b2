#!/usr/bin/env python3
"""
kinematics.py — single source of truth for angular velocity from tracked angles.

Differentiating a tracked angle with a raw finite difference (np.gradient /
np.diff) amplifies sub-pixel marker jitter into huge spikes — ±thousands of
deg/s on a 60 fps clip. Those spikes fill a delay-embedding's phase space and
INFLATE the correlation dimension D2, producing a false "chaotic" verdict on
what is really a clean periodic orbit (this bit us on 3.2V_0.9Hz: D2=2.65,
"CHAOTIC", from a periodic libration whose D_box was 0.97 and whose power
spectrum was a clean line spectrum).

The fix, already used by the phase-portrait scripts, is a Savitzky-Golay
derivative: fit a local low-order polynomial and read off its slope — smooth
and differentiate in one pass, rejecting jitter while preserving the genuine
fast motion of a chaotic clip. We unwrap first so the ±180° wrap is not itself
a 360°/frame phantom spike.

Every analysis script that needs ω-from-θ should call ``angular_velocity``
here rather than rolling its own derivative, so the convention cannot diverge
file-to-file again.
"""

import numpy as np
from scipy.signal import savgol_filter

# Canonical Savitzky-Golay parameters (echoed by phase_panels / phase_3d /
# phase_animation / combined_video). 11 frames ~ 0.18 s at 60 fps.
SG_WINDOW = 11   # frames; must be odd
SG_POLY = 3      # polynomial order


def angular_velocity(theta_deg, t, window=SG_WINDOW, poly=SG_POLY):
    """Smooth angular velocity dθ/dt (deg/s) from a wrapped angle series.

    Parameters
    ----------
    theta_deg : array of angles in degrees, wrapped to [-180, 180]
    t         : matching time stamps in seconds (≈ uniform)
    window    : SG window length in frames (odd; auto-shrunk for short series)
    poly      : SG polynomial order

    Returns
    -------
    omega : array (deg/s), same length as theta_deg.

    Falls back to np.gradient only when the series is too short for an SG fit.
    """
    theta_deg = np.asarray(theta_deg, dtype=float)
    t = np.asarray(t, dtype=float)
    n = theta_deg.size

    phi = np.degrees(np.unwrap(np.radians(theta_deg)))   # continuous angle
    if n < 2:
        return np.zeros_like(phi)

    dt = float(np.median(np.diff(t)))
    if not np.isfinite(dt) or dt <= 0:
        dt = 1.0

    win = int(window)
    if win % 2 == 0:
        win += 1
    if win > n:                      # shrink to the largest valid odd window
        win = n if (n % 2 == 1) else (n - 1)
    if win <= poly:                  # too few samples for an SG fit
        return np.gradient(phi, t)

    return savgol_filter(phi, win, poly, deriv=1, delta=dt)
