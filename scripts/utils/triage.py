"""
triage.py
---------
Walk through non-PASS clips and dispatch the right repair tool per
clip. Each clip falls into one of three primary buckets:

  override — single-frame ω₂ teleport: peak |ω₂| above the absurd line
             (4000 °/s) means one frame jumped to a wrong object.
             Auto-find the worst frame, run chaos override on that
             row, re-verify. Surgical, no re-track.
  fix      — arm-length violations or ω-cap survivors: launch
             chaos fix (interactive seed picker + re-track with
             strict-physics).
  tune     — free-swing dropout in the 5%+ band: re-tune HSV then
             re-track.

A fourth bucket "review" surfaces clips where the only flag is
borderline (e.g. rolling energy spike on otherwise-clean tracking,
pivot drift from a session-specific camera offset). These need
human judgement — triage prints the diagnosis and lets the user
decide (mark verified / accept WARN / skip / quit).

Usage:
    chaos triage             — process clips one at a time, prompting
                               for confirmation per dispatch
    chaos triage --auto      — auto-apply override-bucket fixes; still
                               prompts for fix/tune/review buckets
    chaos triage --filter <substr>
                             — only consider clips whose stem matches
"""

import argparse
import csv
import datetime
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

CHAOS_PY         = os.path.join(REPO_ROOT, "chaos.py")

EXPERIMENTS_FILE = EXPERIMENTS
from track_one import (              # noqa: E402
    read_verification_metrics, compute_verdict,
)
from thresholds import (              # noqa: E402
    PEAK_OMEGA_ABSURD, PEAK_OMEGA_PHYSICAL,
    WARN_DROPOUT_PCT, PASS_DROPOUT_PCT,
)

# ─────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────

def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def has_csv(entry, stem):
    md = entry.get("measurements_dir") or f"measurements/{stem}"
    return os.path.exists(os.path.join(REPO_ROOT, md, "tracking.csv"))

# ─────────────────────────────────────────────
# CLASSIFIER
# ─────────────────────────────────────────────

# Higher priority = process this clip first when triaging the queue.
# Surgical wins (override) come first because each one is ~2 min and
# tends to flip a FAIL straight to PASS or WARN. Interactive fix
# (chaos fix) is medium effort. HSV re-tune (chaos tune) is heaviest.
PRIORITY = {
    "override":      100,
    "fix-omega-cap":  80,
    "fix-arm":        70,
    "tune-fail":      60,   # dropout > 10%
    "tune-warn":      50,   # dropout 5-10%
    "review":         30,
    "special":        20,
}

