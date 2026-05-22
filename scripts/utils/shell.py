"""
shell.py — interactive hub for the chaos pipeline.

Launched by bare ``chaos`` (no subcommand). Presents a compact
dashboard with single-key dispatch to all major pipeline actions.
Uses questionary for arrow-key clip pickers and Rich for formatting.

Usage:
    chaos              # launches the interactive shell
    python scripts/utils/shell.py   # same thing, standalone

The shell is additive — every ``chaos <subcommand>`` still works
for scripting, piping, and power-user invocations.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import questionary
from questionary import Choice

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS,
    REPO_ROOT, PHASE, clip_dir,
)

console = Console()

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v"}

SCRIPT_TRACK_ONE  = os.path.join(REPO_ROOT, "scripts", "utils", "track_one.py")
SCRIPT_VERIFY     = os.path.join(REPO_ROOT, "scripts", "processing", "verify_tracking.py")
SCRIPT_BATCH_FIGS = os.path.join(REPO_ROOT, "scripts", "utils", "batch_figures.py")
SCRIPT_ANALYZE    = os.path.join(REPO_ROOT, "scripts", "analysis", "chaos_analyze.py")
SCRIPT_COMBINED   = os.path.join(REPO_ROOT, "scripts", "analysis", "combined_video.py")
SCRIPT_POINCARE   = os.path.join(REPO_ROOT, "scripts", "analysis", "poincare.py")
SCRIPT_LYAPUNOV   = os.path.join(REPO_ROOT, "scripts", "analysis", "lyapunov.py")


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def load_registry():
    if not os.path.exists(EXPERIMENTS):
        return {}
    try:
        with open(EXPERIMENTS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _resolve_entry(stem, registry):
    """Find registry entry by config_description or video stem."""
    if stem in registry:
        return registry[stem]
    for entry in registry.values():
        if entry.get("config_description") == stem:
            return entry
        vf = entry.get("video_file") or ""
        if Path(vf).stem == stem:
            return entry
    return None


def _is_tracked(entry):
    """True if the entry has a tracking.csv on disk."""
    if not entry:
        return False
    md = entry.get("measurements_dir")
    if not md:
        return False
    csv_name = entry.get("csv_file") or "tracking.csv"
    phase_root = os.path.dirname(MEAS_DIR)
    return os.path.exists(os.path.join(phase_root, md, csv_name))


def get_clips():
    """Return (tracked_list, pending_list).

    Each item is a dict with keys:
        stem, video, status, dropout_pct, duration_s,
        drive_voltage_v, drive_freq_hz
    Stable sort order: alphabetical by stem.
    """
    reg = load_registry()

    # Build lookup from video filename → registry entry
    by_video = {}
    for entry in reg.values():
        vf = entry.get("video_file")
        if vf:
            by_video[vf] = entry

    tracked, pending = [], []

    # Walk all videos on disk
    if os.path.isdir(VIDEOS_DIR):
        for name in sorted(os.listdir(VIDEOS_DIR), key=str.lower):
            full = os.path.join(VIDEOS_DIR, name)
            if not os.path.isfile(full):
                continue
            if Path(name).suffix.lower() not in VIDEO_EXTS:
                continue
            stem = Path(name).stem
            entry = by_video.get(name) or _resolve_entry(stem, reg)

            info = {
                "stem":           entry.get("config_description", stem) if entry else stem,
                "video":          name,
                "drive_voltage_v": entry.get("drive_voltage_v") if entry else None,
                "drive_freq_hz":  entry.get("drive_freq_hz") if entry else None,
                "dropout_pct":    entry.get("dropout_rate_pct") if entry else None,
                "duration_s":     entry.get("duration_s") if entry else None,
                "quality":        entry.get("tracking_quality") if entry else None,
            }

            if entry and _is_tracked(entry):
                info["status"] = entry.get("tracking_quality", "tracked")
                tracked.append(info)
            else:
                info["status"] = "pending"
                pending.append(info)

    return tracked, pending


def get_numbered_map(tracked, pending):
    """Return a dict mapping 1-based number → stem for all clips.
    Tracked come first (sorted), then pending (sorted)."""
    mapping = {}
    for i, clip in enumerate(tracked + pending, start=1):
        mapping[i] = clip["stem"]
    return mapping


def resolve_stem_or_number(arg, tracked, pending):
    """If arg is a digit string, resolve to stem via numbered map.
    Otherwise return arg as-is (it's already a stem)."""
    if arg and arg.isdigit():
        n = int(arg)
        nmap = get_numbered_map(tracked, pending)
        return nmap.get(n)
    return arg


# ─────────────────────────────────────────────
# RENDERING
# ─────────────────────────────────────────────

def _progress_bar(done, total, width=40):
    """Return a Rich-markup progress bar string."""
    if total == 0:
        return "[dim]no clips[/]"
    filled = int(round(done / total * width))
    empty = width - filled
    pct = done / total * 100
    return (f"[green]{'█' * filled}[/][dim]{'░' * empty}[/]"
            f"  [bold]{done}[/][dim]/{total}[/]  [green]{pct:.0f}%[/]")


def render_hub(tracked, pending):
    """Print the compact hub dashboard."""
    total = len(tracked) + len(pending)
    n_verified = sum(1 for c in tracked if c.get("quality") == "verified")

    # Header line
    phase_short = PHASE.replace("pendulum-", "").replace("week", "w")
    console.print()
    console.print(
        f"  [bold magenta]chaos[/]  [dim]{phase_short}[/]"
        f"    {_progress_bar(len(tracked), total)}"
    )
    if n_verified and n_verified != len(tracked):
        console.print(
            f"         [dim]{n_verified} verified · "
            f"{len(tracked) - n_verified} tracked · "
            f"{len(pending)} pending[/]"
        )
    console.print()

    # Action menu
    console.print(Rule(style="dim"))
    actions = [
        ("t", "track next",    "auto-picks first pending clip",    "green"),
        ("p", "pick & track",  "arrow-key picker from pending",    "blue"),
        ("a", "analyze",       "pick a tracked clip → chaos card", "yellow"),
        ("f", "figures",       "batch-render all missing plots",   "magenta"),
        ("s", "status",        "full tracked / pending table",     "white"),
        ("v", "verify",        "re-verify a tracked clip",         "white"),
        ("r", "render",        "render overlay video",             "white"),
        ("l", "lyapunov",      "compute λ₁ for a clip",           "white"),
        ("q", "quit",          "",                                 "dim"),
    ]
    for key, label, desc, color in actions:
        desc_part = f"  [dim]→ {desc}[/]" if desc else ""
        console.print(f"  [{color} bold]{key}[/]  {label:<18}{desc_part}")
    console.print(Rule(style="dim"))


def render_status_table(tracked, pending):
    """Print the full status table with stable numbering."""
    t = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    t.add_column("#", justify="right", style="dim", width=4)
    t.add_column("Stem", style="white", min_width=20)
    t.add_column("Status", min_width=10)
    t.add_column("Drop%", justify="right", width=7)
    t.add_column("Duration", justify="right", width=9)
    t.add_column("Vd", justify="right", width=6)
    t.add_column("fd", justify="right", width=8)

    num = 1
    for clip in tracked:
        quality = clip.get("quality", "tracked")
        if quality == "verified":
            status_cell = "[green]verified[/]"
        elif quality == "manual_accept":
            status_cell = "[yellow]accepted[/]"
        else:
            status_cell = f"[cyan]{quality or 'tracked'}[/]"

        drop = clip.get("dropout_pct")
        drop_cell = f"{drop:.1f}%" if drop is not None else "[dim]—[/]"
        dur = clip.get("duration_s")
        dur_cell = f"{dur:.1f}s" if dur is not None else "[dim]—[/]"
        vd = clip.get("drive_voltage_v")
        vd_cell = f"{vd}V" if vd is not None else "[dim]—[/]"
        fd = clip.get("drive_freq_hz")
        fd_cell = f"{fd}Hz" if fd is not None else "[dim]—[/]"

        t.add_row(str(num), clip["stem"], status_cell,
                  drop_cell, dur_cell, vd_cell, fd_cell)
        num += 1

    if pending:
        t.add_row("", "", "", "", "", "", "", style="dim")
        for clip in pending:
            vd = clip.get("drive_voltage_v")
            vd_cell = f"{vd}V" if vd is not None else "[dim]—[/]"
            fd = clip.get("drive_freq_hz")
            fd_cell = f"{fd}Hz" if fd is not None else "[dim]—[/]"
            t.add_row(str(num), clip["stem"], "[yellow]pending[/]",
                      "[dim]—[/]", "[dim]—[/]", vd_cell, fd_cell)
            num += 1

    console.print(t)


# ─────────────────────────────────────────────
# PICKERS
# ─────────────────────────────────────────────

def pick_clip(clips, label="Pick a clip"):
    """Arrow-key picker. Returns stem or None on Esc/Ctrl-C."""
    if not clips:
        console.print("  [dim]No clips available.[/]")
        return None

    choices = []
    for clip in clips:
        vd = clip.get("drive_voltage_v")
        fd = clip.get("drive_freq_hz")
        extra = ""
        if vd is not None and fd is not None:
            extra = f"  {vd}V  {fd}Hz"
        elif vd is not None:
            extra = f"  {vd}V"
        display = f"{clip['stem']:<22}{extra}"
        choices.append(Choice(display, value=clip["stem"]))

    try:
        result = questionary.select(
            label,
            choices=choices,
            use_arrow_keys=True,
            use_jk_keys=True,
        ).ask()
    except KeyboardInterrupt:
        return None
    return result


def pick_tracked(tracked, label="Pick a clip"):
    return pick_clip(tracked, label)


def pick_pending(pending, label="Pick a clip to track"):
    return pick_clip(pending, label)


# ─────────────────────────────────────────────
# ACTION RUNNERS
# ─────────────────────────────────────────────

def _run(script, *args):
    """Run a script as subprocess, streaming output live."""
    cmd = [sys.executable, script, *map(str, args)]
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def _pause():
    """Wait for any keypress before returning to hub."""
    console.print()
    try:
        questionary.press_any_key_to_continue(
            "press any key to return to hub..."
        ).ask()
    except KeyboardInterrupt:
        pass


def do_track_next(pending):
    if not pending:
        console.print("  [green]Nothing pending — all clips tracked.[/]")
        _pause()
        return
    stem = pending[0]["stem"]
    console.print(f"  [bold]Tracking:[/] {stem}")
    console.print()
    _run(SCRIPT_TRACK_ONE, "--stem", stem)
    _pause()


def do_pick_and_track(pending):
    stem = pick_pending(pending)
    if not stem:
        return
    console.print(f"  [bold]Tracking:[/] {stem}")
    console.print()
    _run(SCRIPT_TRACK_ONE, "--stem", stem)
    _pause()


def do_analyze(tracked):
    stem = pick_tracked(tracked, "Pick a clip to analyze")
    if not stem:
        return
    _run(SCRIPT_ANALYZE, stem)
    _pause()


def do_figures():
    _run(SCRIPT_BATCH_FIGS)
    _pause()


def do_status(tracked, pending):
    console.print()
    render_status_table(tracked, pending)
    _pause()


def do_verify(tracked):
    stem = pick_tracked(tracked, "Pick a clip to re-verify")
    if not stem:
        return
    _run(SCRIPT_VERIFY, "--stem", stem)
    _pause()


def do_render(tracked):
    stem = pick_tracked(tracked, "Pick a clip to render")
    if not stem:
        return
    _run(SCRIPT_COMBINED, "--stem", stem)
    _pause()


def do_lyapunov(tracked):
    stem = pick_tracked(tracked, "Pick a clip for λ₁")
    if not stem:
        return
    _run(SCRIPT_LYAPUNOV, "--stem", stem)
    _pause()


# ─────────────────────────────────────────────
# HUB LOOP
# ─────────────────────────────────────────────

DISPATCH = {
    "t": lambda tr, pe: do_track_next(pe),
    "p": lambda tr, pe: do_pick_and_track(pe),
    "a": lambda tr, pe: do_analyze(tr),
    "f": lambda tr, pe: do_figures(),
    "s": lambda tr, pe: do_status(tr, pe),
    "v": lambda tr, pe: do_verify(tr),
    "r": lambda tr, pe: do_render(tr),
    "l": lambda tr, pe: do_lyapunov(tr),
}


def hub():
    """Main interactive shell loop."""
    try:
        while True:
            console.clear()
            tracked, pending = get_clips()
            render_hub(tracked, pending)

            try:
                key = input("  ▸ ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if not key:
                continue
            key = key[0]

            if key == "q":
                break

            handler = DISPATCH.get(key)
            if handler:
                handler(tracked, pending)
            else:
                console.print(f"  [dim]Unknown key: {key}[/]")
                import time
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    console.print()
    console.print("  [dim]bye.[/]")


if __name__ == "__main__":
    hub()
