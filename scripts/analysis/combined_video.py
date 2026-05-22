"""
analysis_combined_video.py
---------------------------
Renders a side-by-side MP4 combining:
  LEFT  (960×720): original tracked video with arm overlays
  RIGHT (960×720): 3 phase-space panels updating in real time
                   - Configuration space  θ₁ vs θ₂
                   - Phase portrait arm 1 θ₁ vs ω₁
                   - Phase portrait arm 2 θ₂ vs ω₂

Parameter strip along the bottom of the right panel shows:
  θ₁, θ₂, ω₁, ω₂, t, phase

Output: 1920×720 MP4 at source framerate.

Usage:
  # Mode 1 — measurement folder (preferred for pipeline use):
  python scripts/analysis/combined_video.py --stem th1_p044_th2_m001

  # Mode 2 — explicit CSV + video:
  python scripts/analysis/combined_video.py measurements/th1_p044_th2_m001/tracking.csv data/videos/th1_p044_th2_m001.mov

  # Mode 3 — defaults to long_recording:
  python scripts/analysis/combined_video.py
"""

import sys

# Force UTF-8 stdout so unicode glyphs (θ, ω) don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
import os
import csv
import json
import argparse
import numpy as np
import cv2
import matplotlib

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, clip_dir  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS
from figures_paths import figure_path  # noqa: E402
matplotlib.use('Agg')          # non-interactive backend — much faster offscreen
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.signal import savgol_filter

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_CSV   = os.path.join(MEAS_DIR, "th1_p180_th2_m179", "tracking.csv")
DEFAULT_VIDEO = os.path.join(REPO_ROOT, "data", "videos", "long_recording.mov")

def parse_args():
    p = argparse.ArgumentParser(
        description="Render side-by-side video + phase panels MP4.")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to tracking CSV (positional, optional).")
    p.add_argument("video", nargs="?", default=None,
                   help="Path to source video (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description, e.g. th1_p044_th2_m001. "
                        "Resolves CSV, video (via experiments.json), and "
                        "output dir from measurements/.")
    return p.parse_args()

def video_for_stem(stem):
    """
    Look up the source .mov for a given config_description by scanning
    experiments.json. Returns an absolute path, or exits with an error
    if no entry matches the stem.
    """
    if not os.path.exists(EXPERIMENTS_FILE):
        from rich.console import Console as _Console
        _Console().print(f"[red]ERROR:[/] registry missing: [dim]{EXPERIMENTS_FILE}[/]")
        sys.exit(1)
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        reg = json.load(f)
    for entry in reg.values():
        if entry.get("config_description") == stem:
            video_file = entry.get("video_file")
            if not video_file:
                continue
            return os.path.join(VIDEOS_DIR, video_file)
    from rich.console import Console as _Console
    _Console().print(f"[red]ERROR:[/] no registry entry has config_description '{stem}'.")
    _Console().print(f"  [dim]Add an entry to {EXPERIMENTS_FILE} or supply video path positionally.[/]")
    sys.exit(1)

def resolve_paths(args):
    """
    Returns (csv_path, video_path, output_mp4, output_dir).
    --stem mode is non-interactive and writes combined.mp4 directly into
    the measurement folder.
    """
    if args.stem:
        meas_dir = clip_dir(args.stem)
        csv_path = os.path.join(meas_dir, "tracking.csv")
        if not os.path.exists(csv_path):
            from rich.console import Console as _Console
            _Console().print(f"[red]ERROR:[/] tracking.csv not found for stem '{args.stem}'")
            _Console().print(f"  [dim]Expected: {csv_path}[/]")
            sys.exit(1)
        video_path = video_for_stem(args.stem)
        return (csv_path, video_path,
                figure_path("combined", args.stem, ext="mp4"), meas_dir)

    csv_path = args.csv if args.csv else DEFAULT_CSV
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(REPO_ROOT, csv_path)

    video_path = args.video if args.video else DEFAULT_VIDEO
    if not os.path.isabs(video_path):
        video_path = os.path.join(REPO_ROOT, video_path)

    # When the CSV lives inside a measurements folder, derive the stem
    # from the folder name and write the output to the canonical figures
    # directory. Otherwise fall back to the legacy data/figures naming.
    csv_dir = os.path.dirname(csv_path)
    if os.path.basename(os.path.dirname(csv_dir)) == "measurements":
        derived = os.path.basename(csv_dir)
        return (csv_path, video_path,
                figure_path("combined", derived, ext="mp4"), csv_dir)
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    if stem.endswith("_tracking"):
        stem = stem[:-len("_tracking")]
    return (csv_path, video_path,
            os.path.join(LEGACY_OUT, f"{stem}_combined.mp4"),
            LEGACY_OUT)

