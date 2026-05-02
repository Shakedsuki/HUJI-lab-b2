"""
chaos.py — unified entry point for the double-pendulum tracking pipeline.

Run as `chaos <subcommand>` (via the chaos / chaos.bat wrappers) or as
`python chaos.py <subcommand>`. All paths assumed relative to this file.

Subcommands
~~~~~~~~~~~
  status            list tracked vs pending; one-line summary
  report            regenerate data/status_report.xlsx
  roadmap           regenerate docs/tracking_roadmap.md (per-clip dropout/quality table)
  hsv-probe         probe every existing HSV file vs every HSV-ABORT clip
  audit             re-validate verified clips against current verdict logic
  tune <stem>       launch hsv_tuner.py on a clip's video
  track <stem>      standard track + verify + interpolate + verdict
  fix <stem>        interactive manual-seed correction + re-track
  verify <stem>     standalone QA on an existing tracking.csv
  bulk              sequential bulk pass over plannable pending clips
  next              interactive god-mode — drive pending queue end-to-end
  help              print this cheat sheet

Examples
~~~~~~~~
  chaos status
  chaos track th1_p047_th2_m002
  chaos fix th1_p047_th2_m002
  chaos next                   # processes one pending clip after another

Underlying scripts (still callable directly for power-users):
  scripts/processing/hsv_tuner.py
  scripts/processing/ring_tracker.py
  scripts/processing/verify_tracking.py
  scripts/processing/interpolate_suspects.py
  scripts/utils/track_one.py
  scripts/utils/manual_correction.py
  scripts/utils/bulk_track.py
  scripts/utils/video_status.py
  scripts/utils/generate_status_report.py
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR  = os.path.join(ROOT, "Videos")
MEAS_DIR    = os.path.join(ROOT, "measurements")
DATA_DIR    = os.path.join(ROOT, "data")
EXPERIMENTS = os.path.join(DATA_DIR, "experiments.json")

SCRIPT_HSV_TUNER  = os.path.join(ROOT, "scripts", "processing", "hsv_tuner.py")
SCRIPT_RING       = os.path.join(ROOT, "scripts", "processing", "ring_tracker.py")
SCRIPT_VERIFY     = os.path.join(ROOT, "scripts", "processing", "verify_tracking.py")
SCRIPT_INTERP     = os.path.join(ROOT, "scripts", "processing", "interpolate_suspects.py")
SCRIPT_TRACK_ONE  = os.path.join(ROOT, "scripts", "utils", "track_one.py")
SCRIPT_MANUAL     = os.path.join(ROOT, "scripts", "utils", "manual_correction.py")
SCRIPT_OVERRIDE   = os.path.join(ROOT, "scripts", "utils", "override_frame.py")
SCRIPT_BULK       = os.path.join(ROOT, "scripts", "utils", "bulk_track.py")
SCRIPT_STATUS     = os.path.join(ROOT, "scripts", "utils", "video_status.py")
SCRIPT_REPORT     = os.path.join(ROOT, "scripts", "utils", "generate_status_report.py")
SCRIPT_ROADMAP    = os.path.join(ROOT, "scripts", "utils", "generate_roadmap.py")
SCRIPT_HSV_PROBE  = os.path.join(ROOT, "scripts", "utils", "hsv_probe_matrix.py")
SCRIPT_AUDIT      = os.path.join(ROOT, "scripts", "utils", "audit.py")
SCRIPT_TRIAGE     = os.path.join(ROOT, "scripts", "utils", "triage.py")

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v"}


# ─────────────────────────────────────────────
# REGISTRY HELPERS
# ─────────────────────────────────────────────

def load_registry():
    if not os.path.exists(EXPERIMENTS):
        return {}
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def find_entry_by_stem(reg, stem):
    """Return (key, entry) for the row with config_description == stem,
    or the row keyed by `stem` directly. Returns (None, None) on miss."""
    for k, e in reg.items():
        if e.get("config_description") == stem:
            return k, e
    if stem in reg:
        return stem, reg[stem]
    return None, None


def is_tracked(entry):
    if not entry: return False
    if entry.get("release_frame") is None: return False
    if entry.get("theta1_release") is None: return False
    md = entry.get("measurements_dir")
    if not md: return False
    csv_basename = entry.get("csv_file") or "tracking.csv"
    return os.path.exists(os.path.join(ROOT, md, csv_basename))


def list_pending_videos():
    """Return list of video filenames in Videos/ that aren't tracked yet."""
    reg = load_registry()
    if not os.path.isdir(VIDEOS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(VIDEOS_DIR), key=str.lower):
        full = os.path.join(VIDEOS_DIR, name)
        if not os.path.isfile(full):
            continue
        if Path(name).suffix.lower() not in VIDEO_EXTS:
            continue
        stem = Path(name).stem
        # Match against either registry key or config_description.
        key, entry = find_entry_by_stem(reg, stem)
        if entry and is_tracked(entry):
            continue
        out.append(name)
    return out


