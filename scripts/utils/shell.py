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
SCRIPT_REPORT      = os.path.join(REPO_ROOT, "scripts", "utils", "generate_status_report.py")
SCRIPT_ROADMAP     = os.path.join(REPO_ROOT, "scripts", "utils", "generate_roadmap.py")

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

def _is_tracked(entry):
    if not entry: return False
    md = entry.get("measurements_dir")
    if not md: return False
    return os.path.exists(os.path.join(os.path.dirname(MEAS_DIR), md, entry.get("csv_file","tracking.csv")))

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
            if entry and _is_tracked(entry):
                info["status"] = entry.get("tracking_quality", "tracked"); tracked.append(info)
            else:
                info["status"] = "pending"; pending.append(info)
    return tracked, pending

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
    header = Text.from_markup(
        f"  {LOGO}\n  [dim]double pendulum[/]    {bar}  [bold]{nt}[/][dim]/{total}[/]\n"
        f"  [dim]HUJI-LAB-B2[/]        {legend}")

    if expanded:
        ct = _card("track", CLR_TRACK, [
            ("tn","next"),("tp","pick & track"),("tb","bulk"),
            ("ts","sanity"),("tv","verify"),("tr","re-track")])
        ca = _card("analyze", CLR_ANALYZE, [
            ("ac","chaos card"),("ap","poincar\u00e9"),("al","lyapunov"),
            ("ad","driven poincar\u00e9"),("ai","bifurcation"),("aq","quick insights")])
        r1 = Table(box=None, show_header=False, expand=True, padding=(0,1))
        r1.add_column(ratio=1); r1.add_column(ratio=1); r1.add_row(ct, ca)

        cf = _card("figures", CLR_FIGURES, [("fa","all missing"),("fs","single clip"),("ff","force all"),("fp","preview")])
        cv = _card("videos", CLR_VIDEOS, [("va","all overlays"),("vs","single clip"),("vf","force re-render"),("vp","preview")])
        ir = Table(box=None, show_header=False, expand=True, padding=(0,1))
        ir.add_column(ratio=1); ir.add_column(ratio=1); ir.add_row(cf, cv)
        co = Panel(ir, title="[bold]output[/]", border_style=CLR_OUTPUT, padding=(0,0), expand=True)

        # Bottom row: info + system + contact
        ic = Text.from_markup(
            f" [{CLR_INFO} bold]s[/] status  [{CLR_INFO} bold]e[/] export\n"
            f" [{CLR_INFO} bold]m[/] roadmap [{CLR_INFO} bold]w[/] switch\n"
            f" [{CLR_INFO} bold]p[/] paths")
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

        body = Group(header, Text(""), r1, co, Text(""), r3)
    else:
        actions = Text.from_markup(
            f"    [{CLR_TRACK} bold]t[/]  track          [dim]\u2192 tn tp tb ts tv tr[/]\n"
            f"    [{CLR_ANALYZE} bold]a[/]  analyze        [dim]\u2192 ac ap al ad ai aq[/]\n"
            f"    [{CLR_OUTPUT}]o[/]  output         [dim]\u2192 fa fs ff fp va vs vf vp[/]\n"
            f"    [{CLR_INFO} bold]s[/]  info           [dim]\u2192 s e m w p[/]")
        footer = Text.from_markup("  [dim]q quit    h help    + expand[/]")
        body = Group(header, Text(""), actions, Text(""), footer)

    console.print(Panel(body, border_style="magenta", padding=(1,2), width=min(console.width, 76)))

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

