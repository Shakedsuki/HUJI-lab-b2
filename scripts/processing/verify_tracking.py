"""
verify_tracking.py
------------------
Independent quality check on a tracking CSV produced by ring_tracker.py.

The `dropout` column only flags frames where *no* marker was found at all.
It cannot tell you whether the marker that *was* found is the right one —
without an anchor gate, the fallback chain can latch onto a chunk of arm
shaft when the marker mask is empty, and that shows up as `dropout=0`.

This script computes the apparent angular velocity (ω = Δθ/dt with proper
±180° unwrapping) per frame and flags rows whose |ω| exceeds a physical
threshold. A pendulum with arm length 35 cm starting from inverted
maxes out around 1200–1500 °/s for arm 2 in chaotic regimes, so anything
above ~2500 °/s is almost certainly a tracking jump rather than physics.

Usage
~~~~~
    python scripts/processing/verify_tracking.py --stem th1_p180_th2_m179
    python scripts/processing/verify_tracking.py measurements/th1_p180_th2_m179/tracking.csv
    python scripts/processing/verify_tracking.py --omega-cap 2000 --stem th1_p044_th2_m001

Outputs
~~~~~~~
    Console:                                summary of suspect rows split
                                            by phase, plus the cross-tab
                                            with the existing `dropout`
                                            flag.
    measurements/<config>/verification.png  : θ1 / θ2 over time with suspect
                                              frames in red, plus the apparent ω.
    measurements/<config>/verification.csv  : same rows as the input + a
                                              `suspect` column (0/1).
"""

import csv
import os
import sys
import json
import argparse
import numpy as np
from scipy.signal import savgol_filter

# The script prints angle / omega symbols (θ, ω, Δ) which fall outside
# Windows' default cp1252 stdout encoding when output is captured. Force
# UTF-8 so the script works the same in cmd, PowerShell, Git Bash, and
# when piped to a file.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

DEFAULT_CSV = os.path.join(REPO_ROOT, "measurements", "th1_p180_th2_m179",
                           "tracking.csv")

# Pull rendering helpers from scripts/utils/render.py — every print
# block in this script that produces a table is delegated there so
# the verdict layer and the live verify output stay visually
# consistent.
from render import (  # noqa: E402
    render_verification_summary,
    render_arm_breakdown,
    render_phase_summary,
    render_suspect_table,
    render_arm_length_violations,
    render_pivot_check,
)
from figures_paths import figure_path  # noqa: E402
from thresholds import (  # noqa: E402
    ARM_LEN_THRESHOLD_PCT,
    OMEGA_CAP_HOLDING,
    DELTA_OMEGA_CAP,
    SWAP_RATIO_THRESHOLD,
    THETA_RESIDUAL_CAP_DEG,
    ENERGY_SPIKE_FACTOR,
    ENERGY_SMOOTH_WINDOW,
    ENERGY_RELEASE_HEADROOM,
    ARM_LENGTH_TREND_WINDOW,
    ARM_LENGTH_TREND_DEV_PCT,
    ARM_LENGTH_CM,
    PIVOT,
    ARM_LENGTH_PX,
)

def compute_frame_energy(th1_deg, th2_deg, om1_dps, om2_dps,
                         L_m=0.35, g=9.8):
    """
    Total mechanical energy (J, unit mass per arm) for one frame of a
    double pendulum with two uniform rods of equal length and mass.

    Brief 9: replaces the earlier point-mass formula, which over-flagged
    999/1075 frames of a clean clip because the tip-mass approximation
    overestimated KE mid-swing while overestimating PE at release.

    Conventions (ring_tracker):
      th1_deg  — arm-1 angle from vertical (0 = straight down)
      th2_deg  — arm-2 angle relative to arm-1
      om1_dps  — arm-1 angular velocity in °/s
      om2_dps  — arm-2 angular velocity in °/s (relative)

    Reference PE = 0 when both arms hang straight down.
    """
    th1_r     = np.radians(th1_deg)
    th2_abs_r = np.radians(th1_deg + th2_deg)   # absolute angle of arm-2
    th2_rel_r = np.radians(th2_deg)             # relative angle (cross-term)

    w1_r      = np.radians(om1_dps)
    w2_abs_r  = np.radians(om1_dps + om2_dps)   # absolute ω of arm-2

    # Potential energy — uniform rods, CM at L/2 for each arm. Arm-1's
    # CM is at L/2 from the fixed pivot; arm-2's CM is at L from the
    # fixed pivot along arm-1, then L/2 along arm-2.
    PE = (g * (3.0 * L_m / 2.0) * (1.0 - np.cos(th1_r))
        + g * (L_m / 2.0)       * (1.0 - np.cos(th2_abs_r)))

    # Kinetic energy — derived from the Lagrangian for two equal
    # uniform rods. Cross-term sign uses cos(θ₁ - θ₂_abs) = cos(-θ₂_rel).
    KE = L_m**2 * (
          (2.0 / 3.0) * w1_r ** 2
        + 0.5         * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1.0 / 6.0) * w2_abs_r ** 2
    )

    return KE + PE

