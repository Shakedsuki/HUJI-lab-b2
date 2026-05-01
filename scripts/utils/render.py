"""
render.py
----------
Pure-output Rich rendering module for the chaos tracking pipeline.
Every function prints to the terminal (or a recording Console for log
export); no file writes, no subprocess, no registry mutations.

Phase 1 — additive only. Integration into track_one and verify_tracking
will land in a follow-up brief; until then, this module ships
self-tested but unwired.

Module layout
~~~~~~~~~~~~~
- Threshold constants and the bar-scale maxima are imported from
  scripts/utils/thresholds.py — single source of truth shared with
  track_one.compute_verdict so the verdict label can never disagree
  with its visual representation.
- Clean-row / neighbour predicates come from scripts/utils/csv_helpers
  so the interpolation-plan view never drifts from the actual
  interpolate_suspects logic.

The only public surface is the `render_*` functions below. Helpers
prefixed with `_` are internal but tested via the self-test.

Self-test
~~~~~~~~~
Run `python scripts/utils/render.py` to print every panel against
mock data. Visual inspection IS the test for a pure-output module.
"""

import io
import os
import sys

# Force UTF-8 stdout so the unicode glyphs in tables / bars (θ, ω, ━,
# ░, ┊, ✓, ⚠, ✗) don't crash on Windows' cp1252 default. Every other
# script in this repo does the same for the same reason.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import rich.box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# Make scripts/utils importable when this file runs as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thresholds import (  # noqa: E402
    PASS_DROPOUT_PCT,
    WARN_DROPOUT_PCT,
    PEAK_OMEGA_PHYSICAL,
    PEAK_OMEGA_ABSURD,
    OMEGA_BAR_MAX,
    DROPOUT_BAR_MAX,
    OMEGA_HOLD_THRESHOLD,
)
from csv_helpers import is_clean_row, find_neighbours  # noqa: E402,F401


# Module-level Console — callers can replace with their own (e.g.
# record=True for log capture) by re-binding this attribute.
console = Console()

# Logged output uses a fixed width so log files don't depend on the
# terminal that happened to be running.
LOG_CONSOLE_WIDTH = 100

# Cap on rows in any "top-N" table. Keeps long_recording's 493 suspects
# from spamming the screen.
SUSPECT_TABLE_CAP = 30

# Forward contract for render_verdict.actionable_steps. Brief 4 must
# emit dicts with these keys.
ACTIONABLE_STEP_PRIORITIES = ("required", "review", "info")


# ─────────────────────────────────────────────
# COLOUR + BAR HELPERS
# ─────────────────────────────────────────────

def _omega_color(value: float) -> str:
    if value <= PEAK_OMEGA_PHYSICAL:
        return "green"
    if value <= PEAK_OMEGA_ABSURD:
        return "yellow"
    return "red"


def _dropout_color(pct: float) -> str:
    if pct < PASS_DROPOUT_PCT:
        return "green"
    if pct < WARN_DROPOUT_PCT:
        return "yellow"
    return "red"


def _make_bar(value: float, max_val: float, width: int = 20,
              color: str = "green") -> str:
    """Single-colour bar — fill chars in `color`, empty chars dim."""
    filled = min(int(round(value / max_val * width)), width)
    empty  = width - filled
    return f"[{color}]{'━' * filled}[/{color}]{'░' * empty}"


def _make_omega_bar(value: float, width: int = 20) -> str:
    """ω bar with a tick at the physical-RoT line. Filled chars are
    coloured by _omega_color(value); the tick stays visible regardless
    of fill state."""
    threshold_pos = int(round(PEAK_OMEGA_PHYSICAL / OMEGA_BAR_MAX * width))
    value_pos = min(int(round(value / OMEGA_BAR_MAX * width)), width)
    color = _omega_color(value)

    parts = []
    for i in range(width):
        if i == threshold_pos:
            ch = "┊"
            parts.append(ch)
        elif i < value_pos:
            parts.append(f"[{color}]━[/{color}]")
        else:
            parts.append("░")
    return "".join(parts)


