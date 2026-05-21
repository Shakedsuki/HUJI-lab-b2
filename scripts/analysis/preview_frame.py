"""
preview_frame.py
-----------------
Quick sanity-check helper: render ONE representative frame of an
overlay using the current make_left_panel() so cosmetic changes can be
visually inspected without waiting for a full overlay.mp4.

Picks the frame with the largest pivot-to-red distance (worst-case
position for the reachable-disc crop) by default, or a specific frame
via --frame.

Output: measurements/<stem>/preview.png

Usage:
  python scripts/analysis/preview_frame.py --stem 3.2V_0.9Hz
  python scripts/analysis/preview_frame.py --stem 3.2V_0.9Hz --frame 1234
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
sys.path.insert(0, os.path.abspath(os.path.join(_THIS_DIR, os.pardir, "utils")))
from combined_video import (  # noqa: E402
    load_csv,
    make_left_panel,
    resolve_paths,
)
from thresholds import get_pivot_arm  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Render one overlay frame as PNG.")
    p.add_argument("--stem", required=True,
                   help="config_description; resolves CSV/video from "
                        "experiments.json.")
    p.add_argument("--frame", type=int, default=None,
                   help="Frame index to render. Default: frame with the "
                        "largest pivot-to-red distance.")
    return p.parse_args()


def main():
    args = parse_args()
    # Reuse resolve_paths by faking the positional args.
    class _A:
        pass
    a = _A()
    a.stem = args.stem
    a.csv = None
    a.video = None
    csv_path, video_path, _combined_mp4, output_dir = resolve_paths(a)
    out_png = os.path.join(output_dir, "preview.png")

    stem = args.stem
    pivot_orig, arm_length_px = get_pivot_arm(stem)

    frames, times, phases, th1, th2, om1, om2, dropouts = load_csv(csv_path)
    N = len(frames)

    rows = list(csv.DictReader(open(csv_path)))
    xg = np.array([float(r['x_green']) if r['x_green'] else np.nan for r in rows])
    yg = np.array([float(r['y_green']) if r['y_green'] else np.nan for r in rows])
    xr = np.array([float(r['x_red'])   if r['x_red']   else np.nan for r in rows])
    yr = np.array([float(r['y_red'])   if r['y_red']   else np.nan for r in rows])

    if args.frame is None:
        d_sq = (xr - pivot_orig[0])**2 + (yr - pivot_orig[1])**2
        d_sq = np.where(np.isnan(d_sq), -1, d_sq)
        i = int(np.argmax(d_sq))
        d = float(np.sqrt(d_sq[i])) if d_sq[i] >= 0 else float('nan')
        print(f"  picked frame {i} (t={times[i]:.3f}s) — pivot→red = {d:.1f}px  "
              f"(reachable disc r = {2*arm_length_px}px)")
    else:
        i = args.frame
        print(f"  using frame {i} (t={times[i]:.3f}s)")

    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, i)
    ret, vframe = cap.read()
    cap.release()
    if not ret:
        print(f"ERROR: could not read frame {i}")
        return 1

    panel = make_left_panel(
        vframe, phases[i], times[i],
        th1[i], th2[i], om1[i], om2[i],
        xg[i], yg[i], xr[i], yr[i],
        pivot_orig=pivot_orig, arm_length_px=arm_length_px,
    )
    cv2.imwrite(out_png, panel)
    print(f"  saved: {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
