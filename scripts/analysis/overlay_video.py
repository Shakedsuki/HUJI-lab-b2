"""
overlay_video.py
----------------
Render only the left panel of combined_video.py — the original video
with tracking-marker overlays. No phase-space plots, no matplotlib
per frame, much faster. For quick visual sanity checks of a tracking
pass.

Output: measurements/<stem>/overlay.mp4 at source framerate, 960×720.

Usage:
  # Mode 1 — measurement folder:
  python scripts/analysis/overlay_video.py --stem 3.2V_1.34Hz

  # Mode 2 — explicit CSV + video:
  python scripts/analysis/overlay_video.py \\
      measurements/3.2V_1.34Hz/tracking.csv videos/3.2V_1.34Hz.mov

Imports load_csv and make_left_panel from combined_video so the
overlay matches the combined-video version frame-for-frame.
"""

import argparse
import csv
import os
import sys

import cv2
import numpy as np
import rich.box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
sys.path.insert(0, os.path.abspath(os.path.join(_THIS_DIR, os.pardir, "utils")))
from combined_video import (  # noqa: E402
    FPS_OUT,
    PANEL_H,
    PANEL_W,
    load_csv,
    make_left_panel,
    resolve_paths,
)
from paths import REPO_ROOT  # noqa: E402
from thresholds import get_pivot_arm  # noqa: E402

console = Console()
CLR_VIDEOS = "#38BDF8"  # matches the shell's videos accent


def _rel(p):
    try:
        return os.path.relpath(p, REPO_ROOT)
    except ValueError:
        return p


def _render_header(stem, csv_path, video_path, output_mp4, pivot, arm):
    hdr = Table(box=None, show_header=False, padding=(0, 2))
    hdr.add_column(style="dim", justify="right")
    hdr.add_column(style="white")
    hdr.add_row("stem", f"[bold]{stem}[/]")
    hdr.add_row("pivot", f"({pivot[0]}, {pivot[1]})  [dim]arm[/] {arm} px")
    hdr.add_row("video", f"[dim]{_rel(video_path)}[/]")
    hdr.add_row("csv", f"[dim]{_rel(csv_path)}[/]")
    hdr.add_row("output", _rel(output_mp4))
    console.print(Panel(hdr, title=f"[bold {CLR_VIDEOS}]overlay render[/]",
                        border_style=CLR_VIDEOS, box=rich.box.ROUNDED,
                        padding=(0, 1), expand=False))


def parse_args():
    p = argparse.ArgumentParser(
        description="Render tracking-overlay video (no phase plots).")
    p.add_argument("csv", nargs="?", default=None,
                   help="Path to tracking CSV (positional, optional).")
    p.add_argument("video", nargs="?", default=None,
                   help="Path to source video (positional, optional).")
    p.add_argument("--stem", default=None,
                   help="config_description; resolves CSV/video from "
                        "experiments.json.")
    return p.parse_args()


def main():
    args = parse_args()
    # resolve_paths returns the combined.mp4 path in [2]; we ignore it
    # and write overlay.mp4 alongside the measurement folder instead.
    csv_path, video_path, _combined_mp4, output_dir = resolve_paths(args)
    # Per-batch rig calibration — 3.2V clips use a shifted pivot.
    stem = args.stem or os.path.basename(output_dir.rstrip(os.sep))
    output_mp4 = os.path.join(output_dir, f"{stem}_overlay.mp4")
    pivot_orig, arm_length_px = get_pivot_arm(stem)

    _render_header(stem, csv_path, video_path, output_mp4,
                   pivot_orig, arm_length_px)

    frames, times, phases, th1, th2, om1, om2, dropouts = load_csv(csv_path)
    N = len(frames)

    rows = list(csv.DictReader(open(csv_path)))
    xg = np.array([float(r['x_green']) if r['x_green'] else np.nan for r in rows])
    yg = np.array([float(r['y_green']) if r['y_green'] else np.nan for r in rows])
    xr = np.array([float(r['x_red'])   if r['x_red']   else np.nan for r in rows])
    yr = np.array([float(r['y_red'])   if r['y_red']   else np.nan for r in rows])

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        console.print(f"  [red]✗ cannot open video:[/] {video_path}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_OUT

    console.print(f"  [dim]source[/]  [white]{N}[/] frames  [dim]·[/]  "
                  f"t_max [white]{times[-1]:.1f}s[/]  [dim]·[/]  "
                  f"[white]{fps:.0f}[/] fps")

    os.makedirs(output_dir, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_mp4, fourcc, fps, (PANEL_W, PANEL_H))

    with Progress(
        TextColumn("  [progress.description]{task.description}"),
        BarColumn(bar_width=30, complete_style=CLR_VIDEOS, finished_style="green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[dim]frame {task.completed}/{task.total}[/]"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("rendering", total=N)
        for i in range(N):
            ret, vframe = cap.read()
            if not ret:
                console.print(f"  [yellow]⚠ video ended early at frame {i}[/]")
                break
            panel = make_left_panel(
                vframe, phases[i], times[i],
                th1[i], th2[i], om1[i], om2[i],
                xg[i], yg[i], xr[i], yr[i],
                pivot_orig=pivot_orig, arm_length_px=arm_length_px,
                stem=stem,
            )
            writer.write(panel)
            progress.update(task, advance=1)
    cap.release()
    writer.release()
    console.print(f"  [green]✓ saved[/]  [dim]{_rel(output_mp4)}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