def classify_issue(metrics, reasons):
    """
    Decide which repair bucket this clip falls into based on its
    verdict metrics. Returns (bucket, priority, primary_reason).
    """
    peak2  = metrics.get("peak_omega2", 0.0) or 0.0
    drop   = metrics.get("free_swing_dropout_pct") or 0.0
    n_arm  = metrics.get("n_arm_violations", 0) or 0
    n_om   = metrics.get("n_omega_cap_suspects", 0) or 0
    n_ceil = metrics.get("n_energy_ceiling_suspects", 0) or 0
    n_roll = metrics.get("n_energy_rolling_spikes", 0) or 0
    n_trend = metrics.get("n_trend_arm_suspects", 0) or 0
    drift  = metrics.get("pivot_drift_px") or 0.0

    # Override is ONLY valid when peak |ω₂| is absurd AND only a small
    # number of frames are flagged. Many ω-cap or trend-arm suspects
    # indicate a sustained wrong-target latch — overriding the worst
    # frame just shifts the peak to the second-worst, ad infinitum.
    # That's a re-tune problem, not an override problem.
    if peak2 > PEAK_OMEGA_ABSURD:
        if n_om <= 5 and n_trend == 0:
            return ("override", PRIORITY["override"],
                    f"peak |ω₂| = {peak2:.0f} °/s — single-frame teleport "
                    f"({n_om} ω-cap suspects)")
        return ("tune-fail", PRIORITY["tune-fail"],
                f"peak |ω₂| = {peak2:.0f} °/s with {n_om} ω-cap + "
                f"{n_trend} trend-arm suspects — sustained "
                f"wrong-target latch, not a single frame")

    # Tune: dropout band. >10% is FAIL, 5-10% is WARN.
    if drop > WARN_DROPOUT_PCT:
        return ("tune-fail", PRIORITY["tune-fail"],
                f"dropout {drop:.1f}% > {WARN_DROPOUT_PCT:.0f}% — HSV recalibration")
    if drop > PASS_DROPOUT_PCT:
        return ("tune-warn", PRIORITY["tune-warn"],
                f"dropout {drop:.1f}% in {PASS_DROPOUT_PCT:.0f}-{WARN_DROPOUT_PCT:.0f}% band — HSV refinement")

    # Fix: ω-cap survivors mean interpolation couldn't repair real
    # tracking errors. Higher priority than arm-length-only because
    # they are direct evidence that the marker position was wrong.
    if n_om > 0:
        return ("fix-omega-cap", PRIORITY["fix-omega-cap"],
                f"{n_om} ω-cap suspect(s) survived interpolation")

    # Fix: arm-length violations — wrong-target frames the rigid-rod
    # check caught. Threshold of 5 keeps a stray noise frame from
    # routing the clip to interactive fix.
    if n_arm >= 5:
        dev = metrics.get("arm_length_dev_max_pct") or 0.0
        return ("fix-arm", PRIORITY["fix-arm"],
                f"{n_arm} arm-length violation(s) (max {dev:.1f}%)")

    # Review: ω₂ between physical RoT and absurd; might be real
    # chaotic dynamics, might be a 2nd-tier latch. Visual check.
    if peak2 > PEAK_OMEGA_PHYSICAL:
        return ("review", PRIORITY["review"],
                f"peak |ω₂| = {peak2:.0f} °/s above physical RoT")

    # Energy-ceiling suspects without ω-cap or arm-length issues are
    # usually transient ω-noise events. Energy spikes specifically.
    if n_ceil > 0 or n_roll > 0:
        return ("review", PRIORITY["review"],
                f"{n_ceil} energy-ceiling + {n_roll} rolling-spike — borderline")

    # Pivot drift on otherwise-clean tracking → session-specific
    # camera offset, not a tracker error.
    if drift >= 5:
        return ("special", PRIORITY["special"],
                f"pivot drift {drift:.1f} px on clean tracking — likely camera offset")

    # Small-count arm violations / catch-all — borderline.
    if n_arm > 0:
        dev = metrics.get("arm_length_dev_max_pct") or 0.0
        return ("review", PRIORITY["review"],
                f"{n_arm} arm-length violation(s) (max {dev:.1f}%) — small count")

    return ("review", PRIORITY["review"], "unknown reason — visual inspection needed")

# ─────────────────────────────────────────────
# WORST-FRAME FINDER (for override dispatch)
# ─────────────────────────────────────────────

