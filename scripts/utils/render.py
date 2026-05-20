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
    DROPOUT_FAIL_PCT,
    DROPOUT_BAR_MAX,
)
from csv_helpers import is_clean_row, find_neighbours  # noqa: E402,F401

# math.isnan handles plain floats and numpy scalars without forcing a
# numpy dependency on this module's import time.
import math as _math


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

def _dropout_color(pct: float) -> str:
    if pct <= DROPOUT_FAIL_PCT:
        return "green"
    return "red"


def _omega_color(value: float) -> str:
    """Vestigial stub — referenced only by legacy verification-render
    helpers that aren't called by the current pipeline. Returns
    'white' so any incidental call doesn't crash."""
    return "white"


def _make_bar(value: float, max_val: float, width: int = 20,
              color: str = "green") -> str:
    """Single-colour bar — fill chars in `color`, empty chars dim."""
    filled = min(int(round(value / max_val * width)), width)
    empty  = width - filled
    return f"[{color}]{'━' * filled}[/{color}]{'░' * empty}"


def _make_dropout_bar(pct: float, width: int = 20) -> str:
    """Two-zone dropout bar: green up to DROPOUT_FAIL_PCT, red beyond."""
    pass_end = int(round(DROPOUT_FAIL_PCT / DROPOUT_BAR_MAX * width))
    warn_end = pass_end  # binary verdict, no middle band
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
                                dt_med: float,
                                extras: dict | None = None) -> None:
    """Top-of-verify summary table: total frames, dropout %, suspect %,
    hidden-suspect %, median Δt.

    `extras` (Brief 5+) carries optional new-check counts. Keys:
      n_accel_suspect : int — frames flagged by Δω cap
      n_swap_suspect  : int — frames where green/red appear to have swapped
    Each row is appended only when its key is present and > 0; clean
    clips don't sprout zero-rows."""
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

    if extras:
        n_accel = extras.get("n_accel_suspect", 0)
        if n_accel > 0:
            t.add_row("accel suspects |Δω| > cap",
                      f"[red]{n_accel}[/red]  "
                      f"[dim](unphysical Δω between consecutive frames)[/]")
        n_swap = extras.get("n_swap_suspect", 0)
        if n_swap > 0:
            t.add_row("swap suspects",
                      f"[red]{n_swap}[/red]  "
                      f"[dim](green/red markers appear to exchange "
                      f"positions)[/]")
        # Brief 6 — physics checks. Each row only appears when its
        # count is > 0 so clean clips don't sprout zero-rows.
        n_res = extras.get("n_residual_suspect", 0)
        if n_res > 0:
            t.add_row(
                "θ-residual suspects",
                f"[red]{n_res}[/red]  "
                f"[dim](θ[i] vs θ[i-1]+ω[i-1]·dt — catches slow drifts "
                f"near ω zero-crossings that escape the Δω cap)[/]")

        n_eng       = extras.get("n_energy_suspect", 0)
        n_eng_ceil  = extras.get("n_energy_ceiling_suspect", 0)
        n_eng_roll  = extras.get("n_energy_rolling_spike", 0)
        if n_eng > 0:
            t.add_row(
                "energy suspects (total)",
                f"[red]{n_eng}[/red]  "
                f"[dim](E > E_release×headroom = stable latch; "
                f"E/baseline > factor = transition teleport)[/]")
            ceil_color = "red" if n_eng_ceil > 0 else "dim"
            roll_color = "red" if n_eng_roll > 0 else "dim"
            t.add_row(
                "  ↳ above release ceiling",
                f"[{ceil_color}]{n_eng_ceil}[/]")
            t.add_row(
                "  ↳ rolling spike",
                f"[{roll_color}]{n_eng_roll}[/]")

        n_trend_susp = extras.get("n_trend_arm_suspect", 0)
        n_trend_win  = extras.get("n_trend_windows", 0)
        if n_trend_win > 0:
            from thresholds import ARM_LENGTH_TREND_WINDOW as _TW
            t.add_row(
                "trend arm-length suspects",
                f"[red]{n_trend_susp}[/red]  "
                f"[dim]({n_trend_win} window(s) of {_TW} frames "
                f"drifted from reference)[/]")
            t.add_row(
                "",
                "[dim](sliding-window arm-length median drift — catches "
                "stable wrong-target episodes missed by per-frame check)[/]")
    console.print(t)


