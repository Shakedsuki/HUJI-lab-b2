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
    Read measurements/<stem>/verification.csv and return a dict:
      n_total, n_dropout, n_suspect_hidden,
      peak_omega1, peak_omega2,
      free_swing_dropout_pct, holding_dropout_pct.
    Returns None if verification.csv is missing.
    """
    path = os.path.join(meas_dir, "verification.csv")
    if not os.path.exists(path):
        return None
    n_total = n_drop_total = n_suspect_hidden = 0
    n_free = n_free_drop = n_hold = n_hold_drop = 0
    peak_o1 = peak_o2 = 0.0
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
    return {
        "n_total":               n_total,
        "n_dropout_total":       n_drop_total,
        "n_dropout_holding":     n_hold_drop,
        "n_dropout_free_swing":  n_free_drop,
        "n_holding":             n_hold,
        "n_free_swing":          n_free,
        "n_suspect_hidden":      n_suspect_hidden,
        "peak_omega1":           peak_o1,
        "peak_omega2":           peak_o2,
        "free_swing_dropout_pct":
            round(100.0 * n_free_drop / n_free, 2) if n_free else None,
        "holding_dropout_pct":
            round(100.0 * n_hold_drop / n_hold, 2) if n_hold else None,
    }


# ─────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────

# Thresholds for the PASS/WARN/FAIL bucket. Free-swing dropout is the
# headline number the user actually cares about — holding-phase dropouts
# are uninteresting (the pendulum hasn't moved yet). Hidden suspects are
# only counted post-interpolation; the pre-interp count is informational.
PASS_DROPOUT_PCT     = 5.0
WARN_DROPOUT_PCT     = 10.0
PEAK_OMEGA_PHYSICAL  = 1500.0   # rule-of-thumb max ω for arm 2 chaos
PEAK_OMEGA_ABSURD    = 4000.0   # above this it's almost surely tracking error


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

    if reasons:
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
              n_interpolated, hsv_kind, total_elapsed):
    """Print and append the one-page verdict card."""
    flag = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
    drop = (metrics_post.get("free_swing_dropout_pct")
            if metrics_post else None)
    drop_str = f"{drop:.2f}%" if drop is not None else "—"
    n_susp_pre  = (metrics_pre or {}).get("n_suspect_hidden", 0)
    n_susp_post = (metrics_post or {}).get("n_suspect_hidden", 0)
    peak1 = (metrics_post or {}).get("peak_omega1", 0.0)
    peak2 = (metrics_post or {}).get("peak_omega2", 0.0)
    n_free  = (metrics_post or {}).get("n_free_swing", "—")
    n_drop_free = (metrics_post or {}).get("n_dropout_free_swing", "—")
    n_drop_hold = (metrics_post or {}).get("n_dropout_holding", "—")

    lines = []
    lines.append("=" * 70)
    lines.append(f"VERDICT  {flag}  {stem}")
    lines.append("=" * 70)
    lines.append(f"  video         : {os.path.basename(video_path)}")
    lines.append(f"  registry key  : {key}")
    lines.append(f"  HSV used      : {hsv_kind}")
    lines.append(f"  init/release  : {entry.get('init_frame')} / "
                 f"{entry.get('release_frame')}")
    lines.append(f"  free frames   : {n_free}")
    lines.append(f"  dropout       : {drop_str}  "
                 f"({n_drop_free} in free_swing, {n_drop_hold} in holding)")
    lines.append(f"  suspects (pre): {n_susp_pre}")
    if n_interpolated > 0:
        lines.append(f"  interpolated  : {n_interpolated}")
        lines.append(f"  suspects (post): {n_susp_post}")
    lines.append(f"  peak |ω₁|     : {peak1:>5.0f} °/s")
    lines.append(f"  peak |ω₂|     : {peak2:>5.0f} °/s "
                 f"(physical RoT ≤ {PEAK_OMEGA_PHYSICAL:.0f})")
    lines.append(f"  reasons       : " + ("; ".join(reasons) if reasons else "—"))
    lines.append(f"  total elapsed : {total_elapsed:.0f}s")
    lines.append("")
    if status == "FAIL":
        lines.append("  next step: inspect debug.mp4 (or re-run with --debug); "
                     "consider hsv_tuner re-calibration or a different release frame.")
    elif status == "WARN":
        lines.append("  next step: review verification.png; if acceptable, "
                     "set tracking_quality=verified manually.")
    else:
        lines.append("  next step: tracking_quality auto-set to 'verified' "
                     "in the registry. On to the next clip.")
    lines.append("=" * 70)

    text = "\n".join(lines)
    print()
    print(text)

    # Append to log.
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
        emit_card(stem, video_path, key, entry,
                  status="FAIL", reasons=[f"ring_tracker exit {rc}"],
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
