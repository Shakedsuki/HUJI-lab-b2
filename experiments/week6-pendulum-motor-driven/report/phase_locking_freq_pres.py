"""
Presentation recreation of the phase-locking rho(f_drive) figure.

Reproduces figure 2 of reports/final/scripts/phase_locking.py (arm phase
coherence rho vs drive frequency, coloured by spectral entropy H_theta2, with
phase-locked / phase-unlocked bands) but with LARGE labels, ticks and markers so
it's legible from the back of a lecture hall.

Reuses that script's exact computation (compute + _chaos_scores) — no new
physics here, only bigger type.

Run:  python phase_locking_freq_pres.py
"""
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "reports", "final", "scripts"))
import phase_locking as PL   # noqa: E402  (sets up scripts/utils on import)

VOLTAGE = 3.2
TRANSIENT_S = 5.0
HT = 0.4                     # spectral-entropy chaos split (same as the report)
OUT_PNG = os.path.join(HERE, "phase_locking_freq_pres.png")

# ── large-screen type sizes ──
FS_LABEL, FS_TICK = 26, 20
FS_CBAR_LABEL, FS_CBAR_TICK = 23, 18
FS_LEGEND = 19
MARKER_S = 160


def gather(voltage):
    rows = []
    for stem, _d in PL.iter_clip_dirs():
        try:
            meta = PL.parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        try:
            res = PL.compute(stem, TRANSIENT_S)
        except (FileNotFoundError, ValueError):
            continue
        H, _D2, _lam = PL._chaos_scores(stem)
        rows.append((meta["f_drive_hz"], res["rho"], H))
    rows.sort()
    return (np.array([r[0] for r in rows], float),
            np.array([r[1] for r in rows], float),
            np.array([r[2] for r in rows], float))


f, rho, H = gather(VOLTAGE)
if len(f) == 0:
    raise SystemExit(f"no clips found at {VOLTAGE} V")

fig, ax = plt.subplots(figsize=(13.0, 8.4), constrained_layout=True)
lock_band = ax.axhspan(PL.TH.PLOCK_RHO_LOCK, 1.02, color="#3b6ea5", alpha=0.13,
                       lw=0, zorder=0, label="phase locked")
unlock_band = ax.axhspan(-0.02, PL.TH.PLOCK_RHO_UNLOCK, color="#b0855b", alpha=0.13,
                         lw=0, zorder=0, label="phase unlocked")
sc = ax.scatter(f, rho, c=H, cmap=PL.CHAOS_CMAP, vmin=float(np.nanmin(H)),
                vmax=float(np.nanmax(H)), s=MARKER_S, edgecolors="k",
                linewidths=0.8, zorder=3)

ax.set_xlabel(r"drive frequency $f_{drive}$ (Hz)", fontsize=FS_LABEL)
ax.set_ylabel(r"$\rho$  (arm phase coherence)", fontsize=FS_LABEL)
ax.set_ylim(-0.02, 1.02)
ax.grid(alpha=0.25)
ax.tick_params(labelsize=FS_TICK)

leg = ax.legend(handles=[lock_band, unlock_band], loc="center",
                bbox_to_anchor=(0.5, 0.66), fontsize=FS_LEGEND, frameon=True,
                framealpha=0.95, edgecolor="0.3", fancybox=False)
leg.get_frame().set_linewidth(1.2)

cbar = fig.colorbar(sc, ax=ax, pad=0.02)
cbar.set_label(r"$H_{\theta_2}$  spectral entropy", fontsize=FS_CBAR_LABEL)
cbar.ax.tick_params(labelsize=FS_CBAR_TICK)
cbar.ax.axhline(HT, color="0.2", lw=1.0)

fig.savefig(OUT_PNG, dpi=200)
print(f"Saved -> {OUT_PNG}  ({len(f)} clips)")
