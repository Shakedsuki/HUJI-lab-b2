# Driven Double Pendulum — System Setup

**Experiment:** Chaos Lab — Phase 2 (Motor-Driven Double Pendulum)  
**Authors:** Shaked Sokonik, Nir Cohen  
**Last updated:** May 2026

---

## 1. Physical Apparatus

### 1.1 Housing

- The pendulum is enclosed in a **perspex (acrylic) box** mounted on a wall or rigid support.
- The front face provides a clear viewing window for video recording.

### 1.2 Body 1 — Spring-Restrained Rotating Disk (Pivot α mount)

- A **square plate** is wall-mounted and supports a **rotating disk** (body 1).
- The disk has **adjustable bolt masses** positioned radially to tune moment of inertia.
- The disk is **spring-restrained**: springs provide a restoring torque so the system rests at a neutral angle when undriven.
- The disk's center bearing is **Pivot α** — the driven pivot (motor input).

### 1.3 Arms

- **Arm 1 (upper arm):** Attached rigidly to the shaft at Pivot α. Driven by the motor.
- **Arm 2 (lower arm):** Connected to Arm 1 via **Pivot β** (a free bearing, no motor). Hangs and swings freely.
- **Red position markers** are placed along Arm 2 for video tracking.
- **Green marker** at one joint (Pivot β or near it) — confirmed in tracking scripts.

### 1.4 Pivot Locations

| Label | Location | Type | Driven? |
|-------|----------|------|---------|
| Pivot α | Top joint (disk center / wall mount) | Bearing | Yes — motor drives shaft here |
| Pivot β | Mid joint (Arm 1 ↔ Arm 2) | Free bearing | No |

---

## 2. Driving Mechanism

### 2.1 Motor

- A **DC motor housed in a drill casing** (corded drill, modified).
- The original mains power cable has been **cut and reconnected** to accept DC input from the bench supply.
- It runs on variable low DC voltage (not mains-powered).
- The drill chuck grips an **aluminum shaft** that passes through a bearing in the perspex box wall and connects to Pivot α.
- Motor rotation → shaft rotation → angular displacement of Arm 1 at Pivot α.

### 2.2 Relay

- A **small relay module** (blue component) mounted on a prototyping strip board.
- **Assumed DPDT (double-pole double-throw)** based on observed bidirectional shaft oscillation.
- Wired so that each half-cycle of the square wave **reverses motor polarity** → motor alternates CW ↔ CCW → shaft oscillates back and forth.
- An audible tick is heard at each switching event during operation.
- **Note:** DPDT wiring is an inference. A close-up photo of the relay part number would confirm. If SPDT, an H-bridge or additional circuitry must also be present — this has not been ruled out.

### 2.3 Driving Mode

- The shaft **oscillates** (not continuously rotates) at the driving frequency.
- The driving is **approximately sinusoidal in angle** for small amplitudes, or nonlinear for large amplitudes, depending on V_drill.
- Each square-wave period = one full back-and-forth oscillation of Pivot α.

---

## 3. Electronics and Circuit

### 3.1 Power Supply

**Keysight EDU36311A** triple-output bench DC supply:

| Channel | Role | Typical Setting |
|---------|------|-----------------|
| Ch1 (6 V / 5 A) | Relay coil power | Fixed 6 V DC |
| Ch2 (30 V / 1 A) | Drill motor power | Variable (amplitude control) |
| Ch3 | Unused / spare | — |

- Ch1 polarity matters: `+` must connect to the designated red terminal on the circuit board.

### 3.2 Function Generator

- Produces a **square wave** at the driving frequency `f_drive`.
- Output goes to the relay coil input (via the circuit board).
- This signal controls **when** the relay switches, and therefore the driving frequency.

### 3.3 Circuit Board (Acrylic Panel)

- A **clear acrylic panel** serves as the circuit carrier/breakout board.
- Banana-plug terminal pairs labeled on the panel (`R_b`, `R_o`, `R_a`, capacitor labels) are **legacy artifacts from previous builds** and do not represent the current circuit's component values.
- **Ground truth:** The **red handwritten markings** on the acrylic panel give the actual component values in use for this build.
- The relay module (blue component) is soldered onto the strip board portion of this assembly.

### 3.4 Signal Chain

```
Function Generator (square wave, freq = f_drive)
        |
        v
   Circuit Board
        |-- Relay coil switching signal
        |-- Relay coil power (EDU36311A Ch1, 6 V DC)
        |
        v
   DPDT Relay
        |-- Low half-cycle:  Motor+ → A, Motor- → B  (CW)
        |-- High half-cycle: Motor+ → B, Motor- → A  (CCW)
        |
        v
   DC Motor / Drill (EDU36311A Ch2, variable V)
        |
        v
   Drill Chuck → Aluminum Shaft → Bearing in Perspex Wall → Pivot α
        |
        v
   Arm 1 oscillates ±θ at frequency f_drive, amplitude ∝ V_drill
        |
        v
   Pivot β (free) → Arm 2 hangs and swings freely
```