def find_worst_omega_frame(meas_dir):
    """
    Read verification.csv for this clip and return (frame_no, om2)
    for the suspect frame with the largest |ω₂|. Returns None if
    no suspect frames exist or the file is missing.
    """
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return None
    best = (None, -1.0)
    try:
        with open(path, "r", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    if int(r.get("suspect") or 0) != 1:
                        continue
                    if int(r.get("dropout") or 0) != 0:
                        continue
                    om2 = abs(float(r.get("omega2_deg_s") or 0))
                except (ValueError, TypeError):
                    continue
                if om2 > best[1]:
                    best = (int(r["frame"]), om2)
    except (OSError, csv.Error):
        return None
    if best[0] is None:
        return None
    return best

# ─────────────────────────────────────────────
# QUEUE
# ─────────────────────────────────────────────

def build_queue(reg, *, filter_substr=None, skip_stems=None):
    """
    Returns a list of (priority, stem, key, entry, metrics, status,
    reasons, bucket, primary) for clips that need attention.
    Sorted highest-priority first.
    """
    skip_stems = skip_stems or set()
    rows = []
    for key, entry in reg.items():
        stem = entry.get("config_description") or key
        if stem in skip_stems:
            continue
        if filter_substr and filter_substr not in stem:
            continue
        if entry.get("tracking_quality") == "verified":
            # Already verified — re-evaluate against current logic.
            md = os.path.join(REPO_ROOT, entry.get("measurements_dir")
                              or f"measurements/{stem}")
            if not os.path.exists(os.path.join(md, "tracking.csv")):
                continue
            metrics = read_verification_metrics(md)
            if metrics is None:
                continue
            status, reasons = compute_verdict(
                metrics, metrics.get("n_suspect_hidden", 0))
            if status == "PASS":
                continue   # really still PASS, skip
            # Verified-in-registry but no longer PASS — surface.
        else:
            if not has_csv(entry, stem):
                continue
            md = os.path.join(REPO_ROOT, entry.get("measurements_dir")
                              or f"measurements/{stem}")
            metrics = read_verification_metrics(md)
            if metrics is None:
                continue
            status, reasons = compute_verdict(
                metrics, metrics.get("n_suspect_hidden", 0))
            if status == "PASS":
                continue

        bucket, priority, primary = classify_issue(metrics, reasons)
        rows.append((priority, stem, key, entry, metrics, status,
                     reasons, bucket, primary))

    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows

# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

_STATUS_BADGE = {
    "PASS": "\033[1;32mPASS\033[0m",
    "WARN": "\033[1;33mWARN\033[0m",
    "FAIL": "\033[1;31mFAIL\033[0m",
}

_BUCKET_LABEL = {
    "override":      "OVERRIDE  (chaos override --frame N)",
    "fix-arm":       "FIX       (chaos fix — arm-length seeds)",
    "fix-omega-cap": "FIX       (chaos fix — ω-cap survivors)",
    "tune-fail":     "TUNE+TRACK (chaos tune + chaos track — heavy dropout)",
    "tune-warn":     "TUNE+TRACK (chaos tune + chaos track — borderline dropout)",
    "review":        "REVIEW     (manual decision)",
    "special":       "SPECIAL    (manual investigation)",
}

def print_clip_diagnosis(idx, total, stem, status, metrics,
                         reasons, bucket, primary):
    print()
    print("─" * 78)
    print(f"[{idx}/{total}]  {stem}   "
          f"status: {_STATUS_BADGE.get(status, status)}")
    print("─" * 78)
    print(f"  primary issue   : {primary}")
    print(f"  recommended     : {_BUCKET_LABEL.get(bucket, bucket)}")
    drop = metrics.get("free_swing_dropout_pct") or 0.0
    peak2 = metrics.get("peak_omega2", 0.0) or 0.0
    print(f"  dropout         : {drop:.2f}%   peak |ω₂|: {peak2:.0f} °/s")
    if reasons:
        print(f"  all reasons     :")
        for r in reasons[:6]:
            print(f"    • {r}")
        if len(reasons) > 6:
            print(f"    • … and {len(reasons) - 6} more")

# ─────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────

def _run_chaos(*subcmd):
    """Spawn `python chaos.py <subcmd>` so output goes to the user's
    terminal. Inherits stdin/stdout/stderr so interactive picker
    windows work as expected."""
    cmd = [sys.executable, CHAOS_PY, *subcmd]
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode

def dispatch_override(stem, metrics):
    """Find the worst |ω₂| suspect frame and run chaos override on
    that row. Returns the frame chosen or None if nothing to do."""
    md = os.path.join(MEAS_DIR, stem)
    found = find_worst_omega_frame(md)
    if not found:
        print(f"  (no suspect frame found in verification.csv — "
              f"override not applicable)")
        return None
    frame_no, om2 = found
    print(f"  → worst suspect frame: {frame_no}  "
          f"(|ω₂| = {om2:.0f} °/s)")
    rc = _run_chaos("override", stem, "--frame", str(frame_no))
    if rc != 0:
        print(f"  chaos override exited rc={rc}")
    return frame_no

def dispatch_fix(stem):
    """Run chaos fix interactively. The picker handles its own UI."""
    rc = _run_chaos("fix", stem)
    if rc != 0:
        print(f"  chaos fix exited rc={rc}")
    return rc

def dispatch_tune_track(stem):
    """Run chaos tune (interactive) followed by chaos track."""
    rc = _run_chaos("tune", stem)
    if rc != 0:
        print(f"  chaos tune exited rc={rc} — skipping track step")
        return rc
    rc = _run_chaos("track", stem)
    if rc != 0:
        print(f"  chaos track exited rc={rc}")
    return rc

def dispatch_review(stem, status, metrics, reasons):
    """For borderline / special cases, just open the verification.png
    path so the user can inspect, then ask what to do."""
    png = os.path.join(MEAS_DIR, stem, "verification.png")
    if os.path.exists(png):
        print(f"  inspect: {png}")
    print(f"  current status: {status}")
    print(f"  reasons:")
    for r in reasons:
        print(f"    • {r}")
    print(f"  options:")
    print(f"    [v] mark this clip verified anyway (visually clean)")
    print(f"    [w] accept WARN (note added to registry)")
    print(f"    [s] skip for now")
    print(f"    [q] quit triage loop")
    while True:
        ans = input("  > ").strip().lower()
        if ans in ("v", "w", "s", "q"):
            return ans
        print("  please answer v / w / s / q")

def mark_verified_manual(stem, reasons):
    reg = load_registry()
    for k, e in reg.items():
        cd = e.get("config_description") or k
        if cd == stem:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            e["tracking_quality"]              = "verified"
            e["verification_date"]             = today
            e["verification_notes"]            = (
                f"Manually accepted via chaos triage on {today} "
                f"(visually clean despite: {'; '.join(reasons)})")
            e["verified_under_brief_version"]  = 14
            e["audit_old_status"]              = e.get("tracking_quality", "review")
            e["audit_new_status"]              = "PASS"
            # Persist the [v] decision so future audits don't trample it.
            # See project_audit_overwrites_manual_accept.md memo.
            e["manual_accept"]                 = True
            e["manual_accept_date"]            = today
            e["manual_accept_brief_version"]   = 14
            e["manual_accept_reasons"]         = reasons
            with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=2)
            return True
    return False

