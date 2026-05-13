"""
poincare_animation.py
----------------------
Interactive Poincaré-section visualizer for double-pendulum data.

LEFT panel (3D):
    Trajectory in (θ₁, θ₂, ω₁) with a fading 200-frame ghost trail.
    Translucent plane at θ₂ = −θ₁ (the section condition θ₁+θ₂=0).
    When the trajectory pierces the plane upward (d(θ₁+θ₂)/dt > 0),
    a bright marker flashes at the crossing for ~0.5 s, then fades
    to a persistent small dot.

RIGHT panel (2D Poincaré):
    (θ₁, ω₁) at every upward crossing event. New points flash, then
    settle. Color = time index of crossing (viridis).

Controls (matplotlib widgets + keyboard):
    Play / Pause / Reset buttons
    Speed slider (0.1× to 1.0× real time)
    "Show all" toggle: jump to end, dump every crossing
    Frame-step button (advance one source frame)
    Left / Right arrow keys: cycle clips
    Space: play/pause
    R: reset

Reads verification.csv (already has Savitzky-Golay-smoothed ω₁, ω₂);
falls back to central differences on tracking.csv if needed.

Usage:
    python scripts/analysis/poincare_animation.py
        # interactive picker if --stem omitted (uses first available)

    python scripts/analysis/poincare_animation.py --stem th1_p180_th2_m179
        # specific clip; arrow keys cycle
"""

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider, CheckButtons
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from matplotlib import cm
import matplotlib.colors as mcolors

ANIM_INTERVAL_MS = 16       # animation tick (~62 fps display target)
SOURCE_FPS       = 59.94    # data acquisition rate
TRAIL_FRAMES     = 200      # ghost trail length
FLASH_DURATION_S = 0.5      # how long the bright flash lingers

# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def list_clips():
    if not os.path.isdir(MEAS_DIR):
        return []
    out = []
    for d in sorted(os.listdir(MEAS_DIR)):
        if os.path.exists(os.path.join(MEAS_DIR, d, "verification.csv")):
            out.append(d)
    return out

def load_clip(stem):
    """Return (t, th1, th2, w1, w2) for the free_swing phase. Skips NaN rows."""
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv):
        # Fallback: tracking.csv + finite diff
        csv = os.path.join(MEAS_DIR, stem, "tracking.csv")
        if not os.path.exists(csv):
            raise FileNotFoundError(f"No data for {stem}")
        df = pd.read_csv(csv)
        free = df[df["phase"] == "free_swing"].copy()
        free = free.dropna(subset=["theta1_deg", "theta2_deg"]).reset_index(drop=True)
        t   = free["time_s"].to_numpy()
        th1 = free["theta1_deg"].to_numpy()
        th2 = free["theta2_deg"].to_numpy()
        # central differences in deg/s
        w1 = np.gradient(th1, t)
        w2 = np.gradient(th2, t)
        return t, th1, th2, w1, w2

    df = pd.read_csv(csv)
    free = df[df["phase"] == "free_swing"].copy()
    cols = ["theta1_deg", "theta2_deg", "omega1_deg_s", "omega2_deg_s"]
    free = free.dropna(subset=cols).reset_index(drop=True)
    return (free["time_s"].to_numpy(),
            free["theta1_deg"].to_numpy(),
            free["theta2_deg"].to_numpy(),
            free["omega1_deg_s"].to_numpy(),
            free["omega2_deg_s"].to_numpy())

