# Double Pendulum — Chaos Lab (Part 2)

Computer-vision pipeline for tracking a wall-mounted double pendulum and
producing per-frame angles + angular velocities for downstream analysis.

## Pipeline

```
calibrate ──▶ track ──▶ verify ──▶ analyse
hsv_tuner   ring_tracker   verify_tracking   phase_*, combined_video
```

| Stage | Script | What it does |
|---|---|---|
| Calibrate | `scripts/processing/hsv_tuner.py` | Interactive HSV calibration. Eyedropper-sample marker pixels, auto-suggest ranges, fine-tune with sliders, live ring-detection preview. Saves to a per-video file (`data/hsv_<videostem>.json`) by default; pass `--global` to save to the shared `data/hsv_values.json` instead. |
| Track | `scripts/processing/ring_tracker.py` | Frame-independent tracker. Stacks four filters (motion mask via temporal-median background, fixed-arm-length ring, HSV colour, predicted angular arc) with a graceful fallback chain. Reads the calibration; writes `measurements/<config>/tracking.csv` and `measurements/<config>/debug.mp4`. |
| Verify | `scripts/processing/verify_tracking.py` | Post-hoc QA on the CSV. Flags rows where the apparent &#124;dθ/dt&#124; exceeds physical limits — catches silent false positives that `dropout=0` won't reveal. Writes `measurements/<config>/verification.{csv,png}`. |
| Repair | `scripts/processing/interpolate_suspects.py` | Linearly interpolates the suspect frames flagged by verify_tracking. Backs up the CSV first and re-verifies after rewriting. |
| Analyse | `scripts/analysis/*.py` | Plots, 3-D phase rotations, animated trajectory videos, side-by-side comparisons. All accept `--stem <config_description>` to read/write inside a measurement folder. |
| Status | `scripts/utils/generate_status_report.py` | Excel report (`data/status_report.xlsx`) with per-measurement dropout stats, file presence, and derived status — computed live from the CSVs. |

## Setup

```bash
pip install opencv-python numpy scipy matplotlib gdown
```

(Use `opencv-contrib-python` instead if you also want to run the archived
CSRT tracker — `archive/scripts/pendulum_tracker.py`. The active pipeline
only needs core OpenCV.)

Raw videos aren't tracked in git (too large; ~3 GB). They live on Google Drive:

📁 **[כאוס — Google Drive Folder](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-)**

Pull them locally:

```bash
python scripts/utils/download_videos.py
```

## Camera / rig

- Resolution: 1280×720 @ 59.94 fps, H.264
- Fixed pivot pixel: `(608, 355)` — never moves, not detected
- Arm length: 35 cm each (≈ 188 px)
- Scale: 0.186 cm/px (22 cm plate ≈ 118 px)
- Angle convention: 0° = straight down, +90 = right, −90 = left, ±180 = up

## Markers

| Marker | Role | How it's tracked |
|---|---|---|
| 🟡 Yellow | Fixed wall pivot | Hard-coded, not tracked |
| 🟢 Green  | Joint between arm 1 and arm 2 | HSV inside an annulus around the pivot |
| 🔴 Red    | Tip of arm 2 | HSV inside an annulus around the green marker |

Calibrated HSV ranges live in two tiers:

- **Per-video** at `data/hsv_<videostem>.json` — created automatically when
  you run `hsv_tuner.py` on a specific video, or when you press `T`
  inside the frame picker to retune mid-run.
- **Global** at `data/hsv_values.json` — fallback used by the tracker
  whenever a video has no per-video file yet. Created by running
  `hsv_tuner.py` with no positional argument, or with `--global`.

`load_hsv_values(video_path)` in `ring_tracker.py` tries the per-video
file first and falls back to the global one. So re-tuning for one
video never clobbers another's calibration. Field meanings are in
`data/hsv_values_readme.txt`.

## Common workflows

### See what's tracked vs pending

```bash
python scripts/utils/video_status.py
# or, equivalently, from the tracker:
python scripts/processing/ring_tracker.py --status
```

A video counts as "tracked" only when its `experiments.json` entry has
populated `release_frame`, ICs (`theta1_release`, `theta2_release`), and
a `tracking.csv` at the entry's `measurements_dir`.

### First time on a new video / new lighting

```bash
# 1. Calibrate marker colours — click ~8 green pixels, R, ~8 red pixels, S, Q.
python scripts/processing/hsv_tuner.py Videos/long_recording.mov

# 2. Track. With no path, opens a file picker rooted at Videos/.
python scripts/processing/ring_tracker.py
```

