"""
calibrate_pivot.py  —  Phase 2 rig calibration
------------------------------------------------
Detects the green marker (Pivot β) across all frames of one or more video
clips, fits a circle to the collected pixel positions, and reports:

    PIVOT        = (cx, cy)   — Pivot α in pixels (circle center)
    ARM_LENGTH_PX = r          — Arm 1 length in pixels (circle radius)

Also writes a diagnostic PNG showing detected positions + fitted circle.

Usage:
    python phase2-motor-driven/calibrate_pivot.py
    python phase2-motor-driven/calibrate_pivot.py --videos 3V_1Hz.mov 4V_2Hz.mov
    python phase2-motor-driven/calibrate_pivot.py --hsv-h 40 100 --hsv-s 80 255 --hsv-v 40 255
"""

import argparse
import os
import sys

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import least_squares


VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")
OUT_DIR    = os.path.dirname(os.path.abspath(__file__))

# ── Broad starting HSV for the green marker ──────────────────────────────────
# OpenCV uses H in [0,179], S and V in [0,255].
# Phase 2 green marker appears saturated pure-green; sweep wide so we don't
# need exact tuning for a calibration pass.
DEFAULT_H_MIN, DEFAULT_H_MAX = 35, 95
DEFAULT_S_MIN, DEFAULT_S_MAX = 80, 255
DEFAULT_V_MIN, DEFAULT_V_MAX = 40, 220

MIN_BLOB_AREA  = 30    # px² — ignore specks smaller than this
MAX_BLOB_AREA  = 2000  # px² — ignore huge blobs (reflections, etc.)
SAMPLE_EVERY   = 3     # use every Nth frame (faster, still dense enough)


# ── Circle fit ────────────────────────────────────────────────────────────────