def find_crossings_upward(t, th1, th2, w1, w2):
    """Find all upward crossings of θ₁+θ₂=0 (i.e. d/dt(θ₁+θ₂) > 0).
    Returns list of dicts: {idx, frac, t_cross, th1, th2, w1, w2}."""
    c = th1 + th2
    dc = w1 + w2  # velocity of the section coordinate
    out = []
    for i in range(len(c) - 1):
        if c[i] == 0.0 and dc[i] > 0:
            out.append(dict(idx=i, frac=0.0, t_cross=t[i],
                            th1=th1[i], th2=th2[i], w1=w1[i], w2=w2[i]))
            continue
        # zero between [i, i+1]?
        if c[i] * c[i + 1] < 0:
            frac = -c[i] / (c[i + 1] - c[i])
            dc_mid = (1 - frac) * dc[i] + frac * dc[i + 1]
            if dc_mid > 0:  # upward only
                out.append(dict(
                    idx=i, frac=frac,
                    t_cross  = (1 - frac) * t[i]   + frac * t[i + 1],
                    th1      = (1 - frac) * th1[i] + frac * th1[i + 1],
                    th2      = (1 - frac) * th2[i] + frac * th2[i + 1],
                    w1       = (1 - frac) * w1[i]  + frac * w1[i + 1],
                    w2       = (1 - frac) * w2[i]  + frac * w2[i + 1],
                ))
    return out

# ─────────────────────────────────────────────
# ANIMATOR
# ─────────────────────────────────────────────

