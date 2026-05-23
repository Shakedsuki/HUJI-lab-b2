"""
shell.py — interactive hub for the chaos pipeline.

Launched by bare ``chaos`` (no subcommand). Presents a compact
dashboard with single-key dispatch to all major pipeline actions.
Uses questionary for arrow-key clip pickers and Rich for formatting.

All commands use a consistent prefix system:
  t* = track, a* = analyze, f* = figures, v* = videos
"""

import json, os, subprocess, sys
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError): pass

import questionary
from questionary import Choice, Separator
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich.live import Live
from rich import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT, PHASE, PHASE_DRIVEN, clip_dir

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
SCRIPT_ROTATIONS   = os.path.join(REPO_ROOT, "scripts", "analysis", "rotations.py")
SCRIPT_DIMENSION   = os.path.join(REPO_ROOT, "scripts", "analysis", "dimension.py")
SCRIPT_OVERLAY     = os.path.join(REPO_ROOT, "scripts", "analysis", "overlay_video.py")

CLR_TRACK   = "green"
CLR_ANALYZE = "yellow"
CLR_OUTPUT  = "#FF6B35"
CLR_FIGURES = "#FF3D6B"
CLR_VIDEOS  = "#38BDF8"
CLR_INFO    = "cyan"
CLR_SYSTEM  = "dim"

AUTHOR_NAME  = "Shaked Sukiennik"
AUTHOR_EMAIL = "shaked.sukiennik@mail.huji.ac.il"

_activity_log = []
def _log_activity(msg):
    _activity_log.append(msg)
    if len(_activity_log) > 8: _activity_log.pop(0)

WEEK_GROUPS = {
    "week5": {"label": "week 5", "desc": "broad V/f survey",     "color": "cyan"},
    "week6": {"label": "week 6", "desc": "3.2V resonance sweep", "color": "yellow"},
}

LOGO = (
    "[bold magenta]\u250c\u2500\u2510 \u252c \u252c \u250c\u2500\u2510 \u250c\u2500\u2510 \u250c\u2500\u2510[/]\n"
    "[bold magenta]\u2502   \u251c\u2500\u2524 \u251c\u2500\u2524 \u2502 \u2502 \u2514\u2500\u2510[/]\n"
    "[bold magenta]\u2514\u2500\u2518 \u2534 \u2534 \u2534 \u2534 \u2514\u2500\u2518 \u2514\u2500\u2518[/]"
)

# ── Data ──

