"""
override_frame.py
------------------
Surgical CSV-row override for a single frame. Useful when
verify_tracking flags an isolated bad row and you'd rather edit that
one row directly than re-run the tracker.

Frame-local: only that row in tracking.csv changes, everything else
stays as bgr_tracker found it. Fast (no re-track) but does not
propagate to neighbours.

Usage
~~~~~
    python scripts/utils/override_frame.py --stem <config> --frame N
    chaos override <stem> --frame N

Keys
  marker     : G green   R red   LEFT-CLICK set position
  view       : Z zoom loupe   +/- magnification   M overlay (full/min/clean)
  commit     : ENTER write row to tracking.csv + re-verify   ESC/Q cancel
"""

import argparse
import csv
import datetime
import json
import math
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS

VERIFY_SCRIPT = os.path.join(REPO_ROOT, "scripts", "processing", "verify_tracking.py")

# Brief 10b: PIVOT and ARM_LENGTH_PX live in thresholds.py.
from thresholds import PIVOT, ARM_LENGTH_PX  # noqa: E402

FRAME_W = 1280
FRAME_H = 720
DISP_W  = 960
DISP_H  = 540
SCALE   = DISP_W / FRAME_W
WINDOW  = "Override Frame"

INSET_PX     = 240
ZOOM_FACTORS = [2, 3, 4, 6, 8]

OVERLAY_FULL, OVERLAY_MINIMAL, OVERLAY_CLEAN = 0, 1, 2
OVERLAY_LABELS = {OVERLAY_FULL: "FULL", OVERLAY_MINIMAL: "MIN",
                  OVERLAY_CLEAN: "CLEAN"}


# ─────────────────────────────────────────────
# REGISTRY HELPERS
# ─────────────────────────────────────────────

def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_entry_by_stem(reg, stem):
    for k, e in reg.items():
        if e.get("config_description") == stem:
            return k, e
    if stem in reg:
        return stem, reg[stem]
    return None, None


# ─────────────────────────────────────────────
# CSV HELPERS
# ─────────────────────────────────────────────

def load_csv(path):
    with open(path, "r", newline="") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)
        fieldnames = rdr.fieldnames
    return rows, fieldnames


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def compute_angle(p_from, p_to):
    """0° = straight down, +90 = right, -90 = left, ±180 = up. Mirrors
    the convention in ring_tracker.py."""
    dx = p_to[0] - p_from[0]
    dy = p_to[1] - p_from[1]
    return float(np.degrees(np.arctan2(dx, dy)))


# ─────────────────────────────────────────────
# UI STATE
# ─────────────────────────────────────────────

class State:
    def __init__(self, frame_idx, frame_img, current_green, current_red):
        self.frame_idx       = frame_idx
        self.frame_img       = frame_img       # raw cv2 frame
        self.cur_green       = current_green   # tuple or None
        self.cur_red         = current_red     # tuple or None
        # Overrides being built (None until the user clicks):
        self.new_green       = None
        self.new_red         = None
        self.mode            = "green"         # "green" or "red"
        self.cursor_disp     = None
        self.cursor_orig     = None
        self.zoom_on         = True
        self.zoom_idx        = 2               # 4× default
        self.overlay_level   = OVERLAY_FULL

    @property
    def zoom_factor(self):
        return ZOOM_FACTORS[self.zoom_idx]


def disp_to_frame(x, y):
    if x >= DISP_W or y >= DISP_H:
        return None
    return (max(0, min(FRAME_W - 1, int(round(x / SCALE)))),
            max(0, min(FRAME_H - 1, int(round(y / SCALE)))))


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

