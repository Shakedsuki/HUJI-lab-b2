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

## Directory Structure (this folder)
```
reports/final/
├── REQUIREMENTS.md       ← this file
├── report/               ← report document (LyX/LaTeX/etc.)
├── figures/              ← figures that appear in the report
├── scripts/              ← final-report-specific scripts (produce figures/data)
├── data/                 ← data files used in the report
└── week5-6_pendulum-motor-driven/  ← existing expansion report (keep as reference)
```

**Rule:** every figure in `figures/` has a corresponding script in `scripts/` that produces it.
Scripts here are report-specific versions — originals in the main repo stay untouched.
