"""
track_one.py
-------------
Per-video orchestrator: run ring_tracker → verify_tracking →
interpolate_suspects (if needed) → re-verify, then print a single
verdict card so the human in the loop knows whether to keep the run,
re-tune HSV and retry, or move on.

This is the single user-facing command for the "track + assess
quality" pipeline. Bulk_track wraps this for sweeps; for individual
videos call this directly.

Usage
~~~~~
    # Mode 1 — by config_description (the measurement folder name):
    python scripts/utils/track_one.py --stem th1_p047_th2_m002

    # Mode 2 — by video path (resolves config_description from registry):
    python scripts/utils/track_one.py Videos/th1_p047_th2_m002.mov

    # Skip the interpolation step (track + verify only):
    python scripts/utils/track_one.py --stem th1_p047_th2_m002 --no-interpolate

    # Skip the HSV adequacy probe (passes --skip-probe to ring_tracker):
    python scripts/utils/track_one.py --stem th1_p047_th2_m002 --skip-probe

    # Custom suspect-detection cap for verify (default 2500 deg/s):
    python scripts/utils/track_one.py --stem th1_p047_th2_m002 --omega-cap 1800

The verdict card writes itself to stdout AND appends to
data/track_one_log.txt so a bulk run produces a tail-able transcript.
"""

import argparse
import csv
import datetime
import json
import math
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
MEAS_DIR         = os.path.join(ROOT, "measurements")
DATA_DIR         = os.path.join(ROOT, "data")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
LOG_FILE         = os.path.join(DATA_DIR, "track_one_log.txt")

TRACKER_SCRIPT  = os.path.join(ROOT, "scripts", "processing", "ring_tracker.py")
VERIFY_SCRIPT   = os.path.join(ROOT, "scripts", "processing", "verify_tracking.py")
INTERP_SCRIPT   = os.path.join(ROOT, "scripts", "processing",
                               "interpolate_suspects.py")
GLOBAL_HSV_FILE = os.path.join(DATA_DIR, "hsv_values.json")

# scripts/utils is already in sys.path because Python auto-adds the
# script's directory; this re-affirms it for the case where track_one
# is imported from another script (e.g. manual_correction).
sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from render import render_verdict  # noqa: E402
from thresholds import (  # noqa: E402
    ARM_LEN_THRESHOLD_PCT,
    OMEGA_CAP_HOLDING,
    THETA_RESIDUAL_CAP_DEG,
    ENERGY_SPIKE_FACTOR,
    ARM_LENGTH_TREND_WINDOW,
    PIVOT_DRIFT_FAIL_PX,
    ARM_LENGTH_CM,
)


# ─────────────────────────────────────────────
# REGISTRY HELPERS
# ─────────────────────────────────────────────

def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_entry_by_video(reg, video_filename):
    """Return (key, entry) for the registry row whose video_file matches."""
    for k, e in reg.items():
        if e.get("video_file") == video_filename:
            return k, e
    return None, None


def find_entry_by_stem(reg, stem):
    """Return (key, entry) for the registry row whose config_description matches."""
    for k, e in reg.items():
        if e.get("config_description") == stem:
            return k, e
    # Also accept registry keys directly (e.g. legacy DSC_xxxx).
    if stem in reg:
        return stem, reg[stem]
    return None, None


def resolve_inputs(args):
    """
    Returns (video_path, stem, key, entry).
    Either --stem or a positional video path must identify exactly one entry.
    """
    reg = load_registry()
    if args.stem:
        key, entry = find_entry_by_stem(reg, args.stem)
        if not entry:
            print(f"ERROR: no registry entry has config_description "
                  f"'{args.stem}' (and no key matches).")
            sys.exit(1)
        video_filename = entry.get("video_file")
        if not video_filename:
            print(f"ERROR: registry entry for '{args.stem}' has no video_file.")
            sys.exit(1)
        video_path = os.path.join(VIDEOS_DIR, video_filename)
        return video_path, args.stem, key, entry

    if args.video:
        video_path = args.video
        if not os.path.isabs(video_path):
            video_path = os.path.join(ROOT, video_path)
        if not os.path.exists(video_path):
            print(f"ERROR: video not found: {video_path}")
            sys.exit(1)
        video_filename = os.path.basename(video_path)
        key, entry = find_entry_by_video(reg, video_filename)
        if not entry:
            print(f"ERROR: video '{video_filename}' has no registry entry. "
                  f"Add one to experiments.json first.")
            sys.exit(1)
        stem = entry.get("config_description") or os.path.splitext(video_filename)[0]
        return video_path, stem, key, entry

    print("ERROR: provide --stem or a positional video path.")
    sys.exit(1)


# ─────────────────────────────────────────────
# CSV PARSING (for verdict metrics)
# ─────────────────────────────────────────────

