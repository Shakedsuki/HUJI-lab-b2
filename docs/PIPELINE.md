# Pipeline reference — keystroke-level workflow

This is the canonical per-clip workflow for tracking new recordings end
to end with the `chaos` command. The high-level entry point handles
everything; this document explains what each stage looks like at the
keystroke level so you can recover when something goes off-script.

## TL;DR

```bash
chaos next     # interactive driver — processes pending clips one after another
```

That single command:

1. Picks the next pending clip
2. Probes HSV adequacy → optionally launches the tuner if the
   calibration is poor
3. Runs `track_one` (HSV probe → smart init/release picker → tracking →
   verify → interpolate-if-needed → verdict card)
4. On WARN/FAIL, prompts you to fix manually with `chaos fix`
5. On PASS, marks the registry entry `tracking_quality=verified`
6. Asks whether to continue to the next clip

You can interrupt anytime with `q` and resume later — state is
persisted to `experiments.json` and `seeds.json`.

## Stage 1 — Calibrate HSV (only when needed)

Triggered automatically by the HSV adequacy probe, or manually with
`chaos tune <stem>`. The tuner opens paused at frame 0 in GREEN mode.

### Find a representative reference frame

Goal: a frame where the green marker is **well-lit, in focus, against
clean wall**. Usually the holding phase, around the registry's
`tag_frame`.

| Key | Action |
|-----|--------|
| `→` / `←` | Skip ±50 frames quickly |
| `D` / `A` | Step ±1 frame |
| `Z` | Toggle zoom loupe (top-left corner, follows cursor) |
| `+` / `-` | Cycle zoom magnification (2× → 8×; 4× is the default) |
| `M` | Cycle overlay level FULL → MINIMAL → CLEAN |

Use **CLEAN** while sampling — the rings would otherwise obscure the
actual marker pixels.

### Sample marker pixels (diversity wins)

The auto-suggester takes `min/max(H,S,V)` across all your clicks and
pads ±15 (hue) / ±20 (sat, val). The output range only covers what you
sampled, so:

- **Click ~2–3 pixels per frame**, **across 3–4 frames per marker**.
- Each frame should look meaningfully different (lighting, motion blur,
  pendulum angle).
- Center + one edge per frame is plenty. Don't click 8 pixels on one
  marker in one frame — they're nearly identical and give the suggester
  no diversity.

```
Reference frame  (well-lit, sharp)        2–3 clicks
Mid-swing frame  (low velocity)           2–3 clicks
Chaotic frame    (motion blur — critical) 2–3 clicks
Late settling                              1–2 clicks (skip if covered)
```

After 5 clicks the auto-suggester fires automatically and pushes new
HSV ranges into the trackbars. Switch to RED mode (`R`) and repeat.

### Validate across the clip

Press `M` back to FULL. Scrub through 5–6 representative frames
(holding, post-release, mid-chaos, settling, last frame). Both rings
should lock on both markers at every frame. If one fails, sample 1–2
more pixels from THAT frame.

### Save & quit

| Key | Action |
|-----|--------|
| `S` | Save → writes `data/hsv_<clip stem>.json` |
| `Q` | Quit |

## Stage 2 — Track + verify (`chaos track <stem>`)

Internally runs `track_one.py`, which is:

1. **HSV adequacy probe** — samples 30 frames evenly. Three verdicts:
   - **OK** (≥70%) — proceed
   - **WARN** (40–70%) — prompts (auto-confirmed in `chaos next` if
     the user just tuned)
   - **ABORT** (<40%) — non-zero exit, refuses to track

2. **Smart init/release scan + picker** — pre-positions both pickers
   at sensible candidates. Confirm with `ENTER` if the green/red rings
   are locked on the markers; scrub with `a/d`, `A/D`, `z/x` otherwise.

3. **Tracking** runs unattended (1–3 min for 25 s clips, longer for
   long recordings). The predictor is seeded from
   `green_click_px` / `red_click_px` when `tag_frame` is within 3
   frames of `init_frame`.

4. **Verification** runs against the new tracking.csv at the default
   |ω| cap of 2500 °/s. Hidden suspects (dropout=0 but |ω| > cap)
   get flagged.

5. **Interpolation** runs only if there are hidden suspects. Replaces
   each suspect frame with a linear interpolation between its nearest
   clean neighbours; re-runs verify.

6. **Verdict card** is printed. Fields:
   - `dropout` — free-swing dropout %, plus split by phase
   - `peak |ω₁|`, `peak |ω₂|` — annotated against the 1500 °/s
     physical rule-of-thumb
   - `suspects (pre)`, `suspects (post)` — pre / post interpolation
   - `reasons` — what nudged the verdict

7. **Auto-mark** on PASS — `tracking_quality=verified`,
   `verification_date` are written to the registry.

### Verdict bands