PANEL_W   = 960     # width of each half panel
PANEL_H   = 720     # height of both panels
FPS_OUT   = 59.94   # output framerate

SG_WINDOW = 11
SG_POLY   = 3

# Pivot pixel coordinates in original 1280×720 video.
# Brief 10b: imported from thresholds.py (sole source of truth).
_COMBINED_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(
    os.path.join(_COMBINED_DIR, os.pardir, "utils")))
from thresholds import (  # noqa: E402
    PIVOT as PIVOT_ORIG,
    ARM_LENGTH_PX,
    get_pivot_arm,
)
from driven_helpers import _STEM_RE  # noqa: E402

# ── Canonical color scheme ──────────────────────────────────────────────
# Matches physical markers and is consistent across all analysis scripts.
# matplotlib hex        OpenCV BGR
COLOR_CONFIG  = '#2196f3'          # blue  — configuration space (θ₁ vs θ₂)
COLOR_ARM1    = '#4caf50'          # green — arm 1 / green physical marker
COLOR_ARM2    = '#ef5350'          # red   — arm 2 / red physical marker

# OpenCV BGR equivalents (R,G,B -> B,G,R)
BGR_ARM1   = (80,  175,  76)       # green
BGR_ARM2   = (80,   83, 239)       # red
BGR_CONFIG = (243, 150,  33)       # blue

# ─────────────────────────────────────────────
# LOAD CSV
# ─────────────────────────────────────────────

def load_csv(path):
    """Load full tracking CSV — all frames, all phases."""
    rows = list(csv.DictReader(open(path)))

    frames  = np.array([int(r['frame'])   for r in rows])
    times   = np.array([float(r['time_s']) for r in rows])
    phases  = [r['phase']                  for r in rows]
    dropouts = np.array([int(r['dropout']) for r in rows])

    th1 = np.array([float(r['theta1_deg']) if r['theta1_deg'] else np.nan for r in rows])
    th2 = np.array([float(r['theta2_deg']) if r['theta2_deg'] else np.nan for r in rows])

    # Compute velocities on clean data only, then interpolate NaNs
    dt = np.nanmean(np.diff(times))

    # Fill NaN with linear interpolation before SG filter
    def fill_nan(arr):
        nans = np.isnan(arr)
        if nans.any():
            idx = np.arange(len(arr))
            arr[nans] = np.interp(idx[nans], idx[~nans], arr[~nans])
        return arr

    th1c = fill_nan(th1.copy())
    th2c = fill_nan(th2.copy())

    # Unwrap before SG-differentiating: SG'ing a wrapped series produces
    # ~360°/frame phantom spikes at every ±180° crossing.
    th1u = np.degrees(np.unwrap(np.radians(th1c)))
    th2u = np.degrees(np.unwrap(np.radians(th2c)))

    om1 = savgol_filter(th1u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)
    om2 = savgol_filter(th2u, SG_WINDOW, SG_POLY, deriv=1, delta=dt)

    # Restore NaNs for dropout frames
    om1[dropouts == 1] = np.nan
    om2[dropouts == 1] = np.nan

    return frames, times, phases, th1, th2, om1, om2, dropouts

# ─────────────────────────────────────────────
# BUILD MATPLOTLIB FIGURE (offscreen)
# ─────────────────────────────────────────────

