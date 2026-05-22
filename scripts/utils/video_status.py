"""
video_status.py
---------------
Print which videos have been tracked vs. which are still pending.

A video is "tracked" if it has a tracking.csv on disk at the registry
entry's `measurements_dir`. "Pending" means the file exists under
videos/ but no tracking.csv has been produced yet.

Run on its own to see the breakdown:

    python scripts/utils/video_status.py
"""

import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v"}
EXPERIMENTS_FILE = EXPERIMENTS
PHASE_ROOT = os.path.dirname(MEAS_DIR)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def list_videos(videos_dir=VIDEOS_DIR):
    """Sorted list of video file paths in `videos_dir` (top level only)."""
    if not os.path.isdir(videos_dir):
        return []
    out = []
    for name in sorted(os.listdir(videos_dir), key=str.lower):
        full = os.path.join(videos_dir, name)
        if os.path.isfile(full) and Path(name).suffix.lower() in VIDEO_EXTS:
            out.append(full)
    return out

def load_registry(path=EXPERIMENTS_FILE):
    """Load experiments.json. Returns {} if absent or malformed."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

def is_tracked(stem, registry, root=PHASE_ROOT):
    """A video is "tracked" if its registry entry's measurements_dir
    contains a tracking.csv on disk."""
    entry = _resolve_entry(stem, registry)
    if not entry:
        return False
    meas_dir = entry.get("measurements_dir")
    if not meas_dir:
        return False
    csv_basename = entry.get("csv_file") or "tracking.csv"
    return os.path.exists(os.path.join(root, meas_dir, csv_basename))

def _resolve_entry(stem, registry):
    """
    Return the registry entry for `stem`, looking it up by either the
    legacy registry key (e.g. DSC_0136) or the video filename stem
    (which after migration is the config_description for most entries).
    Returns None if no match.
    """
    # Direct key hit (legacy DSC-style keys).
    if stem in registry:
        return registry[stem]
    # Otherwise scan: a video named th1_p044_th2_m001.mov can be
    # registered under key DSC_0136 with video_file=th1_p044_th2_m001.mov.
    for entry in registry.values():
        video_file = entry.get("video_file") or ""
        if Path(video_file).stem == stem:
            return entry
        if entry.get("config_description") == stem:
            return entry
    return None

def status_breakdown(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    """Return (tracked_paths, pending_paths) — both sorted lists."""
    registry = load_registry(registry_path)
    videos   = list_videos(videos_dir)
    tracked, pending = [], []
    for v in videos:
        stem = Path(v).stem
        (tracked if is_tracked(stem, registry) else pending).append(v)
    return tracked, pending

def status_summary(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    """One-liner suitable for printing before opening a picker."""
    t, p = status_breakdown(videos_dir, registry_path)
    return f"Tracked: {len(t)}   Pending: {len(p)}   (total: {len(t) + len(p)})"

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def print_status(videos_dir=VIDEOS_DIR, registry_path=EXPERIMENTS_FILE):
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    tracked, pending = status_breakdown(videos_dir, registry_path)
    total = len(tracked) + len(pending)
    registry = load_registry(registry_path)

    # Summary bar
    n_verified = sum(1 for v in tracked
                     if (_resolve_entry(Path(v).stem, registry) or {})
                     .get("tracking_quality") == "verified")
    n_tracked = len(tracked)
    n_unverified = n_tracked - n_verified
    n_pending = len(pending)
    width = 30
    if total > 0:
        w_ver = int(round(n_verified / total * width))
        w_trk = int(round(n_unverified / total * width))
        w_pen = width - w_ver - w_trk
        bar = (f"[green]{'█' * w_ver}[/]"
               f"[yellow]{'█' * w_trk}[/]"
               f"[dim]{'░' * w_pen}[/]")
        console.print(f"  {bar}  [bold]{n_tracked}[/][dim]/{total}[/]")
        console.print(
            f"  [green]{n_verified} verified[/] [dim]·[/] "
            f"[yellow]{n_unverified} tracked[/] [dim]· {n_pending} pending[/]")
    else:
        console.print("  [dim]no clips found[/]")
    console.print()

    # Table
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    t.add_column("#", justify="right", style="dim", width=4)
    t.add_column("Stem", style="white", min_width=20)
    t.add_column("Status", min_width=10)
    t.add_column("Drop%", justify="right", width=7)
    t.add_column("Duration", justify="right", width=9)

    num = 1
    for v in tracked:
        stem  = Path(v).stem
        entry = _resolve_entry(stem, registry) or {}
        quality = entry.get("tracking_quality", "tracked")
        if quality == "verified":
            status_cell = "[green]verified[/]"
        elif quality == "manual_accept":
            status_cell = "[yellow]accepted[/]"
        else:
            status_cell = f"[cyan]{quality or 'tracked'}[/]"
        drop = entry.get("dropout_rate_pct")
        drop_cell = f"{drop:.1f}%" if isinstance(drop, (int, float)) else "[dim]—[/]"
        dur = entry.get("duration_s")
        dur_cell = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "[dim]—[/]"
        t.add_row(str(num), stem, status_cell, drop_cell, dur_cell)
        num += 1

    if pending:
        t.add_row("", "", "", "", "", style="dim")
        for v in pending:
            t.add_row(str(num), Path(v).stem, "[yellow]pending[/]",
                      "[dim]—[/]", "[dim]—[/]")
            num += 1

    console.print(t)

if __name__ == "__main__":
    print_status()
