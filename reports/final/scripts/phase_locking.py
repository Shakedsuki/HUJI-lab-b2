#!/usr/bin/env python3
"""
phase_locking.py — arm-to-arm phase-locking diagnostic (driven 3.2 V family).

Per clip, recover the instantaneous phase of each arm from its (θ, ω) orbit,
form the relative phase dφ(t) = φ₁ − φ₂, and quantify how locked the two arms
are: Kuramoto coherence ρ ∈ [0,1] (1 = rigidly locked, 0 = wandering), the
locked phase offset mean_dφ (in-phase ≈ 0°, anti-phase ≈ 180°), and the
detuning df (Hz, the drift rate of dφ). Unlocked (low ρ / drifting dφ) is the
chaos signature; in-phase / anti-phase are the locked sub-cases.

Method (no Hilbert — θ and ω are already a 90°-quadrature pair):
    th_c = θ − mean(θ);  w_n = ω / (2π·f_drive);  φ = unwrap(atan2(w_n, th_c))
This assumes the (θ,ω) orbit ENCIRCLES the origin (libration). When an arm
goes over the top (rotation, θ winds past ±180°) the phase angle degenerates,
so each sliding window is flagged libration vs rotation; rotation windows are
excluded from ρ and surfaced separately (rotation is itself a chaos marker).

Conventions (match the pipeline):
  - θ in degrees (0° = down, +90° = right); ω in deg/s.
  - ω via the shared SG derivative (scripts/utils/kinematics.angular_velocity),
    per-clip window ≈ T_d/5 frames — NOT a raw finite difference.
  - first --transient seconds discarded (default 5 s; same value the other
    driven scripts use).
  - f_drive, T_d = 1/f_drive parsed from the stem (driven_helpers.parse_stem).
  - classification thresholds live in thresholds.py (PLOCK_*), not here.

Cross-family (--sweep): ρ(f_drive), mean_dφ(f_drive) and the ρ-vs-chaos-score
scatter, with the chaos reference taken as spectral entropy H_θ₂ (and D₂) —
the discriminators that actually resolve the chaotic band on this sweep. λ₁
(ftle_windows.json) is overlaid faintly but, per measurement, does NOT
discriminate here (its window classification labels every clip "chaotic"), so
it is shown for completeness only, not used as the reference.

Usage:
  python scripts/analysis/phase_locking.py --stem 3.2V_1.19Hz
  python scripts/analysis/phase_locking.py --stem 3.2V_0.9Hz --all-quality
  python scripts/analysis/phase_locking.py --sweep            # cross-family
  python scripts/analysis/phase_locking.py --self-test        # synthetic checks

Outputs:
  measurements/<stem>/phase_locking.json
  figures/phase_locking/<stem>_phase_locking.png        (QA-gated: pass only)
  figures/aggregate/phase_locking_<V>V.png              (--sweep)
"""

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from rich.console import Console

# marker colormap for the f_drive-vs-ρ view: endpoints are the exact locked /
# unlocked band colours (green = regular/low-H → red = chaotic/high-H), gold
# midpoint so transition points stay legible. Aligns with the ρ-zone bands.
CHAOS_CMAP = LinearSegmentedColormap.from_list(
    "bandGR", ["#2e8b57", "#e8c84d", "#c0392b"])

# Report copy — lives in reports/final/scripts/ (original is
# scripts/analysis/phase_locking.py). Resolve the repo's scripts/utils, and
# write the --sweep aggregate into reports/final/figures/ (FINAL_FIGURES).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts", "utils"))
FINAL_FIGURES = os.path.normpath(os.path.join(_HERE, "..", "figures"))
from paths import clip_dir, iter_clip_dirs, EXPERIMENTS          # noqa: E402
from figures_paths import figure_path, aggregate_path            # noqa: E402
from driven_helpers import parse_stem                            # noqa: E402
from kinematics import angular_velocity                          # noqa: E402
import thresholds as TH                                          # noqa: E402

console = Console()
RUN_PHASES = ("driven", "free_swing")
COL1, COL2 = "#2980b9", "#c0392b"     # arm1 blue, arm2 red