def load_registry():
    if not os.path.exists(EXPERIMENTS): return {}
    try:
        with open(EXPERIMENTS, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return {}

def _resolve_entry(stem, reg):
    if stem in reg: return reg[stem]
    for e in reg.values():
        if e.get("config_description") == stem: return e
        if Path(e.get("video_file","")).stem == stem: return e
    return None

def _is_tracked(entry, stem):
    if not entry: return False
    csv = os.path.join(clip_dir(stem), entry.get("csv_file", "tracking.csv"))
    return os.path.isfile(csv)

def _week_bucket(stem):
    if PHASE != PHASE_DRIVEN: return None
    return "week6" if stem.startswith("3.2V_") and stem != "3.2V_1Hz" else "week5"

def get_clips():
    reg = load_registry()
    by_vid = {e.get("video_file"): e for e in reg.values() if e.get("video_file")}
    tracked, pending = [], []
    if os.path.isdir(VIDEOS_DIR):
        for name in sorted(os.listdir(VIDEOS_DIR), key=str.lower):
            if not os.path.isfile(os.path.join(VIDEOS_DIR, name)): continue
            if Path(name).suffix.lower() not in VIDEO_EXTS: continue
            stem = Path(name).stem
            entry = by_vid.get(name) or _resolve_entry(stem, reg)
            cfg = entry.get("config_description", stem) if entry else stem
            info = {"stem": cfg, "video": name, "week": _week_bucket(cfg),
                    "drive_voltage_v": (entry or {}).get("drive_voltage_v"),
                    "drive_freq_hz": (entry or {}).get("drive_freq_hz"),
                    "dropout_pct": (entry or {}).get("dropout_rate_pct"),
                    "duration_s": (entry or {}).get("duration_s"),
                    "quality": (entry or {}).get("tracking_quality")}
            if entry and _is_tracked(entry, cfg):
                info["status"] = entry.get("tracking_quality", "tracked"); tracked.append(info)
            else:
                info["status"] = "pending"; pending.append(info)
    return tracked, pending

# ── Overlay helpers ──

def _overlay_path(stem):
    return os.path.join(clip_dir(stem), f"{stem}_overlay.mp4")

def _has_overlay(stem):
    target = _overlay_path(stem)
    if os.path.isfile(target):
        return True
    legacy = os.path.join(clip_dir(stem), "overlay.mp4")
    if os.path.isfile(legacy):
        os.rename(legacy, target)
        return True
    return False

def _open_file(path):
    import platform
    s = platform.system()
    if s == "Windows":  os.startfile(path)
    elif s == "Darwin": subprocess.Popen(["open", path])
    else:               subprocess.Popen(["xdg-open", path])

def _get_verdict(stem, reg=None):
    if reg is None: reg = load_registry()
    for e in reg.values():
        if e.get("config_description") == stem:
            return e.get("overlay_verdict")
    return None

def _set_verdict(stem, verdict, note=None):
    """Set, or (verdict=None) clear, a clip's overlay verdict + note."""
    reg = load_registry()
    for k, e in reg.items():
        if e.get("config_description") == stem:
            if verdict is None:
                e.pop("overlay_verdict", None)
                e.pop("overlay_verdict_note", None)
            else:
                e["overlay_verdict"] = verdict
                if note: e["overlay_verdict_note"] = note
                elif "overlay_verdict_note" in e: del e["overlay_verdict_note"]
            break
    with open(EXPERIMENTS, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, ensure_ascii=False)

def _group_by_week(clips):
    groups, order = {}, []
    for c in clips:
        wk = c.get("week")
        if wk not in groups: groups[wk] = []; order.append(wk)
        groups[wk].append(c)
    return [(k, groups[k]) for k in order]

# ── Rendering ──

def _bar(nv, nt, total, w=30):
    if total == 0: return "[dim]no clips[/]"
    uv = nt - nv; wv = int(round(nv/total*w)); wt = int(round(uv/total*w)); wp = w-wv-wt
    return f"[green]{'\u2588'*wv}[/][yellow]{'\u2588'*wt}[/][dim]{'\u2591'*wp}[/]"

def _card(title, color, items):
    lines = [f"  [{color} bold]{k:<3}[/] {l}" for k, l in items]
    return Panel(Text.from_markup("\n".join(lines)), title=f"[bold]{title}[/]",
                 border_style=color, padding=(0,0), expand=True)

def render_hub(tracked, pending, expanded=True):
    total = len(tracked) + len(pending)
    nv = sum(1 for c in tracked if c.get("quality") == "verified")
    nt = len(tracked); nu = nt - nv; np_ = len(pending)
    bar = _bar(nv, nt, total)
    legend = f"[green]{nv} verified[/] [dim]\u00b7[/] [yellow]{nu} tracked[/] [dim]\u00b7 {np_} pending[/]"
    phase_label = PHASE.replace("pendulum-","").replace("week","w")
    logo_block = Text.from_markup(
        f"{LOGO}\n[dim]double pendulum[/]\n[dim italic]{phase_label}[/]")
    # Drop the bar + counts down so they sit on the double-pendulum / phase rows.
    pad = "\n" * (LOGO.count("\n") + 1)
    info_right = Text.from_markup(
        f"{pad}{bar}  [bold]{nt}[/][dim]/{total}[/]\n{legend}")
    hdr_tbl = Table(box=None, show_header=False, padding=(0,1), expand=True)
    hdr_tbl.add_column(width=20); hdr_tbl.add_column(ratio=1)
    hdr_tbl.add_row(logo_block, info_right)
    header = hdr_tbl

    if expanded:
        ct = _card("track", CLR_TRACK, [("t","track · status")])
        ca = _card("analyze", CLR_ANALYZE, [
            ("a","analyze"),("aq","quick insights"),("g","gallery"),
            ("ai","bifurcation"),("ar","rotations")])
        r1 = Table(box=None, show_header=False, expand=True, padding=(0,1))
        r1.add_column(ratio=1); r1.add_column(ratio=1); r1.add_row(ct, ca)

        cf = _card("figures", CLR_FIGURES, [("fi","inventory · render")])
        cv = _card("videos", CLR_VIDEOS, [("vi","render · review")])
        ir = Table(box=None, show_header=False, expand=True, padding=(0,1))
        ir.add_column(ratio=1); ir.add_column(ratio=1); ir.add_row(cf, cv)
        co = Panel(ir, title="[bold]output[/]", border_style=CLR_OUTPUT, padding=(0,0), expand=True)

        # Bottom row: info + system + contact
        ic = Text.from_markup(
            f" [{CLR_INFO} bold]sw[/] switch   [{CLR_INFO} bold]p[/] paths\n"
            f" [{CLR_INFO} bold]c[/]  calibrate")
        sc = Text.from_markup(
            f" [{CLR_SYSTEM} bold]q[/] quit\n [{CLR_SYSTEM} bold]h[/] help\n [{CLR_SYSTEM} bold]-[/] fold")
        cc = Text.from_markup(
            f" [dim]Shaked.Sukiennik[/]\n"
            f" [dim]@mail.huji.ac.il[/]\n"
            f" [dim]\u00a9 2026 HUJI[/]")
        pi = Panel(ic, title="[bold]info[/]", border_style=CLR_INFO, padding=(0,0), expand=True)
        ps = Panel(sc, title="[bold]system[/]", border_style=CLR_SYSTEM, padding=(0,0), expand=True)
        pc = Panel(cc, title="[bold]contact[/]", border_style="dim", padding=(0,0), expand=True)
        r3 = Table(box=None, show_header=False, expand=True, padding=(0,1))
        r3.add_column(ratio=3); r3.add_column(ratio=2); r3.add_column(ratio=3)
        r3.add_row(pi, ps, pc)

        body = Group(header, Text(""), r1, co, r3)
    else:
        actions = Text.from_markup(
            f"    [{CLR_TRACK} bold]t[/]  track          [dim]\u2192 track \u00b7 status table[/]\n"
            f"    [{CLR_ANALYZE} bold]a[/]  analyze        [dim]\u2192 c p l d r \u00b7 b s \u00b7 explore[/]\n"
            f"    [{CLR_OUTPUT}]o[/]  output         [dim]\u2192 fi vi[/]\n"
            f"    [{CLR_INFO} bold]s[/]  info           [dim]\u2192 s e sw p[/]")
        footer = Text.from_markup("  [dim]q quit    h help    + expand[/]")
        body = Group(header, Text(""), actions, Text(""), footer)

    console.print(Panel(body, border_style="magenta", padding=(0,2), width=min(console.width, 76)))

# ── Pickers ──

_PICKER_STYLE = None
def _sty():
    global _PICKER_STYLE
    if _PICKER_STYLE is None:
        from prompt_toolkit.styles import Style as S
        _PICKER_STYLE = S([("qmark","fg:#fbbf24 bold"),("question","bold"),
            ("pointer","fg:#22d3ee bold"),("highlighted","fg:#5eead4 bold"),("selected","fg:#5eead4")])
    return _PICKER_STYLE

BACK = "__back__"; SWEEP = "__sweep__"

def _choices(clips, extra=None):
    ch = [Choice("\u2190 back", value=BACK)]
    if extra: ch.extend(extra)
    for wk, gc in _group_by_week(clips):
        m = WEEK_GROUPS.get(wk)
        if m: ch.append(Separator(f"\u2500\u2500 {m['label']} \u00b7 {m['desc']} ({len(gc)}) \u2500\u2500"))
        for i, c in enumerate(gc):
            br = "\u2570\u2500" if i==len(gc)-1 else "\u251c\u2500"
            vd, fd = c.get("drive_voltage_v"), c.get("drive_freq_hz")
            ex = f"  {vd}V {fd}Hz" if vd and fd else ""
            ch.append(Choice(f" {br} {c['stem']:<20}{ex}", value=c["stem"]))
    return ch

def _pick_collapsible(clips, label, extra=None):
    """Single-select picker with collapsible week groups: groups start
    collapsed; Enter on a header expands/collapses it, so a whole group can
    be skipped with one keypress. Falls back to a flat list when there is
    only one named group. Returns a stem, an extra value, or None."""
    if not clips:
        console.print("  [dim]No clips available.[/]"); return None
    groups = _group_by_week(clips)
    named = [wk for wk, _ in groups if WEEK_GROUPS.get(wk)]
    if len(named) < 2:
        try:
            r = questionary.select(label, choices=_choices(clips, extra), style=_sty(),
                                   use_arrow_keys=True, use_jk_keys=True).ask()
        except KeyboardInterrupt: return None
        return None if r is None or r == BACK else r
    expanded, default = set(), None
    while True:
        ch = [Choice("← back", value=BACK)]
        if extra: ch.extend(extra)
        for wk, gc in groups:
            m = WEEK_GROUPS.get(wk, {"label": wk or "clips", "desc": ""})
            arrow = "▾" if wk in expanded else "▸"
            ch.append(Choice(f" {arrow} {m['label']} · {m['desc']} ({len(gc)})",
                             value=f"__tg__{wk}"))
            if wk in expanded:
                for i, c in enumerate(gc):
                    br = "╰─" if i == len(gc) - 1 else "├─"
                    vd, fd = c.get("drive_voltage_v"), c.get("drive_freq_hz")
                    ex = f"  {vd}V {fd}Hz" if vd and fd else ""
                    ch.append(Choice(f"   {br} {c['stem']:<20}{ex}", value=c["stem"]))
        try:
            r = questionary.select(label, choices=ch, style=_sty(), use_arrow_keys=True,
                                   use_jk_keys=True, default=default).ask()
        except KeyboardInterrupt: return None
        if r is None or r == BACK: return None
        if isinstance(r, str) and r.startswith("__tg__"):
            wk = r[len("__tg__"):]
            if wk in expanded: expanded.discard(wk)
            else: expanded.add(wk)
            default = r
            continue
        return r

def pick_clip(clips, label="Pick a clip"):
    return _pick_collapsible(clips, label)

def pick_or_sweep(clips, label="Sanity check"):
    return _pick_collapsible(clips, label, extra=[Choice("\u2261 sweep all", value=SWEEP)])

def pick_t(tr, label="Pick a clip"): return pick_clip(tr, label)
def pick_p(pe, label="Pick a clip to track"): return pick_clip(pe, label)

# ── Navigable tables (overview → arrow-key drill-down) ──

def _read_key():
    """Block for one keypress; return a normalized token: 'up','down','left',
    'right','enter','esc','home','end','pageup','pagedown', or the lowercased
    character. Raises KeyboardInterrupt on Ctrl-C."""
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right",
                    "G": "home", "O": "end", "I": "pageup", "Q": "pagedown"}.get(code, "")
        if ch == "\r": return "enter"
        if ch == "\x1b": return "esc"
        if ch == "\x03": raise KeyboardInterrupt
        return ch.lower()
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left",
                    "[H": "home", "[F": "end", "[5": "pageup", "[6": "pagedown"}.get(seq, "esc")
        if ch in ("\r", "\n"): return "enter"
        if ch == "\x03": raise KeyboardInterrupt
        return ch.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def _resolve(x):
    return x() if callable(x) else x