def annotate_warn(stem, reasons):
    reg = load_registry()
    for k, e in reg.items():
        cd = e.get("config_description") or k
        if cd == stem:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            e["tracking_quality"]   = "review"
            e["verification_notes"] = (
                f"WARN accepted via chaos triage on {today}: "
                f"{'; '.join(reasons)}")
            with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(reg, f, indent=2)
            return True
    return False

# ─────────────────────────────────────────────
# CONFIRM PROMPT
# ─────────────────────────────────────────────

def confirm_dispatch(bucket, *, auto=False):
    """Returns 'apply' / 'skip' / 'quit'.

    With --auto, override-bucket clips don't prompt — they just run.
    Other buckets always prompt because they require user attention.
    """
    if auto and bucket == "override":
        print("  (auto-mode: applying override without prompt)")
        return "apply"
    print(f"  apply this fix?  [y] yes   [v] mark verified anyway   "
          f"[n] skip   [q] quit")
    while True:
        ans = input("  > ").strip().lower()
        if ans in ("y", "yes"):
            return "apply"
        if ans in ("v", "verify", "verified"):
            return "verify"
        if ans in ("n", "no", "skip", "s"):
            return "skip"
        if ans in ("q", "quit"):
            return "quit"
        print("  please answer y / v / n / q")

# ─────────────────────────────────────────────
# RE-VERIFY
# ─────────────────────────────────────────────