# ─────────────────────────────────────────────  DATA
def load_clip(stem):
    """(t, th1, th2) for the running phase, dropout-free, finite. Degrees / s."""
    path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.exists(path):
        path = os.path.join(clip_dir(stem), "tracking.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"no verification/tracking csv for {stem}")
    t, a, b = [], [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            try:
                tt, t1, t2 = float(r["time_s"]), float(r["theta1_deg"]), float(r["theta2_deg"])
            except (KeyError, ValueError):
                continue
            if np.isfinite(tt) and np.isfinite(t1) and np.isfinite(t2):
                t.append(tt); a.append(t1); b.append(t2)
    if len(t) < 200:
        raise ValueError(f"only {len(t)} clean frames for {stem} (need >= 200)")
    return np.asarray(t), np.asarray(a), np.asarray(b)


def odd(n):
    n = int(round(n))
    return n + 1 if n % 2 == 0 else max(n, 3)


# ─────────────────────────────────────────────  PHASE
def inst_phase(theta_deg, omega_dps, f_drive):
    """Instantaneous phase from the (θ,ω) orbit. ω normalised by 2π·f_drive so
    the loop is roughly round; returns the UNWRAPPED phase (radians)."""
    th_c = theta_deg - np.mean(theta_deg)
    w_n = omega_dps / (2.0 * np.pi * f_drive)
    return np.unwrap(np.arctan2(w_n, th_c))


def overtop_count(theta_wrapped):
    """Number of over-the-top crossings (|Δθ| > 180° between samples) — a full
    revolution past ±180°. >0 in a window ⇒ rotation, not libration."""
    return int(np.sum(np.abs(np.diff(theta_wrapped)) > 180.0))


# ─────────────────────────────────────────────  SLIDING WINDOW
def sliding_lock(t, dphi, th1, th2, f_drive):
    """Per sliding window (W = PLOCK_W_PERIODS drive periods, step
    PLOCK_STEP_PERIODS): coherence ρ, mean phase (deg), detuning df (Hz), and a
    libration/rotation flag (rotation if either arm goes over the top in it).
    Returns dict of arrays keyed by window-centre time."""
    dt = float(np.median(np.diff(t)))
    Td = 1.0 / f_drive
    W = odd(TH.PLOCK_W_PERIODS * Td / dt)
    step = max(1, int(round(TH.PLOCK_STEP_PERIODS * Td / dt)))
    n = len(t)
    tc, rho, mean, df, rot = [], [], [], [], []
    for s in range(0, n - W + 1, step):
        e = s + W
        dwin = dphi[s:e]
        twin = t[s:e]
        z = np.mean(np.exp(1j * dwin))
        rho.append(np.abs(z))
        mean.append(np.degrees(np.angle(z)))
        slope = np.polyfit(twin - twin[0], dwin, 1)[0]   # rad/s
        df.append(slope / (2.0 * np.pi))                 # Hz
        rotating = (overtop_count(th1[s:e]) > 0) or (overtop_count(th2[s:e]) > 0)
        rot.append(rotating)
        tc.append(0.5 * (twin[0] + twin[-1]))
    return {"t": np.asarray(tc), "rho": np.asarray(rho), "mean": np.asarray(mean),
            "df": np.asarray(df), "rotation": np.asarray(rot, dtype=bool),
            "W_frames": W, "step_frames": step}


def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


# ─────────────────────────────────────────────  CLASSIFY
def classify(rho, mean_dphi, df, f_drive, rot_frac):
    """(verdict, sub) from the global scalars + thresholds. Rotation-dominated
    clips are flagged 'rotation' (a chaos marker) up front."""
    if rot_frac > TH.PLOCK_ROT_FRAC:
        return "rotation", f"{rot_frac*100:.0f}% of windows rotate (over-the-top)"
    df_ok = abs(df) < TH.PLOCK_DF_TOL * f_drive
    if rho > TH.PLOCK_RHO_LOCK and df_ok:
        m = abs(wrap180(mean_dphi))
        if m < TH.PLOCK_INPHASE_DEG:
            return "locked", "in-phase"
        if abs(m - 180.0) < TH.PLOCK_ANTIPHASE_DEG:
            return "locked", "anti-phase"
        return "locked", f"general phase-lock (Δφ≈{wrap180(mean_dphi):.0f}°)"
    if rho < TH.PLOCK_RHO_UNLOCK or not df_ok:
        return "unlocked", "wandering relative phase (chaos candidate)"
    return "ambiguous", f"ρ in [{TH.PLOCK_RHO_UNLOCK},{TH.PLOCK_RHO_LOCK}] band"


# ─────────────────────────────────────────────  PER-CLIP COMPUTE
def compute(stem, transient_s=5.0):
    f_drive = parse_stem(stem)["f_drive_hz"]
    if not f_drive or f_drive <= 0:
        raise ValueError(f"could not parse f_drive from stem {stem!r}")
    t, th1, th2 = load_clip(stem)
    Td = 1.0 / f_drive
    dt = float(np.median(np.diff(t)))
    win = odd(0.2 * Td / dt)                       # ≈ T_d/5 frames, odd
    om1 = angular_velocity(th1, t, window=win)
    om2 = angular_velocity(th2, t, window=win)

    keep = t >= (t[0] + transient_s)               # discard startup transient
    if keep.sum() < 200:
        keep = np.ones(len(t), dtype=bool)
    t, th1, th2, om1, om2 = t[keep], th1[keep], th2[keep], om1[keep], om2[keep]

    phi1 = inst_phase(th1, om1, f_drive)
    phi2 = inst_phase(th2, om2, f_drive)
    dphi = np.unwrap(phi1 - phi2)                  # arm-to-arm (primary)
    # arm2-to-drive cross-check. atan2(w_n, th_c) winds CLOCKWISE (negative) for
    # a cosine, so a drive-locked arm winds at -f_drive; add 2π·f_drive·t so the
    # drift (psi_df) reads ≈0 when locked, nonzero/constant when detuned.
    psi = np.unwrap(phi2 + 2.0 * np.pi * f_drive * (t - t[0]))

    win_series = sliding_lock(t, dphi, th1, th2, f_drive)
    rot_frac = float(np.mean(win_series["rotation"]))

    # Global coherence over the FULL post-transient record (NOT a libration-only
    # sliver). This is what keeps ρ honest for every clip: a tumbling clip's
    # relative phase winds through many turns, so the Kuramoto average collapses
    # to ρ≈0 (correctly unlocked) on its own — no rotation special-case, and no
    # spurious high ρ from a near-stationary libration window. rot_frac is kept
    # as a secondary marker (how much of the clip is over-the-top tumbling).
    z = np.mean(np.exp(1j * dphi))
    rho = float(np.abs(z))
    mean_dphi = float(wrap180(np.degrees(np.angle(z))))
    df = float(np.polyfit(t - t[0], dphi, 1)[0] / (2.0 * np.pi))
    # drive cross-check: is arm-2 phase-locked to the drive? (boundedness of psi)
    psi_df = float(np.polyfit(t - t[0], psi, 1)[0] / (2.0 * np.pi))

    verdict, sub = classify(rho, mean_dphi, df, f_drive, rot_frac)
    return {
        "stem": stem, "f_drive_hz": f_drive, "transient_s": transient_s,
        "rho": rho, "mean_dphi_deg": mean_dphi, "df_hz": df,
        "psi_drive_df_hz": psi_df, "rotation_fraction": rot_frac,
        "verdict": verdict, "sub": sub,
        "sg_window_frames": win, "n_windows": int(len(win_series["t"])),
        # arrays kept for the figure (not all written to json)
        "_t": t, "_th1": th1, "_th2": th2, "_om1": om1, "_om2": om2,
        "_dphi": dphi, "_win": win_series,
    }


def to_json(res):
    """The scalar sidecar (drop the private array fields)."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


# ─────────────────────────────────────────────  PER-CLIP FIGURE
def make_figure(res, out_path):
    t, dphi, win = res["_t"], res["_dphi"], res["_win"]
    t0 = t - t[0]
    fig = plt.figure(figsize=(13, 9), constrained_layout=True)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1.0, 1.2])

    # (1) dφ(t) — flat ⇒ locked, drifting ⇒ unlocked
    ax = fig.add_subplot(gs[0, :])
    ax.plot(t0, np.degrees(dphi), lw=0.7, color="#333333")
    ax.set_ylabel("Δφ = φ₁−φ₂ (deg)")
    ax.set_title(f"{res['stem']}   f_drive={res['f_drive_hz']:g} Hz   "
                 f"ρ={res['rho']:.2f}   Δφ̄={res['mean_dphi_deg']:.0f}°   "
                 f"df={res['df_hz']:+.3f} Hz   →  {res['verdict'].upper()} ({res['sub']})",
                 loc="left", fontsize=11, fontweight="bold")
    ax.grid(alpha=0.25)

    # (2) ρ(t) sliding window with libration/rotation shading
    ax = fig.add_subplot(gs[1, :])
    wt = win["t"] - t[0]
    ax.plot(wt, win["rho"], lw=1.0, color="#8e44ad")
    ax.axhline(TH.PLOCK_RHO_LOCK, color="#2e8b57", ls=":", lw=0.8, label=f"lock ρ={TH.PLOCK_RHO_LOCK}")
    ax.axhline(TH.PLOCK_RHO_UNLOCK, color="#c0392b", ls=":", lw=0.8, label=f"unlock ρ={TH.PLOCK_RHO_UNLOCK}")
    # shade rotation windows
    rot = win["rotation"]
    if rot.any():
        dwt = np.median(np.diff(wt)) if len(wt) > 1 else 1.0
        for i in np.where(rot)[0]:
            ax.axvspan(wt[i] - dwt / 2, wt[i] + dwt / 2, color="#e67e22", alpha=0.15, lw=0)
    ax.set_ylim(0, 1.02); ax.set_ylabel("ρ (coherence)")
    ax.set_xlabel("time since transient (s)")
    ax.legend(loc="lower right", fontsize=8, ncol=3)
    ax.grid(alpha=0.25)
    ax.text(0.01, 0.05, "orange = rotation windows (phase invalid)",
            transform=ax.transAxes, fontsize=8, color="#e67e22")

    # (3) (θ,ω) phase-plane orbits, both arms — the loops the phase rides on
    for col, (th, om, c, lbl) in enumerate([
            (res["_th1"], res["_om1"], COL1, "arm 1"),
            (res["_th2"], res["_om2"], COL2, "arm 2")]):
        a = fig.add_subplot(gs[2, col])
        a.scatter(th, om, s=2, alpha=0.4, linewidths=0, color=c)
        a.axhline(0, color="0.85", lw=0.5); a.axvline(0, color="0.85", lw=0.5)
        a.set_xlabel("θ (deg)"); a.set_title(f"{lbl}  (θ, ω)", color=c, fontsize=10)
        if col == 0:
            a.set_ylabel("ω (deg/s)")
        a.grid(alpha=0.2)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# ─────────────────────────────────────────────  QA GATE
def _passed_qa(stem):
    try:
        with open(EXPERIMENTS, encoding="utf-8") as f:
            reg = json.load(f)
        for e in reg.values():
            if e.get("config_description") == stem:
                return e.get("overlay_verdict") == "pass"
    except (OSError, ValueError):
        pass
    return False


# ─────────────────────────────────────────────  CROSS-FAMILY
def _chaos_scores(stem):
    """(H_θ₂, D₂, λ₁) for a clip from its existing sidecars; NaN if missing."""
    cd = clip_dir(stem)
    H = D2 = lam = float("nan")
    try:
        H = json.load(open(os.path.join(cd, "chaos_windows.json"), encoding="utf-8")
                      ).get("spectral_entropy_th2", float("nan"))
    except (OSError, ValueError):
        pass
    try:
        D2 = json.load(open(os.path.join(cd, "dimension.json"), encoding="utf-8")
                       ).get("D2_correlation", float("nan"))
    except (OSError, ValueError):
        pass
    try:
        lam = json.load(open(os.path.join(cd, "ftle_windows.json"), encoding="utf-8")
                        ).get("lambda1_global", float("nan"))
    except (OSError, ValueError):
        pass
    return H, D2, lam


def run_sweep(voltage, transient_s):
    rows = []
    for stem, _d in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            console.print(f"[yellow]skip[/] {stem}: stem not parseable"); continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        try:
            res = compute(stem, transient_s)
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[yellow]skip[/] {stem}: {e}"); continue
        H, D2, lam = _chaos_scores(stem)
        rows.append((meta["f_drive_hz"], res["rho"], res["mean_dphi_deg"],
                     res["df_hz"], res["rotation_fraction"], res["verdict"], H, D2, lam, stem))
    if not rows:
        console.print(f"[red]no clips at {voltage} V[/]"); return None
    rows.sort()
    arr = lambda i: np.array([r[i] for r in rows], dtype=float)
    f, rho, mean, df, rotf, H, D2, lam = (arr(0), arr(1), arr(2), arr(3),
                                          arr(4), arr(6), arr(7), arr(8))

    os.makedirs(FINAL_FIGURES, exist_ok=True)
    HT = 0.4   # spectral-entropy chaos split (shared with the other report figs)

    # ── figure 1 (original): ρ vs H_θ₂, coloured by drive frequency ──────────
    # Two independent regular/chaotic measures — bottom-right = locked + regular,
    # top-left = unlocked + chaotic.
    fig, ax = plt.subplots(figsize=(7.6, 6.2), constrained_layout=True)
    sc = ax.scatter(rho, H, c=f, cmap="viridis", s=60, edgecolors="k", linewidths=0.4)
    for x, y, st in zip(rho, H, [r[9] for r in rows]):
        if np.isfinite(x) and np.isfinite(y):
            ax.annotate(st.split("_")[1].replace("Hz", ""), (x, y),
                        fontsize=6, alpha=0.6, xytext=(3, 3), textcoords="offset points")
    xlo, xhi = -0.02, 1.02
    ylo = float(np.nanmin(H)) - 0.04
    yhi = float(np.nanmax(H)) + 0.04
    RL = TH.PLOCK_RHO_LOCK
    ax.fill_between([RL, xhi], ylo, HT, color="#2e8b57", alpha=0.07, zorder=0)
    ax.fill_between([xlo, RL], HT, yhi, color="#c0392b", alpha=0.07, zorder=0)
    ax.axvline(RL, color="0.7", ls=":", lw=0.8, zorder=1)
    ax.axhline(HT, color="0.7", ls=":", lw=0.8, zorder=1)
    ax.set_xlabel("ρ  (arm phase coherence)")
    ax.set_ylabel("H_θ₂  (spectral entropy)")
    ax.set_xlim(xlo, xhi); ax.set_ylim(ylo, yhi); ax.grid(alpha=0.25)
    ax.set_title("Arm lock vs spectral chaos agree", loc="left", fontweight="bold")
    fig.colorbar(sc, ax=ax, label="f_drive (Hz)")
    out = os.path.join(FINAL_FIGURES, f"phase_locking_{voltage:g}V.png")
    fig.savefig(out, dpi=140); plt.close(fig)

    # ── figure 2: arm coherence ρ vs drive frequency, coloured by H_θ₂ ───────
    # (green = regular, red = chaotic — repo palette). ρ collapses through the
    # chaotic band and recovers to a rigid lock at the high-f end; colour (the
    # independent spectral measure) tracks ρ-height, so the two measures agree.
    # Same x = f_drive convention as every other report figure.
    fig2, ax2 = plt.subplots(figsize=(8.2, 6.0), constrained_layout=True)
    # locked / unlocked ρ zones as transparent horizontal bands (the middle
    # strip ρ∈(unlock, lock) is the transition / partial-lock zone, left clear)
    # neutral band hues (blue=locked, tan=unlocked) that do NOT compete with the
    # green→red H_θ₂ marker map — so marker colour means spectral entropy only,
    # while the bands just demarcate the ρ-zones.
    lock_band = ax2.axhspan(TH.PLOCK_RHO_LOCK, 1.02, color="#3b6ea5", alpha=0.13,
                            lw=0, zorder=0, label="phase locked")
    unlock_band = ax2.axhspan(-0.02, TH.PLOCK_RHO_UNLOCK, color="#b0855b", alpha=0.13,
                              lw=0, zorder=0, label="phase unlocked")
    sc2 = ax2.scatter(f, rho, c=H, cmap=CHAOS_CMAP, vmin=float(np.nanmin(H)),
                      vmax=float(np.nanmax(H)), s=70, edgecolors="k",
                      linewidths=0.4, zorder=3)
    ax2.set_xlabel(r"drive frequency $f_{drive}$ (Hz)")
    ax2.set_ylabel(r"$\rho$  (arm phase coherence)")
    ax2.set_ylim(-0.02, 1.02); ax2.grid(alpha=0.25)
    # legend in the clear transition strip (ρ≈0.5–0.8), framed so it reads on white
    leg = ax2.legend(handles=[lock_band, unlock_band], loc="center",
                     bbox_to_anchor=(0.5, 0.66), fontsize=9, frameon=True,
                     framealpha=0.95, edgecolor="0.3", fancybox=False)
    leg.get_frame().set_linewidth(1.0)
    cbar = fig2.colorbar(sc2, ax=ax2, pad=0.02)
    cbar.set_label(r"$H_{\theta_2}$  spectral entropy")
    cbar.ax.axhline(HT, color="0.2", lw=0.8)   # mark the chaos split on the bar
    out2 = os.path.join(FINAL_FIGURES, f"phase_locking_freq_{voltage:g}V.png")
    fig2.savefig(out2, dpi=140); plt.close(fig2)

    # printed summary — measured, no assertions
    console.print(f"\n[bold]phase-locking sweep — {voltage} V ({len(rows)} clips)[/]")
    console.print(f"{'f':>6} {'rho':>5} {'dphi':>6} {'df':>7} {'rot%':>5} {'H':>5}  verdict")
    for r in rows:
        console.print(f"{r[0]:>6.2f} {r[1]:>5.2f} {r[2]:>6.0f} {r[3]:>+7.3f} "
                      f"{r[4]*100:>4.0f}% {(r[6] if r[6]==r[6] else 0):>5.2f}  {r[5]}")
    console.print(f"[dim]→ {out}[/]")
    console.print(f"[dim]→ {out2}[/]")
    return out


# ─────────────────────────────────────────────  SELF-TEST
def self_test():
    """Synthetic sanity checks (no measured data)."""
    fps, f = 60.0, 1.0
    t = np.arange(0, 40, 1 / fps)
    # locked in-phase: both arms same phase
    th1 = 40 * np.cos(2 * np.pi * f * t)
    th2 = 35 * np.cos(2 * np.pi * f * t)
    om1 = angular_velocity(th1, t); om2 = angular_velocity(th2, t)
    p1 = inst_phase(th1, om1, f); p2 = inst_phase(th2, om2, f)
    z = np.mean(np.exp(1j * np.unwrap(p1 - p2)))
    console.print(f"[bold]self-test[/]  in-phase: ρ={abs(z):.3f} (expect ≈1), "
                  f"Δφ̄={np.degrees(np.angle(z)):.1f}° (expect ≈0)")
    # uniformly winding phase on a pure cosine
    dphi_wind = np.diff(np.unwrap(p1))
    console.print(f"             φ winds monotonically: {np.all(dphi_wind > 0) or np.all(dphi_wind < 0)} "
                  f"(median step {np.degrees(np.median(dphi_wind)):.2f}°)")
    # detuned: arm2 slightly faster → dφ drifts, df≈0.05 Hz
    th2d = 35 * np.cos(2 * np.pi * (f + 0.05) * t)
    om2d = angular_velocity(th2d, t); p2d = inst_phase(th2d, om2d, f)
    dphi_d = np.unwrap(p1 - p2d)
    df = np.polyfit(t, dphi_d, 1)[0] / (2 * np.pi)
    zc = np.mean(np.exp(1j * dphi_d))
    console.print(f"             detuned: df={df:+.3f} Hz (expect ≈+0.05), ρ={abs(zc):.3f} (expect <1)")


# ─────────────────────────────────────────────  CLI
def parse_args():
    p = argparse.ArgumentParser(description="Arm phase-locking diagnostic.")
    p.add_argument("--stem", default=None, help="clip stem, e.g. 3.2V_1.19Hz")
    p.add_argument("--sweep", action="store_true", help="cross-family aggregate figure")
    p.add_argument("--voltage", type=float, default=3.2, help="sweep voltage (default 3.2)")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to skip at the start (default 5)")
    p.add_argument("--all-quality", action="store_true",
                   help="write the per-clip figure even if the clip failed overlay QA")
    p.add_argument("--no-plot", action="store_true", help="JSON only, no per-clip figure")
    p.add_argument("--self-test", action="store_true", help="run synthetic checks and exit")
    return p.parse_args()


def main():
    args = parse_args()
    if args.self_test:
        self_test(); return 0
    if args.sweep:
        run_sweep(args.voltage, args.transient); return 0
    if not args.stem:
        console.print("[red]ERROR:[/] provide --stem, --sweep, or --self-test"); return 1

    res = compute(args.stem, args.transient)
    out_json = os.path.join(clip_dir(args.stem), "phase_locking.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(to_json(res), f, indent=2, ensure_ascii=False)

    r = res
    console.print(f"[cyan]{r['stem']}[/]  f_drive={r['f_drive_hz']:g} Hz  "
                  f"[bold]{r['verdict'].upper()}[/] ({r['sub']})")
    console.print(f"  ρ={r['rho']:.3f}  Δφ̄={r['mean_dphi_deg']:.1f}°  "
                  f"df={r['df_hz']:+.4f} Hz  rotation={r['rotation_fraction']*100:.0f}%  "
                  f"[dim](drive cross-check df={r['psi_drive_df_hz']:+.4f} Hz)[/]")
    console.print(f"  [dim]→ {out_json}[/]")

    if not args.no_plot:
        if _passed_qa(args.stem) or args.all_quality:
            out_png = figure_path("phase_locking", args.stem)
            make_figure(res, out_png)
            console.print(f"  [dim]→ {out_png}[/]")
        else:
            console.print("  [yellow]figure skipped[/] — clip not overlay-QA 'pass' "
                          "[dim](--all-quality to force)[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
