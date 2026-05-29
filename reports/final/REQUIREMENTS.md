# Final Report Requirements
*Omri Cohen (omri.cohen6@mail.huji.ac.il) — Physics Lab B2 (77336)*

## Format
- Short scientific paper structure
- Rule of thumb: ~2000 words / ~10 pages (can be less or more depending on content)
- **4–6 numbered figures** with captions
- Submit as **PDF** within 2 weeks of end of experiment
- Proofread final version — layout issues look sloppy

## Structure

### Title + Abstract
- Choose a meaningful, interesting title
- Abstract: ~150–200 words, 1–2 sentences per section
- Describe: research topic, main results, conclusions
- Motivates the reader to read further
- **Write last** (after finishing the rest)

### Introduction + Theoretical Background (~1 page)
- Intro: motivation for the work
- Theory: only what's needed to understand the analysis
- Don't summarize everything you learned — be selective
- Reader level ≈ your level before the experiment (after reading background material)
- Present the equations you'll actually use in the analysis
- Standard derivations → reference or skip
- Derivations you did → can include, detail goes in appendix
- **No errors in the theoretical background** — looks unprofessional

### Experimental Procedure
- Describe setup + procedure so it can be reproduced exactly
- Include a **diagram** (not a photo) of the experimental setup
- Include relevant information precisely
- If complex analysis was done → give an example
- List error sources and how you reduced them
- Don't exaggerate error sources — only list ones that actually affected measurements

### Results + Initial Analysis
- **The heart of the paper**
- Include graphs (raw results too — **required**)
- Present results in a way that emphasizes the "punch" of your paper
- Connect measurements — tell a story for the reader
  - Why did you measure A, then B? What's the connection? What did you expect, what did you see?
- Include error calculations as part of describing results
  - Long calculation → show result with errors, detail in appendix

### Summary + Conclusions
- Show you understood what you measured
- Don't overstate the importance of your findings
- Don't blame measurement errors for everything
- Every experiment yields conclusions
- Suggest future research ideas
- **Emphasize your main result ("punch")** — present it convincingly
- Close the story — reference what was raised in the introduction

### References
- **Everything not written by you** (figures, paragraph summaries, etc.) needs a citation
- Do NOT copy from previous years' reports (not even a sentence or two)

### Appendices
- All measurements not in the main body — with a short analysis and comment
- Non-standard code (if you only did FFT or curve fitting, skip the code)
- Complex mathematical derivations and error calculations

## Figures & Graphs
- Number all figures (rule: 4–6)
- Every figure **must** be referenced in the text
- Clear and readable: axis labels, error bars, legend (if needed), units
- **Mandatory caption** for each figure — reader should understand figure from abstract + figures alone
- "Ink = Information" — no unnecessary elements
- Error bars where relevant

## Equations
- Avoid excess equations
- Number equations you'll reference later
- Define all notation after presenting the equation
- Use standard symbols (ω for frequency, etc.) — be consistent

---

## Introduction scope

- What is chaos; chaotic systems in general
- The double pendulum system — setup, driven vs free
- The chaotic regime: when/why it appears, what characterises it
- Methodology / topology used in the analysis:
  - Poincaré sections (stroboscopic)
  - Do a brief "colloquium" treatment — accessible but rigorous

---

## Figures — status

Each figure has a script in `scripts/` and a PNG in `figures/`. Shared
conventions live in `report_common.py` (`tail_window` steady-state slice,
`TIME_WINDOW_S`=10 s for traces, `PORTRAIT_WINDOW_S`=60 s for portraits).

### ✅ Done

| Figure | Script | PNG |
|---|---|---|
| **Fig A — Spectral waterfall** (FFT heatmap: x=f_drive, y=response freq, colour=amplitude; f_drive + f_drive/2 guides) | `spectral_waterfall.py` | `spectral_waterfall_3.2V.png` |
| **Fig A companion** — locked-response amplitude \|FFT(θ₂)\| at f_drive vs f_drive (high at ends, dips through chaos) | `spectral_waterfall.py` (`--out-companion`) | `spectral_amplitude_3.2V.png` |
| **Fig B — θ₂ time series** (3-panel low/mid/high; wrapped; **last** 10 s steady-state, not first 10 s) | `theta2_timeseries.py` | `theta2_timeseries.png`, `theta2_0.9Hz_fixed.png` |
| **Fig C — Arm-2 phase portraits** (curated 5-tile row **and** full 33-clip grid tinted by phase-lock quadrant) | `phase_portrait_row.py`, `phase_portrait_grid.py` | `phase_portrait_row.png`, `phase_portrait_grid.png` |
| **Phase-locking** (ρ arm-coherence vs H_θ₂ scatter; locked↔regular / unlocked↔chaotic) — new, from the implementation brief | `phase_locking.py` | `phase_locking_3.2V.png` |
| **Energy** (⟨E⟩/⟨T⟩/⟨U⟩ + virial T/U vs f_drive; resonance peak ~0.95 Hz) | `energies.py` | `energies_3.2V.png` |
| **Chaos profile** (H_θ₂ + D₂ vs f, and θ₁ amplitude + % inversion vs f — quantifies the route AND the resonance "why") | `chaos_profile.py` | `chaos_profile_3.2V.png` |
| **Phase-space area** (normalised filling fraction of the θ₂–ω₂ cloud vs f_drive, with D_box cross-check; low=loop, high=filled) | `phase_area.py` | `phase_area_3.2V.png` |
| **Stroboscopic Poincaré spread** (normalised standard distance of the strobe cloud vs f_drive; extrema = most clustered / most scattered) | `poincare_spread.py` | `poincare_spread_3.2V.png` |

### ⬜ Remaining candidates (optional)

- **λ₁ vs f_drive** — superseded by the chaos-profile plot; λ₁ measured non-discriminating on this sweep (ftle classification labels every clip "chaotic"). Skip unless wanted.
- **Rotation / flip count vs f_drive** — partially covered: phase-locking surfaces rotation fraction; `rotation_counter.py` is interactive (not wired for static report use).

### Deviations from the original spec (intentional, agreed)
- Time-domain figures use the **last** N s (steady-state tail, homogenised) rather than the first 10 s.
- The chaos reference is **H_θ₂ / D₂**, not λ₁ (which doesn't resolve the band here).
- Two data-integrity fixes underpin every figure: ω via SG derivative (`scripts/utils/kinematics.py`) and the 8 regenerated stale `verification.csv` files.

---

## Errors / uncertainties to address

- Pixel-to-angle calibration uncertainty (pivot position, arm-length fit)
- Frame-dropout rate and its effect on ω estimates
- Stroboscopic sampling jitter (f_drive precision from function generator)
- Sensitivity of λ₁ estimate to window length

---

## Directory Structure (this folder)
```
reports/final/
├── REQUIREMENTS.md       ← this file
├── final_report.lyx      ← report document
├── system.png / .pptx    ← experimental setup diagram
├── figures/              ← figures that appear in the report
├── scripts/              ← final-report-specific scripts (produce figures/data)
└── data/                 ← data files used in the report
```

**Rule:** every figure in `figures/` has a corresponding script in `scripts/` that produces it.
Scripts here are report-specific versions — originals in the main repo stay untouched.
