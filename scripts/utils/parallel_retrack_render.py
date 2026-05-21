"""
parallel_retrack_render.py
---------------------------
Same per-clip work as bulk_retrack_render.py (copy video → re-track →
render <stem>_overlay.mp4), but runs N clips concurrently via a worker
pool. Each worker handles one clip end-to-end, so there is no shared
state and no need for inter-worker coordination beyond the worker
limit.

Usage:
    CHAOS_PHASE=week5-6-pendulum-motor-driven \\
        python scripts/utils/parallel_retrack_render.py \\
            --filter 3.2V_ --workers 4

The default worker count is 4 — a reasonable balance on a modern
laptop CPU for OpenCV+matplotlib loads. Drop to 2 if you hit thermal
throttling or memory pressure.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


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
                    help="frequency order (default desc — high-freq first)")
    ap.add_argument("--include-verified", action="store_true",
                    help="don't skip clips already marked tracking_quality=verified")
    ap.add_argument("--skip", default="",
                    help="comma-separated stems to skip")
    ap.add_argument("--skip-rendered", action="store_true",
                    help="skip clips that already have a <stem>_overlay.mp4 on disk")
    ap.add_argument("--no-render", action="store_true",
                    help="re-track only; skip overlay render")
    ap.add_argument("--workers", type=int, default=4,
                    help="max parallel workers (default 4)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print queue, run nothing")
    return ap.parse_args()


def load_registry():
    with open(EXPERIMENTS, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_clips(reg, filter_substr, include_verified, order, skip,
                  skip_rendered):
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
        if skip_rendered:
            overlay = os.path.join(
                REPO_ROOT, "experiments", PHASE_DRIVEN, "measurements",
                stem, f"{stem}_overlay.mp4")
            if os.path.exists(overlay):
                continue
        video_file = entry.get("video_file") or f"{stem}.mov"
        freq = entry.get("drive_freq_hz", 0.0) or 0.0
        items.append((stem, video_file, freq))
    items.sort(key=lambda t: t[2], reverse=(order == "desc"))
    return [(s, v) for (s, v, _) in items]


def ensure_video(video_file):
    target = os.path.join(VIDEOS_DIR, video_file)
    if os.path.exists(target):
        return target
    src = os.path.join(_MAIN_REPO_VIDEOS, video_file)
    if not os.path.exists(src):
        return None
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    shutil.copy2(src, target)
    return target


def process_clip(stem, video_file, do_render):
    """Run re-track + render for one clip. Returns dict with status fields."""
    t0 = time.time()
    video_path = ensure_video(video_file)
    if video_path is None:
        return {"stem": stem, "ok": False,
                "error": "video missing", "elapsed_s": 0.0}

    rel = os.path.relpath(video_path, REPO_ROOT)

    # Re-track
    track = subprocess.run(
        [sys.executable, "scripts/processing/bgr_tracker.py",
         rel, "--force"],
        capture_output=True, text=True)
    if track.returncode != 0:
        return {"stem": stem, "ok": False,
                "error": f"track exit {track.returncode}",
                "tail": track.stderr[-400:],
                "elapsed_s": time.time() - t0}

    if not do_render:
        return {"stem": stem, "ok": True, "step": "track-only",
                "elapsed_s": time.time() - t0}

    # Render
    render = subprocess.run(
        [sys.executable, "scripts/analysis/overlay_video.py",
         "--stem", stem],
        capture_output=True, text=True)
    if render.returncode != 0:
        return {"stem": stem, "ok": False,
                "error": f"render exit {render.returncode}",
                "tail": render.stderr[-400:],
                "elapsed_s": time.time() - t0}

    return {"stem": stem, "ok": True, "step": "full",
            "elapsed_s": time.time() - t0}


def main():
    args = parse_args()
    reg = load_registry()
    clips = collect_clips(reg, args.filter, args.include_verified,
                          args.order, args.skip, args.skip_rendered)

    print()
    print("=" * 70)
    print(f"parallel_retrack_render — {len(clips)} clips, "
          f"workers={args.workers}, order={args.order}")
    print("=" * 70)
    for i, (stem, _) in enumerate(clips, 1):
        print(f"  {i:>3}.  {stem}")
    if args.dry_run:
        return 0
    print()

    t0 = time.time()
    done = 0
    failed = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_clip, stem, video_file, not args.no_render):
                stem
            for (stem, video_file) in clips
        }
        for fut in as_completed(futures):
            r = fut.result()
            done += 1
            if r["ok"]:
                print(f"  [{done:>2}/{len(clips)}]  ✓  "
                      f"{r['stem']:<22}  ({r['elapsed_s']:>5.1f}s)")
            else:
                print(f"  [{done:>2}/{len(clips)}]  ✗  "
                      f"{r['stem']:<22}  {r.get('error','?')}")
                failed.append(r)

    print()
    print("=" * 70)
    print(f"parallel_retrack_render done in {time.time()-t0:.1f}s — "
          f"{done-len(failed)}/{done} succeeded")
    if failed:
        for r in failed:
            print(f"  FAIL {r['stem']}: {r.get('error')}")
            tail = r.get("tail", "")
            if tail:
                for ln in tail.splitlines()[-3:]:
                    print(f"      {ln}")
    print("=" * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
