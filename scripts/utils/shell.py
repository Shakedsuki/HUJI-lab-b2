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
SCRIPT_OVERLAY     = os.path.join(REPO_ROOT, "scripts", "analysis", "overlay_video.py")
SCRIPT_REPORT      = os.path.join(REPO_ROOT, "scripts", "utils", "generate_status_report.py")

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
    reg = load_registry()
    for k, e in reg.items():
        if e.get("config_description") == stem:
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
        ct = _card("track", CLR_TRACK, [
            ("tn","next"),("tp","pick & track"),("tb","bulk"),
            ("ts","sanity"),("tv","verify"),("tr","re-track")])
        ca = _card("analyze", CLR_ANALYZE, [
            ("ac","chaos card"),("ap","poincar\u00e9"),("al","lyapunov"),
            ("ad","driven poincar\u00e9"),("ai","bifurcation"),("aq","quick insights")])
        r1 = Table(box=None, show_header=False, expand=True, padding=(0,1))
        r1.add_column(ratio=1); r1.add_column(ratio=1); r1.add_row(ct, ca)

        cf = _card("figures", CLR_FIGURES, [("fs","single figure"),("fc","clip · all types"),("ft","type · all clips"),("fa","all"),("fi","inventory")])
        cv = _card("videos", CLR_VIDEOS, [("vw","render overlays"),("vr","review overlays"),("vc","1-by-1 pipeline"),("va","all combined"),("vi","inventory")])
        ir = Table(box=None, show_header=False, expand=True, padding=(0,1))
        ir.add_column(ratio=1); ir.add_column(ratio=1); ir.add_row(cf, cv)
        co = Panel(ir, title="[bold]output[/]", border_style=CLR_OUTPUT, padding=(0,0), expand=True)

        # Bottom row: info + system + contact
        ic = Text.from_markup(
            f" [{CLR_INFO} bold]s[/]  status   [{CLR_INFO} bold]e[/] export\n"
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
            f"    [{CLR_TRACK} bold]t[/]  track          [dim]\u2192 tn tp tb ts tv tr[/]\n"
            f"    [{CLR_ANALYZE} bold]a[/]  analyze        [dim]\u2192 ac ap al ad ai aq[/]\n"
            f"    [{CLR_OUTPUT}]o[/]  output         [dim]\u2192 fs fc ft fa fi vw vr vc va vi[/]\n"
            f"    [{CLR_INFO} bold]s[/]  info           [dim]\u2192 s e sw p[/]")
        footer = Text.from_markup("  [dim]q quit    h help    + expand[/]")
        body = Group(header, Text(""), actions, Text(""), footer)

    console.print(Panel(body, border_style="magenta", padding=(0,2), width=min(console.width, 76)))

def render_status_panels(tracked, pending):
    for wk, clips in _group_by_week(tracked + pending):
        meta = WEEK_GROUPS.get(wk, {"label":"clips","desc":"","color":"white"})
        gt = [c for c in clips if c["status"]!="pending"]
        gv = [c for c in gt if c.get("quality")=="verified"]
        gp = [c for c in clips if c["status"]=="pending"]
        b = _bar(len(gv), len(gt), len(clips), 24)
        leg = f"[green]{len(gv)} ver[/] [dim]\u00b7[/] [yellow]{len(gt)-len(gv)} trk[/] [dim]\u00b7 {len(gp)} pen[/]"
        t = Table(box=None, show_header=False, padding=(0,1), expand=True)
        t.add_column(justify="right",style="dim",width=4); t.add_column(style="white",min_width=18,ratio=1)
        t.add_column(min_width=10); t.add_column(justify="right",width=7); t.add_column(justify="right",width=9)
        for i, c in enumerate(clips, 1):
            q, st = c.get("quality"), c.get("status","pending")
            sc = "[yellow]pending[/]" if st=="pending" else "[green]verified[/]" if q=="verified" else f"[cyan]{q or 'tracked'}[/]"
            dp = f"{c['dropout_pct']:.1f}%" if c.get("dropout_pct") is not None else "[dim]\u2014[/]"
            du = f"{c['duration_s']:.1f}s" if c.get("duration_s") is not None else "[dim]\u2014[/]"
            t.add_row(str(i), c["stem"], sc, dp, du)
        ti = f"[bold]{meta['label']}[/]"
        if meta["desc"]: ti += f" [dim]\u00b7 {meta['desc']}[/]"
        ti += f" [dim]\u00b7[/] {len(gt)}[dim]/{len(clips)}[/]"
        console.print(Panel(Group(Text.from_markup(f"  {b}  {leg}"), Text(""), t),
            title=ti, border_style=meta["color"], padding=(0,1)))
        console.print()

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