def read_verification_metrics(meas_dir):
    """
    Read measurements/<stem>/verification.csv and return a dict of
    per-stem stats consumed by the verdict-card layer.

    Optional columns added by Brief 3 (arm_length_px, arm_dev_pct) and
    Brief 5 (delta_omega_suspect, swap_suspect) are read defensively —
    older verification.csv files without those columns parse cleanly
    with the corresponding metrics returning None / 0.

    Returns None if verification.csv is missing.
    """
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return None
    n_total = n_drop_total = n_suspect_hidden = 0
    n_free = n_free_drop = n_hold = n_hold_drop = 0
    n_hold_susp = 0
    peak_o1 = peak_o2 = 0.0
    arm_devs = []
    n_arm_violations = 0
    n_accel_suspect = 0
    n_swap_suspect  = 0
    # Brief 6 — defensive read of new columns; older verification.csv
    # files lack them and parse cleanly with these counters at 0.
    n_residual_suspect       = 0
    n_energy_suspect         = 0
    n_energy_ceiling_suspect = 0
    n_energy_rolling_spike   = 0
    n_trend_arm_suspect      = 0
    # Brief 13 — ω-cap-only count (interpolation-resistant tracking
    # errors), distinct from the union-of-all-checks suspect mask.
    n_omega_cap_suspect      = 0
    with open(path, "r", newline="") as f:
        for r in csv.DictReader(f):
            n_total += 1
            phase   = r.get("phase", "")
            try:
                drop = int(r.get("dropout") or 0)
            except ValueError:
                drop = 0
            try:
                susp = int(r.get("suspect") or 0)
            except ValueError:
                susp = 0
            if drop:
                n_drop_total += 1
                if phase == "holding":  n_hold_drop += 1
                if phase == "free_swing": n_free_drop += 1
            if phase == "holding":  n_hold += 1
            if phase == "free_swing": n_free += 1
            if susp and not drop:
                n_suspect_hidden += 1
                if phase == "holding":
                    n_hold_susp += 1
            try:
                o1 = abs(float(r.get("omega1_deg_s") or 0))
                if o1 > peak_o1: peak_o1 = o1
            except ValueError:
                pass
            try:
                o2 = abs(float(r.get("omega2_deg_s") or 0))
                if o2 > peak_o2: peak_o2 = o2
            except ValueError:
                pass
            # Arm-length deviation (Brief 3) — column is optional; only
            # appears in verifications produced after the upgrade.
            try:
                dev_str = r.get("arm_dev_pct") or ""
                if dev_str:
                    dev = float(dev_str)
                    if not math.isnan(dev):
                        arm_devs.append(dev)
                        if dev > ARM_LEN_THRESHOLD_PCT:
                            n_arm_violations += 1
            except ValueError:
                pass
            # Brief 5 columns — defensive (older verification.csv lacks them).
            try:
                if int(r.get("delta_omega_suspect") or 0) == 1:
                    n_accel_suspect += 1
            except ValueError:
                pass
            try:
                if int(r.get("swap_suspect") or 0) == 1:
                    n_swap_suspect += 1
            except ValueError:
                pass
            # Brief 6 columns — defensive.
            for col, counter_name in (
                ("residual_suspect",       "n_residual_suspect"),
                ("energy_suspect",         "n_energy_suspect"),
                ("energy_ceiling_suspect", "n_energy_ceiling_suspect"),
                ("energy_rolling_spike",   "n_energy_rolling_spike"),
                ("trend_arm_suspect",      "n_trend_arm_suspect"),
                ("omega_cap_suspect",      "n_omega_cap_suspect"),
            ):
                try:
                    if int(r.get(col) or 0) == 1:
                        # Bump the local var by name without eval/exec.
                        if counter_name == "n_residual_suspect":
                            n_residual_suspect += 1
                        elif counter_name == "n_energy_suspect":
                            n_energy_suspect += 1
                        elif counter_name == "n_energy_ceiling_suspect":
                            n_energy_ceiling_suspect += 1
                        elif counter_name == "n_energy_rolling_spike":
                            n_energy_rolling_spike += 1
                        elif counter_name == "n_trend_arm_suspect":
                            n_trend_arm_suspect += 1
                        elif counter_name == "n_omega_cap_suspect":
                            # Brief 13 — only count clean (dropout=0)
                            # frames; ω is undefined on dropout rows.
                            if not drop:
                                n_omega_cap_suspect += 1
                except (ValueError, TypeError):
                    pass

    # Brief 6 sidecar — pivot drift, E_release, and trend-window count
    # don't fit the per-frame CSV; verify_tracking writes them to
    # verification_meta.json. Read defensively so older runs without
    # the sidecar still parse cleanly.
    meta_path = os.path.join(meas_dir, "verification_meta.json")
    pivot_drift_px      = None
    energy_release_J    = None
    n_trend_arm_windows = 0
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            pivot_drift_px      = meta.get("pivot_drift_px")
            energy_release_J    = meta.get("energy_release_J")
            n_trend_arm_windows = int(meta.get("n_trend_arm_windows") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    return {
        "n_total":               n_total,
        "n_dropout_total":       n_drop_total,
        "n_dropout_holding":     n_hold_drop,
        "n_dropout_free_swing":  n_free_drop,
        "n_holding":             n_hold,
        "n_free_swing":          n_free,
        "n_suspect_hidden":      n_suspect_hidden,
        "n_holding_suspects":    n_hold_susp,
        "peak_omega1":           peak_o1,
        "peak_omega2":           peak_o2,
        "free_swing_dropout_pct":
            round(100.0 * n_free_drop / n_free, 2) if n_free else None,
        "holding_dropout_pct":
            round(100.0 * n_hold_drop / n_hold, 2) if n_hold else None,
        "arm_length_dev_max_pct":
            round(max(arm_devs), 2) if arm_devs else None,
        "arm_length_dev_mean_pct":
            round(sum(arm_devs) / len(arm_devs), 2) if arm_devs else None,
        "n_arm_violations":      n_arm_violations,
        "n_accel_suspects":      n_accel_suspect,
        "n_swap_suspects":       n_swap_suspect,
        # Brief 6
        "n_residual_suspects":         n_residual_suspect,
        "n_energy_suspects":           n_energy_suspect,
        "n_energy_ceiling_suspects":   n_energy_ceiling_suspect,
        "n_energy_rolling_spikes":     n_energy_rolling_spike,
        "n_trend_arm_suspects":        n_trend_arm_suspect,
        "n_trend_arm_windows":         n_trend_arm_windows,
        "pivot_drift_px":              pivot_drift_px,
        "energy_release_J":            energy_release_J,
        # Brief 13
        "n_omega_cap_suspects":        n_omega_cap_suspect,
    }


# ─────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────

# Verdict-band thresholds live in scripts/utils/thresholds.py — single
# source of truth shared with the render layer. Re-exported here so
# legacy callers that imported these constants from track_one keep
# working without churning their imports.
from thresholds import (  # noqa: E402
    PASS_DROPOUT_PCT,
    WARN_DROPOUT_PCT,
    PEAK_OMEGA_PHYSICAL,
    PEAK_OMEGA_ABSURD,
)


def compute_verdict(metrics, n_suspects_post_interp):
    """
    Returns (status, reasons_list) where status ∈ {PASS, WARN, FAIL}.

    Brief 13: the legacy `n_suspects_post_interp` parameter is the
    union of ω-cap + every Brief 5/6 physics check. That double-counts
    physics suspects (each check has its own dedicated reason below)
    and inflates WARN verdicts on otherwise-clean tracking. We now
    prefer `metrics["n_omega_cap_suspects"]` — the count of frames
    flagged ONLY by the ω-cap mask, which is what
    interpolate_suspects.py can actually fix. The parameter is kept
    for callers that haven't migrated; it's only used as a fallback
    when the new metric is absent (older verification.csv).
    """
    reasons = []
    drop = metrics.get("free_swing_dropout_pct")
    peak2 = metrics.get("peak_omega2", 0.0)

    if drop is None:
        return "FAIL", ["no free_swing frames in verification.csv"]

    if drop > WARN_DROPOUT_PCT:
        reasons.append(f"free-swing dropout {drop:.1f}% > {WARN_DROPOUT_PCT}%")
        return "FAIL", reasons
    if peak2 > PEAK_OMEGA_ABSURD:
        reasons.append(
            f"peak |ω₂| {peak2:.0f}°/s > {PEAK_OMEGA_ABSURD:.0f}°/s "
            f"(likely tracking error)")
        return "FAIL", reasons

    if drop > PASS_DROPOUT_PCT:
        reasons.append(f"free-swing dropout {drop:.1f}% in 5–10% band")

    # Brief 13: report only ω-cap suspects under "residual suspects
    # post-interpolation" — interpolation only acts on the ω-cap mask,
    # so physics-check suspects don't belong in this count. Fall back
    # to the union count when the new column is missing (older CSVs).
    n_omega_cap_post = metrics.get("n_omega_cap_suspects")
    if n_omega_cap_post is None:
        n_omega_cap_post = n_suspects_post_interp
    if n_omega_cap_post > 0:
        reasons.append(
            f"{n_omega_cap_post} ω-cap suspects survived interpolation")

    if peak2 > PEAK_OMEGA_PHYSICAL:
        reasons.append(
            f"peak |ω₂| {peak2:.0f}°/s > {PEAK_OMEGA_PHYSICAL:.0f}°/s "
            f"physical rule-of-thumb")

    # Brief 3: holding-phase suspects (markers should be stationary).
    n_hold_susp = metrics.get("n_holding_suspects", 0)
    if n_hold_susp > 0:
        reasons.append(
            f"{n_hold_susp} holding-phase suspects "
            f"(|ω| > {OMEGA_CAP_HOLDING:.0f}°/s while stationary)")

    # Brief 3: arm-length rigidity violations (rigid-body sanity).
    n_arm = metrics.get("n_arm_violations", 0)
    if n_arm > 0:
        dev_max = metrics.get("arm_length_dev_max_pct") or 0.0
        reasons.append(
            f"{n_arm} arm-length violation(s) "
            f"(max deviation {dev_max:.1f}%) — tracker latched on wrong object")

    # Brief 5: angular-acceleration spikes — unphysical Δω between
    # consecutive frames. Catches latches onto slow wrong objects that
    # ω alone misses. > 3 of these tips a borderline PASS into WARN.
    n_accel = metrics.get("n_accel_suspects", 0)
    if n_accel > 0:
        reasons.append(
            f"{n_accel} frame(s) with |Δω| spike "
            f"(unphysical acceleration)")

    # Brief 5: marker-swap candidates — green/red appear to exchange
    # positions between consecutive frames.
    n_swap = metrics.get("n_swap_suspects", 0)
    if n_swap > 0:
        reasons.append(
            f"{n_swap} frame(s) where green/red markers "
            f"appear to have swapped labels")

    # ── Brief 6 — physics checks ──────────────────────────────────────
    # State track for the running verdict status. We may need to
    # upgrade WARN→FAIL when the energy-ceiling fraction or trend-arm
    # fraction is high, so threading status through these branches.
    status = "PASS" if not reasons else "WARN"

    # Trend arm-length runs first because a high trend-window count
    # signals a long, stable wrong-target episode that interpolation
    # cannot fix — should usually FAIL.
    n_tw = metrics.get("n_trend_arm_windows",  0)
    n_ts = metrics.get("n_trend_arm_suspects", 0)
    n_free = metrics.get("n_free_swing", 1) or 1
    if n_tw > 0:
        frac = n_ts / max(n_free, 1)
        reasons.append(
            f"{n_tw} window(s) of {ARM_LENGTH_TREND_WINDOW} frames "
            f"show arm-length drift from the reference window "
            f"({100*frac:.1f}% of free_swing affected) — "
            f"stable wrong-target episode suspected")
        status = "FAIL" if frac > 0.15 else "WARN"

    # θ-residual: a few are reviewable; many means systematic.
    n_res = metrics.get("n_residual_suspects", 0)
    if n_res > 0:
        reasons.append(
            f"{n_res} frame(s) with θ-prediction residual "
            f"> {THETA_RESIDUAL_CAP_DEG:.1f}° "
            f"(position inconsistent with recent velocity)")
        if n_res > 5 and status == "PASS":
            status = "WARN"

    # Energy ceiling — strong signal of stable wrong-target latch.
    n_ceil = metrics.get("n_energy_ceiling_suspects", 0)
    n_roll = metrics.get("n_energy_rolling_spikes",   0)
    if n_ceil > 0:
        frac = n_ceil / max(n_free, 1)
        reasons.append(
            f"{n_ceil} frame(s) exceed release-energy ceiling "
            f"({100*frac:.1f}% of free_swing) — "
            f"probable stable wrong-target latch")
        if frac > 0.10:
            status = "FAIL"
        elif status != "FAIL":
            status = "WARN"

    if n_roll > 0 and status != "FAIL":
        reasons.append(
            f"{n_roll} frame(s) show rolling energy spike "
            f"(>{ENERGY_SPIKE_FACTOR:.1f}× baseline) — "
            f"tracker likely jumped briefly to wrong object")
        if status == "PASS":
            status = "WARN"

    # Pivot drift — run-level geometry check.
    drift = metrics.get("pivot_drift_px")
    if (drift is not None
            and not (isinstance(drift, float) and math.isnan(drift))
            and drift >= PIVOT_DRIFT_FAIL_PX):
        reasons.append(
            f"inferred pivot drifts {drift:.1f}px from hardcoded "
            f"PIVOT — ring geometry may be miscalibrated")
        if status == "PASS":
            status = "WARN"

    if reasons:
        return status, reasons
    return "PASS", ["dropout, suspects, and ω all within thresholds"]


# ─────────────────────────────────────────────
# ACTIONABLE-STEPS BUILDER  (Brief 4)
# ─────────────────────────────────────────────

def _load_top_suspect_frames(meas_dir, n=5):
    """Read verification.csv and return the top n suspect rows by |ω₂|
    where suspect=1 and dropout=0. Each item:
      {"frame": int, "time_s": float, "phase": str, "om2": float}
    Returns [] when the file is missing or no suspects exist."""
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return []
    candidates = []
    with open(path, "r", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if int(r.get("suspect") or 0) != 1:
                    continue
                if int(r.get("dropout") or 0) != 0:
                    continue
                om2 = abs(float(r.get("omega2_deg_s") or 0))
                candidates.append({
                    "frame":  int(r["frame"]),
                    "time_s": float(r["time_s"]),
                    "phase":  r.get("phase", ""),
                    "om2":    om2,
                })
            except (ValueError, TypeError, KeyError):
                continue
    candidates.sort(key=lambda c: -c["om2"])
    return candidates[:n]


def compute_energy_omega_cap(entry: dict):
    """
    Brief 7 — IC-aware energy cap.
    Derives the physical upper bound on |ω₂| from release ICs.
    Conservative: assumes all release energy concentrates in arm-2
    rotation. Returns °/s, or None if release ICs are unavailable.
    """
    th1 = entry.get("theta1_release")
    th2 = entry.get("theta2_release")
    if th1 is None or th2 is None:
        return None

    L = ARM_LENGTH_CM / 100.0
    g = 9.8

    th1_r     = math.radians(float(th1))
    th2_abs_r = math.radians(float(th1) + float(th2))

    # PE at release (both arms, reference = hanging straight down).
    PE = g * L * (1 - math.cos(th1_r)) + g * L * (1 - math.cos(th2_abs_r))

    KE = 0.0
    w1 = entry.get("omega1_release")
    w2 = entry.get("omega2_release")
    if w1 is not None and w2 is not None:
        w1_r = math.radians(abs(float(w1)))
        w2_r = math.radians(abs(float(w2)))
        KE = 0.5 * (L * w1_r) ** 2 + 0.5 * (L * (w1_r + w2_r)) ** 2

    E_total = PE + KE
    if E_total <= 0:
        return None

    return math.degrees(math.sqrt(2.0 * E_total) / L)


def build_actionable_steps(stem, metrics_post, reasons, status,
                           suspect_frames=None, *, entry=None,
                           energy_cap=None):
    """Translate metrics + verdict into copy-paste-ready guidance.

    Returns a list of dicts:
      {"priority": "required" | "review" | "info",
       "category": "suspect_frame" | "dropout" | "arm_length" |
                   "holding_suspect" | "verified",
       "text":    str,
       "command": str | None}

    User-facing commands use the `chaos` wrapper (chaos override / fix /
    tune / verify) rather than `python scripts/...` paths so the steps
    stay aligned with the documented user surface.
    """
    steps = []
    metrics_post = metrics_post or {}

    # A) residual suspect frames post-interpolation
    n_susp_hidden = metrics_post.get("n_suspect_hidden", 0)
    if n_susp_hidden > 0 and suspect_frames:
        for f in suspect_frames[:3]:
            steps.append({
                "priority": "required",
                "category": "suspect_frame",
                "text": (
                    f"Frame {f['frame']}  "
                    f"(t = {f['time_s']:.3f}s,  {f['phase']}):  "
                    f"|ω₂| = {f['om2']:.0f} °/s\n"
                    f"  Check verification.png at this timestamp.\n"
                    f"  If the marker position looks wrong, correct it manually."
                ),
                # Single-frame fixes go through `chaos override`; the
                # legacy manual_correction tool is for multi-frame
                # cluster fixes.
                "command": f"chaos override {stem} --frame {f['frame']}",
            })
        if len(suspect_frames) > 3:
            steps.append({
                "priority": "info",
                "category": "suspect_frame",
                "text": (f"... and {len(suspect_frames) - 3} more suspect "
                         f"frames. Run verify_tracking for the full list."),
                "command": f"chaos verify {stem}",
            })

    # B) free-swing dropout in WARN band
    drop = metrics_post.get("free_swing_dropout_pct")
    n_drop_free = metrics_post.get("n_dropout_free_swing", "?")
    if drop is not None and PASS_DROPOUT_PCT < drop <= WARN_DROPOUT_PCT:
        steps.append({
            "priority": "review",
            "category": "dropout",
            "text": (
                f"{drop:.1f}% free-swing dropout ({n_drop_free} frames).\n"
                f"  Open verification.png and check for a cluster of red\n"
                f"  markers in a narrow window — that indicates occlusion\n"
                f"  or lighting. Even distribution → HSV recalibration."
            ),
            "command": f"chaos tune {stem}",
        })

    # C) free-swing dropout above WARN — auto-FAIL
    if drop is not None and drop > WARN_DROPOUT_PCT:
        steps.append({
            "priority": "required",
            "category": "dropout",
            "text": (
                f"{drop:.1f}% free-swing dropout — exceeds "
                f"{WARN_DROPOUT_PCT}% FAIL threshold.\n"
                f"  This run likely cannot be salvaged without re-tracking.\n"
                f"  Step 1: Recalibrate HSV. Step 2: re-run chaos track."
            ),
            "command": f"chaos tune {stem}",
        })

    # D) arm-length violations
    n_arm = metrics_post.get("n_arm_violations", 0)
    arm_dev_max = metrics_post.get("arm_length_dev_max_pct")
    if n_arm > 0:
        priority = "required" if (arm_dev_max or 0) > 20 else "review"
        steps.append({
            "priority": priority,
            "category": "arm_length",
            "text": (
                f"{n_arm} frame(s) violate rigid-arm constraint "
                f"(max deviation: {(arm_dev_max or 0):.1f}%).\n"
                f"  These frames show the tracker latched onto a wrong\n"
                f"  object. They cannot be fixed by interpolation alone —\n"
                f"  inspect each frame visually and correct or mark unresolvable."
            ),
            "command": f"chaos verify {stem}",
        })

    # E) holding-phase suspects
    n_hold = metrics_post.get("n_holding_suspects", 0)
    if n_hold > 0:
        steps.append({
            "priority": "review",
            "category": "holding_suspect",
            "text": (
                f"{n_hold} frame(s) in holding phase have "
                f"|ω| > {OMEGA_CAP_HOLDING:.0f} °/s.\n"
                f"  The pendulum should be stationary here — this is\n"
                f"  tracker noise. Acceptable if 1-2; concerning if > 5."
            ),
            "command": None,
        })

    # F) peak ω₂ above physical rule-of-thumb
    peak2 = metrics_post.get("peak_omega2", 0.0)
    if PEAK_OMEGA_PHYSICAL < peak2 <= PEAK_OMEGA_ABSURD:
        steps.append({
            "priority": "review",
            "category": "suspect_frame",
            "text": (
                f"Peak |ω₂| = {peak2:.0f} °/s exceeds "
                f"{PEAK_OMEGA_PHYSICAL:.0f} °/s physical rule-of-thumb.\n"
                f"  May be physical (extreme chaotic event) or a residual\n"
                f"  tracking artefact. Check verification.png near peak ω₂."
            ),
            "command": None,
        })
    if peak2 > PEAK_OMEGA_ABSURD:
        steps.append({
            "priority": "required",
            "category": "suspect_frame",
            "text": (
                f"Peak |ω₂| = {peak2:.0f} °/s > {PEAK_OMEGA_ABSURD:.0f} °/s "
                f"absurd threshold.\n"
                f"  Almost certainly a tracking error, not physics.\n"
                f"  Manual correction or re-tracking required."
            ),
            "command": f"chaos fix {stem}",
        })

    # ── Brief 6 ──────────────────────────────────────────────────────
    n_tw = metrics_post.get("n_trend_arm_windows", 0)
    n_ts = metrics_post.get("n_trend_arm_suspects", 0)
    if n_tw > 0:
        steps.append({
            "priority": "required",
            "category": "arm_length",
            "text": (
                f"{n_tw} window(s) of {ARM_LENGTH_TREND_WINDOW} frames "
                f"show sustained arm-length drift ({n_ts} frames total).\n"
                f"  The tracker likely latched onto a non-marker object "
                f"for an extended run. The per-frame arm check cannot "
                f"catch this because the global median was corrupted.\n"
                f"  Interpolation will not fix a run this long.\n"
                f"  Add a seed at the latch entry point, or recalibrate "
                f"HSV and re-track."
            ),
            "command": f"chaos fix {stem}",
        })

    n_res = metrics_post.get("n_residual_suspects", 0)
    if n_res > 0:
        steps.append({
            "priority": "review",
            "category": "suspect_frame",
            "text": (
                f"{n_res} frame(s) show θ position inconsistent with "
                f"recent velocity (residual > "
                f"{THETA_RESIDUAL_CAP_DEG:.1f}°).\n"
                f"  Likely: slow background object near the ring during "
                f"low-velocity phase.\n"
                f"  Check verification.png for position scatter near "
                f"ω zero-crossings."
            ),
            "command": f"chaos verify {stem}",
        })

    n_ceil = metrics_post.get("n_energy_ceiling_suspects", 0)
    n_roll = metrics_post.get("n_energy_rolling_spikes",   0)
    if n_ceil > 0:
        n_free = max(metrics_post.get("n_free_swing", 1) or 1, 1)
        frac = n_ceil / n_free
        steps.append({
            "priority": "required",
            "category": "suspect_frame",
            "text": (
                f"{n_ceil} frames ({100*frac:.1f}% of free_swing) exceed "
                f"the release-energy ceiling.\n"
                f"  Signature of a sustained wrong-target latch — the "
                f"tracker followed a non-marker object for an extended run.\n"
                f"  Single-frame interpolation cannot fix this. "
                f"Add a seed at the latch entry point or recalibrate HSV."
            ),
            "command": f"chaos fix {stem}",
        })

    if n_roll > 0 and n_ceil == 0:
        steps.append({
            "priority": "review",
            "category": "suspect_frame",
            "text": (
                f"{n_roll} frame(s) show brief energy spikes above the "
                f"rolling baseline.\n"
                f"  Likely: tracker briefly latched onto a wrong object "
                f"and returned. Interpolation may fix these."
            ),
            "command": f"chaos override {stem}",
        })

    # ── Brief 7 — IC-aware energy cap ────────────────────────────────
    peak2 = metrics_post.get("peak_omega2", 0.0)
    if energy_cap is not None and peak2 > energy_cap * 1.2:
        ic_th1 = (entry or {}).get("theta1_release")
        ic_th2 = (entry or {}).get("theta2_release")
        ic_str = (f"θ₁={float(ic_th1):.1f}°, θ₂={float(ic_th2):.1f}°"
                  if ic_th1 is not None and ic_th2 is not None
                  else "(release ICs unavailable)")
        steps.append({
            "priority": "required",
            "category": "suspect_frame",
            "text": (
                f"Peak |ω₂| = {peak2:.0f} °/s exceeds the IC-derived "
                f"energy cap of {energy_cap:.0f} °/s.\n"
                f"  Release: {ic_str}.\n"
                f"  A pendulum released from this configuration physically "
                f"cannot reach {peak2:.0f} °/s.\n"
                f"  This is a tracking error, not chaotic motion."
            ),
            "command": f"chaos override {stem}",
        })

    # G) PASS — no issues found
    if status == "PASS" and not steps:
        steps.append({
            "priority": "info",
            "category": "verified",
            "text": ("All checks passed. tracking_quality has been set to "
                     "'verified'\nin the registry automatically."),
            "command": None,
        })

    return steps


# ─────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────

def run(cmd, *, label):
    """Wrap subprocess.run with a label banner. Returns rc, elapsed_s."""
    print()
    print("─" * 70)
    print(f"[{label}]  {' '.join(str(c) for c in cmd)}")
    print("─" * 70)
    import time
    t0 = time.time()
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    return rc, time.time() - t0


def hsv_kind_for_video(video_filename):
    """Return 'per-video' or 'global' depending on which HSV file applies."""
    stem = os.path.splitext(video_filename)[0]
    if os.path.exists(os.path.join(DATA_DIR, f"hsv_{stem}.json")):
        return "per-video"
    return "global"


def emit_card(stem, video_path, key, entry, *,
              status, reasons,
              metrics_pre, metrics_post,
              n_interpolated, hsv_kind, total_elapsed,
              actionable_steps=None,
              energy_omega_cap=None):
    """Print and append the one-page verdict card. Delegates the
    presentation layer to render.render_verdict; only the log-file
    append stays here."""
    text = render_verdict(
        stem=stem,
        video_path=video_path,
        key=key,
        entry=entry,
        status=status,
        reasons=reasons,
        metrics_pre=metrics_pre,
        metrics_post=metrics_post,
        n_interpolated=n_interpolated,
        hsv_kind=hsv_kind,
        total_elapsed=total_elapsed,
        actionable_steps=actionable_steps,
        energy_omega_cap=energy_omega_cap,
    )
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{datetime.datetime.now().isoformat(timespec='seconds')}\n")
        f.write(text + "\n")
    return text


def maybe_mark_verified(stem, status, reasons):
    """When status is PASS, bump tracking_quality in the registry."""
    if status != "PASS":
        return
    reg = load_registry()
    key, entry = find_entry_by_stem(reg, stem)
    if not entry:
        return
    entry["tracking_quality"]  = "verified"
    entry["verification_date"] = datetime.datetime.now().strftime("%Y-%m-%d")
    entry["verification_notes"] = " ".join(reasons)
    # Brief 8: stamp the brief version this verdict was issued under so
    # generate_roadmap.py can flag pre-Brief-5 PASSes as needing a
    # re-audit. Bump this integer whenever the verdict logic changes.
    # Brief 14 (rod formula + p99 reference + SG-smoothed ω + ω-cap-only
    # post-interp count + tuned ENERGY_SPIKE_FACTOR) is the current
    # verdict logic.
    entry["verified_under_brief_version"] = 14
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Track + verify + interpolate one video, emit verdict card.")
    p.add_argument("video", nargs="?", default=None,
                   help="Path to .mov in Videos/ (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description (e.g. th1_p047_th2_m002).")
    p.add_argument("--no-interpolate", action="store_true",
                   help="Skip interpolate_suspects even if hidden suspects exist.")
    p.add_argument("--skip-probe", action="store_true",
                   help="Pass --skip-probe to ring_tracker (skip HSV adequacy check).")
    p.add_argument("--yes-to-warn", action="store_true",
                   help="Pass --yes-to-warn to ring_tracker (auto-confirm WARN).")
    p.add_argument("--no-debug", action="store_true", default=True,
                   help="Skip debug.mp4 generation (default: skip).")
    p.add_argument("--debug", action="store_true",
                   help="Generate debug.mp4 (overrides --no-debug default).")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="ω threshold for verify_tracking (default 2500 °/s).")
    return p.parse_args()


def main():
    args = parse_args()
    video_path, stem, key, entry = resolve_inputs(args)
    meas_dir = os.path.join(MEAS_DIR, stem)

    print(f"track_one: {stem}")
    print(f"  video       : {video_path}")
    print(f"  registry key: {key}")

    import time
    t_total = time.time()

    # ── 1. Track ───────────────────────────────────────────────────────
    track_cmd = [sys.executable, TRACKER_SCRIPT, video_path, "--force"]
    if not args.debug:
        track_cmd.append("--no-debug")
    if args.skip_probe:
        track_cmd.append("--skip-probe")
    if args.yes_to_warn:
        track_cmd.append("--yes-to-warn")
    rc, _ = run(track_cmd, label="ring_tracker")
    if rc != 0:
        # Ring_tracker uses specific non-zero codes for known abort paths:
        #   2 = HSV adequacy probe ABORT
        #   3 = User cancelled at WARN prompt
        # Anything else is an unexpected error (or the user cancelled the
        # frame picker). Surface the most actionable next step.
        if rc == 2:
            reason = (f"HSV adequacy below {40}% — re-run "
                      f"hsv_tuner.py on this video and try again. "
                      f"(--skip-probe overrides if needed.)")
        elif rc == 3:
            reason = "User cancelled at HSV WARN prompt; no tracking attempted."
        else:
            reason = (f"ring_tracker exit {rc} — likely picker cancellation "
                      f"or unexpected error.")
        emit_card(stem, video_path, key, entry,
                  status="FAIL", reasons=[reason],
                  metrics_pre=None, metrics_post=None,
                  n_interpolated=0,
                  hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
                  total_elapsed=time.time() - t_total)
        return rc

    # ── 2. Verify (pre-interpolation) ──────────────────────────────────
    rc, _ = run([sys.executable, VERIFY_SCRIPT, "--stem", stem,
                 "--omega-cap", str(args.omega_cap), "--no-plot"],
                label="verify_tracking (pre)")
    if rc != 0:
        emit_card(stem, video_path, key, entry,
                  status="FAIL", reasons=[f"verify_tracking exit {rc}"],
                  metrics_pre=None, metrics_post=None,
                  n_interpolated=0,
                  hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
                  total_elapsed=time.time() - t_total)
        return rc
    metrics_pre = read_verification_metrics(meas_dir)
    n_suspects_pre = (metrics_pre or {}).get("n_suspect_hidden", 0)

    # ── 3. Interpolate (only if there are suspects and --no-interpolate
    #      wasn't passed) ─────────────────────────────────────────────
    n_interp = 0
    if n_suspects_pre > 0 and not args.no_interpolate:
        rc, _ = run([sys.executable, INTERP_SCRIPT, "--stem", stem,
                     "--omega-cap", str(args.omega_cap)],
                    label="interpolate_suspects")
        if rc != 0:
            emit_card(stem, video_path, key, entry,
                      status="FAIL", reasons=[f"interpolate_suspects exit {rc}"],
                      metrics_pre=metrics_pre, metrics_post=metrics_pre,
                      n_interpolated=0,
                      hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
                      total_elapsed=time.time() - t_total)
            return rc
        # interpolate_suspects already ran verify internally; re-read.
        metrics_post = read_verification_metrics(meas_dir)
        # Number actually interpolated comes from the registry mutation.
        reg_after = load_registry()
        e_after = (find_entry_by_stem(reg_after, stem)[1] or {})
        n_interp = int(e_after.get("suspect_frames_interpolated", 0))
    else:
        metrics_post = metrics_pre

    # ── 4. Compute verdict ─────────────────────────────────────────────
    n_susp_post = (metrics_post or {}).get("n_suspect_hidden", 0)
    status, reasons = compute_verdict(metrics_post, n_susp_post)

    # ── 5. Build actionable steps + emit card + maybe mark verified ───
    suspect_frames = _load_top_suspect_frames(meas_dir, n=5)
    energy_cap = compute_energy_omega_cap(entry)
    actionable_steps = build_actionable_steps(
        stem=stem,
        metrics_post=metrics_post or metrics_pre or {},
        reasons=reasons,
        status=status,
        suspect_frames=suspect_frames,
        entry=entry,
        energy_cap=energy_cap,
    )
    emit_card(stem, video_path, key, entry,
              status=status, reasons=reasons,
              metrics_pre=metrics_pre, metrics_post=metrics_post,
              n_interpolated=n_interp,
              hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
              total_elapsed=time.time() - t_total,
              actionable_steps=actionable_steps,
              energy_omega_cap=energy_cap)
    maybe_mark_verified(stem, status, reasons)
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
