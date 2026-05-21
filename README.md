# Chaos — Diodes, RLD, and the Double Pendulum

A semester's worth of experiments in nonlinear dynamics and chaos. Each
experiment lives in its own folder under [`experiments/`](experiments/),
labelled by the week range of the lab in which the work was done.

| Weeks | Apparatus | What it covers |
|---|---|---|
| **[Week 1](experiments/week1-diode-iv/)** | Diode + scope | I-V characterization, Shockley fit, junction capacitance C(V) |
| **[Week 2](experiments/week2-rld-bifurcation/)** | RLD circuit + scope | Period-doubling cascade and chaos at ~34 kHz |
| **[Weeks 3–4](experiments/week3-4-pendulum-free-swing/)** | Double pendulum, free swing | Transient chaos, IC sweep, phase portraits, Lyapunov |
| **[Weeks 5–6](experiments/week5-6-pendulum-motor-driven/)** | Motor-driven double pendulum | Driven steady-state attractor, stroboscopic Poincaré, bifurcation across f_drive |

Reports live under [`reports/`](reports/), split into
[`weekly/`](reports/weekly/) (catch-up notes), [`interim/`](reports/interim/)
(midterm-style summaries), and [`final/`](reports/final/) (week 5–6 motor-driven).

Top-level layout:

```
experiments/    per-week lab work (data, figures, measurements, docs)
scripts/        shared video-tracking & analysis pipeline
reference/      collaborator reference scripts (preserved verbatim)
reports/        weekly / interim / final
archive/        dated session handoffs and snapshots
```

---

## Week 1 — Diode Characterisation ([`experiments/week1-diode-iv/`](experiments/week1-diode-iv/))

### What it does
Characterises a silicon diode (1N4005): measures the I-V characteristic, fits the Shockley equation, and extracts the junction capacitance C(V).

### Scripts

| Script | Input data | Output |
|--------|-----------|--------|
| `iv_graph.py` | `samples/square/*.csv` | Square-wave I-V with full Shockley + series-resistance fit |
| `iv_from_triangle.py` | `samples/triangle/f_*.csv` | Triangle-wave I-V with per-cycle ensemble Shockley fit |
| `dischargetimes.py` | `samples/square discharge/*.csv` | Junction capacitance C(V) from direct exponential discharge fit; C ~ a/√V + c |
| `run_fits.py` | — | Canonical runner: regenerates Fig 1 + Fig 2 + Fig 3 PNGs + JSONs |
| `tek_csv.py` | — | Tektronix DPO CSV loader (helper module) |

### Key physics
- **Shockley equation**: $I = I_S(e^{V/nV_T} - 1)$ — extracted parameters: ideality factor $n$, saturation current $I_S$
- **Junction capacitance**: $C_j \propto 1/\sqrt{V}$ — abrupt one-sided PN junction under reverse bias

### Data (not tracked — too large)
Raw oscilloscope CSVs live in `experiments/week1-diode-iv/samples/` (gitignored). Acquire from the lab Google Drive.

---

## Week 2 — RLD Circuit Chaos ([`experiments/week2-rld-bifurcation/`](experiments/week2-rld-bifurcation/))

### What it does
Studies nonlinear dynamics in an RLD circuit (R = 470 Ω, L = 100 mH, 1N4005 diode): period-doubling cascade and chaotic behaviour as a function of drive amplitude.

