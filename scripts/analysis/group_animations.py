"""
group_animations.py
--------------------
IC-sensitivity animations for a curated twin-IC group. Time-aligns
every clip's trajectory to t=0 at release and renders three
complementary views, all on the same time axis:

  (A) ghost  — 6 schematic stick-pendulums on one canvas, all
              starting in lockstep, fanning out as chaos asserts.
              The most legible "look at this!" demo.

  (B) phase  — phase portrait (theta1, omega1) trace-race. Six
              comets leaving trails in canonical phase space.

  (C) 3d     — 3D ribbon overlay in (theta1, theta2, omega1) space,
              all six trajectories drawn incrementally with no
              camera rotation. Most physics-y; pairs with the
              static phase_3d_trajectory PNG.

Output to figures/aggregate/group_<group>_<type>.mp4.

Usage:
    # Default group_a, all three animations:
    python scripts/analysis/group_animations.py --group group_a --type all

    # Just one:
    python scripts/analysis/group_animations.py --group group_a --type ghost

    # Custom set:
    python scripts/analysis/group_animations.py --stems s1,s2,s3 --type ghost

    # Speed control:
    python scripts/analysis/group_animations.py --group group_a --type 3d \\
        --max-time 8 --speed 0.5 --fps 30
"""

import argparse
import csv
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
import matplotlib.animation as animation
from matplotlib.collections import LineCollection
from mpl_toolkits.mplot3d import Axes3D                        # noqa: F401
from mpl_toolkits.mplot3d.art3d import Line3DCollection


ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.abspath(__file__))))
MEAS_DIR = os.path.join(ROOT, "measurements")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import aggregate_path, mirror_to_journal  # noqa: E402

GROUPS = {
    "group_a": [
        "th1_p091_th2_m001",
        "th1_p092_th2_m002",
        "th1_p092_th2_p000",
        "th1_p093_th2_m000",
        "th1_p093_th2_m002",
        "th1_p094_th2_p000",
    ],
    "tier_1": [
        "th1_p044_th2_m001",
        "th1_p056_th2_m001",
        "th1_p082_th2_p001",
        "th1_p180_th2_m179",
    ],
}

# Schematic pendulum geometry (matplotlib math coords; +y up).
# 0 deg = straight down; +90 = right; -90 = left.
ARM_LEN = 1.0   # arbitrary units; both arms same length, the rig has L=L


# ─────────────────────────────────────────────
# DATA LOADING (shared with group_overlay.py)
# ─────────────────────────────────────────────

def load_traj(stem):
    """Load free_swing (t, th1, th2, om1, om2) for a clip."""
    path = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(path):
        return None
    t, th1, th2, om1, om2 = [], [], [], [], []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") != "free_swing":
                continue
            try:
                vals = (float(r["time_s"]),
                        float(r["theta1_deg"]),
                        float(r["theta2_deg"]),
                        float(r["omega1_deg_s"]),
                        float(r["omega2_deg_s"]))
            except (KeyError, ValueError):
                continue
            t.append(vals[0]); th1.append(vals[1]); th2.append(vals[2])
            om1.append(vals[3]); om2.append(vals[4])
    if len(t) < 30:
        return None
    t = np.array(t)
    return {
        "stem": stem,
        "t":    t - t[0],
        "th1":  np.array(th1),
        "th2":  np.array(th2),
        "om1":  np.array(om1),
        "om2":  np.array(om2),
    }


def time_align(rows, max_time=None, dt_out=None):
    """Resample each clip onto a common time grid. Returns list of dicts
    with keys (stem, t, th1, th2, om1, om2) all on the same grid."""
    if dt_out is None:
        dt_out = float(np.median(np.diff(rows[0]["t"])))
    t_max = min(r["t"][-1] for r in rows)
    if max_time is not None:
        t_max = min(t_max, max_time)
    grid = np.arange(0, t_max, dt_out)
    out = []
    for r in rows:
        # Unwrap before interpolating so the ±180 wrap doesn't fold.
        th1u = np.degrees(np.unwrap(np.radians(r["th1"])))
        th2u = np.degrees(np.unwrap(np.radians(r["th2"])))
        out.append({
            "stem": r["stem"],
            "t":    grid,
            "th1":  np.interp(grid, r["t"], th1u),
            "th2":  np.interp(grid, r["t"], th2u),
            "om1":  np.interp(grid, r["t"], r["om1"]),
            "om2":  np.interp(grid, r["t"], r["om2"]),
        })
    return out


