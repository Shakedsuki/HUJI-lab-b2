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
    if n_suspects_post_interp > 0:
        reasons.append(
            f"{n_suspects_post_interp} residual suspects post-interpolation")
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

    if reasons:
        # Severe holding-phase noise upgrades a would-be PASS to WARN.
        return "WARN", reasons
    return "PASS", ["dropout, suspects, and ω all within thresholds"]


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
              actionable_steps=None):
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

    # ── 5. Emit card + maybe mark verified ─────────────────────────────
    emit_card(stem, video_path, key, entry,
              status=status, reasons=reasons,
              metrics_pre=metrics_pre, metrics_post=metrics_post,
              n_interpolated=n_interp,
              hsv_kind=hsv_kind_for_video(os.path.basename(video_path)),
              total_elapsed=time.time() - t_total)
    maybe_mark_verified(stem, status, reasons)
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
