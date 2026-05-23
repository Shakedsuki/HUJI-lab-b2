# Figures & Analysis Inventory

_Compiled 2026-05-23 from a read of `scripts/utils/shell.py`, `scripts/utils/batch_figures.py`, and every script in `scripts/analysis/`._ Snapshot of the **current driven (week6) pipeline** — the tools are phase-agnostic, examples use the 3.2V frequency sweep.

This is a recon catalog of everything the chaos shell can produce on the **analysis / figures** side, for review and discussion. It does not cover tracking/verification (the upstream half).

---

## 1. How the analysis side is wired

The hub (`chaos` with no subcommand → `shell.py:hub`) dispatches to standalone scripts. Two cards plus a videos card cover this half:

| Card | Hub keys | Produces | Gating |
|---|---|---|---|
| **analyze** | `a` `aq` `ai` `ar` | runs an analysis → prints numbers/verdict to terminal **and** writes a figure + data file | none |
| **figures** | `fi` | renders **static PNGs** via `batch_figures.py` | **QA gate**: `overlay_verdict == "pass"` only (unless `--all-quality`) |
| **videos** | `vi` | renders **mp4s** | none; `overlay` is itself the QA gate the figures card depends on |

Two orthogonal distinctions run through everything below:

- **Per-clip** (one stem) vs **aggregate** (a whole voltage/frequency family → `figures/aggregate/`).
- **Same artifact, two paths**: `chaos / poinc / lyap / dim` are reachable from *both* the analyze card (direct script call, always runs, prints to terminal) and the figures card (via `batch_figures`, QA-gated, skip-if-exists).

Source anchors: `FIG_TYPES` → `shell.py:980`; `STATIC_SUITE`/`VIDEO_SUITE` → `batch_figures.py:45`; `ANALYZE_TYPES` → `shell.py:644`; `do_a` → `shell.py:665`; `PLOTS` → `quick_insights.py:495`.

---

## 2. Per-clip figures (the `fi` inventory matrix)

Eight static PNG types, one column each in the figures matrix. Output pattern: `figures/<type>/<stem>_<type>.png`. "Needs verif" = requires `verification.csv` (the figure is skipped otherwise).

| Matrix key | Figure type | Script (`scripts/analysis/`) | Needs verif | Physics — and how it reads chaos |
|---|---|---|---|---|
| `panels` | `phase_panels` | `phase_panels.py --save` | no | 6-panel sanity view (θ₁(t), θ₂(t), two phase portraits, config space, return map). Phase portraits close into clean loops when regular and fill the plane when chaotic — first look at the orbit. |
| `poinc` | `poincare` | `poincare.py` | yes | Geometric Poincaré section at θ₂_abs=0 (upward), points (θ₁, ω₁). Slicing the 4D flow: periodic → a few dots, torus → closed curve, chaos → fractal scatter. Also writes `poincare.csv`. |
| `3d` | `phase_3d_trajectory` | `phase_3d.py --static` | no | Time-colored ribbon in (θ₁, θ₂, ω₁). The orbit on its energy manifold; a strange attractor is a tangled, non-self-intersecting ribbon vs a regular closed tube. |
| `chaos` | `chaos_analyze` | `chaos_analyze.py` (positional stem) | yes | Verdict card: θ₂_abs(t) colored by E/E_inversion + θ₂ log-log power spectrum. Gottwald–Melbourne **0–1 test** + spectral entropy → CHAOTIC / BORDERLINE / REGULAR. |
| `lyap` | `lyapunov` | `lyapunov.py` | yes | Largest Lyapunov exponent λ₁ via Rosenstein delay-embedding of θ₁(t). Exponential divergence rate of nearby orbits — **λ₁ > 0 is chaos signature #1**. |
| `seis1` | `seismograph_v1` | `seismograph.py --mode v1` | no | Spiral hodograph of θ_tip(=θ₂), radius = time (newest outermost). Regular → symmetric evenly-spaced lobes; chaos → tangled asymmetric texture (qualitative). |
| `seis2` | `seismograph_v2` | `seismograph.py --mode v2` | no | Same hodograph, radius = reversed time (ripple, oldest outermost). Same diagnostic, different visual emphasis. |
| `dim` | `dimension` | `dimension.py` | no | Fractal dimension: D₂ correlation (Grassberger–Procaccia on an ω₂ embedding) + D_box box-count on the (θ₂, ω₂) projection. **Non-integer dimension is chaos signature #3** (periodic → D≈1). Also writes `dimension.json`. |

---

## 3. Aggregate / family figures

Computed across a whole fixed-voltage family → `figures/aggregate/`.

