"""
download_videos.py
-------------------
Downloads all raw video files from the project's Google Drive folder
into the local Videos/ directory.

Requirements:
    pip install gdown

Usage:
    python scripts/download_videos.py

The Drive folder is public (view access). No authentication needed.
"""

import os
import subprocess
import sys


# ── Google Drive folder ID ────────────────────────────────────────────
# Extracted from: https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-
DRIVE_FOLDER_ID = "1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-"

# ── Local destination ─────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, "Videos")


def check_gdown():
    """Check gdown is installed, prompt to install if not."""
    try:
        import gdown
        return True
    except ImportError:
        print("ERROR: gdown is not installed.")
        print("Install it with:  pip install gdown")
        sys.exit(1)


def main():
    check_gdown()
    import gdown

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Downloading videos from Google Drive...")
    print(f"Drive folder: https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}")
    print(f"Destination:  {OUTPUT_DIR}")
    print()

    # gdown.download_folder downloads all files in the folder
    # remaining_ok=True skips files that already exist locally
    gdown.download_folder(
        id=DRIVE_FOLDER_ID,
        output=OUTPUT_DIR,
        quiet=False,
        remaining_ok=True,   # skip already-downloaded files
    )

    print()
    print("Done. Videos saved to:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