def stem_for_video(video_filename):
    """Resolve config_description for a video filename via the registry,
    falling back to the bare stem if no entry exists yet."""
    reg = load_registry()
    for k, e in reg.items():
        if e.get("video_file") == video_filename:
            cd = e.get("config_description")
            if cd:
                return cd
    return Path(video_filename).stem


def hsv_kind_for_stem(stem):
    """Return 'per-video' if data/hsv_<stem>.json exists, else 'global'."""
    if os.path.exists(os.path.join(DATA_DIR, f"hsv_{stem}.json")):
        return "per-video"
    return "global"


# ─────────────────────────────────────────────
# SUBCOMMAND DISPATCH
# ─────────────────────────────────────────────

def run_script(script_path, *args, check=False):
    """Invoke a Python script as a subprocess; output streams live."""
    cmd = [sys.executable, script_path, *map(str, args)]
    return subprocess.run(cmd, cwd=ROOT, check=check).returncode


def cmd_status(args):
    return run_script(SCRIPT_STATUS)


def cmd_report(args):
    extra = []
    if args.output:
        extra = ["--output", args.output]
    return run_script(SCRIPT_REPORT, *extra)


def cmd_tune(args):
    video = resolve_video_path_for_stem(args.stem)
    if not video:
        return 1
    return run_script(SCRIPT_HSV_TUNER, video)


def cmd_track(args):
    extra = ["--stem", args.stem]
    if args.skip_probe:
        extra.append("--skip-probe")
    if args.yes_to_warn:
        extra.append("--yes-to-warn")
    if args.debug:
        extra.append("--debug")
    if args.omega_cap is not None:
        extra += ["--omega-cap", str(args.omega_cap)]
    return run_script(SCRIPT_TRACK_ONE, *extra)


def cmd_fix(args):
    extra = ["--stem", args.stem]
    if args.save_only:
        extra.append("--save-only")
    if args.omega_cap is not None:
        extra += ["--omega-cap", str(args.omega_cap)]
    return run_script(SCRIPT_MANUAL, *extra)


def cmd_override(args):
    extra = ["--stem", args.stem, "--frame", str(args.frame)]
    if args.no_verify:
        extra.append("--no-verify")
    if args.omega_cap is not None:
        extra += ["--omega-cap", str(args.omega_cap)]
    return run_script(SCRIPT_OVERRIDE, *extra)


def cmd_verify(args):
    extra = ["--stem", args.stem]
    if args.omega_cap is not None:
        extra += ["--omega-cap", str(args.omega_cap)]
    if args.no_plot:
        extra.append("--no-plot")
    # Brief 5+6 — pass through threshold overrides when set.
    for attr, flag in (
        ("delta_omega_cap",   "--delta-omega-cap"),
        ("theta_residual_cap", "--theta-residual-cap"),
        ("energy_spike_factor", "--energy-spike-factor"),
        ("energy_headroom",   "--energy-headroom"),
        ("arm_len_threshold", "--arm-len-threshold"),
        ("arm_trend_window",  "--arm-trend-window"),
        ("arm_trend_dev",     "--arm-trend-dev"),
    ):
        v = getattr(args, attr, None)
        if v is not None:
            extra += [flag, str(v)]
    return run_script(SCRIPT_VERIFY, *extra)


