"""
video_tagger.py
----------------
Interactive tool to tag each video with its initial conditions (theta1, theta2)
and rename it accordingly.

Workflow for each video:
  1. Opens a frame from the video — navigate to see the starting position
  2. You type theta1, theta2 (intended release angles in degrees, integers)
  3. You specify the repeat number (1 = first recording at this IC)
  4. File is renamed:  th1_p042_th2_p002_r1.mov
  5. experiments.json updated with new filename + config_description

Naming convention:
  th1_p042_th2_p002_r1.mov
  th1_m045_th2_p090_r2.mov
    p = positive, m = negative, zero-padded to 3 digits, r = repeat index

Skipped/already-tagged videos are shown but you can press S to skip.
Press Q at any time to quit and resume later.

Usage:
  python scripts/video_tagger.py
"""

import cv2
import os
import json
import sys
import shutil

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
EXPERIMENTS_FILE = os.path.join(ROOT, r"data\experiments.json")

# Videos to skip (not pendulum experiments)
SKIP_FILES = {
    "long_recording.mov",
    "DSC_0136_trimmed.mov",
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def load_registry():
    if os.path.exists(EXPERIMENTS_FILE):
        with open(EXPERIMENTS_FILE) as f:
            return json.load(f)
    return {}


def save_registry(reg):
    with open(EXPERIMENTS_FILE, 'w') as f:
        json.dump(reg, f, indent=2)


def angle_to_tag(deg):
    """Convert integer angle to tag string: +42 -> 'p042', -45 -> 'm045'"""
    sign = 'p' if deg >= 0 else 'm'
    return f"{sign}{abs(deg):03d}"


def make_label(th1, th2, repeat):
    """Build canonical label: 'th1_p042_th2_p002_r1'"""
    return f"th1_{angle_to_tag(th1)}_th2_{angle_to_tag(th2)}_r{repeat}"


def new_filename(label, ext=".mov"):
    return label + ext


def get_untagged_videos(reg):
    """Return list of .mov files that don't yet have a config_description."""
    all_movs = sorted([
        f for f in os.listdir(VIDEOS_DIR)
        if f.endswith('.mov') and f not in SKIP_FILES
    ])
    untagged = []
    tagged   = []
    for f in all_movs:
        stem = os.path.splitext(f)[0]
        entry = reg.get(stem) or reg.get(f)  # handle both key styles
        if entry and entry.get("config_description"):
            tagged.append(f)
        else:
            untagged.append(f)
    return untagged, tagged


def show_frame(video_path, start_frame=50):
    """
    Interactive frame viewer. Returns the frame index the user confirmed,
    or None if they skipped/quit.

    Controls:
      A / LEFT  : -1 frame
      D / RIGHT : +1 frame
      U         : -50 frames
      I         : +50 frames
      ENTER     : confirm this frame
      S         : skip this video
      Q / ESC   : quit tagger
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  ERROR: cannot open {video_path}")
        return None, 'error'

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps   = cap.get(cv2.CAP_PROP_FPS)
    idx   = min(start_frame, total - 1)

    WIN = "Video Tagger  |  A/D=+-1  U/I=+-50  ENTER=confirm  S=skip  Q=quit"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1280, 720)

    action = 'confirm'

    while True:
        idx = max(0, min(idx, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            idx = max(0, idx - 1)
            continue

        # Overlay info
        info = frame.copy()
        cv2.putText(info, f"frame {idx}/{total}  t={idx/fps:.2f}s",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(info, os.path.basename(video_path),
                    (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (200, 200, 100), 1, cv2.LINE_AA)
        cv2.putText(info, "ENTER=tag  S=skip  Q=quit",
                    (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (150, 255, 150), 1, cv2.LINE_AA)

        cv2.imshow(WIN, info)
        key = cv2.waitKey(30) & 0xFF

        if key in (13, 10):                  # ENTER
            action = 'confirm'; break
        elif key in (ord('q'), 27):          # Q / ESC
            action = 'quit'; break
        elif key == ord('s'):                # S = skip
            action = 'skip'; break
        elif key in (ord('d'), 83, 3):       # D / RIGHT
            idx += 1
        elif key in (ord('a'), 81, 2):       # A / LEFT
            idx -= 1
        elif key == ord('i'):                # I = +50
            idx += 50
        elif key == ord('u'):                # U = -50
            idx -= 50

    cap.release()
    cv2.destroyWindow(WIN)
    return idx, action


def ask_angles():
    """Prompt user for theta1, theta2, repeat. Returns (th1, th2, repeat) or None."""
    print()
    try:
        th1 = int(input("  theta1 (degrees, integer, e.g. 42 or -45): ").strip())
        th2 = int(input("  theta2 (degrees, integer, e.g.  2 or  90): ").strip())
        rep = input("  repeat number [default 1]: ").strip()
        repeat = int(rep) if rep else 1
        return th1, th2, repeat
    except (ValueError, EOFError):
        print("  Invalid input — skipping this video.")
        return None


def rename_and_update(old_path, new_path, old_stem, new_stem,
                      th1, th2, repeat, label, reg):
    """Rename file and update registry."""

    # ── Rename file ──
    if old_path != new_path:
        if os.path.exists(new_path):
            print(f"  WARNING: {new_path} already exists — not renaming")
        else:
            os.rename(old_path, new_path)
            print(f"  Renamed: {os.path.basename(old_path)}")
            print(f"       ->  {os.path.basename(new_path)}")
    else:
        print(f"  File already has correct name: {os.path.basename(new_path)}")

    # ── Update registry ──
    # Move existing entry to new key if it exists under old key
    existing = reg.pop(old_stem, reg.pop(os.path.splitext(os.path.basename(old_path))[0], None))

    entry = existing or {}
    entry["video_file"]         = os.path.basename(new_path)
    entry["config_description"] = label
    entry["video_label"]        = label
    entry["theta1_nominal"]     = th1    # intended angle (integer, set by experimenter)
    entry["theta2_nominal"]     = th2    # distinct from theta1_release (measured by tracker)
    entry["repeat"]             = repeat

    # Update csv_file reference if it exists
    if "csv_file" in entry:
        old_csv = entry["csv_file"]
        new_csv = old_csv.replace(old_stem, new_stem) if old_stem in old_csv else old_csv
        entry["csv_file"] = new_csv
        # Rename CSV file too if it exists
        old_csv_path = os.path.join(ROOT, "data", old_csv)
        new_csv_path = os.path.join(ROOT, "data", new_csv)
        if old_csv != new_csv and os.path.exists(old_csv_path):
            os.rename(old_csv_path, new_csv_path)
            print(f"  CSV renamed: {old_csv} -> {new_csv}")

    reg[new_stem] = entry
    return reg


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Double Pendulum Video Tagger")
    print("  Tags initial conditions and renames video files")
    print("=" * 60)

    reg = load_registry()
    untagged, tagged = get_untagged_videos(reg)

    print(f"\n  Already tagged : {len(tagged)}")
    print(f"  To tag         : {len(untagged)}")

    if not untagged:
        print("\n  All videos are tagged!")
        return

    print("\n  Already tagged videos:")
    for f in tagged:
        stem  = os.path.splitext(f)[0]
        entry = reg.get(stem, {})
        print(f"    {f:40s}  {entry.get('config_description','')}")

    print(f"\n  Starting tagging session ({len(untagged)} remaining)...")
    print("  Navigate to a frame that shows the STARTING POSITION clearly.")
    print("  Then press ENTER and type the angles you set.\n")

    for i, filename in enumerate(untagged):
        video_path = os.path.join(VIDEOS_DIR, filename)
        stem       = os.path.splitext(filename)[0]

        print(f"\n[{i+1}/{len(untagged)}]  {filename}")
        print("-" * 50)

        # Show frame viewer
        _, action = show_frame(video_path, start_frame=80)

        if action == 'quit':
            print("\n  Quit — progress saved.")
            break

        if action in ('skip', 'error'):
            print(f"  Skipped: {filename}")
            continue

        # Get angles from user
        result = ask_angles()
        if result is None:
            continue

        th1, th2, repeat = result
        label    = make_label(th1, th2, repeat)
        new_name = new_filename(label)
        new_path = os.path.join(VIDEOS_DIR, new_name)
        new_stem = os.path.splitext(new_name)[0]

        print(f"\n  Label    : {label}")
        print(f"  New name : {new_name}")

        confirm = input("  Confirm rename? [Y/n]: ").strip().lower()
        if confirm in ('n', 'no'):
            print("  Skipped.")
            continue

        reg = rename_and_update(
            video_path, new_path,
            stem, new_stem,
            th1, th2, repeat, label, reg
        )

        save_registry(reg)
        print(f"  Saved to registry.")

    # Final summary
    print("\n" + "=" * 60)
    _, tagged_final = get_untagged_videos(reg)
    print(f"  Tagged: {len(tagged_final)} / {len(tagged) + len(untagged)} videos")
    print(f"  Registry: {EXPERIMENTS_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
