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
    """Read measurements/<stem>/verification.csv and return:
        {n_total, n_dropout, dropout_pct}
    Returns None if verification.csv is missing.

    The verdict only cares about dropout — anything else is bloat.
    Peak ω, arm length, suspect counts etc. are no longer computed by
    verify_tracking or read here.
    """
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return None
    n_total = n_drop = 0
    with open(path, "r", newline="") as f:
        for r in csv.DictReader(f):
            n_total += 1
            try:
                if int(r.get("dropout") or 0):
                    n_drop += 1
            except ValueError:
                pass
    return {
        "n_total":     n_total,
        "n_dropout":   n_drop,
        "dropout_pct": round(100.0 * n_drop / n_total, 2) if n_total else None,
    }

# ─────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────

from thresholds import (  # noqa: E402
    DROPOUT_FAIL_PCT,
)

def compute_verdict(metrics, *_unused):
    """
    Returns (status, reasons_list) where status ∈ {PASS, FAIL}.

    A clip FAILs if dropout_pct > DROPOUT_FAIL_PCT, otherwise PASS.
    That's the entire verdict — one criterion, one number.

    Earlier versions of this function also checked peak |ω₂|,
    arm-length deviation, marker swaps, and |Δω| spikes. Those have
    been removed: peak |ω₂| crossings are real chaotic physics not
    tracker errors, |Δω| spikes fire on legitimate chaos, and arm-
    length / swap detections are pre-empted by the Y crop in
    bgr_tracker (which excludes the wall-fabric region where wrong-
    blob detections used to happen). What's left is the only thing
    that genuinely tells you the tracker failed: it didn't find both
    markers often enough.

    Extra positional args are accepted but ignored for back-compat
    with older callers.
    """
    drop = metrics.get("dropout_pct")
    if drop is None:
        return "FAIL", ["no frames in verification.csv"]
    if drop > DROPOUT_FAIL_PCT:
        return "FAIL", [
            f"dropout {drop:.2f}% > {DROPOUT_FAIL_PCT:.0f}% — "
            f"tracker missed markers too often"
        ]
    return "PASS", [f"dropout {drop:.2f}% ≤ {DROPOUT_FAIL_PCT:.0f}%"]

# ─────────────────────────────────────────────
# ACTIONABLE-STEPS BUILDER  (Brief 4)
# ─────────────────────────────────────────────

def build_actionable_steps(stem, metrics_post, reasons, status,
                           *_unused, **_unused_kw):
    """Translate metrics + verdict into copy-paste-ready guidance.

    Verdict is binary based on dropout, so there's really one
    possible step on FAIL ("dropout too high, inspect / re-shoot")
    and a "verified" info row on PASS.
    """
    steps = []
    metrics_post = metrics_post or {}

    drop = metrics_post.get("dropout_pct")
    n_drop = metrics_post.get("n_dropout", "?")
    if drop is not None and drop > DROPOUT_FAIL_PCT:
        steps.append({
            "priority": "required",
            "category": "dropout",
            "text": (
                f"{drop:.2f}% dropout ({n_drop} frames) > "
                f"{DROPOUT_FAIL_PCT:.0f}% — tracker missing markers too\n"
                f"  often. Use scripts/utils/diagnose_frames.py to see\n"
                f"  what's happening on a sample of dropout frames;\n"
                f"  may need re-shoot or crop adjustment."
            ),
            "command": f"python scripts/utils/diagnose_frames.py --stem {stem}",
        })

    if status == "PASS" and not steps:
        steps.append({
            "priority": "info",
            "category": "verified",
            "text": ("Dropout within tolerance; tracking_quality set to "
                     "'verified'."),
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
    status, reasons = compute_verdict(metrics_post)

    # ── 4. Build actionable steps + emit card + maybe mark verified ───
    actionable_steps = build_actionable_steps(
        stem=stem,
        metrics_post=metrics_post or metrics_pre or {},
        reasons=reasons,
        status=status,
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