| Reachable via | Figure | Script | Physics — and how it reads chaos |
|---|---|---|---|
| `fi → w`, `a → wf` | **spectral_waterfall** | `spectral_waterfall.py` | Per-clip ω₂ spectra stacked vs f_drive as a per-row dB heatmap + spectral-entropy side panel. Power spectrum goes from sharp lines (periodic) to **continuous broadband** (chaotic) — signature #3 across the sweep; locates the chaotic window. → `spectral_waterfall_<V>V.{png,csv}` |
| `a → bs`, card `ai` | **driven_bifurcation** | `driven_bifurcation.py --sweep vd\|fd` | Stroboscopic θ₁ scattered vs a swept parameter. Period-1 → one dot, period-2 → two, quasiperiodic → dense arc, chaos → vertical cloud: the **period-doubling route to chaos**. Needs ≥2 voltages, so it is hidden in the single-voltage week6. → `driven_bifurcation_<sweep>_fixed_<param>.png` + `data/…csv` |
| `a → rs`, card `ar → a` | **rotations sweep** | `rotations.py --sweep` | Per-arm winding (loops, net turns) vs f_drive. Onset of full circulation (loops > 0 — the lower arm going over the top) flags the chaotic band. → `rotations_sweep_<V>V.{png,csv}` |

**Hidden aggregate tier (CLI-only — NOT on any shell key):**

| Script | Output | Notes |
|---|---|---|
| `resonance.py` | `figures/aggregate/resonance_<V>V.{png,csv}` | θ₁ RMS amplitude vs f_drive (classic resonance curve, f₀/Q). The *curve* is surfaced in quick-insights as `res`, but the standalone aggregate figure is CLI-only. |
| `chaos_sweep.py` | `chaos_sweep_<V>V.{png,csv}` | Route-to-chaos scalars vs f_drive (loops, D₂, θ₁ RMS, freq ratio + slip; optional λ₁). Mirrors `dimension`'s ω₂ D₂. Not wired into the shell at all. |

---

## 4. Videos (related output, `vi` card)

Mp4s, not static figures. Live in `animations/<type>/` except overlay.

| Matrix key | Type | Script | Role |
|---|---|---|---|
| `overlay` | `overlay` | `overlay_video.py` | Ring/marker overlay on the source video → `measurements/<stem>/<stem>_overlay.mp4`. **This is the QA gate**: figures only render for clips marked `pass` here. |
| `comb` | `combined` | `combined_video.py` | Source + live plots side-by-side. |
| `anim` | `phase_animation` | `phase_animation.py` | Phase-portrait trace animation. |
| `3d-rot` | `phase_3d_rotation` | `phase_3d.py` (no `--static`) | Rotating 3D phase-space ribbon. |

---

## 5. The `analyze` command

**What it is:** `a` opens an arrow-key **clip × analysis-type matrix** (`do_a`, `shell.py:665`). Each row is a tracked clip; the ✓/· columns show what is already computed. Highlight a clip, press a **two-letter key** to run a per-clip analysis — it prints the verdict/numbers to the terminal *and* writes the figure + a data file. The same screen exposes family sweeps and a terminal plot explorer.

**What it's for:** turning clean θ₁(t), θ₂(t) time series into the **evidence and numbers that classify and quantify chaos** — the per-clip scalars/figures for the writeup, and the across-sweep transition story.

### 5a. Per-clip analyses (two-letter keys)

| Key | Script | Computes | Data output |
|---|---|---|---|
| `ch` | `chaos_analyze.py` | CHAOTIC / BORDERLINE / REGULAR (0–1 test + spectral entropy + energy/topology) | `chaos_analyze.png` |
| `po` | `poincare.py` | geometric Poincaré section (θ₂_abs = 0) | `poincare.png` + `poincare.csv` |
| `ly` | `lyapunov.py` | largest Lyapunov exponent λ₁ (Rosenstein) | `lyapunov.png` |
| `dr` | `driven_poincare.py` | stroboscopic drive-synced Poincaré → period-n / quasiperiodic / chaos | `driven_poincare.png` + `driven_poincare.csv` |
| `ro` | `rotations.py --stem` | per-arm winding metrics (loops, net turns) | `rotations.json` + `rotations.png` |
| `fr` | `dimension.py` | fractal dimension D₂ + D_box | `dimension.json` + `dimension.png` |
| `↵` | `quick_insights.explore` | terminal-native (plotext) plot explorer for that clip | — (interactive) |

### 5b. Family / aggregate sweeps (from the same matrix)

| Key | Script | Scope |
|---|---|---|
| `bs` | `driven_bifurcation.py --sweep vd` | bifurcation across voltages — *only shown when ≥2 drive voltages exist* (`_voltage_sweep_ok`) |
| `rs` | `rotations.py --sweep` | winding across the family |
| `wf` | `spectral_waterfall.py` | spectral waterfall (voltage inferred from the highlighted clip) |

### 5c. Sibling cards on the analyze panel (hub-level)

| Key | Opens | What it does |
|---|---|---|
| `a` | analyze matrix | the per-clip × type grid above |
| `aq` | quick insights | two-pane plotext explorer — clips left, type plot keywords to render terminal plots right (see §6) |
| `ai` | bifurcation | runs the voltage bifurcation sweep directly (hidden / N-A in single-voltage week6) |
| `ar` | rotations | per-arm winding **table** across all clips (θ₁/θ₂/relative net + loop counts + suspect flag); `a` recomputes all + the sweep aggregate |

