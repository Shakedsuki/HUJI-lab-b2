"""
poincare_forming_animation.py
------------------------------
Non-interactive renderer: side-by-side MP4 of two clips' Poincaré
sections accumulating in real time.

LEFT  : Regular clip (37°)        — points settle into a tight cluster
RIGHT : Fully chaotic clip (180°) — points fill a 2D area

Both panels share the same physical seconds-elapsed clock so the
contrast in crossing rate is visceral. Same (θ₁, ω₁) axes (extreme
of the chaotic clip), so the chaotic cloud literally fills the
phase-space region the regular orbit barely touches.

Output: figures/aggregate/poincare_forming.mp4
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import animation, cm
import matplotlib.colors as mcolors

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
from figures_paths import aggregate_path, mirror_to_ready  # noqa: E402

REGULAR_STEM = "th1_p044_th2_m001"
CHAOTIC_STEM = "th1_p180_th2_m179"

OUTPUT_FPS       = 30
ANIM_DURATION_S  = 30.0      # total wall-clock video length
FLASH_FRAMES     = int(0.4 * OUTPUT_FPS)

def load_crossings(stem):
    """Returns DataFrame with t_s (relative to t=0), theta1_deg, omega1_deg_s."""
    path = os.path.join(MEAS_DIR, stem, "poincare.csv")
    df = pd.read_csv(path)
    df = df.sort_values("t_s").reset_index(drop=True)
    df["t_rel"] = df["t_s"] - df["t_s"].iloc[0]
    return df

def main():
    reg = load_crossings(REGULAR_STEM)
    cha = load_crossings(CHAOTIC_STEM)
    print(f"  regular ({REGULAR_STEM}): {len(reg)} crossings over "
          f"{reg['t_rel'].iloc[-1]:.1f}s")
    print(f"  chaotic ({CHAOTIC_STEM}): {len(cha)} crossings over "
          f"{cha['t_rel'].iloc[-1]:.1f}s")

    # Each panel gets its own physical-time clock that finishes at the
    # video's end. The regular clip's full 18s clock is mapped to the
    # whole 30s video; the chaotic clip's 515s clock is also mapped to
    # the whole 30s video (so chaotic plays ~17× sped up). Same wall-
    # clock seconds elapsed → same fraction of each clip's natural
    # duration shown.
    n_frames = int(ANIM_DURATION_S * OUTPUT_FPS)
    t_reg_max = reg["t_rel"].iloc[-1]
    t_cha_max = cha["t_rel"].iloc[-1]

    # Pre-compute per-frame visible-up-to-index
    progress = np.linspace(0, 1, n_frames)
    reg_t_at = progress * t_reg_max
    cha_t_at = progress * t_cha_max

    reg_visible_idx = np.searchsorted(reg["t_rel"].to_numpy(), reg_t_at)
    cha_visible_idx = np.searchsorted(cha["t_rel"].to_numpy(), cha_t_at)

    # Shared axes: span union of both clips' (θ₁, ω₁) ranges
    th_all = np.concatenate([reg["theta1_deg"], cha["theta1_deg"]])
    om_all = np.concatenate([reg["omega1_deg_s"], cha["omega1_deg_s"]])
    th_pad = 0.08 * (th_all.max() - th_all.min())
    om_pad = 0.08 * (om_all.max() - om_all.min())
    xlim = (th_all.min() - th_pad, th_all.max() + th_pad)
    ylim = (om_all.min() - om_pad, om_all.max() + om_pad)

    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(14, 7))
    for ax, title in ((ax_l, "Regular   ·   θ₁(0)=37°"),
                       (ax_r, "Fully chaotic   ·   θ₁(0)=180°")):
        ax.set_xlim(xlim); ax.set_ylim(ylim)
        ax.axhline(0, color="gray", lw=0.4, ls="--", alpha=0.6)
        ax.axvline(0, color="gray", lw=0.4, ls="--", alpha=0.6)
        ax.grid(alpha=0.2)
        ax.set_xlabel(r"$\theta_1$ at section (deg)")
        ax.set_title(title, fontsize=12)
    ax_l.set_ylabel(r"$\omega_1$ at section (deg/s)")

    # Persistent + flash artists per panel
    persist_l = ax_l.scatter([], [], c=[], cmap="viridis",
                              s=22, edgecolor="black", linewidth=0.3,
                              vmin=0, vmax=t_reg_max)
    persist_r = ax_r.scatter([], [], c=[], cmap="viridis",
                              s=22, edgecolor="black", linewidth=0.3,
                              vmin=0, vmax=t_cha_max)
    flash_l, = ax_l.plot([], [], "*", color="#ffe845", markersize=22,
                          markeredgecolor="#aa7700", markeredgewidth=1.0)
    flash_r, = ax_r.plot([], [], "*", color="#ffe845", markersize=22,
                          markeredgecolor="#aa7700", markeredgewidth=1.0)
    counter_l = ax_l.text(0.02, 0.97, "", transform=ax_l.transAxes,
                            ha="left", va="top", fontsize=11,
                            bbox=dict(boxstyle="round", facecolor="white",
                                      alpha=0.85))
    counter_r = ax_r.text(0.02, 0.97, "", transform=ax_r.transAxes,
                            ha="left", va="top", fontsize=11,
                            bbox=dict(boxstyle="round", facecolor="white",
                                      alpha=0.85))
    clock = fig.text(0.5, 0.02, "", ha="center", fontsize=10,
                       family="monospace")

    fig.suptitle(
        "Poincaré sections forming in real time — same wall clock, two regimes\n"
        r"section: $\theta_1+\theta_2=0$ upward  ·  "
        "regular settles to a few points; chaotic fills the plane",
        fontsize=12, y=0.99,
    )
    plt.tight_layout()

    # Track previous visible counts for the flash effect
    state = {"prev_reg": 0, "prev_cha": 0,
              "flash_l_until": 0, "flash_r_until": 0,
              "flash_l_pt": None, "flash_r_pt": None}

    def update(frame):
        n_l = int(reg_visible_idx[frame])
        n_r = int(cha_visible_idx[frame])

        # Persistent dots
        if n_l != state["prev_reg"]:
            sub = reg.iloc[:n_l]
            persist_l.set_offsets(np.column_stack([sub["theta1_deg"],
                                                     sub["omega1_deg_s"]]))
            persist_l.set_array(sub["t_rel"].to_numpy())
            if n_l > state["prev_reg"]:
                last = reg.iloc[n_l - 1]
                state["flash_l_until"] = frame + FLASH_FRAMES
                state["flash_l_pt"]   = (last["theta1_deg"], last["omega1_deg_s"])
            state["prev_reg"] = n_l

        if n_r != state["prev_cha"]:
            sub = cha.iloc[:n_r]
            persist_r.set_offsets(np.column_stack([sub["theta1_deg"],
                                                     sub["omega1_deg_s"]]))
            persist_r.set_array(sub["t_rel"].to_numpy())
            if n_r > state["prev_cha"]:
                last = cha.iloc[n_r - 1]
                state["flash_r_until"] = frame + FLASH_FRAMES
                state["flash_r_pt"]   = (last["theta1_deg"], last["omega1_deg_s"])
            state["prev_cha"] = n_r

        # Flash markers
        if frame < state["flash_l_until"] and state["flash_l_pt"] is not None:
            flash_l.set_data([state["flash_l_pt"][0]], [state["flash_l_pt"][1]])
        else:
            flash_l.set_data([], [])
        if frame < state["flash_r_until"] and state["flash_r_pt"] is not None:
            flash_r.set_data([state["flash_r_pt"][0]], [state["flash_r_pt"][1]])
        else:
            flash_r.set_data([], [])

        counter_l.set_text(f"crossings: {n_l}")
        counter_r.set_text(f"crossings: {n_r}")
        clock.set_text(f"  regular t = {reg_t_at[frame]:6.2f} s    |    "
                        f"chaotic t = {cha_t_at[frame]:6.2f} s    |    "
                        f"video {frame/OUTPUT_FPS:5.2f} / {ANIM_DURATION_S:.0f} s")
        return (persist_l, persist_r, flash_l, flash_r,
                counter_l, counter_r, clock)

    print(f"  rendering {n_frames} frames at {OUTPUT_FPS} fps "
          f"({ANIM_DURATION_S:.0f}s output)…")
    anim = animation.FuncAnimation(fig, update, frames=n_frames,
                                      interval=1000.0 / OUTPUT_FPS,
                                      blit=False)
    out = aggregate_path("poincare_forming.mp4")
    writer = animation.FFMpegWriter(fps=OUTPUT_FPS, bitrate=2400)
    anim.save(out, writer=writer, dpi=120)
    plt.close(fig)
    mirror_to_ready(out)
    print(f"  wrote {out}")

if __name__ == "__main__":
    main()
