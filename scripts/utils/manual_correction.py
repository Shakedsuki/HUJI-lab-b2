"""
manual_correction.py
---------------------
Streamlined human-in-the-loop fixup tool. One command, one window:

  1. Loads tracking.csv + verification.csv + any existing seeds.json
     for a measurement.
  2. Opens an interactive correction picker pre-positioned at the worst
     suspect frame (or frame 0 if there's no verification yet).
  3. Lets you click the correct green / red marker positions on
     individual frames. Each click creates / updates a "seed" — a
     manually-asserted ground truth at that frame.
  4. On `P` (process), saves seeds.json and re-runs ring_tracker with
     `--strict-physics --seeds-file seeds.json --from-frame=<earliest seed>`,
     then verify_tracking, then prints the verdict card.

The strict-physics flag enforces a hard angular gate at every fallback
stage: any candidate that would imply an unphysical jump becomes
dropout=1 (no fallback). Each seed re-anchors the predictor and reopens
a STRICT_POST_SEED_FRAMES window of strict mode after itself, so a
correction at frame 130 keeps the tracker on the right marker through
~frame 160 without you clicking every frame.

Usage
~~~~~
    python scripts/utils/manual_correction.py --stem th1_p047_th2_m002

    # After clicking corrections, the script can also run track-and-verify
    # automatically. To skip that and just save seeds.json:
    python scripts/utils/manual_correction.py --stem ... --save-only

Keys
  marker     : G green   R red   LEFT-CLICK set seed   X delete frame's seed
  navigate   : a/d ±1   A/D ±10   z/x ±100   n next suspect frame
  view       : Z zoom loupe   +/- magnification   M overlay (full/min/clean)
  commit     : P/ENTER save seeds + re-track + verify   S save seeds only   Q/ESC quit
"""

import argparse
import csv
import datetime
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
MEAS_DIR         = os.path.join(ROOT, "measurements")
DATA_DIR         = os.path.join(ROOT, "data")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")

TRACKER_SCRIPT = os.path.join(ROOT, "scripts", "processing", "ring_tracker.py")
VERIFY_SCRIPT  = os.path.join(ROOT, "scripts", "processing", "verify_tracking.py")
INTERP_SCRIPT  = os.path.join(ROOT, "scripts", "processing", "interpolate_suspects.py")
TRACK_ONE      = os.path.join(ROOT, "scripts", "utils",       "track_one.py")

# Reuse the metrics + verdict logic from track_one so manual_correction
# emits the same verdict card and auto-marks tracking_quality on PASS.
sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
import track_one as _track_one_mod  # noqa: E402

# Frame display dimensions (mirrors the picker in ring_tracker / hsv_tuner).
FRAME_W   = 1280
FRAME_H   = 720
DISP_W    = 960
DISP_H    = 540
SCALE     = DISP_W / FRAME_W
WINDOW    = "Manual Correction"

# Zoom loupe (same UX as hsv_tuner).
INSET_PX = 240
ZOOM_FACTORS = [2, 3, 4, 6, 8]

# Overlay levels.
OVERLAY_FULL, OVERLAY_MINIMAL, OVERLAY_CLEAN = 0, 1, 2
OVERLAY_LABELS = {OVERLAY_FULL: "FULL", OVERLAY_MINIMAL: "MIN",
                  OVERLAY_CLEAN: "CLEAN"}

# Pivot + arm geometry constants (mirror ring_tracker.py).
PIVOT          = (608, 355)
ARM_LENGTH_PX  = 188


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


def parse_args():
    p = argparse.ArgumentParser(
        description="Interactive manual correction tool with re-track + verify.")
    p.add_argument("--stem", required=True,
                   help="config_description (e.g. th1_p047_th2_m002).")
    p.add_argument("--save-only", action="store_true",
                   help="Save seeds.json and quit; skip the re-track step.")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="ω threshold for verify_tracking (default 2500 °/s).")
    return p.parse_args()


# ─────────────────────────────────────────────
# CSV LOADERS
# ─────────────────────────────────────────────

def load_tracking_csv(path):
    """Return list of dict rows; missing / unreadable file -> []."""
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


def load_verification_csv(path):
    """Return list of dict rows or [] when absent."""
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


def suspect_frames_from_verification(rows):
    """Return list of frame indices where suspect=1, sorted."""
    out = []
    for r in rows:
        try:
            if int(r.get("suspect") or 0) == 1:
                out.append(int(r["frame"]))
        except (ValueError, KeyError):
            continue
    return sorted(out)