| Verdict | Conditions | Action |
|---------|-----------|--------|
| **PASS** | dropout < 5% AND no residual suspects AND peak \|ω₂\| ≤ 1500 °/s | done; auto-verified |
| **WARN** | dropout 5–10% OR residual suspects OR peak \|ω₂\| 1500–4000 | review verification.png; manually accept or fix |
| **FAIL** | dropout > 10% OR peak \|ω₂\| > 4000 OR a subprocess errored | fix-up required |

## Stage 3 — Manual fix-up (`chaos fix <stem>`)

Triggered automatically by `chaos next` when the verdict isn't PASS,
or manually for spot fixes. Runs `manual_correction.py`, which opens
an interactive picker pre-positioned at the worst suspect frame.

| Key | Action |
|-----|--------|
| `G` / `R` | Switch active marker |
| `n` | Jump to next suspect frame |
| **LEFT-CLICK** | Set the seed for the active marker AT THIS FRAME |
| `X` | Delete this frame's seed |
| `a` / `d` | ±1 frame |
| `A` / `D` | ±10 frames |
| `z` / `x` | ±100 frames |
| `Z` | Toggle zoom loupe |
| `M` | Cycle overlay level |
| `+` / `-` | Cycle zoom magnification |
| **`P` (or `ENTER`)** | Save seeds.json + re-track from earliest seed forward + re-verify + verdict card |
| `S` | Save seeds without re-tracking |
| `Q` / `ESC` | Quit |

### How seeds work

Each seed asserts the correct marker positions at one frame. On `P`,
ring_tracker re-runs with `--seeds-file --strict-physics`. Each seed:

1. **Writes the seed values** verbatim into the corresponding row of
   `tracking.csv`.
2. **Re-anchors the predictor** at that frame so the arc filter is
   immediately active.
3. **Opens a strict-physics window** for the next 30 frames. In strict
   mode, every fallback stage of the tracker gets a hard angular gate
   (≈82 px at ω=0, scaling to ≈205 px at the 1500 °/s physical max).
   Out-of-gate candidates are rejected; if no in-gate candidate exists,
   the row becomes `dropout=1` instead of falling through to a far-away
   blob (which is what produces silent false positives).

For a clip where the strict-physics window of 30 frames isn't enough to
re-stabilise tracking, place a second seed inside that window. Each
seed extends the strict-mode window by another 30 frames.

### `--from-frame` semantics

When a `tracking.csv` already exists AND the earliest seed is at frame
`N > 0`:

- Rows `0..N-1` are preserved verbatim from the existing CSV.
- Frames `N..end` are re-tracked with `--strict-physics` and seeds.

This means a manual fix at frame 130 doesn't re-do frames 0..129 — the
predictor is re-seeded from row 129 of the existing CSV, then strict
mode kicks in from frame 130.

## Stage 4 — Status / report

```bash
chaos status     # one-screen text summary
chaos report     # writes data/status_report.xlsx (Excel)
```

The Excel report has two sheets:

- **Measurements** — every regular clip with live dropout stats
  computed from each tracking.csv, presence ticks for the eight
  canonical files, and a derived status string.
- **long_recording** — separate row for the long recording with extra
  columns (duration, free-swing frame count, suspect frame count,
  energy proxy).

## Troubleshooting cheat sheet

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| HSV probe ABORTs | global HSV doesn't fit this clip | `chaos tune <stem>` |
| HSV probe WARN borderline | small lighting variation | tune with samples from chaotic frames |
| Detected red sits on user's hand | skin matches red HSV range | `chaos tune` — push `s_min` to ~140 to filter low-saturation skin |
| Detected green sits on jacket / wall poster | green HSV too permissive | tune with tighter sat range |
| Track passes but verify flags hidden suspects in motion-blurred regions | tracker latched briefly to arm shaft | `chaos fix <stem>` — seed the worst suspect frame, strict-physics handles the rest |
| `--from-frame` errors with "requires existing CSV" | passed `>0` but no prior track | run `chaos track <stem>` first; or set seed at frame 0 to track from scratch |
| `chaos next` is blocked at HSV prompt | terminal isn't interactive | run from cmd / PowerShell / a real shell, not via a hooked stdout |

## File map for a "complete" measurement

```
measurements/<config_description>/
├── tracking.csv          (gitignored — main output)
├── verification.csv      (gitignored — verify output)
├── debug.mp4             (gitignored — annotated video)
├── phase_3d_trajectory.png   ← tracked
├── phase_3d_rotation.mp4     (gitignored)
├── phase_animation.mp4       (gitignored)
├── phase_panels.png          ← tracked
├── verification.png          ← tracked
├── combined.mp4              (gitignored)
└── seeds.json                ← tracked when present (human ground truth)
```

All paths assume the measurement folder is keyed by the clip's
`config_description` (e.g. `th1_p047_th2_m002`). The registry's
`measurements_dir` field carries this path.
