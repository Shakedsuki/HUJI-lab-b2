"""
bulk_track.py
--------------
Run track_one.py over every pending video in one shot, then print a
per-video dropout report.

(Internally each clip goes through track_one, which itself wraps
ring_tracker + verify_tracking + interpolate_suspects + verdict card
emission. So bulk and single-clip runs produce identical artefacts and
the same PASS/WARN/FAIL banding.)

Why this exists
~~~~~~~~~~~~~~~
The interactive flow (run ring_tracker, pick init_frame, pick
release_frame, watch tracking finish, move on to the next video) is
fine for one or two clips but gets tedious when 20+ are pending. Most
pending entries already have `tag_frame` populated by the video tagger,
which is a good proxy for both init_frame and release_frame: it's the
frame where markers were positively identified, so it's a safe place
to start tracking AND a reasonable release point when the user filmed
already-released chaotic motion.

The script:
  1. Scans experiments.json for pending entries (no tracking.csv at the
     measurement folder).
  2. For each entry without init_frame/release_frame, derives both from
     `tag_frame` (init = tag_frame, release = tag_frame). Entries that
     have neither are skipped with a warning — those need the picker.
  3. Backs up experiments.json before mutating it.
  4. Runs `ring_tracker.py <video_path> --force --no-debug` as a
     subprocess for every plannable entry. --no-debug skips the
     360 MB debug video output by default; pass --debug to keep it.
  5. After every run, reads the updated registry to capture
     dropout_rate_pct and other ICs, and writes a JSON sidecar at
     data/bulk_tracking_log.json so subsequent runs can avoid redoing
     work.
  6. Prints a sorted dropout summary at the end with warnings for
     anything > 10% (likely needs HSV recalibration).

Usage
~~~~~
    python scripts/utils/bulk_track.py --dry-run            # show the plan
    python scripts/utils/bulk_track.py                      # do it
    python scripts/utils/bulk_track.py --filter th1_p09     # subset
    python scripts/utils/bulk_track.py --debug              # also write debug.mp4
    python scripts/utils/bulk_track.py --redo               # re-track already tracked
    python scripts/utils/bulk_track.py --jobs 1             # forced sequential (default)

Notes
~~~~~
- Defaults to sequential execution (--jobs 1) because ring_tracker is
  CPU-bound on opencv decoding + matplotlib-free; running multiple
  in parallel just thrashes the disk and saturates cores. The --jobs
  flag is reserved for future use.
- `--no-debug` is the default for bulk runs; pass `--debug` if you
  specifically need the per-frame annotated MP4.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

# UTF-8 stdout for the θ/ω glyphs in the summary.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

TRACKER_SCRIPT   = os.path.join(REPO_ROOT, "scripts", "processing", "ring_tracker.py")
TRACK_ONE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "utils", "track_one.py")
BULK_LOG_FILE    = os.path.join(REPO_ROOT, "data", "bulk_tracking_log.json")

# Pull verdict logic from track_one (in-process) and the rich summary
# renderer from render so the bulk wrap-up uses the same PASS/WARN/FAIL
# bands as a single-clip run.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS
from track_one import compute_verdict, read_verification_metrics  # noqa: E402
from render import render_bulk_summary  # noqa: E402

CONFIG_RE = re.compile(r"^th1_[pm]\d+_th2_[pm]\d+(_r\d+)?$")

# ─────────────────────────────────────────────
# REGISTRY HELPERS
# ─────────────────────────────────────────────

def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_registry(reg):
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)

def backup_registry_once(suffix=None):
    """
    Copy experiments.json to a timestamped backup beside it. Returns
    the backup path. No-op if the same backup already exists.
    """
    if suffix is None:
        suffix = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = EXPERIMENTS_FILE + f".bulk_track_{suffix}.bak"
    if not os.path.exists(bak):
        shutil.copy2(EXPERIMENTS_FILE, bak)
    return bak

def has_tracking_csv(entry):
    md = entry.get("measurements_dir")
    if not md:
        return False
    return os.path.exists(os.path.join(REPO_ROOT, md, "tracking.csv"))

# ─────────────────────────────────────────────
# PLAN
# ─────────────────────────────────────────────

class Plan:
    """One row in the planned bulk run."""
    __slots__ = ("key", "config_description", "video_path",
                 "init_frame", "release_frame", "source",
                 "skip_reason")

    def __init__(self, key, config_description, video_path,
                 init_frame=None, release_frame=None,
                 source="", skip_reason=None):
        self.key                 = key
        self.config_description  = config_description
        self.video_path          = video_path
        self.init_frame          = init_frame
        self.release_frame       = release_frame
        self.source              = source
        self.skip_reason         = skip_reason

    @property
    def runnable(self):
        return (self.skip_reason is None
                and self.init_frame is not None
                and self.release_frame is not None)

def derive_frames(entry):
    """
    Resolve (init_frame, release_frame, source_of_decision) for an
    entry. Returns (None, None, reason) when no resolution is possible.

    Precedence:
      1. Both init_frame and release_frame already populated → use them.
      2. tag_frame populated → use it for both.
      3. Otherwise → unresolvable.
    """
    init    = entry.get("init_frame")
    release = entry.get("release_frame")
    if init is not None and release is not None:
        return int(init), int(release), "registry (init/release)"
    tag = entry.get("tag_frame")
    if tag is not None:
        return int(tag), int(tag), "registry (tag_frame)"
    return None, None, None

def build_plan(reg, *, filter_substr=None, redo=False):
    """
    Walk the registry and produce a list of Plan rows. `redo=True`
    includes already-tracked entries (which would otherwise be skipped).
    """
    plans = []
    for key in sorted(reg.keys()):
        entry = reg[key]
        cd    = entry.get("config_description")
        if not cd:
            continue
        if filter_substr and filter_substr not in cd and filter_substr not in key:
            continue

        video_file = entry.get("video_file")
        if not video_file:
            plans.append(Plan(key, cd, "",
                              skip_reason="no video_file in registry"))
            continue
        video_path = os.path.join(VIDEOS_DIR, video_file)
        if not os.path.exists(video_path):
            plans.append(Plan(key, cd, video_path,
                              skip_reason=f"video missing on disk"))
            continue

        if has_tracking_csv(entry) and not redo:
            plans.append(Plan(key, cd, video_path,
                              skip_reason="already tracked (use --redo)"))
            continue

        init, release, source = derive_frames(entry)
        if init is None:
            plans.append(Plan(key, cd, video_path,
                              skip_reason="no init/release/tag_frame"))
            continue

        plans.append(Plan(key, cd, video_path,
                          init_frame=init,
                          release_frame=release,
                          source=source))
    return plans

# ─────────────────────────────────────────────
# RUN ONE
# ─────────────────────────────────────────────

def prepopulate_frames(reg, plan):
    """Write init_frame / release_frame into the registry entry."""
    e = reg[plan.key]
    e["init_frame"]    = plan.init_frame
    e["release_frame"] = plan.release_frame

def run_one(plan, no_debug=True, force=True):
    """
    Delegate to track_one.py per clip. track_one wraps ring_tracker +
    verify_tracking + interpolate_suspects + verdict-card emission, so
    bulk runs use exactly the same evaluation path as a single
    `chaos.py track <stem>` call. Returns (returncode, elapsed_s).
    """
    cmd = [sys.executable, TRACK_ONE_SCRIPT,
           "--stem", plan.config_description,
           "--yes-to-warn"]   # bulk mode: don't pause on borderline HSV
    if no_debug:
        cmd.append("--no-debug")
    # `force` from the old bulk_track signature was always True; track_one
    # passes --force to ring_tracker internally for non-tracked entries.

    print()
    print("=" * 70)
    print(f"TRACKING {plan.video_path}")
    print(f"  config_description = {plan.config_description}")
    print(f"  init_frame         = {plan.init_frame}  ({plan.source})")
    print(f"  release_frame      = {plan.release_frame}")
    print(f"  cmd                = {' '.join(cmd)}")
    print("=" * 70)

    t0 = time.time()
    rc = subprocess.run(cmd, cwd=REPO_ROOT).returncode
    dt = time.time() - t0
    return rc, dt

# ─────────────────────────────────────────────
# BULK LOG
# ─────────────────────────────────────────────

def load_bulk_log():
    if not os.path.exists(BULK_LOG_FILE):
        return {}
    with open(BULK_LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_bulk_log(log):
    os.makedirs(os.path.dirname(BULK_LOG_FILE), exist_ok=True)
    with open(BULK_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

# ─────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────

def emit_report(rows):
    """
    rows: list of dicts with keys:
        config_description, returncode, elapsed_s,
        dropout_rate_pct, n_free_frames, duration_s,
        theta1_release, theta2_release, energy_proxy.

    Builds a per-clip results list using the same compute_verdict logic
    as a single-clip run (so PASS/WARN/FAIL bands stay in one place),
    then delegates rendering to render.render_bulk_summary.
    """
    if not rows:
        print("\nNothing tracked — nothing to report.")
        return

    results = []
    for r in rows:
        cd = r["config_description"]
        if r["returncode"] != 0:
            # Tracker bailed (HSV ABORT, picker cancel, etc.); no
            # verification.csv to read. Treat as FAIL with no dropout.
            results.append({
                "stem":        cd,
                "status":      "FAIL",
                "dropout_pct": None,
                "elapsed_s":   r["elapsed_s"],
            })
            continue
        meas_dir = os.path.join(MEAS_DIR, cd)
        metrics  = read_verification_metrics(meas_dir)
        if metrics is None:
            results.append({
                "stem":        cd,
                "status":      "FAIL",
                "dropout_pct": r.get("dropout_rate_pct"),
                "elapsed_s":   r["elapsed_s"],
            })
            continue
        n_susp = metrics.get("n_suspect_hidden", 0)
        status, _ = compute_verdict(metrics, n_susp)
        results.append({
            "stem":        cd,
            "status":      status,
            "dropout_pct": metrics.get("free_swing_dropout_pct"),
            "elapsed_s":   r["elapsed_s"],
        })

    print()
    print("=" * 70)
    print(f"BULK TRACKING REPORT — {len(rows)} videos")
    print("=" * 70)
    render_bulk_summary(results)

    # Wall-clock aggregate.
    total_time = sum(r["elapsed_s"] for r in rows)
    print(f"  total wall-clock: {total_time:.0f}s "
          f"({total_time / 60:.1f} min)")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Track every pending video in one shot.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan but don't run anything.")
    p.add_argument("--filter", default=None,
                   help="Substring filter on config_description / "
                        "registry key (e.g. 'th1_p09').")
    p.add_argument("--debug", action="store_true",
                   help="Generate debug.mp4 (default: skip — saves 50–400 MB "
                        "and ~30%% wall clock per clip).")
    p.add_argument("--redo", action="store_true",
                   help="Re-track entries that already have tracking.csv.")
    p.add_argument("--jobs", type=int, default=1,
                   help="Reserved for future parallel execution. "
                        "Currently always 1.")
    return p.parse_args()

def main():
    args = parse_args()

    if not os.path.exists(EXPERIMENTS_FILE):
        print(f"ERROR: registry not found: {EXPERIMENTS_FILE}")
        return 2

    reg   = load_registry()
    plans = build_plan(reg, filter_substr=args.filter, redo=args.redo)

    runnable = [p for p in plans if p.runnable]
    skipped  = [p for p in plans if not p.runnable]

    print(f"Plan: {len(runnable)} videos to track, {len(skipped)} skipped.")
    if args.filter:
        print(f"  filter: '{args.filter}'")
    print()
    print("RUNNABLE:")
    for p in runnable:
        print(f"  [+] {p.config_description:<26}  "
              f"init={p.init_frame:>3}  release={p.release_frame:>3}  "
              f"({p.source})")
    if skipped:
        print()
        print("SKIPPED:")
        for p in skipped:
            print(f"  [-] {p.config_description:<26}  "
                  f"({p.skip_reason})")

    if args.dry_run:
        print()
        print("DRY-RUN — no tracking performed.")
        return 0

    if not runnable:
        print()
        print("Nothing to do.")
        return 0

    # ── Back up registry then pre-populate init/release frames. ─────────
    bak = backup_registry_once()
    print()
    print(f"Registry backed up: {os.path.relpath(bak, REPO_ROOT)}")
    for p in runnable:
        prepopulate_frames(reg, p)
    save_registry(reg)
    print(f"Pre-populated init/release for {len(runnable)} entries.")

    # ── Run tracker per video. ──────────────────────────────────────────
    bulk_log = load_bulk_log()
    rows     = []
    for i, p in enumerate(runnable, start=1):
        print(f"\n[{i}/{len(runnable)}] {p.config_description}")
        rc, elapsed = run_one(p, no_debug=not args.debug, force=True)

        # Re-read registry to capture the tracker's writes.
        reg_after = load_registry()
        e = reg_after.get(p.key, {})
        rows.append({
            "config_description": p.config_description,
            "key":                p.key,
            "returncode":         rc,
            "elapsed_s":          elapsed,
            "dropout_rate_pct":   e.get("dropout_rate_pct"),
            "n_free_frames":     e.get("n_free_frames"),
            "duration_s":        e.get("duration_s"),
            "theta1_release":    e.get("theta1_release"),
            "theta2_release":    e.get("theta2_release"),
            "energy_proxy":      e.get("energy_proxy"),
            "ran_at":            datetime.datetime.now().isoformat(timespec="seconds"),
        })
        bulk_log[p.config_description] = rows[-1]
        save_bulk_log(bulk_log)

    # ── Emit final report. ──────────────────────────────────────────────
    emit_report(rows)
    print(f"\nDetailed log: {os.path.relpath(BULK_LOG_FILE, REPO_ROOT)}")
    return 0 if all(r["returncode"] == 0 for r in rows) else 1

if __name__ == "__main__":
    sys.exit(main())