def pick_group(clips, label="Select scope", allow_multi=False):
    """Collapsible scope picker: week groups start collapsed; Enter on a
    header expands it to reveal 'all <week>' + individual clips. Returns a
    list of stems, the sentinel ["__multi__"], or None."""
    if not clips:
        console.print("  [dim]No clips available.[/]"); return None
    groups = _group_by_week(clips)
    named = [wk for wk, _ in groups if WEEK_GROUPS.get(wk)]
    expanded, default = set(), None
    while True:
        ch = [Choice("\u2190 back", value=BACK)]
        if allow_multi:
            ch.append(Choice(" \u2611 pick specific clips\u2026", value="__multi__"))
        if len(named) < 2:
            for wk, gc in groups:
                for i, c in enumerate(gc):
                    br = "\u2570\u2500" if i == len(gc) - 1 else "\u251c\u2500"
                    ch.append(Choice(f" {br} {c['stem']}", value=c["stem"]))
        else:
            for wk, gc in groups:
                m = WEEK_GROUPS.get(wk, {"label": wk or "clips", "desc": ""})
                arrow = "\u25be" if wk in expanded else "\u25b8"
                ch.append(Choice(f" {arrow} {m['label']} \u00b7 {m['desc']} ({len(gc)})",
                                 value=f"__tg__{wk}"))
                if wk in expanded:
                    ch.append(Choice(f"     \u2261 all {m['label']} ({len(gc)})", value=f"__grp__{wk}"))
                    for i, c in enumerate(gc):
                        br = "\u2570\u2500" if i == len(gc) - 1 else "\u251c\u2500"
                        ch.append(Choice(f"     {br} {c['stem']}", value=c["stem"]))
        if len(clips) > 1:
            ch.append(Choice(f" \u2261 everything ({len(clips)})", value="__all__"))
        try:
            r = questionary.select(label, choices=ch, style=_sty(), use_arrow_keys=True,
                                   use_jk_keys=True, default=default).ask()
        except KeyboardInterrupt: return None
        if r is None or r == BACK: return None
        if r == "__multi__": return ["__multi__"]
        if r == "__all__": return [c["stem"] for c in clips]
        if isinstance(r, str) and r.startswith("__tg__"):
            wk = r[len("__tg__"):]
            if wk in expanded: expanded.discard(wk)
            else: expanded.add(wk)
            default = r
            continue
        if isinstance(r, str) and r.startswith("__grp__"):
            wk = r[len("__grp__"):]
            return [c["stem"] for c in clips if c.get("week") == wk]
        return [r]

def _pick_multi(clips, preselect=None, label="Select clips to re-render (space toggles, enter confirms)"):
    """Checkbox multi-select; preselect = set of stems to pre-check."""
    if not clips:
        console.print("  [dim]No clips available.[/]"); return None
    preselect = preselect or set()
    ch = []
    for wk, gc in _group_by_week(clips):
        m = WEEK_GROUPS.get(wk)
        if m: ch.append(Separator(f"── {m['label']} · {m['desc']} ({len(gc)}) ──"))
        for c in gc:
            ch.append(Choice(c["stem"], value=c["stem"], checked=c["stem"] in preselect))
    try:
        r = questionary.checkbox(label, choices=ch, style=_sty()).ask()
    except KeyboardInterrupt: return None
    return r or None