def pick_clip(clips, label="Pick a clip"):
    if not clips: console.print("  [dim]No clips available.[/]"); return None
    try: r = questionary.select(label, choices=_choices(clips), style=_sty(), use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt: return None
    return None if r is None or r == BACK else r

def pick_or_sweep(clips, label="Sanity check"):
    if not clips: console.print("  [dim]No clips available.[/]"); return None
    try: r = questionary.select(label, choices=_choices(clips, [Choice("\u2261 sweep all", value=SWEEP)]),
             style=_sty(), use_arrow_keys=True, use_jk_keys=True).ask()
    except KeyboardInterrupt: return None
    return None if r is None or r == BACK else r

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
    k = _sub("output", [("fa","all figures","batch",CLR_FIGURES),("fs","single fig","pick",CLR_FIGURES),
        ("ff","force fig","redo",CLR_FIGURES),("fp","preview","frame",CLR_FIGURES),
        ("va","all videos","batch",CLR_VIDEOS),("vs","single vid","pick",CLR_VIDEOS),
        ("vf","force vid","redo",CLR_VIDEOS),("vp","preview vid","frame",CLR_VIDEOS)])
    if not k: return
    {"fa":do_fa,"fs":lambda:do_fs(tr),"ff":do_ff,"fp":lambda:do_fp(tr),
     "va":do_va,"vs":lambda:do_vs(tr),"vf":do_vf,"vp":lambda:do_vp(tr)}.get(k[:2],lambda:None)()

def sub_info(tr, pe):
    k = _sub("info", [("s","status","panels",CLR_INFO),("e","export","xlsx",CLR_INFO),
        ("m","roadmap","md",CLR_INFO),("w","switch","phase",CLR_INFO),("p","paths","config",CLR_INFO)])
    if not k: return
    {"s":lambda:do_s(tr,pe),"e":do_e,"m":do_m,"w":do_w,"p":do_p}.get(k[0],lambda:None)()

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
            console.print("  [dim][a]ccept [f]lag [n]ext [q]uit[/]")
            try: k=input("  \u25b8 ").strip().lower()
            except: return "q"
            return k[0] if k else "n"
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

# Figures
def do_fa(): _run(SCRIPT_BATCH_FIGS); _log_activity("figures done"); _pause()
def do_fs(tr):
    s=pick_t(tr,"Figures"); 
    if not s: return
    _run(SCRIPT_BATCH_FIGS,"--stem",s); _pause()
def do_ff(): _run(SCRIPT_BATCH_FIGS,"--force"); _pause()
def do_fp(tr):
    s=pick_t(tr,"Preview"); 
    if not s: return
    _run(os.path.join(REPO_ROOT,"scripts","analysis","preview_frame.py"),"--stem",s); _pause()

# Videos
def do_va(): _run(SCRIPT_BATCH_FIGS,"--video"); _pause()
def do_vs(tr):
    s=pick_t(tr,"Overlay video"); 
    if not s: return
    _run(SCRIPT_COMBINED,"--stem",s); _pause()
def do_vf(): _run(SCRIPT_BATCH_FIGS,"--video","--force"); _pause()
def do_vp(tr):
    s=pick_t(tr,"Preview video"); 
    if not s: return
    _run(os.path.join(REPO_ROOT,"scripts","analysis","preview_frame.py"),"--stem",s,"--video"); _pause()

# Info
def do_s(tr,pe): console.print(); render_status_panels(tr,pe); _pause()
def do_e(): _run(SCRIPT_REPORT); _pause()
def do_m(): _run(SCRIPT_ROADMAP); _pause()
def do_w():
    cur=PHASE.replace("pendulum-","").replace("week","w")
    console.print(f"\n  [bold]Switch phase[/]  [dim]current: [cyan]{cur}[/][/]\n")
    console.print('  [dim]$env:CHAOS_PHASE = "week3-4-pendulum-free-swing"[/]')
    console.print('  [dim]$env:CHAOS_PHASE = "week5-6-pendulum-motor-driven"[/]'); _pause()
def do_h(): _run(sys.executable, os.path.join(REPO_ROOT,"chaos.py"),"help"); _pause()
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

# ── Hub loop ──

TWO_CHAR_KEYS = ("tn","tp","tb","ts","tv","tr","ac","ap","al","ad","ai","aq","fa","fs","ff","fp","va","vs","vf","vp")

DISPATCH = {
    "tn":lambda t,p:do_tn(p), "tp":lambda t,p:do_tp(p), "tb":lambda t,p:do_tb(),
    "ts":lambda t,p:do_ts(t), "tv":lambda t,p:do_tv(t), "tr":lambda t,p:do_tr(t),
    "ac":lambda t,p:do_ac(t), "ap":lambda t,p:do_ap(t), "al":lambda t,p:do_al(t),
    "ad":lambda t,p:do_ad(t), "ai":lambda t,p:do_ai(),  "aq":lambda t,p:do_aq(t),
    "fa":lambda t,p:do_fa(),  "fs":lambda t,p:do_fs(t), "ff":lambda t,p:do_ff(),
    "fp":lambda t,p:do_fp(t), "va":lambda t,p:do_va(),  "vs":lambda t,p:do_vs(t),
    "vf":lambda t,p:do_vf(),  "vp":lambda t,p:do_vp(t),
    "s":lambda t,p:do_s(t,p), "e":lambda t,p:do_e(),    "m":lambda t,p:do_m(),
    "w":lambda t,p:do_w(),    "p":lambda t,p:do_p(),     "h":lambda t,p:do_h(),
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
