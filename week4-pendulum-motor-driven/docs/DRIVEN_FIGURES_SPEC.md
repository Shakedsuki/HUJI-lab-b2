# Driven Double Pendulum — Analysis Figures Specification

**Scope:** Figures and visualizations uniquely enabled by the motor-driven (Phase 2) setup.  
**Audience:** Architect / Claude Code sessions preparing data pipelines, tracking foundations, and analysis scripts.  
**Status:** Pre-data. Recording has not started. All scripts are to be designed against the planned data format.

---

## Context

Phase 1 produced free-swing clips with a standard toolkit: phase portraits, Poincaré sections (geometric, θ₂_abs = 0 crossing), Lyapunov exponents.

Phase 2 adds a **known external drive** at frequency `f_drive` (Hz) and voltage `V_drill` (V). This unlocks a fundamentally different class of figures because:

- The drive period `T = 1/f_drive` is a natural sampling clock.
- The system's response can be referenced against the drive phase.
- Sweeping `f_drive` or `V_drill` as a control parameter turns individual clips into points on a bifurcation/parameter diagram.
- Two-dimensional coverage of the `(f_drive, V_drill)` parameter space enables tongue maps.

The figures below cannot be produced from free-swing data and are the primary scientific output of Phase 2.

---

## 0. Shared Data Prerequisites

Before any figure script can run, the following must be in place.

### 0.1 Clip Naming Convention

Every Phase 2 clip stem encodes its control parameters:

```
fd_<freq>_vd_<volt>
```

Examples: `fd_1p5_vd_4v0`, `fd_2p0_vd_6v0`.  
Rules: `p` replaces the decimal point (consistent with Phase 1 angle convention). Frequency in Hz, voltage in V.

A `parse_stem()` utility (see §5) must extract `(f_drive_hz, v_drill_v)` from any such stem.

### 0.2 `verification.csv` Column for Driven Clips

Existing analysis scripts filter rows on `phase == "free_swing"`. Driven clips have no holding/release phase.

**Decision needed before tracking starts:** What string does `thresholds.py` write into the `phase` column for driven data?

Proposal: `"driven"` — and all driven-aware loaders accept a `--phase-filter driven` flag (defaulting to `"free_swing"` for backward compatibility with Phase 1 scripts).

### 0.3 `experiments.json` for Phase 2

Located at `week4-pendulum-motor-driven/data/experiments.json`. Each entry:

```json
{
  "stem": "fd_1p5_vd_4v0",
  "f_drive_hz": 1.5,
  "v_drill_v": 4.0,
  "regime": "periodic",       // "periodic" | "quasiperiodic" | "chaotic" | "unknown"
  "notes": ""
}
```

The `regime` field can be populated manually after visual inspection and updated by analysis scripts.

### 0.4 Transient Discard

All driven analyses should skip the first `T_transient` seconds (default: 5 s) to let the system settle onto the attractor. This should be a configurable parameter, not hardcoded.

---

## 1. Stroboscopic (Drive-Synchronized) Poincaré Section

### What it shows

The system state `(θ₁, ω₁)` sampled exactly once per drive period `T = 1/f_drive`. In a period-1 locked regime: a single fixed point. Period-2: two points. Chaos: a cloud forming the strange attractor cross-section.

This is the natural Poincaré map for a driven system — more physically meaningful than the geometric θ₂_abs = 0 crossing used in Phase 1, because the sampling clock is the drive itself.

### Figures produced

- **4-panel figure** (mirrors `poincare.py` layout):
  - Main panel: `(θ₁, ω₁)` stroboscopic scatter, colored by time.
  - Top-right: θ₁ at each strobe vs. time (shows transient decay + settled attractor).
  - Bottom-right: full phase portrait with stroboscopic points overlaid in red.
  - Text annotation: `f_drive`, `V_drill`, number of strobe points, transient discard.

### Algorithm

1. Parse `f_drive_hz` from stem. Compute `T = 1 / f_drive_hz`.
2. Load `(t, θ₁, ω₁)` from `verification.csv`, filter `phase == "driven"`, discard first `T_transient` seconds.
3. For each integer `n` such that `n·T` falls within the data window, linearly interpolate `θ₁` and `ω₁` at `t = n·T`. This avoids the "ladder" artefact from pure sample-snapping.
4. Collect as `(t_strobe, θ₁_strobe, ω₁_strobe)`.

### Script

`scripts/analysis/driven_poincare.py`

```
Usage: python scripts/analysis/driven_poincare.py --stem fd_1p5_vd_4v0
       python scripts/analysis/driven_poincare.py --stem fd_1p5_vd_4v0 --transient 8
Output: measurements/<stem>/driven_poincare.png
        measurements/<stem>/driven_poincare.csv
```