def cmd_bulk(args):
    extra = []
    if args.dry_run: extra.append("--dry-run")
    if args.filter:  extra += ["--filter", args.filter]
    if args.debug:   extra.append("--debug")
    if args.redo:    extra.append("--redo")
    return run_script(SCRIPT_BULK, *extra)


def cmd_roadmap(args):
    extra = []
    if args.output: extra += ["--output", args.output]
    if args.dry_run: extra.append("--dry-run")
    return run_script(SCRIPT_ROADMAP, *extra)


def cmd_hsv_probe(args):
    extra = []
    if args.filter:    extra += ["--filter", args.filter]
    if args.apply:     extra.append("--apply")
    if args.warn_also: extra.append("--warn-also")
    return run_script(SCRIPT_HSV_PROBE, *extra)


def cmd_audit(args):
    extra = []
    if args.apply:         extra.append("--apply")
    if args.upgrade:       extra.append("--upgrade")
    if args.filter:        extra += ["--filter", args.filter]
    if args.skip_reverify: extra.append("--skip-reverify")
    if args.omega_cap is not None:
        extra += ["--omega-cap", str(args.omega_cap)]
    return run_script(SCRIPT_AUDIT, *extra)


def cmd_triage(args):
    extra = []
    if args.auto:   extra.append("--auto")
    if args.once:   extra.append("--once")
    if args.filter: extra += ["--filter", args.filter]
    return run_script(SCRIPT_TRIAGE, *extra)


def resolve_video_path_for_stem(stem):
    """Look up Videos/<video_file> for a config_description via registry."""
    reg = load_registry()
    _, entry = find_entry_by_stem(reg, stem)
    if not entry or not entry.get("video_file"):
        print(f"ERROR: no registry entry for stem '{stem}'.", file=sys.stderr)
        return None
    p = os.path.join(VIDEOS_DIR, entry["video_file"])
    if not os.path.exists(p):
        print(f"ERROR: video missing on disk: {p}", file=sys.stderr)
        return None
    return p


_HELP_CHEAT_SHEET = r"""
chaos — unified entry point for the double-pendulum tracking pipeline

USAGE
  chaos <command> [args]                      # PowerShell: .\chaos <command>

PIPELINE COMMANDS  (per clip, in typical order)
  chaos tune <stem>          calibrate per-video HSV (interactive eyedropper)
  chaos track <stem>         track + verify + interpolate + verdict
  chaos fix <stem>           interactive manual-seed fix-up + re-track
                             (forward-propagating; for cascading errors)
  chaos override <stem>      surgical single-row CSV edit (no re-track)
        --frame N            (frame-local; for one isolated bad frame)
  chaos verify <stem>        standalone QA on an existing tracking.csv
                             flags: --delta-omega-cap, --theta-residual-cap,
                                    --energy-spike-factor, --energy-headroom,
                                    --arm-len-threshold, --arm-trend-window,
                                    --arm-trend-dev

BATCH / DRIVER COMMANDS
  chaos next                 god-mode loop — drive pending queue end-to-end
  chaos next --stem <stem>   same loop but only one clip
  chaos bulk                 sequential bulk pass over plannable pendings
  chaos bulk --dry-run       show the plan without tracking anything
  chaos triage               walk non-PASS clips, dispatch the right
                             repair tool per clip (override / fix / tune)
                             --auto      auto-apply override-bucket fixes
                             --once      dispatch a single clip and exit
                             --filter S  only consider clips matching S

INFO / REPORT COMMANDS
  chaos status               who's tracked, who's pending (one-screen)
  chaos report               regenerate data/status_report.xlsx (Excel)
  chaos roadmap              regenerate docs/tracking_roadmap.md (per-clip Markdown table)
  chaos hsv-probe            probe every existing HSV file vs every HSV-ABORT clip
                             (--apply: copy the best OK match per clip)
  chaos audit                re-validate verified clips against current thresholds
                             --apply  downgrade clips that no longer pass
  chaos help                 this cheat sheet
  chaos <command> --help     full flag list for any subcommand

EXAMPLES
  chaos status
  chaos tune th1_p047_th2_m002
  chaos track th1_p047_th2_m002
  chaos fix th1_p047_th2_m002
  chaos next                            # the typical session: drive everything

WHERE TO LEARN MORE
  README.md                  quickstart, setup, architecture
  docs/PIPELINE.md           keystroke-level reference for every stage
  scripts/processing/*.py    low-level building blocks (callable directly)
  scripts/utils/*.py         orchestrators (track_one, manual_correction, bulk_track)
"""


