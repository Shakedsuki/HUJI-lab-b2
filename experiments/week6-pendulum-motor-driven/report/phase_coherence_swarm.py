"""
Kuramoto phase-coherence figure (slide "מדדים לכאוס (2)").

Side-by-side unit-circle "phasor swarm" of the arm-to-arm relative phase:
    rho = |<exp(i (phi1 - phi2))>|
Each sample's phasor exp(i(phi1-phi2)) sits on the unit circle; their vector
mean is the black resultant arrow, whose length IS rho.

  Periodic (0.9 Hz): phases locked -> phasors cluster -> long arrow, rho ~ 1.
  Chaotic  (1.19 Hz): phases wander -> phasors cancel  -> tiny arrow, rho ~ 0.

phi_k = inst_phase(theta_k, omega_k, f_drive): the angle in the (theta, omega)
plane (omega normalised by 2*pi*f_drive), exactly as scripts/analysis/
phase_locking.py defines it. omega via kinematics.angular_velocity.
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "scripts", "utils"))
from kinematics import angular_velocity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
OUT_PNG = os.path.join(HERE, "phase_coherence_swarm.png")

TRANSIENT_S = 5.0
PANELS = [
    {"label": "Periodic", "stem": "3.2V_0.9Hz",  "f": 0.9,  "color": "green"},
    {"label": "Chaotic",  "stem": "3.2V_1.19Hz", "f": 1.19, "color": "#d62728"},
]


def inst_phase(theta_deg, omega_dps, f_drive):
    th_c = theta_deg - np.mean(theta_deg)
    w_n = omega_dps / (2.0 * np.pi * f_drive)
    return np.unwrap(np.arctan2(w_n, th_c))


def relative_phase(stem, f):
    df = pd.read_csv(os.path.join(BASE, "measurements", stem, "tracking.csv"))
    df = df.dropna(subset=["time_s", "theta1_deg", "theta2_deg"])
    t = df["time_s"].to_numpy()
    th1 = df["theta1_deg"].to_numpy()
    th2 = df["theta2_deg"].to_numpy()
    keep = t >= t[0] + TRANSIENT_S
    t, th1, th2 = t[keep], th1[keep], th2[keep]
    dt = float(np.median(np.diff(t)))
    win = int(0.2 * (1.0 / f) / dt) | 1            # ~T_drive/5 frames, odd
    o1 = angular_velocity(th1, t, window=max(win, 3))
    o2 = angular_velocity(th2, t, window=max(win, 3))
    phi1 = inst_phase(th1, o1, f)
    phi2 = inst_phase(th2, o2, f)
    return phi1 - phi2


fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.0))
theta_ring = np.linspace(0, 2 * np.pi, 240)
for ax, p in zip(axes, PANELS):
    dphi = relative_phase(p["stem"], p["f"])
    z = np.exp(1j * dphi)
    R = z.mean()
    rho = abs(R)

    ax.plot(np.cos(theta_ring), np.sin(theta_ring), color="0.75", lw=1.2, zorder=1)
    s = z[::5]                                     # subsample swarm for clarity
    ax.scatter(s.real, s.imag, s=10, color=p["color"], alpha=0.22,
               edgecolors="none", zorder=2)
    ax.annotate("", xy=(R.real, R.imag), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", lw=3.2, color="black",
                                mutation_scale=22), zorder=5)
    ax.plot(0, 0, "o", ms=4, color="black", zorder=6)
    ax.set_title(f"{p['label']} — {p['f']:g} Hz", fontsize=16, fontweight="bold")
    ax.text(0, -1.34, rf"$\rho = {rho:.2f}$", ha="center", va="center",
            fontsize=20, fontweight="bold")
    ax.set_aspect("equal")
    ax.set_xlim(-1.28, 1.28)
    ax.set_ylim(-1.5, 1.28)
    ax.axis("off")

fig.suptitle(r"Phase coherence  $\rho = \left|\langle e^{\,i(\phi_1-\phi_2)}\rangle\right|$",
             fontsize=16, y=0.98)
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(OUT_PNG, dpi=200, bbox_inches="tight")
print(f"Saved -> {OUT_PNG}")
for p in PANELS:
    print(p["stem"], "rho=", round(abs(np.exp(1j * relative_phase(p["stem"], p["f"])).mean()), 3))