def colors_for(n):
    cmap = plt.cm.tab10
    return [cmap(i / max(1, n - 1)) for i in range(n)]


def pendulum_xy(th1_deg, th2_deg):
    """Return (pivot, elbow, bob) (x, y) for one frame in math coords.
    0 deg = down; +90 = right; -90 = left."""
    th1 = np.radians(th1_deg)
    th2 = np.radians(th2_deg)
    pivot  = np.array([0.0, 0.0])
    elbow  = pivot + ARM_LEN * np.array([np.sin(th1), -np.cos(th1)])
    bob    = elbow + ARM_LEN * np.array([np.sin(th1 + th2),
                                          -np.cos(th1 + th2)])
    return pivot, elbow, bob


# ─────────────────────────────────────────────
# (A) GHOST PENDULUMS
# ─────────────────────────────────────────────

def render_ghost(rows, out_path, fps_out, speed):
    """6 schematic pendulums, time-synchronized at release."""
    n = len(rows)
    cs = colors_for(n)
    grid = rows[0]["t"]
    dt_grid = grid[1] - grid[0]

    # Subsample: write one frame per (1/fps_out / speed) seconds.
    step = max(1, int(round(1.0 / (fps_out * speed) / dt_grid)))
    frame_idx = np.arange(0, len(grid), step)

    fig, (ax_pend, ax_div) = plt.subplots(1, 2, figsize=(13, 6.5),
                                           gridspec_kw={"width_ratios":[1.4, 1]})

    # Left: schematic canvas.
    ax_pend.set_aspect("equal")
    ax_pend.set_xlim(-2.3, 2.3)
    ax_pend.set_ylim(-2.3, 0.5)
    ax_pend.set_title("Ghost pendulums — 6 clips, identical IC class "
                      r"($\theta_1 \approx 90°, \theta_2 \approx 0°$)")
    ax_pend.axis("off")
    # Pivot dot.
    ax_pend.plot(0, 0, "o", color="#222", markersize=9)
    # Reach circles for visual reference.
    th = np.linspace(0, 2 * np.pi, 80)
    ax_pend.plot(np.cos(th), np.sin(th) - 0,
                 color="#bbb", lw=0.5, ls=":")
    ax_pend.plot(2 * np.cos(th), 2 * np.sin(th) - 0,
                 color="#bbb", lw=0.5, ls=":")

    # Per-clip artists: upper arm, lower arm, elbow dot, bob dot.
    upper_lines = []
    lower_lines = []
    elbow_dots  = []
    bob_dots    = []
    for c in cs:
        ul, = ax_pend.plot([], [], color=c, lw=2.0, alpha=0.85)
        ll, = ax_pend.plot([], [], color=c, lw=2.0, alpha=0.85)
        ed, = ax_pend.plot([], [], "o", color=c, markersize=6)
        bd, = ax_pend.plot([], [], "o", color=c, markersize=8)
        upper_lines.append(ul); lower_lines.append(ll)
        elbow_dots.append(ed);  bob_dots.append(bd)

    # Time label.
    time_txt = ax_pend.text(0.02, 0.95, "", transform=ax_pend.transAxes,
                            fontsize=14, fontweight="bold", color="#222")

    # Right: pairwise log-divergence growing in real time.
    ax_div.set_yscale("log")
    ax_div.set_xlim(0, grid[-1])
    ax_div.set_ylim(0.5, 360)
    ax_div.set_xlabel("t (s)")
    ax_div.set_ylabel(r"pair separation $\Delta_{ij}$ (deg, log scale)")
    ax_div.set_title(r"15 pairwise $\Delta(t)$ curves")
    ax_div.grid(True, alpha=0.3, which="both")

    # Pre-compute pairs and divergence series.
    pair_idx = [(i, j) for i in range(n) for j in range(i + 1, n)]
    pair_lines = []
    for _ in pair_idx:
        ln, = ax_div.plot([], [], color="black", lw=0.6, alpha=0.4)
        pair_lines.append(ln)
    mean_line, = ax_div.plot([], [], color="tab:red", lw=2.2,
                              label=r"$\langle \Delta \rangle$")
    ax_div.legend(loc="lower right")

    # Pre-compute pair separations (in degrees) on the time grid.
    th1_arr = np.array([r["th1"] for r in rows])  # (n, T)
    th2_arr = np.array([r["th2"] for r in rows])
    n_pairs = len(pair_idx)
    T = len(grid)
    pair_d = np.zeros((n_pairs, T))
    for k, (i, j) in enumerate(pair_idx):
        d_th1 = th1_arr[i] - th1_arr[j]
        d_th2 = th2_arr[i] - th2_arr[j]
        pair_d[k] = np.sqrt(d_th1 ** 2 + d_th2 ** 2)

    log_pair = np.where(pair_d > 0, pair_d, np.nan)
    mean_curve = np.exp(np.nanmean(np.log(log_pair), axis=0))

    def init():
        for ul, ll, ed, bd in zip(upper_lines, lower_lines,
                                   elbow_dots, bob_dots):
            ul.set_data([], []); ll.set_data([], [])
            ed.set_data([], []); bd.set_data([], [])
        for pl in pair_lines:
            pl.set_data([], [])
        mean_line.set_data([], [])
        time_txt.set_text("")
        return (upper_lines + lower_lines + elbow_dots + bob_dots
                + pair_lines + [mean_line, time_txt])

    def update(k):
        idx = frame_idx[k]
        # Pendulum geometry
        for i, r in enumerate(rows):
            piv, el, bob = pendulum_xy(r["th1"][idx], r["th2"][idx])
            upper_lines[i].set_data([piv[0], el[0]], [piv[1], el[1]])
            lower_lines[i].set_data([el[0], bob[0]], [el[1], bob[1]])
            elbow_dots[i].set_data([el[0]], [el[1]])
            bob_dots[i].set_data([bob[0]], [bob[1]])
        # Divergence panel — fill in growing traces up to current t.
        for k_idx, pl in enumerate(pair_lines):
            pl.set_data(grid[:idx + 1], pair_d[k_idx, :idx + 1])
        mean_line.set_data(grid[:idx + 1], mean_curve[:idx + 1])
        time_txt.set_text(f"t = {grid[idx]:5.2f} s")
        return (upper_lines + lower_lines + elbow_dots + bob_dots
                + pair_lines + [mean_line, time_txt])

    anim = animation.FuncAnimation(
        fig, update, frames=len(frame_idx),
        init_func=init, blit=True, interval=1000 / fps_out)
    writer = animation.FFMpegWriter(fps=fps_out, bitrate=2400)
    print(f"  rendering {len(frame_idx)} frames at {fps_out} fps "
          f"({len(frame_idx)/fps_out:.1f}s output)...")
    anim.save(out_path, writer=writer, dpi=120)
    plt.close(fig)
    mirror_to_journal(out_path)
    print(f"  wrote {out_path}")