def _make_dropout_bar(pct: float, width: int = 20) -> str:
    """Three-zone dropout bar: filled chars coloured by which threshold
    zone they sit in; unfilled chars dim. Lets the user read both
    'how big' (length) and 'how bad' (colour) at once."""
    pass_end = int(round(PASS_DROPOUT_PCT / DROPOUT_BAR_MAX * width))
    warn_end = int(round(WARN_DROPOUT_PCT / DROPOUT_BAR_MAX * width))
    value_pos = min(int(round(pct / DROPOUT_BAR_MAX * width)), width)

    parts = []
    for i in range(width):
        if i < value_pos:
            if i < pass_end:
                parts.append("[green]━[/green]")
            elif i < warn_end:
                parts.append("[yellow]━[/yellow]")
            else:
                parts.append("[red]━[/red]")
        else:
            parts.append("░")
    return "".join(parts)


def _kv_table() -> Table:
    """Borderless two-column key-value table used inside Panels."""
    t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t.add_column(style="dim")     # key column
    t.add_column(style="white")   # value column
    return t


# ─────────────────────────────────────────────
# RENDER FUNCTIONS — verification stage
# ─────────────────────────────────────────────

def render_verification_summary(n: int,
                                n_drop: int,
                                n_suspect: int,
                                n_clean_suspect: int,
                                dt_med: float) -> None:
    """Top-of-verify summary table: total frames, dropout %, suspect %,
    hidden-suspect %, median Δt."""
    t = Table(title="Verification — Frame Totals",
              box=rich.box.SIMPLE_HEAD)
    t.add_column("Metric", style="dim")
    t.add_column("Value", style="white")

    pct_drop = 100.0 * n_drop / n if n else 0.0
    pct_susp = 100.0 * n_suspect / n if n else 0.0
    pct_hide = 100.0 * n_clean_suspect / n if n else 0.0

    if n_clean_suspect > 0:
        hidden_str = (f"[red]{n_clean_suspect}[/red]  ({pct_hide:.2f}%)"
                      f"  [dim]← likely false positives[/dim]")
    else:
        hidden_str = f"[green]{n_clean_suspect}[/green]  ({pct_hide:.2f}%)"

    t.add_row("total frames",         str(n))
    t.add_row("dropout = 1",          f"{n_drop}  ({pct_drop:.2f}%)")
    t.add_row("suspect |ω| > cap",    f"{n_suspect}  ({pct_susp:.2f}%)")
    t.add_row("hidden suspects",      hidden_str)
    t.add_row("median Δt",
              f"{dt_med * 1000:.2f} ms  ({1.0 / dt_med:.2f} fps)")
    console.print(t)


def render_arm_breakdown(arm_data: dict) -> None:
    """Per-arm suspect counts. arm_data: {arm1_only, arm2_only, both}."""
    t = Table(title="Per-arm Suspects (clean rows only)",
              box=rich.box.SIMPLE_HEAD)
    t.add_column("Arm", style="dim")
    t.add_column("Count", style="white", justify="right")
    t.add_row("|ω₁| only", str(arm_data.get("arm1_only", 0)))
    t.add_row("|ω₂| only", str(arm_data.get("arm2_only", 0)))
    t.add_row("both",       str(arm_data.get("both", 0)))
    console.print(t)


def render_phase_summary(phase_data: dict) -> None:
    """Holding vs free_swing breakdown. phase_data:
       {"holding": {"suspect": N, "total_clean": M},
        "free_swing": {...}}"""
    t = Table(title="Phase Summary", box=rich.box.SIMPLE_HEAD)
    t.add_column("Phase",     style="white")
    t.add_column("Suspect",   justify="right", style="white")
    t.add_column("Total",     justify="right", style="white")
    t.add_column("Clean %",   justify="right", style="white")

    for phase in ("holding", "free_swing"):
        d = phase_data.get(phase, {"suspect": 0, "total_clean": 0})
        sus = int(d.get("suspect", 0))
        tot = int(d.get("total_clean", 0))
        if tot > 0:
            clean_pct = 100.0 * (tot - sus) / tot
            dropout_pct = 100.0 - clean_pct
            color = _dropout_color(dropout_pct)
            pct_cell = f"[{color}]{clean_pct:.2f}%[/{color}]"
        else:
            pct_cell = "[dim]—[/dim]"
        phase_cell = (f"[dim blue]{phase}[/dim blue]"
                      if phase == "holding"
                      else f"[cyan]{phase}[/cyan]")
        t.add_row(phase_cell, str(sus), str(tot), pct_cell)
    console.print(t)


