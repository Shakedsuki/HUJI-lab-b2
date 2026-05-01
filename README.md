# Double Pendulum — Chaos Lab (Part 2)

Computer-vision pipeline for tracking a wall-mounted double pendulum and
producing per-frame angles + angular velocities for downstream analysis.

## Quickstart — the `chaos` command

One entry point to drive the whole pipeline:

```bash
# Setup once
pip install -r requirements.txt
python scripts/utils/download_videos.py     # pull raw videos from Drive

# Drive the pending queue interactively (god-mode):
.\chaos next                                # PowerShell — auto-resolves chaos.ps1 via PATHEXT
chaos next                                  # cmd.exe (with the repo on PATH or from repo root)
./chaos.sh next                             # Git Bash / Linux / macOS
python chaos.py next                        # cross-platform fallback

# Or operate one clip at a time:
chaos status                                # who's tracked, who's pending
chaos tune <stem>                           # open the HSV tuner
chaos track <stem>                          # standard track + verdict
chaos fix <stem>                            # interactive manual fix-up
chaos verify <stem>                         # standalone QA pass
chaos report                                # regenerate the Excel report
chaos bulk                                  # sequential bulk pass
chaos help                                  # cheat sheet
```

`<stem>` is a `config_description` like `th1_p047_th2_m002` — the folder
name under `measurements/`. `chaos status` prints the list.