def render_pivot_check(hardcoded: tuple,
                       inferred: tuple,
                       drift_px: float,
                       max_arm_dev_pct: float | None = None) -> None:
    """
    Print a single kv-table row summarising pivot consistency.
    Called from verify_tracking after the arm-length block.

    Brief 11b — when MAX arm-length deviation across clean frames
    exceeds 15%, the back-projected pivot is meaningless because
    green_pos and θ₁ are both corrupted on the violating frames and
    the median pulls the implied-pivot estimate around. Render a
    "check unreliable" row instead of a misleading drift number.

    Mean arm-deviation is not a useful proxy here — it stays under 2%
    even on heavily corrupted clips because the global-median normaliser
    used by the per-frame check biases toward the majority object.
    """
    if drift_px is None or (isinstance(drift_px, float)
                            and _math.isnan(drift_px)):
        console.print("[dim]  pivot check  — insufficient clean frames[/]")
        return

    if (max_arm_dev_pct is not None
            and not (isinstance(max_arm_dev_pct, float)
                     and _math.isnan(max_arm_dev_pct))
            and max_arm_dev_pct > 15.0):
        t = _kv_table()
        t.add_row(
            "pivot check",
            f"[dim]inferred ({inferred[0]:.1f}, {inferred[1]:.1f}), "
            f"drift {drift_px:.1f} px[/]  "
            f"[yellow]unreliable — max arm deviation "
            f"{max_arm_dev_pct:.1f}% indicates corrupted tracking; "
            f"fix tracking first[/]"
        )
        console.print(t)
        return

    if drift_px < PIVOT_DRIFT_WARN_PX:
        color, note = "green", ""
    elif drift_px < PIVOT_DRIFT_FAIL_PX:
        color, note = "yellow", "  [dim]minor camera shift[/]"
    else:
        color, note = "red", (
            "  [red]ring geometry may be wrong — "
            "update PIVOT in thresholds.py[/]")

    t = _kv_table()
    t.add_row(
        "pivot check",
        f"hardcoded {hardcoded}  →  "
        f"inferred ({inferred[0]:.1f}, {inferred[1]:.1f})  "
        f"[{color}]drift {drift_px:.1f} px[/]{note}"
    )
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
    "FAIL": ("[bold red]✗  FAIL[/]",     "red"),
}

_GENERIC_NEXT_STEPS = {
    "PASS": "tracking_quality auto-set to 'verified' in the registry.",
    "FAIL": ("Inspect verification.png and the diagnostic frames "
             "(scripts/utils/diagnose_frames.py); fix outliers with "
             "chaos override, or accept the clip as untrackable."),
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
                   actionable_steps: list | None = None,
                   energy_omega_cap: float | None = None) -> str:
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
    n_total = metrics.get("n_total", "—")
    n_drop  = metrics.get("n_dropout", "—")
    drop_pct = metrics.get("dropout_pct")

    sq_table = _kv_table()
    sq_table.add_row("frames", str(n_total))
    if drop_pct is not None:
        color = _dropout_color(drop_pct)
        bar = _make_dropout_bar(drop_pct)
        sq_table.add_row(
            "dropout",
            f"[{color}]{drop_pct:.2f}%[/]  {bar}  ({n_drop} frames)")
    else:
        sq_table.add_row("dropout", "—")

    body = [
        Rule("Identity", style="dim"), id_table,
        Rule("Signal Quality", style="dim"), sq_table,
    ]

    # ── Reasons (optional inner Panel) ─────────────────────────────
    if reasons:
        reason_color = {"PASS": "green", "FAIL": "red"}.get(status, "yellow")
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

    n_pass = n_fail = 0
    for i, r in enumerate(rows, start=1):
        status = r.get("status", "FAIL")
        if status == "PASS":
            n_pass += 1
        else:
            n_fail += 1
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
    console.print(f"  {n_pass} passed  ·  {n_fail} failed")


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

    render_verification_summary(
        1056, 143, 71, 1, 1.0 / 60.0,
        extras={
            "n_accel_suspect":           4,
            "n_swap_suspect":            0,
            "n_residual_suspect":        2,
            "n_energy_suspect":          7,
            "n_energy_ceiling_suspect":  6,
            "n_energy_rolling_spike":    1,
            "n_trend_arm_suspect":      150,
            "n_trend_windows":           3,
        })
    render_arm_breakdown({"arm1_only": 0, "arm2_only": 1, "both": 0})
    render_phase_summary(mock_phase_data)
    render_suspect_table(mock_suspects, omega_cap=2500.0)
    render_arm_length_violations(mock_violations)
    from thresholds import PIVOT as _PIVOT_DEMO
    render_pivot_check(_PIVOT_DEMO, (_PIVOT_DEMO[0] + 2.3,
                                    _PIVOT_DEMO[1] + 3.1), 3.8)
    render_pivot_check(_PIVOT_DEMO, (_PIVOT_DEMO[0] + 7.0,
                                    _PIVOT_DEMO[1] + 10.0), 12.2)
    render_pivot_check(_PIVOT_DEMO, (_PIVOT_DEMO[0] + 32.0,
                                    _PIVOT_DEMO[1] + 25.0), 40.6)
    txt = render_verdict(
        stem="th1_p001_th2_p093",
        video_path=r"C:\dev\chaos\Videos\th1_p001_th2_p093.mov",
        key="th1_p001_th2_p093",
        entry=mock_entry,
        status="FAIL",
        reasons=[
            "dropout 7.1% > 5% — tracker missed markers too often",
            "3 arm-length violation(s) (max 18%) — wrong-blob signal",
        ],
        metrics_pre=mock_metrics_pre,
        metrics_post=mock_metrics_post,
        n_interpolated=1,
        hsv_kind="global",
        total_elapsed=42.0,
        actionable_steps=None,
        energy_omega_cap=1820.0,
    )
    print(f"\n[exported text length: {len(txt)} chars, locked width "
          f"{LOG_CONSOLE_WIDTH}]\n")
    render_bulk_summary([
        {"stem": "th1_p001_th2_p093", "status": "FAIL",
         "dropout_pct": 7.12, "elapsed_s": 42.0},
        {"stem": "th1_p180_th2_m179", "status": "PASS",
         "dropout_pct": 2.1,  "elapsed_s": 118.0},
        {"stem": "th1_p044_th2_m001", "status": "FAIL",
         "dropout_pct": 14.5, "elapsed_s": 37.0},
    ])
