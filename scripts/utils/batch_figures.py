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
from paths import MEAS_DIR, EXPERIMENTS, FIGURES_DIR, clip_dir  # noqa: E402
from figures_paths import figure_path                  # noqa: E402

ROOT     = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
ANALYSIS = os.path.join(ROOT, "scripts", "analysis")
PYTHON   = sys.executable

from rich.console import Console  # noqa: E402
from rich.rule import Rule        # noqa: E402
console = Console()


# ─────────────────────────────────────────────
# Figure suite definition
# Each entry: (figure_type, ext, needs_verification, script, extra_args)
# ─────────────────────────────────────────────

STATIC_SUITE = [
    ("phase_panels",      "png", False, "phase_panels.py",   ["--save"]),
    ("poincare",          "png", True,  "poincare.py",       []),
    ("phase_3d_trajectory","png",False, "phase_3d.py",       ["--static"]),
    ("chaos_analyze",     "png", True,  "chaos_analyze.py",  []),
    ("lyapunov",          "png", True,  "lyapunov.py",       []),
    ("seismograph_v1",    "png", False, "seismograph.py",    ["--mode", "v1"]),
    ("seismograph_v2",    "png", False, "seismograph.py",    ["--mode", "v2"]),
    ("dimension",         "png", False, "dimension.py",      []),
    ("driven_poincare",   "png", True,  "driven_poincare.py",[]),
    ("return_map",        "png", True,  "return_map.py",     []),
]

VIDEO_SUITE = [
    ("phase_animation",   "mp4", False, "phase_animation.py", []),
    ("combined",          "mp4", False, "combined_video.py",   []),
    ("phase_3d_rotation", "mp4", False, "phase_3d.py",         []),
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


def passed_qa_stems():
    """Stems whose overlay-review verdict is 'pass' — the QA gate for figures."""
    if not os.path.exists(EXPERIMENTS):
        return set()
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        reg = json.load(f)
    return {e.get("config_description") for e in reg.values()
            if e.get("overlay_verdict") == "pass" and e.get("config_description")}


def has_verification(stem):
    return os.path.exists(os.path.join(clip_dir(stem), "verification.csv"))


def run_suite(stems, suite, force, label):
    total = len(stems) * len(suite)
    done = skipped = failed = 0

    for stem in stems:
        console.print()
        console.print(Rule(f"[bold]{stem}[/]", style="dim"))

        for fig_type, ext, needs_verif, script, extra in suite:
            out_path = figure_path(fig_type, stem, ext)

            if not force and os.path.exists(out_path):
                console.print(f"  [dim]{fig_type:<20}[/] [yellow]skip[/]  [dim](exists)[/]")
                skipped += 1
                continue

            if needs_verif and not has_verification(stem):
                console.print(f"  [dim]{fig_type:<20}[/] [yellow]skip[/]  [dim](no verification.csv — run chaos verify first)[/]")
                skipped += 1
                continue

            script_path = os.path.join(ANALYSIS, script)

            # chaos_analyze takes stem as positional, others use --stem
            if script == "chaos_analyze.py":
                cmd = [PYTHON, script_path, stem] + extra
            else:
                cmd = [PYTHON, script_path, "--stem", stem] + extra

            result = subprocess.run(cmd, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace")
            if result.returncode == 0:
                relpath = os.path.relpath(out_path, ROOT)
                console.print(f"  [dim]{fig_type:<20}[/] [green]OK[/]   [dim]{relpath}[/]")
                done += 1
            else:
                console.print(f"  [dim]{fig_type:<20}[/] [red]FAIL[/]")
                for line in (result.stderr or result.stdout or "").splitlines()[-8:]:
                    console.print(f"  [dim]  {line}[/]")
                failed += 1

    console.print()
    style = "green" if failed == 0 else "red"
    console.print(f"  [{style} bold]{done}[/] rendered  [dim]{skipped} skipped  {failed} failed[/]")
    return failed


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch-render all per-clip figures for tracked measurements.")
    p.add_argument("--stem", default=None,
                   help="Render figures for one specific stem only.")
    p.add_argument("--stems", default=None,
                   help="comma-separated stems to render (overrides --stem).")
    p.add_argument("--video", action="store_true",
                   help="Also render phase_animation and combined mp4 (slow).")
    p.add_argument("--force", action="store_true",
                   help="Re-render even if output files already exist.")
    p.add_argument("--types", default=None,
                   help="comma-separated figure types to render (default: all).")
    p.add_argument("--all-quality", action="store_true",
                   help="include clips that haven't passed overlay QA (default: pass only).")
    return p.parse_args()


def main():
    args = parse_args()

    if args.stems:
        stems = [s.strip() for s in args.stems.split(",") if s.strip()]
    elif args.stem:
        stems = [args.stem]
    else:
        stems = load_tracked_stems()

    if not args.all_quality:
        passed = passed_qa_stems()
        skipped = [s for s in stems if s not in passed]
        stems = [s for s in stems if s in passed]
        if skipped:
            console.print(f"[yellow]QA gate:[/] skipped {len(skipped)} clip(s) not passed in "
                          f"overlay review [dim](--all-quality to include)[/]")

    if not stems:
        console.print("[yellow]WARN:[/] no clips to render — need an overlay-review "
                      "[dim]'pass'[/] (run vr), or use [dim]--all-quality[/].")
        sys.exit(0)

    suite = STATIC_SUITE + (VIDEO_SUITE if args.video else [])
    if args.types:
        want = {x.strip() for x in args.types.split(",") if x.strip()}
        suite = [s for s in suite if s[0] in want]
        if not suite:
            console.print(f"[yellow]WARN:[/] no known figure types in {sorted(want)}.")
            sys.exit(0)

    console.print(
        f"[cyan]Batch figures[/]  [dim]{len(stems)} clip(s), {len(suite)} figure type(s)"
        + ("  force" if args.force else "") + "[/]"
    )

    failures = run_suite(stems, suite, args.force, "total")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