### 3.5 Control Parameters

| Parameter | Physical Meaning | Set Via |
|-----------|-----------------|---------|
| `f_drive` | Driving frequency (Hz) | Function generator frequency |
| `V_drill` | Driving amplitude proxy | EDU36311A Ch2 voltage |

Higher `V_drill` → larger angular displacement per half-cycle.  
The two parameters form a **2D control space**. Fixed `f_drive` sweeps in `V_drill` produce the period-doubling cascade.

---

## 4. Video Tracking

### 4.1 Camera and Framing

- Camera positioned **straight-on** through the front perspex face.
- Frame captures both arms and both pivots in full.
- Multiple clips taken at different `(f_drive, V_drill)` settings.

### 4.2 Markers

- **Red markers** along Arm 2 (lower arm) — primary tracking targets.
- **Green marker** at or near Pivot β — joint reference.
- Same HSV color segmentation pipeline as Phase 1.

### 4.3 Clip Naming Convention

Phase 2 clips are keyed by control parameters:

```
fd_<freq_hz>_vd_<voltage_v>
```

Examples: `fd_1p5_vd_4v0`, `fd_2p0_vd_5v5`.  
Use `p` for the decimal point and no unit suffix on digits (consistent with Phase 1 angle convention).

### 4.4 Degrees of Freedom

| DOF | Symbol | Description |
|-----|--------|-------------|
| Arm 1 angle | θ₁ | Upper arm angle at Pivot α |
| Arm 2 angle | θ₂ | Lower arm angle at Pivot β |

Phase space is 4D: (θ₁, ω₁, θ₂, ω₂).

**Key difference from Phase 1:** θ₁ is no longer free — it is driven at `f_drive`. The holding/release phase structure does not apply; the entire recording is "driven steady-state".

---

## 5. Expected Physics

### 5.1 System Classification

- **Driven, damped double pendulum**
- Unlike Phase 1 (free, undriven → transient chaos only), this system receives continuous energy input from the motor.
- Energy balance: input from motor ≈ dissipation in bearings/air → system can sustain a **strange attractor**.
- Analogous to the RLD circuit (Part 2), but mechanically realized with a 2D parameter space.

### 5.2 Expected Dynamics

| V_drill | Expected behaviour |
|---------|-------------------|
| Low | Period-1 oscillation |
| Increasing (fixed f_drive) | Period-doubling cascade → period-2 → period-4 → chaos |
| Chaotic regime | Strange attractor in 4D phase space |

Structure mirrors Feigenbaum universality (same as logistic map, RLD circuit).

---

## 6. Deliverables

| Output | Description |
|--------|-------------|
| Phase portraits | (θ₁, ω₁) and (θ₂, ω₂) per clip, colored by time |
| Poincaré sections | Strobed at θ₁ = 0, ω₁ > 0; shows periodic/chaotic structure |
| Pairwise divergence | Lyapunov exponent estimate from trajectory separation |
| Return maps | Peak θ₂(n) vs θ₂(n+1) |
| Bifurcation diagram | Peak θ₂ vs V_drill at fixed f_drive |
| 3D phase animation | Rotating (θ₁, θ₂, t) or (θ₁, ω₁, θ₂) trajectory |

See `scripts/analysis/` for the shared pendulum analysis scripts.

---

## 7. Circuit Diagram

File: `experiments/week5-6-pendulum-motor-driven/docs/driven_pendulum_circuit.html`  
HTML/CSS annotated diagram with:
- Three input blocks (function generator, Ch1 relay power, Ch2 drill power)
- DPDT relay switching logic
- Mechanical output chain (shaft → bearing → Pivot α)
- Physics implication note (strange attractor, 2D parameter space)
- Flagged assumption: DPDT relay wiring — to be confirmed by relay part number

---

## 8. Open Questions

- Relay part number not confirmed → DPDT assumption unverified.
- Exact arm lengths (Arm 1, Arm 2) not measured.
- Spring constant(s) of the restoring springs on the disk — not characterized.
- Pivot-to-tip distances and marker positions along Arm 2 — not archived here.
- Whether shaft motion is truly symmetric CW/CCW or has a slight asymmetry (DC offset in θ₁).
- Effective driving angle (°/half-cycle) as a function of V_drill — no calibration curve yet.