def parse_args():
    p = argparse.ArgumentParser(
        description="Sanity-check a pendulum tracking CSV.")
    p.add_argument("csv", nargs="?", default=None,
                   help="path to tracking CSV (positional)")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p180_th2_m179. "
                        "Resolves the CSV and output dir from "
                        "measurements/<stem>/.")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="deg/s above which |Δθ/dt| is flagged as suspect "
                        "(default 2500; arm-2 chaos peaks ~1500)")
    p.add_argument("--no-plot", action="store_true",
                   help="skip the matplotlib plot")
    p.add_argument("--no-csv-out", action="store_true",
                   help="skip writing the verification.csv companion")
    p.add_argument("--arm-len-threshold", type=float,
                   default=ARM_LEN_THRESHOLD_PCT,
                   help=f"pixel arm-length deviation %% above which a "
                        f"clean frame is flagged as a tracker error "
                        f"(default {ARM_LEN_THRESHOLD_PCT:.0f}%%)")
    p.add_argument("--delta-omega-cap", type=float,
                   default=DELTA_OMEGA_CAP,
                   help=f"maximum |Δω| per frame in °/s; catches sudden "
                        f"acceleration spikes that signal a tracker latch "
                        f"(default {DELTA_OMEGA_CAP:.0f})")
    p.add_argument("--theta-residual-cap", type=float,
                   default=THETA_RESIDUAL_CAP_DEG,
                   help=f"° prediction-residual gate for θ vs "
                        f"θ[i-1]+ω[i-1]·dt (default "
                        f"{THETA_RESIDUAL_CAP_DEG:.1f})")
    p.add_argument("--energy-spike-factor", type=float,
                   default=ENERGY_SPIKE_FACTOR,
                   help=f"E[i] / rolling baseline ratio above which a "
                        f"frame is flagged as a spike (default "
                        f"{ENERGY_SPIKE_FACTOR:.2f})")
    p.add_argument("--energy-headroom", type=float,
                   default=ENERGY_RELEASE_HEADROOM,
                   help=f"E[i] ≤ E_release × this before flagging as a "
                        f"ceiling violation (default "
                        f"{ENERGY_RELEASE_HEADROOM:.2f})")
    p.add_argument("--arm-trend-window", type=int,
                   default=ARM_LENGTH_TREND_WINDOW,
                   help=f"frames per sliding window for arm-length "
                        f"trend check (default {ARM_LENGTH_TREND_WINDOW})")
    p.add_argument("--arm-trend-dev", type=float,
                   default=ARM_LENGTH_TREND_DEV_PCT,
                   help=f"%% deviation from reference window before a "
                        f"trend window is flagged (default "
                        f"{ARM_LENGTH_TREND_DEV_PCT:.1f})")
    return p.parse_args()

