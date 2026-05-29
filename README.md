# Chaos — Diodes, RLD circuits, and the Double Pendulum

A semester of nonlinear-dynamics experiments from the HUJI undergraduate
physics lab (Lab B2, 2026). Four experiments over six weeks, each
exploring a different route into chaos:

| Weeks                                                     | Apparatus                     | Phenomenon                                                            |
| --------------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------- |
| **[Week 1](experiments/week1-diode-iv/)**                 | Diode + oscilloscope          | I-V characterisation, Shockley fit, junction capacitance C(V)         |
| **[Week 2](experiments/week2-rld-bifurcation/)**          | RLD circuit + scope           | Period-doubling cascade to chaos at ~34 kHz                           |
| **[Weeks 3–4](experiments/week3-4-pendulum-free-swing/)** | Free-swinging double pendulum | Transient chaos, IC sweep, phase portraits, λ₁                        |
| **[Week 5](experiments/week5-pendulum-motor-driven/)**    | Motor-driven double pendulum  | Broad V/f survey — period-doubling across drive parameters            |
| **[Week 6](experiments/week6-pendulum-motor-driven/)**    | Motor-driven double pendulum  | 3.2 V resonance sweep — stroboscopic Poincaré, bifurcation, rotations |

The repo doubles as **a working tracking pipeline** for the double-pendulum
video data and **a documented record** of the analyses we ran. The whole
pipeline is driven from an **interactive terminal shell** — run `chaos`
with no arguments (see [The `chaos` shell](#the-chaos-shell)). If you're a
future student doing this lab, start with [Quickstart](#quickstart) below,
then read the section for the experiment you're on.

---

## Repository layout

```
chaos/
├── experiments/                  per-experiment work — data, figures, measurements, docs
│   ├── week1-diode-iv/                  Shockley-fit + C(V) analysis scripts
│   ├── week2-rld-bifurcation/           discrete + continuous bifurcation map
│   ├── week3-4-pendulum-free-swing/     free-swing measurements + figures
│   ├── week5-pendulum-motor-driven/     driven — broad V/f survey (29 clips)
│   └── week6-pendulum-motor-driven/     driven — 3.2V resonance sweep (33 clips)
│       ├── measurements/<stem>/   per-clip tracking + analysis outputs
│       ├── figures/<type>/        static PNG figures only (QA-gated)
│       ├── animations/<type>/      MP4 / animated outputs (overlays, rotations)
│       ├── videos/                 source .mov clips
│       ├── calibration/            pivot / arm-length-pixel fit
│       ├── docs/                   setup notes + figure specs
│       └── data/                   experiments.json registry + .xlsx exports
│
├── scripts/                      shared video-tracking & analysis pipeline (weeks 3–6)
│   ├── processing/   BGR marker tracker + verification
│   ├── analysis/     post-tracking physics (phase portraits, Poincaré, λ₁, rotations, …)
│   └── utils/        shell (TUI hub), registry, batch drivers, paths, calibration
│
├── chaos.py + chaos.{bat,ps1,sh}  entry point — run `chaos` to launch the shell
│
├── archive/                      out-of-the-way bucket
│   ├── cohen_get_video_coords.py    N. Cohen's BGR detection reference — DO NOT EDIT
│   └── scripts/utils/               one-shot, setup, regression scripts
│
├── reports/                      writeups for the course
│   ├── lab-assignment.pdf
│   ├── interim/                  midterm-style summaries
│   └── final/                    final report (week 6 resonance sweep)
│
└── requirements.txt
```

Each driven phase (week 5, week 6) is **self-contained** — it carries its
own `measurements/`, `figures/`, `animations/`, `videos/`, `calibration/`,
`docs/`, and `data/experiments.json`. Switch between phases with the
`CHAOS_PHASE` environment variable or the shell's `sw` command (see
[Phases](#phases)).

---

## Quickstart

```bash
git clone https://github.com/Shakedsuki/HUJI-lab-b2
cd HUJI-lab-b2
pip install -r requirements.txt
chaos                 # launch the interactive shell  (PowerShell: .\chaos)
```

That's the whole 30-second start — `chaos` drops you into the hub.
Tested on **Python 3.13 / Windows 11**; macOS + Linux work too.

For the pendulum weeks you also need the raw videos — they're **not in
git** because each .mov is ~50 MB. Pull them from Drive:

```bash
python archive/scripts/utils/download_videos.py    # → free-swing data/videos/
```

Drive folder: [כאוס on Google Drive](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-).
The motor-driven videos are copied separately into each driven phase's
`videos/` directory (`experiments/week5-pendulum-motor-driven/videos/`,
`experiments/week6-pendulum-motor-driven/videos/`).

---

## The `chaos` shell

The pipeline's primary interface is an **interactive Rich TUI hub**. From
the repo root just run `chaos` with no arguments (PowerShell: `.\chaos`):

The header shows the active **phase**, an XP-style progress bar, and a
live `verified · tracked · pending` count. Type a one- or two-character
key to act; `-` folds the hub to a compact list, `+` expands it again,
`h` shows help, `q` quits.

To drop the leading `.\` in PowerShell so you can just type `chaos`, add
this to your `$PROFILE`:

```powershell
function chaos { & "C:\dev\chaos\chaos.ps1" @args }
```

### Command groups

**track** — get video into the pipeline:

| key  | action                                                        |
| ---- | ------------------------------------------------------------- |
| `tn` | drive the pending queue end-to-end (track → verify → verdict) |
| `tp` | pick a clip and track just that one                           |
| `tb` | unattended bulk pass over all plannable pending clips         |
| `ts` | sanity check (quick physics/geometry sniff)                   |
| `tv` | verify — QA an existing `tracking.csv`                        |
| `tr` | re-track an already-tracked clip                              |

**analyze** — physics on a tracked clip:

| key  | action                                                                           |
| ---- | -------------------------------------------------------------------------------- |
| `ac` | chaos card — 0-1 test, spectral entropy → CHAOTIC / BORDERLINE / REGULAR         |
| `ap` | true 2D Poincaré section (θ₁+θ₂ = 0)                                             |
| `al` | largest Lyapunov exponent λ₁ (Rosenstein)                                        |
| `ad` | driven (stroboscopic) Poincaré — samples once per drive period                   |
| `ai` | driven bifurcation diagram across a V or f sweep                                 |
| `ar` | rotations — per-arm loop counts & accumulated angle (single clip or 3.2 V sweep) |
| `aq` | quick insights — interactive plot explorer                                       |

**output → figures** (static PNG) and **videos** (animated MP4):

| key  | action                                               | key  | action                                       |
| ---- | ---------------------------------------------------- | ---- | -------------------------------------------- |
| `fs` | one figure: clip × type                              | `vw` | render ring+crop overlay MP4s (multi-select) |
| `fc` | all figure types for one clip                        | `vr` | review overlays — watch & set pass/fail      |
| `ft` | one figure type across all clips                     | `vc` | 1-by-1 combined-video pipeline               |
| `fa` | batch all figures (QA-gated)                         | `va` | batch all combined videos                    |
| `fi` | inventory — coverage grid + fill gaps / row / column | `vi` | inventory — video coverage grid              |

**info / system**: `s` status · `e` export `.xlsx` · `sw` switch phase ·
`p` show resolved paths · `c` calibrate pivot/arm · `h` help · `q` quit.

> **figures are static, animations are animated.** Everything under a
> phase's `figures/<type>/` is a `.png`; every MP4 (overlays, combined
> video, rotation animations) lives under `animations/<type>/`. No command
> in the figures menu ever emits a video.

> **figures are QA-gated.** `fa` / `fi` only build figures for clips whose
> overlay-review verdict is `pass` — figures from un-reviewed tracking are
> not trustworthy. Watch the overlay (`vr`) and pass it first.

---

## Phases

Everything phase-specific (paths, calibration, thresholds) is resolved
from a single environment variable, `CHAOS_PHASE`. **The default is
week 6** (the 3.2 V resonance sweep — the focus of the final report).

| `CHAOS_PHASE`                 | Experiment                                         |
| ----------------------------- | -------------------------------------------------- |
| `week3-4-pendulum-free-swing` | Free-swinging pendulum (weeks 3–4)                 |
| `week5-pendulum-motor-driven` | Motor-driven — broad V/f survey                    |
| `week6-pendulum-motor-driven` | Motor-driven — 3.2 V resonance sweep **(default)** |

Switch interactively with the shell's `sw` command, or set the variable
directly:

```powershell
$env:CHAOS_PHASE = "week5-pendulum-motor-driven"     # broad survey
$env:CHAOS_PHASE = "week3-4-pendulum-free-swing"     # free-swing
```

Legacy values from earlier refactors still resolve transparently (aliased
in `scripts/utils/paths.py`): `phase1-free-swing`, `phase2-motor-driven`,
`week3-pendulum-free-swing`, `week4-pendulum-motor-driven`, and the
pre-split combined `week5-6-pendulum-motor-driven` (→ week 6).

---

## Week 1 — Diode characterisation

Folder: [`experiments/week1-diode-iv/`](experiments/week1-diode-iv/)

Characterises a silicon diode (1N4005): measures the I-V curve, fits the
Shockley equation $I = I_S(e^{V/nV_T} - 1)$, and extracts the junction
capacitance $C_j(V) \propto 1/\sqrt{V}$ via direct exponential discharge fits.

### Scripts

| Script                | Input                            | Output                                                           |
| --------------------- | -------------------------------- | ---------------------------------------------------------------- |
| `iv_graph.py`         | `samples/square/*.csv`           | Square-wave I-V with full Shockley + series-resistance fit       |
| `iv_from_triangle.py` | `samples/triangle/f_*.csv`       | Triangle-wave I-V with per-cycle ensemble Shockley fit           |
| `dischargetimes.py`   | `samples/square discharge/*.csv` | Junction capacitance C(V); C ~ a/√V + c                          |
| `run_fits.py`         | —                                | Canonical runner: regenerates Fig 1 + Fig 2 + Fig 3 PNGs + JSONs |
| `tek_csv.py`          | —                                | Tektronix DPO CSV loader (helper module)                         |

Raw oscilloscope CSVs live in `experiments/week1-diode-iv/samples/`
(gitignored). Acquire from the lab Drive.

### Writeup

[`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/) — full interim covering weeks 1+2.

---

## Week 2 — RLD circuit chaos

Folder: [`experiments/week2-rld-bifurcation/`](experiments/week2-rld-bifurcation/)

Nonlinear dynamics of an RLD circuit (R = 470 Ω, L = 100 mH, 1N4005
diode): period-doubling cascade to chaos as a function of drive amplitude
at ~34 kHz carrier with 0.7 Hz AM envelope.

### Interactive 3D bifurcation map

[**→ Open the interactive 3D plot**](https://shakedsuki.github.io/HUJI-lab-b2/experiments/week2-rld-bifurcation/bifurcation_continuous_3d.html)
(GitHub Pages — enable in repo Settings → Pages → master / root).

### Scripts

| Script                      | Input               | Output                                                                                                 |
| --------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------ |
| `get_cycles.py`             | `samples/*.csv`     | Discrete bifurcation map (one fixed amplitude per file)                                                |
| `get_return_map.py`         | `samples/*.csv`     | Return maps with colorbar                                                                              |
| `bifurcation_continuous.py` | `samples/AM/7V.csv` | Continuous bifurcation map via Hilbert envelope + peak detection — 2D PNG + interactive 3D Plotly HTML |

### Key physics

- **Period-doubling cascade:** P1 → P2 → P4 → chaos as the AM envelope sweeps up
- **Hysteresis:** bifurcation transitions occur at different amplitudes on upswing vs downswing (finite relaxation time)
- **Carrier:** ~34 kHz, FFT-confirmed — LC resonance with effective junction capacitance

### Writeup

[`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/) — same interim as week 1.

---

## Weeks 3–4 — Free-swinging double pendulum

Folder: [`experiments/week3-4-pendulum-free-swing/`](experiments/week3-4-pendulum-free-swing/)

The double pendulum is released from a range of initial-condition pairs
`(θ₁, θ₂)` and allowed to swing freely. This is **transient chaos** —
energy dissipates over ~30 s, so each clip captures a single trajectory
from launch to rest. The tracking pipeline in [`scripts/`](scripts/) turns
each video into per-frame angles + angular velocities, with a PASS / FAIL
verdict on tracking quality.

28 clips recorded. Switch to the free-swing phase (`sw`) and the shell
header shows the live verified / tracked / pending breakdown.

### What's in each measurement folder

`experiments/week3-4-pendulum-free-swing/measurements/<stem>/`:

| File                             | Source           | Description                                 |
| -------------------------------- | ---------------- | ------------------------------------------- |
| `tracking.csv`                   | `track`          | per-frame angles + marker pixels            |
| `verification.csv`               | `verify`         | + ω, suspect flags from physics checks      |
| `verification.png`               | `verify`         | θ / ω timelines, suspect dots               |
| `verification_meta.json`         | `verify`         | run-level metadata (pivot drift, E_release) |
| `combined.mp4`                   | `render`         | source video + marker overlay + phase plots |
| `phase_panels.png`, `phase_3d_*` | analysis scripts | post-tracking physics figures               |

### Writeup

[`reports/interim/02_week3-4_pendulum-free/`](reports/interim/02_week3-4_pendulum-free/)
— "Expansion report 1": LyX source, PDF, figures.

See also [`docs/PIPELINE.md`](experiments/week3-4-pendulum-free-swing/docs/PIPELINE.md)
— keystroke-level walkthrough (pre-BGR pipeline archive).

---

## Weeks 5 & 6 — Motor-driven double pendulum

A driven, damped double pendulum — a DC drill (Black & Decker) oscillates
Arm 1 at frequency `f_drive`, amplitude ∝ `V_drill`; Arm 2 hangs free from
Pivot β.

- **Strange attractor:** motor energy balances dissipation → sustained
  chaos, unlike the transient decay of weeks 3–4.
- **2D control space:** `f_drive` (Hz) × `V_drill` (V); a `V_drill` sweep at
  fixed `f_drive` gives a period-doubling cascade (P1 → P2 → P4 → chaos),
  mirroring week 2's RLD.
- **Clip naming:** `<voltage>V_<freq>Hz` (e.g. `3.2V_1.20Hz`), or spec form
  `fd_<freq>_vd_<voltage>`.

| Parameter | Physical meaning        | Set via                    |
| --------- | ----------------------- | -------------------------- |
| `f_drive` | Driving frequency (Hz)  | Function generator → relay |
| `V_drill` | Driving-amplitude proxy | Bench supply Ch2           |

Split into **two self-contained phases** (the final report is on the week-6
resonance sweep):

### Week 5 — broad V/f survey

Folder: [`experiments/week5-pendulum-motor-driven/`](experiments/week5-pendulum-motor-driven/)

29 clips spanning a coarse grid (≈ 2.4 V–4 V × 0.25 Hz–2 Hz), including
`3.2V_1Hz` (recorded on the original rig before the 3.2 V sweep). This is
the exploratory pass that located the interesting region of parameter
space.

### Week 6 — 3.2 V resonance sweep

Folder: [`experiments/week6-pendulum-motor-driven/`](experiments/week6-pendulum-motor-driven/)

33 clips finely sweeping drive frequency at fixed 3.2 V (≈ 0.9 Hz–1.34 Hz)
through the resonance, where the period-doubling route to chaos is
clearest. This is the dataset the final report analyses. The 3.2 V sweep
was recorded after the rig was repositioned, so it uses its own pivot
calibration — see `thresholds.get_pivot_arm(stem)`.

### Deliverables (per clip / per sweep)

- Phase portraits (`phase_panels.png`)
- Stroboscopic Poincaré sections at the drive period (`driven_poincare`)
- Bifurcation diagram — peak θ₂ vs V_drill or f_drive
- Lyapunov exponent λ₁
- Rotations — per-arm loop counts & accumulated angle (`rotations`, with a
  3.2 V sweep aggregate)
- 3D phase trajectory (static PNG + rotation animation under `animations/`)

### Documentation

- [`docs/SYSTEM_SETUP.md`](experiments/week6-pendulum-motor-driven/docs/SYSTEM_SETUP.md) — apparatus, circuit, electronics, physics reference
- [`docs/DRIVEN_FIGURES_SPEC.md`](experiments/week6-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md) — figure-by-figure specification (algorithms, signatures, recording requirements)
- [`calibration/`](experiments/week6-pendulum-motor-driven/calibration/) — `calibrate_pivot.py` + reference frames for the pivot / arm-length-pixel fit

### Writeup

[`reports/interim/03_week5-6_pendulum-motor-driven/`](reports/interim/03_week5-6_pendulum-motor-driven/) — "Expansion report 2": LyX source, PDF, per-clip phase-panel PNGs.

---

## The pendulum tracking pipeline

The same software stack handles weeks 3–4 and 5–6; `CHAOS_PHASE` picks
which phase you're working on.

### What it does (per clip)

1. **Detect markers** — Cohen's BGR-thresholding logic (preserved verbatim in [`archive/cohen_get_video_coords.py`](archive/cohen_get_video_coords.py); the production wrapper is [`scripts/processing/bgr_tracker.py`](scripts/processing/bgr_tracker.py))
2. **Crop** — a tight bbox around the pivot reduces background noise; an inscribed disc mask removes everything outside the reachable region
3. **Project onto the rigid-arm constraint** — green/red marker positions are re-projected onto the pivot-circle and green-circle, killing sub-pixel jitter without smoothing the dynamics
4. **Compute angles** — θ₁, θ₂ in degrees (0° = straight down, +90° = right)
5. **Verify** — physics checks flag suspect rows (Δω spikes, energy ceiling, arm-length drift); a single dropout rate determines PASS / FAIL
6. **Render** — `<stem>_overlay.mp4` shows the source video with the detected markers and constraint circles drawn every frame for visual verification

### Verdict — two gates

- **Numeric (automatic):** binary. `dropout > 5 %` → **FAIL**; otherwise
  **PASS**. One criterion (`scripts/utils/thresholds.py`).
- **Visual (human):** the overlay-review verdict (`pass` / `fail`), set via
  the shell's `vr`. This is the gate that controls figure generation.

> **The visual overlay video is the test**, not just the numerical
> dropout. 0 % dropout is necessary but not sufficient — always watch
> `<stem>_overlay.mp4` end-to-end (`vr`) before trusting a clip. We learned
> this the hard way on the 3.2 V sweep.

### Registry schema (`experiments/<phase>/data/experiments.json`)

Each entry is keyed by `config_description`.

<details>
<summary>Show a full registry entry</summary>

```json
{
  "video_file": "3.2V_1.20Hz.mov",
  "config_description": "3.2V_1.20Hz",
  "drive_voltage_v": 3.2,
  "drive_freq_hz": 1.2,
  "arm_length_cm": 33.1,
  "arm_length_px": 153,
  "pivot_px": [663, 332],
  "scale_cm_per_px": 0.216,
  "tracker": "bgr",
  "measurements_dir": "measurements/3.2V_1.20Hz",
  "csv_file": "tracking.csv",
  "tracking_quality": "verified",
  "overlay_verdict": "pass",
  "duration_s": 38.49,
  "dropout_rate_pct": 0.0,
  "theta1_initial": 0.0,
  "theta2_initial": 0.0,
  "n_frames": 2307,
  "notes": ""
}
```

</details>

---

## Reports

| Path                                                                                           | Audience   | What's in it                                               |
| ---------------------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------- |
| [`reports/lab-assignment.pdf`](reports/lab-assignment.pdf)                                     | original   | Course assignment (Diodes + RLC + Dynamical Systems, 2025) |
| [`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/)               | course     | Interim report — weeks 1–2 (diode + RLD)                   |
| [`reports/interim/02_week3-4_pendulum-free/`](reports/interim/02_week3-4_pendulum-free/)       | course     | Interim report — weeks 3–4 ("Expansion report 1")          |
| [`reports/interim/03_week5-6_pendulum-motor-driven/`](reports/interim/03_week5-6_pendulum-motor-driven/) | course | Interim report — weeks 5–6 ("Expansion report 2") |
| [`reports/final/`](reports/final/)                                                             | course     | Final report — week 6 resonance sweep (in progress)        |

---

## For future students

A few notes from running this lab in 2026 that might save you time:

- **Don't skip visual verification of tracking output.** A clip with 0 %
  dropout can still have systematic marker confusion — the overlay video is
  the only way to catch it. Watch it with the shell's `vr` before passing.
- **The pivot is rig-specific and per-batch.** Weeks 3–4 used a 35 cm arm at
  pivot (608, 355); the driven rig used a 33.1 cm arm at (663, 332) after
  repositioning; the 3.2 V sweep needed its own pivot (583, 331). See
  [`scripts/utils/thresholds.py`](scripts/utils/thresholds.py) and
  `thresholds.get_pivot_arm(stem)`.
- **Frame your videos so the pivot is well-lit and away from reflections.**
  The BGR tracker uses fixed colour ranges (no per-clip tuning); reflective
  surfaces near the green marker are the dominant failure mode.
- **The double pendulum is louder than you expect** — clamp the apparatus to
  a heavy bench.
- **For the motor-driven setup**, the function-generator → relay → drill
  chain has subtle phase issues; [`docs/SYSTEM_SETUP.md`](experiments/week6-pendulum-motor-driven/docs/SYSTEM_SETUP.md)
  documents the working configuration.

For the physics and analysis methodology, read the writeups under
[`reports/`](reports/). For software questions, every script has a
docstring; or just run `chaos` and press `h` for in-shell help.

---

## Dependencies

See [`requirements.txt`](requirements.txt). The main external libraries are
NumPy, SciPy, OpenCV, Matplotlib, Plotly, pandas, openpyxl, and Rich +
questionary (for the interactive shell). No GPU is required — the BGR
tracker is fast enough on CPU.

---

## Acknowledgements

The BGR detection logic is N. Cohen's — preserved verbatim in
[`archive/cohen_get_video_coords.py`](archive/cohen_get_video_coords.py) as
the regression reference for `scripts/processing/bgr_tracker.py`.