def render_suspect_table(suspects: list,
                         omega_cap: float = 2500.0) -> None:
    """Top suspect frames. Each suspect dict carries:
       frame, time_s, phase, th1, th2, om1, om2.
       Optional: arm_length_px, arm_length_dev_pct (Brief 3).

       Caps display at SUSPECT_TABLE_CAP rows with a "… and N more"
       footer for longer lists."""
    if not suspects:
        console.print("  [dim italic]No suspect frames (dropout=0).[/]")
        return

    show_arm = any(s.get("arm_length_px") is not None for s in suspects)

    t = Table(title=(f"Top Suspect Frames  "
                     f"[dropout=0, ω_cap={omega_cap:.0f} °/s]"),
              box=rich.box.SIMPLE_HEAD)
    t.add_column("frame",   justify="right", style="white")
    t.add_column("time(s)", justify="right", style="dim")
    t.add_column("phase",   style="white")
    t.add_column("θ₁",      justify="right", style="white")
    t.add_column("θ₂",      justify="right", style="white")
    t.add_column("|ω₁|",    justify="right", style="white")
    t.add_column("|ω₂|",    justify="right", style="white")
    if show_arm:
        t.add_column("arm L", justify="right", style="white")

    capped = suspects[:SUSPECT_TABLE_CAP]
    for s in capped:
        phase = s.get("phase", "")
        phase_cell = (f"[dim blue]{phase}[/dim blue]"
                      if phase == "holding"
                      else f"[cyan]{phase}[/cyan]")
        om1, om2 = abs(float(s.get("om1", 0))), abs(float(s.get("om2", 0)))
        om1_cell = f"[{_omega_color(om1)}]{om1:.0f} °/s[/]"
        om2_cell = f"[{_omega_color(om2)}]{om2:.0f} °/s[/]"
        row = [
            str(int(s["frame"])),
            f"{float(s['time_s']):.3f}",
            phase_cell,
            f"{float(s['th1']):.2f}",
            f"{float(s['th2']):.2f}",
            om1_cell,
            om2_cell,
        ]
        if show_arm:
            arm_l = s.get("arm_length_px")
            dev   = s.get("arm_length_dev_pct")
            if arm_l is None:
                row.append("[dim]—[/dim]")
            else:
                if dev is None or dev < 5:
                    c = "green"
                elif dev < 10:
                    c = "yellow"
                else:
                    c = "red"
                row.append(f"[{c}]{arm_l:.1f}[/{c}]")
        t.add_row(*row)
    console.print(t)

    if len(suspects) > SUSPECT_TABLE_CAP:
        console.print(
            f"  [dim italic]… and {len(suspects) - SUSPECT_TABLE_CAP}"
            f" more.[/]")


def render_arm_length_violations(violations: list) -> None:
    """Rigid-body sanity check (Brief 3). Skips silently when empty."""
    if not violations:
        return

    t = Table(title="Arm Length Violations  (rigid-body check)",
              box=rich.box.SIMPLE_HEAD,
              caption=("[dim]Arm length should be constant (rigid arm). "
                       "Deviations indicate tracker latched onto wrong "
                       "object.[/]"))
    t.add_column("frame",        justify="right", style="white")
    t.add_column("time(s)",      justify="right", style="dim")
    t.add_column("phase",        style="white")
    t.add_column("arm L (px)",   justify="right", style="white")
    t.add_column("median L",     justify="right", style="dim")
    t.add_column("deviation %",  justify="right", style="white")

    for v in violations:
        phase = v.get("phase", "")
        phase_cell = (f"[dim blue]{phase}[/dim blue]"
                      if phase == "holding"
                      else f"[cyan]{phase}[/cyan]")
        dev = float(v["dev_pct"])
        if 5 <= dev < 10:
            dev_cell = f"[yellow]{dev:.1f}%[/yellow]"
        elif dev >= 10:
            dev_cell = f"[red]{dev:.1f}%[/red]"
        else:
            dev_cell = f"{dev:.1f}%"
        t.add_row(str(int(v["frame"])),
                  f"{float(v['time_s']):.3f}",
                  phase_cell,
                  f"{float(v['arm_length_px']):.1f}",
                  f"{float(v['median_arm_px']):.1f}",
                  dev_cell)
    console.print(t)


