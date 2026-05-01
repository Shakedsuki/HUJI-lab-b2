# Chaos — Double-Pendulum Tracking Lab

Computer-vision pipeline for tracking a wall-mounted double pendulum from
fixed-camera video, producing per-frame joint angles and angular
velocities for chaos-physics analysis. Designed for batch processing of
new recordings with a human-in-the-loop quality gate.

```
                       Videos/*.mov
                            │
                            ▼
   ┌──────────────────────────────────────────────────────┐
   │  per-video HSV calibration  (eyedropper + auto-tune) │
   └──────────────────────┬───────────────────────────────┘
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  ring + motion + colour + arc tracker  (5-stage      │
   │  graceful fallback chain, strict-physics gates,      │
   │  per-frame manual seeds)                             │
   └──────────────────────┬───────────────────────────────┘
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  verify  (|Δθ/dt| outliers, hidden suspect frames)   │
   │  interpolate-suspects  (linear repair)               │
   │  verdict card  (PASS / WARN / FAIL → registry flag)  │
   └──────────────────────┬───────────────────────────────┘
                          ▼
              measurements/<config>/tracking.csv
              measurements/<config>/verification.{csv,png}
              data/experiments.json   (single source of truth)
```

## Quickstart

```bash
# Setup once
pip install -r requirements.txt
python scripts/utils/download_videos.py     # pull raw videos from Drive

# Drive the pending queue interactively (god-mode):
.\chaos next                                # PowerShell — auto-resolves chaos.ps1
chaos next                                  # cmd.exe (with the repo on PATH)
./chaos.sh next                             # Git Bash / Linux / macOS
python chaos.py next                        # cross-platform fallback

# One-off operations:
chaos status                                # who's tracked, who's pending
chaos tune <stem>                           # open the HSV tuner
chaos track <stem>                          # standard track + verdict
chaos fix <stem>                            # interactive manual fix-up
chaos verify <stem>                         # standalone QA pass
chaos report                                # regenerate data/status_report.xlsx
chaos bulk                                  # sequential bulk pass
chaos help                                  # one-page cheat sheet
chaos <cmd> --help                          # full flag list per subcommand
```

`<stem>` is a `config_description` like `th1_p047_th2_m002` — the folder
name under `measurements/`. `chaos status` prints the list of every clip
and its current state.

> **PowerShell note.** PowerShell's default security model requires a
> leading `.\` for scripts in the current directory. Type
> `.\chaos <cmd>`. For an unprefixed `chaos` from any directory, add to
> your `$PROFILE`:
> ```powershell
> function chaos { & "C:\dev\chaos\chaos.ps1" @args }
> ```
> Reload with `. $PROFILE`. cmd.exe / Git Bash / Linux / macOS users
> don't need this step.

## Per-clip workflow (what `chaos next` automates)

```
┌──────────────────────────────────────────────────────────────┐
│ 1. HSV adequacy probe  (30 sampled frames)                   │
│    OK    (≥70%)  → continue                                   │
│    WARN  (40–70) → prompt: continue / tune / skip             │
│    ABORT (<40%)  → prompt: tune (mandatory) / skip            │
└────────────┬─────────────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. track_one bundle:                                          │
│    a) ring_tracker       — 5-stage fallback, strict-physics   │
│                            gates after seeds                  │
│    b) verify_tracking    — flags |Δθ/dt|>cap as suspects     │
│    c) interpolate_suspects (only if hidden suspects > 0)      │
│    d) re-verify                                               │
│    e) verdict card       — PASS / WARN / FAIL                 │
│       PASS auto-marks  tracking_quality=verified              │
└────────────┬─────────────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. WARN / FAIL → manual fix-up:                              │
│    interactive picker pre-positioned at worst suspect frame   │
│    LEFT-CLICK to set a seed (correct marker position)         │
│    P → save seeds.json + re-track from earliest seed          │
│        forward, with --strict-physics enforcing physical      │
│        plausibility (no silent FPs to skin/arm-shaft)         │
└──────────────────────────────────────────────────────────────┘
```

See [docs/PIPELINE.md](docs/PIPELINE.md) for the keystroke-level reference.

## Setup

```bash
pip install -r requirements.txt
```

Pinned set: `opencv-python`, `numpy`, `scipy`, `matplotlib`, `pandas`,
`openpyxl`, `gdown`. Use `opencv-contrib-python` instead of
`opencv-python` if you also want to run the archived CSRT tracker
at `archive/scripts/pendulum_tracker.py` — the active pipeline only
needs core OpenCV.

Tested on Python 3.13.2 (Windows 11). Lower bounds in `requirements.txt`
reflect the minimum versions that exercise current API usage.

Raw videos aren't in git (~3 GB total). They live on Google Drive:

📁 **[כאוס — Google Drive Folder](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-)**

```bash
python scripts/utils/download_videos.py
```

## Camera / rig

| Field | Value |
|---|---|
| Resolution | 1280×720 @ 59.94 fps, H.264 |
| Pivot pixel | `(608, 355)` (fixed, not detected) |
| Arm length | 35 cm each (≈ 188 px) |
| Scale | 0.186 cm/px (22 cm reference plate ≈ 118 px) |
| Angle convention | 0° = down, +90 = right, −90 = left, ±180 = up |

## Markers

| Marker | Role | How it's tracked |
|---|---|---|
| 🟡 Yellow | Fixed wall pivot | Hard-coded, not detected |
| 🟢 Green  | Joint between arm 1 and arm 2 | HSV inside an annulus around the pivot |
| 🔴 Red    | Tip of arm 2 | HSV inside an annulus around the green marker |

### HSV calibration tiers

```
                ┌─────────────────────────────────────┐
                │  data/hsv_<videostem>.json          │   ← per-video
                │  (created by `chaos tune <stem>`)   │     overrides
                └──────────────┬──────────────────────┘
                               ▼
                ┌─────────────────────────────────────┐
                │  data/hsv_values.json               │   ← global
                │  (legacy / fallback)                │     fallback
                └─────────────────────────────────────┘
