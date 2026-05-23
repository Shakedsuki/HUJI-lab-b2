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
SCRIPT_POINCARE    = os.path.join(REPO_ROOT, "scripts", "analysis", "poincare.py")
SCRIPT_LYAPUNOV    = os.path.join(REPO_ROOT, "scripts", "analysis", "lyapunov.py")
SCRIPT_DRIVEN_POIN = os.path.join(REPO_ROOT, "scripts", "analysis", "driven_poincare.py")
SCRIPT_DRIVEN_BIF  = os.path.join(REPO_ROOT, "scripts", "analysis", "driven_bifurcation.py")
SCRIPT_ROTATIONS   = os.path.join(REPO_ROOT, "scripts", "analysis", "rotations.py")
SCRIPT_DIMENSION   = os.path.join(REPO_ROOT, "scripts", "analysis", "dimension.py")
SCRIPT_DIM_SWEEP   = os.path.join(REPO_ROOT, "scripts", "analysis", "dimension_sweep.py")
SCRIPT_RETURN_MAP  = os.path.join(REPO_ROOT, "scripts", "analysis", "return_map.py")
SCRIPT_RECURRENCE  = os.path.join(REPO_ROOT, "scripts", "analysis", "recurrence.py")
SCRIPT_ATTRACTOR   = os.path.join(REPO_ROOT, "scripts", "analysis", "attractor.py")
SCRIPT_WINDING_SWEEP = os.path.join(REPO_ROOT, "scripts", "analysis", "winding_sweep.py")
SCRIPT_PHASE3D_PLOTLY = os.path.join(REPO_ROOT, "scripts", "analysis", "phase_3d_plotly.py")
SCRIPT_WATERFALL   = os.path.join(REPO_ROOT, "scripts", "analysis", "spectral_waterfall.py")
SCRIPT_FTLE_WINDOWS = os.path.join(REPO_ROOT, "scripts", "analysis", "ftle_windows.py")
SCRIPT_CHAOS_WINDOWS = os.path.join(REPO_ROOT, "scripts", "analysis", "chaos_windows.py")
SCRIPT_OVERLAY     = os.path.join(REPO_ROOT, "scripts", "analysis", "overlay_video.py")

CLR_TRACK   = "#4ade80"
CLR_ANALYZE = "#fbbf24"
CLR_OUTPUT  = "#FF6B35"
CLR_FIGURES = "#FF3D6B"
CLR_VIDEOS  = "#38BDF8"
CLR_INTERACTIVE = "#2dd4bf"
CLR_MAIN    = "#c084fc"
CLR_INFO    = "cyan"
CLR_SYSTEM  = "dim"

AUTHOR_NAME  = "Shaked Sukiennik"
AUTHOR_EMAIL = "shaked.sukiennik@mail.huji.ac.il"

_activity_log = []
def _log_activity(msg):
    _activity_log.append(msg)
    if len(_activity_log) > 8: _activity_log.pop(0)

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

# ── Chaos verdict windows (the glyph + sparkline source of truth) ──
# measurements/<stem>/chaos_windows.json (chaos_windows.py): the SAME verdict the
# i-insights chaos card shows + per-window theta2 spectral entropy. Glyph = verdict,
# sparkline = entropy (coloured by the verdict) → card / glyph / sparkline can never
# disagree. Missing file -> dots. Cached; cleared on mode switch / suspended action.
_cw_cache = {}