def setup_figure(th1, th2, om1, om2):
    """
    Create the matplotlib figure and all artists.
    Returns (fig, artists_dict) where artists_dict holds the line/scatter
    objects that get updated each frame.
    """
    # Figure at exactly PANEL_W x PANEL_H pixels
    dpi = 100
    fig = plt.figure(figsize=(PANEL_W / dpi, PANEL_H / dpi), dpi=dpi)
    fig.patch.set_facecolor('#0e0e0e')   # dark background

    gs = gridspec.GridSpec(
        3, 1, figure=fig,
        hspace=0.45,
        left=0.12, right=0.97,
        top=0.96, bottom=0.08
    )

    ax1 = fig.add_subplot(gs[0])   # config space
    ax2 = fig.add_subplot(gs[1])   # phase arm 1
    ax3 = fig.add_subplot(gs[2])   # phase arm 2

    axes = [ax1, ax2, ax3]

    # Compute axis limits from full data (ignoring NaN)
    def lim(arr, margin=0.12):
        a = np.nanmin(arr); b = np.nanmax(arr)
        pad = (b - a) * margin
        return a - pad, b + pad

    xlims = [lim(th1), lim(th1), lim(th2)]
    ylims = [lim(th2), lim(om1), lim(om2)]

    titles = [
        r"$\theta_1$ vs $\theta_2$  (configuration space)",
        r"$\theta_1$ vs $\omega_1$  (phase portrait — arm 1)",
        r"$\theta_2$ vs $\omega_2$  (phase portrait — arm 2)",
    ]
    xlabels = [r"$\theta_1$ (°)", r"$\theta_1$ (°)", r"$\theta_2$ (°)"]
    ylabels = [r"$\theta_2$ (°)", r"$\omega_1$ (°/s)", r"$\omega_2$ (°/s)"]
    colors  = [COLOR_CONFIG, COLOR_ARM1, COLOR_ARM2]

    trace_lines = []
    head_dots   = []

    for ax, xl, yl, title, xlabel, ylabel, color, xlim, ylim in zip(
            axes, xlims, ylims, titles, xlabels, ylabels, colors, xlims, ylims):

        ax.set_facecolor('#1a1a1a')
        ax.set_xlim(xlim); ax.set_ylim(ylim)
        ax.set_title(title, color='#cccccc', fontsize=8, pad=3)
        ax.set_xlabel(xlabel, color='#999999', fontsize=7)
        ax.set_ylabel(ylabel, color='#999999', fontsize=7)
        ax.tick_params(colors='#666666', labelsize=6)
        ax.axhline(0, color='#333333', lw=0.7, zorder=0)
        ax.axvline(0, color='#333333', lw=0.7, zorder=0)
        for spine in ax.spines.values():
            spine.set_edgecolor('#333333')
        ax.grid(True, color='#2a2a2a', lw=0.5)

        # Ghost: full future trajectory very faint
        # (gives visual sense of the attractor shape from the start)
        ax.plot([], [], color=color, lw=0.3, alpha=0.15, zorder=1)

        # Permanent trace
        trace, = ax.plot([], [], color=color, lw=0.8, alpha=0.85, zorder=2)
        trace_lines.append(trace)

        # Current position dot
        head, = ax.plot([], [], 'o', color=color, ms=5, zorder=3,
                        markeredgecolor='white', markeredgewidth=0.5)
        head_dots.append(head)

    # Time / parameter annotation at top
    time_txt = fig.text(0.5, 0.995, '', ha='center', va='top',
                        color='#aaaaaa', fontsize=8,
                        fontfamily='monospace')

    return fig, trace_lines, head_dots, time_txt

def render_figure(fig):
    """Render matplotlib figure to a BGR numpy array (PANEL_H × PANEL_W × 3)."""
    fig.canvas.draw()
    buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    buf = buf.reshape(PANEL_H, PANEL_W, 4)
    return cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)

# ─────────────────────────────────────────────
# LEFT PANEL: resize + overlay
# ─────────────────────────────────────────────