class PoincareAnimator:
    def __init__(self, fig, ax3d, ax2d, ax_status, stems, initial_stem):
        self.fig = fig
        self.ax3d = ax3d
        self.ax2d = ax2d
        self.ax_status = ax_status
        self.stems = stems
        self.stem = initial_stem
        self.speed = 0.25
        self.playing = True
        self.show_all = False
        self.frame_f = 0.0       # fractional frame index
        self.last_seen_idx = -1  # highest crossing index already processed
        self._load_current()
        self._build_artists()

    def _load_current(self):
        self.t, self.th1, self.th2, self.w1, self.w2 = load_clip(self.stem)
        self.n = len(self.t)
        if self.n < 2:
            raise ValueError(f"{self.stem}: not enough data")
        self.crossings = find_crossings_upward(
            self.t, self.th1, self.th2, self.w1, self.w2)
        self.frame_f = 0.0
        self.last_seen_idx = -1
        # Visible crossings (those whose source-frame index <= current frame)
        self.visible_crossings = []   # list of dicts with extra 'first_seen_t'
        # Per-frame caches to skip redundant artist updates when nothing changed
        self._last_visible_count = -1   # tracks scatter point counts
        self._last_flash_count   = -1   # tracks flash marker counts

    def _build_artists(self):
        ax = self.ax3d
        ax.clear()
        # Limits
        th_lo, th_hi = float(min(self.th1.min(), self.th2.min())), \
                       float(max(self.th1.max(), self.th2.max()))
        pad = 0.08 * max(1.0, th_hi - th_lo)
        ax.set_xlim(th_lo - pad, th_hi + pad)
        ax.set_ylim(th_lo - pad, th_hi + pad)
        w1_lo, w1_hi = float(self.w1.min()), float(self.w1.max())
        wpad = 0.08 * max(1.0, w1_hi - w1_lo)
        ax.set_zlim(w1_lo - wpad, w1_hi + wpad)
        ax.set_xlabel("θ₁ (deg)")
        ax.set_ylabel("θ₂ (deg)")
        ax.set_zlabel("ω₁ (deg/s)")
        ax.set_title(f"Phase space (3D projection) — {self.stem}", fontsize=10)

        # Section plane: θ₂ = −θ₁, all ω₁
        # Corners parameterized by (θ₁, ω₁) at the visible bbox.
        x_lo, x_hi = ax.get_xlim()
        z_lo, z_hi = ax.get_zlim()
        plane_pts = np.array([
            [x_lo, -x_lo, z_lo], [x_hi, -x_hi, z_lo],
            [x_hi, -x_hi, z_hi], [x_lo, -x_lo, z_hi],
        ])
        plane = Poly3DCollection([plane_pts], alpha=0.13,
                                  facecolor="#4477bb", edgecolor="#224499",
                                  linewidth=0.8)
        ax.add_collection3d(plane)
        # Mark the plane with a label corner
        ax.text(x_hi, -x_hi, z_hi,
                "  Poincaré section\n  θ₁+θ₂=0",
                fontsize=8, color="#224499")

        # Trail (will update each frame). Empty 3D line.
        self.trail_line, = ax.plot([], [], [], lw=1.4, color="#cc4422", alpha=0.85)
        # Current point marker
        self.current_pt, = ax.plot([], [], [], "o", color="#cc4422",
                                     markersize=6, zorder=10)
        # Persistent crossing dots on the plane (3D)
        self.cross3d_persistent = ax.scatter(
            [], [], [], c=[], cmap="viridis", s=18, depthshade=False, zorder=8)
        # Flash marker (single bright dot, possibly multiple — use scatter)
        self.cross3d_flash, = ax.plot([], [], [], "*", color="#ffe845",
                                        markersize=22, markeredgecolor="#aa7700",
                                        markeredgewidth=1.0, alpha=1.0)

        # ── 2D panel ──
        self.ax2d.clear()
        self.ax2d.set_xlabel("θ₁ at crossing (deg)")
        self.ax2d.set_ylabel("ω₁ at crossing (deg/s)")
        self.ax2d.set_title(f"Poincaré section (θ₁+θ₂=0, upward) — {self.stem}",
                              fontsize=10)
        self.ax2d.grid(alpha=0.3)
        # Pre-size axes if we know the range from full crossings list
        if self.crossings:
            x = np.array([c["th1"] for c in self.crossings])
            y = np.array([c["w1"]  for c in self.crossings])
            xpad = 0.1 * max(1.0, x.max() - x.min())
            ypad = 0.1 * max(1.0, y.max() - y.min())
            self.ax2d.set_xlim(x.min() - xpad, x.max() + xpad)
            self.ax2d.set_ylim(y.min() - ypad, y.max() + ypad)
        else:
            self.ax2d.set_xlim(-180, 180)
            self.ax2d.set_ylim(-1500, 1500)
        self.cross2d_persistent = self.ax2d.scatter(
            [], [], c=[], cmap="viridis", s=20,
            vmin=0, vmax=max(1, len(self.crossings) - 1))
        self.cross2d_flash, = self.ax2d.plot([], [], "*", color="#ffe845",
                                                markersize=22,
                                                markeredgecolor="#aa7700",
                                                markeredgewidth=1.0)
        self.count_text = self.ax2d.text(
            0.97, 0.03, "", transform=self.ax2d.transAxes,
            ha="right", va="bottom", fontsize=11,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

        # Status text on the figure
        self.status_text = self.ax_status.text(
            0.5, 0.5, "", transform=self.ax_status.transAxes,
            ha="center", va="center", fontsize=10, family="monospace")
        self.ax_status.axis("off")

        # 4D context note
        self.fig.text(0.01, 0.01,
                       "Phase space is 4D: (θ₁, θ₂, ω₁, ω₂). "
                       "Left panel shows a 3D projection. "
                       "Section reduces 4D flow → 2D map.",
                       fontsize=8, color="#444",
                       style="italic")

    # ── State transitions ──

    def reload_clip(self, stem):
        self.stem = stem
        self._load_current()
        self._build_artists()
        self.fig.canvas.draw_idle()

    def cycle_clip(self, direction):
        if not self.stems:
            return
        i = self.stems.index(self.stem) if self.stem in self.stems else 0
        i = (i + direction) % len(self.stems)
        self.reload_clip(self.stems[i])

    def reset(self, _evt=None):
        self.frame_f = 0.0
        self.last_seen_idx = -1
        self.visible_crossings = []
        self.show_all = False
        self.playing = True
        self._build_artists()
        self.fig.canvas.draw_idle()

    def toggle_play(self, _evt=None):
        self.playing = not self.playing

    def step_one_frame(self, _evt=None):
        was = self.playing
        self.playing = False
        self._advance_to(int(self.frame_f) + 1)
        self.playing = was

    def set_speed(self, val):
        self.speed = float(val)

    def toggle_show_all(self, _label=None):
        self.show_all = not self.show_all
        if self.show_all:
            self._advance_to(self.n - 1)
            self.playing = False

    # ── Animation per-tick logic ──

    def _advance_to(self, target_frame):
        target_frame = max(0, min(self.n - 1, int(target_frame)))
        # Process any newly-crossed events
        for c in self.crossings:
            if c["idx"] <= target_frame and c["idx"] > self.last_seen_idx:
                # New visible crossing
                self.visible_crossings.append(
                    {**c, "first_seen_t": self.t[target_frame]})
                self.last_seen_idx = c["idx"]
        self.frame_f = float(target_frame)

    def update(self, _frame_count):
        if self.playing and not self.show_all:
            advance = self.speed * SOURCE_FPS * (ANIM_INTERVAL_MS / 1000.0)
            self.frame_f = min(self.n - 1, self.frame_f + advance)
            self._advance_to(self.frame_f)

        cur = int(self.frame_f)

        # ── Trail (last TRAIL_FRAMES, fading) ──
        lo = max(0, cur - TRAIL_FRAMES)
        self.trail_line.set_data(self.th1[lo:cur + 1], self.th2[lo:cur + 1])
        self.trail_line.set_3d_properties(self.w1[lo:cur + 1])

        # Current point
        self.current_pt.set_data([self.th1[cur]], [self.th2[cur]])
        self.current_pt.set_3d_properties([self.w1[cur]])

        # ── Crossings ──
        now_t = self.t[cur]
        n_visible = len(self.visible_crossings)
        # Only update persistent scatters when their point counts changed.
        # 3D scatter reprojection is the dominant per-frame cost; skipping it
        # when nothing was added gives a large framerate win.
        if n_visible != self._last_visible_count:
            if n_visible:
                xs3 = np.array([c["th1"] for c in self.visible_crossings])
                ys3 = np.array([c["th2"] for c in self.visible_crossings])
                zs3 = np.array([c["w1"]  for c in self.visible_crossings])
                cs  = np.array([c["t_cross"] for c in self.visible_crossings])
                self.cross3d_persistent._offsets3d = (xs3, ys3, zs3)
                norm = mcolors.Normalize(vmin=self.t[0], vmax=self.t[-1])
                self.cross3d_persistent.set_color(cm.viridis(norm(cs)))
                xs2 = xs3  # same θ₁
                ys2 = np.array([c["w1"] for c in self.visible_crossings])
                self.cross2d_persistent.set_offsets(np.column_stack([xs2, ys2]))
                self.cross2d_persistent.set_array(cs)
                self.cross2d_persistent.set_clim(self.t[0], self.t[-1])
            else:
                self.cross3d_persistent._offsets3d = ([], [], [])
                self.cross2d_persistent.set_offsets(np.empty((0, 2)))
            self._last_visible_count = n_visible

        # Flash markers: only update when count changes (most frames have none)
        flash_x3, flash_y3, flash_z3 = [], [], []
        flash_x2, flash_y2 = [], []
        for c in self.visible_crossings:
            age = now_t - c["first_seen_t"]
            if 0 <= age < FLASH_DURATION_S:
                flash_x3.append(c["th1"]); flash_y3.append(c["th2"])
                flash_z3.append(c["w1"])
                flash_x2.append(c["th1"]); flash_y2.append(c["w1"])
        n_flash = len(flash_x3)
        if n_flash != self._last_flash_count or n_flash > 0:
            # Always update when there ARE flashes (their fade timing is per-frame);
            # skip only the steady-state "no flash" → "no flash" no-op transition.
            self.cross3d_flash.set_data(flash_x3, flash_y3)
            self.cross3d_flash.set_3d_properties(flash_z3)
            self.cross2d_flash.set_data(flash_x2, flash_y2)
            self._last_flash_count = n_flash

        n_cross_now = len(self.visible_crossings)
        n_cross_total = len(self.crossings)
        self.count_text.set_text(
            f"N crossings: {n_cross_now} / {n_cross_total}")

        self.status_text.set_text(
            f"clip: {self.stem}    "
            f"frame: {cur:5d} / {self.n - 1}    "
            f"t = {now_t:6.2f} s    "
            f"speed: {self.speed:.2f}×    "
            f"{'PLAYING' if self.playing else 'PAUSED'}"
            f"{'  [SHOW-ALL]' if self.show_all else ''}")

        return (self.trail_line, self.current_pt,
                self.cross3d_persistent, self.cross3d_flash,
                self.cross2d_persistent, self.cross2d_flash,
                self.count_text, self.status_text)

# ─────────────────────────────────────────────
# WIRING
# ─────────────────────────────────────────────

def build_figure(stems, initial_stem):
    fig = plt.figure(figsize=(15, 7.5))
    fig.suptitle("Poincaré section visualizer  (θ₁+θ₂=0, upward crossings)",
                  fontsize=12)
    # Main panels
    ax3d = fig.add_subplot(1, 2, 1, projection="3d")
    ax2d = fig.add_subplot(1, 2, 2)
    # Status bar
    ax_status = fig.add_axes([0.05, 0.92, 0.6, 0.04])

    plt.subplots_adjust(left=0.05, right=0.97, bottom=0.18, top=0.88,
                          wspace=0.18)

    anim_obj = PoincareAnimator(fig, ax3d, ax2d, ax_status, stems, initial_stem)

    # ── Widgets ──
    btn_h, btn_w = 0.045, 0.075
    y0 = 0.06

    ax_play  = fig.add_axes([0.05, y0, btn_w, btn_h])
    ax_reset = fig.add_axes([0.13, y0, btn_w, btn_h])
    ax_step  = fig.add_axes([0.21, y0, btn_w, btn_h])
    ax_prev  = fig.add_axes([0.29, y0, btn_w, btn_h])
    ax_next  = fig.add_axes([0.37, y0, btn_w, btn_h])
    ax_speed = fig.add_axes([0.50, y0 + 0.005, 0.30, btn_h - 0.01])
    ax_all   = fig.add_axes([0.83, y0, 0.13, btn_h])

    btn_play  = Button(ax_play, "▶ / ⏸")
    btn_reset = Button(ax_reset, "Reset")
    btn_step  = Button(ax_step,  "Step +1")
    btn_prev  = Button(ax_prev,  "← clip")
    btn_next  = Button(ax_next,  "clip →")
    sld_speed = Slider(ax_speed, "speed", 0.05, 1.0,
                         valinit=anim_obj.speed, valstep=0.05)
    chk_all   = CheckButtons(ax_all, ["Show all"], [False])

    btn_play .on_clicked(anim_obj.toggle_play)
    btn_reset.on_clicked(anim_obj.reset)
    btn_step .on_clicked(anim_obj.step_one_frame)
    btn_prev .on_clicked(lambda e: anim_obj.cycle_clip(-1))
    btn_next .on_clicked(lambda e: anim_obj.cycle_clip(+1))
    sld_speed.on_changed(anim_obj.set_speed)
    chk_all  .on_clicked(lambda lbl: anim_obj.toggle_show_all(lbl))

    # Keyboard
    def on_key(evt):
        if evt.key == "right":
            anim_obj.cycle_clip(+1)
        elif evt.key == "left":
            anim_obj.cycle_clip(-1)
        elif evt.key == " " or evt.key == "space":
            anim_obj.toggle_play()
        elif evt.key in ("r", "R"):
            anim_obj.reset()
        elif evt.key in (".", ">"):
            anim_obj.step_one_frame()
    fig.canvas.mpl_connect("key_press_event", on_key)

    # Hold widget refs so they aren't GC'd
    fig._widgets = (btn_play, btn_reset, btn_step, btn_prev, btn_next,
                     sld_speed, chk_all)

    anim = FuncAnimation(fig, anim_obj.update, interval=ANIM_INTERVAL_MS,
                           blit=False, cache_frame_data=False)
    fig._anim = anim
    return fig, anim_obj

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", default=None, help="Clip stem (default: first).")
    return p.parse_args()

def main():
    args = parse_args()
    stems = list_clips()
    if not stems:
        print("No clips with verification.csv found in measurements/")
        sys.exit(1)
    initial = args.stem if args.stem in stems else stems[0]
    if args.stem and args.stem not in stems:
        print(f"Warning: --stem {args.stem!r} not found, using {initial!r}")
    print(f"Loaded {len(stems)} clips. Showing: {initial}")
    print("Controls: SPACE=play/pause  R=reset  ←/→=cycle clips  .=step")
    fig, _ = build_figure(stems, initial)
    plt.show()

if __name__ == "__main__":
    main()

from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
