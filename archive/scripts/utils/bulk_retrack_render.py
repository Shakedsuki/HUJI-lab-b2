"""
bulk_retrack_render.py
-----------------------
Re-track every clip in a list under the current bgr_tracker, then
render its <stem>_overlay.mp4 for visual review. Sequential to keep
the CPU happy. Skips clips already marked tracking_quality=verified
unless --include-verified is passed.

Usage:
    CHAOS_PHASE=week5-6-pendulum-motor-driven \\
        python scripts/utils/bulk_retrack_render.py --filter 3.2V_

    # Limit to a frequency range:
    python scripts/utils/bulk_retrack_render.py --filter 3.2V_ \\
        --order desc                  # process high-frequency first

    # Skip the render step (re-track only):
    python scripts/utils/bulk_retrack_render.py --filter 3.2V_ --no-render

The video file is auto-copied from the main repo (C:/dev/chaos)
into the worktree if missing, so this works in either a worktree
or the main checkout.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from paths import EXPERIMENTS, VIDEOS_DIR, REPO_ROOT, PHASE_DRIVEN  # noqa: E402

# When this script runs inside a git worktree, gitignored .mov files
# live in the main checkout, not the worktree's videos dir. This is
# the canonical fallback location.
_MAIN_REPO_VIDEOS = f"C:/dev/chaos/experiments/{PHASE_DRIVEN}/videos"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", default="",
                    help="only include clips whose stem contains this substring")
    ap.add_argument("--order", choices=("asc", "desc"), default="desc",
                    help="frequency order to walk the clips (default: desc — "
                         "high-freq first)")
    ap.add_argument("--include-verified", action="store_true",
                    help="don't skip clips already marked tracking_quality=verified")
    ap.add_argument("--no-render", action="store_true",
                    help="re-track only; skip the overlay render step")
    ap.add_argument("--skip", default="",
                    help="comma-separated stems to skip (e.g. clips currently "
                         "being watched in a player)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be done, run nothing")
    return ap.parse_args()


def load_registry():
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_clips(reg, filter_substr, include_verified, order, skip):
    """Return list of (stem, video_file) tuples in the requested order."""
    skip_set = {s.strip() for s in skip.split(",") if s.strip()}
    items = []
    for entry in reg.values():
        stem = entry.get("config_description")
        if not stem:
            continue
        if filter_substr and filter_substr not in stem:
            continue
        if stem in skip_set:
            continue
        if not include_verified and entry.get("tracking_quality") == "verified":
            continue
        video_file = entry.get("video_file") or f"{stem}.mov"
        freq = entry.get("drive_freq_hz", 0.0) or 0.0
        items.append((stem, video_file, freq))
    items.sort(key=lambda t: t[2], reverse=(order == "desc"))
    return [(s, v) for (s, v, _) in items]


def ensure_video(video_file):
    """Make sure the .mov file is reachable from the local videos/ dir."""
    target = os.path.join(VIDEOS_DIR, video_file)
    if os.path.exists(target):
        return target
    src = os.path.join(_MAIN_REPO_VIDEOS, video_file)
    if not os.path.exists(src):
        print(f"    ERROR: video file missing in main repo: {src}")
        return None
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    shutil.copy2(src, target)
    return target


def run(cmd, env=None):
    """Run a subprocess and stream its tail line so the user has feedback."""
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"    FAILED ({proc.returncode}). Tail:")
        print(proc.stdout[-500:])
        print(proc.stderr[-500:])
        return False
    last = [l for l in proc.stdout.splitlines() if l.strip()]
    if last:
        print(f"    {last[-1]}")
    return True


def main():
    args = parse_args()
    reg = load_registry()
    clips = collect_clips(reg, args.filter, args.include_verified,
                          args.order, args.skip)

    print()
    print("=" * 70)
    print(f"bulk_retrack_render — {len(clips)} clips, order={args.order}")
    print("=" * 70)
    for i, (stem, _) in enumerate(clips, 1):
        print(f"  {i:>3}.  {stem}")
    print("=" * 70)
    if args.dry_run:
        return 0
    print()

    env = dict(os.environ)

    for i, (stem, video_file) in enumerate(clips, 1):
        print(f"\n[{i}/{len(clips)}] {stem}")

        video_path = ensure_video(video_file)
        if video_path is None:
            print(f"    skip — no video")
            continue

        rel = os.path.relpath(video_path, REPO_ROOT)
        track_cmd = [
            sys.executable, "scripts/processing/bgr_tracker.py",
            rel, "--force",
        ]
        print(f"    re-tracking ...")
        if not run(track_cmd, env=env):
            continue

        if args.no_render:
            continue

        render_cmd = [
            sys.executable, "scripts/analysis/overlay_video.py",
            "--stem", stem,
        ]
        print(f"    rendering overlay ...")
        run(render_cmd, env=env)

    print()
    print("=" * 70)
    print("bulk_retrack_render done")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