When the video isn't already in `experiments.json`, the tracker opens
**two cv2 windows** — one for `init_frame`, one for `release_frame` —
that show the actual frame with a live HSV detection overlay (green and
red markers light up if calibration is good). Navigate with `a/d` (±1),
`A/D` (±10), `z/x` (±100), then `ENTER` to confirm. The overlay
doubles as the HSV-adequacy check.

If you spot a bad detection (e.g. the red dot lands on the user's face
because skin matches the red HSV range), press **`T`** inside the
picker. That hands off to `hsv_tuner.py` on the current frame; once you
re-tune and save, the tuner closes and the picker resumes with the new
calibration — no need to restart the tracker.

### Filename position prior

If the video filename matches `th1_pXXX_th2_pYYY.mov` (e.g.
`th1_p180_th2_p180.mov`), the picker uses those angles as a position
prior: blobs more than 70 px from the expected marker location are
rejected. This eliminates skin-tone / wall-poster / glove-color false
positives at held-pendulum starting frames, where HSV thresholds alone
cannot separate the actual marker from a confounder of similar colour.

The expected positions show as **cyan crosshairs** in the picker. If
your ground-truth angles differ from the filename (e.g. mid-tracking
on a long recording), pass `--no-prior` to disable. Videos without
matching filenames (`long_recording.mov`, `DSC_0136.mov`, etc.) get
the legacy unconstrained behaviour automatically.

```bash
# 3. Sanity check — pass --stem to look up the CSV in measurements/.
python scripts/processing/verify_tracking.py --stem th1_p180_th2_m179

# 4. Repair (only if step 3 found suspect frames).
python scripts/processing/interpolate_suspects.py --stem th1_p180_th2_m179

# 5. Analyse — each script writes its canonical output into the same folder.
python scripts/analysis/phase_panels.py     --stem th1_p180_th2_m179
python scripts/analysis/phase_3d.py         --stem th1_p180_th2_m179
python scripts/analysis/phase_animation.py  --stem th1_p180_th2_m179
python scripts/analysis/combined_video.py   --stem th1_p180_th2_m179
```

`--stem` is the `config_description` of the measurement (the folder name
under `measurements/`, e.g. `th1_p180_th2_m179`). The scripts also accept
a positional CSV path (`measurements/<stem>/tracking.csv`) for backward
compatibility, and `combined_video.py` looks up the source `.mov` from
`experiments.json` when `--stem` is given.

### Pick a video from the GUI picker

```bash
python scripts/processing/ring_tracker.py
# prints a one-line "Tracked: N  Pending: M" banner, then opens a Tk
# file dialog rooted at Videos/.
```

The dialog also opens if you pass `--browse`, useful to override a stale
positional path.

### Re-running on a video already in `experiments.json`

```bash
python scripts/processing/ring_tracker.py Videos/long_recording.mov
```

If the video is already tracked, the script prints its stored ICs and
asks `Re-run tracking? [y/N]:` so you don't accidentally overwrite a
good run. Pass `--force` to skip that prompt:

```bash
python scripts/processing/ring_tracker.py Videos/long_recording.mov --force
```

### Skip the debug video (faster on long recordings)

```bash
python scripts/processing/ring_tracker.py Videos/long_recording.mov --no-debug
```

### Stricter verification

```bash
python scripts/processing/verify_tracking.py --stem th1_p180_th2_m179 --omega-cap 1800
# default cap is 2500 deg/s; arm-2 chaos peaks ~1500 deg/s for a 35 cm arm
```

### Status report across every measurement

```bash
python scripts/utils/generate_status_report.py
# writes data/status_report.xlsx
```

Two sheets: a row-per-measurement overview with live dropout stats
computed from each `tracking.csv`, plus a long-recording sheet with
extra columns. Idempotent — always regenerates from scratch.

## Outputs

Every per-measurement artefact lives in `measurements/<config_description>/`.
A "complete" measurement has the eight canonical files below. Status is
derived from which of these files are present.