# ─────────────────────────────────────────────
# (B) PHASE PORTRAIT TRACE RACE
# ─────────────────────────────────────────────

def render_phase(rows, out_path, fps_out, speed):
    n = len(rows)
    cs = colors_for(n)
    grid = rows[0]["t"]
    dt_grid = grid[1] - grid[0]
    step = max(1, int(round(1.0 / (fps_out * speed) / dt_grid)))
    frame_idx = np.arange(0, len(grid), step)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))
    fig.suptitle("Phase-portrait trace race — 6 twin-IC clips",
                 fontsize=13)

    th1_arr = np.array([r["th1"] for r in rows])
    om1_arr = np.array([r["om1"] for r in rows])
    th2_arr = np.array([r["th2"] for r in rows])
    om2_arr = np.array([r["om2"] for r in rows])

    for ax, label_x, label_y in (
        (ax1, r"$\theta_1$ (deg)", r"$\omega_1$ (deg/s)"),
        (ax2, r"$\theta_2$ (deg)", r"$\omega_2$ (deg/s)")):
        ax.set_xlabel(label_x); ax.set_ylabel(label_y)
        ax.axhline(0, color="gray", lw=0.5, ls="--")
        ax.axvline(0, color="gray", lw=0.5, ls="--")
        ax.grid(True, alpha=0.3)

    pad = 0.08
    def lim(arr):
        lo, hi = arr.min(), arr.max()
        r = hi - lo
        return lo - pad * r, hi + pad * r
    ax1.set_xlim(*lim(th1_arr)); ax1.set_ylim(*lim(om1_arr))
    ax2.set_xlim(*lim(th2_arr)); ax2.set_ylim(*lim(om2_arr))
    ax1.set_title(r"arm 1 ($\theta_1, \omega_1$)")
    ax2.set_title(r"arm 2 ($\theta_2, \omega_2$)")

    trails_1 = [ax1.plot([], [], color=c, lw=0.8, alpha=0.6)[0] for c in cs]
    heads_1  = [ax1.plot([], [], "o", color=c, markersize=6)[0]   for c in cs]
    trails_2 = [ax2.plot([], [], color=c, lw=0.8, alpha=0.6)[0] for c in cs]
    heads_2  = [ax2.plot([], [], "o", color=c, markersize=6)[0]   for c in cs]
    time_txt = fig.text(0.5, 0.94, "", ha="center", fontsize=12)

    def init():
        for ln in trails_1 + heads_1 + trails_2 + heads_2:
            ln.set_data([], [])
        time_txt.set_text("")
        return trails_1 + heads_1 + trails_2 + heads_2 + [time_txt]

    def update(k):
        idx = frame_idx[k]
        for i in range(n):
            trails_1[i].set_data(th1_arr[i, :idx+1], om1_arr[i, :idx+1])
            heads_1[i].set_data([th1_arr[i, idx]], [om1_arr[i, idx]])
            trails_2[i].set_data(th2_arr[i, :idx+1], om2_arr[i, :idx+1])
            heads_2[i].set_data([th2_arr[i, idx]], [om2_arr[i, idx]])
        time_txt.set_text(f"t = {grid[idx]:5.2f} s")
        return trails_1 + heads_1 + trails_2 + heads_2 + [time_txt]

    anim = animation.FuncAnimation(
        fig, update, frames=len(frame_idx),
        init_func=init, blit=True, interval=1000 / fps_out)
    writer = animation.FFMpegWriter(fps=fps_out, bitrate=2400)
    print(f"  rendering {len(frame_idx)} frames at {fps_out} fps "
          f"({len(frame_idx)/fps_out:.1f}s output)...")
    anim.save(out_path, writer=writer, dpi=120)
    plt.close(fig)
    mirror_to_journal(out_path)
    print(f"  wrote {out_path}")


