"""
overlay_video.py
----------------
Render only the left panel of combined_video.py — the original video
with tracking-marker overlays. No phase-space plots, no matplotlib
per frame, much faster. For quick visual sanity checks of a tracking
pass.

Output: measurements/<stem>/overlay.mp4 at source framerate, 960×720.

Usage:
  # Mode 1 — measurement folder:
  python scripts/analysis/overlay_video.py --stem 3.2V_1.34Hz

  # Mode 2 — explicit CSV + video:
  python scripts/analysis/overlay_video.py \\
      measurements/3.2V_1.34Hz/tracking.csv videos/3.2V_1.34Hz.mov

Imports load_csv and make_left_panel from combined_video so the
overlay matches the combined-video version frame-for-frame.
"""

import argparse
import csv
import os
import sys

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from combined_video import (  # noqa: E402
    FPS_OUT,
    PANEL_H,
    PANEL_W,
    load_csv,
    make_left_panel,
    resolve_paths,
)


def parse_args():
    p = argparse.ArgumentParser(
        description="Render tracking-overlay video (no phase plots).")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to tracking CSV (positional, optional).")
    p.add_argument("video", nargs="?", default=None,
                   help="Path to source video (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description; resolves CSV/video from "
                        "experiments.json.")
    return p.parse_args()


def main():
    args = parse_args()
    # resolve_paths returns the combined.mp4 path in [2]; we ignore it
    # and write overlay.mp4 alongside the measurement folder instead.
    csv_path, video_path, _combined_mp4, output_dir = resolve_paths(args)
    output_mp4 = os.path.join(output_dir, "overlay.mp4")

    print(f"CSV    : {csv_path}")
    print(f"Video  : {video_path}")
    print(f"Output : {output_mp4}")

    print("Loading CSV ...")
    frames, times, phases, th1, th2, om1, om2, dropouts = load_csv(csv_path)
    N = len(frames)
    print(f"  {N} frames, t_max = {times[-1]:.2f}s")

    rows = list(csv.DictReader(open(csv_path)))
    xg = np.array([float(r['x_green']) if r['x_green'] else np.nan for r in rows])
    yg = np.array([float(r['y_green']) if r['y_green'] else np.nan for r in rows])
    xr = np.array([float(r['x_red'])   if r['x_red']   else np.nan for r in rows])
    yr = np.array([float(r['y_red'])   if r['y_red']   else np.nan for r in rows])

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cannot open {video_path}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_OUT

    os.makedirs(output_dir, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_mp4, fourcc, fps, (PANEL_W, PANEL_H))

    print(f"Rendering {N} frames -> {output_mp4}")
    step = max(1, N // 40)
    for i in range(N):
        ret, vframe = cap.read()
        if not ret:
            print(f"\nWARN: video ended at frame {i}")
            break
        panel = make_left_panel(
            vframe, phases[i], times[i],
            th1[i], th2[i], om1[i], om2[i],
            xg[i], yg[i], xr[i], yr[i],
        )
        writer.write(panel)
        if i % step == 0 or i == N - 1:
            pct = 100 * (i + 1) // N
            bar = '#' * (pct // 5) + '-' * (20 - pct // 5)
            print(f"  [{bar}] {pct:3d}%  frame {i+1}/{N}",
                  end='\r', flush=True)
    cap.release()
    writer.release()
    print(f"\nDone. Saved to: {output_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