# ─────────────────────────────────────────────
# RENDER FUNCTIONS — interpolation stage
# ─────────────────────────────────────────────

def render_interpolation_plan(suspect_idxs: list,
                              track_rows: list,
                              verif_by_frame: dict,
                              *,
                              dry_run: bool = False) -> None:
    """Pre-fix plan: for each suspect frame, show its current θ₂, the
    clean neighbours' θ₂ values, and the |ω₂| that flagged it.

    `verif_by_frame` is a dict keyed by int(frame) — built upstream;
    no positional fallback (Brief 2).
    """
    title = f"Interpolation Plan  ({len(suspect_idxs)} suspects)"
    if dry_run:
        title += "  [bold yellow][DRY-RUN][/]"

    t = Table(title=title, box=rich.box.SIMPLE_HEAD)
    t.add_column("frame",      justify="right", style="white")
    t.add_column("time(s)",    justify="right", style="dim")
    t.add_column("phase",      style="white")
    t.add_column("θ₂ before",  justify="right", style="white")
    t.add_column("prev θ₂",    justify="right", style="dim")
    t.add_column("next θ₂",    justify="right", style="dim")
    t.add_column("|ω₂|",       justify="right", style="white")

    capped = suspect_idxs[:SUSPECT_TABLE_CAP]
    for i in capped:
        target = track_rows[i]
        prev_idx, next_idx = find_neighbours(track_rows, i)
        phase = target.get("phase", "")
        phase_cell = (f"[dim blue]{phase}[/dim blue]"
                      if phase == "holding"
                      else f"[cyan]{phase}[/cyan]")
        prev_v = (track_rows[prev_idx]["theta2_deg"]
                  if prev_idx is not None else "—")
        next_v = (track_rows[next_idx]["theta2_deg"]
                  if next_idx is not None else "—")

        vrow = verif_by_frame.get(int(target["frame"]), {})
        try:
            om2 = abs(float(vrow.get("omega2_deg_s") or 0))
            om2_cell = f"[{_omega_color(om2)}]{om2:.0f}[/]"
        except (TypeError, ValueError):
            om2_cell = "[dim]—[/dim]"

        t.add_row(str(int(target["frame"])),
                  f"{float(target['time_s']):.3f}",
                  phase_cell,
                  str(target.get("theta2_deg") or "—"),
                  str(prev_v),
                  str(next_v),
                  om2_cell)
    console.print(t)
    if len(suspect_idxs) > SUSPECT_TABLE_CAP:
        console.print(
            f"  [dim italic]… and "
            f"{len(suspect_idxs) - SUSPECT_TABLE_CAP} more.[/]")


# ─────────────────────────────────────────────
# RENDER FUNCTIONS — verdict stage
# ─────────────────────────────────────────────

_STATUS_BADGE = {
    "PASS": ("[bold green]✓  PASS[/]",   "green"),
    "WARN": ("[bold yellow]⚠  WARN[/]",  "yellow"),
    "FAIL": ("[bold red]✗  FAIL[/]",     "red"),
}

_GENERIC_NEXT_STEPS = {
    "PASS": "tracking_quality auto-set to 'verified' in the registry.",
    "WARN": ("Review verification.png; if acceptable, "
             "set tracking_quality=verified manually."),
    "FAIL": ("Inspect debug.mp4 or re-run with --debug; consider "
             "hsv_tuner re-calibration or a different release frame."),
}