| File | Produced by | Notes |
|---|---|---|
| `tracking.csv` | `ring_tracker.py` | Per frame: `frame, time_s, phase, x_green, y_green, x_red, y_red, theta1_deg, theta2_deg, dropout` |
| `debug.mp4` | `ring_tracker.py` | Annotated video — search rings, predicted arcs, marker dots, phase, dropout flag |
| `verification.csv` | `verify_tracking.py` | Tracking CSV + `omega1_deg_s`, `omega2_deg_s`, `suspect` columns |
| `verification.png` | `verify_tracking.py` | θ and ω timelines with suspect frames highlighted |
| `phase_panels.png` | `phase_panels.py` | 6-panel static physics-sanity figure |
| `phase_3d_trajectory.png` | `phase_3d.py` | 3-D phase ribbon (θ₁, θ₂, ω₁) coloured by time |
| `phase_3d_rotation.mp4` | `phase_3d.py` | Same view, rotating 360° |
| `phase_animation.mp4` | `phase_animation.py` | Animated 3-panel phase view, real time |
| `combined.mp4` | `combined_video.py` | Side-by-side raw video + phase panels |

The registry at `data/experiments.json` is the only file outside the
measurement folder. It carries init/release frames, ICs at release,
dropout rate, normalised energy proxy, tracker name, `config_description`
(folder name), `measurements_dir`, and quality flags
(`tracking_quality`, `verification_notes`, `verification_date`,
`suspect_frames_interpolated`).


## Directory structure

```
chaos/
├── scripts/
│   ├── processing/             tracking pipeline
│   │   ├── hsv_tuner.py             interactive HSV calibration
│   │   ├── ring_tracker.py          main tracker
│   │   ├── verify_tracking.py       post-hoc QA
│   │   └── interpolate_suspects.py  linear-interp the |ω| > cap suspects
│   ├── analysis/               plots, figures, animations (all accept --stem)
│   │   ├── phase_3d.py              3D phase trajectory + rotating MP4
│   │   ├── phase_animation.py       animated 3-panel phase view
│   │   ├── phase_panels.py          6-panel static physics sanity check
│   │   └── combined_video.py        side-by-side raw video + phase panels
│   └── utils/
│       ├── download_videos.py        pull raw videos from Google Drive
│       ├── video_status.py           which Videos/ files are tracked vs pending
│       ├── migrate_to_measurements.py one-shot reorganisation script (idempotent)
│       └── generate_status_report.py builds data/status_report.xlsx
├── measurements/              per-measurement output folders
│   └── <config_description>/  e.g. th1_p044_th2_m001/
│       ├── tracking.csv             (gitignored — large, regenerable)
│       ├── verification.csv         (gitignored)
│       ├── debug.mp4                (gitignored)
│       ├── phase_3d_rotation.mp4    (gitignored)
│       ├── phase_animation.mp4      (gitignored)
│       ├── combined.mp4             (gitignored)
│       ├── phase_3d_trajectory.png  (tracked)
│       ├── phase_panels.png         (tracked)
│       └── verification.png         (tracked)
├── data/                      registry, HSV calibration, status report
│   ├── experiments.json            single source of truth for measurements
│   ├── hsv_values.json             global HSV fallback
│   ├── hsv_<videostem>.json        per-video HSV overrides
│   └── status_report.xlsx          generated by generate_status_report.py
├── Videos/                    raw .mov files (gitignored, ~3 GB)
└── archive/                   superseded scripts and reference data
    ├── scripts/               pendulum_tracker (CSRT), pendulum_tracker_hybrid,
    │                          ring_tracker (v1), tag_videos, video_tagger,
    │                          rename_tagged_videos, split_video, stitch_csv,
    │                          preview_frame
    └── Videos/                angle reference jpgs
```

Small human-readable artefacts (the three PNGs) stay tracked so the
repo always shows what's been measured at a glance. Large regenerable
artefacts (CSVs and MP4s) are gitignored.

## History

`ring_tracker.py` is the third generation of the tracker. The earlier two
live in `archive/scripts/`:

- `pendulum_tracker.py` — original CSRT (appearance-based) tracker. Works
  on slow, well-lit clips but loses the red marker on inverted starts and
  fast falls. On `long_recording.mov` it dropped ~98% of free-swing red
  frames.
- `ring_tracker.py` (v1) — first ring-based tracker. Frame-independent
  HSV detection inside the arm-length annulus. Improved over CSRT but
  still missed motion-blur frames where saturation collapses.
- `ring_tracker.py` (current) — adds median-frame background subtraction,
  a temporal angular predictor, and a five-stage fallback chain. Brings
  the long-recording dropout rate from ~98% (CSRT) to 0.01% (2 of 30,942
  frames). `verify_tracking.py` flagged 23 hidden suspects (dropout=0
  but |ω₂| > 2500 °/s) on long_recording, which were fixed by
  `interpolate_suspects.py`; physically the residual ω peaks are now
  well within plausible chaotic-motion limits.
