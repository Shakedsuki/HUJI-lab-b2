"""
shell.py — interactive hub for the chaos pipeline.

Launched by bare ``chaos`` (no subcommand). Presents a compact
dashboard with single-key dispatch to all major pipeline actions.
Uses questionary for arrow-key clip pickers and Rich for formatting.
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
from questionary import Choice, Separator

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (
    DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS,
    REPO_ROOT, PHASE, PHASE_DRIVEN, clip_dir,
)

console = Console()

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".m4v"}

SCRIPT_TRACK_ONE   = os.path.join(REPO_ROOT, "scripts", "utils", "track_one.py")
SCRIPT_BULK        = os.path.join(REPO_ROOT, "scripts", "utils", "bulk_track.py")
SCRIPT_VERIFY      = os.path.join(REPO_ROOT, "scripts", "processing", "verify_tracking.py")
SCRIPT_BATCH_FIGS  = os.path.join(REPO_ROOT, "scripts", "utils", "batch_figures.py")
SCRIPT_ANALYZE     = os.path.join(REPO_ROOT, "scripts", "analysis", "chaos_analyze.py")
SCRIPT_COMBINED    = os.path.join(REPO_ROOT, "scripts", "analysis", "combined_video.py")
SCRIPT_POINCARE    = os.path.join(REPO_ROOT, "scripts", "analysis", "poincare.py")
SCRIPT_LYAPUNOV    = os.path.join(REPO_ROOT, "scripts", "analysis", "lyapunov.py")
SCRIPT_DRIVEN_POIN = os.path.join(REPO_ROOT, "scripts", "analysis", "driven_poincare.py")
SCRIPT_DRIVEN_BIF  = os.path.join(REPO_ROOT, "scripts", "analysis", "driven_bifurcation.py")
SCRIPT_REPORT      = os.path.join(REPO_ROOT, "scripts", "utils", "generate_status_report.py")
SCRIPT_ROADMAP     = os.path.join(REPO_ROOT, "scripts", "utils", "generate_roadmap.py")
SCRIPT_STATUS      = os.path.join(REPO_ROOT, "scripts", "utils", "video_status.py")

WEEK_GROUPS = {
    "week5": {"label": "week 5", "desc": "broad V/f survey",     "color": "cyan"},
    "week6": {"label": "week 6", "desc": "3.2V resonance sweep", "color": "yellow"},
}

LOGO = (
    "[bold magenta]\u250c\u2500\u2510 \u252c \u252c \u250c\u2500\u2510 \u250c\u2500\u2510 \u250c\u2500\u2510[/]\n"
    "[bold magenta]\u2502   \u251c\u2500\u2524 \u251c\u2500\u2524 \u2502 \u2502 \u2514\u2500\u2510[/]\n"
    "[bold magenta]\u2514\u2500\u2518 \u2534 \u2534 \u2534 \u2534 \u2514\u2500\u2518 \u2514\u2500\u2518[/]"
)


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
    if not entry:
        return False
    md = entry.get("measurements_dir")
    if not md:
        return False
    csv_name = entry.get("csv_file") or "tracking.csv"
    phase_root = os.path.dirname(MEAS_DIR)
    return os.path.exists(os.path.join(phase_root, md, csv_name))

def _week_bucket(stem):
    if PHASE != PHASE_DRIVEN:
        return None
    if stem.startswith("3.2V_") and stem != "3.2V_1Hz":
        return "week6"
    return "week5"

def get_clips():
    reg = load_registry()
    by_video = {}
    for entry in reg.values():
        vf = entry.get("video_file")
        if vf:
            by_video[vf] = entry
    tracked, pending = [], []
    if os.path.isdir(VIDEOS_DIR):
        for name in sorted(os.listdir(VIDEOS_DIR), key=str.lower):
            full = os.path.join(VIDEOS_DIR, name)
            if not os.path.isfile(full) or Path(name).suffix.lower() not in VIDEO_EXTS:
                continue
            stem = Path(name).stem
            entry = by_video.get(name) or _resolve_entry(stem, reg)
            cfg_stem = entry.get("config_description", stem) if entry else stem
            info = {
                "stem": cfg_stem, "video": name,
                "drive_voltage_v": entry.get("drive_voltage_v") if entry else None,
                "drive_freq_hz": entry.get("drive_freq_hz") if entry else None,
                "dropout_pct": entry.get("dropout_rate_pct") if entry else None,
                "duration_s": entry.get("duration_s") if entry else None,
                "quality": entry.get("tracking_quality") if entry else None,
                "week": _week_bucket(cfg_stem),
            }
            if entry and _is_tracked(entry):
                info["status"] = entry.get("tracking_quality", "tracked")
                tracked.append(info)
            else:
                info["status"] = "pending"
                pending.append(info)
    return tracked, pending

def _group_by_week(clips):
    groups = {}
    order = []
    for clip in clips:
        wk = clip.get("week")
        if wk not in groups:
            groups[wk] = []
            order.append(wk)
        groups[wk].append(clip)
    return [(k, groups[k]) for k in order]


# ─────────────────────────────────────────────
# RENDERING
# ─────────────────────────────────────────────

def _stacked_bar(n_verified, n_tracked, total, width=30):
    if total == 0:
        return "[dim]no clips[/]"
    n_unverified = n_tracked - n_verified
    w_ver = int(round(n_verified / total * width))
    w_trk = int(round(n_unverified / total * width))
    w_pen = width - w_ver - w_trk
    return (f"[green]{'\u2588' * w_ver}[/]"
            f"[yellow]{'\u2588' * w_trk}[/]"
            f"[dim]{'\u2591' * w_pen}[/]")


def _action_card(title, color, items):
    """Build a Rich Panel card with a list of key-label pairs."""
    lines = []
    for key, label in items:
        lines.append(f"  [{color} bold]{key:<3}[/] {label}")
    content = "\n".join(lines)
    return Panel(
        Text.from_markup(content),
        title=f"[bold]{title}[/]",
        border_style=color,
        padding=(0, 0),
        expand=True,
    )


def render_hub(tracked, pending, expanded=True):
    total = len(tracked) + len(pending)
    n_verified = sum(1 for c in tracked if c.get("quality") == "verified")
    n_tracked = len(tracked)
    n_unverified = n_tracked - n_verified
    n_pending = len(pending)

    phase_short = PHASE.replace("pendulum-", "").replace("week", "w")
    bar = _stacked_bar(n_verified, n_tracked, total)
    legend = (f"[green]{n_verified} verified[/] [dim]\u00b7[/] "
              f"[yellow]{n_unverified} tracked[/] [dim]\u00b7 {n_pending} pending[/]")

    # Header: logo left, stats right
    header = Text.from_markup(
        f"  {LOGO}\n"
        f"  [dim]double pendulum[/]"
        f"         {bar}  [bold]{n_tracked}[/][dim]/{total}[/]\n"
        f"  [dim]{phase_short}[/]"
        f"       {legend}"
    )

    if expanded:
        # 2x2 action card grid
        card_track = _action_card("track", "green", [
            ("n", "next"),
            ("p", "pick & track"),
            ("b", "bulk"),
            ("x", "sanity check"),
            ("k", "sanity sweep"),
            ("v", "verify"),
            ("r", "render"),
        ])
        card_analyze = _action_card("analyze", "yellow", [
            ("c", "chaos card"),
            ("o", "poincar\u00e9"),
            ("l", "lyapunov"),
            ("d", "driven poincar\u00e9"),
            ("i", "bifurcation"),
            ("qi", "quick insights"),
        ])
        card_figures = _action_card("figures", "magenta", [
            ("fa", "all missing"),
            ("fs", "single clip"),
            ("fv", "+ video"),
            ("ff", "force all"),
            ("fp", "preview frame"),
        ])
        card_info = _action_card("info", "cyan", [
            ("s", "full status table"),
            ("e", "export report"),
            ("m", "roadmap"),
            ("w", "switch phase"),
            ("h", "help"),
        ])

        row1 = Table(box=None, show_header=False, expand=True, padding=(0, 1))
        row1.add_column(ratio=1)
        row1.add_column(ratio=1)
        row1.add_row(card_track, card_analyze)

        row2 = Table(box=None, show_header=False, expand=True, padding=(0, 1))
        row2.add_column(ratio=1)
        row2.add_column(ratio=1)
        row2.add_row(card_figures, card_info)

        footer = Text.from_markup(
            "  [dim]q quit[/]                          [dim]\u2212 collapse[/]"
        )

        body = Group(header, Text(""), row1, row2, Text(""), footer)
    else:
        # Collapsed: compact list with submenu hints
        actions = Text.from_markup(
            "    [green bold]t[/]  track          [dim]\u2192 track, verify, render clips[/]\n"
            "    [yellow bold]a[/]  analyze        [dim]\u2192 chaos card, Poincar\u00e9, \u03bb\u2081[/]\n"
            "    [magenta bold]f[/]  figures        [dim]\u2192 batch-render plots[/]\n"
            "    [cyan bold]s[/]  info           [dim]\u2192 status, report, roadmap[/]"
        )
        footer = Text.from_markup(
            "  [dim]q quit[/]                            [dim]+ expand[/]"
        )
        body = Group(header, Text(""), actions, Text(""), footer)

    console.print(Panel(
        body,
        border_style="magenta",
        padding=(1, 2),
        width=min(console.width, 76),
    ))


def render_status_panels(tracked, pending):
    all_clips = tracked + pending
    groups = _group_by_week(all_clips)
    num = 1
    for week_key, clips in groups:
        meta = WEEK_GROUPS.get(week_key, {"label": "clips", "desc": "", "color": "white"})
        color = meta["color"]
        grp_tracked = [c for c in clips if c["status"] != "pending"]
        grp_verified = [c for c in grp_tracked if c.get("quality") == "verified"]
        grp_pending = [c for c in clips if c["status"] == "pending"]
        bar = _stacked_bar(len(grp_verified), len(grp_tracked), len(clips), width=24)
        legend = (f"[green]{len(grp_verified)} verified[/] [dim]\u00b7[/] "
                  f"[yellow]{len(grp_tracked) - len(grp_verified)} tracked[/] [dim]\u00b7 "
                  f"{len(grp_pending)} pending[/]")
        t = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        t.add_column(justify="right", style="dim", width=4)
        t.add_column(style="white", min_width=18, ratio=1)
        t.add_column(min_width=10)
        t.add_column(justify="right", width=7)
        t.add_column(justify="right", width=9)
        for clip in clips:
            quality = clip.get("quality")
            status = clip.get("status", "pending")
            if status == "pending":
                s_cell = "[yellow]pending[/]"
            elif quality == "verified":
                s_cell = "[green]verified[/]"
            elif quality == "manual_accept":
                s_cell = "[yellow]accepted[/]"
            else:
                s_cell = f"[cyan]{quality or 'tracked'}[/]"
            drop = clip.get("dropout_pct")
            d_cell = f"{drop:.1f}%" if drop is not None else "[dim]\u2014[/]"
            dur = clip.get("duration_s")
            dur_cell = f"{dur:.1f}s" if dur is not None else "[dim]\u2014[/]"
            t.add_row(str(num), clip["stem"], s_cell, d_cell, dur_cell)
            num += 1
        title_str = f"[bold]{meta['label']}[/]"
        if meta["desc"]:
            title_str += f" [dim]\u00b7 {meta['desc']}[/]"
        title_str += f" [dim]\u00b7[/] {len(grp_tracked)}[dim]/{len(clips)}[/]"
        body = Group(Text.from_markup(f"  {bar}  {legend}"), Text(""), t)
        console.print(Panel(body, title=title_str, border_style=color, padding=(0, 1)))
        console.print()


# ─────────────────────────────────────────────
# PICKERS
# ─────────────────────────────────────────────

_PICKER_STYLE = None

def _get_picker_style():
    global _PICKER_STYLE
    if _PICKER_STYLE is None:
        from prompt_toolkit.styles import Style as PtStyle
        _PICKER_STYLE = PtStyle([
            ("qmark", "fg:#fbbf24 bold"),
            ("question", "bold"),
            ("pointer", "fg:#22d3ee bold"),
            ("highlighted", "fg:#5eead4 bold"),
            ("selected", "fg:#5eead4"),
        ])
    return _PICKER_STYLE

def pick_clip(clips, label="Pick a clip"):
    if not clips:
        console.print("  [dim]No clips available.[/]")
        return None
    choices = [Choice("\u2190 back", value=None)]
    groups = _group_by_week(clips)
    for week_key, group_clips in groups:
        meta = WEEK_GROUPS.get(week_key)
        if meta:
            choices.append(Separator(
                f"\u2500\u2500\u2500\u2500 {meta['label']} \u00b7 "
                f"{meta['desc']} ({len(group_clips)} clips) "
                f"\u2500\u2500\u2500\u2500"
            ))
        for i, clip in enumerate(group_clips):
            is_last = (i == len(group_clips) - 1)
            branch = "\u2570\u2500" if is_last else "\u251c\u2500"
            vd = clip.get("drive_voltage_v")
            fd = clip.get("drive_freq_hz")
            extra = ""
            if vd is not None and fd is not None:
                extra = f"  {vd}V  {fd}Hz"
            display = f" {branch} {clip['stem']:<20}{extra}"
            choices.append(Choice(display, value=clip["stem"]))
    try:
        result = questionary.select(
            label, choices=choices, style=_get_picker_style(),
            use_arrow_keys=True, use_jk_keys=True,
        ).ask()
    except KeyboardInterrupt:
        return None
    return result

def pick_tracked(tracked, label="Pick a clip"):
    return pick_clip(tracked, label)

def pick_pending(pending, label="Pick a clip to track"):
    return pick_clip(pending, label)


# ─────────────────────────────────────────────
# SUBMENUS (collapsed mode fallback)
# ─────────────────────────────────────────────

def _submenu(title, actions):
    console.print()
    console.print(f"  [bold]{title}[/]")
    console.print(Rule(style="dim"))
    for key, label, desc, color in actions:
        desc_part = f"  [dim]\u2192 {desc}[/]" if desc else ""
        console.print(f"  [{color} bold]{key}[/]  {label:<20}{desc_part}")
    console.print(f"  [dim bold]\u2190[/]  [dim]back[/]")
    console.print(Rule(style="dim"))
    try:
        k = input("  \u25b8 ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    return k[0] if k else None

def submenu_track(tracked, pending):
    k = _submenu("track", [
        ("n", "next",          "auto-pick first pending",   "green"),
        ("p", "pick & track",  "arrow-key picker",          "blue"),
        ("b", "bulk",          "sequential batch",          "magenta"),
        ("x", "sanity check",  "examine one tracked clip",  "cyan"),
        ("k", "sanity sweep",  "auto-check all tracked",    "cyan"),
        ("v", "verify",        "re-verify a tracked clip",  "yellow"),
        ("r", "render",        "overlay video for a clip",  "white"),
    ])
    if k == "n": do_track_next(pending)
    elif k == "p": do_pick_and_track(pending)
    elif k == "b": do_bulk()
    elif k == "x": do_sanity_check(tracked)
    elif k == "k": do_sanity_sweep(tracked)
    elif k == "v": do_verify(tracked)
    elif k == "r": do_render(tracked)

def submenu_analyze(tracked):
    k = _submenu("analyze", [
        ("c", "chaos card",      "0-1 test, verdict",             "yellow"),
        ("p", "poincar\u00e9",        "section at \u03b8\u2081+\u03b8\u2082=0",           "blue"),
        ("l", "lyapunov",        "largest \u03bb\u2081 (Rosenstein)",  "magenta"),
        ("d", "driven poincar\u00e9", "stroboscopic",                 "white"),
        ("b", "bifurcation",     "cross-clip Vd or fd sweep",     "white"),
        ("q", "quick insights",  "interactive plot explorer",     "cyan"),
    ])
    if k == "c": do_analyze(tracked)
    elif k == "p": do_poincare(tracked)
    elif k == "l": do_lyapunov(tracked)
    elif k == "d": do_driven_poincare(tracked)
    elif k == "b": do_driven_bifurcation()
    elif k == "q": do_quick_insights(tracked)

def submenu_figures(tracked):
    k = _submenu("figures", [
        ("a", "all missing",  "batch-render every tracked clip", "magenta"),
        ("s", "single clip",  "pick one \u2192 render its figures",  "blue"),
        ("v", "+ video",      "include mp4s (slow)",              "white"),
        ("f", "force all",    "re-render even existing",          "white"),
    ])
    if k == "a": do_figures()
    elif k == "s": do_figures_single(tracked)
    elif k == "v": do_figures_with_video()
    elif k == "f": do_figures_force()

def submenu_info(tracked, pending):
    k = _submenu("info", [
        ("s", "full status",  "stacked panel view",           "cyan"),
        ("e", "export",       "generate status_report.xlsx",  "white"),
        ("m", "roadmap",      "generate tracking_roadmap.md", "white"),
        ("w", "switch phase", "toggle free-swing / driven",   "white"),
        ("h", "help",         "cheat sheet",                  "white"),
    ])
    if k == "s": do_status(tracked, pending)
    elif k == "e": do_export()
    elif k == "m": do_roadmap()
    elif k == "w": do_switch_phase()
    elif k == "h": do_help()


# ─────────────────────────────────────────────
# ACTION RUNNERS
# ─────────────────────────────────────────────

def _run(script, *args):
    cmd = [sys.executable, script, *map(str, args)]
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode

def _pause():
    console.print()
    try:
        questionary.press_any_key_to_continue("press any key to return...").ask()
    except KeyboardInterrupt:
        pass

# ── Track ──
def do_track_next(pending):
    if not pending:
        console.print("  [green]Nothing pending \u2014 all clips tracked.[/]")
        _pause(); return
    stem = pending[0]["stem"]
    console.print(f"  [bold]Tracking:[/] {stem}\n")
    _run(SCRIPT_TRACK_ONE, "--stem", stem); _pause()

def do_pick_and_track(pending):
    stem = pick_pending(pending)
    if not stem: return
    console.print(f"  [bold]Tracking:[/] {stem}\n")
    _run(SCRIPT_TRACK_ONE, "--stem", stem); _pause()

def do_bulk():
    _run(SCRIPT_BULK); _pause()

def do_sanity_check(tracked):
    stem = pick_tracked(tracked, "Pick a clip to examine")
    if not stem: return
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    from sanity_check import check_one
    try:
        check_one(stem)
    except Exception as e:
        console.print(f"  [red]ERROR:[/] {e}")
    _pause()

def do_sanity_sweep(tracked):
    if not tracked:
        console.print("  [dim]No tracked clips to check.[/]")
        _pause()
        return
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    from sanity_check import check_sweep

    def on_pause(stem, verdict, reasons):
        console.print("  [dim][a]ccept  [f]lag  [r]ender video  [n]ext  [q]uit[/]")
        try:
            k = input("  \u25b8 ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        return k[0] if k else "n"

    console.print()
    results = check_sweep(tracked, on_pause=on_pause)
    n_clean = sum(1 for _, v in results if v == "CLEAN")
    n_warn = sum(1 for _, v in results if v in ("WARN", "REVIEW"))
    console.print()
    console.print(
        f"  [green]{n_clean} clean[/]  "
        f"[yellow]{n_warn} flagged[/]  "
        f"[dim]{len(results)} total[/]"
    )
    _pause()

def do_verify(tracked):
    stem = pick_tracked(tracked, "Pick a clip to re-verify")
    if not stem: return
    _run(SCRIPT_VERIFY, "--stem", stem); _pause()

def do_render(tracked):
    stem = pick_tracked(tracked, "Pick a clip to render")
    if not stem: return
    _run(SCRIPT_COMBINED, "--stem", stem); _pause()

# ── Analyze ──
def do_analyze(tracked):
    stem = pick_tracked(tracked, "Pick a clip to analyze")
    if not stem: return
    _run(SCRIPT_ANALYZE, stem); _pause()

def do_poincare(tracked):
    stem = pick_tracked(tracked, "Pick a clip for Poincar\u00e9")
    if not stem: return
    _run(SCRIPT_POINCARE, "--stem", stem); _pause()

def do_lyapunov(tracked):
    stem = pick_tracked(tracked, "Pick a clip for \u03bb\u2081")
    if not stem: return
    _run(SCRIPT_LYAPUNOV, "--stem", stem); _pause()

def do_driven_poincare(tracked):
    stem = pick_tracked(tracked, "Pick a clip for driven Poincar\u00e9")
    if not stem: return
    _run(SCRIPT_DRIVEN_POIN, "--stem", stem); _pause()

def do_driven_bifurcation():
    _run(SCRIPT_DRIVEN_BIF, "--sweep", "vd"); _pause()

def do_quick_insights(tracked):
    stem = pick_tracked(tracked, "Pick a clip to explore")
    if not stem: return
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    from quick_insights import explore
    explore(stem)

# ── Figures ──
def do_figures():
    _run(SCRIPT_BATCH_FIGS); _pause()

def do_figures_single(tracked):
    stem = pick_tracked(tracked, "Pick a clip for figures")
    if not stem: return
    _run(SCRIPT_BATCH_FIGS, "--stem", stem); _pause()

def do_figures_with_video():
    _run(SCRIPT_BATCH_FIGS, "--video"); _pause()

def do_figures_force():
    _run(SCRIPT_BATCH_FIGS, "--force"); _pause()

def do_figures_preview(tracked):
    stem = pick_tracked(tracked, "Pick a clip to preview")
    if not stem: return
    _run(os.path.join(REPO_ROOT, "scripts", "analysis", "preview_frame.py"),
         "--stem", stem); _pause()

# ── Info ──
def do_status(tracked, pending):
    console.print()
    render_status_panels(tracked, pending)
    _pause()

def do_export():
    _run(SCRIPT_REPORT); _pause()

def do_roadmap():
    _run(SCRIPT_ROADMAP); _pause()

def do_switch_phase():
    console.print()
    console.print("  [bold]Switch phase[/]")
    console.print()
    current = PHASE.replace("pendulum-", "").replace("week", "w")
    console.print(f"  Current: [cyan]{current}[/]")
    console.print()
    console.print("  Set in your shell before launching chaos:")
    console.print('  [dim]$env:CHAOS_PHASE = "week3-4-pendulum-free-swing"[/]')
    console.print('  [dim]$env:CHAOS_PHASE = "week5-6-pendulum-motor-driven"[/]')
    _pause()

def do_help():
    _run(sys.executable, os.path.join(REPO_ROOT, "chaos.py"), "help"); _pause()


# ─────────────────────────────────────────────
# HUB LOOP
# ─────────────────────────────────────────────

EXPANDED_DISPATCH = {
    # track
    "n": lambda tr, pe: do_track_next(pe),
    "p": lambda tr, pe: do_pick_and_track(pe),
    "b": lambda tr, pe: do_bulk(),
    "x": lambda tr, pe: do_sanity_check(tr),
    "k": lambda tr, pe: do_sanity_sweep(tr),
    "v": lambda tr, pe: do_verify(tr),
    "r": lambda tr, pe: do_render(tr),
    # analyze
    "c": lambda tr, pe: do_analyze(tr),
    "o": lambda tr, pe: do_poincare(tr),
    "l": lambda tr, pe: do_lyapunov(tr),
    "d": lambda tr, pe: do_driven_poincare(tr),
    "i": lambda tr, pe: do_driven_bifurcation(),
    "qi": lambda tr, pe: do_quick_insights(tr),
    # info
    "s": lambda tr, pe: do_status(tr, pe),
    "e": lambda tr, pe: do_export(),
    "m": lambda tr, pe: do_roadmap(),
    "w": lambda tr, pe: do_switch_phase(),
    "h": lambda tr, pe: do_help(),
}


def hub():
    expanded = True
    try:
        while True:
            console.clear()
            tracked, pending = get_clips()
            render_hub(tracked, pending, expanded=expanded)

            try:
                raw = input("  \u25b8 ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if not raw:
                continue

            # Toggle expand/collapse
            if raw in ("+", "-", "="):
                expanded = not expanded
                continue

            key = raw[:2] if raw[:2] in ("fa", "fs", "fv", "ff", "fp", "qi") else raw[0]

            if key == "q":
                break
            elif expanded:
                handler = EXPANDED_DISPATCH.get(key)
                if handler:
                    handler(tracked, pending)
                elif key == "fa": do_figures()
                elif key == "fs": do_figures_single(tracked)
                elif key == "fv": do_figures_with_video()
                elif key == "ff": do_figures_force()
                elif key == "fp": do_figures_preview(tracked)
                else:
                    console.print(f"  [dim]Unknown key: {key}[/]")
                    import time; time.sleep(0.5)
            else:
                if key == "t": submenu_track(tracked, pending)
                elif key == "a": submenu_analyze(tracked)
                elif key == "f": submenu_figures(tracked)
                elif key == "s": submenu_info(tracked, pending)
                else:
                    console.print(f"  [dim]Unknown key: {key}[/]")
                    import time; time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    console.print("\n  [dim]bye.[/]")


if __name__ == "__main__":
    hub()