> **PowerShell note:** PowerShell does not run commands from the
> current directory by default — type `.\chaos <cmd>` (with the
> leading `.\`). For an unprefixed `chaos` from any directory, add a
> function to your `$PROFILE`:
>
> ```powershell
> function chaos { & "C:\dev\chaos\chaos.ps1" @args }
> ```
>
> (Reload with `. $PROFILE` or open a new shell.) `cmd.exe`, Git Bash,
> Linux, and macOS users don't need this step.

## Per-clip workflow (what `chaos next` automates)

```
   ┌──────────────────────────────────────────────────────────────┐
   │  HSV adequacy probe (30 sampled frames)                       │
   │   ABORT (<40%)  ──▶  prompt to launch hsv_tuner               │
   │   WARN  (40–70) ──▶  prompt to continue or tune               │
   │   OK    (≥70)   ──▶  proceed                                  │
   └────────────┬─────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  track_one  (= ring_tracker → verify → interpolate → verdict) │
   │   strict-physics gate active in any post-seed window          │
   │   PASS  ──▶ tracking_quality=verified, on to next clip        │
   │   WARN  ──▶ prompt: accept / fix-up / skip                    │
   │   FAIL  ──▶ prompt: fix-up (manual seeds) / skip              │
   └──────────────────────────────────────────────────────────────┘
                │
                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  manual_correction (only if WARN/FAIL)                        │
   │   interactive picker pre-positioned at the worst suspect      │
   │   click correct marker positions on as many frames as needed  │
   │   P → save seeds.json + re-track from earliest seed forward   │
   │       under --strict-physics --seeds-file                     │
   └──────────────────────────────────────────────────────────────┘
```

See [docs/PIPELINE.md](docs/PIPELINE.md) for the full keystroke-level
workflow.

## Setup

```bash
pip install -r requirements.txt
```

The pinned set is `opencv-python`, `numpy`, `scipy`, `matplotlib`,
`pandas`, `openpyxl`, and `gdown`. Use `opencv-contrib-python` instead
of `opencv-python` if you also want to run the archived CSRT tracker
at `archive/scripts/pendulum_tracker.py` — the active pipeline only
needs core OpenCV.

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
  you run `chaos tune <stem>` or when you press `T`
  inside the frame picker to retune mid-run.
- **Global** at `data/hsv_values.json` — fallback used by the tracker
  whenever a video has no per-video file yet.

`load_hsv_values(video_path)` in `ring_tracker.py` tries the per-video
file first and falls back to the global one. So re-tuning for one
video never clobbers another's calibration.

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
| `seeds.json` | `manual_correction.py` | Optional human-asserted ground-truth marker positions |

The registry at `data/experiments.json` is the only authoritative file
outside the measurement folders. It carries init/release frames, ICs at
release, dropout rate, energy proxy, tracker name,
`config_description`, `measurements_dir`, and quality flags
(`tracking_quality`, `verification_notes`, `verification_date`,
`suspect_frames_interpolated`).

## Directory structure

```
chaos/
├── chaos.py                 ← unified entry point (the "god script")
├── chaos.bat                ← cmd.exe wrapper
├── chaos.ps1                ← PowerShell wrapper (use `.\chaos <cmd>`)
├── chaos.sh                 ← POSIX wrapper (Git Bash / Linux / macOS)
├── scripts/
│   ├── processing/                tracking primitives
│   │   ├── hsv_tuner.py             interactive HSV calibration
│   │   ├── ring_tracker.py          main tracker
│   │   ├── verify_tracking.py       post-hoc QA
│   │   └── interpolate_suspects.py  linear-interp the |ω| > cap suspects
│   ├── analysis/                  plots, figures, animations (--stem aware)
│   │   ├── phase_3d.py
│   │   ├── phase_animation.py
│   │   ├── phase_panels.py
│   │   └── combined_video.py
│   └── utils/                     orchestrators + housekeeping
│       ├── download_videos.py        pull raw videos from Drive
│       ├── video_status.py           who's tracked, who's pending
│       ├── track_one.py              per-clip orchestrator
│       ├── manual_correction.py      interactive seed UI + re-track
│       ├── bulk_track.py             sequential bulk over track_one
│       └── generate_status_report.py builds data/status_report.xlsx
├── docs/
│   └── PIPELINE.md          ← keystroke-level workflow reference
├── measurements/            per-measurement output folders
│   └── <config_description>/  e.g. th1_p044_th2_m001/
│       ├── tracking.csv             (gitignored — large, regenerable)
│       ├── verification.csv         (gitignored)
│       ├── debug.mp4                (gitignored)
│       ├── phase_3d_rotation.mp4    (gitignored)
│       ├── phase_animation.mp4      (gitignored)
│       ├── combined.mp4             (gitignored)
│       ├── phase_3d_trajectory.png  (tracked)
│       ├── phase_panels.png         (tracked)
│       ├── verification.png         (tracked)
│       └── seeds.json               (tracked — small, human input)
├── data/                    registry, HSV calibration, status report
│   ├── experiments.json            single source of truth for measurements
│   ├── hsv_values.json             global HSV fallback
│   ├── hsv_<videostem>.json        per-video HSV overrides
│   └── status_report.xlsx          generated by `chaos report`
├── Videos/                  raw .mov files (gitignored, ~3 GB)
└── archive/                 superseded scripts and reference data
    └── scripts/
        ├── oneshots/        one-shot migration scripts (already run)
        ├── pendulum_tracker.py     CSRT tracker (v1)
        └── ...
```

Small human-readable artefacts (the three PNGs + seeds.json) stay
tracked so the repo always shows what's been measured at a glance. Large
regenerable artefacts (CSVs and MP4s) are gitignored.

## Reference: low-level building blocks

The `chaos` command above is the recommended interface. The underlying
scripts are still callable directly for power-users:

```bash
# Calibration
python scripts/processing/hsv_tuner.py Videos/<clip>.mov

# Tracking
python scripts/processing/ring_tracker.py Videos/<clip>.mov [--no-debug]
                                                            [--force]
                                                            [--strict-physics]
                                                            [--seeds-file <path>]
                                                            [--from-frame N]
                                                            [--skip-probe]
                                                            [--yes-to-warn]

# QA
python scripts/processing/verify_tracking.py --stem <config>

# Repair
python scripts/processing/interpolate_suspects.py --stem <config> [--dry-run]

# Orchestrators (subsumed by `chaos`)
python scripts/utils/track_one.py          --stem <config>
python scripts/utils/manual_correction.py  --stem <config>
python scripts/utils/bulk_track.py         [--dry-run] [--filter STR]
python scripts/utils/video_status.py
python scripts/utils/generate_status_report.py
```

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
  a temporal angular predictor, a five-stage fallback chain, an HSV
  adequacy probe, smart init/release scanning, click_px predictor seeding,
  and a strict-physics mode driven by per-frame manual seeds. Brings
  the long-recording dropout rate from ~98% (CSRT) to 0.01% (2 of 30,942
  frames). Hidden suspect frames flagged by `verify_tracking.py` are
  fixed by `interpolate_suspects.py`; the residual ω peaks then sit
  within plausible chaotic-motion limits.