def cmd_help(args):
    print(_HELP_CHEAT_SHEET)
    return 0


# ─────────────────────────────────────────────
# `next` — interactive god-mode
# ─────────────────────────────────────────────

def hsv_probe_for_clip(video_path):
    """Run the HSV adequacy probe headlessly. Returns (verdict, both_pct)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts", "processing"))
    import ring_tracker as rt
    import cv2
    hsv = rt.load_hsv_values(video_path)
    ring_tol = int(hsv.get("ring_tolerance", rt.DEFAULT_RING_TOL))
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return "ABORT", 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    verdict, both, _, _ = rt.hsv_adequacy_probe(
        cap, total, hsv, ring_tol,
        use_filename_prior=True, video_path=video_path,
    )
    cap.release()
    return verdict, both


def prompt(text, allowed):
    """Read a single-letter answer; loops until one of `allowed` is given."""
    allowed_lc = [a.lower() for a in allowed]
    while True:
        try:
            ans = input(text).strip().lower()
        except EOFError:
            return "q"
        if not ans:
            ans = allowed_lc[0]    # bare-Enter = first option (default)
        if ans[0] in allowed_lc:
            return ans[0]
        print(f"  (please answer one of: {', '.join(allowed)})")


def get_tracking_quality(stem):
    reg = load_registry()
    _, entry = find_entry_by_stem(reg, stem)
    if not entry: return None
    return entry.get("tracking_quality")


def cmd_next(args):
    """
    Interactive god-mode loop. For each pending clip:
      1. HSV adequacy probe → optionally launch hsv_tuner.
      2. track_one → verdict.
      3. WARN/FAIL → optionally launch manual_correction.
      4. Prompt for next clip / report / quit.
    """
    pending = list_pending_videos()
    print()
    print("=" * 70)
    print(f"chaos next — interactive driver")
    print("=" * 70)
    print(f"Pending: {len(pending)}")
    if args.stem:
        # Filter to a single stem when --stem is passed.
        target_video = resolve_video_path_for_stem(args.stem)
        if target_video is None:
            return 1
        pending = [os.path.basename(target_video)]

    if not pending:
        print("Nothing pending. Exiting.")
        return 0

    print()
    print("Pending queue (head 10):")
    for v in pending[:10]:
        print(f"  - {v}")
    if len(pending) > 10:
        print(f"  ... and {len(pending) - 10} more")
    print()

    for i, video_filename in enumerate(pending):
        stem = stem_for_video(video_filename)
        video_path = os.path.join(VIDEOS_DIR, video_filename)
        bar = "=" * 72
        print()
        print(bar)
        print(f"[{i + 1}/{len(pending)}]  {stem}")
        print(bar)
        print(f"Source video       : Videos\\{video_filename}")

        # ── Step 1: HSV adequacy probe ─────────────────────────────────
        hsv_kind = hsv_kind_for_stem(stem)
        hsv_label = ("per-video hsv_<stem>.json" if hsv_kind == "per-video"
                     else "global hsv_values.json (no per-video file yet)")
        print(f"HSV calibration    : {hsv_label}")
        try:
            verdict, both_pct = hsv_probe_for_clip(video_path)
        except Exception as e:
            print(f"HSV adequacy probe : ERROR  ({e})")
            verdict, both_pct = "WARN", 0.0
        else:
            verdict_arrow = {
                "OK":    f"{both_pct:.0f}%  ->  OK (≥70%, ready to track)",
                "WARN":  f"{both_pct:.0f}%  ->  WARN (40-70%, can proceed)",
                "ABORT": f"{both_pct:.0f}%  ->  ABORT (<40%, need to tune)",
            }
            print(f"HSV adequacy probe : "
                  f"{verdict_arrow.get(verdict, verdict)}")

        if verdict == "ABORT":
            print()
            print("Action required")
            print("  This clip needs HSV calibration before tracking can")
            print("  engage. Next step opens hsv_tuner so you can sample")
            print("  green and red marker pixels in this clip's lighting.")
            print()
            ans = prompt(
                "  [t]une HSV / [s]kip / [q]uit  (default tune): ",
                ["t", "s", "q"],
            )
            if ans == "q": break
            if ans == "s": continue
            run_script(SCRIPT_HSV_TUNER, video_path)
            # Re-probe after tuning.
            try:
                verdict, both_pct = hsv_probe_for_clip(video_path)
            except Exception:
                verdict = "WARN"
            print(f"HSV probe (post-tune): {verdict}  ({both_pct:.0f}%)")
        elif verdict == "WARN":
            print()
            print("Action required")
            print("  HSV is borderline — tracking will probably work but")
            print("  may produce more dropouts than usual. You can continue")
            print("  or re-tune for a cleaner pass.")
            print()
            ans = prompt(
                "  [c]ontinue / [t]une / [s]kip / [q]uit  (default continue): ",
                ["c", "t", "s", "q"],
            )
            if ans == "q": break
            if ans == "s": continue
            if ans == "t":
                run_script(SCRIPT_HSV_TUNER, video_path)

        # ── Step 2: track_one ─────────────────────────────────────────
        track_args = ["--stem", stem]
        if verdict in ("WARN", "OK"):
            # WARN already prompted; if user continued, suppress the
            # adequacy prompt inside ring_tracker.
            track_args.append("--yes-to-warn")
        rc = run_script(SCRIPT_TRACK_ONE, *track_args)

        if rc != 0:
            print()
            print("Action required")
            print("  track_one returned a non-zero exit code (FAIL or")
            print("  picker cancelled). Manual seed clicks are the next step.")
            print()
            ans = prompt(
                "  [f]ix manually / [s]kip / [q]uit  (default fix): ",
                ["f", "s", "q"],
            )
            if ans == "q": break
            if ans == "s": continue
            run_script(SCRIPT_MANUAL, "--stem", stem)

        # ── Step 3: read verdict from registry ─────────────────────────
        quality = get_tracking_quality(stem)
        if quality == "verified":
            print(f"\n  [PASS] {stem} verified.")
            ans = prompt(
                "  [Enter] next clip / [s]top here / [r]eport now: ",
                ["", "s", "r"],
            )
            if ans == "s": break
            if ans == "r":
                run_script(SCRIPT_REPORT)
                ans = prompt("  Continue to next clip? [y/n]: ", ["y", "n"])
                if ans == "n": break
        else:
            print(f"\n  [WARN] {stem} did not auto-verify "
                  f"(tracking_quality={quality!r}).")
            print()
            print("Action required")
            print("  Inspect measurements/<stem>/verification.png. If the")
            print("  trace looks like real chaos, [a]ccept. If the tracker")
            print("  latched onto something wrong, [f]ix with seeded retrack.")
            print()
            ans = prompt(
                "  [f]ix manually / [a]ccept anyway / [s]kip / [q]uit  "
                "(default fix): ",
                ["f", "a", "s", "q"],
            )
            if ans == "q": break
            if ans == "s": continue
            if ans == "a":
                # Mark verified despite WARN/FAIL — user took responsibility.
                _mark_verified(stem,
                               note="manually accepted via chaos next")
            elif ans == "f":
                run_script(SCRIPT_MANUAL, "--stem", stem)

    print()
    print("=" * 70)
    print(f"Loop complete.")
    run_script(SCRIPT_STATUS)
    return 0


def _mark_verified(stem, note="manually accepted"):
    reg = load_registry()
    _, entry = find_entry_by_stem(reg, stem)
    if not entry:
        return
    import datetime
    entry["tracking_quality"]   = "verified"
    entry["verification_date"]  = datetime.datetime.now().strftime("%Y-%m-%d")
    entry["verification_notes"] = note
    with open(EXPERIMENTS, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="chaos",
        description="Unified entry point for the chaos tracking pipeline.",
        epilog="Run `chaos help` for a one-page cheat sheet.")
    sub = p.add_subparsers(dest="command", required=False)

    sub.add_parser("status",
        help="list tracked vs pending videos with IC angles + dropout %%")

    p_report = sub.add_parser("report",
        help="regenerate data/status_report.xlsx (or --output PATH)")
    p_report.add_argument("--output", metavar="PATH",
        help="alternate output path for the .xlsx file")

    p_tune = sub.add_parser("tune",
        help="launch hsv_tuner.py on a clip's video")
    p_tune.add_argument("stem", metavar="<stem>",
        help="config_description, e.g. th1_p047_th2_m002")

    p_track = sub.add_parser("track",
        help="standard track + verify + interpolate + verdict card")
    p_track.add_argument("stem", metavar="<stem>",
        help="config_description, e.g. th1_p047_th2_m002")
    p_track.add_argument("--skip-probe", action="store_true",
        help="skip the HSV-adequacy probe (forces tracking even if HSV is poor)")
    p_track.add_argument("--yes-to-warn", action="store_true",
        help="auto-confirm a WARN verdict from the HSV probe (for bulk mode)")
    p_track.add_argument("--debug", action="store_true",
        help="generate debug.mp4 (default: skipped to save 50–400 MB)")
    p_track.add_argument("--omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="ω threshold for the verify step (default 2500 °/s)")

    p_fix = sub.add_parser("fix",
        help="interactive manual-seed correction + re-track + verdict")
    p_fix.add_argument("stem", metavar="<stem>",
        help="config_description, e.g. th1_p047_th2_m002")
    p_fix.add_argument("--save-only", action="store_true",
        help="save seeds.json and quit; skip the re-track step")
    p_fix.add_argument("--omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="ω threshold for the verify step (default 2500 °/s)")

    p_override = sub.add_parser("override",
        help="surgical CSV-row edit for a single bad frame (no re-track)")
    p_override.add_argument("stem", metavar="<stem>",
        help="config_description, e.g. th1_p047_th2_m002")
    p_override.add_argument("--frame", type=int, required=True,
        metavar="N", help="frame index whose row to overwrite")
    p_override.add_argument("--no-verify", action="store_true",
        help="skip the post-write verify_tracking re-run")
    p_override.add_argument("--omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="ω threshold for the post-write verify step (default 2500 °/s)")

    p_verify = sub.add_parser("verify",
        help="standalone QA on an existing tracking.csv (no track/fix)")
    p_verify.add_argument("stem", metavar="<stem>",
        help="config_description, e.g. th1_p047_th2_m002")
    p_verify.add_argument("--omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="ω threshold above which |Δθ/dt| is suspect (default 2500)")
    p_verify.add_argument("--no-plot", action="store_true",
        help="skip writing measurements/<stem>/verification.png")
    # Brief 5+6 — physics-check threshold overrides. Defaults are
    # supplied by verify_tracking.py from thresholds.py; passing None
    # here means "don't override".
    p_verify.add_argument("--delta-omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="max |Δω| per frame; catches sudden tracker latches")
    p_verify.add_argument("--theta-residual-cap", type=float, default=None,
        metavar="DEG",
        help="θ vs (θ+ω·dt) prediction-residual gate (default 5°)")
    p_verify.add_argument("--energy-spike-factor", type=float, default=None,
        metavar="RATIO",
        help="E[i] / rolling baseline ratio above which a frame is "
             "flagged (default 1.3)")
    p_verify.add_argument("--energy-headroom", type=float, default=None,
        metavar="RATIO",
        help="E[i] ≤ E_release × this before flagging (default 1.15)")
    p_verify.add_argument("--arm-len-threshold", type=float, default=None,
        metavar="PCT",
        help="per-frame arm-length deviation %% gate (default 10)")
    p_verify.add_argument("--arm-trend-window", type=int, default=None,
        metavar="FRAMES",
        help="sliding-window size for arm-length trend (default 100)")
    p_verify.add_argument("--arm-trend-dev", type=float, default=None,
        metavar="PCT",
        help="trend window %% deviation that flags the window (default 5)")

    p_bulk = sub.add_parser("bulk",
        help="sequential bulk pass over plannable pending clips")
    p_bulk.add_argument("--dry-run", action="store_true",
        help="print the plan and exit; don't track anything")
    p_bulk.add_argument("--filter", metavar="SUBSTR",
        help="only process clips whose stem contains SUBSTR")
    p_bulk.add_argument("--debug", action="store_true",
        help="generate debug.mp4 for each clip (default: skipped)")
    p_bulk.add_argument("--redo", action="store_true",
        help="re-track even clips that already have a verified tracking.csv")

    p_roadmap = sub.add_parser("roadmap",
        help="regenerate docs/tracking_roadmap.md from registry state")
    p_roadmap.add_argument("--output", metavar="PATH", default=None,
        help="alternate output path (default: docs/tracking_roadmap.md)")
    p_roadmap.add_argument("--dry-run", action="store_true",
        help="print the markdown to stdout instead of writing")

    p_hsv_probe = sub.add_parser("hsv-probe",
        help="probe every existing HSV file against every HSV-ABORT clip")
    p_hsv_probe.add_argument("--filter", metavar="SUBSTR",
        help="only probe clips whose stem contains SUBSTR")
    p_hsv_probe.add_argument("--apply", action="store_true",
        help="copy the best-scoring OK match into hsv_<stem>.json per clip")
    p_hsv_probe.add_argument("--warn-also", action="store_true",
        help="also recommend WARN-band matches (default: OK only)")

    p_audit = sub.add_parser("audit",
        help="re-validate verified clips against current verdict logic")
    p_audit.add_argument("--apply", action="store_true",
        help="downgrade tracking_quality on clips whose new verdict isn't PASS")
    p_audit.add_argument("--upgrade", action="store_true",
        help="also audit non-verified clips with tracking.csv; with "
             "--apply, mark new PASSes as verified")
    p_audit.add_argument("--filter", metavar="SUBSTR",
        help="only audit clips whose stem contains SUBSTR")
    p_audit.add_argument("--skip-reverify", action="store_true",
        help="trust existing verification.csv; skip the verify_tracking re-run")
    p_audit.add_argument("--omega-cap", type=float, default=None,
        metavar="DEG_PER_S",
        help="ω cap passed to verify_tracking (default 2500 °/s)")

    p_next = sub.add_parser("next",
        help="interactive driver — process pending clips end-to-end")
    p_next.add_argument("--stem", default=None, metavar="<stem>",
        help="optional: process only this stem instead of the full queue")

    p_triage = sub.add_parser("triage",
        help="walk through non-PASS clips, dispatch the right repair tool per clip")
    p_triage.add_argument("--auto", action="store_true",
        help="auto-apply override-bucket fixes; still prompts for "
             "fix/tune/review buckets")
    p_triage.add_argument("--once", action="store_true",
        help="dispatch a single clip and exit (default: loop)")
    p_triage.add_argument("--filter", metavar="SUBSTR",
        help="only consider clips whose stem matches SUBSTR")

    sub.add_parser("help", help="one-page cheat sheet for all subcommands")

    return p


HANDLERS = {
    "status":     cmd_status,
    "report":     cmd_report,
    "roadmap":    cmd_roadmap,
    "hsv-probe":  cmd_hsv_probe,
    "audit":      cmd_audit,
    "tune":       cmd_tune,
    "track":    cmd_track,
    "fix":      cmd_fix,
    "override": cmd_override,
    "verify":   cmd_verify,
    "bulk":     cmd_bulk,
    "next":     cmd_next,
    "triage":   cmd_triage,
    "help":     cmd_help,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