def _load_chaos_windows(stem):
    path = os.path.join(clip_dir(stem), "chaos_windows.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

def _get_chaos_windows(stem):
    if stem not in _cw_cache:
        _cw_cache[stem] = _load_chaos_windows(stem)
    return _cw_cache[stem]

def _invalidate_chaos_windows_cache():
    _cw_cache.clear()

# verdict -> (glyph markup, colour), matching the chaos card's colour scheme
_VERDICT_GLYPH = {"REGULAR":    ("[#55ff55]○[/]", "#55ff55"),
                  "BORDERLINE": ("[#fbbf24]◎[/]", "#fbbf24"),
                  "CHAOTIC":    ("[#ff5555]●[/]", "#ff5555")}
_GLYPH_NONE = "[dim]·[/]"
_BLOCKS = "▁▂▃▄▅▆▇█"   # sparkline ramp: low entropy -> short, high -> tall

def _render_sparkline(stem):
    """8-char time-resolved chaos bar — per-window theta2 spectral entropy [0,1]
    from chaos_windows.json, coloured by the whole-clip verdict so it agrees with
    the glyph + card (low/short = periodic, tall = broadband). Dots until computed."""
    cw = _get_chaos_windows(stem)
    ent = (cw or {}).get("window_entropy") or []
    if len(ent) < 8:
        return "[dim]········[/]"
    color = _VERDICT_GLYPH.get((cw or {}).get("verdict"), (None, "dim"))[1]
    out = []
    for e in ent[:8]:
        if e is None or e != e:              # missing or NaN
            out.append("[dim]·[/]"); continue
        lvl = max(0, min(7, int(max(0.0, min(1.0, e)) * 8 - 1e-9)))
        out.append(f"[{color}]{_BLOCKS[lvl]}[/]")
    return "".join(out)

def _render_glyph_clip(stem):
    """'glyph stem' for the clip column — the chaos verdict marker (○ regular ·
    ◎ borderline · ● chaotic), the same verdict the i-insights card shows."""
    cw = _get_chaos_windows(stem)
    glyph = _GLYPH_NONE if not cw else _VERDICT_GLYPH.get(cw.get("verdict"), (_GLYPH_NONE, "dim"))[0]
    return f"{glyph} {stem}"

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
        analyze_items = [("a","analyze"),("aq","quick insights")]
        if _voltage_sweep_ok(tracked + pending):
            analyze_items.append(("ai","bifurcation"))
        analyze_items.append(("ar","rotations"))
        ca = _card("analyze", CLR_ANALYZE, analyze_items)
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

BACK = "__back__"

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

_SPECIAL_KEYS = frozenset({"enter", "esc", "tab", "backspace", "up", "down",
                           "left", "right", "home", "end", "pageup", "pagedown"})

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
    pending = ""        # type-ahead buffer for multi-char (two-letter) keys
    show_help = False

    def _help_panel():
        hp = [Text.from_markup("  [dim]move[/]  ↑↓ / k j   Home/End   PgUp/PgDn   [dim]·[/]   q/Esc back")]
        rh = _resolve(hint)
        if rh: hp.append(Text.from_markup("  [bold]row[/]      " + rh))
        if has_cols:
            ch = _resolve(col_hint)
            if ch: hp.append(Text.from_markup("  [bold]column[/]   " + ch))
        if has_cells:
            eh = _resolve(cell_hint)
            if eh: hp.append(Text.from_markup("  [bold]entry[/]    " + eh))
        hp.append(Text.from_markup("  [dim]— any key to close —[/]"))
        return Panel(Group(*hp), title=f"[bold]keys · {_resolve(title)}[/]",
                     border_style=border_style, padding=(1, 2), expand=False)

    def frame():
        nonlocal idx, cidx
        rows = build_rows()
        n = len(rows)
        idx = max(0, min(idx, n - 1)) if n else 0
        _active = cell_targets if mode == "cell" else col_targets
        if _active: cidx = max(0, min(cidx, len(_active) - 1))
        avail = max(5, console.height - 10)
        if show_help:
            return rows, n, avail, _help_panel()
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
        if mode == "row" and pending:
            h = (h or "") + f"     [bold cyan]{pending}…[/]"
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
            if show_help:
                show_help = False
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if key == "esc" and pending:
                pending = ""
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
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
                if key in ("up", "k"): idx -= 1; pending = ""
                elif key in ("down", "j"): idx += 1; pending = ""
                elif key == "home": idx = 0; pending = ""
                elif key == "end": idx = n - 1; pending = ""
                elif key == "pageup": idx -= avail; pending = ""
                elif key == "pagedown": idx += avail; pending = ""
                elif key in ("backspace", "\x08", "\x7f"): pending = pending[:-1]
                elif key == "enter":
                    pending = ""
                    act = key_actions.get("enter")
                    if act:
                        res = act(rows[idx] if n else None, rows, idx, ctx)
                        if res == "quit": break
                        elif res == "advance": idx += 1
                        elif res == "top": idx = 0
                elif len(key) == 1 and key.isprintable():
                    cand = pending + key
                    prefixed = any(len(k) > len(cand) and k.startswith(cand) and k not in _SPECIAL_KEYS for k in key_actions)
                    if cand in key_actions and not prefixed:
                        pending = ""
                        res = key_actions[cand](rows[idx] if n else None, rows, idx, ctx)
                        if res == "quit": break
                        elif res == "advance": idx += 1
                        elif res == "top": idx = 0
                    elif prefixed:
                        pending = cand
                    elif pending:
                        pending = ""
                    elif key == "h": show_help = True
                    elif has_cols and key == "c": mode = "col"; cidx = 0
                    elif has_cells and key == "e": mode = "cell"; cidx = 0
                else:
                    pending = ""
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
        _invalidate_chaos_windows_cache()   # the action may have changed a clip's verdict
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
def _sanity_preview():
    """Return a preview_fn rendering the highlighted clip's sanity-card panel."""
    pcache = {}
    def preview(row):
        if not row: return None
        stem = row["stem"]
        if stem not in pcache:
            ph = max(4, (console.height - 26) // 2)
            pw = max(44, console.width - 78)
            try:
                sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
                from sanity_check import build_one
                verdict, txt = build_one(stem, plot_width=pw, plot_height=ph)
                pcache[stem] = (verdict, Text.from_ansi(txt))
            except Exception as e:
                pcache[stem] = ("?", Text.from_markup(f"[red]sanity unavailable:[/] {e}"))
        verdict, ptxt = pcache[stem]
        ptxt.no_wrap = True; ptxt.overflow = "crop"   # plotext renders at TTY width; crop to the pane, don't wrap
        vc = {"CLEAN": "green", "WARN": "yellow", "REVIEW": "red"}.get(verdict, "dim")
        return Panel(ptxt, title=f"[bold]sanity[/] [dim]·[/] [{vc}]{verdict}[/]",
                     border_style=CLR_TRACK, padding=(0, 1))
    return preview

def _chaos_panel(stem, topo, stat, verdict, reasons):
    """Build the chaos verdict card as a compact in-pane panel (shell-native)."""
    import math
    def _f(v, fmt=".3f"):
        return format(v, fmt) if not (isinstance(v, float) and math.isnan(v)) else "n/a"
    vc = {"CHAOTIC": "red", "BORDERLINE": "yellow", "REGULAR": "green"}.get(verdict, "white")
    topo_t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    topo_t.add_column(style="dim"); topo_t.add_column(justify="right")
    topo_t.add_row("max |θ₂_abs|", f"{topo['max_theta2_abs']:.1f}°")
    topo_t.add_row("arm-2 rotations", f"{topo['n_arm2_rotations']}")
    topo_t.add_row("fraction inverted", f"{topo['frac_inverted']*100:.1f}%")
    topo_t.add_row("E_peak / E_inv", _f(topo['E_ratio_peak'], '.2f'))
    stat_t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    stat_t.add_column(style="dim"); stat_t.add_column(justify="right")
    _kiqr = stat.get('K_chaos_iqr', float('nan'))
    _kval = (f"{_f(stat['K_chaos'])} ± {_f(_kiqr)}"
             if not (isinstance(_kiqr, float) and math.isnan(_kiqr)) else _f(stat['K_chaos']))
    stat_t.add_row("K_chaos (median)", _kval)
    stat_t.add_row("spectral entropy θ₁", _f(stat['spectral_entropy_th1_norm']))
    stat_t.add_row("spectral entropy θ₂", _f(stat['spectral_entropy_th2_norm']))
    rt = Text()
    for i, r in enumerate(reasons):
        if i: rt.append("\n")
        rt.append(f"• {r}", style=vc)
    return Panel(Group(Rule("topological", style="dim"), topo_t,
                       Rule("statistical", style="dim"), stat_t,
                       Rule("verdict", style="dim"), rt),
                 title=f"[bold {vc}]{verdict}[/]  [dim]{stem}[/]",
                 border_style=vc, padding=(0, 1), width=76)

_CHAOS_CACHE = {}
def _chaos_data(stem):
    """Compute + cache (topo, stat, verdict, reasons) for a clip — or the Exception."""
    if stem not in _CHAOS_CACHE:
        try:
            sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
            import chaos_analyze as ca
            data = ca.load_free_swing(os.path.join(clip_dir(stem), "verification.csv"))
            topo = ca.compute_topological(data)
            stat = ca.compute_statistical(topo)
            verdict, reasons = ca.compute_verdict(topo, stat)
            _CHAOS_CACHE[stem] = (topo, stat, verdict, reasons)
        except Exception as e:
            _CHAOS_CACHE[stem] = e
    return _CHAOS_CACHE[stem]

def _chaos_preview():
    """preview_fn rendering the highlighted clip's chaos card (cached, in-process)."""
    def preview(row):
        if not row: return None
        d = _chaos_data(row["stem"])
        if isinstance(d, Exception):
            return Panel(Text.from_markup(f"[red]chaos card unavailable:[/] {d}"),
                         title="[bold]chaos[/]", border_style=CLR_ANALYZE, padding=(0, 1))
        return _chaos_panel(row["stem"], *d)
    return preview

def _chaos_explain(row):
    """explain_fn — plain-English explanation panel for the chaos card."""
    if not row: return None
    d = _chaos_data(row["stem"])
    if isinstance(d, Exception):
        return Panel(Text.from_markup(f"[red]explanation unavailable:[/] {d}"),
                     title="[bold]explain[/]", border_style=CLR_ANALYZE, padding=(0, 1))
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    from insight_explain import explain_chaos
    return Panel(Text.from_markup(explain_chaos(*d)),
                 title="[bold]explain[/] [dim]·[/] chaos", border_style=CLR_ANALYZE, padding=(0, 1), width=76)

# ── Insight registry (cards shown in `i` insights mode) ──
# (id, label, quick_insights key). chaos = the compact metric card; the rest are
# sized plotext plots via quick_insights.build_gallery (which honors plotsize).
ANALYZE_INSIGHTS = [
    ("chaos",    "chaos card",     None),
    ("poincare", "poincaré",       "ret"),
    ("spectrum", "spectrum",       "spectrum"),
    ("phase",    "phase portrait", "phase1"),
    ("return",   "return map",     "return"),
]
def _iw(iid):
    """Card width per insight — chaos is a compact table; plots get room to breathe."""
    return 76 if iid == "chaos" else 92
_INSIGHT_CACHE = {}
def _insight_card(iid, qi_key, label, stem):
    """Render one insight for a clip as (panel, height); cached per (stem, id)."""
    ck = (stem, iid)
    if ck not in _INSIGHT_CACHE:
        w = _iw(iid)
        if iid == "chaos":
            d = _chaos_data(stem)
            panel = (_chaos_panel(stem, *d) if not isinstance(d, Exception)
                     else Panel(Text.from_markup(f"[red]chaos unavailable:[/] {d}"),
                                title="[bold]chaos[/]", border_style=CLR_ANALYZE, padding=(0, 1), width=w))
        else:
            try:
                sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
                from quick_insights import build_gallery
                txt = build_gallery(stem, width=w - 4, plot_height=16, keys=[qi_key])
                body = Text.from_ansi(txt) if txt.strip() else Text.from_markup("[dim](no data for this clip)[/]")
                body.no_wrap = True; body.overflow = "crop"
                panel = Panel(body, title=f"[bold]{label}[/]", border_style=CLR_ANALYZE, padding=(0, 1), width=w)
            except Exception as e:
                panel = Panel(Text.from_markup(f"[red]{label} unavailable:[/] {e}"),
                              title=f"[bold]{label}[/]", border_style=CLR_ANALYZE, padding=(0, 1), width=w)
        _mc = Console(width=w + 4)
        with _mc.capture() as _cap: _mc.print(panel)
        _INSIGHT_CACHE[ck] = (panel, len(_cap.get().splitlines()))
    return _INSIGHT_CACHE[ck]

def _insight_caption(iid, stem):
    """Per-insight explain caption (figure → caption, journal-style), card-width."""
    w = _iw(iid)
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    import insight_explain as ie
    if iid == "chaos":
        d = _chaos_data(stem)
        if isinstance(d, Exception): return None
        txt = ie.explain_chaos(*d)
    else:
        fn = {"poincare": ie.explain_poincare, "spectrum": ie.explain_spectrum,
              "phase": ie.explain_phase, "return": ie.explain_return}.get(iid)
        if fn is None: return None
        txt = fn()
    return Panel(Text.from_markup(txt), title="[bold]explain[/]", border_style=CLR_ANALYZE,
                 padding=(0, 1), width=w)

def build_mode_track():
    """Track mode — one table over all clips; row keys act on the highlighted clip
    (t track/re-track, v verify, s sanity, o open, a bulk); column mode re-tracks
    every clip in view. Preview pane shows the sanity card."""
    def build_rows():
        tr2, pe2 = get_clips()
        rows = [{"stem": c["stem"], "status": c["status"],
                 "dropout": c.get("dropout_pct"), "dur": c.get("duration_s")}
                for c in (tr2 + pe2)]
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
        ("clip",    lambda r: _render_glyph_clip(r["stem"]), dict(min_width=18, no_wrap=True)),
        ("status",  _scell,                 dict(width=9)),
        ("dropout", _pct,                   dict(justify="right", width=8)),
        ("dur",     _dur,                   dict(justify="right", width=7)),
    ]
    def legend():
        tr2, pe2 = get_clips()
        nv = sum(1 for c in tr2 if c.get("quality") == "verified")
        return (f"[green]{nv} verified[/]  [cyan]{len(tr2) - nv} tracked[/]  [yellow]{len(pe2)} pending[/]")
    hint = ("[dim]↑↓[/] [bold]t[/] track/re-track   [bold]v[/] verify   [bold]s[/] sanity   "
            "[bold]o[/] open   [bold]a[/] all   [bold]c[/] column mode   [bold]h[/] help   [bold]q[/] quit")
    col_hint = ("[bold cyan]column mode[/]   [bold]↵[/] re-track every clip in view   "
                "[bold]r[/] row mode   [bold]q[/] quit")
    def act_track(row, rows, i, ctx):
        if not row: return
        stem = row["stem"]
        if row["status"] == "pending":
            _do_suspended(ctx, lambda: _run(SCRIPT_TRACK_ONE, "--stem", stem)); _log_activity(f"tracked {stem}")
        else:
            _do_suspended(ctx, lambda: _run(SCRIPT_TRACK_ONE, "--stem", stem),
                          confirm=f"Re-track [bold]{stem}[/]? Overwrites existing tracking.")
    def act_verify(row, rows, i, ctx):
        if row and row["status"] != "pending":
            _do_suspended(ctx, lambda: _run(SCRIPT_VERIFY, "--stem", row["stem"])); _log_activity(f"verified {row['stem']}")
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
    def col_retrack_all(cpos, rows, ctx):
        stems = [r["stem"] for r in rows]
        if not stems:
            _do_suspended(ctx, lambda: console.print("  [dim]No clips in view.[/]")); return
        def work():
            for j, s in enumerate(stems, 1):
                console.print(Rule(f"[bold][{j}/{len(stems)}] {s}[/]", style="dim"))
                _run(SCRIPT_TRACK_ONE, "--stem", s)
            _log_activity(f"re-tracked {len(stems)} clips")
        _do_suspended(ctx, work,
            confirm=f"[red]Re-track[/] all [bold]{len(stems)}[/] clip(s) in view? "
                    f"Overwrites existing tracking.")
    return Mode(name="track", key="1", color=CLR_TRACK, build_rows=build_rows, columns=columns,
                legend=legend, hint=hint, preview_fn=_sanity_preview(), preview_key="s",
                key_actions={"t": act_track, "v": act_verify, "o": act_open, "a": act_bulk},
                col_targets=[2], col_actions={"enter": col_retrack_all}, col_hint=col_hint)

def do_t(tr, pe):
    _run_one_mode(build_mode_track())
    _log_activity("track/status")

# Analyze
ANALYZE_TYPES = [
    ("chaos_analyze", "chaos",  "chaos card"),
    ("poincare",      "poinc",  "poincar\u00e9"),
    ("lyapunov",      "lyap",   "lyapunov"),
    ("driven",        "driven", "driven poincar\u00e9"),
    ("rotations",     "rot",    "rotations"),
    ("dimension",     "dim",    "fractal dimension"),
    ("return_map",    "ret",    "return map"),
    ("recurrence",    "rec",    "recurrence plot"),
    ("attractor",     "attr",   "attractor embed"),
    ("ftle_windows",  "ftle",   "FTLE windows"),
]

def _analyze_exists(tn, stem):
    if tn == "driven":     return os.path.isfile(os.path.join(clip_dir(stem), "driven_poincare.csv"))
    if tn == "rotations":  return os.path.isfile(os.path.join(clip_dir(stem), "rotations.json"))
    if tn == "dimension":  return os.path.isfile(os.path.join(clip_dir(stem), "dimension.json"))
    if tn == "return_map": return os.path.isfile(os.path.join(clip_dir(stem), "return_map.csv"))
    if tn == "ftle_windows": return os.path.isfile(os.path.join(clip_dir(stem), "ftle_windows.json"))
    return _fig_exists(tn, stem)

def _voltage_sweep_ok(clips):
    """A voltage bifurcation needs >=2 distinct drive voltages. Week6 (a single
    3.2V frequency sweep) -> False, so 'ai'/bifurcation is hidden / N/A there."""
    volts = {c.get("drive_voltage_v") for c in clips if c.get("drive_voltage_v") is not None}
    return len(volts) >= 2

def _freq_sweep_ok(clips):
    """A frequency bifurcation needs >=2 distinct drive frequencies. Week6 (the
    3.2V sweep across f_drive) -> True, so the fd bifurcation applies there."""
    freqs = {c.get("drive_freq_hz") for c in clips if c.get("drive_freq_hz") is not None}
    return len(freqs) >= 2

def build_mode_analyze():
    """Analyze mode \u2014 per-clip analysis matrix; two-letter row keys (ch/po/ly/dr/
    ro/fr) run one analysis, enter explores; aggregate sweeps live in the / palette."""
    def _runclip(ctx, *args):
        _do_suspended(ctx, lambda: _run(*args))
    def act_chaos(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_ANALYZE, row["stem"]); _log_activity(f"chaos {row['stem']}")
    def act_poin(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_POINCARE, "--stem", row["stem"])
    def act_lyap(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_LYAPUNOV, "--stem", row["stem"])
    def act_ftle(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_FTLE_WINDOWS, "--stem", row["stem"]); _log_activity(f"ftle {row['stem']}")
    def act_driven(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_DRIVEN_POIN, "--stem", row["stem"])
    def act_rot(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_ROTATIONS, "--stem", row["stem"]); _log_activity(f"rotations {row['stem']}")
    def act_dim(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_DIMENSION, "--stem", row["stem"]); _log_activity(f"dimension {row['stem']}")
    def act_returnmap(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_RETURN_MAP, "--stem", row["stem"]); _log_activity(f"return map {row['stem']}")
    def act_recurrence(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_RECURRENCE, "--stem", row["stem"]); _log_activity(f"recurrence {row['stem']}")
    def act_attractor(row, rows, i, ctx):
        if row: _runclip(ctx, SCRIPT_ATTRACTOR, "--stem", row["stem"]); _log_activity(f"attractor {row['stem']}")
    def act_explore(row, rows, i, ctx):
        if not row: return
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
        from quick_insights import explore
        _do_suspended(ctx, lambda: explore(row["stem"]), pause=False)
    _RUN = {"chaos": act_chaos, "poinc": act_poin, "lyap": act_lyap, "ftle": act_ftle,
            "driven": act_driven, "rot": act_rot, "dim": act_dim, "ret": act_returnmap,
            "rec": act_recurrence, "attr": act_attractor}
    def run_cell(stem, t, ctx):
        fn = _RUN.get(t[1])
        if fn: fn({"stem": stem}, None, None, ctx)
    hint = ("[dim]\u2191\u2193[/] [bold]\u21b5[/] explore   [bold]i[/] insights   [bold]e[/] entry mode   "
            "[bold]h[/] help   [bold]q[/] quit")
    cell_hint = ("[bold cyan]entry mode[/]   [dim]\u2191\u2193\u2190\u2192[/] pick a cell   [bold]\u21b5[/] run that analysis   "
                 "[bold]e[/]/[bold]r[/] row mode   [bold]q[/] quit")
    keys = {"enter": act_explore}
    return _inventory_mode("analyze", "2", CLR_ANALYZE, ANALYZE_TYPES, _analyze_exists,
                           key_actions=keys, hint=hint, on_view=run_cell, cell_hint=cell_hint,
                           preview_fn=_chaos_preview(), explain_fn=_chaos_explain,
                           insights=ANALYZE_INSIGHTS)

def do_a(tr):
    _run_one_mode(build_mode_analyze())
    _log_activity("analyze")

_QI_CATS = [
    ("green",   "time series", ["both", "omega", "tip", "energy", "rot"]),
    ("yellow",  "phase space", ["phase1", "phase2", "config", "full", "seis1", "seis2"]),
    ("blue",    "physical",    ["xy", "trace"]),
    ("red",     "chaos",       ["spectrum", "return", "ret", "dim", "wfall"]),
    ("magenta", "driven",      ["cyc", "lock", "res"]),
]

def do_aq(tr):
    """Quick insights — clips on the left; type plot names to render them on the
    right and chain more. ↑↓ navigate · ↵ select a clip · type a plot keyword + ↵
    to add it · 'l' clears the pane · 'back' exits."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "analysis"))
    from quick_insights import PLOTS, build_gallery
    clips = [c["stem"] for c in tr]
    st = {"idx": 0, "sel": None, "plots": [], "buf": "", "msg": ""}
    pcache = {}
    def menu():
        lines = [f"[{c} bold]{lbl:<12}[/]" + "  ".join(f"[{c}]{k}[/]" for k in keys)
                 for c, lbl, keys in _QI_CATS]
        return Text.from_markup("\n".join(lines) +
            "\n\n[dim]type a plot keyword + ↵ to render it · chain more · "
            "[bold]l[/] clears · [bold]back[/] exits[/]")
    def right():
        if st["sel"] and st["plots"]:
            key = (st["sel"], tuple(st["plots"]))
            if key not in pcache:
                pw = max(46, console.width - 40); mh = max(12, console.height - 8)
                try:
                    txt = build_gallery(st["sel"], width=pw - 4, plot_height=11,
                                        max_height=mh, keys=st["plots"])
                    pcache[key] = Text.from_ansi(txt) if txt else Text.from_markup("[dim](no output)[/]")
                except Exception as e:
                    pcache[key] = Text.from_markup(f"[red]{e}[/]")
            body = pcache[key]
            title = f"[bold]{st['sel']}[/]  [dim]{' · '.join(st['plots'])}[/]"
        else:
            body = menu()
            tgt = (f"[green]{st['sel']}[/]" if st["sel"]
                   else f"[dim]{clips[st['idx']]} — ↵ to select[/]")
            title = f"[bold]plots[/]  [dim]·[/]  {tgt}"
        return Panel(body, title=title, border_style=CLR_ANALYZE, padding=(0, 1))
    def frame():
        n = len(clips); avail = max(5, console.height - 9)
        if n <= avail: lo, hi = 0, n
        else:
            lo = max(0, min(st["idx"] - avail // 2, n - avail)); hi = lo + avail
        t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=False)
        t.add_column(" ", width=2); t.add_column("#", justify="right", width=3, style="dim")
        t.add_column("clip", min_width=14, no_wrap=True)
        if lo > 0: t.add_row(" ", "", "[dim]↑…[/]")
        for i in range(lo, hi):
            stem = clips[i]
            cur, issel = i == st["idx"], clips[i] == st["sel"]
            mark = "[bold cyan]▸[/]" if cur else ("[green]●[/]" if issel else " ")
            disp = f"[green]{stem}[/]" if issel else stem
            t.add_row(mark, str(i + 1), disp, style="on grey23" if cur else None)
        if hi < n: t.add_row(" ", "", "[dim]↓…[/]")
        left = Panel(t, title="[bold]quick insights[/]", border_style=CLR_ANALYZE,
                     padding=(0, 1), expand=False)
        lay = Table(box=None, show_header=False, expand=True, padding=(0, 1))
        lay.add_column(); lay.add_column(ratio=1); lay.add_row(left, right())
        cl = (f"  [bold cyan]▸[/] {st['buf']}▌" if st["buf"]
              else "  [bold cyan]▸[/] [dim]type a plot name…[/]")
        hint = ("  [dim]↵[/] run plot   [dim]esc cancel · ⌫ edit[/]" if st["buf"]
                else "  [dim]↑↓[/] navigate   [bold]↵[/] select   type a plot + [bold]↵[/]   "
                     "[bold]l[/] clear   [bold]back[/] exit")
        parts = [lay, Text.from_markup(cl)]
        if st["msg"]: parts.append(Text.from_markup("  " + st["msg"]))
        parts.append(Text.from_markup(hint))
        return Group(*parts)
    with Live(frame(), console=console, screen=True, auto_refresh=False) as live:
        while True:
            try: k = _read_key()
            except KeyboardInterrupt: break
            st["msg"] = ""
            if st["buf"]:
                if k == "enter":
                    cmd = st["buf"].strip().lower(); st["buf"] = ""
                    if cmd in ("back", "b", "q", "quit"): break
                    elif cmd in ("l", "clear"): st["plots"] = []
                    elif cmd in ("h", "help", "?"): st["plots"] = []
                    elif cmd in PLOTS:
                        if st["sel"] is None: st["sel"] = clips[st["idx"]]
                        st["plots"].append(cmd)
                    else: st["msg"] = f"[yellow]unknown plot:[/] {cmd}  [dim](l clears, back exits)[/]"
                elif k in ("\x08", "\x7f", "backspace"): st["buf"] = st["buf"][:-1]
                elif k == "esc": st["buf"] = ""
                elif len(k) == 1 and k.isprintable(): st["buf"] += k
            else:
                if k in ("up", "k"): st["idx"] = max(0, st["idx"] - 1)
                elif k in ("down", "j"): st["idx"] = min(len(clips) - 1, st["idx"] + 1)
                elif k == "home": st["idx"] = 0
                elif k == "end": st["idx"] = len(clips) - 1
                elif k == "enter": st["sel"] = clips[st["idx"]]; st["plots"] = []
                elif k in ("q", "esc"): break
                elif len(k) == 1 and k.isprintable(): st["buf"] += k
            live.update(frame(), refresh=True)
    _log_activity("quick insights")

def do_ai(tr):
    """Bifurcation — driven sweep of θ₁ at strobe vs the swept parameter. Uses a
    voltage sweep (vd) when ≥2 drive voltages are present (e.g. week5); otherwise
    falls back to a frequency sweep (fd, fixed 3.2V) when ≥2 drive frequencies are
    present (the week6 resonance sweep)."""
    if _voltage_sweep_ok(tr):
        if not _ask_confirm("Run [bold]bifurcation sweep[/] (vd) across the family?"):
            return
        _run(SCRIPT_DRIVEN_BIF, "--sweep", "vd"); _log_activity("bifurcation sweep"); _pause()
    elif _freq_sweep_ok(tr):
        if not _ask_confirm("Run [bold]bifurcation sweep[/] (fd) across the 3.2V family?"):
            return
        _run(SCRIPT_DRIVEN_BIF, "--sweep", "fd", "--fixed-vd", "3.2")
        _log_activity("bifurcation fd sweep"); _pause()
    else:
        console.print("  [yellow]Bifurcation needs a sweep[/] — this phase has a single drive "
                      "voltage and a single drive frequency, so neither sweep applies here.")
        _pause()

def do_ar(tr):
    """Rotations — per-arm winding metrics across all clips (read from each
    clip's rotations.json). Row keys: ↵ compute this clip, o open its figure;
    a recomputes every clip + the sweep aggregate."""
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    def _load(stem):
        p = os.path.join(clip_dir(stem), "rotations.json")
        if not os.path.isfile(p): return None
        try:
            with open(p, encoding="utf-8") as f: return json.load(f)
        except Exception: return None
    def _sweep_map():
        # the --sweep aggregate CSV holds every clip even when no per-clip json
        # exists yet; read it as the fallback so the table isn't empty.
        import glob, csv as _csv
        from paths import FIGURES_DIR
        m = {}
        for path in glob.glob(os.path.join(FIGURES_DIR, "aggregate", "rotations_sweep_*.csv")):
            try:
                with open(path, encoding="utf-8") as f:
                    for row in _csv.DictReader(f):
                        try:
                            m.setdefault(row["stem"], {})[row["arm"]] = {
                                "net_turns": float(row["net_turns"]),
                                "total_turns": float(row["total_turns"]),
                                "suspect": row.get("suspect", "") in ("1", "True", "true"),
                            }
                        except (ValueError, KeyError):
                            continue
            except OSError:
                continue
        return m
    def build_rows():
        sweep = _sweep_map()
        rows = []
        for c in tr:
            r = _load(c["stem"])
            arms = (r or {}).get("arms") or sweep.get(c["stem"], {})
            susp = any((arms.get(a) or {}).get("suspect") for a in arms)
            rows.append({"stem": c["stem"], "arms": arms, "has": bool(arms), "susp": susp})
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    def _net(r, arm):
        m = r["arms"].get(arm); return f"{m['net_turns']:+.2f}" if m else "[dim]—[/]"
    def _loops(r, arm):
        m = r["arms"].get(arm); return f"{m['total_turns']:.0f}" if m else "[dim]—[/]"
    columns = [
        ("#",       lambda r: str(r["_n"]),         dict(justify="right", width=3, style="dim")),
        ("clip",    lambda r: _render_glyph_clip(r["stem"]), dict(min_width=17, no_wrap=True)),
        ("θ1 net",  lambda r: _net(r, "upper"),     dict(justify="right")),
        ("θ1 ↻",    lambda r: _loops(r, "upper"),   dict(justify="right", style="bold")),
        ("θ2 net",  lambda r: _net(r, "lower_abs"), dict(justify="right")),
        ("θ2 ↻",    lambda r: _loops(r, "lower_abs"),dict(justify="right", style="bold")),
        ("rel net", lambda r: _net(r, "lower_rel"), dict(justify="right")),
        ("rel ↻",   lambda r: _loops(r, "lower_rel"),dict(justify="right")),
        ("susp",    lambda r: "[yellow]⚠[/]" if r["susp"] else "", dict(justify="center", width=4)),
    ]
    def legend():
        sweep = _sweep_map()
        nh = sum(1 for c in tr if _load(c["stem"]) or sweep.get(c["stem"]))
        return (f"[dim]{nh}/{len(tr)} computed[/]   [dim]·  ↻ = completed loops[/]")
    hint = ("[dim]↑↓[/] [bold]↵[/] compute   [bold]o[/] open   [bold]a[/] all + sweep   [bold]h[/] help   [bold]q[/] quit")
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
    navigate_table(build_rows, columns, title="rotations · winding", border_style=CLR_ANALYZE,
                   legend=legend, hint=hint, empty_msg="No clips.",
                   key_actions={"enter": act_compute, "o": act_fig, "a": act_all})
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

def _inventory_mode(name, key, color, types, exists_fn, *, key_actions, hint, glyph="",
                    on_col=None, col_hint=None,
                    on_view=None, on_create=None, cell_hint=None,
                    preview_fn=None, preview_key=None, explain_fn=None, insights=None):
    """Navigable clip×type matrix.
    on_col(type_tuple, ctx) enables column mode ('c'): ←→ pick a type column, enter
    batches it across all clips. on_view / on_create
    (stem, type_tuple, ctx) enable entry mode ('e'): ↑↓←→ pick one cell, 'o' opens
    that file, '+' creates it."""
    def build_rows():
        rows = []
        for c in get_clips()[0]:
            cells = {tn: exists_fn(tn, c["stem"]) for tn, _s, _d in types}
            rows.append({"stem": c["stem"], "cells": cells, "ndone": sum(cells.values())})
        for k, r in enumerate(rows, 1): r["_n"] = k
        return rows
    columns = [("#", lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
               ("clip", lambda r: _render_glyph_clip(r["stem"]), dict(min_width=18, no_wrap=True))]
    for tn, short, _d in types:
        columns.append((short,
            (lambda t: lambda r: "[green]✓[/]" if r["cells"][t] else "[dim]·[/]")(tn),
            dict(justify="center")))
    def legend():
        tr, _pe = get_clips()
        parts = [f"[bold]{short}[/] [dim]{sum(1 for c in tr if exists_fn(tn, c['stem']))}/{len(tr)}[/]"
                 for tn, short, _d in types]
        return "   ".join(parts)
    col_targets = col_actions = cell_actions = None
    if on_col or on_view or on_create:
        col_targets = list(range(2, 2 + len(types)))   # the type columns, after #, clip
    if on_col:
        def col_enter(cpos, rows, ctx): on_col(types[cpos], ctx)
        col_actions = {"enter": col_enter}
        if col_hint is None:
            col_hint = ("[bold cyan]column mode[/]   [dim]←→[/] pick type   [bold]↵[/] batch all clips"
                        + "   [bold]r[/] row mode   [bold]q[/] quit")
    if on_view or on_create:
        cell_actions = {}
        if on_view:
            def cell_view(row, cpos, ctx):
                if row: on_view(row["stem"], types[cpos], ctx)
            cell_actions["o"] = cell_view; cell_actions["enter"] = cell_view
        if on_create:
            def cell_create(row, cpos, ctx):
                if row: on_create(row["stem"], types[cpos], ctx)
            cell_actions["+"] = cell_create
        if cell_hint is None:
            cell_hint = ("[bold cyan]entry mode[/]   [dim]↑↓←→[/] pick cell"
                         + ("   [bold]↵[/]/[bold]o[/] open" if on_view else "")
                         + ("   [bold]+[/] create" if on_create else "")
                         + "   [bold]e[/]/[bold]r[/] row mode   [bold]q[/] quit")
    return Mode(name=name, key=key, color=color, glyph=glyph, build_rows=build_rows,
                columns=columns, key_actions=key_actions, legend=legend, hint=hint,
                col_targets=col_targets, col_actions=col_actions, col_hint=col_hint,
                cell_targets=col_targets, cell_actions=cell_actions, cell_hint=cell_hint,
                preview_fn=preview_fn, preview_key=preview_key, explain_fn=explain_fn, insights=insights)

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
    ("driven_poincare",     "drpoinc","driven poincaré"),
    ("return_map",          "ret",    "return map"),
    ("recurrence",          "rec",    "recurrence plot"),
    ("attractor",           "attr",   "attractor embed"),
]

def build_mode_figures():
    """Figures mode — per-clip figure matrix; enter renders a clip's figures,
    column mode batches a type across clips, entry mode opens/creates one cell."""
    tr, _pe = get_clips()
    def render_clip(row, rows, i, ctx):
        if row:
            _do_suspended(ctx, lambda: _run(SCRIPT_BATCH_FIGS, "--stem", row["stem"]))
            _log_activity(f"figures/{row['stem']}")
    def fill_all(row, rows, i, ctx):
        def work(): _run(SCRIPT_BATCH_FIGS); _log_activity("figures: all")
        _do_suspended(ctx, work,
            confirm=f"Render [bold]all figure types[/] for all {len(tr)} clips?  [dim](QA-passed only)[/]")
    def col_batch(t, ctx):
        def work(): _run(SCRIPT_BATCH_FIGS, "--types", t[0]); _log_activity(f"figures col {t[1]}")
        _do_suspended(ctx, work,
            confirm=f"Create [bold]{t[2]}[/] for all {len(tr)} clips?  [dim](QA-passed only)[/]")
    def view_fig(stem, t, ctx):
        from paths import FIGURES_DIR
        path = os.path.join(FIGURES_DIR, t[0], f"{stem}_{t[0]}.png")
        if os.path.isfile(path):
            try: _open_file(path)
            except Exception: pass
            _log_activity(f"view {t[1]}/{stem}")
    def create_fig(stem, t, ctx):
        _do_suspended(ctx, lambda: _run(SCRIPT_BATCH_FIGS, "--stem", stem, "--types", t[0], "--force", "--all-quality"))
        _log_activity(f"create {t[1]}/{stem}")
    hint = ("[dim]↑↓[/] [bold]↵[/] render   [bold]a[/] all   [bold]c[/] column mode   [bold]e[/] entry mode   "
            "[bold]h[/] help   [bold]q[/] quit")
    return _inventory_mode("figures", "3", CLR_FIGURES, FIG_TYPES, _fig_exists,
                           key_actions={"enter": render_clip, "a": fill_all},
                           hint=hint, on_col=col_batch,
                           on_view=view_fig, on_create=create_fig)

def do_fi(tr):
    _run_one_mode(build_mode_figures())

# Videos
VIDEO_TYPES = [
    ("overlay",          "overlay", "ring overlay"),
    ("combined",         "comb",    "combined + plots"),
    ("phase_animation",  "anim",    "phase animation"),
    ("phase_3d_rotation","3d-rot",  "3D rotation"),
]

def build_mode_videos():
    """Videos mode — overlay/verdict/comb/anim/3d-rot matrix. o/enter render+review
    the overlay, p/f/x set verdict; column mode batches a type, entry mode
    opens/toggles one cell."""
    tr, _pe = get_clips()
    def _note_for(stem, reg):
        for e in reg.values():
            if e.get("config_description") == stem:
                return e.get("overlay_verdict_note")
        return None
    def build_rows():
        reg = load_registry()
        rows = []
        for c in get_clips()[0]:
            s = c["stem"]
            rows.append({"stem": s, "ov": _has_overlay(s),
                         "verdict": _get_verdict(s, reg), "note": _note_for(s, reg),
                         "comb": _vid_exists("combined", s),
                         "anim": _vid_exists("phase_animation", s),
                         "rot3d": _vid_exists("phase_3d_rotation", s)})
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
        ("clip",    lambda r: _render_glyph_clip(r["stem"]), dict(min_width=18, no_wrap=True)),
        ("overlay", lambda r: "[green]✓[/]" if r["ov"] else "[dim]—[/]", dict(justify="center")),
        ("verdict", _vcell,                 dict(width=8)),
        ("comb",    _ck("comb"),            dict(justify="center")),
        ("anim",    _ck("anim"),            dict(justify="center")),
        ("3d-rot",  _ck("rot3d"),           dict(justify="center")),
        ("note",    lambda r: r["note"] or "", dict(style="dim", no_wrap=True, overflow="ellipsis", max_width=22)),
    ]
    # column + entry mode both land on every actionable column incl. verdict (idx 3)
    col_targets = cell_targets = [2, 3, 4, 5, 6]
    CELL_COLS = ["overlay", "__verdict__", "combined", "phase_animation", "phase_3d_rotation"]
    def legend():
        reg = load_registry()
        ov = [_has_overlay(c["stem"]) for c in tr]
        vd = [_get_verdict(c["stem"], reg) for c in tr]
        npa = sum(1 for v in vd if v == "pass"); nfa = sum(1 for v in vd if v == "fail")
        npe = sum(1 for o, v in zip(ov, vd) if o and v is None); nno = sum(1 for o in ov if not o)
        return (f"[green]{npa} pass[/]  [red]{nfa} fail[/]  [yellow]{npe} to review[/]  "
                f"[dim]{nno} no overlay[/]")
    hint = ("[dim]↑↓[/] [bold]o[/]/[bold]↵[/] open   [green bold]p[/]ass [red bold]f[/]ail [bold]x[/] clear   "
            "[bold]c[/] column mode   [bold]e[/] entry mode   [bold]h[/] help   [bold]q[/] quit")
    col_hint = ("[bold cyan]column mode[/]   [dim]←→[/] pick column   [bold]↵[/] batch render   "
                "[green bold]p[/]ass [red bold]f[/]ail [bold]x[/] clear [dim]verdict[/]   "
                "[bold]r[/] row mode   [bold]q[/] quit")
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
    def _col_videos(tn, force):
        # 'overlay' is per-stem via overlay_video.py (not in batch_figures' suite)
        if tn == "overlay":
            tgt = [c["stem"] for c in tr] if force else [c["stem"] for c in tr if not _has_overlay(c["stem"])]
            if not tgt: console.print("  [dim]All overlays already rendered.[/]"); return
            for s in tgt: _render_overlay(s)
        else:
            _run(SCRIPT_BATCH_FIGS, "--video", "--types", tn, *(["--force"] if force else []))
    def _col_verdict(verdict, rows, ctx):
        """Batch-set the overlay verdict across the whole verdict column.
        pass/fail apply to clips that have an overlay (mirrors row-mode p/f);
        clear applies to every clip. Confirmed, then instant (no pause)."""
        if verdict is None:
            tgt = [r["stem"] for r in rows]
            if not tgt: return
            msg = f"Clear overlay verdict for all [bold]{len(tgt)}[/] clip(s)?"
        else:
            tgt = [r["stem"] for r in rows if r["ov"]]
            if not tgt: return
            color = "green" if verdict == "pass" else "red"
            msg = f"Mark all [bold]{len(tgt)}[/] reviewed clip(s) [{color} bold]{verdict}[/]?"
        def work():
            for s in tgt: _set_verdict(s, verdict)
            _log_activity(f"verdict column → {verdict}")
        _do_suspended(ctx, work, pause=False, confirm=msg)
    def col_batch(cpos, rows, ctx):
        col = CELL_COLS[cpos]
        if col == "__verdict__":          # enter on the verdict column = batch pass (clears the figures QA gate)
            _col_verdict("pass", rows, ctx)
        else:
            _do_suspended(ctx, lambda: _col_videos(col, False), confirm=f"Render [bold]{col}[/] for all {len(tr)} clips?")
    def col_pass(cpos, rows, ctx):
        if CELL_COLS[cpos] == "__verdict__": _col_verdict("pass", rows, ctx)
    def col_fail(cpos, rows, ctx):
        if CELL_COLS[cpos] == "__verdict__": _col_verdict("fail", rows, ctx)
    def col_clear(cpos, rows, ctx):
        if CELL_COLS[cpos] == "__verdict__": _col_verdict(None, rows, ctx)
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
    def cell_create(row, cpos, ctx):
        if not row: return
        col = CELL_COLS[cpos]
        if col == "__verdict__": return
        def work():
            if col == "overlay": _render_overlay(row["stem"])
            else: _run(SCRIPT_BATCH_FIGS, "--video", "--types", col, "--stem", row["stem"], "--force", "--all-quality")
        _do_suspended(ctx, work); _log_activity(f"create {col}/{row['stem']}")
    cell_hint = ("[bold cyan]entry mode[/]   [dim]↑↓←→[/] pick cell   [bold]↵[/]/[bold]o[/] open · toggle verdict   "
                 "[bold]+[/] create   [bold]e[/]/[bold]r[/] row mode   [bold]q[/] quit")
    return Mode(name="videos", key="4", color=CLR_VIDEOS, build_rows=build_rows, columns=columns,
                legend=legend, hint=hint, col_hint=col_hint, cell_hint=cell_hint,
                key_actions={"o": act_review, "enter": act_review, "p": act_pass,
                             "f": act_fail, "x": act_clear},
                col_targets=col_targets,
                col_actions={"enter": col_batch, "p": col_pass, "f": col_fail, "x": col_clear},
                cell_targets=cell_targets,
                cell_actions={"enter": cell_enter, "o": cell_view, "+": cell_create})

def do_vi(tr):
    _run_one_mode(build_mode_videos())
    _log_activity("videos")

# Interactive (HTML viewers — regenerable, open in browser)
INTERACTIVE_TYPES = [
    ("phase_3d_plotly", "3d", "interactive 3D phase"),
]
SCRIPT_INTERACTIVE = {"phase_3d_plotly": SCRIPT_PHASE3D_PLOTLY}

def _interactive_path(itype, stem):
    from paths import ANIMATIONS_DIR
    return os.path.join(ANIMATIONS_DIR, itype, f"{stem}_{itype}.html")

def _interactive_exists(itype, stem):
    return os.path.isfile(_interactive_path(itype, stem))

def build_mode_interactive():
    """Interactive mode — per-clip HTML viewers (regenerable, open in browser).
    o/enter render-if-missing then open; column mode batch-renders a type;
    entry mode opens / force-creates one cell."""
    tr, _pe = get_clips()
    def render_open(row, rows, i, ctx):
        if not row: return
        stem = row["stem"]
        missing = [(it, s, d) for (it, s, d) in INTERACTIVE_TYPES
                   if SCRIPT_INTERACTIVE.get(it) and not _interactive_exists(it, stem)]
        if missing:  # rendering shells out (prints) — suspend, but auto-return (no pause)
            def work():
                for it, _s, _d in missing:
                    _run(SCRIPT_INTERACTIVE[it], "--stem", stem)
            _do_suspended(ctx, work, pause=False)
        opened = None
        for it, _s, _d in INTERACTIVE_TYPES:
            p = _interactive_path(it, stem)
            if os.path.isfile(p):
                try: _open_file(p); opened = p
                except Exception: pass
        if not opened:
            return "flash:[red]render failed — see console[/]"
        _log_activity(f"interactive {stem}")
        from pathlib import Path as _Path
        verb = "rendered + opened" if missing else "opened in browser"
        return (f"flash:[link={_Path(opened).as_uri()}]{verb} ↗[/]  ·  "
                "drag rotate · scroll zoom · right-drag pan")
    def col_render(t, ctx):
        itype = t[0]; script = SCRIPT_INTERACTIVE.get(itype)
        def work():
            tgt = [c["stem"] for c in tr if not _interactive_exists(itype, c["stem"])]
            if not tgt:
                console.print(f"  [dim]All {t[2]} already rendered.[/]"); return
            for s in tgt:
                if script: _run(script, "--stem", s)
            _log_activity(f"interactive col {t[1]}")
        _do_suspended(ctx, work, confirm=f"Render [bold]{t[2]}[/] for all missing clips?")
    def open_html(stem, t, ctx):
        p = _interactive_path(t[0], stem)
        if os.path.isfile(p):
            try: _open_file(p); _log_activity(f"open {t[1]}/{stem}")
            except Exception: pass
    def create_html(stem, t, ctx):
        script = SCRIPT_INTERACTIVE.get(t[0])
        if not script: return
        _do_suspended(ctx, lambda: _run(script, "--stem", stem)); _log_activity(f"create {t[1]}/{stem}")
    hint = ("[dim]↑↓[/] [bold]o[/]/[bold]↵[/] open   [bold]c[/] column mode   [bold]e[/] entry mode   "
            "[bold]h[/] help   [bold]q[/] quit")
    return _inventory_mode("interactive", "5", CLR_INTERACTIVE, INTERACTIVE_TYPES, _interactive_exists,
                           key_actions={"enter": render_open, "o": render_open},
                           hint=hint, on_col=col_render,
                           on_view=open_html, on_create=create_html)

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

# ── Mode ring (shell v2 engine) ──
from dataclasses import dataclass, field

@dataclass
class Mode:
    """Per-mode config consumed by run_modes(). Mirrors navigate_table's kwargs,
    so a mode is just a bundle of (rows, columns, handlers, hints)."""
    name: str
    key: str
    color: str
    glyph: str = ""
    build_rows: object = None
    columns: list = field(default_factory=list)
    key_actions: dict = field(default_factory=dict)
    legend: object = ""
    hint: object = ""
    col_targets: object = None
    col_actions: object = None
    col_hint: object = None
    cell_targets: object = None
    cell_actions: object = None
    cell_hint: object = None
    preview_fn: object = None
    preview_key: object = None   # key that toggles the preview panel (track: "s")
    explain_fn: object = None    # row -> explanation panel; enables `x` explain
    insights: object = None      # [(id, label, qi_key)] for `i` insights mode; enables `i`

def _ring_title(modes, active):
    t = Text()
    t.append("CHAOS", style=f"bold {CLR_MAIN}")
    t.append("   ", style="dim")
    for i, m in enumerate(modes):
        if i: t.append("  ")
        t.append(f"{m.glyph or m.key} {m.name}",
                 style=(f"bold {m.color}" if i == active else m.color))
    return t

def _status_line(modes, phase_label, width):
    left = Text("  ")
    left.append(phase_label, style="dim")
    left.append("    ")
    for i, m in enumerate(modes):
        if i: left.append("/", style="dim")
        left.append(m.key, style=f"bold {m.color}")
    left.append(" mode", style="dim")
    left.append("   ⇥ cycle", style="dim")
    right = Text()
    right.append("/ ", style="bold cyan")
    for j, (k, act) in enumerate((("sw", "switch"), ("pa", "paths"), ("cal", "calibrate"))):
        if j: right.append("  ", style="dim")
        right.append(k, style="dim"); right.append(f" {act}", style="dim")
    pad = max(3, width - left.cell_len - right.cell_len - 2)
    return left + Text(" " * pad) + right

def _run_one_mode(m):
    """Run a single Mode through the legacy navigate_table frame (hub fallback)."""
    navigate_table(m.build_rows, m.columns, title=m.name, border_style=m.color,
                   key_actions=m.key_actions, legend=m.legend, hint=m.hint, empty_msg="No clips.",
                   col_targets=m.col_targets, col_actions=m.col_actions, col_hint=m.col_hint,
                   cell_targets=m.cell_targets, cell_actions=m.cell_actions, cell_hint=m.cell_hint,
                   preview_fn=m.preview_fn)

# ── Palette commands (family-aggregate sweeps via the `/` palette) ──
# These act on a whole drive family, not one clip, so they live in the command
# palette rather than the per-clip mode hint bars.
def _palette_waterfall():
    if not _ask_confirm("Run [bold]spectral waterfall[/] across the 3.2V family?"): return
    _run(SCRIPT_WATERFALL); _log_activity("spectral waterfall"); _pause()
def _palette_bif():
    tr, _pe = get_clips()
    if _voltage_sweep_ok(tr):
        if not _ask_confirm("Run [bold]bifurcation sweep[/] (vd) across the family?"): return
        _run(SCRIPT_DRIVEN_BIF, "--sweep", "vd"); _log_activity("bifurcation sweep")
    elif _freq_sweep_ok(tr):
        if not _ask_confirm("Run [bold]bifurcation sweep[/] (fd) across the 3.2V family?"): return
        _run(SCRIPT_DRIVEN_BIF, "--sweep", "fd", "--fixed-vd", "3.2"); _log_activity("bifurcation fd sweep")
    else:
        console.print("  [yellow]No sweep available — single drive voltage and frequency.[/]")
    _pause()
def _palette_rotsweep():
    if not _ask_confirm("Run [bold]rotations sweep[/] across the 3.2V family?"): return
    _run(SCRIPT_ROTATIONS, "--sweep"); _log_activity("rotations sweep"); _pause()
def _palette_dimsweep():
    if not _ask_confirm("Run [bold]dimension sweep[/] across the 3.2V family?"): return
    _run(SCRIPT_DIM_SWEEP); _log_activity("dimension sweep"); _pause()
def _palette_windsweep():
    if not _ask_confirm("Run [bold]winding-number sweep[/] across the 3.2V family?"): return
    _run(SCRIPT_WINDING_SWEEP); _log_activity("winding sweep"); _pause()
def _palette_ftle():
    # ftle_windows.py is per-clip (no --sweep), so batch by looping over the family.
    tr, _pe = get_clips()
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    if not _ask_confirm(f"Compute [bold]FTLE windows[/] for all {len(tr)} clips?  [dim](~5 min)[/]"): return
    for j, c in enumerate(tr, 1):
        console.print(Rule(f"[bold][{j}/{len(tr)}] {c['stem']}[/]", style="dim"))
        _run(SCRIPT_FTLE_WINDOWS, "--stem", c["stem"])
    _log_activity("ftle (all clips)"); _pause()
def _palette_chaoswin():
    # chaos_windows.py is per-clip; batch by looping the family. Cheap (no Rosenstein) —
    # recomputes the verdict + sparkline source of truth behind the glyph/sparkline.
    tr, _pe = get_clips()
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); _pause(); return
    if not _ask_confirm(f"Recompute [bold]chaos verdict + sparkline[/] for all {len(tr)} clips?"): return
    for j, c in enumerate(tr, 1):
        console.print(Rule(f"[bold][{j}/{len(tr)}] {c['stem']}[/]", style="dim"))
        _run(SCRIPT_CHAOS_WINDOWS, "--stem", c["stem"])
    _invalidate_chaos_windows_cache(); _log_activity("chaos windows (all)"); _pause()

def run_modes(modes, start=0, phase_label=None, selected_bg="grey23", overall_fn=None):
    """Shell v2 driver — one persistent table; 0-4 swap modes, cursor persists.
    Rigid frame (title ring + bordered table + hint + status line); only the
    clip-row band scrolls. Reuses the row/column/entry + type-ahead + help
    interaction model from navigate_table."""
    if phase_label is None:
        phase_label = PHASE.replace("pendulum-", "").replace("week", "w")
    by_key = {m.key: i for i, m in enumerate(modes)}
    midx = start
    idx = cidx = 0
    mode = "row"
    pending = ""
    show_help = False
    show_preview = False
    cmd = None
    flash = None
    insights = False
    ins_explain = True
    ins_sel = 0
    shell_cmds = {"sw": do_w, "pa": do_p, "cal": do_c,
                  "wf": _palette_waterfall, "bif": _palette_bif, "rs": _palette_rotsweep,
                  "ds": _palette_dimsweep, "ws": _palette_windsweep, "ftle": _palette_ftle,
                  "cw": _palette_chaoswin}

    def cur():
        return modes[midx]

    def _help_panel(m):
        hp = [Text.from_markup("  [dim]move[/]  ↑↓ / k j   Home/End   PgUp/PgDn   [dim]·[/]   q/Esc quit"),
              Text.from_markup("  [dim]switch[/]  m/1/2/3/4/5 mode   [bold]tab[/] cycle"),
              Text.from_markup("  [dim]palette[/]  [bold cyan]/[/]  sw switch · pa paths · cal calibrate · "
                               "wf waterfall · bif bifurcation · rs rot · ds dim · ws wind · ftle windows · cw verdict")]
        rh = _resolve(m.hint)
        if rh: hp.append(Text.from_markup("  [bold]row[/]      " + rh))
        if m.col_targets:
            ch = _resolve(m.col_hint)
            if ch: hp.append(Text.from_markup("  [bold]column[/]   " + ch))
        if m.cell_actions:
            eh = _resolve(m.cell_hint)
            if eh: hp.append(Text.from_markup("  [bold]entry[/]    " + eh))
        hp.append(Text.from_markup("  [dim]— any key to close —[/]"))
        return Panel(Group(*hp), title=_ring_title(modes, midx), title_align="left",
                     border_style=m.color, padding=(1, 2), box=box.SQUARE)

    def frame():
        nonlocal idx, cidx
        m = cur()
        has_cols = bool(m.col_actions) and bool(m.col_targets)
        cell_tgts = m.cell_targets or m.col_targets
        has_cells = bool(cell_tgts) and bool(m.cell_actions)
        rows = m.build_rows() if m.build_rows else []
        n = len(rows)
        idx = max(0, min(idx, n - 1)) if n else 0
        _active = cell_tgts if mode == "cell" else m.col_targets
        if _active: cidx = max(0, min(cidx, len(_active) - 1))
        width = console.width
        avail = max(5, min(25, console.height - 10))
        try:
            tr2, pe2 = get_clips()
            nver = sum(1 for c in tr2 if c.get("quality") == "verified")
            right_info = f"{nver}/{len(tr2) + len(pe2)}"
        except Exception:
            right_info = None
        try:
            ov = overall_fn() if overall_fn else None
        except Exception:
            ov = None
        title = _ring_title(modes, midx)
        if ov:
            nver, ntr, npe = ov
            total = nver + ntr + npe
            filled = max(0, min(10, round(10 * nver / total))) if total else 0
            prog = Text()
            prog.append("█" * filled, style=CLR_TRACK)
            prog.append("░" * (10 - filled), style="dim")
            prog.append(f"  {nver} verified", style=CLR_TRACK)
            prog.append(" · ", style="dim")
            prog.append(f"{ntr} tracked", style=CLR_ANALYZE)
            prog.append(" · ", style="dim")
            prog.append(f"{npe} pending", style="dim")
            fill = max(3, (width - 6) - title.cell_len - prog.cell_len)
            title.append(" " + "─" * (fill - 2) + " ", style="dim")
            title.append_text(prog)
        if show_help:
            return rows, n, avail, Group(_help_panel(m), _status_line(modes, phase_label, width))
        preview_on = ((show_preview and m.preview_fn is not None) or (insights and m.insights)) and mode == "row"
        # collapse to identity cols for the preview/insights pane; main's leading
        # sparkline (empty header) keeps 3 (spark+#+clip), others keep 2 (#+clip)
        n_id = 3 if (m.columns and m.columns[0][0] == "") else 2
        cols = m.columns[:n_id] if preview_on else m.columns
        ncol = len(cols)
        flash_on = bool(flash) and mode == "row" and not preview_on
        extra = 1 if flash_on else 0
        sel_col = m.col_targets[cidx] if (has_cols and mode == "col") else None
        cell_col = cell_tgts[cidx] if (has_cells and mode == "cell") else None
        if n <= avail:
            lo, hi = 0, n
        else:
            lo = max(0, min(idx - avail // 2, n - avail)); hi = lo + avail
        t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=False)
        t.add_column(" ", width=2)
        for p, (header, _rf, kw) in enumerate(cols):
            if p == sel_col:
                kw = {**kw, "style": f"on {selected_bg}", "header_style": f"bold on {selected_bg}"}
            t.add_column(header, **kw)
        if flash_on:
            t.add_column("", no_wrap=True, overflow="ellipsis")
        if n == 0:
            t.add_row(" ", "[dim]No clips.[/]", *[""] * (ncol - 1 + extra))
        else:
            if lo > 0: t.add_row(" ", "[dim]↑…[/]", *[""] * (ncol - 1 + extra))
            for i in range(lo, hi):
                cells = [rf(rows[i]) for _h, rf, _k in cols]
                if flash_on:
                    cells = cells + [f"  [{m.color}]{flash}[/]" if i == idx else ""]
                if mode == "cell" and i == idx:
                    if cell_col is not None:
                        cells[cell_col] = f"[bold black on bright_cyan]{cells[cell_col]}[/]"
                    t.add_row("[bold cyan]▸[/]", *cells, style=f"on {selected_bg}")
                elif mode == "row" and i == idx:
                    t.add_row("[bold cyan]▸[/]", *cells, style=f"on {selected_bg}")
                else:
                    t.add_row(" ", *cells)
            if hi < n: t.add_row(" ", "[dim]↓…[/]", *[""] * (ncol - 1 + extra))
        table_block = t
        if preview_on:
            row0 = rows[idx] if n else None
            if insights:
                stem0 = row0["stem"] if row0 else None
                tl = Text("  "); tl.append("insights", style="bold"); tl.append("   ")
                for j, (iid, label, _qk) in enumerate(m.insights):
                    if j: tl.append("   ")
                    sel = (j == ins_sel)
                    tl.append(f"{j + 1} ", style=("bold" if sel else "dim"))
                    tl.append("●" if sel else "○", style=("green" if sel else "dim"))
                    tl.append(f" {label.split()[0]}", style=(None if sel else "dim"))
                tl.no_wrap = True; tl.overflow = "crop"   # keep the selector on one line
                parts = [tl, Text("")]
                if stem0 and 0 <= ins_sel < len(m.insights):
                    iid, label, qk = m.insights[ins_sel]
                    card, ch = _insight_card(iid, qk, label, stem0)
                    parts.append(card)
                    if ins_explain and ch + 8 <= max(8, console.height - 12):
                        cap = _insight_caption(iid, stem0)
                        if cap is not None: parts += [Text(""), cap]
                prev = Group(*parts)
            else:
                try: prev = m.preview_fn(row0)
                except Exception: prev = None
            if prev is not None:
                lay = Table(box=None, show_header=False, expand=True, padding=(0, 1))
                lay.add_column(); lay.add_column(ratio=1)
                # blank line drops the pane's border to the table's header row
                # (box.SIMPLE has a blank top line, so an un-padded pane floats 1 line high)
                lay.add_row(t, Group(Text(""), prev))
                table_block = lay
        content = [table_block]
        if cmd is not None:
            cl = Text.from_markup(f"  [bold cyan]/[/] {cmd}▌   [dim]sw switch · pa paths · cal calibrate   ·   wf waterfall · bif bifurcation · rs rot · ds dim · ws wind · ftle windows · cw verdict   · esc cancel[/]")
            cl.no_wrap = True; cl.overflow = "ellipsis"
            content.append(cl)
        else:
            if insights:
                h = (f"[dim]↑↓[/] clip   [bold]1–{len(m.insights)}[/] insight   [bold]x[/] "
                     + ("hide caption" if ins_explain else "caption")
                     + "   [bold]i[/]/[bold]q[/] back")
            elif mode == "cell" and m.cell_hint: h = _resolve(m.cell_hint)
            elif mode == "col" and m.col_hint: h = _resolve(m.col_hint)
            else: h = _resolve(m.hint)
            if mode == "row" and pending:
                h = (h or "") + f"     [bold cyan]{pending}…[/]"
            if h:
                ht = Text.from_markup("  " + h); ht.no_wrap = True; ht.overflow = "ellipsis"
                content.append(ht)
        st = _status_line(modes, phase_label, width - 4); st.no_wrap = True; st.overflow = "ellipsis"
        content.append(st)
        panel = Panel(Group(*content), title=title, title_align="left",
                      border_style=m.color, padding=(0, 1), box=box.SQUARE, expand=True)
        return rows, n, avail, panel

    rows, n, avail, renderable = frame()
    with Live(renderable, console=console, screen=True, auto_refresh=False) as live:
        ctx = _NavCtx(live)
        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                break
            flash = None
            if show_help:
                show_help = False
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if insights:
                mi = cur().insights or []
                if key in ("q", "esc", "i"): insights = False; ins_explain = False
                elif key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key == "home": idx = 0
                elif key == "end": idx = n - 1
                elif key == "pageup": idx -= avail
                elif key == "pagedown": idx += avail
                elif key == "x": ins_explain = not ins_explain
                elif key.isdigit() and key != "0" and int(key) <= len(mi):
                    ins_sel = int(key) - 1
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if cmd is not None:
                if key == "enter":
                    c = cmd.strip().lower(); cmd = None
                    fn = shell_cmds.get(c)
                    if fn:
                        try: ctx.suspend(fn)
                        except Exception: pass
                elif key == "esc": cmd = None
                elif key in ("backspace", "\x08", "\x7f"): cmd = cmd[:-1]
                elif len(key) == 1 and key.isprintable(): cmd += key
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if key == "esc" and pending:
                pending = ""
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if key in ("q", "esc"): break
            if key == "/":
                cmd = ""
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if key == "\t":
                midx = (midx + 1) % len(modes); mode = "row"; cidx = 0; pending = ""; show_preview = False
                _invalidate_chaos_windows_cache()
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            if key in by_key:
                midx = by_key[key]; mode = "row"; cidx = 0; pending = ""; show_preview = False
                _invalidate_chaos_windows_cache()
                rows, n, avail, renderable = frame(); live.update(renderable, refresh=True); continue
            m = cur()
            has_cols = bool(m.col_actions) and bool(m.col_targets)
            cell_tgts = m.cell_targets or m.col_targets
            has_cells = bool(cell_tgts) and bool(m.cell_actions)
            if mode == "col":
                if key in ("left", "h"): cidx -= 1
                elif key in ("right", "l"): cidx += 1
                elif key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key in ("r", "c"): mode = "row"
                else:
                    act = (m.col_actions or {}).get(key)
                    if act and act(cidx, rows, ctx) == "quit": break
            elif mode == "cell":
                if key in ("left", "h"): cidx -= 1
                elif key in ("right", "l"): cidx += 1
                elif key in ("up", "k"): idx -= 1
                elif key in ("down", "j"): idx += 1
                elif key in ("r", "e"): mode = "row"
                else:
                    act = (m.cell_actions or {}).get(key)
                    if act:
                        res = act(rows[idx] if n else None, cidx, ctx)
                        if res == "quit": break
                        elif isinstance(res, str) and res.startswith("mode:"):
                            midx = by_key.get(res[5:], midx); mode = "row"; cidx = 0; pending = ""; show_preview = False
            else:
                ka = m.key_actions or {}
                if key in ("up", "k"): idx -= 1; pending = ""
                elif key in ("down", "j"): idx += 1; pending = ""
                elif key == "home": idx = 0; pending = ""
                elif key == "end": idx = n - 1; pending = ""
                elif key == "pageup": idx -= avail; pending = ""
                elif key == "pagedown": idx += avail; pending = ""
                elif key in ("backspace", "\x08", "\x7f"): pending = pending[:-1]
                elif m.preview_key and key == m.preview_key:
                    show_preview = not show_preview; pending = ""
                elif key == "enter":
                    pending = ""
                    act = ka.get("enter")
                    if act:
                        res = act(rows[idx] if n else None, rows, idx, ctx)
                        if res == "quit": break
                        elif res == "advance": idx += 1
                        elif res == "top": idx = 0
                        elif isinstance(res, str) and res.startswith("flash:"): flash = res[6:]
                elif len(key) == 1 and key.isprintable():
                    cand = pending + key
                    prefixed = any(len(k) > len(cand) and k.startswith(cand) and k not in _SPECIAL_KEYS for k in ka)
                    if cand in ka and not prefixed:
                        pending = ""
                        res = ka[cand](rows[idx] if n else None, rows, idx, ctx)
                        if res == "quit": break
                        elif res == "advance": idx += 1
                        elif res == "top": idx = 0
                        elif isinstance(res, str) and res.startswith("flash:"): flash = res[6:]
                    elif prefixed:
                        pending = cand
                    elif pending:
                        pending = ""
                    elif key == "h": show_help = True
                    elif m.insights and key == "i":
                        insights = True; ins_explain = True; show_preview = False; ins_sel = 0
                    elif has_cols and key == "c": mode = "col"; cidx = 0; show_preview = False
                    elif has_cells and key == "e": mode = "cell"; cidx = 0; show_preview = False
                else:
                    pending = ""
            rows, n, avail, renderable = frame(); live.update(renderable, refresh=True)

def build_mode_main():
    """Main mode — per-clip pipeline overview: track / analyze / figures / videos
    completeness plus a per-clip progress bar. 1-4 dive into a stage (the cursor
    persists across modes). Landing screen."""
    AN_N, FI_N, VI_N = len(ANALYZE_TYPES), len(FIG_TYPES), len(VIDEO_TYPES)
    TOTAL = 1 + AN_N + FI_N + VI_N
    _last = {}
    def build_rows():
        tr, _pe = get_clips()
        rows = []
        for c in tr:
            stem = c["stem"]
            verified = c.get("quality") == "verified" or c.get("status") == "verified"
            an = sum(1 for tn, _s, _d in ANALYZE_TYPES if _analyze_exists(tn, stem))
            fi = sum(1 for tn, _s, _d in FIG_TYPES if _fig_exists(tn, stem))
            vi = sum(1 for tn, _s, _d in VIDEO_TYPES if _vid_exists(tn, stem))
            done = (1 if verified else 0) + an + fi + vi
            rows.append({"_n": 0, "stem": stem, "verified": verified,
                         "an": an, "fi": fi, "vi": vi, "pct": round(100 * done / TOTAL)})
        for k, r in enumerate(rows, 1): r["_n"] = k
        _last["rows"] = rows
        return rows
    def _stage(done, total):
        if done >= total: return "[green]✓[/]"
        if done > 0:      return f"[yellow]◐[/] [dim]{done}/{total}[/]"
        return "[dim]·[/]"
    columns = [
        ("", lambda r: _render_sparkline(r["stem"]), dict(width=8, no_wrap=True)),
        ("#",    lambda r: str(r["_n"]), dict(justify="right", width=3, style="dim")),
        ("clip", lambda r: _render_glyph_clip(r["stem"]), dict(min_width=18, no_wrap=True)),
        (f"[{CLR_TRACK}]track[/]",    lambda r: "[green]✓[/]" if r["verified"] else "[dim]·[/]", dict(justify="center", width=7)),
        (f"[{CLR_ANALYZE}]analyze[/]", lambda r: _stage(r["an"], AN_N), dict(justify="center", width=9)),
        (f"[{CLR_FIGURES}]figures[/]", lambda r: _stage(r["fi"], FI_N), dict(justify="center", width=9)),
        (f"[{CLR_VIDEOS}]videos[/]",  lambda r: _stage(r["vi"], VI_N), dict(justify="center", width=9)),
    ]
    def legend():
        rows = _last.get("rows") or build_rows()
        if not rows: return "[dim]no tracked clips[/]"
        overall = round(sum(r["pct"] for r in rows) / len(rows))
        cws = [_get_chaos_windows(r["stem"]) for r in rows]
        n_reg   = sum(1 for f in cws if f and f.get("verdict") == "REGULAR")
        n_edge  = sum(1 for f in cws if f and f.get("verdict") == "BORDERLINE")
        n_chaos = sum(1 for f in cws if f and f.get("verdict") == "CHAOTIC")
        n_none  = sum(1 for f in cws if f is None)
        spark = f"[#55ff55]○[/] {n_reg}  [#fbbf24]◎[/] {n_edge}  [#ff5555]●[/] {n_chaos}"
        if n_none: spark += f"  [dim]· {n_none} pending[/]"
        return f"{spark}      overall [bold]{overall}%[/]"
    def dive(row, cpos, ctx):
        return "mode:" + ("1", "2", "3", "4")[cpos] if cpos < 4 else None
    hint = "[dim]↑↓[/] [bold]e[/] entry mode   [bold]h[/] help   [bold]q[/] quit"
    cell_hint = ("[bold cyan]entry mode[/]   [dim]←→[/] pick a stage   [bold]↵[/] open that stage   "
                 "[bold]e[/]/[bold]r[/] row mode   [bold]q[/] quit")
    return Mode("main", "m", CLR_MAIN, glyph="⌂", build_rows=build_rows, columns=columns,
                legend=legend, hint=hint,
                cell_targets=[3, 4, 5, 6], cell_actions={"enter": dive, "o": dive}, cell_hint=cell_hint)

def main():
    """Shell v2 — mode-ring entry point (launched by bare `chaos`). Opens on the
    main pipeline overview; 1-5 switch modes (cursor persists)."""
    def _overall():
        tr, pe = get_clips()
        nver = sum(1 for c in tr if c.get("quality") == "verified")
        return (nver, len(tr) - nver, len(pe))
    modes = [build_mode_main(), build_mode_track(), build_mode_analyze(),
             build_mode_figures(), build_mode_videos(), build_mode_interactive()]
    run_modes(modes, start=0, overall_fn=_overall)

# ── Hub loop ──

TWO_CHAR_KEYS = ("aq","ai","ar","fi","vi","sw")

DISPATCH = {
    "t":lambda t,p:do_t(t,p),
    "a":lambda t,p:do_a(t),   "aq":lambda t,p:do_aq(t),
    "ai":lambda t,p:do_ai(t),  "ar":lambda t,p:do_ar(t),
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
                {"t":lambda:do_t(tr,pe),"a":lambda:do_a(tr),
                 "o":lambda:sub_output(tr,pe),"s":lambda:sub_info(tr,pe),
                 "h":do_h}.get(key, lambda:console.print(f"  [dim]Unknown: {key}[/]"))()
    except KeyboardInterrupt: pass
    console.print("\n  [dim]bye.[/]")

if __name__ == "__main__": hub()