# ─────────────────────────────────────────────
# (C) 3D PHASE RIBBON OVERLAY
# ─────────────────────────────────────────────

def render_3d(rows, out_path, fps_out, speed):
    n = len(rows)
    cs = colors_for(n)
    grid = rows[0]["t"]
    dt_grid = grid[1] - grid[0]
    step = max(1, int(round(1.0 / (fps_out * speed) / dt_grid)))
    frame_idx = np.arange(0, len(grid), step)

    th1_arr = np.array([r["th1"] for r in rows])
    th2_arr = np.array([r["th2"] for r in rows])
    om1_arr = np.array([r["om1"] for r in rows])

    fig = plt.figure(figsize=(11, 8))
    ax  = fig.add_subplot(111, projection="3d")
    fig.patch.set_facecolor("#0d0d0d")
    ax.set_facecolor("#0d0d0d")

    pad = 0.08
    def lim(a):
        lo, hi = a.min(), a.max(); r = hi - lo
        return lo - pad * r, hi + pad * r
    ax.set_xlim(*lim(th1_arr)); ax.set_ylim(*lim(th2_arr))
    ax.set_zlim(*lim(om1_arr))
    ax.set_xlabel(r"$\theta_1$ (°)", color="#aaa", labelpad=8)
    ax.set_ylabel(r"$\theta_2$ (°)", color="#aaa", labelpad=8)
    ax.set_zlabel(r"$\omega_1$ (°/s)", color="#aaa", labelpad=8)
    ax.tick_params(colors="#555", labelsize=7)
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False; pane.set_edgecolor("#222")
    ax.grid(True, color="#222", lw=0.4)
    ax.set_title(r"3D phase trajectories — twin-IC group",
                 color="#ccc", fontsize=12, pad=12)

    # Per-clip line + head dot.
    lines = [ax.plot([], [], [], color=c, lw=1.0, alpha=0.85)[0] for c in cs]
    heads = [ax.plot([], [], [], "o", color=c, markersize=5)[0]    for c in cs]
    time_txt = ax.text2D(0.02, 0.95, "", transform=ax.transAxes,
                          color="#ccc", fontsize=12)

    # Slow camera rotation across the animation.
    elev_start, elev_end = 22, 22
    azim_start, azim_end = 30, 30 + 60   # mild rotation, ~ 60° over the clip

    def init():
        for ln, hd in zip(lines, heads):
            ln.set_data_3d([], [], [])
            hd.set_data_3d([], [], [])
        time_txt.set_text("")
        return lines + heads + [time_txt]

    def update(k):
        idx = frame_idx[k]
        for i in range(n):
            lines[i].set_data_3d(
                th1_arr[i, :idx+1], th2_arr[i, :idx+1], om1_arr[i, :idx+1])
            heads[i].set_data_3d(
                [th1_arr[i, idx]], [th2_arr[i, idx]], [om1_arr[i, idx]])
        # Smooth camera path
        frac = k / max(1, len(frame_idx) - 1)
        ax.view_init(elev=elev_start + frac * (elev_end - elev_start),
                     azim=azim_start + frac * (azim_end - azim_start))
        time_txt.set_text(f"t = {grid[idx]:5.2f} s")
        return lines + heads + [time_txt]

    # blit must be False with 3D + view rotation.
    anim = animation.FuncAnimation(
        fig, update, frames=len(frame_idx),
        init_func=init, blit=False, interval=1000 / fps_out)
    writer = animation.FFMpegWriter(fps=fps_out, bitrate=2400)
    print(f"  rendering {len(frame_idx)} frames at {fps_out} fps "
          f"({len(frame_idx)/fps_out:.1f}s output)...")
    anim.save(out_path, writer=writer, dpi=120)
    plt.close(fig)
    mirror_to_journal(out_path)
    print(f"  wrote {out_path}")