def _format_pre_post(pre, post, color, n_label):
    """Render a 'pre → post' or 'value' cell for dropout %."""
    if pre is None and post is None:
        return "—"
    if pre == post or post is None:
        v = pre if pre is not None else post
        bar = _make_dropout_bar(v if v is not None else 0)
        return (f"[{color}]{v:.2f}%[/]  {bar}  "
                f"({n_label} frames)")
    bar = _make_dropout_bar(post if post is not None else 0)
    return (f"[dim]{(pre or 0):.2f}%[/] → [{color}]{(post or 0):.2f}%[/]  "
            f"{bar}  ({n_label} frames)")


def render_verdict(stem: str,
                   video_path: str,
                   key: str,
                   entry: dict,
                   *,
                   status: str,
                   reasons: list,
                   metrics_pre: dict | None,
                   metrics_post: dict | None,
                   n_interpolated: int,
                   hsv_kind: str,
                   total_elapsed: float,
                   actionable_steps: list | None = None) -> str:
    """Render the verdict panel and return its plain-text export so the
    caller can append it to the verdict log file."""
    badge, border = _STATUS_BADGE.get(status, _STATUS_BADGE["FAIL"])

    # ── Identity ───────────────────────────────────────────────────
    id_table = _kv_table()
    id_table.add_row("video",        os.path.basename(video_path))
    id_table.add_row("registry key", str(key))
    id_table.add_row("HSV used",     str(hsv_kind))

    # ── Signal Quality ─────────────────────────────────────────────
    metrics = metrics_post or metrics_pre or {}
    n_free      = metrics.get("n_free_swing", "—")
    n_init      = entry.get("init_frame", "—")
    n_release   = entry.get("release_frame", "—")
    drop_free_pre  = (metrics_pre  or {}).get("free_swing_dropout_pct")
    drop_free_post = (metrics_post or {}).get("free_swing_dropout_pct")
    drop_hold_pre  = (metrics_pre  or {}).get("holding_dropout_pct")
    drop_hold_post = (metrics_post or {}).get("holding_dropout_pct")
    n_drop_free = metrics.get("n_dropout_free_swing", "—")
    n_drop_hold = metrics.get("n_dropout_holding",    "—")
    n_susp_pre  = (metrics_pre  or {}).get("n_suspect_hidden", 0)
    n_susp_post = (metrics_post or {}).get("n_suspect_hidden", 0)

    sq_table = _kv_table()
    sq_table.add_row(
        "frames",
        f"init {n_init}  /  release {n_release}  /  free {n_free}")

    drop_hold_color = (_dropout_color(drop_hold_post or drop_hold_pre or 0)
                       if (drop_hold_pre is not None or
                           drop_hold_post is not None) else "white")
    sq_table.add_row(
        "holding dropout",
        _format_pre_post(drop_hold_pre, drop_hold_post,
                         drop_hold_color, n_drop_hold))

    drop_free_color = (_dropout_color(drop_free_post or drop_free_pre or 0)
                       if (drop_free_pre is not None or
                           drop_free_post is not None) else "white")
    sq_table.add_row(
        "free dropout",
        _format_pre_post(drop_free_pre, drop_free_post,
                         drop_free_color, n_drop_free))

    if n_susp_post == 0:
        susp_color = "green"
    elif n_susp_post <= 2:
        susp_color = "yellow"
    else:
        susp_color = "red"
    if n_interpolated > 0:
        suspects_cell = (f"pre: {n_susp_pre}  [dim]→  interp: "
                         f"{n_interpolated}  →[/]  post: "
                         f"[{susp_color}]{n_susp_post}[/]")
    else:
        suspects_cell = f"[{susp_color}]{n_susp_pre}[/]"
    sq_table.add_row("suspects", suspects_cell)

    # ── Physical Diagnostics ───────────────────────────────────────
    peak1 = (metrics_post or metrics_pre or {}).get("peak_omega1", 0.0)
    peak2 = (metrics_post or metrics_pre or {}).get("peak_omega2", 0.0)

    def omega_value(peak_val):
        color = _omega_color(peak_val)
        bar   = _make_omega_bar(peak_val)
        note  = ("  [dim]⚠ > 1500 physical limit[/]"
                 if peak_val > PEAK_OMEGA_PHYSICAL else "")
        return f"[{color}]{peak_val:.0f} °/s[/]  {bar}{note}"

    pd_table = _kv_table()
    pd_table.add_row("peak |ω₁|", omega_value(peak1))
    pd_table.add_row("peak |ω₂|", omega_value(peak2))

    arm_dev = (metrics_post or {}).get("arm_length_dev_max_pct")
    if arm_dev is not None:
        if arm_dev < 5:
            dev_color = "green"
        elif arm_dev < 10:
            dev_color = "yellow"
        else:
            dev_color = "red"
        pd_table.add_row("arm L deviation",
                         f"[{dev_color}]{arm_dev:.1f}%[/] max")

    body = [
        Rule("Identity", style="dim"), id_table,
        Rule("Signal Quality", style="dim"), sq_table,
        Rule("Physical Diagnostics", style="dim"), pd_table,
    ]

    # ── Reasons (optional inner Panel) ─────────────────────────────
    if reasons:
        reason_color = {"PASS": "green", "WARN": "yellow",
                        "FAIL": "red"}[status]
        reason_text = Text()
        for i, r in enumerate(reasons):
            if i:
                reason_text.append("\n")
            reason_text.append(f"  • {r}", style=reason_color)
        body.append(
            Panel(reason_text, title="Reasons",
                  border_style=f"{reason_color} dim", padding=(0, 1)))

    # ── Next Steps ─────────────────────────────────────────────────
    body.append(Rule("next steps", style="dim"))
    if actionable_steps:
        steps_table = Table(box=None, show_header=False, padding=(0, 1),
                            expand=False)
        steps_table.add_column(no_wrap=True)
        steps_table.add_column()
        for step in actionable_steps:
            pri = step.get("priority", "info")
            text = step.get("text", "")
            cmd  = step.get("command")
            badge_cell = {
                "required": "[bold white on red] required [/]",
                "review":   "[bold black on yellow] review  [/]",
                "info":     "[dim] info     [/]",
            }.get(pri, "[dim] info     [/]")
            # Append the copy-paste command (if present) on a new line
            # in dim monospace below the instruction text.
            instruction = text
            if cmd:
                instruction = f"{text}\n[dim]  $ {cmd}[/]"
            steps_table.add_row(badge_cell, instruction)
        body.append(steps_table)
    else:
        body.append(Text(
            f"  {_GENERIC_NEXT_STEPS.get(status, '—')}",
            style="dim italic"))

    # Right-aligned elapsed under the next-step block.
    body.append(Align.right(
        Text(f"elapsed: {total_elapsed:.0f}s", style="dim")))

    panel = Panel(
        Group(*body),
        title=f"{badge}  [bold white]{stem}[/]",
        border_style=border,
        padding=(1, 2),
    )

    console.print(panel)

    # Build a frozen-width recording console for log export so the
    # logged width doesn't depend on the live terminal. The recording
    # console writes into an internal StringIO so it doesn't double up
    # on stdout — we only want its export_text output.
    rec = Console(record=True, width=LOG_CONSOLE_WIDTH,
                  force_terminal=False, file=io.StringIO())
    rec.print(panel)
    return rec.export_text()


