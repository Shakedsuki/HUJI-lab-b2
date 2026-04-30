# Double Pendulum — Chaos Lab (Part 2)

## Video Data

Raw videos are **not tracked in git** (too large). They are stored on Google Drive:

📁 **[כאוס — Google Drive Folder](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-)**

To download all videos locally, run:
```bash
python scripts/download_videos.py
```
Requires `gdown`: `pip install gdown`

## Setup

Video files are stored locally in `Videos/` — not tracked by git (too large).

Install dependencies:
```bash
pip install opencv-python numpy
```

## Directory Structure

```
chaos/
├── scripts/
│   ├── pendulum_tracker.py   # Main tracking pipeline → outputs CSV
│   ├── hsv_tuner.py          # Interactive HSV range tuning tool
│   └── hsv_values.txt        # Tuned HSV ranges for this camera/lighting
├── data/                     # CSV outputs (tracked by git)
├── snapshots/                # Reference photos (tracked by git)
├── output/                   # Debug videos (git-ignored — large)
├── frames/                   # Extracted frames (git-ignored — regenerable)
└── Videos/                   # Raw .mov files (git-ignored — ~3 GB)
```

## Workflow

### 1 — Trim a video (remove hold period before release)
```bash
ffmpeg -i Videos/DSC_0136.mov -vf "select=gte(n\,234)" -vsync vfr -c:v libx264 -crf 18 Videos/DSC_0136_trimmed.mov
```
Replace `234` with the frame where the person's hand clears the frame.

### 2 — Tune HSV ranges (if needed for a new video)
```bash
python scripts/hsv_tuner.py
```
Navigate to a frame with active motion, adjust sliders until both markers
show clean white blobs, press `S` to save.

### 3 — Run the tracker
```bash
python scripts/pendulum_tracker.py
```
Edit the `CONFIG` section at the top of the script first.

Output: `data/<video_name>_tracking.csv`

## Camera / Setup

- Resolution: 1280×720 @ 59.94fps
- Codec: H.264
- Fixed pivot pixel: `(608, 355)`
- Arm length: 35 cm each
- Scale: ~0.186 cm/px (derived from 22cm plate ≈ 118px)

## Marker Colors

| Marker | Role | HSV range |
|--------|------|-----------|
| 🟡 Yellow | Fixed wall pivot | Hard-coded, not tracked |
| 🟢 Green  | Joint (arm1 → arm2) | H:35–80, S:30–255, V:80–255 |
| 🔴 Red    | Tip of arm 2 | H:0–10 + 165–179, S:32–255, V:72–255 |