def make_left_panel(frame, phase, t, th1, th2, om1, om2,
                    x_green, y_green, x_red, y_red,
                    pivot_orig=None, arm_length_px=None,
                    stem=None):
    """
    Crop the source frame to a square that contains every constraint
    circle at every frame (6·arm × 6·arm centred on the pivot, since
    the red constraint circle reaches 3·arm from pivot at maximum
    extension), scale to PANEL_H × PANEL_H, and composite a parameter
    strip on the left so the output stays at PANEL_W × PANEL_H.

    When the bbox extends past the original frame edges (typical: the
    camera frame isn't tall enough to contain 3·arm above and below the
    pivot), the source frame is padded with BORDER_REPLICATE so the
    out-of-camera region continues the background style instead of
    showing a black void. The visible circles always sit on what looks
    like continuous curtain/wall, not on a hard cutoff.

    No dimming. cv2 auto-clips drawing at panel edges; since the bbox
    is large enough to contain every circle every frame, that clipping
    never actually fires for the three constraint circles.
    """
    if pivot_orig is None:
        pivot_orig = PIVOT_ORIG
    if arm_length_px is None:
        arm_length_px = ARM_LENGTH_PX

    # ── Visualization bbox (6·arm × 6·arm) ────────────────────────────
    # Worst-case red constraint circle reaches 3·arm from pivot (red
    # marker at 2·arm + its own radius arm). Size the bbox so every
    # circle fits regardless of the pendulum's configuration.
    px, py    = pivot_orig
    half_side = 3 * arm_length_px
    side      = 2 * half_side
    fh, fw    = frame.shape[:2]

    # Pad the source frame on each side by however much the bbox
    # overhangs. BORDER_REPLICATE extends the boundary pixels outward,
    # so curtain/wall background continues naturally into the padding.
    pad_top    = max(0, half_side - py)
    pad_bot    = max(0, py + half_side - fh)
    pad_left   = max(0, half_side - px)
    pad_right  = max(0, px + half_side - fw)
    if pad_top or pad_bot or pad_left or pad_right:
        padded = cv2.copyMakeBorder(
            frame, pad_top, pad_bot, pad_left, pad_right,
            cv2.BORDER_REPLICATE)
    else:
        padded = frame

    # Bbox in the padded-frame coords. Pivot in padded coords is
    # shifted by (pad_left, pad_top).
    pp_x = px + pad_left
    pp_y = py + pad_top
    bbox = padded[pp_y - half_side:pp_y + half_side,
                  pp_x - half_side:pp_x + half_side, :]

    # Scale the bbox to the right square of the panel (PANEL_H × PANEL_H).
    vid_size = PANEL_H
    video    = cv2.resize(bbox, (vid_size, vid_size))
    s        = vid_size / side                # original px → display px

    # ── Circular porthole crop ─────────────────────────────────────────
    # Show ONLY the inscribed disc of the bbox (radius = vid_size/2,
    # which corresponds to 3·arm in original coords). The four corner
    # triangles outside the disc are filled with a single background
    # colour sampled from the source frame so the panel looks like a
    # round porthole onto the action, not a rectangular crop.
    bg_color = np.median(frame.reshape(-1, 3), axis=0).astype(frame.dtype)
    yy, xx   = np.ogrid[:vid_size, :vid_size]
    cr       = vid_size // 2
    porthole = (xx - cr)**2 + (yy - cr)**2 <= cr * cr
    video    = np.where(porthole[..., None], video, bg_color)

    # Output panel: param strip on the left + vid_size square on the right.
    col_w = PANEL_W - vid_size                 # 240 for 960×720
    panel = np.zeros((PANEL_H, PANEL_W, 3), dtype=frame.dtype)
    panel[:, col_w:, :] = video

    def disp(x, y):
        """Map original-frame coords to display coords inside the panel."""
        return (int((x - (px - half_side)) * s) + col_w,
                int((y - (py - half_side)) * s))

    pivot     = disp(px, py)
    arm_disp  = int(arm_length_px * s)         # constraint-circle radius

    # ── Three constraint circles, always drawn ────────────────────────
    # All at radius = arm_length_px so the geometric structure of the
    # double pendulum is visible at every frame:
    #   yellow: locus the green marker MUST sit on  (arm 1 length)
    #   green:  locus the red marker MUST sit on    (arm 2 length)
    #   red:    visual symmetry around the bottom marker
    # cv2.circle auto-clips at the panel edges when a circle extends
    # outside; nothing in the visible region is dimmed.
    CIRCLE_THICK = 1
    cv2.circle(panel, pivot, arm_disp, (0, 215, 255), CIRCLE_THICK,
               lineType=cv2.LINE_AA)

    # Yellow pivot dot
    cv2.circle(panel, pivot, 7, (0, 215, 255), -1, lineType=cv2.LINE_AA)

    # Arms and markers
    gp = None
    if not np.isnan(x_green):
        gp = disp(x_green, y_green)
        cv2.circle(panel, gp, arm_disp, (0, 200, 0), CIRCLE_THICK,
                   lineType=cv2.LINE_AA)
        cv2.line(panel, pivot, gp, (0, 200, 0), 2, lineType=cv2.LINE_AA)
        cv2.circle(panel, gp, 7, (0, 255, 0), -1, lineType=cv2.LINE_AA)

    if not np.isnan(x_red):
        rp = disp(x_red, y_red)
        cv2.circle(panel, rp, arm_disp, (0, 0, 200), CIRCLE_THICK,
                   lineType=cv2.LINE_AA)
        cv2.circle(panel, rp, 7, (0, 0, 255), -1, lineType=cv2.LINE_AA)
        if gp is not None:
            cv2.line(panel, gp, rp, (0, 0, 200), 2, lineType=cv2.LINE_AA)

    # ── Parameter column on the LEFT ──────────────────────────────────
    # The video region starts at x=col_w, so the column never overlaps
    # any moving marker or constraint circle in the visible cropped
    # disc. No alpha blend needed — the column lives on the black
    # background to the left of the video.

    def fv(v, decimals=1):
        return f"{v:+.{decimals}f}" if not np.isnan(v) else "  ---  "

    font = cv2.FONT_HERSHEY_SIMPLEX
    fs   = 0.50
    swatch_size = 10
    x_text  = 10
    x_label = x_text + swatch_size + 5

    # Clip header — voltage / drive-frequency parsed from the stem so the
    # video is self-identifying in any player. Falls back to the raw stem
    # when the standard "<V>V_<f>Hz[_N]" pattern doesn't match.
    if stem:
        m = _STEM_RE.match(stem)
        if m:
            v_str  = m.group("v")
            f_str  = m.group("f")
            rep    = m.group("rep")
            header = f"{v_str}V  {f_str}Hz" + (f"  #{rep}" if rep else "")
        else:
            header = stem
        cv2.putText(panel, header, (x_text, 28),
                    font, 0.62, (255, 255, 255), 1, lineType=cv2.LINE_AA)

    # Phase label (color-coded). 'driven' and 'free_swing' are the two
    # "normal" running phases; any other string (e.g. legacy 'holding')
    # gets the off-color to flag it.
    phase_col = (80, 255, 80) if phase in ('driven', 'free_swing') else (100, 100, 255)
    cv2.putText(panel, phase.upper(), (x_text, 60),
                font, 0.55, phase_col, 1, lineType=cv2.LINE_AA)

    # Time
    cv2.putText(panel, f"t = {t:.3f} s", (x_text, 90),
                font, fs, (200, 200, 200), 1, lineType=cv2.LINE_AA)

    # Parameters, grouped by arm: green θ₁/ω₁ block, then red θ₂/ω₂ block.
    params = [
        (f"th1 = {fv(th1)} deg",       BGR_ARM1, 132),
        (f"om1 = {fv(om1, 0)} deg/s",  BGR_ARM1, 162),
        (f"th2 = {fv(th2)} deg",       BGR_ARM2, 207),
        (f"om2 = {fv(om2, 0)} deg/s",  BGR_ARM2, 237),
    ]
    for text, color, y in params:
        cv2.rectangle(panel, (x_text, y - swatch_size),
                      (x_text + swatch_size, y), color, -1)
        cv2.putText(panel, text, (x_label, y),
                    font, fs, color, 1, lineType=cv2.LINE_AA)

    return panel

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    csv_path, video_path, output_mp4, output_dir = resolve_paths(args)

    # Per-batch rig calibration — stem is the measurement folder name
    # (or args.stem when supplied). 3.2V clips use a shifted pivot.
    stem = args.stem or os.path.basename(output_dir.rstrip(os.sep))
    pivot_orig, arm_length_px = get_pivot_arm(stem)

    from rich.console import Console as _Console
    _con = _Console()

    csv_ext = os.path.splitext(csv_path)[1].lower()
    if csv_ext != ".csv":
        _con.print(f"[red]ERROR:[/] first argument must be a tracking CSV, got [dim]{csv_path}[/] "
                   f"(extension '{csv_ext}').")
        _con.print(f"  [dim]Try:  python {os.path.basename(__file__)} --stem <config_description>[/]")
        sys.exit(2)

    video_ext = os.path.splitext(video_path)[1].lower()
    if video_ext not in (".mov", ".mp4", ".avi", ".mkv", ".m4v"):
        _con.print(f"[yellow]WARN:[/] second argument doesn't look like a video ([dim]{video_path}[/]). Continuing anyway.")

    from rich.table import Table as _Table
    import rich.box as _box
    io_t = _Table(box=_box.SIMPLE_HEAD, show_header=False)
    io_t.add_column(style="dim", min_width=10)
    io_t.add_column(style="white")
    io_t.add_row("CSV",    csv_path)
    io_t.add_row("Video",  video_path)
    io_t.add_row("Output", output_mp4)
    _con.print(io_t)

    # ── Load data ──
    _con.print("  [dim]Loading CSV …[/]")
    frames, times, phases, th1, th2, om1, om2, dropouts = load_csv(csv_path)
    N = len(frames)
    _con.print(f"  [dim]{N} frames, t_max = {times[-1]:.2f} s[/]")

    # Load x/y coordinates too (for left panel overlay)
    rows = list(csv.DictReader(open(csv_path)))
    xg = np.array([float(r['x_green']) if r['x_green'] else np.nan for r in rows])
    yg = np.array([float(r['y_green']) if r['y_green'] else np.nan for r in rows])
    xr = np.array([float(r['x_red'])   if r['x_red']   else np.nan for r in rows])
    yr = np.array([float(r['y_red'])   if r['y_red']   else np.nan for r in rows])

    # ── Set up matplotlib figure ──
    _con.print("  [dim]Setting up figure …[/]")
    fig, trace_lines, head_dots, time_txt = setup_figure(th1, th2, om1, om2)

    # Pre-compute XY data for each panel. Insert NaN at ±180° wrap
    # points so matplotlib breaks the trace line at the inverted-angle
    # crossings instead of streaking across the plot.
    def _break_arrays(arrays, mask):
        out = []
        for a in arrays:
            b = np.asarray(a, dtype=float).copy()
            b[1:][mask] = np.nan
            out.append(b)
        return out

    diff_th1 = np.abs(np.diff(th1)) > 180
    diff_th2 = np.abs(np.diff(th2)) > 180
    th1c, th2c = _break_arrays([th1, th2], diff_th1 | diff_th2)
    th1p, om1p = _break_arrays([th1, om1], diff_th1)
    th2p, om2p = _break_arrays([th2, om2], diff_th2)
    XY = [(th1c, th2c), (th1p, om1p), (th2p, om2p)]
    # Head-dot data: original (un-broken) arrays so the dot doesn't
    # disappear on a wrap frame.
    HEAD_XY = [(th1, th2), (th1, om1), (th2, om2)]

    # ── Open video ──
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _con.print(f"[red]ERROR:[/] Cannot open [dim]{video_path}[/]")
        return
    video_fps = cap.get(cv2.CAP_PROP_FPS) or FPS_OUT

    # ── Set up writer ──
    os.makedirs(output_dir, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_mp4, fourcc, video_fps,
                             (PANEL_W * 2, PANEL_H))

    # ── Render loop ──
    _con.print(f"  [dim]Rendering {N} frames → {output_mp4} …[/]")

    step = max(1, N // 40)   # progress update every 2.5%

    for i in range(N):
        # Read video frame
        ret, vframe = cap.read()
        if not ret:
            _con.print(f"\n[yellow]WARNING:[/] video ended at frame {i}")
            break

        # ── Update matplotlib plots ──
        for panel_idx, ((x, y), (xh, yh)) in enumerate(zip(XY, HEAD_XY)):
            # Pass arrays *with* NaN intact — matplotlib renders NaN as
            # a gap, breaking the line cleanly at wraps and dropouts.
            trace_lines[panel_idx].set_data(x[:i+1], y[:i+1])
            # Head dot uses the un-broken arrays so it stays visible
            # even on wrap frames.
            if not (np.isnan(xh[i]) or np.isnan(yh[i])):
                head_dots[panel_idx].set_data([xh[i]], [yh[i]])
            else:
                head_dots[panel_idx].set_data([], [])

        if phases[i] == 'free_swing':
            phase_word = 'FREE SWING'
        elif phases[i] == 'driven':
            phase_word = 'DRIVEN'
        else:
            phase_word = phases[i].upper()
        time_txt.set_text(
            f"frame {frames[i]:4d} / {N}   "
            f"t = {times[i]:.3f} s   "
            f"{phase_word}"
        )

        # ── Render matplotlib → numpy ──
        right_panel = render_figure(fig)

        # ── Build left panel ──
        left_panel = make_left_panel(
            vframe, phases[i], times[i],
            th1[i], th2[i], om1[i], om2[i],
            xg[i], yg[i], xr[i], yr[i],
            pivot_orig=pivot_orig, arm_length_px=arm_length_px,
            stem=stem,
        )

        # ── Stack and write ──
        composite = np.hstack([left_panel, right_panel])
        writer.write(composite)

        # Progress
        if i % step == 0 or i == N - 1:
            pct = 100 * (i + 1) // N
            bar = '█' * (pct // 5) + '░' * (20 - pct // 5)
            eta_frames = N - i - 1
            print(f"  [{bar}] {pct:3d}%  frame {i+1}/{N}", end='\r', flush=True)

    cap.release()
    writer.release()
    plt.close(fig)

    _con.print(f"\n  [dim]Saved → {output_mp4}[/]")

if __name__ == "__main__":
    main()
