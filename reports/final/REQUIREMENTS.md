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

## Figures — confirmed

These are in. Scripts go in `scripts/`, output PNGs in `figures/`.

### Fig A — Spectral waterfall
Source: `scripts/analysis/spectral_waterfall.py` (existing aggregate script)

- Per sample: take the last X% of frames (no transients), compute FFT
- Stack all week-6 samples into a 2D plot: x = drive frequency, y = signal frequency, color = FFT amplitude
- Shows how the frequency content of θ₂ evolves across the resonance sweep
- **Extra idea (separate graph):** extract just the amplitude at f_drive from each sample → amplitude-at-resonance vs f_drive curve

### Fig B — θ₂ time series (3-panel)
Source: `scripts/analysis/phase_analysis.py` or new script

- Three representative clips: periodic (green) / chaotic (red) / periodic (green)
- Time window: first 10 s (0–10 t), wrapped angle
- Shows the qualitative transition visually

### Fig C — Phase space of arm 2, single row
Source: `scripts/analysis/phase_panels.py` (codename: Gaussian row)

- θ₂ vs ω₂ phase portrait for all week-6 clips, laid out in a single row ordered by f_drive
- Shows the P1 → P2 → chaos → P1 progression across the sweep

---

## Figures — ideas / candidates

Not committed yet. Revisit after confirmed figures are drafted.

- **Lyapunov exponent λ₁ vs f_drive** — sweeps all week-6 clips; already computed per-clip, just needs aggregation. Strong quantitative marker of chaos onset.
- **Stroboscopic Poincaré spread** — for each clip compute std-dev / area / volume of the stroboscopic section; plot vs f_drive. Extremum marks the chaotic regime.
- **Phase-space area of arm 2** — area enclosed by the θ₂ phase portrait (normalised); another scalar proxy for chaos.
- **Rotation / flip count** — time-window counter (last 50% of frames, no transients): how many full CW/CCW loops per arm per clip → aggregate mean vs f_drive.
- **Energy graph** — reconstructed mechanical energy vs time (or vs f_drive). TBD whether this adds independent information.

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