def detection_at_frame(track_rows, frame_idx):
    """Return ((gx,gy) or None, (rx,ry) or None) from the existing CSV."""
    if not track_rows:
        return None, None
    if 0 <= frame_idx < len(track_rows):
        r = track_rows[frame_idx]
        try:
            gx = int(float(r["x_green"])) if r.get("x_green") else None
            gy = int(float(r["y_green"])) if r.get("y_green") else None
            rx = int(float(r["x_red"]))   if r.get("x_red")   else None
            ry = int(float(r["y_red"]))   if r.get("y_red")   else None
        except (TypeError, ValueError):
            return None, None
        green = (gx, gy) if gx is not None and gy is not None else None
        red   = (rx, ry) if rx is not None and ry is not None else None
        return green, red
    return None, None


# ─────────────────────────────────────────────
# SEEDS I/O
# ─────────────────────────────────────────────

def load_seeds(path):
    """Return (dict frame->seed, raw_meta or {})."""
    if not os.path.exists(path):
        return {}, {}
    with open(path, "r") as f:
        data = json.load(f)
    by_frame = {}
    for s in data.get("seeds", []):
        try:
            f = int(s["frame"])
        except (KeyError, TypeError, ValueError):
            continue
        by_frame[f] = {
            "green_xy": tuple(s["green_xy"]) if s.get("green_xy") else None,
            "red_xy":   tuple(s["red_xy"])   if s.get("red_xy")   else None,
        }
    return by_frame, data


def save_seeds(path, seeds_by_frame):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "seeds": [
            {
                "frame": f,
                "green_xy": list(s["green_xy"]) if s.get("green_xy") else None,
                "red_xy":   list(s["red_xy"])   if s.get("red_xy")   else None,
            }
            for f, s in sorted(seeds_by_frame.items())
        ],
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "notes":    "Created by manual_correction.py",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ─────────────────────────────────────────────
# UI STATE
# ─────────────────────────────────────────────

class State:
    def __init__(self, stem, video_path, meas_dir, total_frames, fps,
                 track_rows, susp_frames, seeds_by_frame):
        self.stem            = stem
        self.video_path      = video_path
        self.meas_dir        = meas_dir
        self.total_frames    = total_frames
        self.fps             = fps
        self.track_rows      = track_rows
        self.susp_frames     = susp_frames
        self.seeds           = dict(seeds_by_frame)   # {frame: {green_xy, red_xy}}
        self.dirty           = False
        # Picker state.
        self.frame_idx       = (susp_frames[0] if susp_frames else 0)
        self.mode            = "green"     # "green" or "red"
        self.last_idx        = -1
        self.cached_frame    = None
        self.cursor_disp     = None
        self.cursor_orig     = None
        # Loupe / overlay.
        self.zoom_on         = True
        self.zoom_idx        = 2           # 4x default
        self.overlay_level   = OVERLAY_FULL

    @property
    def zoom_factor(self):
        return ZOOM_FACTORS[self.zoom_idx]

    def get_or_init_seed(self):
        if self.frame_idx not in self.seeds:
            self.seeds[self.frame_idx] = {"green_xy": None, "red_xy": None}
        return self.seeds[self.frame_idx]


# ─────────────────────────────────────────────
# DISPLAY <-> FRAME COORD MAPPING
# ─────────────────────────────────────────────

def disp_to_frame(x, y):
    if x >= DISP_W or y >= DISP_H:
        return None
    return (max(0, min(FRAME_W - 1, int(round(x / SCALE)))),
            max(0, min(FRAME_H - 1, int(round(y / SCALE)))))


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

