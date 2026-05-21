# Chaos — Diodes, RLD circuits, and the Double Pendulum

A semester of nonlinear-dynamics experiments from the HUJI undergraduate
physics lab (Lab B2, 2026). Four experiments over six weeks, each
exploring a different route into chaos:

| Weeks | Apparatus | Phenomenon |
|---|---|---|
| **[Week 1](experiments/week1-diode-iv/)** | Diode + oscilloscope | I-V characterisation, Shockley fit, junction capacitance C(V) |
| **[Week 2](experiments/week2-rld-bifurcation/)** | RLD circuit + scope | Period-doubling cascade to chaos at ~34 kHz |
| **[Weeks 3–4](experiments/week3-4-pendulum-free-swing/)** | Free-swinging double pendulum | Transient chaos, IC sweep, phase portraits, λ₁ |
| **[Weeks 5–6](experiments/week5-6-pendulum-motor-driven/)** | Motor-driven double pendulum | Steady-state attractor, stroboscopic Poincaré, bifurcation across f_drive |

The repo doubles as **a working tracking pipeline** for the double-pendulum
video data and **a documented record** of the analyses we ran. If you're
a future student doing this lab — start with [Quickstart](#quickstart)
below, then read the section for the experiment you're on.

---

## Repository layout

```
chaos/
├── experiments/                  per-week lab work — data, figures, measurements, docs
│   ├── week1-diode-iv/                    Shockley-fit + C(V) analysis scripts
│   ├── week2-rld-bifurcation/             discrete + continuous bifurcation map
│   ├── week3-4-pendulum-free-swing/       free-swing measurements + figures
│   └── week5-6-pendulum-motor-driven/     driven measurements + figures + calibration
│
├── scripts/                      shared video-tracking & analysis pipeline (weeks 3–6)
│   ├── processing/   BGR marker tracker + verification
│   ├── analysis/     post-tracking physics figures (phase portraits, Poincaré, …)
│   └── utils/        registry, status, batch drivers, calibration helpers
│
├── chaos.py + chaos.{bat,ps1,sh} unified CLI entry point — `chaos <command>`
│
├── legacy/                       collaborator reference (untouched — DO NOT EDIT)
│   └── cohen_get_video_coords.py
│
├── archive/                      one-shot, setup, and regression scripts (out of the way)
│   └── scripts/utils/            see archive/scripts/utils/README.md
│
├── reports/                      writeups for the course
│   ├── lab-assignment.pdf
│   ├── weekly/                   short catch-up reports
│   ├── interim/                  midterm-style summaries
│   │   ├── 01_week1-2_diode-rld/
│   │   └── 02_week3-4_pendulum-free/
│   └── final/
│       └── week5-6_pendulum-motor-driven/
│
└── requirements.txt
```

---

## Quickstart

```bash
git clone https://github.com/Shakedsuki/HUJI-lab-b2
cd HUJI-lab-b2
pip install -r requirements.txt
```

Tested on **Python 3.13 / Windows 11**; macOS + Linux work too.

For the pendulum weeks you also need the raw videos — they're **not in
git** because each .mov is ~50 MB. Pull them from Drive:

```bash
python archive/scripts/utils/download_videos.py    # → experiments/week3-4-pendulum-free-swing/data/videos/
```

Drive folder: [כאוס on Google Drive](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-).
The week 5–6 motor-driven videos need to be copied separately into
`experiments/week5-6-pendulum-motor-driven/videos/`.

### Running the CLI

From the repo root:

```bash
# bash / cmd
chaos status
chaos help

# PowerShell needs the .\
.\chaos status
```

To drop the `.\` in PowerShell add this to your `$PROFILE`:

```powershell
function chaos { & "C:\dev\chaos\chaos.ps1" @args }
```

The CLI defaults to the free-swing phase. Switch via the
`CHAOS_PHASE` environment variable:

```powershell
$env:CHAOS_PHASE = "week5-6-pendulum-motor-driven"   # motor-driven
$env:CHAOS_PHASE = "week3-4-pendulum-free-swing"     # free-swing (default)
```

Legacy values from earlier refactors (`phase1-free-swing`, `phase2-motor-driven`,
`week3-pendulum-free-swing`, `week4-pendulum-motor-driven`) still work — they're
aliased to the new paths in `scripts/utils/paths.py`.

---

## Week 1 — Diode characterisation

Folder: [`experiments/week1-diode-iv/`](experiments/week1-diode-iv/)

Characterises a silicon diode (1N4005): measures the I-V curve, fits the
Shockley equation $I = I_S(e^{V/nV_T} - 1)$, and extracts the junction
capacitance $C_j(V) \propto 1/\sqrt{V}$ via direct exponential discharge fits.

### Scripts

| Script | Input | Output |
|--------|-------|--------|
| `iv_graph.py` | `samples/square/*.csv` | Square-wave I-V with full Shockley + series-resistance fit |
| `iv_from_triangle.py` | `samples/triangle/f_*.csv` | Triangle-wave I-V with per-cycle ensemble Shockley fit |
| `dischargetimes.py` | `samples/square discharge/*.csv` | Junction capacitance C(V); C ~ a/√V + c |
| `run_fits.py` | — | Canonical runner: regenerates Fig 1 + Fig 2 + Fig 3 PNGs + JSONs |
| `tek_csv.py` | — | Tektronix DPO CSV loader (helper module) |

### Data

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

| Script | Input | Output |
|--------|-------|--------|
| `get_cycles.py` | `samples/*.csv` | Discrete bifurcation map (one fixed amplitude per file) |
| `get_return_map.py` | `samples/*.csv` | Return maps with colorbar |
| `bifurcation_continuous.py` | `samples/AM/7V.csv` | Continuous bifurcation map via Hilbert envelope + peak detection — 2D PNG + interactive 3D Plotly HTML |

### Key physics

- **Period-doubling cascade:** P1 → P2 → P4 → chaos as the AM envelope sweeps up
- **Hysteresis:** bifurcation transitions occur at different amplitudes on upswing vs downswing (finite relaxation time)
- **Carrier:** ~34 kHz, FFT-confirmed — LC resonance with effective junction capacitance

### Data

Raw oscilloscope CSVs in `experiments/week2-rld-bifurcation/samples/`
(gitignored).

### Writeup

[`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/) — same interim as week 1.

---

## Weeks 3–4 — Free-swinging double pendulum

Folder: [`experiments/week3-4-pendulum-free-swing/`](experiments/week3-4-pendulum-free-swing/)

The double pendulum is released from a range of initial-condition pairs
`(θ₁, θ₂)` and allowed to swing freely. This is **transient chaos** —
energy dissipates over ~30 s, so each clip captures a single trajectory
from launch to rest. The tracking pipeline in [`scripts/`](scripts/)
turns each video into per-frame angles + angular velocities, with a
PASS / FAIL verdict on tracking quality.

### Current data status

```
28 clips total
  17  good         tracked, post-bgr_tracker, dropout < 5%
   5  verified     visually approved end-to-end
   6  review       flagged for re-track or override
```

### What's in each measurement folder

`experiments/week3-4-pendulum-free-swing/measurements/<stem>/`:

| File | Source | Description |
|---|---|---|
| `tracking.csv` | `chaos track` | per-frame angles + marker pixels |
| `verification.csv` | `chaos verify` | + ω, suspect flags from physics checks |
| `verification.png` | `chaos verify` | θ / ω timelines, suspect dots |
| `verification_meta.json` | `chaos verify` | run-level metadata (pivot drift, E_release) |
| `combined.mp4` | `chaos render` | source video + marker overlay + phase plots |
| `phase_panels.png`, `phase_3d_*` | analysis scripts | post-tracking physics figures |

Cross-clip rollup at `experiments/week3-4-pendulum-free-swing/data/status_report.xlsx`
(regenerate via `chaos report`) and `experiments/week3-4-pendulum-free-swing/docs/tracking_roadmap.md`
(`chaos roadmap`).

### Writeup

[`reports/interim/02_week3-4_pendulum-free/`](reports/interim/02_week3-4_pendulum-free/)
— "Expansion report 1": LyX source, PDF, figures.

### More

- [`experiments/week3-4-pendulum-free-swing/docs/PIPELINE.md`](experiments/week3-4-pendulum-free-swing/docs/PIPELINE.md) — keystroke-level walkthrough (pre-BGR pipeline archive)
- The CLI section below documents every `chaos <command>` you'll need.

---

## Weeks 5–6 — Motor-driven double pendulum

Folder: [`experiments/week5-6-pendulum-motor-driven/`](experiments/week5-6-pendulum-motor-driven/)

A driven, damped double pendulum: a DC drill (Black & Decker) oscillates
Arm 1 (upper arm) at a controlled frequency `f_drive` and amplitude
proportional to `V_drill`. Arm 2 (lower arm) hangs free from Pivot β.
Continuous energy input from the motor balances dissipation, so the
system sustains a **strange attractor** (unlike the transient chaos
of weeks 3–4).

The control space is 2D: **`f_drive` (Hz) × `V_drill` (V)**.
A V_drill sweep at fixed f_drive produces a period-doubling cascade
(P1 → P2 → P4 → chaos), mirroring the RLD results from week 2.

### Control parameters

| Parameter | Physical meaning | Set via |
|---|---|---|
| `f_drive` | Driving frequency (Hz) | Function generator → relay |
| `V_drill` | Driving-amplitude proxy | Bench supply Ch2 |

### Clip naming convention

```
<voltage>V_<freq>Hz                e.g.  3.2V_1.20Hz
fd_<freq>_vd_<voltage>             e.g.  fd_1p5_vd_4v0   (specification form)
```

### Current data status

```
62 clips total
   9  verified     visually approved end-to-end under the BGR tracker
   9  unreviewed   tracked but not yet watched in overlay
  44  untracked    raw .mov captured, not yet through bgr_tracker
```

### Week 5 vs Week 6 split

The 62 clips were recorded across two lab sessions. The `measurements/`
directory is split accordingly:

| Bucket | Clips | What |
|---|---|---|
| `measurements/week5/` | 29 | The broad V/f survey (2.4V–4V × 0.25Hz–2Hz). Includes `3.2V_1Hz`. |
| `measurements/week6/` | 33 | The focused 3.2V resonance sweep (0.9Hz–1.34Hz). Excludes `3.2V_1Hz` (recorded in week 5 on the original rig). |

Routing rule, baked into `paths.clip_dir(stem)`: stems matching `3.2V_*`
go to `week6/`, except `3.2V_1Hz` which lives in `week5/`. Every clip
the bgr_tracker produces lands in the right bucket automatically;
nothing in the analysis scripts needs to know about the split.

The 3.2V sweep dominates the dataset (34 clips total — 33 in week6 +
1 in week5); the rest is the coarser V/f grid in week5.

### Deliverables (figures we produce per clip / sweep)

- Phase portraits (`phase_panels.png`)
- Stroboscopic Poincaré sections at θ₁ = 0, ω₁ > 0 (`driven_poincare.csv` + PNG)
- Bifurcation diagram — peak θ₂ vs V_drill or f_drive
- Return maps
- Lyapunov exponent λ₁
- 3D phase animation

### Documentation

- [`docs/SYSTEM_SETUP.md`](experiments/week5-6-pendulum-motor-driven/docs/SYSTEM_SETUP.md) — apparatus, circuit, electronics, physics reference
- [`docs/DRIVEN_FIGURES_SPEC.md`](experiments/week5-6-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md) — figure-by-figure specification (algorithms, signatures, recording requirements)
- [`docs/driven_pendulum_circuit.html`](experiments/week5-6-pendulum-motor-driven/docs/driven_pendulum_circuit.html) — annotated HTML circuit diagram (DPDT relay, signal chain, mechanical output)
- [`calibration/`](experiments/week5-6-pendulum-motor-driven/calibration/) — `calibrate_pivot.py` + reference frames for the Pivot α / arm-length-pixel fit

### Writeup

[`reports/final/week5-6_pendulum-motor-driven/`](reports/final/week5-6_pendulum-motor-driven/) — "Expansion report 2": LyX source, PDF, per-clip phase-panel PNGs.

---

## The pendulum tracking pipeline

The same software stack handles both weeks 3–4 and 5–6. Set
`CHAOS_PHASE` to pick which phase you're working on.

### What it does (per clip)

1. **Detect markers** — Cohen's BGR-thresholding logic (preserved verbatim in [`legacy/cohen_get_video_coords.py`](legacy/cohen_get_video_coords.py); the production wrapper is [`scripts/processing/bgr_tracker.py`](scripts/processing/bgr_tracker.py))
2. **Crop** — a tight bbox around the pivot reduces background noise; an inscribed disc mask removes everything outside the reachable region
3. **Project onto the rigid-arm constraint** — green/red marker positions are re-projected onto the pivot-circle and green-circle, killing sub-pixel jitter without smoothing the dynamics
4. **Compute angles** — θ₁, θ₂ in degrees (0° = straight down, +90° = right)
5. **Verify** — physics checks flag suspect rows (Δω spikes, energy ceiling, arm-length drift); a single dropout rate determines PASS / FAIL
6. **Render** — `<stem>_overlay.mp4` shows the source video with the detected markers and constraint circles drawn every frame for visual verification

### CLI cheat-sheet

```
PIPELINE  (per-clip flow)
  chaos track <stem>             track + verify + verdict
  chaos verify <stem>            standalone QA on existing tracking.csv
  chaos render <stem>            render combined.mp4 (video + overlay + phase plots)

BATCH / DRIVER
  chaos next                     drive the pending queue end-to-end (interactive)
  chaos bulk [--dry-run]         unattended sequential pass over plannable clips

INSPECTION
  chaos status                   tracked / pending
  chaos roadmap                  per-clip status table (docs/tracking_roadmap.md)
  chaos report                   Excel summary (data/status_report.xlsx)

REGISTRY
  chaos audit                    re-validate verified clips against current logic
  chaos audit --apply            downgrade clips that no longer pass
  chaos audit --upgrade --apply  also promote new PASSes to verified

ANALYSIS
  chaos analyze <stem>           chaos physics: 0-1 test, spectral entropy, verdict
  chaos poincare <stem>          true 2D Poincaré section (θ₁+θ₂=0)
  chaos driven-poincare <stem>   stroboscopic Poincaré (motor-driven; samples at T = 1/f_drive)
  chaos driven-bifurcation       bifurcation across a V_drill or f_drive sweep
  chaos lyapunov <stem>          λ₁ estimate

  chaos help                     full cheat-sheet on stdout
  chaos <cmd> --help             flags for any subcommand
```

`<stem>` is the `config_description` — the folder name under `measurements/`.

### Verdict bands

- **PASS** — tracking_quality auto-set to `verified` after visual review; ready for downstream analysis
- **FAIL** — dropout > 5 %; needs a re-track with adjusted thresholds (or a manual fix via `archive/scripts/utils/override_frame.py` for one-off frame issues)

> **Note:** in this lab the *visual overlay video is the test*, not just
> the numerical dropout. 0 % dropout is necessary but not sufficient —
> always watch `<stem>_overlay.mp4` end-to-end before marking a clip
> verified. We learned this the hard way on the 3.2V sweep.

### Registry schema (`experiments/<phase>/data/experiments.json`)

Each entry is keyed by `config_description` and carries:

```json
{
  "video_file": "3.2V_1.20Hz.mov",
  "config_description": "3.2V_1.20Hz",
  "drive_voltage_v": 3.2,
  "drive_freq_hz": 1.20,
  "repeat_number": 1,
  "arm_length_cm": 33.1,
  "arm_length_px": 153,
  "pivot_px": [663, 332],
  "scale_cm_per_px": 0.2160,
  "tracker": "bgr",
  "measurements_dir": "measurements/3.2V_1.20Hz",
  "csv_file": "tracking.csv",
  "tracking_quality": "verified",
  "duration_s": 38.49,
  "dropout_rate_pct": 0.0,
  "theta1_initial": 0.0,
  "theta2_initial": 0.0,
  "omega1_initial": null,
  "omega2_initial": null,
  "n_frames": 2307,
  "notes": "",
  "verification_notes": ""
}
```

---

## Reports

| Path | Audience | What's in it |
|---|---|---|
| [`reports/lab-assignment.pdf`](reports/lab-assignment.pdf) | original | Course assignment (Diodes + RLC + Dynamical Systems, 2025) |
| [`reports/weekly/`](reports/weekly/) | instructor | Lightweight catch-up notes |
| [`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/) | course | Interim report — weeks 1–2 (diode + RLD) |
| [`reports/interim/02_week3-4_pendulum-free/`](reports/interim/02_week3-4_pendulum-free/) | course | Interim report — weeks 3–4 ("Expansion report 1") |
| [`reports/final/week5-6_pendulum-motor-driven/`](reports/final/week5-6_pendulum-motor-driven/) | course | Final report — weeks 5–6 motor-driven ("Expansion report 2") |

---

## For future students

A few notes from running this lab in 2026 that might save you time:

- **Don't skip visual verification of tracking output.** A clip with 0 % dropout can still have systematic marker confusion — the overlay video is the only way to catch it. See the notes in `scripts/processing/bgr_tracker.py` and the verdict-card mechanism.
- **The pivot is rig-specific and per-batch.** Weeks 3–4 used a 35 cm arm at pivot (608, 355); weeks 5–6 used a 33.1 cm arm at pivot (663, 332) after the rig was repositioned. The 3.2V sweep needed its own pivot (583, 331). See [`scripts/utils/thresholds.py`](scripts/utils/thresholds.py) and `thresholds.get_pivot_arm(stem)`.
- **Frame your videos so the pivot is well-lit and away from reflections.** The BGR tracker uses fixed colour ranges (no per-clip tuning); reflective surfaces near the green marker are the dominant failure mode.
- **The double pendulum is louder than you expect** — clamp the apparatus to a heavy bench.
- **For the motor-driven setup**, the function-generator → relay → drill chain has subtle phase issues; the `docs/driven_pendulum_circuit.html` diagram in week 5–6 documents the working configuration.

For the physics and analysis methodology, read the writeups under
[`reports/`](reports/). For software questions, every script has a
docstring; start with `chaos help` and `chaos <cmd> --help`.

---

## Dependencies

See [`requirements.txt`](requirements.txt). The main external libraries
are NumPy, SciPy, OpenCV, Matplotlib, Plotly, pandas, and openpyxl. No
GPU is required — the BGR tracker is fast enough on CPU.

---

## Acknowledgements

The BGR detection logic is N. Cohen's — preserved verbatim in
[`legacy/cohen_get_video_coords.py`](legacy/cohen_get_video_coords.py) as
the regression reference for `scripts/processing/bgr_tracker.py`.
