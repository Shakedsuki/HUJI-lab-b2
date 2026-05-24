"""
bgr_tracker.py
--------------
Phase 2 marker tracker: BGR colour thresholding + image moments,
wrapping Cohen's detection logic (archive/cohen_get_video_coords.py — preserved
verbatim as the regression reference inside
scripts/utils/capture_bgr_baseline.py) inside canonical pipeline I/O.

What it does
~~~~~~~~~~~~
For each frame of the input video:
  bbox    = 4·arm × 4·arm square centred on the pivot (reachable region)
  cropped = frame[bbox] AND inscribed disc mask
  green   = centroid from the first non-empty mask in GREEN_BGR_RANGES
            (strict box, then a motion-blur fallback)
  red     = centroid from the first non-empty mask in RED_BGR_RANGES,
            additionally ANDed with a green-proximity disk

Centroids returned by detect_markers_bgr() are already in ORIGINAL
frame coords (the bbox offset is added internally), so the canonical
per-batch PIVOT / ARM_LENGTH_PX from thresholds.get_pivot_arm() apply
unchanged to downstream analysis. Angles are computed with the
convention 0° = straight down, +90 = right.

What it does NOT do (by design)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  * No HSV. No motion mask. No ring/arc filters. No CSRT seeds.
  * No init/release frame distinction — Phase 2 is continuously driven,
    every frame is tagged 'free_swing'.
  * No debug.mp4 — combined.mp4 from the analysis layer covers post-hoc
    visualization.
  * No HSV adequacy probe — the BGR colour ranges are fixed in
    thresholds.py and not tuned per clip.

I/O
~~~
Reads:  experiments/<phase>/videos/<video_file>
        experiments/<phase>/data/experiments.json
Writes: experiments/<phase>/measurements/<stem>/tracking.csv
            schema: frame, time_s, phase, x_green, y_green, x_red, y_red,
                    theta1_deg, theta2_deg, dropout
                    (matches ring_tracker.py — verify_tracking and the
                     rest of the pipeline consume this unchanged)
        experiments/<phase>/data/experiments.json
            entry updated: tracker='bgr', dropout_rate_pct, n_free_frames,
            theta/omega_release, energy_proxy, duration_s, ...
    (<phase> = week6-pendulum-motor-driven by default; see scripts/utils/paths.py)

Usage
~~~~~
    # default invocation (track_one passes the positional path):
    python scripts/processing/bgr_tracker.py experiments/week6-pendulum-motor-driven/videos/3.2V_0.9Hz.mov --force

    # Or by stem, when called directly:
    python scripts/processing/bgr_tracker.py --stem 4V_1.9Hz --force

The --no-debug flag is accepted as a no-op for compatibility with the
track_one.py invocation chain.
"""

import argparse
import csv
import json
import math
import os
import sys

import cv2
import numpy as np
from scipy.ndimage import median_filter
from tqdm import tqdm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_UTILS_DIR  = os.path.abspath(os.path.join(_SCRIPT_DIR, os.pardir, "utils"))
sys.path.insert(0, _UTILS_DIR)
from paths import VIDEOS_DIR, MEAS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
from thresholds import (  # noqa: E402
    PIVOT,
    ARM_LENGTH_PX,
    ARM_LENGTH_CM,
    GREEN_BGR_RANGES,
    RED_BGR_RANGES,
    get_pivot_arm,
    DROPOUT_FAIL_PCT,
)

SCALE_CM_PER_PX  = ARM_LENGTH_CM / ARM_LENGTH_PX
FPS_DEFAULT      = 59.94

# Red-search disk slack (px). The red marker is bolted to the rigid
# lower arm, so it must lie within arm_length_px of green plus this
# slack for centroid noise and per-batch arm-length variation. The
# actual disk radius squared is computed per-clip in main() using the
# resolved arm length, since different rig batches have different
# arm lengths in pixels.
_RED_SEARCH_SLACK_PX = 30