def render_frame(state, frame):
    """Build the display image for the current frame."""
    raw = frame.copy()
    overlay = frame.copy()

    # Existing detection from the tracking CSV (cyan = green marker
    # current detection, magenta = red marker current detection).
    cur_green, cur_red = detection_at_frame(state.track_rows, state.frame_idx)
    if state.overlay_level == OVERLAY_FULL:
        cv2.circle(overlay, PIVOT, 8, (0, 215, 255), -1)
        cv2.circle(overlay, PIVOT, ARM_LENGTH_PX, (0, 200, 0), 1)
        if cur_green is not None:
            cv2.line(overlay, PIVOT, cur_green, (0, 200, 0), 1)
            cv2.drawMarker(overlay, cur_green, (255, 200, 0),
                           cv2.MARKER_CROSS, 18, 2)
            cv2.circle(overlay, cur_green, ARM_LENGTH_PX, (0, 0, 200), 1)
            if cur_red is not None:
                cv2.line(overlay, cur_green, cur_red, (0, 0, 200), 1)
                cv2.drawMarker(overlay, cur_red, (255, 0, 200),
                               cv2.MARKER_CROSS, 18, 2)

    # Seeds at the current frame (bright stars).
    seed = state.seeds.get(state.frame_idx)
    if seed:
        if seed["green_xy"]:
            cv2.drawMarker(overlay, seed["green_xy"], (0, 255, 0),
                           cv2.MARKER_STAR, 26, 3)
        if seed["red_xy"]:
            cv2.drawMarker(overlay, seed["red_xy"], (0, 0, 255),
                           cv2.MARKER_STAR, 26, 3)

    # Bottom info strip.
    is_susp = state.frame_idx in state.susp_frames
    txt = (f"frame {state.frame_idx}/{state.total_frames - 1}   "
           f"t={state.frame_idx / state.fps:.3f}s   "
           f"{'SUSPECT' if is_susp else ''}")
    cv2.putText(overlay, txt, (10, FRAME_H - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Resize to display.
    disp = cv2.resize(overlay, (DISP_W, DISP_H), interpolation=cv2.INTER_AREA)

    # Mode + seed-count + dirty badge.
    mode_color = (0, 255, 0) if state.mode == "green" else (0, 0, 255)
    cv2.rectangle(disp, (DISP_W - 130, 5), (DISP_W - 5, 35), mode_color, -1)
    cv2.putText(disp, f"MODE: {state.mode.upper()}",
                (DISP_W - 122, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
    seed_summary = f"seeds: {len(state.seeds)}"
    if state.dirty:
        seed_summary += "*"
    cv2.putText(disp, seed_summary, (DISP_W - 130, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
    cv2.putText(disp, f"OVERLAY: {OVERLAY_LABELS[state.overlay_level]}",
                (DISP_W - 130, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    if seed and seed.get(state.mode + "_xy"):
        cv2.putText(disp,
                    f"seed @ ({seed[state.mode + '_xy'][0]}, "
                    f"{seed[state.mode + '_xy'][1]})",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

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
        cv2.putText(inset, f"ZOOM {zf}x  pixel ({cx},{cy})",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1)
        # Place at top-left of the display.
        disp[5:5 + INSET_PX, 5:5 + INSET_PX] = inset

    return disp


# ─────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────

def run_track_and_verify(stem, seeds_path, earliest_seed, omega_cap,
                         have_existing_csv):
    """
    Re-run ring_tracker with --strict-physics + --seeds-file, then
    verify_tracking. Returns the rc of verify (0 = ok).

    Three cases for --from-frame:
      * earliest_seed > 0 AND existing tracking.csv → pass --from-frame
        so rows 0..earliest_seed-1 are preserved verbatim and only
        frame earliest_seed onward gets re-tracked.
      * earliest_seed == 0  → no --from-frame; ring_tracker runs from
        scratch with seeds + strict-physics applied.
      * earliest_seed > 0 BUT no existing CSV → no --from-frame either;
        we'd have nothing to preserve. The whole clip gets re-tracked
        with strict-physics; the seed is honoured at its frame.
    """
    video_filename = None
    reg = load_registry()
    _, entry = find_entry_by_stem(reg, stem)
    if entry:
        video_filename = entry.get("video_file")
    if not video_filename:
        print("ERROR: no video_file in registry; aborting re-track.")
        return 1
    video_path = os.path.join(VIDEOS_DIR, video_filename)

    use_from_frame = (earliest_seed > 0 and have_existing_csv)

    print()
    print("─" * 70)
    if use_from_frame:
        print(f"Re-tracking {stem} from frame {earliest_seed} with "
              f"strict-physics (rows 0..{earliest_seed - 1} preserved)...")
    else:
        print(f"Tracking {stem} from scratch with strict-physics + seeds...")
    print("─" * 70)

    cmd = [sys.executable, TRACKER_SCRIPT, video_path,
           "--no-debug", "--force",
           "--seeds-file", seeds_path,
           "--strict-physics",
           "--skip-probe"]   # the user just verified by clicking — probe is moot
    if use_from_frame:
        cmd += ["--from-frame", str(earliest_seed)]

    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        print(f"ring_tracker exit {rc} — aborting before verify.")
        return rc

    # ── Verify (pre-interp) ─────────────────────────────────────────────
    print()
    print("─" * 70)
    print("Re-running verify_tracking ...")
    print("─" * 70)
    rc = subprocess.run(
        [sys.executable, VERIFY_SCRIPT, "--stem", stem,
         "--omega-cap", str(omega_cap), "--no-plot"],
        cwd=ROOT,
    ).returncode
    if rc != 0:
        print(f"verify_tracking exit {rc} — aborting before interpolation.")
        return rc

    meas_dir = os.path.join(MEAS_DIR, stem)
    metrics_pre = _track_one_mod.read_verification_metrics(meas_dir)
    n_pre = (metrics_pre or {}).get("n_suspect_hidden", 0)

    # ── Interpolate any residual hidden suspects (rare with strict
    # physics but boundary cases can still slip through) and re-verify.
    n_interp = 0
    if n_pre > 0:
        print()
        print("─" * 70)
        print(f"Found {n_pre} residual suspects — running interpolate_suspects ...")
        print("─" * 70)
        irc = subprocess.run(
            [sys.executable, INTERP_SCRIPT, "--stem", stem,
             "--omega-cap", str(omega_cap)],
            cwd=ROOT,
        ).returncode
        if irc != 0:
            print(f"interpolate_suspects exit {irc} — verdict will use pre-interp metrics.")
            metrics_post = metrics_pre
        else:
            # interpolate_suspects already re-ran verify internally; re-read.
            metrics_post = _track_one_mod.read_verification_metrics(meas_dir)
            reg_after = load_registry()
            _, e_after = find_entry_by_stem(reg_after, stem)
            n_interp = int((e_after or {}).get("suspect_frames_interpolated", 0))
    else:
        metrics_post = metrics_pre

    # ── Verdict card + maybe mark verified — same logic as track_one. ──
    n_post = (metrics_post or {}).get("n_suspect_hidden", 0)
    status, reasons = _track_one_mod.compute_verdict(metrics_post, n_post)
    reg = load_registry()
    key, entry = find_entry_by_stem(reg, stem)
    video_filename = (entry or {}).get("video_file", "")
    _track_one_mod.emit_card(
        stem, video_path, key, entry or {},
        status=status, reasons=reasons,
        metrics_pre=metrics_pre, metrics_post=metrics_post,
        n_interpolated=n_interp,
        hsv_kind=_track_one_mod.hsv_kind_for_video(video_filename),
        total_elapsed=0.0,   # we don't time-track manual_correction's whole flow
    )
    _track_one_mod.maybe_mark_verified(stem, status, reasons)
    return 0 if status != "FAIL" else 1


# ─────────────────────────────────────────────
# MAIN UI LOOP
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    reg = load_registry()
    key, entry = find_entry_by_stem(reg, args.stem)
    if not entry:
        print(f"ERROR: no registry entry for stem '{args.stem}'.")
        return 1

    video_filename = entry.get("video_file")
    if not video_filename:
        print(f"ERROR: registry entry has no video_file.")
        return 1
    video_path = os.path.join(VIDEOS_DIR, video_filename)
    if not os.path.exists(video_path):
        print(f"ERROR: video missing on disk: {video_path}")
        return 1

    meas_dir   = os.path.join(MEAS_DIR, args.stem)
    csv_path   = os.path.join(meas_dir, "tracking.csv")
    verif_path = os.path.join(meas_dir, "verification.csv")
    seeds_path = os.path.join(meas_dir, "seeds.json")

    track_rows = load_tracking_csv(csv_path)
    susp_rows  = load_verification_csv(verif_path)
    susp_frames = suspect_frames_from_verification(susp_rows)
    seeds_by_frame, _ = load_seeds(seeds_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: cv2 cannot open {video_path}")
        return 1
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 59.94

    print(f"manual_correction.py  —  {args.stem}")
    print(f"  video      : {video_path}")
    print(f"  meas       : {meas_dir}")
    print(f"  csv        : "
          f"{'(absent)' if not track_rows else f'{len(track_rows)} rows'}")
    print(f"  verify     : "
          f"{'(absent)' if not susp_rows else f'{len(susp_rows)} rows; {len(susp_frames)} suspects'}")
    print(f"  seeds      : {len(seeds_by_frame)} loaded")
    print()

    if not track_rows:
        print("Note: no tracking.csv exists for this clip yet.")
        print("  manual_correction is most effective AFTER an initial track")
        print("  (you can see where the tracker's gone wrong and fix only those")
        print("  frames). For a fresh clip, the standard flow is:")
        print(f"     python scripts/utils/track_one.py --stem {args.stem}")
        print("  Continuing here is fine if you want to seed predictor anchors")
        print("  before the first track — pressing P will run ring_tracker")
        print("  from scratch with --strict-physics + your seeds, opening the")
        print("  picker for init/release frames if the registry has none.")
        print()

    state = State(args.stem, video_path, meas_dir, total_frames, fps,
                  track_rows, susp_frames, seeds_by_frame)

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)

    def on_mouse(event, x, y, flags, _userdata):
        mapped = disp_to_frame(x, y)
        if mapped is None:
            state.cursor_disp = None
            state.cursor_orig = None
        else:
            state.cursor_disp = (x, y)
            state.cursor_orig = mapped
        if event != cv2.EVENT_LBUTTONDOWN or mapped is None:
            return
        seed = state.get_or_init_seed()
        seed[state.mode + "_xy"] = mapped
        state.dirty = True
        print(f"  set seed[frame {state.frame_idx}].{state.mode}_xy = {mapped}")

    cv2.setMouseCallback(WINDOW, on_mouse)

    print("Keys")
    print("  marker     : G green   R red   LEFT-CLICK set seed   "
          "X delete frame's seed")
    print("  navigate   : a/d ±1   A/D ±10   z/x ±100   n next suspect frame")
    print("  view       : Z zoom loupe   +/- magnification   "
          "M overlay (full/min/clean)")
    print("  commit     : P/ENTER save seeds + re-track + verify   "
          "S save seeds only   Q/ESC quit")
    print()

    while True:
        if state.frame_idx != state.last_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, state.frame_idx)
            ok, frame = cap.read()
            if not ok:
                state.frame_idx = max(0, state.frame_idx - 1)
                continue
            state.cached_frame = frame
            state.last_idx = state.frame_idx

        disp = render_frame(state, state.cached_frame)
        cv2.imshow(WINDOW, disp)
        k = cv2.waitKey(20) & 0xFF

        if k == 0xFF:
            continue
        if k == 27 or k in (ord("q"), ord("Q")):
            if state.dirty:
                ans = input("Unsaved seed changes. Save before quitting? [y/N]: ")
                if ans.strip().lower().startswith("y"):
                    save_seeds(seeds_path, state.seeds)
                    print(f"Saved {seeds_path}")
            break
        if k in (ord("g"), ord("G")):
            state.mode = "green"
            continue
        if k in (ord("r"), ord("R")):
            state.mode = "red"
            continue
        if k == ord("a"):
            state.frame_idx = max(0, state.frame_idx - 1)
        elif k == ord("d"):
            state.frame_idx = min(total_frames - 1, state.frame_idx + 1)
        elif k == ord("A"):
            state.frame_idx = max(0, state.frame_idx - 10)
        elif k == ord("D"):
            state.frame_idx = min(total_frames - 1, state.frame_idx + 10)
        elif k == ord("z"):
            state.frame_idx = max(0, state.frame_idx - 100)
        elif k == ord("x"):
            state.frame_idx = min(total_frames - 1, state.frame_idx + 100)
        elif k in (ord("n"), ord("N")):
            # Jump to next suspect frame after current.
            future = [s for s in state.susp_frames if s > state.frame_idx]
            if future:
                state.frame_idx = future[0]
            else:
                print("(no more suspect frames after current)")
        elif k in (ord("Z"),):
            state.zoom_on = not state.zoom_on
        elif k in (ord("M"), ord("m")):
            state.overlay_level = (state.overlay_level + 1) % 3
        elif k in (ord("+"), ord("=")):
            state.zoom_idx = min(len(ZOOM_FACTORS) - 1, state.zoom_idx + 1)
        elif k in (ord("-"), ord("_")):
            state.zoom_idx = max(0, state.zoom_idx - 1)
        elif k in (ord("X"),):
            if state.frame_idx in state.seeds:
                del state.seeds[state.frame_idx]
                state.dirty = True
                print(f"  deleted seed[frame {state.frame_idx}]")
        elif k in (ord("s"), ord("S")):
            save_seeds(seeds_path, state.seeds)
            state.dirty = False
            print(f"  saved {seeds_path}  ({len(state.seeds)} seeds)")
        elif k in (13, 10, ord("p"), ord("P")):
            # P / ENTER: save + retrack + verify.
            if not state.seeds:
                print("(no seeds set yet — nothing to do)")
                continue
            save_seeds(seeds_path, state.seeds)
            state.dirty = False
            print(f"\n  saved {seeds_path}  ({len(state.seeds)} seeds)")
            cv2.destroyWindow(WINDOW)
            earliest = min(state.seeds.keys())
            have_existing_csv = bool(state.track_rows)
            rc = run_track_and_verify(args.stem, seeds_path, earliest,
                                      args.omega_cap, have_existing_csv)
            print(f"\nrun_track_and_verify exit code: {rc}")
            break

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