# ─────────────────────────────────────────────
# RENDER FUNCTIONS — bulk stage
# ─────────────────────────────────────────────

_VERDICT_BADGE_BULK = {
    "PASS": "[bold green]✓ PASS[/]",
    "WARN": "[bold yellow]⚠ WARN[/]",
    "FAIL": "[bold red]✗ FAIL[/]",
}


def render_bulk_summary(results: list) -> None:
    """One row per clip in the recent bulk run, sorted worst-first."""
    if not results:
        console.print("[dim italic]No bulk results to summarize.[/]")
        return

    # Sort by dropout descending, None last.
    def sort_key(r):
        d = r.get("dropout_pct")
        return (d is None, -(d if d is not None else 0))
    rows = sorted(results, key=sort_key)

    t = Table(title="Bulk Track Summary", box=rich.box.SIMPLE_HEAD)
    t.add_column("#",            justify="right", style="dim")
    t.add_column("Experiment",   style="white")
    t.add_column("Verdict",      style="white")
    t.add_column("Free Dropout", style="white")
    t.add_column("Elapsed",      justify="right", style="dim")

    n_pass = n_warn = n_fail = 0
    for i, r in enumerate(rows, start=1):
        status = r.get("status", "FAIL")
        if status == "PASS": n_pass += 1
        elif status == "WARN": n_warn += 1
        else: n_fail += 1
        verdict_cell = _VERDICT_BADGE_BULK.get(status,
                                               _VERDICT_BADGE_BULK["FAIL"])
        d = r.get("dropout_pct")
        if d is None:
            drop_cell = "[dim]—[/dim]"
        else:
            color = _dropout_color(d)
            bar = _make_dropout_bar(d)
            drop_cell = f"[{color}]{d:.2f}%[/]  {bar}"
        t.add_row(str(i),
                  str(r.get("stem", "?")),
                  verdict_cell,
                  drop_cell,
                  f"{float(r.get('elapsed_s', 0)):.0f}s")
    console.print(t)
    console.print(f"  {n_pass} passed  ·  {n_warn} warned  ·  "
                  f"{n_fail} failed")