---

## 6. Quick-insights plot palette (`aq` / `↵` explore)

Instant terminal (plotext) views — the *look-before-you-render* loop. **20 plots across 5 categories** (`PLOTS`, `quick_insights.py:495`):

| Category | Keywords |
|---|---|
| **time series** (green) | `both` θ₁+θ₂ · `omega` ω₁+ω₂ · `tip` θ₂ (abs) · `energy` KE+PE · `rot` accumulated angle/loops |
| **phase space** (yellow) | `phase1` θ₁–ω₁ · `phase2` θ₂–ω₂ · `config` θ₁–θ₂ · `full` θ₂_abs–ω₂_abs · `seis1` seismograph v1 · `seis2` seismograph v2 |
| **physical** (blue) | `xy` marker pixel positions · `trace` tip trajectory in pixels |
| **chaos** (red) | `spectrum` θ₂ power spectrum · `return` θ₂(n)–θ₂(n+1) map · `dim` D₂ + D_box · `wfall` broadband-ness vs f_drive |
| **driven** (magenta) | `cyc` cyclic phase ψ(t) · `lock` drive-relative phase Δφ(t) · `res` resonance curve θ₁ amp vs f_drive |

---

## 7. Organizing principle — the three signatures of chaos

The suite is deliberately built around the textbook signatures, each with a dedicated tool:

1. **Positive Lyapunov exponent** → `ly` / `lyapunov` (sensitive dependence on ICs)
2. **Non-integer attractor dimension** → `fr` / `dimension` (strange attractor)
3. **Broadband power spectrum** → `wf` / `spectral_waterfall` + the `chaos_analyze` spectrum panel

…backed by **Poincaré sections** for regime cardinality (`po` geometric, `dr` stroboscopic) and a **model-free 0–1 classifier** (`ch`). For the driven experiment, the **bifurcation / rotations / waterfall** sweeps add the *route* to chaos across the drive parameter.

---

## 8. Script inventory: wired vs. not

**Reachable from the shell** (analysis half): `chaos_analyze`, `poincare`, `lyapunov`, `driven_poincare`, `driven_bifurcation`, `rotations`, `dimension`, `spectral_waterfall`, `phase_panels`, `phase_3d`, `seismograph`, `combined_video`, `phase_animation`, `overlay_video`, `quick_insights`, `sanity_check`. Supporting modules pulled in by quick-insights: `phase_analysis` (`cyc`/`lock`), `resonance` (`res`).

**Present in `scripts/analysis/` but NOT reachable from the current shell** (verify before relying on any):

| Script | Why it's here |
|---|---|
| `chaos_sweep.py` | CLI-only route-to-chaos aggregate (see §3) |
| `resonance.py` (standalone fig) | CLI-only aggregate figure (curve is in `aq res`) |
| `chaos_vs_regular.py` | legacy free-swing comparison |
| `group_animations.py`, `group_overlay.py` | legacy free-swing IC-twin set visualizers |
| `lyapunov_compare.py`, `lyapunov_focused.py` | legacy free-swing λ₁ aggregates |
| `phase_portrait_regimes.py` | legacy free-swing |
| `poincare_overlay.py`, `poincare_regimes.py`, `poincare_animation.py`, `poincare_forming_animation.py` | legacy free-swing Poincaré aggregates/animations |
| `portrait_progression.py` | legacy free-swing 2D portrait progression |
| `preview_frame.py` | standalone frame-preview utility |

---

## 9. Cross-cutting notes & open questions (for discussion)

- **Figures matrix is a strict subset of analysis.** `driven_poincare`, `rotations`, and the bifurcation figure are produced only via the analyze card — they are not columns in the `fi` inventory. Worth deciding whether the figures card should mirror all analysis outputs.
- **Two paths, one artifact.** `chaos / poinc / lyap / dim` render via both cards with different gating (analyze = always + terminal verdict; figures = QA-gated + skip-if-exists). Intentional, but a source of "why didn't it re-render?" confusion.
- **QA gate.** The figures card silently skips clips not marked `pass` in overlay review. Entry-mode `+` create forces `--all-quality`; the batch `a`/column paths do not.
- **Hidden aggregate tier.** `resonance.py` and `chaos_sweep.py` produce family-level figures with no shell entry point. Candidates either to wire in (a `resonance` / `sweep` key) or to retire.
- **Stale docstrings spotted:** `quick_insights.py` header says "12 plot types across 4 categories" (actually **20 across 5**); several legacy scripts above still ship.
- **`ai` vs `bs`** both launch the bifurcation sweep (`ai` from the hub, `bs` from inside the analyze matrix) and both are auto-hidden in single-voltage phases — redundant entry points worth consolidating.

---

_Generated as a static reference; re-derive from source when the shell keymap changes (recent commits moved analyze to two-letter keys)._