**Testable with a single clip.** Implement and validate this first.

---

## 2. Bifurcation Diagram

### What it shows

The canonical figure for a driven nonlinear oscillator. X-axis: control parameter (sweep `f_drive` at fixed `V_drill`, or sweep `V_drill` at fixed `f_drive`). Y-axis: θ₁ at each stroboscopic Poincaré crossing. Each clip contributes a vertical column of dots.

- Period-1 regime → single dot.
- Period-2 → two dots (after transient).
- Chaos → vertical cloud.

Reading left to right shows the period-doubling cascade and onset of chaos.

### Figures produced

- **Scatter plot:** each clip's stroboscopic θ₁ values plotted at its `f_drive` (or `V_drill`) x-coordinate, colored by `V_drill` (or `f_drive`).
- Optional: second panel showing ω₁ at same crossings.
- Vertical dashed guide-lines at detected bifurcation points (initially manual, later automatic).

### Algorithm

1. From `experiments.json` (or stem glob), collect all clips matching a fixed `V_drill` (for fd sweep) or fixed `f_drive` (for vd sweep).
2. For each clip: run stroboscopic sampler (same function as `driven_poincare.py`) → get `θ₁_strobe` array.
3. Sort clips by their sweep parameter.
4. Scatter: x = sweep parameter value, y = each element of `θ₁_strobe`.

### Script

`scripts/analysis/driven_bifurcation.py`

```
Usage: python scripts/analysis/driven_bifurcation.py --sweep-axis fd --fixed-vd 4.0
       python scripts/analysis/driven_bifurcation.py --sweep-axis vd --fixed-fd 1.5
Output: figures/driven_bifurcation_fd_sweep_vd4p0.png
```

**Requires ≥ 5 clips varying along the sweep axis.** Meaningful at 5; clear cascade visible at 10+.

### Recording requirement

To produce a bifurcation diagram sweeping `f_drive`:
- Hold `V_drill` fixed (e.g. 4 V).
- Record clips at ≥ 8 distinct `f_drive` values spanning the range where regime changes are expected.
- Minimum spacing: fine enough to resolve the period-doubling region (likely needs ~0.1–0.2 Hz steps near the transition).

---

## 3. Arnold Tongue Map

### What it shows

A 2D heatmap of the `(f_drive, V_drill)` parameter space. Each cell is colored by the **winding number** — the ratio of the pendulum's dominant oscillation frequency to the drive frequency. Integer or simple rational winding numbers (1:1, 1:2, 2:3, ...) appear as colored "tongues" (locking regions). Chaotic or quasiperiodic regions appear as gray or textured.

This is the highest-information Phase 2 figure: it maps the entire dynamical landscape of the driven system in a single image.

### Figures produced

- **Primary: 2D heatmap** with `f_drive` on x-axis, `V_drill` on y-axis.
  - Color encodes winding number (rational ratios get distinct colors; irrational/chaotic = gray).
  - Cells with λ₁ > 0 (chaotic) marked with hatching or distinct border.
  - Clip locations plotted as scatter points on top.
- **Secondary: Lyapunov overlay** — same axes, color = λ₁ (blue = ordered, red = chaotic).

### Algorithm

Per clip:

1. Parse `(f_drive_hz, v_drill_v)` from stem.
2. Load `θ₁(t)` from verification.csv, discard transient.
3. **Winding number estimator:**
   - FFT of `θ₁(t)`.
   - Find dominant spectral peak frequency `f_peak` (excluding DC and harmonics above `2·f_drive`).
   - Compute raw ratio `r = f_peak / f_drive`.
   - Round `r` to the nearest simple rational with denominator ≤ 6 (using Farey sequence or `fractions.Fraction(r).limit_denominator(6)`).
4. **Lyapunov sign** — reuse existing `lyapunov.py` output if available (`measurements/<stem>/lyapunov.csv`), or recompute.
5. Store `(f_drive, v_drill, winding_num, lyapunov)` per clip.

Plotting:

- Interpolate onto a regular grid using `scipy.interpolate.griddata` (nearest-neighbor safe for sparse grids).
- Color map: one color per rational winding number (e.g. red=1:1, blue=1:2, green=2:3, yellow=2:1, gray=incommensurate/chaotic).

### Script

`scripts/analysis/arnold_tongue.py`

```
Usage: python scripts/analysis/arnold_tongue.py
       python scripts/analysis/arnold_tongue.py --min-fd 0.5 --max-fd 3.0
Output: figures/arnold_tongue.png
        figures/arnold_tongue_lyapunov.png
        data/arnold_tongue.csv  (f_drive, v_drill, winding_num, lambda1 per clip)
```