# ─────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    mock_metrics_pre = {
        "n_total": 1056, "n_dropout_total": 143,
        "n_dropout_holding": 73, "n_dropout_free_swing": 70,
        "n_holding": 876, "n_free_swing": 913,
        "n_suspect_hidden": 1,
        "peak_omega1": 4151.0, "peak_omega2": 2426.0,
        "free_swing_dropout_pct": 7.12,
        "holding_dropout_pct": 8.33,
    }
    mock_metrics_post = {**mock_metrics_pre,
                         "n_dropout_free_swing": 69,
                         "free_swing_dropout_pct": 7.05,
                         "n_suspect_hidden": 1}
    mock_entry = {"init_frame": 73, "release_frame": 73}
    mock_suspects = [
        {"frame": 227, "time_s": 3.787, "phase": "free_swing",
         "th1": 9.58, "th2": 63.83, "om1": 4151.0, "om2": 2426.0},
    ]
    mock_phase_data = {
        "holding":    {"suspect": 0, "total_clean": 0},
        "free_swing": {"suspect": 1, "total_clean": 913},
    }
    mock_violations = [
        {"frame": 227, "time_s": 3.787, "phase": "free_swing",
         "arm_length_px": 231.4, "median_arm_px": 188.0, "dev_pct": 23.1},
    ]

    render_verification_summary(1056, 143, 71, 1, 1.0 / 60.0)
    render_arm_breakdown({"arm1_only": 0, "arm2_only": 1, "both": 0})
    render_phase_summary(mock_phase_data)
    render_suspect_table(mock_suspects, omega_cap=2500.0)
    render_arm_length_violations(mock_violations)
    txt = render_verdict(
        stem="th1_p001_th2_p093",
        video_path=r"C:\dev\chaos\Videos\th1_p001_th2_p093.mov",
        key="th1_p001_th2_p093",
        entry=mock_entry,
        status="WARN",
        reasons=[
            "free-swing dropout 7.1% in 5-10% band",
            "1 residual suspect post-interpolation",
            "peak |omega2| 2426 deg/s > 1500 deg/s physical rule-of-thumb",
        ],
        metrics_pre=mock_metrics_pre,
        metrics_post=mock_metrics_post,
        n_interpolated=1,
        hsv_kind="global",
        total_elapsed=42.0,
        actionable_steps=None,
    )
    print(f"\n[exported text length: {len(txt)} chars, locked width "
          f"{LOG_CONSOLE_WIDTH}]\n")
    render_bulk_summary([
        {"stem": "th1_p001_th2_p093", "status": "WARN",
         "dropout_pct": 7.12, "elapsed_s": 42.0},
        {"stem": "th1_p180_th2_m179", "status": "PASS",
         "dropout_pct": 2.1,  "elapsed_s": 118.0},
        {"stem": "th1_p044_th2_m001", "status": "FAIL",
         "dropout_pct": 14.5, "elapsed_s": 37.0},
    ])