# ─────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--group", choices=list(GROUPS),
                   help="predefined curated set")
    p.add_argument("--stems", help="comma-separated stems")
    p.add_argument("--type", choices=["ghost", "phase", "3d", "all"],
                   default="all")
    p.add_argument("--max-time", type=float, default=8.0,
                   help="cap the animation window in seconds (default 8)")
    p.add_argument("--fps", type=int, default=30,
                   help="output frame rate (default 30)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="playback speed multiplier (default 1.0 = real time)")
    return p.parse_args()


def resolve_stems(args):
    if args.stems:
        return [s.strip() for s in args.stems.split(",") if s.strip()]
    if args.group:
        return list(GROUPS[args.group])
    raise SystemExit("Need --group or --stems.")


def main():
    args = parse_args()
    stems = resolve_stems(args)
    print(f"group_animations.py — {len(stems)} clips, type={args.type}")

    raw = []
    for s in stems:
        r = load_traj(s)
        if r is None:
            print(f"  [skip] {s}: no usable verification.csv")
            continue
        raw.append(r)
    if len(raw) < 2:
        print("  fewer than 2 usable clips — aborting.")
        return

    rows = time_align(raw, max_time=args.max_time)
    print(f"  aligned: 0 → {rows[0]['t'][-1]:.2f}s, "
          f"dt = {(rows[0]['t'][1] - rows[0]['t'][0])*1000:.2f} ms")

    label = args.group or "custom"
    do = ([args.type] if args.type != "all"
          else ["ghost", "phase", "3d"])

    if "ghost" in do:
        print("(A) ghost pendulums")
        render_ghost(rows,
                     aggregate_path(f"group_{label}_ghost.mp4"),
                     args.fps, args.speed)
    if "phase" in do:
        print("(B) phase-portrait trace race")
        render_phase(rows,
                     aggregate_path(f"group_{label}_phase.mp4"),
                     args.fps, args.speed)
    if "3d" in do:
        print("(C) 3D phase ribbon overlay")
        render_3d(rows,
                  aggregate_path(f"group_{label}_3d.mp4"),
                  args.fps, args.speed)


if __name__ == "__main__":
    main()