**Requires clips spanning a 2D grid.** Minimum viable: 3 fd values × 3 vd values = 9 clips. Useful map: 5 × 5 = 25 clips. Dense enough to resolve tongue boundaries: 8 × 6 = 48 clips.

### Recording requirement

This figure demands deliberate 2D coverage. Suggested grid:

| `f_drive` (Hz) | `V_drill` (V) values |
|---|---|
| 0.5, 1.0, 1.5, 2.0, 2.5, 3.0 | 2, 3, 4, 5, 6, 8 |

That's 36 clips. Each clip needs ≥ 30 s of settled data (+ transient). **Coordinate the recording grid before starting Phase 2 data collection** — retrofit coverage is difficult.

---

## 4. Shared Helper Module

All three figure scripts import from a single new utility:

**`scripts/utils/driven_helpers.py`**

### Functions

```python
def parse_stem(stem: str) -> dict:
    """
    'fd_1p5_vd_4v0' -> {'f_drive_hz': 1.5, 'v_drill_v': 4.0}
    Raises ValueError on unrecognized format.
    """

def load_driven_csv(csv_path: str, phase_label: str = "driven",
                    transient_s: float = 5.0) -> tuple:
    """
    Load verification.csv for a driven clip.
    Filters rows where phase == phase_label.
    Discards first transient_s seconds.
    Returns (t, th1, th2, om1, om2) as numpy arrays in deg / deg·s⁻¹.
    """

def strobe_sample(t, th1, om1, f_drive: float) -> tuple:
    """
    Linearly interpolate (th1, om1) at t = n / f_drive for integer n
    within the data window. Returns (t_strobe, th1_strobe, om1_strobe).
    """

def winding_number(t, th1, f_drive: float, max_denom: int = 6) -> float:
    """
    Estimate the winding number (f_pendulum / f_drive) via FFT.
    Returns the ratio rounded to the nearest rational with denominator
    <= max_denom. Returns NaN if no clear dominant peak found.
    """
```

---

## 5. Integration with Existing Pipeline

| Existing component | Change needed | Notes |
|---|---|---|
| `thresholds.py` | Add DRIVEN mode; write `phase = "driven"` column | No holding/release detection |
| `ring_tracker.py` | No change | Tracking is phase-agnostic |
| `verify_tracking.py` | No change | |
| `poincare.py` | No change | Phase 1 only; driven clips use `driven_poincare.py` |
| `lyapunov.py` | Minor: accept `--phase-filter driven` | Reuse unchanged for λ₁ computation; arnold_tongue.py reads its CSV output |
| `paths.py` | No change | `CHAOS_PHASE=week4-pendulum-motor-driven` already works (legacy `phase2-motor-driven` aliased) |
| `chaos.py` | Register new subcommands | `chaos driven-poincare`, `chaos bifurcation`, `chaos arnold-tongue` |

---

## 6. Implementation Order

Build in dependency order. Each step is independently testable.

1. **`driven_helpers.py`** — foundation for all three scripts. Zero data required; unit-testable with synthetic arrays.
2. **`thresholds.py` DRIVEN mode** — write `phase = "driven"` into tracking output. Needed before any real data can load.
3. **`driven_poincare.py`** — testable with a single clip. Validates the stroboscopic sampler end-to-end.
4. **`driven_bifurcation.py`** — testable once ≥ 3 clips exist at different fd values.
5. **`arnold_tongue.py`** — only meaningful with ≥ 9 clips on a 2D grid. Implement last; validate winding number estimator on synthetic data first.

---

## 7. Open Questions (resolve before recording)

1. **Phase column string:** `"driven"` or something else? Must be decided before `thresholds.py` DRIVEN mode is written.
2. **Recording grid:** Confirm the `(f_drive, V_drill)` grid before collecting data. The Arnold tongue map needs deliberate 2D coverage — retrofitting is costly.
3. **Clip duration:** How long must each clip be? Minimum: `T_transient + N_orbits / f_drive` where N_orbits ≥ 50 for a meaningful stroboscopic section. At `f_drive = 1.5 Hz`, 50 orbits = 33 s; add 5–10 s transient → **≥ 45 s per clip**.
4. **Lyapunov reuse:** `lyapunov.py` currently loads `phase == "free_swing"`. Add `--phase-filter` flag before running it on driven clips, or the arnold_tongue script will need to call it with the right arguments.
5. **Pivot angle reference:** The driven setup has a spring-restrained disk at Pivot α. Confirm that `θ₁` in the tracking output is measured from the same rest-equilibrium reference as the drive neutral position — otherwise the stroboscopic phase will be offset but still self-consistent.