```

`load_hsv_values(video_path)` in `ring_tracker.py` tries the per-video
file first and falls back to the global one. So tuning one clip never
clobbers another's calibration.

## What the tracker does (and why)

The tracker is **frame-independent** — it doesn't propagate an
appearance template like a CSRT tracker would. Each frame is detected
fresh by the **intersection of four weak filters**:

1. **Motion mask** — temporal-median background subtraction on a
   fixed-camera scene
2. **Ring** — pixels at `arm_length ± tolerance` from the pivot (for
   green) or from green (for red)
3. **HSV colour** — calibrated marker hue/sat/val ranges
4. **Angular arc** — pixels within ±arc-half-width of the predicted
   angle from the previous frame, using a Kalman-lite ω predictor

Each individual filter can be lax; their **AND** is selective. When the
strict pipeline fails (motion blur, partial occlusion), a 5-stage
graceful fallback drops one filter at a time:

```
1. motion ∩ ring ∩ colour ∩ arc                  (strict)
2. motion ∩ ring ∩ colour                        (drop arc — fast moves)
3. motion ∩ ring ∩ arc                           (drop colour — blur)
4. ring ∩ colour                                 (drop motion — held)
5. motion ∩ ring                                 (last resort, distance-gated)
```

### Strict-physics mode

Activated by `--strict-physics` or any post-seed window. Every fallback
stage gets a **hard angular gate**:

```
gate_radius = max(STRICT_PIXEL_FLOOR_PX,
                  ARM_LENGTH_PX · radians(25° + 1.5·|ω|·dt))