def algebraic_circle_fit(pts):
    """Kasa algebraic least-squares circle fit. Fast, good init for refinement."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    b = x**2 + y**2
    c, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    cx = c[0] / 2
    cy = c[1] / 2
    r  = np.sqrt(c[2] + cx**2 + cy**2)
    return cx, cy, r


def geometric_circle_fit(pts, cx0, cy0, r0):
    """Refine with geometric (orthogonal) residuals via scipy least_squares."""
    def residuals(params):
        cx, cy, r = params
        d = np.sqrt((pts[:, 0] - cx)**2 + (pts[:, 1] - cy)**2)
        return d - r
    result = least_squares(residuals, [cx0, cy0, r0], method="lm")
    cx, cy, r = result.x
    return cx, cy, r, result


# ── Per-video detection ───────────────────────────────────────────────────────

def detect_green_positions(video_path, hsv_params, sample_every=SAMPLE_EVERY):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  Cannot open {video_path}")
        return np.empty((0, 2))

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    print(f"  {os.path.basename(video_path)}: {total} frames @ {fps:.2f} fps")

    h_min, h_max, s_min, s_max, v_min, v_max = hsv_params
    lower = np.array([h_min, s_min, v_min], dtype=np.uint8)
    upper = np.array([h_max, s_max, v_max], dtype=np.uint8)

    positions = []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % sample_every == 0:
            hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, lower, upper)
            # Morphological cleanup
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
            mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
                mask, connectivity=8)
            for i in range(1, n_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if MIN_BLOB_AREA <= area <= MAX_BLOB_AREA:
                    positions.append(centroids[i])

        frame_idx += 1

    cap.release()
    arr = np.array(positions)
    print(f"  -> {len(arr)} green detections collected")
    return arr


# ── Diagnostic plot ───────────────────────────────────────────────────────────

def save_diagnostic(all_pts, pivot, arm_px, per_video, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))

    # Left: raw scatter + fitted circle
    ax = axes[0]
    colors = plt.cm.tab10(np.linspace(0, 1, max(len(per_video), 1)))
    for (label, pts), col in zip(per_video, colors):
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 1], s=2, alpha=0.4, color=col, label=label)
    theta = np.linspace(0, 2 * np.pi, 360)
    ax.plot(pivot[0] + arm_px * np.cos(theta),
            pivot[1] + arm_px * np.sin(theta),
            'k-', lw=2, label=f"fit r={arm_px:.1f}px")
    ax.plot(*pivot, 'r+', ms=14, mew=3, label=f"PIVOT=({pivot[0]:.1f},{pivot[1]:.1f})")
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_title("Green marker positions + circle fit")
    ax.legend(fontsize=8, markerscale=4)
    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")

    # Right: radial residuals
    ax2 = axes[1]
    d = np.sqrt((all_pts[:, 0] - pivot[0])**2 + (all_pts[:, 1] - pivot[1])**2)
    residuals = d - arm_px
    ax2.hist(residuals, bins=60, color="steelblue", edgecolor="white")
    ax2.axvline(0, color="k", lw=1)
    ax2.set_xlabel("Radial residual (px)")
    ax2.set_ylabel("Count")
    ax2.set_title(f"Residuals  std={np.std(residuals):.2f}px  "
                  f"median={np.median(np.abs(residuals)):.2f}px")

    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"\nDiagnostic plot saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Phase 2 PIVOT + ARM_LENGTH_PX calibration.")
    p.add_argument("--videos", nargs="+", default=None,
                   help="Video filenames in phase2-motor-driven/videos/ "
                        "(default: all .mov files)")
    p.add_argument("--hsv-h", nargs=2, type=int,
                   default=[DEFAULT_H_MIN, DEFAULT_H_MAX],
                   metavar=("H_MIN", "H_MAX"))
    p.add_argument("--hsv-s", nargs=2, type=int,
                   default=[DEFAULT_S_MIN, DEFAULT_S_MAX],
                   metavar=("S_MIN", "S_MAX"))
    p.add_argument("--hsv-v", nargs=2, type=int,
                   default=[DEFAULT_V_MIN, DEFAULT_V_MAX],
                   metavar=("V_MIN", "V_MAX"))
    p.add_argument("--sample-every", type=int, default=SAMPLE_EVERY,
                   help=f"Use every Nth frame (default {SAMPLE_EVERY})")
    return p.parse_args()


def main():
    args = parse_args()

    hsv_params = (
        args.hsv_h[0], args.hsv_h[1],
        args.hsv_s[0], args.hsv_s[1],
        args.hsv_v[0], args.hsv_v[1],
    )
    print(f"HSV range: H=[{hsv_params[0]},{hsv_params[1]}] "
          f"S=[{hsv_params[2]},{hsv_params[3]}] "
          f"V=[{hsv_params[4]},{hsv_params[5]}]")

    # Resolve video list
    if args.videos:
        video_paths = [os.path.join(VIDEOS_DIR, v) for v in args.videos]
    else:
        video_paths = sorted(
            os.path.join(VIDEOS_DIR, f)
            for f in os.listdir(VIDEOS_DIR)
            if f.lower().endswith(".mov")
        )

    if not video_paths:
        sys.exit("No .mov files found.")

    print(f"\nCollecting green detections from {len(video_paths)} clip(s)...")
    per_video = []
    for vp in video_paths:
        pts = detect_green_positions(vp, hsv_params, args.sample_every)
        per_video.append((os.path.basename(vp), pts))

    all_pts = np.concatenate([p for _, p in per_video if len(p)], axis=0)
    if len(all_pts) < 10:
        sys.exit(f"Only {len(all_pts)} detections - check HSV range.")

    print(f"\nTotal detections: {len(all_pts)}")

    # Remove outliers: keep points within 3σ of mean distance from rough center
    cx0, cy0, r0 = algebraic_circle_fit(all_pts)
    d = np.sqrt((all_pts[:, 0] - cx0)**2 + (all_pts[:, 1] - cy0)**2)
    med, std = np.median(d), np.std(d)
    mask = np.abs(d - med) < 3 * std
    if mask.sum() < 10:
        sys.exit("Too few inliers after outlier removal.")
    inliers = all_pts[mask]
    n_outliers = len(all_pts) - mask.sum()
    print(f"Outlier removal: kept {mask.sum()} / {len(all_pts)} "
          f"({n_outliers} removed, 3-sigma gate)")

    # Geometric fit on inliers
    cx, cy, r, result = geometric_circle_fit(inliers, cx0, cy0, r0)
    residuals = np.abs(np.sqrt((inliers[:, 0] - cx)**2 +
                               (inliers[:, 1] - cy)**2) - r)

    print(f"\n{'='*50}")
    print(f"  PIVOT        = ({cx:.1f}, {cy:.1f})  px")
    print(f"  ARM_LENGTH_PX = {r:.1f}  px")
    print(f"  Fit residuals: std={np.std(residuals):.2f}px  "
          f"median={np.median(residuals):.2f}px  "
          f"p95={np.percentile(residuals, 95):.2f}px")
    print(f"{'='*50}")
    print(f"\nUpdate thresholds.py with:")
    print(f"  PIVOT         = ({int(round(cx))}, {int(round(cy))})")
    print(f"  ARM_LENGTH_PX = {int(round(r))}")

    diag_path = os.path.join(OUT_DIR, "pivot_calibration.png")
    save_diagnostic(inliers, (cx, cy), r, per_video, diag_path)


if __name__ == "__main__":
    main()