def _pick_render_count(total, has_existing=False):
    choices = [
        Choice(" 1  smoke test", value=1),
        Choice(" n  custom batch", value=-1),
        Choice(f" a  all {total} unrendered", value=total),
    ]
    if has_existing:
        choices.append(Choice(" f  force re-render all", value=-2))
    choices.append(Choice(" \u2190 back", value=0))
    try:
        r = questionary.select("How many to render?", choices=choices, style=_sty(),
                               use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt: return 0, False
    if r is None: return 0, False
    if r == -2: return -2, True  # force flag
    if r == -1:
        try:
            n = int(input(f"  How many? (1-{total}): ").strip())
            return max(1, min(n, total)), False
        except (ValueError, EOFError, KeyboardInterrupt): return 0, False
    return r, False

def pick_or_sweep(clips, label="Sanity check"):
    return _pick_collapsible(clips, label, extra=[Choice("\u2261 sweep all", value=SWEEP)])

def pick_t(tr, label="Pick a clip"): return pick_clip(tr, label)
def pick_p(pe, label="Pick a clip to track"): return pick_clip(pe, label)

# ── Submenus (collapsed) ──

def _sub(title, actions):
    console.print(); console.print(f"  [bold]{title}[/]"); console.print(Rule(style="dim"))
    for k, l, d, c in actions:
        console.print(f"  [{c} bold]{k:<3}[/] {l:<18} [dim]{d}[/]")
    console.print(f"  [dim bold]\u2190[/]  [dim]back[/]"); console.print(Rule(style="dim"))
    try: k = input("  \u25b8 ").strip().lower()
    except (EOFError, KeyboardInterrupt): return None
    return k if k else None

def sub_track(tr, pe):
    k = _sub("track", [("tn","next","first pending",CLR_TRACK),("tp","pick","arrow-key",CLR_TRACK),
        ("tb","bulk","batch all",CLR_TRACK),("ts","sanity","check/sweep",CLR_TRACK),
        ("tv","verify","re-verify",CLR_TRACK),("tr","re-track","force redo",CLR_TRACK)])
    if not k: return
    {"tn":lambda:do_tn(pe),"tp":lambda:do_tp(pe),"tb":do_tb,
     "ts":lambda:do_ts(tr),"tv":lambda:do_tv(tr),"tr":lambda:do_tr(tr)}.get(k[:2],lambda:None)()

def sub_analyze(tr):
    k = _sub("analyze", [("ac","chaos card","verdict",CLR_ANALYZE),("ap","poincar\u00e9","section",CLR_ANALYZE),
        ("al","lyapunov","\u03bb\u2081",CLR_ANALYZE),("ad","driven","stroboscopic",CLR_ANALYZE),
        ("ai","bifurcation","sweep",CLR_ANALYZE),("aq","insights","plot explorer",CLR_ANALYZE)])
    if not k: return
    {"ac":lambda:do_ac(tr),"ap":lambda:do_ap(tr),"al":lambda:do_al(tr),
     "ad":lambda:do_ad(tr),"ai":do_ai,"aq":lambda:do_aq(tr)}.get(k[:2],lambda:None)()

def sub_output(tr, pe):
    k = _sub("output", [("fs","single figure","clip×type",CLR_FIGURES),("fc","clip","all types",CLR_FIGURES),
        ("ft","type","all clips",CLR_FIGURES),("fa","all","everything",CLR_FIGURES),("fi","inventory","catalogue",CLR_FIGURES),
        ("vw","render overlays","group picker",CLR_VIDEOS),("vr","review overlays","verdict sweep",CLR_VIDEOS),
        ("vc","1-by-1 pipeline","render + review",CLR_VIDEOS),("va","all combined","batch",CLR_VIDEOS),("vi","inventory","catalogue",CLR_VIDEOS)])
    if not k: return
    {"fs":lambda:do_fs(tr),"fc":lambda:do_fc(tr),"ft":lambda:do_ft(tr),"fa":do_fa,"fi":lambda:do_fi(tr),
     "vw":lambda:do_vw(tr),"vr":lambda:do_vr(tr),"vc":lambda:do_vc(tr),"vi":lambda:do_vi(tr),
     "va":do_va,"vs":lambda:do_vs(tr),"vf":do_vf,"vp":lambda:do_vp(tr)}.get(k[:2],lambda:None)()

def sub_info(tr, pe):
    k = _sub("info", [("s","status","panels",CLR_INFO),("e","export","xlsx",CLR_INFO),
        ("sw","switch","phase",CLR_INFO),("p","paths","config",CLR_INFO),
        ("c","calibration","pivot & arm",CLR_INFO)])
    if not k: return
    {"s":lambda:do_s(tr,pe),"e":do_e,"sw":do_w,"p":do_p,"c":do_c}.get(k,lambda:None)()

# ── Actions ──

def _run(script, *args):
    return subprocess.run([sys.executable, script, *map(str, args)], cwd=REPO_ROOT).returncode

def _pause():
    console.print()
    try: questionary.press_any_key_to_continue("press any key to return...").ask()
    except KeyboardInterrupt: pass

# Track
def do_tn(pe):
    if not pe: console.print("  [green]Nothing pending.[/]"); _pause(); return
    s=pe[0]["stem"]; console.print(f"  [bold]Tracking:[/] {s}\n")
    _run(SCRIPT_TRACK_ONE,"--stem",s); _log_activity(f"tracked {s}"); _pause()
def do_tp(pe):
    s=pick_p(pe); 
    if not s: return
    console.print(f"  [bold]Tracking:[/] {s}\n"); _run(SCRIPT_TRACK_ONE,"--stem",s); _pause()
def do_tb(): _run(SCRIPT_BULK); _log_activity("bulk done"); _pause()
def do_ts(tr):
    r=pick_or_sweep(tr,"Sanity check")
    if not r: return
    sys.path.insert(0,os.path.join(REPO_ROOT,"scripts","analysis"))
    if r==SWEEP:
        from sanity_check import check_sweep
        def on_p(stem,v,reasons):
            has_vid = _has_overlay(stem)
            console.print()
            if has_vid:
                console.print(f"  [yellow bold]\u2192 overlay video available for inspection[/]")
                console.print("  [bold]v[/] open overlay   [bold]a[/] accept   [bold]n[/] next   [bold]q[/] quit")
            else:
                console.print("  [bold]a[/] accept   [bold]n[/] next   [bold]q[/] quit   [dim](no overlay \u2014 run vw to render)[/]")
            while True:
                try: k=input("  \u25b8 ").strip().lower()
                except: return "q"
                if not k: return "n"
                if k[0]=="v" and has_vid:
                    try: _open_file(_overlay_path(stem))
                    except: console.print("  [red]Could not open video[/]")
                    console.print("  [bold]a[/] accept   [bold]n[/] next   [bold]q[/] quit")
                    continue
                return k[0]
        console.print(); res=check_sweep(tr,on_pause=on_p)
        nc=sum(1 for _,v in res if v=="CLEAN"); nw=sum(1 for _,v in res if v in("WARN","REVIEW"))
        console.print(); console.print(f"  [green]{nc} clean[/]  [yellow]{nw} flagged[/]  [dim]{len(res)} total[/]")
        _log_activity(f"sanity: {nc} clean, {nw} flagged")
    else:
        from sanity_check import check_one
        try: check_one(r)
        except Exception as e: console.print(f"  [red]ERROR:[/] {e}")
    _pause()
def do_tv(tr):
    s=pick_t(tr,"Verify"); 
    if not s: return
    _run(SCRIPT_VERIFY,"--stem",s); _log_activity(f"verified {s}"); _pause()
def do_tr(tr):
    s=pick_t(tr,"Re-track"); 
    if not s: return
    console.print(f"  [bold]Re-tracking:[/] {s}\n"); _run(SCRIPT_TRACK_ONE,"--stem",s,"--force"); _pause()

# Analyze
def do_ac(tr):
    s=pick_t(tr,"Analyze"); 
    if not s: return
    _run(SCRIPT_ANALYZE,s); _log_activity(f"analyzed {s}"); _pause()
def do_ap(tr):
    s=pick_t(tr,"Poincar\u00e9"); 
    if not s: return
    _run(SCRIPT_POINCARE,"--stem",s); _pause()
def do_al(tr):
    s=pick_t(tr,"\u03bb\u2081"); 
    if not s: return
    _run(SCRIPT_LYAPUNOV,"--stem",s); _pause()
def do_ad(tr):
    s=pick_t(tr,"Driven Poincar\u00e9"); 
    if not s: return
    _run(SCRIPT_DRIVEN_POIN,"--stem",s); _pause()
def do_ai(): _run(SCRIPT_DRIVEN_BIF,"--sweep","vd"); _pause()
def do_aq(tr):
    s=pick_t(tr,"Explore"); 
    if not s: return
    sys.path.insert(0,os.path.join(REPO_ROOT,"scripts","analysis"))
    from quick_insights import explore; explore(s)

# ── Inventory ──
def _fig_exists(ftype, stem):
    from paths import FIGURES_DIR
    return os.path.isfile(os.path.join(FIGURES_DIR, ftype, f"{stem}_{ftype}.png"))

def _vid_exists(vtype, stem):
    if vtype == "overlay":
        return os.path.isfile(_overlay_path(stem))
    from paths import FIGURES_DIR
    return os.path.isfile(os.path.join(FIGURES_DIR, vtype, f"{stem}_{vtype}.mp4"))

def _inventory(tr, title, color, types, exists_fn):
    if not tr:
        console.print("  [dim]No tracked clips.[/]"); return
    t = Table(box=box.SIMPLE, show_header=True, padding=(0,1), expand=False)
    t.add_column("clip", min_width=16)
    for tn, short, desc in types: t.add_column(short, justify="center")
    totals = [0]*len(types)
    for wk, gc in _group_by_week(tr):
        m = WEEK_GROUPS.get(wk)
        if m: t.add_row(f"[dim]── {m['label']} ──[/]", *[""]*len(types))
        for c in gc:
            cells = []
            for i,(tn,short,desc) in enumerate(types):
                ok = exists_fn(tn, c["stem"])
                if ok: totals[i] += 1
                cells.append("[green]✓[/]" if ok else "[dim]·[/]")
            t.add_row(c["stem"], *cells)
    t.add_row("[bold]total[/]", *[f"[bold]{n}[/][dim]/{len(tr)}[/]" for n in totals])
    legend = "   ".join(f"[bold]{short}[/] [dim]{desc}[/]" for tn,short,desc in types)
    console.print()
    console.print(Panel(Group(t, Text.from_markup("  " + legend)),
                        title=f"[bold {color}]{title}[/]", border_style=color, padding=(0,1)))

# Figures
FIG_TYPES = [
    ("phase_panels",        "panels", "phase panels"),
    ("poincare",            "poinc",  "poincaré section"),
    ("phase_3d_trajectory", "3d",     "3D trajectory"),
    ("chaos_analyze",       "chaos",  "chaos card"),
    ("lyapunov",            "lyap",   "lyapunov"),
]

def _pick_figtype(label="Figure type"):
    ch = [Choice("← back", value=BACK)]
    for tn, short, desc in FIG_TYPES:
        ch.append(Choice(f"  {tn}  ({desc})", value=tn))
    try:
        r = questionary.select(label, choices=ch, style=_sty(), use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt: return None
    return None if r is None or r == BACK else r

def do_fs(tr):
    s = pick_t(tr, "Single figure — pick clip")
    if not s: return
    ft = _pick_figtype("Single figure — pick type")
    if not ft: return
    _run(SCRIPT_BATCH_FIGS, "--stem", s, "--types", ft, "--force")
    _log_activity(f"figure {ft}/{s}"); _pause()

def do_fc(tr):
    s = pick_t(tr, "All figures for one clip — pick clip")
    if not s: return
    _run(SCRIPT_BATCH_FIGS, "--stem", s)
    _log_activity(f"figures/{s}"); _pause()

def do_ft(tr):
    ft = _pick_figtype("One type across all clips — pick type")
    if not ft: return
    _run(SCRIPT_BATCH_FIGS, "--types", ft)
    _log_activity(f"figures {ft} (all)"); _pause()

def do_fa(): _run(SCRIPT_BATCH_FIGS); _log_activity("figures done"); _pause()

def do_fi(tr):
    while True:
        console.clear()
        _inventory(tr, "figures inventory", CLR_FIGURES, FIG_TYPES, _fig_exists)
        console.print("  [bold]g[/] fill gaps   [bold]q[/] back")
        try: k = input("  ▸ ").strip().lower()
        except (EOFError, KeyboardInterrupt): break
        if not k or k.startswith("q"): break
        if k.startswith("g"):
            scope = pick_group(tr, "Fill gaps — select scope", allow_multi=True)
            if not scope: continue
            if scope == ["__multi__"]:
                scope = _pick_multi(tr, label="Fill gaps — pick clips")
                if not scope: continue
            console.print(f"\n  [dim]filling figure gaps for {len(scope)} clip(s)…[/]")
            _run(SCRIPT_BATCH_FIGS, "--stems", ",".join(scope))
            _log_activity(f"filled figure gaps ({len(scope)})")
            _pause()

# Videos
VIDEO_TYPES = [
    ("overlay",         "overlay", "ring overlay"),
    ("combined",        "comb",    "combined + plots"),
    ("phase_animation", "anim",    "phase animation"),
]

def do_vi(tr):
    _inventory(tr, "videos inventory", CLR_VIDEOS, VIDEO_TYPES, _vid_exists)
    _pause()

def do_va(): _run(SCRIPT_BATCH_FIGS,"--video"); _pause()
def do_vs(tr):
    s=pick_t(tr,"Overlay video")
    if not s: return
    _run(SCRIPT_COMBINED,"--stem",s); _pause()
def do_vf(): _run(SCRIPT_BATCH_FIGS,"--video","--force"); _pause()
def do_vp(tr):
    s=pick_t(tr,"Preview video")
    if not s: return
    _run(os.path.join(REPO_ROOT,"scripts","analysis","preview_frame.py"),"--stem",s,"--video"); _pause()

# Overlay render + review
def _render_overlay(stem):
    """Render one overlay; overlay_video.py owns its own Rich output.
    Returns True on success."""
    rc = subprocess.run([sys.executable, SCRIPT_OVERLAY, "--stem", stem],
                        cwd=REPO_ROOT).returncode
    return rc == 0

def _verdict_prompt(stem):
    """Open video and ask for pass/fail. Returns 'p','f','s','q' or None."""
    mp4 = _overlay_path(stem)
    if os.path.isfile(mp4):
        try: _open_file(mp4)
        except: pass
    console.print(f"  [bold {CLR_VIDEOS}]{stem}[/] \u2014 video opened")
    console.print("  [green bold]p[/]ass   [red bold]f[/]ail   [dim bold]s[/]kip   [dim bold]q[/]uit")
    try: v = input("  \u25b8 ").strip().lower()
    except (EOFError, KeyboardInterrupt): return "q"
    if not v: return "p"
    return v[0]

def _render_batch(batch):
    """Render (overwrite) overlays for the given stems."""
    console.print(Panel(f"Rendering {len(batch)} overlay video{'s' if len(batch)>1 else ''}",
                        title="[bold]batch render[/]", border_style=CLR_VIDEOS, expand=False))
    rendered, failed = 0, 0
    for i, stem in enumerate(batch, 1):
        console.print(Rule(f"[{CLR_VIDEOS}]({i}/{len(batch)})[/]", style="dim"))
        ok = _render_overlay(stem)
        if not ok:
            console.print(f"  [red]\u2717 render failed[/]")
            failed += 1
            if i < len(batch):
                console.print("  [bold]c[/]ontinue   [bold]q[/]uit")
                try: k = input("  \u25b8 ").strip().lower()
                except (EOFError, KeyboardInterrupt): break
                if k.startswith("q"): break
            continue
        rendered += 1
        mp4 = _overlay_path(stem)
        if os.path.isfile(mp4):
            try: _open_file(mp4)
            except: pass
        console.print(f"  [green]\u2713[/] {stem} \u2014 opened for preview")
        console.print()
    summary = Table(box=None, show_header=False, padding=(0,2), expand=False)
    summary.add_column(style="dim"); summary.add_column()
    summary.add_row("rendered", f"[green]{rendered}[/]")
    if failed: summary.add_row("failed", f"[red]{failed}[/]")
    console.print(Panel(summary, title="[bold]done[/]", border_style="dim", expand=False))
    _log_activity(f"overlays: {rendered} rendered" + (f", {failed} failed" if failed else ""))

def do_vw(tr):
    """Render overlay videos: a whole group, or hand-pick a subset to re-render."""
    stems = pick_group(tr, "Render overlays \u2014 select scope", allow_multi=True)
    if not stems: return
    if stems == ["__multi__"]:
        reg = load_registry()
        fails = {c["stem"] for c in tr if _get_verdict(c["stem"], reg) == "fail"}
        sel = _pick_multi(tr, preselect=fails)
        if not sel: return
        _render_batch(sel)
        _pause(); return
    unrendered = [s for s in stems if not _has_overlay(s)]
    existing = len(stems) - len(unrendered)
    if not unrendered and not existing:
        console.print("  [dim]No clips in scope.[/]")
        _pause(); return
    if not unrendered:
        console.print(f"  [green]\u2713[/] All {len(stems)} clips already have overlay videos.")
        console.print(f"  [dim]Use force re-render to overwrite.[/]")
    else:
        console.print(f"\n  [dim]{len(unrendered)} unrendered, {existing} existing[/]")
    count, force = _pick_render_count(len(unrendered) if unrendered else len(stems), has_existing=existing > 0)
    if count == 0: return
    batch = stems if force else unrendered[:count]
    _render_batch(batch)
    _pause()

def do_vr(tr):
    """Overlay review manager \u2014 view verdicts, re-review, change status."""
    stems = pick_group(tr, "Review overlays \u2014 select scope")
    if not stems: return
    while True:
        reg = load_registry()
        # Build status table
        rows = []
        for s in stems:
            has_ov = _has_overlay(s)
            verdict = _get_verdict(s, reg)
            note = None
            for e in reg.values():
                if e.get("config_description") == s:
                    note = e.get("overlay_verdict_note"); break
            rows.append({"stem": s, "has_ov": has_ov, "verdict": verdict, "note": note})
        n_pass = sum(1 for r in rows if r["verdict"]=="pass")
        n_fail = sum(1 for r in rows if r["verdict"]=="fail")
        n_pend = sum(1 for r in rows if r["has_ov"] and r["verdict"] is None)
        n_norend = sum(1 for r in rows if not r["has_ov"])
        # Display
        t = Table(box=box.SIMPLE, show_header=True, padding=(0,1), expand=False)
        t.add_column("#", style="dim", width=3); t.add_column("stem", min_width=18)
        t.add_column("overlay"); t.add_column("verdict"); t.add_column("note", style="dim")
        for i, r in enumerate(rows, 1):
            ov = "[green]\u2713[/]" if r["has_ov"] else "[dim]\u2014[/]"
            if r["verdict"] == "pass":   vs = "[green]pass[/]"
            elif r["verdict"] == "fail": vs = "[red]fail[/]"
            elif r["has_ov"]:            vs = "[yellow]pending[/]"
            else:                        vs = "[dim]\u2014[/]"
            t.add_row(str(i), r["stem"], ov, vs, r["note"] or "")
        legend = f"[green]{n_pass} pass[/]  [red]{n_fail} fail[/]  [yellow]{n_pend} pending[/]  [dim]{n_norend} no overlay[/]"
        console.print(Panel(Group(t, Text.from_markup(f"  {legend}")),
                            title="[bold]overlay review[/]", border_style=CLR_VIDEOS, padding=(0,1)))
        console.print("  [bold]r[/] review pending   [bold]#[/] set/change a verdict   [bold]q[/] done")
        try: cmd = input("  \u25b8 ").strip().lower()
        except (EOFError, KeyboardInterrupt): break
        if not cmd or cmd.startswith("q"): break
        if cmd.startswith("r"):
            pending = [r["stem"] for r in rows if r["has_ov"] and r["verdict"] is None]
            if not pending:
                console.print("  [dim]Nothing pending.[/]")
                import time; time.sleep(0.8); continue
            for j, stem in enumerate(pending, 1):
                console.print(Rule(f"[{CLR_VIDEOS}]({j}/{len(pending)}) {stem}[/]", style="dim"))
                v = _verdict_prompt(stem)
                if v == "q": break
                elif v == "s": continue
                elif v == "f":
                    note = None
                    try: note = input("  reason (optional): ").strip() or None
                    except: pass
                    _set_verdict(stem, "fail", note)
                    console.print(f"  [red]\u2717[/] {stem} \u2192 fail")
                else:
                    _set_verdict(stem, "pass")
                    console.print(f"  [green]\u2713[/] {stem} \u2192 pass")
                console.print()
            continue
        # Pick by number \u2192 set / change its verdict
        try:
            idx = int(cmd) - 1
            if 0 <= idx < len(rows):
                r = rows[idx]
                if not r["has_ov"]:
                    console.print(f"  [dim]No overlay for {r['stem']}. Run vw first.[/]")
                    import time; time.sleep(0.8); continue
                cur = r["verdict"] or "pending"
                console.print(Rule(f"[{CLR_VIDEOS}]{r['stem']}[/]  [dim]current: {cur}[/]", style="dim"))
                console.print("  [green bold]p[/]ass   [red bold]f[/]ail   [bold]o[/]pen video   [dim bold]s[/]kip")
                try: a = input("  \u25b8 ").strip().lower()
                except (EOFError, KeyboardInterrupt): a = "s"
                a = a[0] if a else "s"
                if a == "o":
                    a = _verdict_prompt(r["stem"])
                if a == "f":
                    note = None
                    try: note = input("  reason (optional): ").strip() or None
                    except: pass
                    _set_verdict(r["stem"], "fail", note)
                    console.print(f"  [red]\u2717[/] {r['stem']} \u2192 fail")
                elif a == "p":
                    _set_verdict(r["stem"], "pass")
                    console.print(f"  [green]\u2713[/] {r['stem']} \u2192 pass")
                import time; time.sleep(0.5)
        except ValueError:
            console.print(f"  [dim]Unknown: {cmd}[/]")
            import time; time.sleep(0.5)
    _log_activity("overlay review")
    _pause()

def do_vc(tr):
    """Combined 1-by-1 pipeline: render if needed, then review."""
    stems = pick_group(tr, "Render & review \u2014 select scope")
    if not stems: return
    reg = load_registry()
    # Build ordered work queue: pending-review first, then unrendered
    needs_review = [s for s in stems if _has_overlay(s) and _get_verdict(s, reg) is None]
    needs_render = [s for s in stems if not _has_overlay(s) and _get_verdict(s, reg) is None]
    done_count = len(stems) - len(needs_review) - len(needs_render)
    total_todo = len(needs_review) + len(needs_render)
    if total_todo == 0:
        console.print(f"  [green]\u2713[/] All {len(stems)} clips verified.")
        _pause(); return
    info = Table(box=None, show_header=False, padding=(0,2), expand=False)
    info.add_column(style="dim"); info.add_column()
    info.add_row("ready to review", f"[green]{len(needs_review)}[/]")
    info.add_row("need rendering", f"[yellow]{len(needs_render)}[/]")
    info.add_row("already done", f"[dim]{done_count}[/]")
    console.print(Panel(info, title="[bold]1-by-1 pipeline[/]", border_style=CLR_VIDEOS, expand=False))
    passed, failed_c, seq = 0, 0, 0
    # Phase 1: review existing overlays
    for i, stem in enumerate(needs_review):
        seq += 1
        console.print(Rule(f"[{CLR_VIDEOS}]({seq}/{total_todo}) review[/]", style="dim"))
        v = _verdict_prompt(stem)
        if v == "q": break
        elif v == "s": continue
        elif v == "f":
            note = None
            try: note = input("  reason (optional): ").strip() or None
            except: pass
            _set_verdict(stem, "fail", note)
            console.print(f"  [red]\u2717[/] {stem} \u2192 fail"); failed_c += 1
        else:
            _set_verdict(stem, "pass")
            console.print(f"  [green]\u2713[/] {stem} \u2192 pass"); passed += 1
        console.print()
    else:
        # Phase 2: render + review unrendered
        for i, stem in enumerate(needs_render):
            seq += 1
            console.print(Rule(f"[{CLR_VIDEOS}]({seq}/{total_todo}) render + review[/]", style="dim"))
            ok = _render_overlay(stem)
            if not ok:
                console.print(f"  [red]\u2717 render failed[/]")
                console.print("  [bold]s[/]kip   [bold]q[/]uit")
                try: k = input("  \u25b8 ").strip().lower()
                except: break
                if k.startswith("q"): break
                continue
            console.print(f"  [green]\u2713[/] rendered \u2014 opening for review")
            v = _verdict_prompt(stem)
            if v == "q": break
            elif v == "s": continue
            elif v == "f":
                note = None
                try: note = input("  reason (optional): ").strip() or None
                except: pass
                _set_verdict(stem, "fail", note)
                console.print(f"  [red]\u2717[/] {stem} \u2192 fail"); failed_c += 1
            else:
                _set_verdict(stem, "pass")
                console.print(f"  [green]\u2713[/] {stem} \u2192 pass"); passed += 1
            console.print()
    # Summary
    reg = load_registry()
    total_pass = sum(1 for s in stems if _get_verdict(s, reg) == "pass")
    total_fail = sum(1 for s in stems if _get_verdict(s, reg) == "fail")
    total_pend = sum(1 for s in stems if _get_verdict(s, reg) is None)
    summary = Table(box=None, show_header=False, padding=(0,2), expand=False)
    summary.add_column(style="dim"); summary.add_column()
    summary.add_row("pass", f"[green]{total_pass}[/]")
    summary.add_row("fail", f"[red]{total_fail}[/]")
    summary.add_row("pending", f"[dim]{total_pend}[/]")
    console.print(Panel(summary, title="[bold]pipeline summary[/]", border_style="dim", expand=False))
    _log_activity(f"pipeline: {passed}\u2713 {failed_c}\u2717")
    _pause()

# Info
def do_s(tr,pe): console.print(); render_status_panels(tr,pe); _pause()
def do_e(): _run(SCRIPT_REPORT); _pause()
def do_w():
    import importlib
    global DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, PHASE, clip_dir
    from paths import PHASE_FREE, PHASE_DRIVEN as _PD
    phases = [
        (PHASE_FREE, "week 3-4", "free swing"),
        (_PD,        "week 5-6", "motor-driven"),
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

TWO_CHAR_KEYS = ("tn","tp","tb","ts","tv","tr","ac","ap","al","ad","ai","aq","fs","fc","ft","fa","fi","vw","vr","vc","va","vi","vs","vf","vp","sw")

DISPATCH = {
    "tn":lambda t,p:do_tn(p), "tp":lambda t,p:do_tp(p), "tb":lambda t,p:do_tb(),
    "ts":lambda t,p:do_ts(t), "tv":lambda t,p:do_tv(t), "tr":lambda t,p:do_tr(t),
    "ac":lambda t,p:do_ac(t), "ap":lambda t,p:do_ap(t), "al":lambda t,p:do_al(t),
    "ad":lambda t,p:do_ad(t), "ai":lambda t,p:do_ai(),  "aq":lambda t,p:do_aq(t),
    "fs":lambda t,p:do_fs(t), "fc":lambda t,p:do_fc(t), "ft":lambda t,p:do_ft(t),
    "fa":lambda t,p:do_fa(),  "fi":lambda t,p:do_fi(t),
    "vw":lambda t,p:do_vw(t), "vr":lambda t,p:do_vr(t), "vc":lambda t,p:do_vc(t),
    "va":lambda t,p:do_va(),  "vi":lambda t,p:do_vi(t),
    "vs":lambda t,p:do_vs(t), "vf":lambda t,p:do_vf(), "vp":lambda t,p:do_vp(t),
    "s":lambda t,p:do_s(t,p), "e":lambda t,p:do_e(),
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
                {"t":lambda:sub_track(tr,pe),"a":lambda:sub_analyze(tr),
                 "o":lambda:sub_output(tr,pe),"s":lambda:sub_info(tr,pe),
                 "h":do_h}.get(key, lambda:console.print(f"  [dim]Unknown: {key}[/]"))()
    except KeyboardInterrupt: pass
    console.print("\n  [dim]bye.[/]")

if __name__ == "__main__": hub()
