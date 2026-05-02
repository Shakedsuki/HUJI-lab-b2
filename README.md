# Chaos — Double-Pendulum Tracking Lab

Tool that turns a fixed-camera video of a double pendulum into per-frame
joint angles + angular velocities. You feed it a `.mov` file; it produces
a `tracking.csv` that downstream physics analysis can consume.

## What you'll do

For each new recording, in order:

1. **Tune** marker colours for the clip (~1 min interactive)
2. **Track** the clip and read the verdict card (~1–3 min unattended)
3. **Fix** any frames the tracker got wrong (only if needed)

The single command **`chaos next`** drives all three steps for every
pending clip, prompting only when human input is genuinely required.

> `chaos verify` now runs **7 physics checks** in addition to dropout:
> arm-length rigidity, angular acceleration (Δω), marker swap, arm-length
> trend, θ-prediction residual, energy monotonicity, and pivot drift.
> A 0%-dropout clip can still fail if any of these checks detects a
> wrong-target latch. After updating `thresholds.py`, run **`chaos
> audit`** to re-validate previously-verified clips.

## Setup (once)

```bash
git clone <this repo> && cd chaos
pip install -r requirements.txt
python scripts/utils/download_videos.py     # pull raw videos from Drive
```

> **Drive folder for raw videos**:
> [כאוס on Google Drive](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-)

Tested on Python 3.13 / Windows 11. macOS and Linux work fine too.

## How to invoke `chaos`

| Shell | Command |
|---|---|
| **PowerShell** (default in VS Code on Windows) | `.\chaos <cmd>` |
| cmd.exe | `chaos <cmd>` (with repo on PATH) |
| Git Bash / Linux / macOS | `./chaos.sh <cmd>` |
| Cross-platform fallback | `python chaos.py <cmd>` |

> **PowerShell tip**: to drop the `.\` prefix, add this line to your
> `$PROFILE` once: `function chaos { & "C:\dev\chaos\chaos.ps1" @args }`,
> then `. $PROFILE`.

## Cheat sheet

```
chaos next                    drive the whole pending queue (god-mode)
chaos next --stem <stem>      drive just one clip through the pipeline

chaos status                  who's tracked, who's pending
chaos report                  regenerate data/status_report.xlsx
chaos audit [--apply]         re-validate verified clips against current physics thresholds

chaos tune <stem>             open the HSV tuner for one clip
chaos track <stem>            track + verify + interpolate + verdict
chaos fix <stem>              interactive manual-seed fix-up + re-track
chaos override <stem> --frame N   surgical single-row CSV edit
chaos verify <stem>           standalone QA on an existing track

