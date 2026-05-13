"""
batch_figures.py
----------------
Render all per-clip figures for every tracked measurement that is missing
its outputs. Skips clips whose figures already exist unless --force is set.

Invoked via:
    chaos figures               # all tracked clips, static figures only
    chaos figures --stem 3V_1Hz # one clip only
    chaos figures --video       # also render phase_animation + combined mp4
    chaos figures --force       # re-render even if outputs already exist
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

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from paths import MEAS_DIR, EXPERIMENTS, FIGURES_DIR  # noqa: E402
from figures_paths import figure_path                  # noqa: E402

ROOT     = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
ANALYSIS = os.path.join(ROOT, "scripts", "analysis")
PYTHON   = sys.executable


# ─────────────────────────────────────────────
# Figure suite definition
# Each entry: (figure_type, ext, needs_verification, script, extra_args)
# ─────────────────────────────────────────────

STATIC_SUITE = [
    ("phase_panels",      "png", False, "phase_panels.py",   ["--save"]),
    ("poincare",          "png", True,  "poincare.py",       []),
    ("phase_3d_trajectory","png",False, "phase_3d.py",       []),
    ("chaos_analyze",     "png", True,  "chaos_analyze.py",  []),
    ("lyapunov",          "png", True,  "lyapunov.py",       []),
]

VIDEO_SUITE = [
    ("phase_animation",   "mp4", False, "phase_animation.py", []),
    ("combined",          "mp4", False, "combined_video.py",   []),
]


def load_tracked_stems():
    """Return list of stems that have a tracking.csv on disk."""
    if not os.path.exists(EXPERIMENTS):
        return []
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        reg = json.load(f)
    stems = []
    for entry in reg.values():
        md = entry.get("measurements_dir")
        if not md:
            continue
        csv_basename = entry.get("csv_file") or "tracking.csv"
        phase_root = os.path.dirname(MEAS_DIR)
        csv_path = os.path.join(phase_root, md, csv_basename)
        if os.path.exists(csv_path):
            stems.append(entry.get("config_description") or Path(md).name)
    return sorted(stems)


def has_verification(stem):
    return os.path.exists(os.path.join(MEAS_DIR, stem, "verification.csv"))


def run_suite(stems, suite, force, label):
    total = len(stems) * len(suite)
    done = skipped = failed = 0

    for stem in stems:
        print(f"\n{'─'*60}")
        print(f"  {stem}")
        print(f"{'─'*60}")

        for fig_type, ext, needs_verif, script, extra in suite:
            out_path = figure_path(fig_type, stem, ext)

            if not force and os.path.exists(out_path):
                print(f"  [skip] {fig_type}  (exists)")
                skipped += 1
                continue

            if needs_verif and not has_verification(stem):
                print(f"  [skip] {fig_type}  (no verification.csv — run chaos verify first)")
                skipped += 1
                continue

            script_path = os.path.join(ANALYSIS, script)

            # chaos_analyze takes stem as positional, others use --stem
            if script == "chaos_analyze.py":
                cmd = [PYTHON, script_path, stem] + extra
            else:
                cmd = [PYTHON, script_path, "--stem", stem] + extra

            print(f"  [ run] {fig_type} ...", end="", flush=True)
            result = subprocess.run(cmd, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace")
            if result.returncode == 0:
                print(f"  OK  → {os.path.relpath(out_path, ROOT)}")
                done += 1
            else:
                print(f"  FAIL")
                # Print stderr indented for readability
                for line in (result.stderr or result.stdout or "").splitlines()[-8:]:
                    print(f"       {line}")
                failed += 1

    print(f"\n{'═'*60}")
    print(f"  {label}: {done} rendered, {skipped} skipped, {failed} failed")
    print(f"{'═'*60}")
    return failed


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch-render all per-clip figures for tracked measurements.")
    p.add_argument("--stem", default=None,
                   help="Render figures for one specific stem only.")
    p.add_argument("--video", action="store_true",
                   help="Also render phase_animation and combined mp4 (slow).")
    p.add_argument("--force", action="store_true",
                   help="Re-render even if output files already exist.")
    return p.parse_args()


def main():
    args = parse_args()

    if args.stem:
        stems = [args.stem]
    else:
        stems = load_tracked_stems()

    if not stems:
        print("No tracked measurements found. Run 'chaos track <stem>' first.")
        sys.exit(0)

    suite = STATIC_SUITE + (VIDEO_SUITE if args.video else [])

    print(f"Batch figures — {len(stems)} clip(s), {len(suite)} figure type(s)")
    print(f"Force re-render: {args.force}")

    failures = run_suite(stems, suite, args.force, "total")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