def reverify_and_status(stem):
    """Run verify_tracking and return (status, reasons, metrics)."""
    rc = _run_chaos("verify", stem)
    md = os.path.join(MEAS_DIR, stem)
    metrics = read_verification_metrics(md)
    if metrics is None:
        return "ERROR", [f"verify exited rc={rc}, no metrics"], None
    status, reasons = compute_verdict(
        metrics, metrics.get("n_suspect_hidden", 0))
    return status, reasons, metrics

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Walk through non-PASS clips and dispatch the "
                    "right repair tool per clip.")
    p.add_argument("--auto", action="store_true",
                   help="auto-apply override-bucket fixes; still "
                        "prompts for fix/tune/review")
    p.add_argument("--filter", metavar="SUBSTR",
                   help="only consider clips whose stem matches")
    p.add_argument("--once", action="store_true",
                   help="dispatch a single clip and exit "
                        "(default: loop until queue empty or user quits)")
    return p.parse_args()

def main():
    args = parse_args()
    skipped = set()

    print("chaos triage")
    print("Walks the queue of non-PASS clips. Dispatches the right "
          "repair tool per clip.")
    print()

    while True:
        reg = load_registry()
        queue = build_queue(reg, filter_substr=args.filter,
                            skip_stems=skipped)
        if not queue:
            if skipped:
                print(f"\n  Queue empty (skipped {len(skipped)} this "
                      f"session). Run again with the skip set cleared "
                      f"to revisit them.")
            else:
                print("\n  Queue empty — nothing left to fix.")
            break

        # Take the highest-priority candidate.
        (_, stem, key, entry, metrics, status,
         reasons, bucket, primary) = queue[0]
        print_clip_diagnosis(
            len(skipped) + 1, len(queue) + len(skipped),
            stem, status, metrics, reasons, bucket, primary)

        # REVIEW + SPECIAL go through their own multi-choice prompt.
        if bucket in ("review", "special"):
            choice = dispatch_review(stem, status, metrics, reasons)
            if choice == "q":
                break
            if choice == "s":
                skipped.add(stem)
                if args.once: break
                continue
            if choice == "v":
                if mark_verified_manual(stem, reasons):
                    print(f"  marked verified.")
                skipped.add(stem)
                if args.once: break
                continue
            if choice == "w":
                if annotate_warn(stem, reasons):
                    print(f"  annotated WARN in registry.")
                skipped.add(stem)
                if args.once: break
                continue

        # OVERRIDE / FIX / TUNE — confirm then dispatch.
        action = confirm_dispatch(bucket, auto=args.auto)
        if action == "quit":
            break
        if action == "skip":
            skipped.add(stem)
            if args.once: break
            continue
        if action == "verify":
            # Force-mark this clip as verified despite the WARN.
            # Useful when the user has visually confirmed the tracking
            # is sound and the physics-check flags are noise rather
            # than real tracker errors.
            if mark_verified_manual(stem, reasons):
                print(f"  marked verified.")
            skipped.add(stem)
            if args.once: break
            continue

        if bucket == "override":
            dispatch_override(stem, metrics)
        elif bucket in ("fix-arm", "fix-omega-cap"):
            dispatch_fix(stem)
        elif bucket in ("tune-fail", "tune-warn"):
            dispatch_tune_track(stem)

        # Re-verify and report new state. chaos override / fix / track
        # already ran verify internally, but we want compute_verdict
        # in this process to confirm.
        new_status, new_reasons, new_metrics = reverify_and_status(stem)
        if new_status == "PASS":
            print(f"\n  ✓ {stem} now PASS")
        else:
            print(f"\n  → {stem} now {new_status}")
            if new_reasons:
                print(f"    primary: {new_reasons[0]}")

        # Always advance — if the clip is still non-PASS, the user
        # decides next iteration whether to fix again.
        skipped.add(stem)
        if args.once:
            break

    return 0

if __name__ == "__main__":
    sys.exit(main())