```

That's ~82 px at ω=0 (held marker) scaling to ~205 px at the physical
1500 °/s arm-2 chaos peak. **Out-of-gate candidates are rejected; if no
in-gate candidate exists in any stage, the row becomes `dropout=1`.**
This eliminates silent false positives where the tracker would
otherwise snap to a wall artifact, the user's hand, or a chunk of arm
shaft.

### Manual seeds

`measurements/<config>/seeds.json` stores human-asserted marker
positions for specific frames. Each seed:

1. Writes the seed values verbatim into the corresponding row of
   `tracking.csv`.
2. Re-anchors the predictors at that frame.
3. Opens a **30-frame strict-physics window** after itself.

`chaos fix <stem>` provides an interactive picker for adding/editing
seeds; pressing `P` saves the file and re-runs ring_tracker from the
earliest seed with `--strict-physics --seeds-file --from-frame=N`.

### Verify + interpolate

`verify_tracking.py` flags rows where the apparent |Δθ/dt| exceeds a
physical threshold (default 2500 °/s — arm-2 chaos peaks ~1500). The
critical metric is **hidden suspects**: rows with `dropout=0` but
|ω| > cap. Those are silent tracking errors that the dropout column
won't reveal.

`interpolate_suspects.py` replaces each hidden suspect frame with a
linear interpolation of θ between its nearest clean neighbours, then
back-projects (x, y) from the interpolated angle. Backs up the CSV
first (`tracking.csv.bak`) and re-runs verify after rewriting.

## Verdict bands

`track_one` and `manual_correction` both emit a one-page verdict card
with this banding:

| Verdict | Conditions | Action |
|---|---|---|
| **PASS** | dropout < 5%, no residual suspects, peak \|ω₂\| ≤ 1500 °/s | done; auto-marks `tracking_quality=verified` |
| **WARN** | dropout 5–10%, OR residual suspects, OR peak \|ω₂\| 1500–4000 °/s | review verification.png; manually accept or fix |
| **FAIL** | dropout > 10%, OR peak \|ω₂\| > 4000 °/s, OR a subprocess errored | fix-up required |

## Outputs

Every per-measurement artefact lives in `measurements/<config_description>/`.
The eight canonical files plus `seeds.json` for manual ground-truth:

| File | Produced by | Tracked in git? |
|---|---|---|
| `tracking.csv` | `ring_tracker` | ✗ (gitignored — large, regenerable) |
| `verification.csv` | `verify_tracking` | ✗ |
| `debug.mp4` | `ring_tracker` (when `--debug`) | ✗ |
| `phase_3d_trajectory.png` | `phase_3d.py` | ✓ |
| `phase_3d_rotation.mp4` | `phase_3d.py --save` | ✗ |
| `phase_animation.mp4` | `phase_animation.py --save` | ✗ |
| `phase_panels.png` | `phase_panels.py` | ✓ |
| `verification.png` | `verify_tracking.py` | ✓ |
| `combined.mp4` | `combined_video.py` | ✗ |
| `seeds.json` | `manual_correction.py` | ✓ (small, human input) |

The **registry** at `data/experiments.json` is the single source of
truth. Per measurement it carries:

- `video_file`, `config_description`, `measurements_dir`, `csv_file`
- `init_frame`, `release_frame`, `tag_frame`, `green_click_px`, `red_click_px`
- `theta1_release`, `theta2_release`, `omega1_release`, `omega2_release`,
  `energy_proxy`
- `tracking_quality`, `verification_date`, `verification_notes`,
  `suspect_frames_interpolated`
- `dropout_rate_pct`, `n_free_frames`, `duration_s`, etc.

`chaos report` exports it to **`data/status_report.xlsx`** with two
sheets (regular measurements + the long_recording row), live dropout
stats computed from each `tracking.csv`, conditional formatting, and
auto-filter on the header row.

## Directory structure

```
chaos/
├── chaos.py                 ← unified entry point (the "god script")
├── chaos.bat                ← cmd.exe wrapper
├── chaos.ps1                ← PowerShell wrapper (use `.\chaos <cmd>`)
├── chaos.sh                 ← POSIX wrapper (Git Bash / Linux / macOS)
├── README.md                ← this file
├── requirements.txt
├── scripts/
│   ├── processing/                tracking primitives
│   │   ├── hsv_tuner.py             interactive HSV calibration (eyedropper, zoom loupe)
│   │   ├── ring_tracker.py          main tracker (HSV probe, smart picker, strict-physics, seeds)
│   │   ├── verify_tracking.py       post-hoc QA on a tracking.csv
│   │   └── interpolate_suspects.py  linearly fixes hidden suspect frames
│   ├── analysis/                  plots, figures, animations (--stem aware)
│   │   ├── phase_3d.py
│   │   ├── phase_animation.py
│   │   ├── phase_panels.py
│   │   └── combined_video.py
│   └── utils/                     orchestrators + housekeeping
│       ├── download_videos.py        pull raw videos from Drive
│       ├── video_status.py           who's tracked, who's pending
│       ├── track_one.py              per-clip orchestrator (track + verify + verdict)
│       ├── manual_correction.py      interactive seed UI + re-track + verdict
│       ├── bulk_track.py             sequential bulk over track_one
│       └── generate_status_report.py builds data/status_report.xlsx
├── docs/
│   └── PIPELINE.md          ← keystroke-level workflow reference
├── measurements/            per-measurement output folders
│   └── <config_description>/  e.g. th1_p044_th2_m001/
│       ├── tracking.csv             ✗ (gitignored — main output)
│       ├── verification.csv         ✗
│       ├── debug.mp4                ✗
│       ├── phase_3d_rotation.mp4    ✗
│       ├── phase_animation.mp4      ✗
│       ├── combined.mp4             ✗
│       ├── phase_3d_trajectory.png  ✓ (tracked)
│       ├── phase_panels.png         ✓
│       ├── verification.png         ✓
│       └── seeds.json               ✓ (when present — human input)
├── data/                    registry, HSV calibration, status report
│   ├── experiments.json            single source of truth for measurements
│   ├── hsv_values.json             global HSV fallback
│   ├── hsv_<videostem>.json        per-video HSV overrides
│   └── status_report.xlsx          generated by `chaos report`
├── Videos/                  raw .mov files (gitignored, ~3 GB)
└── archive/                 superseded scripts and reference data
    └── scripts/
        ├── oneshots/                one-shot migration scripts (already run)
        ├── pendulum_tracker.py      CSRT tracker (v1)
        ├── pendulum_tracker_hybrid.py
        ├── ring_tracker.py          ring tracker v1 (no fallback chain)
        └── ...