# Pre-build numpy arrays once at module load (cv2.inRange wants ndarray).
_GREEN_RANGES_NP = [(np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
                    for lo, hi in GREEN_BGR_RANGES]
_RED_RANGES_NP = [(np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
                  for lo, hi in RED_BGR_RANGES]


# ─────────────────────────────────────────────
# ANGLE CONVENTION (matches ring_tracker.compute_angle)
# ─────────────────────────────────────────────

def compute_angle(p_from, p_to):
    """0° = straight down; +90 = right, -90 = left, ±180 = up."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return float(np.degrees(np.arctan2(dx, dy)))


def angular_diff(a, b):
    """Signed (a − b) wrapped to [-180, 180]."""
    return ((a - b + 180.0) % 360.0) - 180.0


# ─────────────────────────────────────────────
# DETECTION CORE (mirrors get_video_coords.py per-frame body)
# ─────────────────────────────────────────────

def reachable_bbox(pivot, arm_length_px, frame_shape):
    """Return (x0, y0, x1, y1) tight bbox around the reachable disc,
    clipped to the frame extents. Used by tracker and overlay so the
    same cropped region drives both detection and visualization.
    """
    px, py = pivot
    reach = 2 * arm_length_px
    h, w = frame_shape[:2]
    return (
        max(0, px - reach),
        max(0, py - reach),
        min(w, px + reach),
        min(h, py + reach),
    )


def _project_to_circle(px, py, qx, qy, r):
    """Project point (qx, qy) onto the circle of radius r centred at
    (px, py). Returns (qx_proj, qy_proj). The projection preserves the
    direction (px,py)->(qx,qy) — it only enforces |Q' - P| == r.

    For an exactly-rigid arm the projected point IS the physically
    correct marker position regardless of how the BGR centroid's
    radial component drifted.
    """
    dx = qx - px
    dy = qy - py
    d  = math.sqrt(dx * dx + dy * dy)
    if d == 0:
        return qx, qy
    scale = r / d
    return px + dx * scale, py + dy * scale


def detect_markers_bgr(frame, pivot, arm_length_px, red_search_r_sq):
    """Return (gx, gy, rx, ry) in ORIGINAL-frame coords for one frame.

    Centroids are sub-pixel floats and have been projected onto their
    rigid-arm constraint circles (green onto pivot circle, red onto
    the projected-green circle, both of radius arm_length_px). Any
    component is None when its mask had no pixels.

    Cropping strategy
    ~~~~~~~~~~~~~~~~~
    The frame is hard-cropped to a tight square bbox of size 4·arm×4·arm
    centred on the pivot — the reachable region for any pendulum marker.
    A disc mask inscribed in that bbox knocks out the four corner
    triangles. Together these reduce mask area by ~22 % vs the old
    X-only crop and physically guarantee that no off-rig pixel
    (curtain, whiteboard, red prop) can contribute to a centroid.

    Red detection then ANDs in the green-proximity disk (radius
    arm_length_px+30 around green) when green is found, since the red
    marker is bolted to the rigid lower arm.

    Precision & rigidity
    ~~~~~~~~~~~~~~~~~~~~
    `cv2.moments` already returns sub-pixel centroids via
    m10/m00, m01/m00; we keep them as floats rather than truncating
    to int. Storing the full precision through the CSV cuts the at-rest
    angular noise floor by ~18× (eliminating the ±1 px integer-grid
    quantization).

    The two constraint-circle projections (green→pivot, red→green) are
    radial: they preserve direction, so θ₁ and θ₂ are unchanged by them.
    What they DO change is |G−P| and |R−G|, which are now exactly
    arm_length_px every frame. This corrects red-on-rod misdetections
    (where the detected centroid sits inside arm 2 rather than at the
    marker tip) by pushing the position outward along the correct
    direction.
    """
    bx0, by0, bx1, by1 = reachable_bbox(pivot, arm_length_px, frame.shape)
    cropped = frame[by0:by1, bx0:bx1, :]
    h, w = cropped.shape[:2]
    yy, xx = np.ogrid[:h, :w]

    # Disc mask inscribed in the bbox (pivot is at (px-bx0, py-by0)
    # in cropped coords).
    pcx = pivot[0] - bx0
    pcy = pivot[1] - by0
    reach_r_sq = (2 * arm_length_px) ** 2
    reach = ((xx - pcx)**2 + (yy - pcy)**2 <= reach_r_sq).astype(np.uint8) * 255

    gx_c = gy_c = None
    for lo_np, hi_np in _GREEN_RANGES_NP:
        green_mask = cv2.inRange(cropped, lo_np, hi_np)
        green_mask = cv2.bitwise_and(green_mask, reach)
        M_g = cv2.moments(green_mask)
        if M_g['m00'] > 0:
            gx_c = M_g['m10'] / M_g['m00']
            gy_c = M_g['m01'] / M_g['m00']
            break

    disk = None
    if gx_c is not None:
        disk = ((xx - gx_c)**2 + (yy - gy_c)**2 <= red_search_r_sq).astype(np.uint8) * 255

    rx_c = ry_c = None
    for lo_np, hi_np in _RED_RANGES_NP:
        mask = cv2.inRange(cropped, lo_np, hi_np)
        mask = cv2.bitwise_and(mask, reach)
        if disk is not None:
            mask = cv2.bitwise_and(mask, disk)
        M_r = cv2.moments(mask)
        if M_r['m00'] > 0:
            rx_c = M_r['m10'] / M_r['m00']
            ry_c = M_r['m01'] / M_r['m00']
            break

    gx = gx_c + bx0 if gx_c is not None else None
    gy = gy_c + by0 if gy_c is not None else None
    rx = rx_c + bx0 if rx_c is not None else None
    ry = ry_c + by0 if ry_c is not None else None

    # Project onto the rigid-arm constraint circles. Direction is
    # preserved (angles unchanged), only |G−P| and |R−G| are pinned to
    # arm_length_px.
    if gx is not None:
        gx, gy = _project_to_circle(pivot[0], pivot[1], gx, gy, arm_length_px)
    if rx is not None and gx is not None:
        rx, ry = _project_to_circle(gx, gy, rx, ry, arm_length_px)

    return gx, gy, rx, ry


# ─────────────────────────────────────────────
# REGISTRY I/O
# ─────────────────────────────────────────────

def load_registry():
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(reg):
    os.makedirs(os.path.dirname(EXPERIMENTS), exist_ok=True)
    with open(EXPERIMENTS, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def find_entry(reg, *, stem=None, video_filename=None):
    """Locate the registry (key, entry) for a given stem or video filename.
    Returns (None, None) on miss."""
    if stem:
        for k, e in reg.items():
            if e.get("config_description") == stem:
                return k, e
        if stem in reg:
            return stem, reg[stem]
    if video_filename:
        for k, e in reg.items():
            if e.get("video_file") == video_filename:
                return k, e
    return None, None


def resolve_inputs(args):
    """Return (video_path, stem, key, entry).

    Priority:
      * --stem given      → look up registry by config_description, get video
      * positional video  → derive filename, look up registry by video_file
                             (or fall back to filename stem)
    """
    reg = load_registry()

    if args.stem:
        key, entry = find_entry(reg, stem=args.stem)
        if entry is None:
            from rich.console import Console as _C
            _C().print(f"[red]ERROR:[/] no registry entry with config_description '{args.stem}'")
            sys.exit(2)
        video_file = entry.get("video_file") or f"{args.stem}.mov"
        video_path = os.path.join(VIDEOS_DIR, video_file)
        return video_path, args.stem, key, entry, reg

    if args.video:
        video_path = args.video
        if not os.path.isabs(video_path):
            video_path = os.path.join(REPO_ROOT, video_path)
        if not os.path.exists(video_path):
            from rich.console import Console as _C
            _C().print(f"[red]ERROR:[/] video not found: {video_path}")
            sys.exit(2)
        video_filename = os.path.basename(video_path)
        key, entry = find_entry(reg, video_filename=video_filename)
        if entry is None:
            stem = os.path.splitext(video_filename)[0]
            from rich.console import Console as _C
            _C().print(f"[yellow]WARN:[/] video '{video_filename}' has no registry entry; "
                       f"will create one keyed '{stem}'.")
            key = stem
            entry = {}
        stem = entry.get("config_description") or os.path.splitext(video_filename)[0]
        return video_path, stem, key, entry, reg

    from rich.console import Console as _C
    _C().print("[red]ERROR:[/] provide --stem or a positional video path.")
    sys.exit(2)


def update_registry_entry(reg, key, entry, *, video_file, stem,
                          n_total, n_drop, dropout_pct, duration_s,
                          th1_rel, th2_rel, om1_rel, om2_rel,
                          pivot, arm_length_px):
    # Driven-mode registry schema: no init/release/tag frames (always 0),
    # no ROIs (HSV-only concept), no energy_proxy (release-based and
    # vacuous when the motor pumps energy in continuously). The
    # theta*_initial / omega*_initial fields capture frame-0 markers
    # state — meaningful as initial conditions even though no "release"
    # event exists. pivot/arm_length_px are passed in so each clip
    # records the actual per-batch calibration used during tracking.
    base = dict(entry) if entry else {}
    base.update({
        "video_file":         video_file,
        "tracker":            "bgr",
        "arm_length_px":      arm_length_px,
        "arm_length_cm":      ARM_LENGTH_CM,
        "pivot_px":           list(pivot),
        "scale_cm_per_px":    round(ARM_LENGTH_CM / arm_length_px, 4),
        "theta1_initial":     round(th1_rel, 4),
        "theta2_initial":     round(th2_rel, 4),
        "omega1_initial":     round(om1_rel, 4),
        "omega2_initial":     round(om2_rel, 4),
        "duration_s":         round(duration_s, 3),
        "n_frames":           n_total,
        "dropout_rate_pct":   round(dropout_pct, 2),
        "csv_file":           "tracking.csv",
        "measurements_dir":   f"measurements/{stem}",
        "config_description": stem,
        "tracking_quality":   base.get("tracking_quality", "good"),
        "notes":              base.get("notes", ""),
    })
    # Strip legacy free-swing fields from any pre-existing entry we're
    # updating, so the registry doesn't accumulate stale schema cruft.
    for stale_key in ("init_frame", "release_frame", "t0_offset_s",
                      "tag_frame", "green_roi", "red_roi",
                      "ring_tolerance", "energy_proxy",
                      "theta1_release", "theta2_release",
                      "omega1_release", "omega2_release",
                      "n_free_frames", "green_click_px", "red_click_px",
                      "suspect_frames_interpolated",
                      "interpolation_date"):
        base.pop(stale_key, None)
    reg[key] = base


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    ap = argparse.ArgumentParser(
        description="Phase 2 BGR marker tracker (wraps Cohen's "
                    "get_video_coords detection in pipeline I/O).")
    ap.add_argument("video", nargs="?",
                    help="Path to video file (absolute or repo-relative). "
                         "If omitted, use --stem.")
    ap.add_argument("--stem",
                    help="config_description (registry key) for the clip.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing tracking.csv.")
    ap.add_argument("--no-debug", action="store_true",
                    help="(no-op) bgr_tracker produces no debug video.")
    return ap.parse_args()


def main():
    args = parse_args()
    video_path, stem, key, entry, reg = resolve_inputs(args)

    # Per-batch rig calibration (3.2V sweep was recorded after the rig
    # was repositioned; see thresholds.get_pivot_arm).
    pivot, arm_length_px = get_pivot_arm(stem)
    red_search_r_sq = (arm_length_px + _RED_SEARCH_SLACK_PX) ** 2

    out_dir = clip_dir(stem)
    os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, "tracking.csv")

    from rich.console import Console
    from rich.table import Table
    console = Console()

    if os.path.exists(out_csv) and not args.force:
        console.print(f"[red]ERROR:[/] {os.path.relpath(out_csv, REPO_ROOT)} exists. Pass --force to overwrite.")
        return 1

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        console.print(f"[red]ERROR:[/] cannot open {video_path}")
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_DEFAULT
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dt = 1.0 / fps

    t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t.add_column(style="dim", min_width=10)
    t.add_column(style="white")
    t.add_row("stem",    stem)
    t.add_row("video",   f"[dim]{os.path.relpath(video_path, REPO_ROOT)}[/]")
    t.add_row("out",     f"[dim]{os.path.relpath(out_csv, REPO_ROOT)}[/]")
    t.add_row("pivot",   str(pivot))
    t.add_row("arm_L",   f"{arm_length_px}px / {ARM_LENGTH_CM}cm")
    t.add_row("bbox",    f"4·arm = {4*arm_length_px}px square around pivot")
    t.add_row("fps",     f"{fps:.3f}   frames={total_frames}   dt={dt:.5f}s")
    console.print(t)

    times     = []
    xg_raw    = []
    yg_raw    = []
    xr_raw    = []
    yr_raw    = []

    with tqdm(total=total_frames, desc="bgr_tracker") as pbar:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            pbar.update(1)

            times.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            gx, gy, rx, ry = detect_markers_bgr(
                frame, pivot, arm_length_px, red_search_r_sq)
            xg_raw.append(gx if gx is not None else np.nan)
            yg_raw.append(gy if gy is not None else np.nan)
            xr_raw.append(rx if rx is not None else np.nan)
            yr_raw.append(ry if ry is not None else np.nan)

    cap.release()

    n_total = len(times)
    if n_total == 0:
        console.print("[red]ERROR:[/] no frames read from video.")
        return 2

    # ── Post-loop position smoothing ──────────────────────────────────
    # Light 5-frame median filter on each (x, y) position series. The
    # filter bandwidth (~12 Hz at 60 fps) is well above the pendulum's
    # response frequencies (drive 0.9 Hz, harmonics ≤ ~5 Hz) so real
    # motion is essentially unattenuated, while broadband
    # moment-centroid noise above ~5 Hz is suppressed. NaN-aware:
    # dropouts are interpolated for filter input then masked back at
    # the end.
    xg_arr = np.array(xg_raw, dtype=float)
    yg_arr = np.array(yg_raw, dtype=float)
    xr_arr = np.array(xr_raw, dtype=float)
    yr_arr = np.array(yr_raw, dtype=float)

    def _smooth(arr, win=5):
        nans = np.isnan(arr)
        if nans.any():
            idx = np.arange(len(arr))
            arr_filled = arr.copy()
            arr_filled[nans] = np.interp(idx[nans], idx[~nans], arr[~nans])
        else:
            arr_filled = arr
        out = median_filter(arr_filled, size=win, mode='nearest')
        out[nans] = np.nan
        return out

    xg_s = _smooth(xg_arr)
    yg_s = _smooth(yg_arr)
    xr_s = _smooth(xr_arr)
    yr_s = _smooth(yr_arr)

    # Re-project the smoothed positions onto the rigid-arm constraint
    # circles. The median filter knocks the smoothed point slightly off
    # the circle (median of points on a circle isn't on the circle);
    # this restores the rigid-arm constraint. Direction is preserved,
    # so smoothing is effectively applied to the angular coordinate.
    for i in range(n_total):
        if not np.isnan(xg_s[i]):
            xg_s[i], yg_s[i] = _project_to_circle(
                pivot[0], pivot[1], xg_s[i], yg_s[i], arm_length_px)
        if not np.isnan(xr_s[i]) and not np.isnan(xg_s[i]):
            xr_s[i], yr_s[i] = _project_to_circle(
                xg_s[i], yg_s[i], xr_s[i], yr_s[i], arm_length_px)

    # Build the row records from smoothed/re-projected positions.
    rows = []
    n_drop = 0
    for i in range(n_total):
        green_ok = not np.isnan(xg_s[i])
        red_ok   = not np.isnan(xr_s[i])
        th1 = compute_angle(pivot, (xg_s[i], yg_s[i])) if green_ok else None
        th2 = (compute_angle((xg_s[i], yg_s[i]), (xr_s[i], yr_s[i]))
               if (green_ok and red_ok) else None)
        dropout = 0 if (green_ok and red_ok) else 1
        if dropout:
            n_drop += 1
        rows.append({
            "frame":      i,
            "time_s":     round(times[i], 5),
            "phase":      "driven",
            "x_green":    "" if not green_ok else f"{xg_s[i]:.3f}",
            "y_green":    "" if not green_ok else f"{yg_s[i]:.3f}",
            "x_red":      "" if not red_ok   else f"{xr_s[i]:.3f}",
            "y_red":      "" if not red_ok   else f"{yr_s[i]:.3f}",
            "theta1_deg": "" if th1 is None  else f"{th1:.3f}",
            "theta2_deg": "" if th2 is None  else f"{th2:.3f}",
            "dropout":    dropout,
        })

    # Write tracking.csv (canonical schema).
    fieldnames = ["frame", "time_s", "phase",
                  "x_green", "y_green", "x_red", "y_red",
                  "theta1_deg", "theta2_deg", "dropout"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    dropout_pct = 100.0 * n_drop / n_total
    duration_s  = n_total / fps

    # ── Initial-frame physics for registry. ─────────────────────────────
    # Phase 2 has no holding/release distinction; "release" = first
    # usable (non-dropout) frame. ω at "release" is the angular velocity
    # from that frame to the next clean one.
    r0 = next((r for r in rows if r["dropout"] == 0), None)
    if r0 is None:
        console.print("[red]ERROR:[/] every frame is a dropout — refusing to update registry.")
        return 3
    th1_rel = float(r0["theta1_deg"])
    th2_rel = float(r0["theta2_deg"])

    om1_rel = om2_rel = 0.0
    i0 = r0["frame"]
    for r in rows[i0 + 1:]:
        if r["dropout"] == 0:
            dt_pair = (r["time_s"] - r0["time_s"]) or dt
            om1_rel = angular_diff(float(r["theta1_deg"]), th1_rel) / dt_pair
            om2_rel = angular_diff(float(r["theta2_deg"]), th2_rel) / dt_pair
            break

    update_registry_entry(
        reg, key, entry,
        video_file=os.path.basename(video_path),
        stem=stem,
        n_total=n_total, n_drop=n_drop, dropout_pct=dropout_pct,
        duration_s=duration_s,
        th1_rel=th1_rel, th2_rel=th2_rel,
        om1_rel=om1_rel, om2_rel=om2_rel,
        pivot=pivot, arm_length_px=arm_length_px,
    )
    save_registry(reg)

    from render import _make_dropout_bar
    drop_color = "green" if dropout_pct <= DROPOUT_FAIL_PCT else "red"
    bar = _make_dropout_bar(dropout_pct)
    console.print(
        f"  [{drop_color}]{n_total} rows[/]  "
        f"dropout [{drop_color}]{dropout_pct:.2f}%[/] ({n_drop} frames)  {bar}"
    )
    console.print(f"  [dim]registry → {os.path.relpath(EXPERIMENTS, REPO_ROOT)}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