class _NavCtx:
    """Handed to navigate_table key handlers. ctx.suspend(fn) pauses the live
    display so fn() can prompt on a normal terminal, then resumes."""
    def __init__(self, live): self._live = live
    def suspend(self, fn):
        if self._live is not None: self._live.stop()
        try:
            return fn()
        finally:
            if self._live is not None: self._live.start(refresh=False)

def navigate_table(build_rows, columns, *, title="", border_style="cyan",
                   key_actions=None, legend=None, hint=None,
                   empty_msg="Nothing here.", selected_bg="grey23",
                   col_targets=None, col_actions=None, col_hint=None,
                   cell_targets=None, cell_actions=None, cell_hint=None,
                   preview_fn=None):
    """Arrow-key navigable Rich table — land on the overview, drill into a row.

    Renders through rich.Live on the alternate screen, so arrow-key movement
    updates in place with no full-screen clear()/reprint flicker.

    build_rows()  -> list[dict]; re-called every frame so the table tracks live
                     state (filters, registry edits).
    columns       -> list of (header, render_fn, col_kwargs); render_fn(row)
                     returns Rich-markup text for one cell.
    key_actions   -> {key_token: handler(row, rows, idx, ctx)} in ROW mode;
                     handler returns "advance" (move down), "top" (jump first),
                     "quit", or None/"stay". row is None when empty; ctx.suspend
                     (fn) pauses the display for a prompt / shelled-out renderer.

    Column mode (opt-in, for matrices): pass col_targets = list of caller-column
    indices that are column-operable. Then 'c' enters column mode (←→ pick a
    column, the column is highlighted), 'r' returns to row mode (idempotent),
    and col_actions = {key_token: handler(col_pos, rows, ctx)} fire there, where
    col_pos indexes col_targets. col_hint replaces hint while in column mode.

    title/legend/hint may be plain strings or zero-arg callables.
    Up/Down (k/j), PgUp/PgDn, Home/End, q/Esc are handled internally."""
    key_actions = key_actions or {}
    col_actions = col_actions or {}
    cell_actions = cell_actions or {}
    cell_targets = cell_targets or col_targets
    has_cols = bool(col_targets)
    has_cells = bool(cell_targets)
    idx, cidx, mode = 0, 0, "row"

    def frame():
        nonlocal idx, cidx
        rows = build_rows()
        n = len(rows)
        idx = max(0, min(idx, n - 1)) if n else 0
        _active = cell_targets if mode == "cell" else col_targets
        if _active: cidx = max(0, min(cidx, len(_active) - 1))
        avail = max(5, console.height - 10)
        if n <= avail:
            lo, hi = 0, n
        else:
            lo = max(0, min(idx - avail // 2, n - avail)); hi = lo + avail
        ncol = len(columns)
        sel_col = col_targets[cidx] if (has_cols and mode == "col") else None
        cell_col = cell_targets[cidx] if (has_cells and mode == "cell") else None
        t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=False)
        t.add_column(" ", width=2)
        for p, (header, _rf, kw) in enumerate(columns):
            if p == sel_col:
                kw = {**kw, "style": f"on {selected_bg}", "header_style": f"bold on {selected_bg}"}
            t.add_column(header, **kw)
        if n == 0:
            t.add_row(" ", f"[dim]{empty_msg}[/]", *[""] * (ncol - 1))
        else:
            if lo > 0: t.add_row(" ", "[dim]↑…[/]", *[""] * (ncol - 1))
            for i in range(lo, hi):
                cells = [rf(rows[i]) for _h, rf, _k in columns]
                if mode == "cell" and i == idx:
                    if cell_col is not None:
                        cells[cell_col] = f"[bold black on bright_cyan]{cells[cell_col]}[/]"
                    t.add_row("[bold cyan]▸[/]", *cells, style=f"on {selected_bg}")
                elif mode == "row" and i == idx:
                    t.add_row("[bold cyan]▸[/]", *cells, style=f"on {selected_bg}")
                else:
                    t.add_row(" ", *cells)
            if hi < n: t.add_row(" ", "[dim]↓…[/]", *[""] * (ncol - 1))
        body = [t]
        leg = _resolve(legend)
        if leg: body.append(Text.from_markup("  " + leg))
        panel = Panel(Group(*body), title=f"[bold]{_resolve(title)}[/]",
                      border_style=border_style, padding=(0, 1),
                      expand=(preview_fn is None))
        main = panel
        if preview_fn is not None:
            try: prev = preview_fn(rows[idx] if n else None)
            except Exception: prev = None
            if prev is not None:
                lay = Table(box=None, show_header=False, expand=True, padding=(0, 1))
                lay.add_column(); lay.add_column(ratio=1)
                lay.add_row(panel, prev)
                main = lay
        if mode == "cell" and cell_hint: h = _resolve(cell_hint)
        elif mode == "col" and col_hint:  h = _resolve(col_hint)
        else:                             h = _resolve(hint)
        renderable = Group(main, Text.from_markup("  " + h)) if h else main
        return rows, n, avail, renderable

    rows, n, avail, renderable = frame()
    with Live(renderable, console=console, screen=True, auto_refresh=False) as live:
        ctx = _NavCtx(live)
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                break
            if key in ("q", "esc"): break
            if mode == "col":
                if key in ("left", "h"): cidx -= 1
                elif key in ("right", "l"): cidx += 1
                elif key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key in ("r", "c"): mode = "row"
                else:
                    act = col_actions.get(key)
                    if act and act(cidx, rows, ctx) == "quit": break
            elif mode == "cell":
                if key in ("left", "h"): cidx -= 1
                elif key in ("right", "l"): cidx += 1
                elif key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key in ("r", "e"): mode = "row"
                else:
                    act = cell_actions.get(key)
                    if act and act(rows[idx] if n else None, cidx, ctx) == "quit": break
            else:
                if key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key == "home": idx = 0
                elif key == "end": idx = n - 1
                elif key == "pageup": idx -= avail
                elif key == "pagedown": idx += avail
                elif has_cols and key == "c": mode = "col"; cidx = 0
                elif has_cells and key == "e": mode = "cell"; cidx = 0
                elif has_cols and key == "r": pass
                else:
                    act = key_actions.get(key)
                    if act:
                        res = act(rows[idx] if n else None, rows, idx, ctx)
                        if res == "quit": break
                        if res == "advance": idx += 1
                        elif res == "top": idx = 0
            rows, n, avail, renderable = frame()
            live.update(renderable, refresh=True)

def _ask_confirm(question, default=False):
    """Single-keypress y/n confirm on the current (suspended) screen → bool.
    y = yes, enter = the default, anything else (n/esc/q) = no."""
    console.print()
    console.print(Panel(Text.from_markup(question), title="[bold yellow]confirm[/]",
                        border_style="yellow", padding=(0, 1), expand=False))
    console.print(f"  [green bold]y[/]es   [bold]n[/]o   [dim](enter = {'yes' if default else 'no'}, esc cancels)[/]")
    try:
        k = _read_key()
    except KeyboardInterrupt:
        return False
    if k == "y": return True
    if k == "enter": return default
    return False

def _do_suspended(ctx, work, pause=True, confirm=None, confirm_default=False):
    """Pause the live table, run work() on the normal terminal, optionally wait
    for a keypress, then resume. If confirm is given, ask y/n first and skip
    work() unless confirmed. For row/column actions that shell out to a renderer."""
    def go():
        if confirm and not _ask_confirm(confirm, default=confirm_default):
            return
        work()
        if pause: _pause()
    ctx.suspend(go)

# ── Submenus (collapsed) ──

def _sub(title, actions):
    console.print(); console.print(f"  [bold]{title}[/]"); console.print(Rule(style="dim"))
    for k, l, d, c in actions:
        console.print(f"  [{c} bold]{k:<3}[/] {l:<18} [dim]{d}[/]")
    console.print(f"  [dim bold]\u2190[/]  [dim]back[/]"); console.print(Rule(style="dim"))
    try: k = input("  \u25b8 ").strip().lower()
    except (EOFError, KeyboardInterrupt): return None
    return k if k else None

def sub_output(tr, pe):
    k = _sub("output", [("fi","figures","inventory · render",CLR_FIGURES),
        ("vi","videos","render · review · inventory",CLR_VIDEOS)])
    if not k: return
    {"fi":lambda:do_fi(tr),"vi":lambda:do_vi(tr)}.get(k[:2],lambda:None)()

def sub_info(tr, pe):
    k = _sub("info", [("sw","switch","phase",CLR_INFO),
        ("p","paths","config",CLR_INFO),("c","calibration","pivot & arm",CLR_INFO)])
    if not k: return
    {"sw":do_w,"p":do_p,"c":do_c}.get(k,lambda:None)()

# ── Actions ──

def _run(script, *args):
    return subprocess.run([sys.executable, script, *map(str, args)], cwd=REPO_ROOT).returncode

def _pause():
    console.print()
    try: questionary.press_any_key_to_continue("press any key to return...").ask()
    except KeyboardInterrupt: pass

# Track + status
def do_t(tr, pe):
    """Track + status — one table over all clips. Row keys act on the highlighted
    clip: t track / re-track, v verify, s sanity, o overlay. b = bulk-track all
    pending. Filters: 1 all · 2 pending · 3 tracked."""
    state = {"filter": "all"}
    def build_rows():
        tr2, pe2 = get_clips()
        rows = [{"stem": c["stem"], "status": c["status"],
                 "dropout": c.get("dropout_pct"), "dur": c.get("duration_s")}
                for c in (tr2 + pe2)]
        f = state["filter"]
        if f == "pending":    rows = [r for r in rows if r["status"] == "pending"]
        elif f == "tracked":  rows = [r for r in rows if r["status"] != "pending"]
        elif f == "verified": rows = [r for r in rows if r["status"] == "verified"]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    def _scell(r):
        s = r["status"]
        if s == "pending":  return "[yellow]pending[/]"
        if s == "verified": return "[green]verified[/]"
        return f"[cyan]{s}[/]"
    def _pct(r): return f"{r['dropout']:.1f}%" if r["dropout"] is not None else "[dim]—[/]"
    def _dur(r): return f"{r['dur']:.1f}s" if r["dur"] is not None else "[dim]—[/]"
    columns = [
        ("#",       lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
        ("clip",    lambda r: r["stem"],    dict(min_width=16, no_wrap=True)),
        ("status",  _scell,                 dict(width=9)),
        ("dropout", _pct,                   dict(justify="right", width=8)),
        ("dur",     _dur,                   dict(justify="right", width=7)),
    ]
    def legend():
        tr2, pe2 = get_clips()
        nv = sum(1 for c in tr2 if c.get("quality") == "verified")
        return (f"[green]{nv} verified[/]  [cyan]{len(tr2) - nv} tracked[/]  [yellow]{len(pe2)} pending[/]"
                f"   [dim]·[/]   filter: [bold]{state['filter']}[/]")
    hint = ("[dim]↑↓[/] [bold]t[/] track/re-track   [bold]v[/] verify   [bold]s[/] sanity   "
            "[bold]o[/] overlay   [bold]b[/] bulk-pending   [bold]1[/]/[bold]2[/]/[bold]3[/] filter   [bold]q[/] back")
    def act_track(row, rows, i, ctx):
        if not row: return
        stem = row["stem"]
        if row["status"] == "pending":
            _do_suspended(ctx, lambda: _run(SCRIPT_TRACK_ONE, "--stem", stem)); _log_activity(f"tracked {stem}")
        else:
            _do_suspended(ctx, lambda: _run(SCRIPT_TRACK_ONE, "--stem", stem, "--force"),
                          confirm=f"Re-track [bold]{stem}[/]? Overwrites existing tracking.")
    def act_verify(row, rows, i, ctx):
        if row and row["status"] != "pending":
            _do_suspended(ctx, lambda: _run(SCRIPT_VERIFY, "--stem", row["stem"])); _log_activity(f"verified {row['stem']}")
    def act_sanity(row, rows, i, ctx):
        if not row: return
        def work():
            sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
            from sanity_check import check_one
            try: check_one(row["stem"])
            except Exception as e: console.print(f"  [red]ERROR:[/] {e}")
        _do_suspended(ctx, work)
    def act_open(row, rows, i, ctx):
        if row and _has_overlay(row["stem"]):
            try: _open_file(_overlay_path(row["stem"]))
            except Exception: pass
    def act_bulk(row, rows, i, ctx):
        _, pe2 = get_clips()
        if not pe2:
            _do_suspended(ctx, lambda: console.print("  [green]Nothing pending.[/]")); return
        def work(): _run(SCRIPT_BULK); _log_activity("bulk done")
        _do_suspended(ctx, work, confirm=f"Bulk-track all [bold]{len(pe2)}[/] pending clips?")
    def mkfilter(val):
        def _f(row, rows, i, ctx): state["filter"] = val; return "top"
        return _f
    pcache = {}
    def preview(row):
        if not row: return None
        stem = row["stem"]
        if stem not in pcache:
            ph = max(6, (console.height - 28) // 2)
            pw = max(44, console.width - 78)
            try:
                sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
                from sanity_check import build_one
                verdict, txt = build_one(stem, plot_width=pw, plot_height=ph)
                pcache[stem] = (verdict, Text.from_ansi(txt))
            except Exception as e:
                pcache[stem] = ("?", Text.from_markup(f"[red]sanity unavailable:[/] {e}"))
        verdict, ptxt = pcache[stem]
        vc = {"CLEAN": "green", "WARN": "yellow", "REVIEW": "red"}.get(verdict, "dim")
        return Panel(ptxt, title=f"[bold]sanity[/] [dim]·[/] [{vc}]{verdict}[/]",
                     border_style=CLR_TRACK, padding=(0, 1))
    navigate_table(build_rows, columns, title="track · status", border_style=CLR_TRACK,
                   legend=legend, hint=hint, empty_msg="No clips match this filter.", preview_fn=preview,
                   key_actions={"t": act_track, "v": act_verify, "s": act_sanity, "o": act_open,
                                "b": act_bulk,
                                "1": mkfilter("all"), "2": mkfilter("pending"), "3": mkfilter("tracked")})
    _log_activity("track/status")

# Analyze
ANALYZE_TYPES = [
    ("chaos_analyze", "chaos",  "chaos card"),
    ("poincare",      "poinc",  "poincar\u00e9"),
    ("lyapunov",      "lyap",   "lyapunov"),
    ("driven",        "driven", "driven poincar\u00e9"),
    ("rotations",     "rot",    "rotations"),
    ("dimension",     "dim",    "fractal dimension"),
]

def _analyze_exists(tn, stem):
    if tn == "driven":    return os.path.isfile(os.path.join(clip_dir(stem), "driven_poincare.csv"))
    if tn == "rotations": return os.path.isfile(os.path.join(clip_dir(stem), "rotations.json"))
    if tn == "dimension": return os.path.isfile(os.path.join(clip_dir(stem), "dimension.json"))
    return _fig_exists(tn, stem)

def do_a(tr):
    """Analyze \u2014 navigate clips; row keys run a per-clip analysis on the
    highlighted clip; the \u2713/\u00b7 columns show what's already been computed.
    Aggregate sweeps (bifurcation, rotations) act on the whole family."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    fstate = {"gaps": False}
    def _runclip(ctx, *args):
        _do_suspended(ctx, lambda: _run(*args))
    def act_chaos(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_ANALYZE, row["stem"]); _log_activity(f"chaos {row['stem']}")
    def act_poin(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_POINCARE, "--stem", row["stem"])
    def act_lyap(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_LYAPUNOV, "--stem", row["stem"])
    def act_driven(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_DRIVEN_POIN, "--stem", row["stem"])
    def act_rot(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_ROTATIONS, "--stem", row["stem"]); _log_activity(f"rotations {row['stem']}")
    def act_dim(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_DIMENSION, "--stem", row["stem"]); _log_activity(f"dimension {row['stem']}")
    def act_explore(row, rows, i, ctx):
        if not row: return
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
        from quick_insights import explore
        _do_suspended(ctx, lambda: explore(row["stem"]), pause=False)
    def act_bif(row, rows, i, ctx):
        def work(): _run(SCRIPT_DRIVEN_BIF, "--sweep", "vd"); _log_activity("bifurcation sweep")
        _do_suspended(ctx, work, confirm="Run [bold]bifurcation sweep[/] (vd) across the family?")
    def act_rotsweep(row, rows, i, ctx):
        def work(): _run(SCRIPT_ROTATIONS, "--sweep"); _log_activity("rotations sweep")
        _do_suspended(ctx, work, confirm="Run [bold]rotations sweep[/] across the 3.2V family?")
    def toggle_gaps(row, rows, i, ctx):
        fstate["gaps"] = not fstate["gaps"]; return "top"
    hint = ("[dim]\u2191\u2193[/] run [bold]c[/]haos [bold]p[/]oinc [bold]l[/]yap [bold]d[/]riven [bold]r[/]ot [bold]f[/]rac   "
            "[bold]\u21b5[/] explore   [bold]b[/] bif-sweep [bold]s[/] rot-sweep   "
            "[bold]g[/] gaps   [bold]q[/] back")
    _inventory_nav(tr, "analyze", CLR_ANALYZE, ANALYZE_TYPES, _analyze_exists,
                   key_actions={"c": act_chaos, "p": act_poin, "l": act_lyap,
                                "d": act_driven, "r": act_rot, "f": act_dim,
                                "enter": act_explore, "x": act_explore,
                                "b": act_bif, "s": act_rotsweep, "g": toggle_gaps},
                   hint=hint, fstate=fstate)
    _log_activity("analyze")

def do_aq(tr):
    """Quick insights — pick a clip, drop into the interactive plot explorer."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    def build_rows():
        rows = [{"stem": c["stem"]} for c in tr]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    columns = [
        ("#",    lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
        ("clip", lambda r: r["stem"],    dict(min_width=16, no_wrap=True)),
    ]
    def act_explore(row, rows, i, ctx):
        if not row: return
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
        from quick_insights import explore
        _do_suspended(ctx, lambda: explore(row["stem"]), pause=False)
        _log_activity(f"insights {row['stem']}")
    navigate_table(build_rows, columns, title="quick insights", border_style=CLR_ANALYZE,
                   legend="[dim]interactive plot explorer (plotext REPL) — 12 views[/]",
                   hint="[dim]↑↓[/] move   [bold]↵[/] explore clip   [bold]q[/] back",
                   key_actions={"enter": act_explore, "x": act_explore})

def do_gallery(tr):
    """Gallery — clips on the left; the right pane fills with as many
    quick-insights plots as fit for the highlighted clip."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    def build_rows():
        rows = [{"stem": c["stem"]} for c in tr]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    columns = [
        ("#",    lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
        ("clip", lambda r: r["stem"],    dict(min_width=15, no_wrap=True)),
    ]
    pcache = {}
    def preview(row):
        if not row: return None
        stem = row["stem"]
        if stem not in pcache:
            pw = max(48, console.width - 32)
            mh = max(12, console.height - 6)
            try:
                sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
                from quick_insights import build_gallery
                txt = build_gallery(stem, width=pw - 4, plot_height=10, max_height=mh)
                pcache[stem] = Text.from_ansi(txt) if txt else Text.from_markup("[dim]no plots[/]")
            except Exception as e:
                pcache[stem] = Text.from_markup(f"[red]gallery unavailable:[/] {e}")
        return Panel(pcache[stem], title=f"[bold]gallery[/] [dim]·[/] {row['stem']}",
                     border_style=CLR_ANALYZE, padding=(0, 1))
    navigate_table(build_rows, columns, title="gallery", border_style=CLR_ANALYZE,
                   legend="[dim]quick-insights plot wall — ↑↓ to change clip[/]",
                   hint="[dim]↑↓[/] move   [bold]q[/] back", preview_fn=preview)
    _log_activity("gallery")

def do_ai():
    """Bifurcation — driven sweep (θ₁ vs drive voltage) across the family."""
    if not _ask_confirm("Run [bold]bifurcation sweep[/] (vd) across the family?"):
        return
    _run(SCRIPT_DRIVEN_BIF, "--sweep", "vd"); _log_activity("bifurcation sweep"); _pause()

def do_ar(tr):
    """Rotations — per-arm winding metrics across all clips (read from each
    clip's rotations.json). Row keys: c/↵ compute this clip, o open its figure;
    a recomputes every clip + the sweep aggregate."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    state = {"filter": "all"}
    def _load(stem):
        p = os.path.join(clip_dir(stem), "rotations.json")
        if not os.path.isfile(p): return None
        try:
            with open(p, encoding="utf-8") as f: return json.load(f)
        except Exception: return None
    def build_rows():
        rows = []
        for c in tr:
            r = _load(c["stem"])
            arms = (r or {}).get("arms", {})
            susp = any((arms.get(a) or {}).get("suspect") for a in arms)
            rows.append({"stem": c["stem"], "arms": arms, "has": r is not None, "susp": susp})
        f = state["filter"]
        if f == "suspect":   rows = [r for r in rows if r["susp"]]
        elif f == "missing": rows = [r for r in rows if not r["has"]]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    def _net(r, arm):
        m = r["arms"].get(arm); return f"{m['net_turns']:+.2f}" if m else "[dim]—[/]"
    def _loops(r, arm):
        m = r["arms"].get(arm); return f"{m['total_turns']:.0f}" if m else "[dim]—[/]"
    columns = [
        ("#",       lambda r: str(r["_n"]),         dict(justify="right", width=3, style="dim")),
        ("clip",    lambda r: r["stem"],            dict(min_width=15, no_wrap=True)),
        ("θ1 net",  lambda r: _net(r, "upper"),     dict(justify="right")),
        ("θ1 ↻",    lambda r: _loops(r, "upper"),   dict(justify="right", style="bold")),
        ("θ2 net",  lambda r: _net(r, "lower_abs"), dict(justify="right")),
        ("θ2 ↻",    lambda r: _loops(r, "lower_abs"),dict(justify="right", style="bold")),
        ("rel net", lambda r: _net(r, "lower_rel"), dict(justify="right")),
        ("rel ↻",   lambda r: _loops(r, "lower_rel"),dict(justify="right")),
        ("susp",    lambda r: "[yellow]⚠[/]" if r["susp"] else "", dict(justify="center", width=4)),
    ]
    def legend():
        nh = sum(1 for c in tr if _load(c["stem"]))
        return (f"[dim]{nh}/{len(tr)} computed[/]   [dim]·  ↻ = completed loops[/]"
                f"   [dim]·[/]   filter: [bold]{state['filter']}[/]")
    hint = ("[dim]↑↓[/] [bold]c[/]/[bold]↵[/] compute   [bold]o[/] figure   [bold]a[/] recompute all + sweep   "
            "[bold]1[/]/[bold]2[/]/[bold]3[/] all·suspect·missing   [bold]q[/] back")
    def act_compute(row, rows, i, ctx):
        if row:
            _do_suspended(ctx, lambda: _run(SCRIPT_ROTATIONS, "--stem", row["stem"]))
            _log_activity(f"rotations {row['stem']}")
    def act_fig(row, rows, i, ctx):
        if not row: return
        from paths import FIGURES_DIR
        p = os.path.join(FIGURES_DIR, "rotations", f"{row['stem']}_rotations.png")
        if os.path.isfile(p):
            try: _open_file(p)
            except Exception: pass
    def act_all(row, rows, i, ctx):
        def work(): _run(SCRIPT_ROTATIONS, "--sweep"); _log_activity("rotations sweep")
        _do_suspended(ctx, work, confirm=f"Recompute rotations + sweep across all {len(tr)} clips?")
    def mkfilter(val):
        def _f(row, rows, i, ctx): state["filter"] = val; return "top"
        return _f
    navigate_table(build_rows, columns, title="rotations · winding", border_style=CLR_ANALYZE,
                   legend=legend, hint=hint, empty_msg="No clips match this filter.",
                   key_actions={"c": act_compute, "enter": act_compute, "o": act_fig, "a": act_all,
                                "1": mkfilter("all"), "2": mkfilter("suspect"), "3": mkfilter("missing")})
    _log_activity("rotations")

# ── Inventory (navigable clip × type matrix) ──
def _fig_exists(ftype, stem):
    from paths import FIGURES_DIR
    return os.path.isfile(os.path.join(FIGURES_DIR, ftype, f"{stem}_{ftype}.png"))

def _vid_exists(vtype, stem):
    if vtype == "overlay":
        return os.path.isfile(_overlay_path(stem))
    from paths import ANIMATIONS_DIR
    return os.path.isfile(os.path.join(ANIMATIONS_DIR, vtype, f"{stem}_{vtype}.mp4"))

def _inventory_nav(tr, title, color, types, exists_fn, *, key_actions, hint, fstate,
                   on_col=None, on_col_force=None, col_hint=None,
                   on_view=None, cell_hint=None):
    """Navigable clip×type matrix. fstate is a mutable {'gaps': bool} filter.
    on_col(type_tuple, ctx) enables column mode ('c'): ←→ pick a type column, enter
    batches it across all clips (on_col_force = 'f'). on_view(stem, type_tuple, ctx)
    enables cell mode ('e'): ↑↓←→ pick one cell, 'v' views that file."""
    def build_rows():
        rows = []
        for c in tr:
            cells = {tn: exists_fn(tn, c["stem"]) for tn, _s, _d in types}
            rows.append({"stem": c["stem"], "cells": cells, "ndone": sum(cells.values())})
        if fstate.get("gaps"):
            rows = [r for r in rows if r["ndone"] < len(types)]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    columns = [("#", lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
               ("clip", lambda r: r["stem"], dict(min_width=16, no_wrap=True))]
    for tn, short, _d in types:
        columns.append((short,
            (lambda t: lambda r: "[green]✓[/]" if r["cells"][t] else "[dim]·[/]")(tn),
            dict(justify="center")))
    def legend():
        parts = [f"[bold]{short}[/] [dim]{sum(1 for c in tr if exists_fn(tn, c['stem']))}/{len(tr)}[/]"
                 for tn, short, _d in types]
        flt = "   [dim]·[/]   filter: [bold]gaps[/]" if fstate.get("gaps") else ""
        return "   ".join(parts) + flt
    col_targets = col_actions = cell_actions = None
    if on_col or on_view:
        col_targets = list(range(2, 2 + len(types)))   # the type columns, after #, clip
    if on_col:
        def col_enter(cpos, rows, ctx): on_col(types[cpos], ctx)
        col_actions = {"enter": col_enter}
        if on_col_force:
            def col_force(cpos, rows, ctx): on_col_force(types[cpos], ctx)
            col_actions["f"] = col_force
        if col_hint is None:
            col_hint = ("[bold cyan]column mode[/]   [dim]←→[/] pick type   [bold]↵[/] batch all clips"
                        + ("   [bold]f[/] force" if on_col_force else "")
                        + "   [bold]r[/] row mode   [bold]q[/] back")
    if on_view:
        def cell_view(row, cpos, ctx):
            if row: on_view(row["stem"], types[cpos], ctx)
        cell_actions = {"v": cell_view, "enter": cell_view}
        if cell_hint is None:
            cell_hint = ("[bold cyan]cell mode[/]   [dim]↑↓←→[/] pick cell   [bold]↵[/]/[bold]v[/] view file   "
                         "[bold]e[/]/[bold]r[/] row mode   [bold]q[/] back")
    navigate_table(build_rows, columns, title=title, border_style=color,
                   key_actions=key_actions, legend=legend, hint=hint,
                   empty_msg="No clips match this filter.",
                   col_targets=col_targets, col_actions=col_actions, col_hint=col_hint,
                   cell_actions=cell_actions, cell_hint=cell_hint)

# Figures
FIG_TYPES = [
    ("phase_panels",        "panels", "phase panels"),
    ("poincare",            "poinc",  "poincaré section"),
    ("phase_3d_trajectory", "3d",     "3D trajectory"),
    ("chaos_analyze",       "chaos",  "chaos card"),
    ("lyapunov",            "lyap",   "lyapunov"),
    ("seismograph_v1",      "seis1",  "seismograph v1 (spiral)"),
    ("seismograph_v2",      "seis2",  "seismograph v2 (ripple)"),
    ("dimension",           "dim",    "fractal dimension"),
]

def _pick_figtype(label="Figure type"):
    ch = [Choice("← back", value=BACK)]
    for tn, short, desc in FIG_TYPES:
        ch.append(Choice(f"  {tn}  ({desc})", value=tn))
    try:
        r = questionary.select(label, choices=ch, style=_sty(), use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt: return None
    return None if r is None or r == BACK else r

def do_fi(tr):
    """Figures inventory — row mode renders a clip's figures; column mode (c)
    batches a figure type across all clips."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    fstate = {"gaps": False}
    def render_clip(row, rows, i, ctx):
        if row:
            _do_suspended(ctx, lambda: _run(SCRIPT_BATCH_FIGS, "--stem", row["stem"]))
            _log_activity(f"figures/{row['stem']}")
    def force_clip(row, rows, i, ctx):
        if row:
            _do_suspended(ctx, lambda: _run(SCRIPT_BATCH_FIGS, "--stem", row["stem"], "--force"))
    def one_type(row, rows, i, ctx):
        if not row: return
        def work():
            ft = _pick_figtype(f"Render one type · {row['stem']}")
            if ft: _run(SCRIPT_BATCH_FIGS, "--stem", row["stem"], "--types", ft, "--force"); _pause()
        ctx.suspend(work)
    def fill_all(row, rows, i, ctx):
        def work(): _run(SCRIPT_BATCH_FIGS); _log_activity("figures: all")
        _do_suspended(ctx, work,
            confirm=f"Render [bold]all figure types[/] for all {len(tr)} clips?  [dim](QA-passed only)[/]")
    def toggle_gaps(row, rows, i, ctx):
        fstate["gaps"] = not fstate["gaps"]; return "top"
    def col_batch(t, ctx):
        def work(): _run(SCRIPT_BATCH_FIGS, "--types", t[0]); _log_activity(f"figures col {t[1]}")
        _do_suspended(ctx, work,
            confirm=f"Create [bold]{t[2]}[/] for all {len(tr)} clips?  [dim](QA-passed only)[/]")
    def col_force(t, ctx):
        _do_suspended(ctx, lambda: _run(SCRIPT_BATCH_FIGS, "--types", t[0], "--force"),
            confirm=f"[red]Force re-render[/] [bold]{t[2]}[/] for all {len(tr)} clips?  [dim]overwrites existing[/]")
    def view_fig(stem, t, ctx):
        from paths import FIGURES_DIR
        path = os.path.join(FIGURES_DIR, t[0], f"{stem}_{t[0]}.png")
        if os.path.isfile(path):
            try: _open_file(path)
            except Exception: pass
            _log_activity(f"view {t[1]}/{stem}")
    hint = ("[dim]↑↓[/] [bold]↵[/] render   [bold]c[/] columns   [bold]e[/] cells   "
            "[bold]o[/] one-type   [bold]a[/] all   [bold]f[/] force   [bold]g[/] gaps   [bold]q[/] back")
    _inventory_nav(tr, "figures inventory", CLR_FIGURES, FIG_TYPES, _fig_exists,
                   key_actions={"enter": render_clip, "f": force_clip,
                                "o": one_type, "a": fill_all, "g": toggle_gaps},
                   hint=hint, fstate=fstate, on_col=col_batch, on_col_force=col_force,
                   on_view=view_fig)

# Videos
VIDEO_TYPES = [
    ("overlay",          "overlay", "ring overlay"),
    ("combined",         "comb",    "combined + plots"),
    ("phase_animation",  "anim",    "phase animation"),
    ("phase_3d_rotation","3d-rot",  "3D rotation"),
]

def do_vi(tr):
    """Videos — the one videos table. Row mode renders & reviews the highlighted
    clip's overlay (o = render-if-missing then open; p/f/x verdict) and combined
    video (m). Column mode (c) batch-renders a video type across all clips.
    Filters walk the render→review pipeline: 2 = awaiting review, 3 = no overlay."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    state = {"filter": "all"}
    COL_TYPES = ["overlay", "combined", "phase_animation", "phase_3d_rotation"]
    def _note_for(stem, reg):
        for e in reg.values():
            if e.get("config_description") == stem:
                return e.get("overlay_verdict_note")
        return None
    def build_rows():
        reg = load_registry()
        rows = []
        for c in tr:
            s = c["stem"]
            rows.append({"stem": s, "ov": _has_overlay(s),
                         "verdict": _get_verdict(s, reg), "note": _note_for(s, reg),
                         "comb": _vid_exists("combined", s),
                         "anim": _vid_exists("phase_animation", s),
                         "rot3d": _vid_exists("phase_3d_rotation", s)})
        f = state["filter"]
        if f == "review":     rows = [r for r in rows if r["ov"] and r["verdict"] is None]
        elif f == "norender": rows = [r for r in rows if not r["ov"]]
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    def _vcell(r):
        if r["verdict"] == "pass": return "[green]pass[/]"
        if r["verdict"] == "fail": return "[red]fail[/]"
        if r["ov"]: return "[yellow]pending[/]"
        return "[dim]—[/]"
    def _ck(key): return lambda r: "[green]✓[/]" if r[key] else "[dim]·[/]"
    columns = [
        ("#",       lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
        ("clip",    lambda r: r["stem"],    dict(min_width=16, no_wrap=True)),
        ("overlay", lambda r: "[green]✓[/]" if r["ov"] else "[dim]—[/]", dict(justify="center")),
        ("verdict", _vcell,                 dict(width=8)),
        ("comb",    _ck("comb"),            dict(justify="center")),
        ("anim",    _ck("anim"),            dict(justify="center")),
        ("3d-rot",  _ck("rot3d"),           dict(justify="center")),
        ("note",    lambda r: r["note"] or "", dict(style="dim", no_wrap=True, overflow="ellipsis", max_width=22)),
    ]
    col_targets = [2, 4, 5, 6]       # column mode batches renderable types
    cell_targets = [2, 3, 4, 5, 6]   # cell mode also lands on verdict (enter toggles it)
    CELL_COLS = ["overlay", "__verdict__", "combined", "phase_animation", "phase_3d_rotation"]
    def legend():
        reg = load_registry()
        ov = [_has_overlay(c["stem"]) for c in tr]
        vd = [_get_verdict(c["stem"], reg) for c in tr]
        npa = sum(1 for v in vd if v == "pass"); nfa = sum(1 for v in vd if v == "fail")
        npe = sum(1 for o, v in zip(ov, vd) if o and v is None); nno = sum(1 for o in ov if not o)
        return (f"[green]{npa} pass[/]  [red]{nfa} fail[/]  [yellow]{npe} to review[/]  "
                f"[dim]{nno} no overlay[/]   [dim]·[/]   filter: [bold]{state['filter']}[/]")
    hint = ("[dim]↑↓[/] [bold]o[/]/[bold]↵[/] review   [green bold]p[/]ass [red bold]f[/]ail [bold]x[/] clear   "
            "[bold]m[/] combined   [bold]c[/] cols   [bold]e[/] cells   [bold]1[/]/[bold]2[/]/[bold]3[/] filter   [bold]q[/] back")
    col_hint = ("[bold cyan]column mode[/]   [dim]←→[/] pick type   [bold]↵[/] batch all clips   "
                "[bold]f[/] force   [bold]r[/] row mode   [bold]q[/] back")
    def act_review(row, rows, i, ctx):
        if not row: return
        def work():
            if not _has_overlay(row["stem"]):
                console.print(f"  [dim]rendering overlay for {row['stem']}…[/]")
                _render_overlay(row["stem"])
            mp4 = _overlay_path(row["stem"])
            if os.path.isfile(mp4):
                try: _open_file(mp4)
                except Exception: pass
                console.print(f"  [bold {CLR_VIDEOS}]{row['stem']}[/] — opened; mark [green]p[/]ass / [red]f[/]ail in the table")
            else:
                console.print("  [red]overlay render failed[/]")
        _do_suspended(ctx, work)
        _log_activity(f"review {row['stem']}")
    def act_pass(row, rows, i, ctx):
        if row and row["ov"]: _set_verdict(row["stem"], "pass"); return "advance"
    def act_fail(row, rows, i, ctx):
        if not (row and row["ov"]): return
        def ask():
            console.print(f"\n  [red]fail[/] {row['stem']} — reason (optional):")
            try: return input("  ▸ ").strip() or None
            except (EOFError, KeyboardInterrupt): return None
        _set_verdict(row["stem"], "fail", ctx.suspend(ask)); return "advance"
    def act_clear(row, rows, i, ctx):
        if row: _set_verdict(row["stem"], None)
    def act_combined(row, rows, i, ctx):
        if row: _do_suspended(ctx, lambda: _run(SCRIPT_COMBINED, "--stem", row["stem"]))
    def mkfilter(val):
        def _f(row, rows, i, ctx): state["filter"] = val; return "top"
        return _f
    def _col_videos(tn, force):
        # 'overlay' is per-stem via overlay_video.py (not in batch_figures' suite)
        if tn == "overlay":
            tgt = [c["stem"] for c in tr] if force else [c["stem"] for c in tr if not _has_overlay(c["stem"])]
            if not tgt: console.print("  [dim]All overlays already rendered.[/]"); return
            for s in tgt: _render_overlay(s)
        else:
            _run(SCRIPT_BATCH_FIGS, "--video", "--types", tn, *(["--force"] if force else []))
    def col_batch(cpos, rows, ctx):
        tn = COL_TYPES[cpos]
        _do_suspended(ctx, lambda: _col_videos(tn, False), confirm=f"Render [bold]{tn}[/] for all {len(tr)} clips?")
    def col_force(cpos, rows, ctx):
        tn = COL_TYPES[cpos]
        _do_suspended(ctx, lambda: _col_videos(tn, True),
                      confirm=f"[red]Force re-render[/] [bold]{tn}[/] for all {len(tr)} clips?  [dim]overwrites[/]")
    def view_vid(stem, tn, ctx):
        if tn == "overlay":
            path = _overlay_path(stem)
        else:
            from paths import ANIMATIONS_DIR
            path = os.path.join(ANIMATIONS_DIR, tn, f"{stem}_{tn}.mp4")
        if os.path.isfile(path):
            try: _open_file(path)
            except Exception: pass
            _log_activity(f"view {tn}/{stem}")
    def cell_enter(row, cpos, ctx):
        if not row: return
        col = CELL_COLS[cpos]
        if col == "__verdict__":
            if row["ov"]: _set_verdict(row["stem"], "fail" if row["verdict"] == "pass" else "pass")
        else:
            view_vid(row["stem"], col, ctx)
    def cell_view(row, cpos, ctx):
        if row and CELL_COLS[cpos] != "__verdict__": view_vid(row["stem"], CELL_COLS[cpos], ctx)
    cell_hint = ("[bold cyan]cell mode[/]   [dim]↑↓←→[/] pick cell   [bold]↵[/] toggle verdict · view   "
                 "[bold]e[/]/[bold]r[/] row mode   [bold]q[/] back")
    navigate_table(build_rows, columns, title="videos", border_style=CLR_VIDEOS,
                   legend=legend, hint=hint, col_hint=col_hint, cell_hint=cell_hint,
                   empty_msg="No clips match this filter.",
                   key_actions={"o": act_review, "enter": act_review, "p": act_pass,
                                "f": act_fail, "x": act_clear, "m": act_combined,
                                "1": mkfilter("all"), "2": mkfilter("review"), "3": mkfilter("norender")},
                   col_targets=col_targets, col_actions={"enter": col_batch, "f": col_force},
                   cell_targets=cell_targets,
                   cell_actions={"enter": cell_enter, "v": cell_view})
    _log_activity("videos")

# Overlay render + review
def _render_overlay(stem):
    """Render one overlay; overlay_video.py owns its own Rich output.
    Returns True on success."""
    rc = subprocess.run([sys.executable, SCRIPT_OVERLAY, "--stem", stem],
                        cwd=REPO_ROOT).returncode
    return rc == 0

# Info
def do_w():
    import importlib
    global DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, PHASE, clip_dir
    from paths import PHASE_FREE, PHASE_WEEK5, PHASE_WEEK6
    phases = [
        (PHASE_FREE,  "week 3-4", "free swing"),
        (PHASE_WEEK5, "week 5",   "broad V/f survey"),
        (PHASE_WEEK6, "week 6",   "3.2V resonance"),
    ]
    choices = []
    for val, short, desc in phases:
        mark = "  [dim]← current[/]" if val == PHASE else ""
        choices.append(Choice(f" {short} · {desc}{mark}", value=val))
    choices.append(Choice(" ← back", value=None))
    console.print()
    try:
        r = questionary.select("Switch phase", choices=choices, style=_sty(),
                               use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt:
        return
    if r is None or r == PHASE:
        return
    os.environ["CHAOS_PHASE"] = r
    # Reload paths so all module-level path vars pick up the new phase
    import paths as _paths_mod
    importlib.reload(_paths_mod)
    # Re-bind the globals this module uses
    DATA_DIR    = _paths_mod.DATA_DIR
    MEAS_DIR    = _paths_mod.MEAS_DIR
    VIDEOS_DIR  = _paths_mod.VIDEOS_DIR
    EXPERIMENTS = _paths_mod.EXPERIMENTS
    PHASE       = _paths_mod.PHASE
    clip_dir    = _paths_mod.clip_dir
    short = r.replace("pendulum-", "").replace("week", "w")
    _log_activity(f"phase → {short}")
def do_h(): _run(os.path.join(REPO_ROOT,"chaos.py"),"help"); _pause()
def do_p():
    from thresholds import PIVOT, ARM_LENGTH_PX, get_pivot_arm
    pv5,al5=PIVOT,ARM_LENGTH_PX; pv6,al6=get_pivot_arm("3.2V_0.9Hz")
    console.print()
    t=Table(box=None,show_header=False,padding=(0,2),expand=False)
    t.add_column(style="dim"); t.add_column(style="white")
    t.add_row("repo",REPO_ROOT); t.add_row("phase",PHASE)
    t.add_row("videos",VIDEOS_DIR); t.add_row("measurements",MEAS_DIR)
    t.add_row("",""); t.add_row("week5 pivot",f"({pv5[0]},{pv5[1]}) arm {al5}px")
    t.add_row("week6 pivot",f"({pv6[0]},{pv6[1]}) arm {al6}px")
    console.print(Panel(t,title="[bold]paths[/]",border_style=CLR_INFO,padding=(0,1))); _pause()
def do_c():
    from thresholds import PIVOT, ARM_LENGTH_PX, PIVOT_3_2V, ARM_LENGTH_PX_3_2V, ARM_LENGTH_CM, get_pivot_arm
    console.print()
    t=Table(box=box.ROUNDED,show_header=True,padding=(0,2),expand=False,
            title="[bold]Calibration[/]",border_style=CLR_INFO)
    t.add_column("Group",style="bold"); t.add_column("Pivot (x,y)"); t.add_column("Arm (px)")
    t.add_column("Arm (cm)"); t.add_column("Clips")
    # Count clips per calibration group
    from paths import iter_clip_dirs
    n_w5 = sum(1 for s,_ in iter_clip_dirs() if not (s.startswith("3.2V_") and s != "3.2V_1Hz"))
    n_w6 = sum(1 for s,_ in iter_clip_dirs() if s.startswith("3.2V_") and s != "3.2V_1Hz")
    t.add_row("week 5 (broad survey)",f"({PIVOT[0]}, {PIVOT[1]})",str(ARM_LENGTH_PX),
              f"{ARM_LENGTH_CM:.1f}",str(n_w5))
    t.add_row("week 6 (3.2V sweep)",f"({PIVOT_3_2V[0]}, {PIVOT_3_2V[1]})",str(ARM_LENGTH_PX_3_2V),
              f"{ARM_LENGTH_CM:.1f}",str(n_w6))
    console.print(t)
    console.print("\n  [dim]Calibration is set in scripts/utils/thresholds.py[/]")
    console.print("  [dim]Routing logic: get_pivot_arm(stem) — stems starting with 3.2V_ use week 6 calibration[/]")
    _pause()

# ── Hub loop ──

TWO_CHAR_KEYS = ("aq","ai","ar","fi","vi","sw")

DISPATCH = {
    "t":lambda t,p:do_t(t,p),
    "a":lambda t,p:do_a(t),   "aq":lambda t,p:do_aq(t),  "g":lambda t,p:do_gallery(t),
    "ai":lambda t,p:do_ai(),  "ar":lambda t,p:do_ar(t),
    "fi":lambda t,p:do_fi(t),
    "vi":lambda t,p:do_vi(t),
    "s":lambda t,p:do_t(t,p),
    "sw":lambda t,p:do_w(),   "p":lambda t,p:do_p(),     "h":lambda t,p:do_h(),
}

def hub():
    expanded = True
    try:
        while True:
            console.clear(); tr, pe = get_clips()
            render_hub(tr, pe, expanded=expanded)
            try: raw = input("  \u25b8 ").strip().lower()
            except (EOFError, KeyboardInterrupt): break
            if not raw: continue
            if raw in ("+","-","="): expanded = not expanded; continue
            key = raw[:2] if raw[:2] in TWO_CHAR_KEYS else raw[0]
            if key == "q": break
            elif expanded:
                h = DISPATCH.get(key)
                if h: h(tr, pe)
                else: console.print(f"  [dim]Unknown: {key}[/]"); import time; time.sleep(0.5)
            else:
                {"t":lambda:do_t(tr,pe),"a":lambda:do_a(tr),"g":lambda:do_gallery(tr),
                 "o":lambda:sub_output(tr,pe),"s":lambda:sub_info(tr,pe),
                 "h":do_h}.get(key, lambda:console.print(f"  [dim]Unknown: {key}[/]"))()
    except KeyboardInterrupt: pass
    console.print("\n  [dim]bye.[/]")

if __name__ == "__main__": hub()
