# Chaos — Diodes, RLD, and the Double Pendulum

A semester's worth of experiments in nonlinear dynamics and chaos, organized by
the **week** of the lab in which the work was done.

| Week | Apparatus | What it covers |
|---|---|---|
| **[Week 1](week1-diode-iv/)** | Diode + scope | I-V characterization, Shockley fit, junction capacitance C(V) |
| **[Week 2](week2-rld-bifurcation/)** | RLD circuit + scope | Period-doubling cascade and chaos at ~34 kHz |
| **[Week 3](week3-pendulum-free-swing/)** | Double pendulum, free swing | Transient chaos, IC sweep, phase portraits, Lyapunov |
| **[Week 4](week4-pendulum-motor-driven/)** | Motor-driven double pendulum | Driven steady-state attractor, stroboscopic Poincaré, bifurcation across f_drive |

Reports for all weeks live under [`reports/`](reports/).

---

## Week 1 — Diode Characterisation ([`week1-diode-iv/`](week1-diode-iv/))

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
Raw oscilloscope CSVs live in `week1-diode-iv/samples/` (gitignored). Acquire from the lab Google Drive.

---

## Week 2 — RLD Circuit Chaos ([`week2-rld-bifurcation/`](week2-rld-bifurcation/))

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
Raw oscilloscope CSVs live in `week2-rld-bifurcation/samples/` (gitignored). Acquire from the lab Google Drive.
- `samples/AM/7V.csv` — 1 s AM-sweep recording (1 MS/s, 7 V peak, 0.7 Hz envelope)
- `samples/*.csv` — discrete amplitude steps for the traditional bifurcation map

---

## Week 3 — Free-Swing Double Pendulum ([`week3-pendulum-free-swing/`](week3-pendulum-free-swing/))

This is the main tracking-pipeline week. The double pendulum is released from
a range of initial-condition pairs `(θ₁, θ₂)` and allowed to swing freely. The
pipeline in `scripts/` turns each recorded video into per-frame angles +
angular velocities, with verdicts on tracking quality.

### Setup

```bash
git clone <this repo>
cd chaos
pip install -r requirements.txt
python scripts/utils/download_videos.py    # raw .mov files from Drive → week3-pendulum-free-swing/data/videos/
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
  chaos suspects <stem>            decompose suspect counts by check
  chaos triage [--auto] [--once]   walk non-PASS clips, dispatch right tool

REGISTRY
  chaos audit                      re-validate verified clips against current logic
  chaos audit --apply              downgrade clips that no longer pass
  chaos audit --upgrade --apply    also promote new PASSes to verified

ANALYSIS
  chaos friction-fit <stem>        fit decay model to mechanical energy

  chaos help                       full cheat sheet
  chaos <cmd> --help               flags for any subcommand
```

`<stem>` is the `config_description` (e.g. `th1_p047_th2_m002`) — the folder name under `measurements/`.

### Verdict bands

- **PASS** — auto-marks `tracking_quality=verified`; ready for downstream analysis
- **WARN** — tracking probably fine but a physics check fired; review or run `chaos triage`
- **FAIL** — broken; needs `chaos override` or a re-track with adjusted thresholds

### Outputs per clip

`week3-pendulum-free-swing/measurements/<stem>/`:

| File | Source | What it is |
|---|---|---|
| `tracking.csv` | `chaos track` | per-frame angles + marker pixels |
| `verification.csv` | `chaos verify` | + ω, suspect flags from 7 physics checks |
| `verification.png` | `chaos verify` | θ / ω timelines, suspect dots |
| `verification_meta.json` | `chaos verify` | run-level (pivot drift, E_release) |
| `combined.mp4` | `chaos render` | source video + marker overlay + phase plots |
| `phase_panels.png`, `phase_3d_*` | analysis scripts | post-tracking physics figures |
| `friction_fit.png` | `chaos friction-fit` | E(t) + decay-model fit |
| `debug.mp4` | `chaos track --debug` | tracker-internal annotated video (large) |

Plus the cross-clip rollup at `week3-pendulum-free-swing/data/status_report.xlsx` (`chaos report`) and `week3-pendulum-free-swing/docs/tracking_roadmap.md` (`chaos roadmap`).

### More

- [`week3-pendulum-free-swing/docs/PIPELINE.md`](week3-pendulum-free-swing/docs/PIPELINE.md) — keystroke-level walkthrough (archive of the pre-BGR pipeline)
- `chaos help` — same cheat sheet on stdout
- `chaos <cmd> --help` — flag list for any subcommand

---

## Week 4 — Motor-Driven Double Pendulum ([`week4-pendulum-motor-driven/`](week4-pendulum-motor-driven/))

### What it is

A driven, damped double pendulum: a DC motor oscillates Arm 1 (upper arm) at a controlled frequency `f_drive` and amplitude proportional to `V_drill`. Arm 2 (lower arm) hangs free from Pivot β. The system can sustain a **strange attractor** — unlike Week 3 (free swing / transient chaos), continuous energy input from the motor balances dissipation.

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

- [`week4-pendulum-motor-driven/docs/SYSTEM_SETUP.md`](week4-pendulum-motor-driven/docs/SYSTEM_SETUP.md) — full apparatus, circuit, electronics, and physics reference
- [`week4-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md`](week4-pendulum-motor-driven/docs/DRIVEN_FIGURES_SPEC.md) — specification for stroboscopic Poincaré / bifurcation / Arnold tongue figures
- [`week4-pendulum-motor-driven/docs/driven_pendulum_circuit.html`](week4-pendulum-motor-driven/docs/driven_pendulum_circuit.html) — annotated HTML circuit diagram (DPDT relay, signal chain, mechanical output)

### The shared pendulum pipeline

The video-tracking pipeline under [`scripts/`](scripts/) targets driven
motion (Week 4). The Week 3 free-swing data and figures remain on disk
as archive, but the HSV-based tracker that produced them has been
retired — only `bgr_tracker.py` is active in the current pipeline.

```bash
# Driven tracking (default — week4-pendulum-motor-driven)
CHAOS_PHASE=week4-pendulum-motor-driven python scripts/processing/bgr_tracker.py <video> --force
```

(The legacy values `phase1-free-swing` / `phase2-motor-driven` still work and
resolve to the new directories for one transition cycle.)

---

## Reports ([`reports/`](reports/))

| Path | What it is |
|---|---|
| [`reports/lab-assignment.pdf`](reports/lab-assignment.pdf) | The original course assignment (Diodes + RLC + Dynamical Systems, 2025) |
| [`reports/week1-2-interim/`](reports/week1-2-interim/) | Interim report covering Weeks 1+2 (diode I-V + RLD chaos): LyX source, final PDF, all figures |
| [`reports/week3-pendulum-free/`](reports/week3-pendulum-free/) | Pendulum free-swing "Expansion report 1": LyX source, PDF, figures |