def render(state):
    raw     = state.frame_img.copy()
    overlay = state.frame_img.copy()

    if state.overlay_level == OVERLAY_FULL:
        cv2.circle(overlay, PIVOT, 8, (0, 215, 255), -1)
        cv2.circle(overlay, PIVOT, ARM_LENGTH_PX, (0, 200, 0), 1)
        # Current detection (existing CSV row) shown in pale colours.
        if state.cur_green is not None:
            cv2.line(overlay, PIVOT, state.cur_green, (0, 160, 0), 1)
            cv2.drawMarker(overlay, state.cur_green, (200, 200, 200),
                           cv2.MARKER_CROSS, 16, 2)
            cv2.circle(overlay, state.cur_green, ARM_LENGTH_PX,
                       (0, 0, 160), 1)
            if state.cur_red is not None:
                cv2.line(overlay, state.cur_green, state.cur_red,
                         (0, 0, 160), 1)
                cv2.drawMarker(overlay, state.cur_red, (200, 200, 200),
                               cv2.MARKER_CROSS, 16, 2)

    # Override positions in bright colours (stars).
    if state.new_green is not None:
        cv2.drawMarker(overlay, state.new_green, (0, 255, 0),
                       cv2.MARKER_STAR, 26, 3)
    if state.new_red is not None:
        cv2.drawMarker(overlay, state.new_red, (0, 0, 255),
                       cv2.MARKER_STAR, 26, 3)
    if state.new_green is not None and state.new_red is not None:
        cv2.line(overlay, state.new_green, state.new_red, (255, 255, 0), 1)

    cv2.putText(overlay, f"frame {state.frame_idx}",
                (10, FRAME_H - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    disp = cv2.resize(overlay, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)

    # ── Goal ribbon — top-center ───────────────────────────────────
    g_set = state.new_green is not None
    r_set = state.new_red is not None
    if not g_set:
        goal_text = "GOAL: click the actual GREEN marker"
    elif not r_set:
        goal_text = "GOAL: click the actual RED marker"
    else:
        goal_text = "READY: press ENTER to commit"
    progress = (f"GREEN: {'OK' if g_set else 'not set'}   "
                f"RED: {'OK' if r_set else 'not set'}")
    rib_x0, rib_y0 = 252, 4
    rib_x1, rib_y1 = DISP_W - 135, 50
    cv2.rectangle(disp, (rib_x0, rib_y0), (rib_x1, rib_y1),
                  (40, 40, 40), -1)
    cv2.rectangle(disp, (rib_x0, rib_y0), (rib_x1, rib_y1),
                  (220, 220, 220), 1)
    cv2.putText(disp, goal_text,
                (rib_x0 + 10, rib_y0 + 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 2)
    cv2.putText(disp, progress,
                (rib_x0 + 10, rib_y0 + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (200, 220, 200) if (g_set and r_set) else (220, 220, 220), 1)

    # Mode badge.
    mode_color = (0, 255, 0) if state.mode == "green" else (0, 0, 255)
    cv2.rectangle(disp, (DISP_W - 130, 5), (DISP_W - 5, 35), mode_color, -1)
    cv2.putText(disp, f"MODE: {state.mode.upper()}",
                (DISP_W - 122, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
    cv2.putText(disp, f"OVERLAY: {OVERLAY_LABELS[state.overlay_level]}",
                (DISP_W - 130, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

    # Status lines.
    g_str = (f"new green: ({state.new_green[0]},{state.new_green[1]})"
             if state.new_green else "new green: not set")
    r_str = (f"new red:   ({state.new_red[0]},{state.new_red[1]})"
             if state.new_red else "new red:   not set")
    cv2.putText(disp, g_str, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(disp, r_str, (10, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    if state.new_green is not None and state.new_red is not None:
        cv2.putText(disp, "ENTER to commit  |  ESC to cancel",
                    (10, DISP_H - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    # Zoom loupe.
    if state.zoom_on and state.cursor_orig is not None:
        zf = state.zoom_factor
        src = INSET_PX // zf
        cx, cy = state.cursor_orig
        x0 = max(0, min(FRAME_W - src, cx - src // 2))
        y0 = max(0, min(FRAME_H - src, cy - src // 2))
        crop = raw[y0:y0 + src, x0:x0 + src]
        inset = cv2.resize(crop, (INSET_PX, INSET_PX),
                           interpolation=cv2.INTER_NEAREST)
        mid = INSET_PX // 2
        cv2.drawMarker(inset, (mid, mid), (255, 255, 255),
                       cv2.MARKER_CROSS, 24, 1)
        cv2.rectangle(inset, (0, 0),
                      (INSET_PX - 1, INSET_PX - 1), (255, 255, 255), 2)
        cv2.putText(inset, f"ZOOM {zf}x  ({cx},{cy})",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1)
        disp[5:5 + INSET_PX, 5:5 + INSET_PX] = inset

    return disp


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Surgical CSV-row override for a single frame.")
    p.add_argument("--stem", required=True,
                   help="config_description, e.g. th1_p047_th2_m002.")
    p.add_argument("--frame", required=True, type=int,
                   help="frame index whose row to overwrite.")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the post-write verify_tracking re-run.")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="ω cap passed to the post-write verify "
                        "(default 2500 °/s).")
    return p.parse_args()


def main():
    args = parse_args()
    reg = load_registry()
    key, entry = find_entry_by_stem(reg, args.stem)
    if not entry:
        print(f"ERROR: no registry entry for stem '{args.stem}'.")
        return 1

    video_filename = entry.get("video_file")
    if not video_filename:
        print("ERROR: registry entry has no video_file.")
        return 1
    video_path = os.path.join(VIDEOS_DIR, video_filename)
    if not os.path.exists(video_path):
        print(f"ERROR: video missing on disk: {video_path}")
        return 1

    meas_dir = clip_dir(args.stem)
    csv_path = os.path.join(meas_dir, "tracking.csv")
    if not os.path.exists(csv_path):
        print(f"ERROR: tracking.csv missing: {csv_path}")
        print("       Run `chaos track <stem>` first.")
        return 1

    rows, fieldnames = load_csv(csv_path)
    if args.frame < 0 or args.frame >= len(rows):
        print(f"ERROR: frame {args.frame} out of range "
              f"(0..{len(rows) - 1}).")
        return 1
    target = rows[args.frame]

    # Read current detection from the row (so we can show it as
    # context).
    def _xy(r, gx_key, gy_key):
        try:
            x = int(float(r[gx_key])) if r.get(gx_key) else None
            y = int(float(r[gy_key])) if r.get(gy_key) else None
            return (x, y) if (x is not None and y is not None) else None
        except (TypeError, ValueError):
            return None
    cur_green = _xy(target, "x_green", "y_green")
    cur_red   = _xy(target, "x_red",   "y_red")

    # Open the video at the target frame.
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cv2 cannot open {video_path}")
        return 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame_img = cap.read()
    cap.release()
    if not ok:
        print(f"ERROR: could not read frame {args.frame}")
        return 1

    bar = "=" * 72
    print()
    print(bar)
    print(f"override_frame.py  —  {args.stem}  frame {args.frame}")
    print(bar)
    print("Why")
    print("  This frame in tracking.csv is suspect. Overwrite that one row")
    print("  with correct marker positions; nothing else in the CSV changes.")
    print()
    print("Steps")
    print("  1. LEFT-CLICK the GREEN marker (mode auto-switches to RED).")
    print("  2. LEFT-CLICK the RED marker.")
    print("  3. Press ENTER to commit.")
    print()
    print("Done when")
    print("  Both markers clicked (colored stars visible). ENTER → re-verify.")
    print()
    print("Keys")
    print("  marker     : G green   R red   LEFT-CLICK set position")
    print("  view       : Z zoom loupe   +/- magnification   "
          "M overlay (full/min/clean)")
    print("  commit     : ENTER write row + re-verify   ESC/Q cancel")
    print()
    print("Status")
    print(f"  video         : {video_path}")
    print(f"  current green : {cur_green}")
    print(f"  current red   : {cur_red}")
    print(f"  current row   : phase={target.get('phase')}   "
          f"dropout={target.get('dropout')}")
    print()

    state = State(args.frame, frame_img, cur_green, cur_red)
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def on_mouse(event, x, y, flags, _user):
        mapped = disp_to_frame(x, y)
        state.cursor_disp = (x, y) if mapped else None
        state.cursor_orig = mapped
        if event != cv2.EVENT_LBUTTONDOWN or mapped is None:
            return
        if state.mode == "green":
            state.new_green = mapped
            print(f"  set new_green = {mapped}")
            # Auto-switch to RED if RED isn't yet placed.
            if state.new_red is None:
                state.mode = "red"
                print("  → mode auto-switched to RED")
        else:
            state.new_red = mapped
            print(f"  set new_red   = {mapped}")
            if state.new_green is not None and state.new_red is not None:
                print("  → both set — press ENTER to commit")

    cv2.setMouseCallback(WINDOW, on_mouse)

    while True:
        cv2.imshow(WINDOW, render(state))
        k = cv2.waitKey(20) & 0xFF
        if k == 0xFF:
            continue
        if k == 27 or k in (ord("q"), ord("Q")):
            print("Cancelled. Tracking CSV unchanged.")
            cv2.destroyAllWindows()
            return 0
        if k in (13, 10):                                  # ENTER
            if state.new_green is None or state.new_red is None:
                print("  (set both green AND red before committing)")
                continue
            break
        if k in (ord("g"), ord("G")):
            state.mode = "green"
        elif k in (ord("r"), ord("R")):
            state.mode = "red"
        elif k in (ord("z"), ord("Z")):
            state.zoom_on = not state.zoom_on
        elif k in (ord("m"), ord("M")):
            state.overlay_level = (state.overlay_level + 1) % 3
        elif k in (ord("+"), ord("=")):
            state.zoom_idx = min(len(ZOOM_FACTORS) - 1, state.zoom_idx + 1)
        elif k in (ord("-"), ord("_")):
            state.zoom_idx = max(0, state.zoom_idx - 1)

    cv2.destroyAllWindows()

    # ── Compute angles + write the row ──────────────────────────────────
    th1 = compute_angle(PIVOT, state.new_green)
    th2 = compute_angle(state.new_green, state.new_red)
    target["x_green"]    = str(state.new_green[0])
    target["y_green"]    = str(state.new_green[1])
    target["x_red"]      = str(state.new_red[0])
    target["y_red"]      = str(state.new_red[1])
    target["theta1_deg"] = f"{th1:.3f}"
    target["theta2_deg"] = f"{th2:.3f}"
    target["dropout"]    = "0"

    # Backup CSV (skip if .bak already exists — interpolate_suspects may
    # have made one earlier).
    bak_path = csv_path + ".bak"
    if not os.path.exists(bak_path):
        shutil.copy2(csv_path, bak_path)
        print(f"Backup written: {os.path.relpath(bak_path, REPO_ROOT)}")

    write_csv(csv_path, rows, fieldnames)
    print(f"Wrote override into {os.path.relpath(csv_path, REPO_ROOT)}:")
    print(f"  frame {args.frame}: green=({target['x_green']},{target['y_green']}), "
          f"red=({target['x_red']},{target['y_red']}), "
          f"th1={th1:.2f}°, th2={th2:.2f}°, dropout=0")

    # Track this in the registry so analyses can see it was edited.
    reg = load_registry()
    key, entry = find_entry_by_stem(reg, args.stem)
    if entry is not None:
        n_overrides = int(entry.get("frames_overridden", 0)) + 1
        entry["frames_overridden"]    = n_overrides
        entry["last_override_frame"]  = args.frame
        entry["last_override_date"]   = datetime.datetime.now().strftime("%Y-%m-%d")
        with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)

    # Re-verify so the user sees whether the suspect cleared.
    if not args.no_verify:
        print()
        print("─" * 60)
        print("Re-running verify_tracking ...")
        print("─" * 60)
        rc = subprocess.run(
            [sys.executable, VERIFY_SCRIPT, "--stem", args.stem,
             "--omega-cap", str(args.omega_cap), "--no-plot"],
            cwd=REPO_ROOT,
        ).returncode
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