def resolve_paths(args):
    """
    Returns (csv_path, output_dir, stem_label).
    Priority: --stem > positional csv > DEFAULT_CSV.
    output_dir is where verification.csv / verification.png are written.
    """
    if args.stem:
        meas_dir = os.path.join(REPO_ROOT, "measurements", args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            print(f"ERROR: tracking.csv not found for stem '{args.stem}'")
            print(f"  Expected: {csv_path}")
            sys.exit(1)
        return csv_path, meas_dir, args.stem

    if args.csv:
        csv_path = args.csv
        if not os.path.isabs(csv_path):
            csv_path = os.path.join(REPO_ROOT, csv_path)
        # Write outputs next to the CSV — i.e., into the measurement folder.
        output_dir = os.path.dirname(csv_path)
        stem_label = os.path.basename(output_dir) or \
                     os.path.splitext(os.path.basename(csv_path))[0]
        return csv_path, output_dir, stem_label

    csv_path = DEFAULT_CSV
    output_dir = os.path.dirname(csv_path)
    stem_label = os.path.basename(output_dir)
    return csv_path, output_dir, stem_label

def wrap_diff(angle_series):
    """
    Frame-to-frame Δθ that handles the ±180° wraparound. Returns an array
    the same length as the input, with NaN in slots where the diff is
    undefined (first frame, or either neighbour was a dropout).
    """
    a = np.asarray(angle_series, dtype=float)
    d = np.empty_like(a)
    d[:] = np.nan
    for i in range(1, len(a)):
        if np.isnan(a[i]) or np.isnan(a[i - 1]):
            continue
        delta = ((a[i] - a[i - 1] + 180.0) % 360.0) - 180.0
        d[i] = delta
    return d

# Brief 12 — Savitzky-Golay differentiation parameters. Match the
# values used by the analysis-side scripts (phase_panels, phase_3d,
# combined_video) so verify_tracking's ω is consistent with the ω
# downstream consumers actually plot.
SG_WINDOW = 11
SG_POLY   = 3

def smooth_omega(angle_series, dt_med):
    """
    Brief 12 — angular velocity via Savitzky-Golay differentiation.

    KE in the energy formula is quadratic in ω, so finite-difference ω
    noise σ_ω inflates KE as ΔKE ≈ L²·|ω|·σ_ω. Replacing raw `Δθ/dt`
    with a low-order polynomial fit over a small window dramatically
    reduces σ_ω without introducing lag bias (SG with deriv=1 is
    centred). This matches what every analysis-side script already
    does to θ before plotting.

    Per-segment processing handles dropouts cleanly:
      - Walk continuous non-NaN runs of θ.
      - Unwrap each segment (θ wraps at ±180° but the SG fit assumes
        a smooth function).
      - Apply savgol_filter when the segment is at least SG_WINDOW
        long; fall back to np.gradient on shorter segments so we
        don't drop short clean runs.
      - NaN at every frame whose θ was missing.
    """
    a = np.asarray(angle_series, dtype=float)
    n = len(a)
    om = np.full(n, np.nan)
    if n == 0:
        return om

    # Walk continuous non-NaN segments.
    valid = ~np.isnan(a)
    i = 0
    while i < n:
        if not valid[i]:
            i += 1
            continue
        j = i
        while j < n and valid[j]:
            j += 1
        # Segment is [i, j).
        seg = a[i:j]
        if len(seg) >= SG_POLY + 1:
            seg_unwrap = np.degrees(np.unwrap(np.radians(seg)))
            if len(seg) >= SG_WINDOW:
                om[i:j] = savgol_filter(
                    seg_unwrap, SG_WINDOW, SG_POLY,
                    deriv=1, delta=dt_med)
            else:
                # Too short for the canonical SG window — use np.gradient
                # (centred finite differences) on the unwrapped segment.
                om[i:j] = np.gradient(seg_unwrap, dt_med)
        i = j
    return om

def main():
    args = parse_args()

    csv_path, output_dir, stem = resolve_paths(args)
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)

    print(f"verify_tracking.py")
    print(f"CSV    : {csv_path}")
    print(f"Folder : {output_dir}")
    print(f"|ω| threshold: {args.omega_cap:.0f} deg/s")
    print()

    # ── Load the CSV ────────────────────────────────────────────────────
    with open(csv_path, "r") as f:
        rows = list(csv.DictReader(f))

    n     = len(rows)
    times = np.array([float(r["time_s"])     for r in rows])
    drops = np.array([int(r["dropout"])      for r in rows])
    phase = np.array([r["phase"]             for r in rows])

    def to_float_or_nan(x):
        return float(x) if x not in ("", None) else np.nan

    th1 = np.array([to_float_or_nan(r["theta1_deg"]) for r in rows])
    th2 = np.array([to_float_or_nan(r["theta2_deg"]) for r in rows])

    # Load marker pixel positions for the arm-length rigidity check.
    x_green = np.array([to_float_or_nan(r.get("x_green", "")) for r in rows])
    y_green = np.array([to_float_or_nan(r.get("y_green", "")) for r in rows])
    x_red   = np.array([to_float_or_nan(r.get("x_red",   "")) for r in rows])
    y_red   = np.array([to_float_or_nan(r.get("y_red",   "")) for r in rows])

    # ── Per-frame dt (use median to be robust to gaps) ─────────────────
    diffs = np.diff(times)
    dt_med = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 1.0 / 60.0
    print(f"Median dt: {dt_med * 1000:.2f} ms  ({1.0 / dt_med:.2f} fps)")

    # ── ω via Savitzky-Golay differentiation (Brief 12) ────────────────
    # Replaces the previous raw finite-difference ω. The KE noise
    # σ_KE ≈ L²·|ω|·σ_ω scales quadratically in ω, so smoothing θ
    # before differentiation is the single highest-leverage fix for
    # the σ_ω-driven false positives in the energy and θ-residual
    # checks. Mirrors the convention used by every analysis-side
    # script (phase_panels.py, phase_3d.py, combined_video.py).
    om1 = smooth_omega(th1, dt_med)
    om2 = smooth_omega(th2, dt_med)

    # Arm-length rigidity (pixel distance from green pivot to red tip).
    # Frames where green or red is missing yield NaN; the median is
    # taken over clean rows so dropouts don't pull the reference.
    arm_len = np.sqrt((x_red - x_green) ** 2 + (y_red - y_green) ** 2)
    clean_arm_mask = (drops == 0) & ~np.isnan(arm_len)
    if clean_arm_mask.any():
        arm_median = float(np.nanmedian(arm_len[clean_arm_mask]))
    else:
        arm_median = float("nan")
    if not np.isnan(arm_median) and arm_median > 0:
        arm_dev_pct = np.abs(arm_len - arm_median) / arm_median * 100.0
    else:
        arm_dev_pct = np.full_like(arm_len, np.nan)

    # Phase-separated ω caps. Holding-phase markers should be
    # stationary, so ANY ω above OMEGA_CAP_HOLDING is tracker noise,
    # not physics. Free-swing keeps the user-configurable cap (default
    # 2500 °/s, well above the 1500 °/s physical RoT).
    suspect = np.zeros(n, dtype=bool)
    free_mask    = (phase == "free_swing")
    holding_mask = (phase == "holding")
    if free_mask.any():
        suspect[free_mask] = (
            (np.abs(om1[free_mask]) > args.omega_cap) |
            (np.abs(om2[free_mask]) > args.omega_cap)
        )
    if holding_mask.any():
        suspect[holding_mask] = (
            (np.abs(om1[holding_mask]) > OMEGA_CAP_HOLDING) |
            (np.abs(om2[holding_mask]) > OMEGA_CAP_HOLDING)
        )

    # Brief 13: snapshot the ω-cap-only mask BEFORE Brief 5/6 checks
    # union into `suspect`. interpolate_suspects.py operates only on
    # ω-cap suspects (single-frame teleports between clean neighbours);
    # the post-interpolation residual count therefore needs to be the
    # ω-cap-only count, not the union of every check. Without this
    # split, the verdict layer double-counts physics-check suspects
    # (which already have their own dedicated reasons) under the
    # generic "residual suspects post-interpolation" message.
    omega_cap_suspect = suspect.copy()

    # Per-arm masks (using the same phase-aware caps) for the breakdown.
    suspect1 = np.zeros(n, dtype=bool)
    suspect2 = np.zeros(n, dtype=bool)
    if free_mask.any():
        suspect1[free_mask] = np.abs(om1[free_mask]) > args.omega_cap
        suspect2[free_mask] = np.abs(om2[free_mask]) > args.omega_cap
    if holding_mask.any():
        suspect1[holding_mask] = np.abs(om1[holding_mask]) > OMEGA_CAP_HOLDING
        suspect2[holding_mask] = np.abs(om2[holding_mask]) > OMEGA_CAP_HOLDING

    # Arm-length violations (clean frames only — dropouts have no
    # arm length to check).
    arm_violation = np.zeros(n, dtype=bool)
    if not np.isnan(arm_median):
        arm_violation = ((arm_dev_pct > args.arm_len_threshold)
                         & (drops == 0)
                         & ~np.isnan(arm_dev_pct))

    # Δω post-hoc check (Brief 5). Catches frames where ω itself looks
    # plausible but the per-frame change in ω is unphysical — typical
    # signature of a tracker latch onto a slow-moving wrong object.
    dom1 = np.empty_like(om1)
    dom2 = np.empty_like(om2)
    dom1[:] = np.nan
    dom2[:] = np.nan
    for i in range(1, n):
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om1[i]) and not np.isnan(om1[i - 1])):
            dom1[i] = abs(om1[i] - om1[i - 1])
        if (drops[i] == 0 and drops[i - 1] == 0
                and not np.isnan(om2[i]) and not np.isnan(om2[i - 1])):
            dom2[i] = abs(om2[i] - om2[i - 1])
    accel_suspect1 = dom1 > args.delta_omega_cap
    accel_suspect2 = dom2 > args.delta_omega_cap
    accel_suspect  = (accel_suspect1 | accel_suspect2) & (drops == 0)
    # Treat NaN-derived comparisons as False — np.isnan(...) > X is
    # already False but be explicit.
    accel_suspect &= ~np.isnan(np.where(accel_suspect1, dom1, dom2))

    # Marker swap detection (Brief 5). Each consecutive pair of clean
    # frames is checked: if the cross-pairing distance is much smaller
    # than the same-pairing, the markers have swapped labels.
    swap_suspect = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if drops[i] or drops[i - 1]:
            continue
        gx0, gy0 = x_green[i - 1], y_green[i - 1]
        gx1, gy1 = x_green[i],     y_green[i]
        rx0, ry0 = x_red[i - 1],   y_red[i - 1]
        rx1, ry1 = x_red[i],       y_red[i]
        if any(np.isnan(v) for v in (gx0, gy0, gx1, gy1,
                                     rx0, ry0, rx1, ry1)):
            continue
        d_same  = (np.hypot(gx1 - gx0, gy1 - gy0)
                 + np.hypot(rx1 - rx0, ry1 - ry0))
        d_cross = (np.hypot(rx1 - gx0, ry1 - gy0)
                 + np.hypot(gx1 - rx0, gy1 - ry0))
        if d_same > 0 and (d_cross / d_same) < SWAP_RATIO_THRESHOLD:
            swap_suspect[i] = True

    # Merge Brief-5 flags into the combined suspect mask. They count as
    # hidden suspects (dropout=0 + suspect=1) for downstream consumers.
    suspect = suspect | accel_suspect | swap_suspect
    n_accel_suspect = int(np.sum(accel_suspect))
    n_swap_suspect  = int(np.sum(swap_suspect))

    # ── Brief 6 Check D — trend arm-length ─────────────────────────────
    # Runs BEFORE energy because it validates the median used by Check B
    # and because a corrupted global arm-length median means the per-frame
    # arm check (Brief 3) under-flags. The reference is the first
    # ARM_LENGTH_TREND_WINDOW clean free_swing frames; the tracker starts
    # fresh at init_frame so this window is the least likely to be
    # corrupted.
    free_clean = ((phase == "free_swing")
                  & (drops == 0)
                  & ~np.isnan(arm_len))
    free_clean_idxs = np.where(free_clean)[0]

    trend_arm_suspect = np.zeros(n, dtype=bool)
    n_trend_windows   = 0

    if len(free_clean_idxs) >= args.arm_trend_window:
        ref_idxs = free_clean_idxs[:args.arm_trend_window]
        reference_median = float(np.nanmedian(arm_len[ref_idxs]))
        if reference_median > 0:
            step = max(args.arm_trend_window // 2, 1)
            for start in range(0, len(free_clean_idxs), step):
                window_idxs = free_clean_idxs[
                    start : start + args.arm_trend_window]
                if len(window_idxs) < args.arm_trend_window // 2:
                    break   # too few frames for a meaningful window
                window_median = float(np.nanmedian(arm_len[window_idxs]))
                dev = (abs(window_median - reference_median)
                       / reference_median)
                if dev > args.arm_trend_dev / 100.0:
                    trend_arm_suspect[window_idxs] = True
                    n_trend_windows += 1

    suspect = suspect | trend_arm_suspect

    # ── Brief 6 Check A — θ-prediction residual ────────────────────────
    # ω[i] is computed from Δθ so it is definitionally consistent with
    # θ[i] within a single frame. The residual θ[i] - (θ[i-1] +
    # ω[i-1]·dt) catches slow drifts to a wrong-target near a ω
    # zero-crossing — those escape the Δω cap because the jump happens
    # while ω is small.
    res1 = np.full(n, np.nan)
    res2 = np.full(n, np.nan)
    for i in range(1, n):
        if drops[i] or drops[i - 1]:
            continue
        if not (np.isnan(th1[i]) or np.isnan(th1[i - 1])
                or np.isnan(om1[i - 1])):
            pred = th1[i - 1] + om1[i - 1] * dt_med
            res1[i] = ((th1[i] - pred + 180.0) % 360.0) - 180.0
        if not (np.isnan(th2[i]) or np.isnan(th2[i - 1])
                or np.isnan(om2[i - 1])):
            pred = th2[i - 1] + om2[i - 1] * dt_med
            res2[i] = ((th2[i] - pred + 180.0) % 360.0) - 180.0

    residual_suspect1 = np.abs(res1) > args.theta_residual_cap
    residual_suspect2 = np.abs(res2) > args.theta_residual_cap
    residual_suspect  = ((residual_suspect1 | residual_suspect2)
                         & (drops == 0))

    suspect = suspect | residual_suspect

    # ── Brief 6 Check B — energy monotonicity (two-tier) ───────────────
    # Tier 1 (absolute ceiling, E_release × headroom): catches stable
    # wrong-target latches that would inflate tracked energy beyond what
    # the release ICs allow. A rolling baseline would adapt to the
    # wrong-object energy and miss this.
    # Tier 2 (rolling spike): catches single-frame teleports — tracker
    # briefly latches on a wrong object and returns.
    L_m   = ARM_LENGTH_CM / 100.0
    valid_energy = ((phase == "free_swing")
                    & (drops == 0)
                    & ~np.isnan(th1) & ~np.isnan(th2)
                    & ~np.isnan(om1) & ~np.isnan(om2))

    energy = np.full(n, np.nan)
    for i in np.where(valid_energy)[0]:
        energy[i] = compute_frame_energy(
            th1[i], th2[i], om1[i], om2[i], L_m=L_m)

    # Brief 11a: E_reference is taken from the early free_swing window,
    # NOT the single first frame. The first frame's ω is noisy because
    # the finite difference is initialised at the holding/free_swing
    # boundary, and KE ∝ ω² so that noise scales as ΔKE ≈ L²·|ω|·σ_ω.
    # A single-frame reference is also fragile to that one frame.
    #
    # The brief proposed the 10th percentile of the first 100 frames,
    # but empirically that sets the reference far below the legitimate
    # upper envelope of clean energies (mid-swing KE peaks are real
    # physics, not just noise) and produces 62%/30% FPR on clean clips.
    # The 99th percentile of the same window captures the legitimate
    # upper envelope — it is robust to a single outlier (unlike max)
    # while still tracking the full swing-amplitude energy. Empirically
    # this hits the brief's target (< 2% FPR) on both clean clips.
    #
    # Sidecar JSON keeps the "energy_release_J" key for backwards
    # compatibility; its meaning is now the percentile reference.
    release_idxs = np.where(valid_energy)[0]
    if len(release_idxs) >= 10:
        n_ref = min(100, len(release_idxs))
        E_release = float(
            np.nanpercentile(energy[release_idxs[:n_ref]], 99.0))
    elif len(release_idxs) > 0:
        # Too few frames to meaningfully take a percentile — fall back
        # to the single-frame reference.
        E_release = float(energy[release_idxs[0]])
    else:
        E_release = float("nan")

    if not np.isnan(E_release):
        ceiling = E_release * args.energy_headroom
        energy_ceiling_suspect = valid_energy & (energy > ceiling)
    else:
        energy_ceiling_suspect = np.zeros(n, dtype=bool)

    energy_rolling_spike = np.zeros(n, dtype=bool)
    rolling_baseline = np.full(n, np.nan)
    idxs = np.where(valid_energy)[0]
    for k, i in enumerate(idxs):
        window = idxs[max(0, k - ENERGY_SMOOTH_WINDOW):k]
        if len(window) >= 2:
            base = float(np.nanmedian(energy[window]))
            rolling_baseline[i] = base
            if base > 0 and energy[i] / base > args.energy_spike_factor:
                energy_rolling_spike[i] = True

    energy_suspect = ((energy_ceiling_suspect | energy_rolling_spike)
                      & valid_energy)
    suspect = suspect | energy_suspect

    n_residual_suspect       = int(np.sum(residual_suspect))
    n_energy_ceiling_suspect = int(np.sum(energy_ceiling_suspect))
    n_energy_rolling_spike   = int(np.sum(energy_rolling_spike))
    n_energy_suspect         = int(np.sum(energy_suspect))
    n_trend_arm_suspect      = int(np.sum(trend_arm_suspect))

    # ── Brief 6 Check C — pivot drift (run-level only) ─────────────────
    # Independent estimate of the rotation center from green-marker
    # positions, via least-squares circle fit. Compared against the
    # hardcoded PIVOT to flag camera shifts or miscalibration. Does NOT
    # merge into the suspect mask — this is a run-level geometry check.
    #
    # The earlier "back-projection" approach (gx − L·sin(θ₁), …) was
    # mathematically circular: θ₁ itself was computed from PIVOT, so
    # the implied pivot always converged to PIVOT regardless of where
    # the marker actually rotates. A circle fit uses only (x_green,
    # y_green) and is unbiased.
    pivot_clean = ((drops == 0)
                   & ~np.isnan(x_green) & ~np.isnan(y_green))
    if pivot_clean.sum() >= 3:
        xs = x_green[pivot_clean].astype(float)
        ys = y_green[pivot_clean].astype(float)
        # Linear circle fit: solve A·[cx, cy, c]ᵀ = b where
        # 2·gx·cx + 2·gy·cy + c = gx² + gy²  and  c = r² − cx² − cy².
        A = np.column_stack([2 * xs, 2 * ys, np.ones_like(xs)])
        b = xs * xs + ys * ys
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        med_px = float(sol[0])
        med_py = float(sol[1])
        pivot_drift_px = float(
            np.hypot(med_px - PIVOT[0], med_py - PIVOT[1]))
    else:
        med_px = med_py = float("nan")
        pivot_drift_px = float("nan")

    # ── Headline numbers ────────────────────────────────────────────────
    n_drop          = int(np.sum(drops == 1))
    n_suspect       = int(np.sum(suspect))
    n_drop_suspect  = int(np.sum(suspect & (drops == 1)))
    n_clean_suspect = int(np.sum(suspect & (drops == 0)))

    render_verification_summary(
        n, n_drop, n_suspect, n_clean_suspect, dt_med,
        extras={
            "n_accel_suspect":          n_accel_suspect,
            "n_swap_suspect":           n_swap_suspect,
            "n_residual_suspect":       n_residual_suspect,
            "n_energy_suspect":         n_energy_suspect,
            "n_energy_ceiling_suspect": n_energy_ceiling_suspect,
            "n_energy_rolling_spike":   n_energy_rolling_spike,
            "n_trend_arm_suspect":      n_trend_arm_suspect,
            "n_trend_windows":          n_trend_windows,
        })

    # ── Per-arm breakdown ──────────────────────────────────────────────
    clean = drops == 0
    render_arm_breakdown({
        "arm1_only": int(np.sum(suspect1 & ~suspect2 & clean)),
        "arm2_only": int(np.sum(suspect2 & ~suspect1 & clean)),
        "both":      int(np.sum(suspect1 & suspect2 & clean)),
    })

    # ── Phase breakdown ────────────────────────────────────────────────
    holding = phase == "holding"
    free    = phase == "free_swing"
    render_phase_summary({
        "holding": {
            "suspect":     int(np.sum(suspect & clean & holding)),
            "total_clean": int(np.sum(clean & holding)),
        },
        "free_swing": {
            "suspect":     int(np.sum(suspect & clean & free)),
            "total_clean": int(np.sum(clean & free)),
        },
    })

    # ── Show worst-offender frames ─────────────────────────────────────
    suspects_list = []
    if n_clean_suspect > 0:
        # Combined |ω| score (max of the two)
        worst_score = np.fmax(np.abs(om1), np.abs(om2))
        worst_score[~(suspect & clean)] = -1
        idx_sorted = np.argsort(worst_score)[::-1]
        worst = idx_sorted[:min(10, n_clean_suspect)]
        for i in worst:
            arm_l_val   = (float(arm_len[i])
                           if not np.isnan(arm_len[i]) else None)
            arm_dev_val = (float(arm_dev_pct[i])
                           if not np.isnan(arm_dev_pct[i]) else None)
            suspects_list.append({
                "frame":              int(rows[i]["frame"]),
                "time_s":             float(times[i]),
                "phase":              str(phase[i]),
                "th1":                float(th1[i]),
                "th2":                float(th2[i]),
                "om1":                float(abs(om1[i])),
                "om2":                float(abs(om2[i])),
                "arm_length_px":      arm_l_val,
                "arm_length_dev_pct": arm_dev_val,
            })
    render_suspect_table(suspects_list, omega_cap=args.omega_cap)

    # ── Arm-length violations (rigid-body sanity) ──────────────────────
    violations_list = []
    for i in np.where(arm_violation)[0]:
        violations_list.append({
            "frame":          int(rows[i]["frame"]),
            "time_s":         float(times[i]),
            "phase":          str(phase[i]),
            "arm_length_px":  float(arm_len[i]),
            "median_arm_px":  float(arm_median),
            "dev_pct":        float(arm_dev_pct[i]),
        })
    render_arm_length_violations(violations_list)

    # ── Brief 6 Check C — pivot drift (run-level render) ────────────────
    # Brief 11b: pass the MAX arm-length deviation so render can
    # suppress the drift number when tracking is too corrupted for
    # back-projection to be meaningful. Max separates clean (≤3%) from
    # bad (≥31%) cleanly; mean does not, because the global-median
    # normaliser biases toward the majority object.
    if clean_arm_mask.any():
        max_arm_dev = float(np.nanmax(arm_dev_pct[clean_arm_mask]))
    else:
        max_arm_dev = float("nan")
    render_pivot_check(PIVOT, (med_px, med_py), pivot_drift_px,
                       max_arm_dev_pct=max_arm_dev)

    # ── Optional: write CSV with extra audit columns ───────────────────
    if not args.no_csv_out:
        os.makedirs(output_dir, exist_ok=True)
        out_csv = os.path.join(output_dir, "verification.csv")
        with open(out_csv, "w", newline="") as f:
            # Brief 6 columns. Note: there is documented overlap between
            # energy_suspect and the existing arm_dev_pct flags around
            # frames 213-226 of th1_p001_th2_p093 — both are signatures
            # of the same wrong-target latch viewed from different physics
            # axes (rigid-body vs energy conservation).
            fieldnames = list(rows[0].keys()) + [
                "omega1_deg_s", "omega2_deg_s", "suspect",
                "arm_length_px", "arm_dev_pct", "omega_cap_applied",
                "delta_omega_suspect", "swap_suspect",
                # Brief 6
                "residual_suspect",
                "energy_J",
                "energy_ceiling_suspect",
                "energy_rolling_spike",
                "energy_suspect",
                "trend_arm_suspect",
                # Brief 13 — ω-cap-only mask, separate from the union
                # so the verdict layer can count interpolation-resistant
                # tracking errors without double-counting physics flags.
                "omega_cap_suspect",
            ]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for i, r in enumerate(rows):
                out = dict(r)
                out["omega1_deg_s"] = (
                    f"{om1[i]:.2f}" if not np.isnan(om1[i]) else "")
                out["omega2_deg_s"] = (
                    f"{om2[i]:.2f}" if not np.isnan(om2[i]) else "")
                out["suspect"] = 1 if suspect[i] else 0
                out["arm_length_px"] = (
                    f"{arm_len[i]:.2f}" if not np.isnan(arm_len[i]) else "")
                out["arm_dev_pct"] = (
                    f"{arm_dev_pct[i]:.2f}"
                    if not np.isnan(arm_dev_pct[i]) else "")
                out["omega_cap_applied"] = (
                    f"{OMEGA_CAP_HOLDING:.0f}"
                    if phase[i] == "holding"
                    else f"{args.omega_cap:.0f}")
                out["delta_omega_suspect"] = 1 if accel_suspect[i] else 0
                out["swap_suspect"]        = 1 if swap_suspect[i]  else 0
                out["residual_suspect"]    = 1 if residual_suspect[i] else 0
                out["energy_J"] = (
                    f"{energy[i]:.4f}" if not np.isnan(energy[i]) else "")
                out["energy_ceiling_suspect"] = (
                    1 if energy_ceiling_suspect[i] else 0)
                out["energy_rolling_spike"] = (
                    1 if energy_rolling_spike[i] else 0)
                out["energy_suspect"]   = 1 if energy_suspect[i] else 0
                out["trend_arm_suspect"] = 1 if trend_arm_suspect[i] else 0
                out["omega_cap_suspect"] = 1 if omega_cap_suspect[i] else 0
                w.writerow(out)

        # Brief 6 — sidecar JSON for run-level metrics that don't fit
        # the per-frame CSV (pivot drift + E_release reference).
        meta_path = os.path.join(output_dir, "verification_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "pivot_drift_px":
                    None if np.isnan(pivot_drift_px) else float(pivot_drift_px),
                "pivot_inferred_px":
                    None if np.isnan(med_px) else [float(med_px),
                                                   float(med_py)],
                "pivot_hardcoded_px": list(PIVOT),
                "energy_release_J":
                    None if np.isnan(E_release) else float(E_release),
                "n_trend_arm_windows":  int(n_trend_windows),
                "n_residual_suspects":  int(n_residual_suspect),
                "n_energy_suspects":         int(n_energy_suspect),
                "n_energy_ceiling_suspects": int(n_energy_ceiling_suspect),
                "n_energy_rolling_spikes":   int(n_energy_rolling_spike),
                "n_trend_arm_suspects":      int(n_trend_arm_suspect),
            }, f, indent=2)
        print(f"\nWrote: {out_csv}")

    # ── Optional: matplotlib plot ──────────────────────────────────────
    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("\nmatplotlib not available — skipping plot")
            return

        fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)

        axes[0].plot(times, th1, lw=0.6, label="θ1")
        axes[0].plot(times, th2, lw=0.6, label="θ2", alpha=0.7)
        if n_clean_suspect > 0:
            mask = suspect & clean
            axes[0].scatter(times[mask], th1[mask], s=8, c="red",
                            label="suspect θ1", zorder=3)
            axes[0].scatter(times[mask], th2[mask], s=8, c="darkred",
                            label="suspect θ2", zorder=3)
        axes[0].axvline(times[(phase == "free_swing").argmax()],
                        color="grey", ls="--", lw=0.8, label="release")
        axes[0].set_ylabel("angle (deg)")
        axes[0].legend(loc="upper right", fontsize=8)
        axes[0].grid(alpha=0.3)

        axes[1].plot(times, om1, lw=0.5, label="ω1")
        axes[1].plot(times, om2, lw=0.5, label="ω2", alpha=0.7)
        axes[1].axhline( args.omega_cap, color="red", ls=":", lw=0.7)
        axes[1].axhline(-args.omega_cap, color="red", ls=":", lw=0.7,
                        label=f"±{args.omega_cap:.0f} deg/s cap")
        axes[1].set_ylabel("ω (deg/s)")
        axes[1].legend(loc="upper right", fontsize=8)
        axes[1].grid(alpha=0.3)

        # Bottom panel: dropout / suspect timeline
        axes[2].fill_between(times, 0, drops,
                             step="mid", color="grey", alpha=0.6,
                             label="dropout")
        axes[2].fill_between(times, 0, suspect.astype(int),
                             step="mid", color="red", alpha=0.4,
                             label="suspect")
        axes[2].set_yticks([0, 1])
        axes[2].set_ylabel("flags")
        axes[2].set_xlabel("time (s)")
        axes[2].legend(loc="upper right", fontsize=8)
        axes[2].grid(alpha=0.3)

        plt.suptitle(f"{stem}  —  "
                     f"dropouts {n_drop} ({100*n_drop/n:.1f}%)  |  "
                     f"hidden suspects {n_clean_suspect} "
                     f"({100*n_clean_suspect/n:.2f}%)")
        plt.tight_layout()

        # Canonical: figures/verification/<stem>_verification.png.
        # Derive the stem from the measurements/<stem>/ folder name.
        derived_stem = os.path.basename(output_dir)
        out_png = figure_path("verification", derived_stem)
        plt.savefig(out_png, dpi=140)
        print(f"Plot: {out_png}")

if __name__ == "__main__":
    main()
