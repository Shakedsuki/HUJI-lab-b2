"""
rename_tagged_videos.py
------------------------
One-time script: renames all tagged video files in experiments.json
from their original DSC_XXXX.mov names to their video_label names.

Run once, then delete.
"""

import os
import json

ROOT             = r"C:\dev\chaos"
VIDEOS_DIR       = os.path.join(ROOT, "Videos")
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")

with open(EXPERIMENTS_FILE) as f:
    reg = json.load(f)

renamed  = 0
skipped  = 0
errors   = 0

for stem, entry in reg.items():
    label      = entry.get("video_label")
    video_file = entry.get("video_file", f"{stem}.mov")

    if not label:
        print(f"  SKIP  {stem:20s}  — no video_label set")
        skipped += 1
        continue

    new_filename = label + ".mov"
    old_path     = os.path.join(VIDEOS_DIR, video_file)
    new_path     = os.path.join(VIDEOS_DIR, new_filename)

    if not os.path.exists(old_path):
        # Maybe already renamed
        if os.path.exists(new_path):
            print(f"  OK    {video_file:30s}  already renamed to  {new_filename}")
            entry["video_file"] = new_filename
            renamed += 1
        else:
            print(f"  ERROR {video_file:30s}  — file not found in Videos/")
            errors += 1
        continue

    if os.path.normpath(old_path) == os.path.normpath(new_path):
        print(f"  OK    {video_file:30s}  already correctly named")
        skipped += 1
        continue

    if os.path.exists(new_path):
        print(f"  WARN  {video_file:30s}  — target {new_filename} already exists, skipping")
        skipped += 1
        continue

    os.rename(old_path, new_path)
    entry["video_file"] = new_filename
    print(f"  OK    {video_file:30s}  ->  {new_filename}")
    renamed += 1

# Save updated registry
with open(EXPERIMENTS_FILE, 'w') as f:
    json.dump(reg, f, indent=2)

print(f"\nDone.  Renamed: {renamed}   Skipped: {skipped}   Errors: {errors}")
print(f"experiments.json updated.")
