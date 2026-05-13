"""
chaos_vs_regular.py
--------------------
Side-by-side 2×2 figure contrasting chaotic vs regular dynamics.

Top row    : θ_abs(t) trace, colored by E/E_inversion. Inversion
             thresholds (±90°, ±180°) drawn.
Bottom row : Power spectrum of θ_abs(t), log-log. K-test value
             (Gottwald-Melbourne 0-1) annotated.

Left  column: th1_p180_th2_m179  — fully chaotic (long_recording)
Right column: th1_p044_th2_m001  — regular regime (37° release)

The contrast is the message:
    chaotic  ⇒ broadband spectrum + inversion-crossing trace + K≈1
    regular  ⇒ sharp spectral peaks + bounded trace + K≈0
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
from chaos_analyze import (  # noqa: E402
    load_free_swing, compute_topological, k01_test,
)

CHAOTIC_STEM = "th1_p180_th2_m179"
REGULAR_STEM = "th1_p044_th2_m001"

def load_one(stem):
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    data = load_free_swing(csv)
    topo = compute_topological(data)
    # K-test on θ₂_abs (the same target chaos_analyze uses for the headline K)
    K = k01_test(topo["theta2_abs"])
    # Power spectrum of θ₂_abs
    x = topo["theta2_abs"] - np.mean(topo["theta2_abs"])
    t = topo["time_s"]
    dt = float(np.mean(np.diff(t)))
    n = len(x)
    fft   = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, d=dt)
    power = np.abs(fft) ** 2
    # drop DC for log-log readability
    freqs, power = freqs[1:], power[1:]
    return {
        "stem": stem, "topo": topo, "K": K,
        "freqs": freqs, "power": power,
    }

def plot_trace(ax, d, label, t_max=None):
    topo = d["topo"]
    t  = topo["time_s"] - topo["time_s"][0]
    th = topo["theta2_abs"]
    er = topo["E_ratio_trace"]

    # Truncate to actively-chaotic window if requested
    if t_max is not None:
        m = t <= t_max
        t, th, er = t[m], th[m], er[m]

    # Sub-sample for plotting speed if very long
    if len(t) > 8000:
        stride = len(t) // 8000
        t, th, er = t[::stride], th[::stride], er[::stride]

    norm = Normalize(vmin=0, vmax=max(1.1, float(np.nanmax(er))))
    sc = ax.scatter(t, th, c=er, cmap="viridis", norm=norm, s=1.6,
                     alpha=0.8, edgecolor="none")
    ax.set_xlabel("time from release (s)")
    ax.set_ylabel(r"$\theta_2^{\rm abs}$ (deg)")
    ax.set_title(label, fontsize=11)
    ax.grid(alpha=0.25)
    cb = plt.colorbar(sc, ax=ax, shrink=0.85)
    cb.set_label(r"$E / E_{\rm inversion}$", fontsize=9)

def plot_spectrum(ax, d, label):
    ax.loglog(d["freqs"], d["power"], lw=0.6, color="#3a4f7a", alpha=0.85)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel(r"power (deg$^2$)")
    K = d["K"]
    ax.set_title(label + rf"    $K = {K:.2f}$", fontsize=11)
    ax.grid(which="both", alpha=0.2)

def main():
    print("loading chaotic clip…")
    chaotic = load_one(CHAOTIC_STEM)
    print(f"  K = {chaotic['K']:.3f}")
    print("loading regular clip…")
    regular = load_one(REGULAR_STEM)
    print(f"  K = {regular['K']:.3f}")

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # Trim the chaotic θ_abs trace to the actively-chaotic window
    # (after ~55s the long_recording is in low-amplitude bound oscillation).
    plot_trace(axes[0, 0], chaotic,
                "Chaotic   ·   $\\theta_1(0)=180°$",
                t_max=55.0)
    plot_trace(axes[0, 1], regular,
                "Regular   ·   $\\theta_1(0)=37°$")

    # Match θ y-axis on the top row so the amplitude contrast is direct
    yhi = max(max(abs(y) for y in axes[0, 0].get_ylim()),
                max(abs(y) for y in axes[0, 1].get_ylim()),
                200)
    axes[0, 0].set_ylim(-yhi, yhi)
    axes[0, 1].set_ylim(-yhi, yhi)

    plot_spectrum(axes[1, 0], chaotic, "Chaotic — broadband")
    plot_spectrum(axes[1, 1], regular, "Regular — sharp peaks")

    # Force matched x AND y limits on the spectra so the broadband-vs-sharp-peaks
    # comparison is direct (both record lengths/sample counts produce different
    # native frequency ranges otherwise).
    xlim_lo = min(axes[1, 0].get_xlim()[0], axes[1, 1].get_xlim()[0])
    xlim_hi = max(axes[1, 0].get_xlim()[1], axes[1, 1].get_xlim()[1])
    ylim_lo = min(axes[1, 0].get_ylim()[0], axes[1, 1].get_ylim()[0])
    ylim_hi = max(axes[1, 0].get_ylim()[1], axes[1, 1].get_ylim()[1])
    axes[1, 0].set_xlim(xlim_lo, xlim_hi); axes[1, 0].set_ylim(ylim_lo, ylim_hi)
    axes[1, 1].set_xlim(xlim_lo, xlim_hi); axes[1, 1].set_ylim(ylim_lo, ylim_hi)

    fig.tight_layout()

    out = aggregate_path("chaos_vs_regular.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    mirror_to_ready(out)
    print(f"  wrote {out}")

if __name__ == "__main__":
    main()
