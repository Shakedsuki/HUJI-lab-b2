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
    python scripts/utils/track_one.py data/videos/th1_p047_th2_m002.mov

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

LOG_FILE         = os.path.join(DATA_DIR, "track_one_log.txt")

# Tracker — Cohen's BGR detection wrapped in pipeline I/O. The HSV ring
# tracker that previously sat behind a phase switch has been removed
# (PR C); driven motion is now the only regime the pipeline targets.
TRACKER_SCRIPT  = os.path.join(REPO_ROOT, "scripts", "processing", "bgr_tracker.py")
VERIFY_SCRIPT   = os.path.join(REPO_ROOT, "scripts", "processing", "verify_tracking.py")

# scripts/utils is already in sys.path because Python auto-adds the
# script's directory; this re-affirms it for the case where track_one
# is imported from another script (e.g. manual_correction).
EXPERIMENTS_FILE = EXPERIMENTS
from render import render_verdict  # noqa: E402
from thresholds import (  # noqa: E402
    ARM_LEN_THRESHOLD_PCT,
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
            video_path = os.path.join(REPO_ROOT, video_path)
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

    Verdict surface (PR D — driven-only pipeline)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Free-swing physics checks (release-energy ceiling, fixed-pivot
    drift, θ-prediction residual, holding-phase ω, trend arm-length,
    energy rolling spike) have been removed — they all produced
    near-universal false positives on driven clips. What's left:

      * dropout band  — > 10% → FAIL,  5-10% → WARN reason
      * peak |ω₂|     — > 4000 °/s → FAIL,  > 1500 °/s → WARN reason
      * arm-length    — any rigid-rod violation → WARN reason
      * |Δω| spike    — any unphysical acceleration → WARN reason
      * marker swap   — any swap candidate       → WARN reason
      * ω-cap suspects→ count → WARN reason

    The `n_suspects_post_interp` parameter is retained for callers
    that still pass it, but interpolation has been retired on the
    driven path so the count is the same as the pre-interp count.
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

    n_omega_cap_post = metrics.get("n_omega_cap_suspects")
    if n_omega_cap_post is None:
        n_omega_cap_post = n_suspects_post_interp
    if n_omega_cap_post > 0:
        reasons.append(f"{n_omega_cap_post} ω-cap suspect frame(s)")

    if peak2 > PEAK_OMEGA_PHYSICAL:
        reasons.append(
            f"peak |ω₂| {peak2:.0f}°/s > {PEAK_OMEGA_PHYSICAL:.0f}°/s "
            f"physical rule-of-thumb")

    n_arm = metrics.get("n_arm_violations", 0)
    if n_arm > 0:
        dev_max = metrics.get("arm_length_dev_max_pct") or 0.0
        reasons.append(
            f"{n_arm} arm-length violation(s) "
            f"(max deviation {dev_max:.1f}%) — tracker latched on wrong object")

    n_accel = metrics.get("n_accel_suspects", 0)
    if n_accel > 0:
        reasons.append(
            f"{n_accel} frame(s) with |Δω| spike "
            f"(unphysical acceleration)")

    n_swap = metrics.get("n_swap_suspects", 0)
    if n_swap > 0:
        reasons.append(
            f"{n_swap} frame(s) where green/red markers "
            f"appear to have swapped labels")

    if reasons:
        return "WARN", reasons
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
                f"  markers in a narrow window — that indicates occlusion,\n"
                f"  lighting issues, or the markers leaving the crop window."
            ),
            "command": None,
        })

    # C) free-swing dropout above WARN — auto-FAIL
    if drop is not None and drop > WARN_DROPOUT_PCT:
        steps.append({
            "priority": "required",
            "category": "dropout",
            "text": (
                f"{drop:.1f}% free-swing dropout — exceeds "
                f"{WARN_DROPOUT_PCT}% FAIL threshold.\n"
                f"  Run is likely unrecoverable. Re-shoot the clip with\n"
                f"  consistent lighting and the markers inside the\n"
                f"  CROP_X_START..CROP_X_END window."
            ),
            "command": None,
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
                f"  These frames likely caught a wrong object. Inspect\n"
                f"  verification.png; consider chaos override on outliers."
            ),
            "command": f"chaos verify {stem}",
        })

    # E) peak ω₂ above physical rule-of-thumb
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
                f"  Use chaos override on the worst frame."
            ),
            "command": f"chaos override {stem}",
        })

    # F) PASS — no issues found
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
    rc = subprocess.run(cmd, cwd=REPO_ROOT).returncode
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
                   help="Path to .mov in data/videos/ (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description (e.g. th1_p047_th2_m002).")
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
    rc, _ = run(track_cmd, label="bgr_tracker")
    if rc != 0:
        reason = f"bgr_tracker exit {rc} — unexpected error."
        emit_card(stem, video_path, key, entry,
                  status="FAIL", reasons=[reason],
                  metrics_pre=None, metrics_post=None,
                  n_interpolated=0,
                  hsv_kind=None,
                  total_elapsed=time.time() - t_total)
        return rc

    # ── 2. Verify ──────────────────────────────────────────────────────
    rc, _ = run([sys.executable, VERIFY_SCRIPT, "--stem", stem,
                 "--omega-cap", str(args.omega_cap), "--no-plot"],
                label="verify_tracking")
    if rc != 0:
        emit_card(stem, video_path, key, entry,
                  status="FAIL", reasons=[f"verify_tracking exit {rc}"],
                  metrics_pre=None, metrics_post=None,
                  n_interpolated=0,
                  hsv_kind=None,
                  total_elapsed=time.time() - t_total)
        return rc
    metrics = read_verification_metrics(meas_dir)
    # No interpolation step on the driven pipeline — BGR tracker doesn't
    # produce silent fallback-latch failures, so any suspects left here
    # are real and shouldn't be linearly back-projected away.
    metrics_pre  = metrics
    metrics_post = metrics
    n_interp = 0

    # ── 3. Compute verdict ─────────────────────────────────────────────
    n_susp_post = (metrics_post or {}).get("n_suspect_hidden", 0)
    status, reasons = compute_verdict(metrics_post, n_susp_post)

    # ── 5. Build actionable steps + emit card + maybe mark verified ───
    suspect_frames = _load_top_suspect_frames(meas_dir, n=5)
    actionable_steps = build_actionable_steps(
        stem=stem,
        metrics_post=metrics_post or metrics_pre or {},
        reasons=reasons,
        status=status,
        suspect_frames=suspect_frames,
        entry=entry,
        energy_cap=None,
    )
    emit_card(stem, video_path, key, entry,
              status=status, reasons=reasons,
              metrics_pre=metrics_pre, metrics_post=metrics_post,
              n_interpolated=n_interp,
              hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
              total_elapsed=time.time() - t_total,
              actionable_steps=actionable_steps,
              energy_omega_cap=None)
    maybe_mark_verified(stem, status, reasons)
    return 0 if status != "FAIL" else 1

if __name__ == "__main__":
    sys.exit(main())