```

## Reference: low-level building blocks

The `chaos` command is the recommended interface. The underlying scripts
are still callable directly for power-users:

```bash
# Calibration
python scripts/processing/hsv_tuner.py Videos/<clip>.mov

# Tracking — every flag chaos uses internally is exposed
python scripts/processing/ring_tracker.py Videos/<clip>.mov \
                                          [--no-debug]
                                          [--force]
                                          [--browse]
                                          [--no-prior]
                                          [--skip-probe]
                                          [--yes-to-warn]
                                          [--strict-physics]
                                          [--seeds-file <path>]
                                          [--from-frame N]

# QA
python scripts/processing/verify_tracking.py --stem <config> [--omega-cap N] [--no-plot]

# Repair
python scripts/processing/interpolate_suspects.py --stem <config> [--dry-run]

# Orchestrators (subsumed by `chaos`)
python scripts/utils/track_one.py          --stem <config>
python scripts/utils/manual_correction.py  --stem <config>
python scripts/utils/bulk_track.py         [--dry-run] [--filter STR]
python scripts/utils/video_status.py
python scripts/utils/generate_status_report.py
```

## Tracker history

`ring_tracker.py` is the third generation. The earlier two live in
`archive/scripts/`:

- **`pendulum_tracker.py`** (CSRT, v1) — original appearance-based
  tracker. Works on slow, well-lit clips but loses the red marker on
  inverted starts and fast falls. On `long_recording.mov` it dropped
  ~98 % of free-swing red frames.
- **`ring_tracker.py`** (v1, archived) — first ring-based tracker.
  Frame-independent HSV detection inside the arm-length annulus.
  Improved over CSRT but still missed motion-blur frames where
  saturation collapses.
- **`ring_tracker.py`** (current) — adds median-frame background
  subtraction, a temporal angular predictor, the 5-stage fallback
  chain, an HSV adequacy probe, smart init/release scanning, click_px
  predictor seeding, strict-physics mode, and per-frame manual seeds.
  Brings the long-recording dropout rate from ~98 % (CSRT) to 0.01 %
  (2 of 30,942 frames). Hidden suspect frames flagged by
  `verify_tracking.py` are repaired by `interpolate_suspects.py`; the
  residual ω peaks then sit within plausible chaotic-motion limits.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `chaos: command not found` (PowerShell) | PowerShell doesn't run from current dir | use `.\chaos <cmd>` or add `$PROFILE` function (see Quickstart) |
| `chaos.py: command not found` (cmd.exe) | repo not on PATH | run from repo root, or add the repo to PATH |
| `HSV adequacy below 40%` (ABORT) | global HSV doesn't fit this clip | `chaos tune <stem>` |
| Detected red sits on user's hand | skin matches red HSV range | re-tune with tighter `s_min` (~140) to filter low-saturation skin |
| Verify flags many hidden suspects | tracker latched briefly to arm shaft | `chaos fix <stem>` to seed problem frames; strict-physics re-track handles the rest |
| `--from-frame` errors with "requires existing CSV" | passed `>0` but no prior track | run `chaos track <stem>` first; or seed at frame 0 to track from scratch |

## Contributing / development notes

- Branch from `master`; merge via PR. The repo defaults to `master` as
  the integration branch.
- Per-measurement outputs live in `measurements/<config>/`; small
  human-readable artefacts are tracked, large regenerable artefacts
  are gitignored.
- The registry at `data/experiments.json` is the only authoritative
  metadata file. Don't edit it by hand; let `ring_tracker` and the
  orchestrators write to it.
- HSV calibration files (`data/hsv_*.json`) are tracked because they
  represent calibration ground truth. Tracking CSVs are not, because
  they're regenerable from `seeds.json` + the videos.
- Run `chaos report` periodically and commit `data/status_report.xlsx`
  if you want a snapshot in version control; otherwise it's regenerable.