chaos help                    one-page summary
chaos <cmd> --help            full flag list per subcommand
```

`<stem>` is a config_description like `th1_p047_th2_m002` — the folder
name under `measurements/`. Run `chaos status` to see the list.

## Per-clip workflow

```
┌─────────────────────────────────────────────────────────────┐
│  1. chaos tune <stem>     calibrate per-clip HSV            │
│       only when chaos track's HSV probe ABORTs              │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  2. chaos track <stem>    standard run                      │
│       runs HSV probe → init/release picker → tracking →     │
│       verify → interpolate (if needed) → verdict card       │
│                                                              │
│       PASS → tracking_quality=verified, you're done         │
│       WARN → review verification.png, accept or fix         │
│       FAIL → fix-up required                                │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  3. chaos fix <stem>      (only if not PASS)                │
│       interactive picker, click correct marker positions    │
│       on the bad frames, P → re-tracks with strict-physics  │
│                                                              │
│       OR  chaos override <stem> --frame N  for one bad row  │
└─────────────────────────────────────────────────────────────┘
```

`chaos next` runs all three steps automatically and prompts you only
where input is needed. Use it as your default; the per-step commands
are there for when you need surgical control.

### When to use `fix` vs `override`

| Scenario | Use |
|---|---|
| One isolated bad frame in a sea of good frames | `chaos override <stem> --frame N` |
| A run of bad frames where the tracker drifted | `chaos fix <stem>` |
| Not sure | `chaos fix <stem>` (it covers both cases) |

## HSV tuner — keyboard reference

`chaos tune <stem>` opens the tuner. Default mode is GREEN.

| Key | Action |
|---|---|
| `LEFT-CLICK` | Sample a circle of the current radius around the cursor; HSV-similarity filter keeps only matching pixels |
| `[` / `]` | Shrink / grow the click sample radius (5 → 60 px in steps of 5) |
| `G` / `R` | Switch active marker (GREEN ↔ RED) |
| `M` | Cycle overlay level: FULL → MINIMAL → CLEAN |
| `Z` | Toggle zoom loupe (top-left corner, follows cursor) |
| `+` / `-` | Cycle zoom magnification (2× → 8×) |
| `D` / `A` | Step ±1 frame |
| `→` / `←` | Step ±50 frames |
| `T` | Cycle ring tolerance (20 → 30 → 40 px) |
| `C` | Clear sampled points for the active marker |
| `S` | Save → writes `data/hsv_<clip stem>.json` |
| `Q` / `ESC` | Quit |

**How sampling works**: hover the cursor over a marker — a circle of
the current click radius previews what would be sampled. Click. The
tool keeps every pixel in the circle whose HSV is close to the centre
pixel's, so the radius can be generous (default 25 px) without
polluting the bucket with background. The script auto-advances to the
next of 4 reference frames spread across the clip after each
successful sample, so a single G/click → R/click pass naturally
covers lighting variation.

## Manual fix-up — keyboard reference

`chaos fix <stem>` opens the picker pre-positioned at the worst suspect
frame. Default mode is GREEN.

| Key | Action |
|---|---|
| `LEFT-CLICK` | Set the seed for the active marker AT THIS FRAME |
| `G` / `R` | Switch active marker |
| `n` | Jump to next suspect frame |
| `X` | Delete this frame's seed |
| `a` / `d` | ±1 frame  |
| `A` / `D` | ±10 frames |
| `z` / `x` | ±100 frames |
| `Z` | Toggle zoom loupe |
| `M` | Cycle overlay level |
| `+` / `-` | Cycle zoom magnification |
| **`P` (or `ENTER`)** | Save seeds + re-track + verify + verdict |
| `S` | Save seeds without re-tracking |
| `Q` / `ESC` | Quit |

## Outputs

Per measurement, in `measurements/<stem>/`:

| File | What it is |
|---|---|
| `tracking.csv` | Per-frame angles (the main output) |
| `verification.csv` | tracking.csv + ω columns + suspect flag |
| `verification.png` | θ and ω timelines, suspect frames highlighted |
| `phase_panels.png` | 6-panel physics-sanity figure |
| `phase_3d_trajectory.png` | 3-D phase ribbon |
| `seeds.json` | Manual marker positions you set with `chaos fix` |

Plus the cross-clip Excel report: `data/status_report.xlsx`
(regenerate any time with `chaos report`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `chaos: command not found` (PowerShell) | Use `.\chaos <cmd>` (PowerShell needs the `.\`) |
| `HSV adequacy below 40%` (ABORT) | `chaos tune <stem>` |
| Detected red marker sits on user's hand / skin | In the tuner, push S_min to ~140 to filter low-saturation skin |
| Tracker latches onto a moving artifact for several frames | `chaos fix <stem>`, click correct positions on the bad frames |
| One isolated bad frame | `chaos override <stem> --frame N` |
| `chaos next` is blocked at a prompt | Run from cmd / PowerShell / a real shell, not from a hooked stdout |

## Project layout

```
chaos/
├── chaos.py / chaos.bat / chaos.ps1 / chaos.sh   wrappers
├── scripts/
│   ├── processing/   tracking primitives  (hsv_tuner, ring_tracker, ...)
│   ├── analysis/     plots / animations    (post-tracking, optional)
│   └── utils/        orchestrators         (track_one, manual_correction, ...)
├── docs/PIPELINE.md  detailed reference for every stage
├── measurements/     per-clip output folders (tracking.csv etc.)
├── data/             registry, HSV calibration, status report
├── Videos/           raw .mov files (gitignored, fetched via Drive)
└── archive/          superseded scripts, kept for reference
```

## Where to learn more

- **`chaos help`** — this cheat sheet at any time
- **[`docs/PIPELINE.md`](docs/PIPELINE.md)** — keystroke-level reference for every stage, troubleshooting, internals
- **`chaos <cmd> --help`** — full flag list for any subcommand
- **`scripts/processing/*.py`** — the underlying tracker (read the module docstrings if you're modifying it)

## Camera / rig (reference)

| Field | Value |
|---|---|
| Resolution | 1280×720 @ 59.94 fps |
| Pivot pixel | `(608, 355)` (fixed) |
| Arm length | 35 cm each (≈ 188 px) |
| Scale | 0.186 cm/px |
| Angle convention | 0° = down, +90 = right, −90 = left, ±180 = up |

| Marker | Role | Detection method |
|---|---|---|
| 🟡 Yellow | Wall pivot | Hard-coded, not detected |
| 🟢 Green  | Joint between arm 1 and arm 2 | HSV inside an annulus around the pivot |
| 🔴 Red    | Tip of arm 2 | HSV inside an annulus around the green marker |