### Interactive 3D Bifurcation Map
View the continuous bifurcation map online (GitHub Pages):
**[→ Open interactive 3D plot](https://shakedsuki.github.io/HUJI-lab-b2/week2-rld-bifurcation/bifurcation_continuous_3d.html)**
*(Enable GitHub Pages in repo Settings → Pages → master / root to activate this link)*

### Scripts

| Script | Input data | Output |
|--------|-----------|--------|
| `get_cycles.py` | `samples/*.csv` | Discrete bifurcation map (one fixed amplitude per file) |
| `get_return_map.py` | `samples/*.csv` | Return maps with colorbar |
| `bifurcation_continuous.py` | `samples/AM/7V.csv` | Continuous bifurcation map via Hilbert envelope + peak detection; 2D matplotlib PNG (unfiltered) + interactive 3D plotly HTML (forward-bias only) |

### Key physics
- **Period-doubling cascade**: RLD circuit driven at ~34 kHz with 0.7 Hz AM amplitude sweep shows period-1 → period-2 → period-4 → chaos
- **Hysteresis**: bifurcation transitions occur at different amplitudes on upswing vs downswing (finite relaxation time)
- **Carrier frequency**: ~34 kHz confirmed by FFT; corresponds to LC resonance with effective junction capacitance

### Data (not tracked — too large)
Raw oscilloscope CSVs live in `experiments/week2-rld-bifurcation/samples/` (gitignored). Acquire from the lab Google Drive.
- `samples/AM/7V.csv` — 1 s AM-sweep recording (1 MS/s, 7 V peak, 0.7 Hz envelope)
- `samples/*.csv` — discrete amplitude steps for the traditional bifurcation map

---

## Weeks 3–4 — Free-Swing Double Pendulum ([`experiments/week3-4-pendulum-free-swing/`](experiments/week3-4-pendulum-free-swing/))

This is the main tracking-pipeline phase. The double pendulum is released from
a range of initial-condition pairs `(θ₁, θ₂)` and allowed to swing freely. The
pipeline in `scripts/` turns each recorded video into per-frame angles +
angular velocities, with verdicts on tracking quality.

### Setup

```bash
git clone <this repo>
cd chaos
pip install -r requirements.txt
python scripts/utils/download_videos.py    # raw .mov files from Drive → experiments/week3-4-pendulum-free-swing/data/videos/
```

Drive: [כאוס on Google Drive](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-). Tested on Python 3.13 / Windows 11 (macOS + Linux work).

PowerShell needs `.\chaos <cmd>`; cmd / Bash use `chaos <cmd>` or `./chaos.sh <cmd>`. To drop the `.\` in PowerShell, add `function chaos { & "C:\dev\chaos\chaos.ps1" @args }` to your `$PROFILE`.

### Commands

```
PIPELINE
  chaos next                       drive the pending queue end-to-end
  chaos next --stem <stem>         single-clip walkthrough
  chaos bulk [--dry-run] [--redo]  unattended pass over plannable clips

PER-CLIP
  chaos track <stem> [--debug]     track + verify + interpolate + verdict
  chaos verify <stem>              standalone QA on existing tracking.csv
  chaos override <stem> --frame N  patch one row of tracking.csv
  chaos render <stem>              render combined.mp4 (video + overlay)

INSPECTION
  chaos status                     who's tracked / pending
  chaos roadmap                    per-clip status table (docs/tracking_roadmap.md)
  chaos report                     Excel summary (data/status_report.xlsx)

REGISTRY
  chaos audit                      re-validate verified clips against current logic
  chaos audit --apply              downgrade clips that no longer pass
  chaos audit --upgrade --apply    also promote new PASSes to verified

ANALYSIS
  chaos analyze <stem>             chaos physics: 0-1 test, spectral entropy, verdict
  chaos render <stem>              render combined.mp4 (video + overlay)

  chaos help                       full cheat sheet
  chaos <cmd> --help               flags for any subcommand
```

`<stem>` is the `config_description` (e.g. `th1_p047_th2_m002`) — the folder name under `measurements/`.

### Verdict bands

- **PASS** — auto-marks `tracking_quality=verified`; ready for downstream analysis
- **WARN** — tracking probably fine but a physics check fired; review `verification.png` or `chaos override <stem> --frame N`
- **FAIL** — broken; needs `chaos override` or a re-track with adjusted thresholds

### Outputs per clip

`experiments/week3-4-pendulum-free-swing/measurements/<stem>/`:

| File | Source | What it is |
|---|---|---|
| `tracking.csv` | `chaos track` | per-frame angles + marker pixels |
| `verification.csv` | `chaos verify` | + ω, suspect flags from 7 physics checks |
| `verification.png` | `chaos verify` | θ / ω timelines, suspect dots |
| `verification_meta.json` | `chaos verify` | run-level (pivot drift, E_release) |
| `combined.mp4` | `chaos render` | source video + marker overlay + phase plots |
| `phase_panels.png`, `phase_3d_*` | analysis scripts | post-tracking physics figures |
| `debug.mp4` | `chaos track --debug` | tracker-internal annotated video (large) |

Plus the cross-clip rollup at `experiments/week3-4-pendulum-free-swing/data/status_report.xlsx` (`chaos report`) and `experiments/week3-4-pendulum-free-swing/docs/tracking_roadmap.md` (`chaos roadmap`).

### More

- [`experiments/week3-4-pendulum-free-swing/docs/PIPELINE.md`](experiments/week3-4-pendulum-free-swing/docs/PIPELINE.md) — keystroke-level walkthrough (archive of the pre-BGR pipeline)
- `chaos help` — same cheat sheet on stdout
- `chaos <cmd> --help` — flag list for any subcommand

---

## Weeks 5–6 — Motor-Driven Double Pendulum ([`experiments/week5-6-pendulum-motor-driven/`](experiments/week5-6-pendulum-motor-driven/))

### What it is

A driven, damped double pendulum: a DC motor oscillates Arm 1 (upper arm) at a controlled frequency `f_drive` and amplitude proportional to `V_drill`. Arm 2 (lower arm) hangs free from Pivot β. The system can sustain a **strange attractor** — unlike weeks 3–4 (free swing / transient chaos), continuous energy input from the motor balances dissipation.

The control space is 2D: **`f_drive` (Hz) × `V_drill` (V)**. A sweep in `V_drill` at fixed `f_drive` produces the period-doubling cascade (period-1 → period-2 → period-4 → chaos), mirroring the RLD circuit results from Week 2.

### Control parameters

| Parameter | Physical meaning | Set via |
|-----------|-----------------|---------|
| `f_drive` | Driving frequency (Hz) | Function generator |
| `V_drill` | Driving amplitude proxy | Bench supply Ch2 |

### Clip naming convention

```
<voltage>V_<freq>Hz                e.g.  3.2V_1.20Hz
fd_<freq>_vd_<voltage>             e.g.  fd_1p5_vd_4v0   (specification form)
```

### Deliverables

Phase portraits · Poincaré sections (stroboscopic at θ₁ = 0, ω₁ > 0) · Bifurcation diagram (peak θ₂ vs V_drill) · Return maps · Lyapunov exponent · 3D phase animation

### Docs

- [`experiments/week5-6-pendulum-motor-driven/docs/SYSTEM_SETUP.md`](experiments/week5-6-pendulum-motor-driven/docs/SYSTEM_SETUP.md) — full apparatus, circuit, electronics, and physics reference
- [`experiments/week5-6-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md`](experiments/week5-6-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md) — specification for stroboscopic Poincaré / bifurcation / Arnold tongue figures
- [`experiments/week5-6-pendulum-motor-driven/docs/driven_pendulum_circuit.html`](experiments/week5-6-pendulum-motor-driven/docs/driven_pendulum_circuit.html) — annotated HTML circuit diagram (DPDT relay, signal chain, mechanical output)
- [`experiments/week5-6-pendulum-motor-driven/calibration/`](experiments/week5-6-pendulum-motor-driven/calibration/) — `calibrate_pivot.py` + reference frame for the Pivot α / arm-length-pixel fit

### The shared pendulum pipeline

The video-tracking pipeline under [`scripts/`](scripts/) targets driven
motion (weeks 5–6). The weeks 3–4 free-swing data and figures remain on
disk as archive, but the HSV-based tracker that produced them has been
retired — only `bgr_tracker.py` is active in the current pipeline. The
verbatim Cohen reference for the BGR detection logic lives at
[`reference/cohen_get_video_coords.py`](reference/cohen_get_video_coords.py).

```bash
# Driven tracking (default — weeks 5–6 motor-driven)
CHAOS_PHASE=week5-6-pendulum-motor-driven python scripts/processing/bgr_tracker.py <video> --force
```

(The legacy values `phase1-free-swing`, `phase2-motor-driven`,
`week3-pendulum-free-swing`, and `week4-pendulum-motor-driven` still
work — they're aliased to the new `experiments/` paths in `paths.py`.)

---

## Reports ([`reports/`](reports/))

Three-tier layout matching the lab's reporting cadence:

| Path | What it is |
|---|---|
| [`reports/lab-assignment.pdf`](reports/lab-assignment.pdf) | The original course assignment (Diodes + RLC + Dynamical Systems, 2025) |
| [`reports/weekly/`](reports/weekly/) | Lightweight weekly catch-up reports (one per week the lab was active) |
| [`reports/interim/01_week1-2_diode-rld/`](reports/interim/01_week1-2_diode-rld/) | First interim: Weeks 1+2 (diode I-V + RLD chaos): LyX source, final PDF, all figures |
| [`reports/interim/02_week3-4_pendulum-free/`](reports/interim/02_week3-4_pendulum-free/) | Second interim: Weeks 3–4 pendulum free-swing ("Expansion report 1"): LyX source, PDF, figures |
| [`reports/final/week5-6_pendulum-motor-driven/`](reports/final/week5-6_pendulum-motor-driven/) | Final report: Weeks 5–6 motor-driven ("Expansion report 2"): LyX source, PDF, per-clip phase-panel PNGs |
