# Rich Harmonization — Claude Code Prompt

## Context

The `chaos` CLI has been partially Rich-ified. The interactive shell (`scripts/utils/shell.py`) and the main hub are polished with Rich Panels, Tables, colored progress bars, and questionary pickers. But the **individual subcommand scripts** still emit raw `print()` output — when you pick "track next" from the shell, the tracking subprocess dumps unstyled text. This creates a jarring visual break between the polished shell and the raw pipeline output underneath.

Your job: go through each subprocess script and harmonize its terminal output to match the design language established in `shell.py` and `scripts/utils/render.py`.

## Design Language (follow these patterns exactly)

### Color assignments (consistent across the project)
- **Green** = verified, pass, success, done
- **Yellow** = tracked (not verified), warning, in-progress
- **Red** = fail, error, chaotic verdict
- **Cyan** = info, metadata, week-5 grouping
- **Magenta** = figures, branding, outer panel borders
- **Dim/gray** = secondary info, timestamps, elapsed time, paths

### Rich components to use
- `Panel(border_style="<color>")` for verdict cards, result summaries, bounded output blocks
- `Table(box=box.SIMPLE_HEAD)` for structured data (never raw column-aligned print)
- `Rule(style="dim")` for section separators (never `"─" * 70` or `"=" * 72`)
- `Text.from_markup()` for inline colored text
- Progress bars: `[green]{"█" * n}[/][dim]{"░" * m}[/]` for visual bars
- Status badges: `[bold green]✓ PASS[/]`, `[bold red]✗ FAIL[/]`, `[bold red]CHAOTIC[/]`, `[bold green]REGULAR[/]`

### What NOT to do
- No raw `print("=" * N)` or `print("─" * N)` box drawing
- No manual column alignment with f-string padding (use Rich Table instead)
- No raw `print(f"  key: value")` for structured data (use kv Table pattern)
- No bare ERROR/WARNING prints — use `console.print("[red]ERROR:[/] message")`
- Don't add Rich imports at the module top level if the script is also imported as a library — use lazy imports inside the output functions
- Don't change any computational logic, file I/O, or return values — only change how results are printed to stdout
- Don't break the existing `render.py` functions that are already Rich — those are the gold standard

### The kv-table pattern (use this for any key-value display)
```python
from rich.table import Table
t = Table(box=None, show_header=False, padding=(0, 1), expand=False)
t.add_column(style="dim", min_width=24)
t.add_column(style="white", justify="right")
t.add_row("some metric", f"{value:.2f}")
console.print(t)
```

### The subprocess banner pattern (already implemented in track_one.py — reference)
```python
from rich.console import Console
from rich.rule import Rule
_con = Console()
_con.print()
_con.print(Rule(f"[bold]{label}[/]", style="dim"))
# ... subprocess runs ...
status = "[green]done[/]" if rc == 0 else f"[red]exit {rc}[/]"
_con.print(f"  {status} [dim]{elapsed:.0f}s[/]")
```

## Scripts to harmonize (in priority order)

### 1. `scripts/processing/bgr_tracker.py`
**Current output:** Raw print at the end: `print(f"Wrote {n_total} rows  dropout={n_drop} ({dropout_pct:.2f}%)")`
**Target:** Replace the final summary with a compact Rich output:
- One line: frames written + dropout with colored bar
- One line: registry path (dim)
- Keep it minimal — this script runs inside track_one's subprocess banner

### 2. `scripts/processing/verify_tracking.py`
**Current output:** Already partially Rich via `render.py` imports, but check for any remaining raw `print()` calls in the main flow (not inside render functions).
**Target:** Ensure all direct `print()` in this file's `main()` or helper functions use `console.print()` with markup. The render.py functions it calls are already good — don't touch those.

### 3. `scripts/utils/bulk_track.py`
**Current output:** Raw print for the per-clip progress and summary.
**Target:**
- Per-clip line: `[1/25]  3.2V_0.95Hz ...` should use Rich markup with colored clip name and status
- Summary: use the existing `render_bulk_summary()` from render.py if it's not already wired, or build a similar Rich Table
- Don't duplicate what render.py already provides

### 4. `scripts/utils/audit.py`
**Current output:** Has its own `render_audit_table()` and `render_summary()` — check if these are Rich or raw print. The tail of the file has raw `print()` for the apply/upgrade results.
**Target:** Ensure `render_audit_table` and `render_summary` use Rich Tables. Convert the "Applied: N downgraded, N upgraded" summary to Rich markup.

### 5. `scripts/utils/generate_status_report.py`
**Current output:** Likely minimal print (generates a file). Check for any progress/completion messages.
**Target:** Brief Rich confirmation: `console.print(f"  [green]✓[/] Wrote [dim]{path}[/]")`

### 6. `scripts/utils/generate_roadmap.py`
**Current output:** Similar to above — generates a file.
**Target:** Same brief Rich confirmation pattern.

### 7. `scripts/analysis/chaos_analyze.py`
**Current output:** Already Rich-ified (Rich Panel with topological/statistical tables). But check the `main()` function for the initial load line: `print(f"  {stem}: {data['n_frames']} free_swing frames, ...")` and the final plot path print.
**Target:** Convert those 2-3 remaining raw prints to `console.print()` with dim markup for paths.

### 8. `scripts/analysis/poincare.py`
**Current output:** Check for any print statements.
**Target:** If it prints results (crossing count, output path), use Rich markup. If it's silent (just writes files), leave it alone.

### 9. `scripts/analysis/lyapunov.py`
**Current output:** Likely prints λ₁ estimate and fit quality.
**Target:** Small Rich Panel or kv-table showing: λ₁ value (bold, colored by magnitude), R² fit quality, embedding parameters used, output path (dim).

### 10. `scripts/analysis/driven_poincare.py` and `driven_bifurcation.py`
**Current output:** Check for prints.
**Target:** Same pattern — Rich output for results, dim for paths.

### 11. `scripts/analysis/phase_panels.py`, `phase_3d.py`, `phase_animation.py`, `combined_video.py`
**Current output:** These are figure/video generators. Likely minimal output.
**Target:** If they print anything, make it a single dim confirmation line: `console.print(f"  [dim]Saved → {path}[/]")`

### 12. `scripts/utils/batch_figures.py`
**Current output:** Partially Rich-ified (summary footer uses Rich). But the per-figure `[ run] ... OK/FAIL` lines are still raw print with ANSI escapes.
**Target:** Replace per-figure lines with Rich markup:
```python
console.print(f"  [dim]{fig_type:<16}[/] [green]OK[/]  [dim]{relpath}[/]")
# or on failure:
console.print(f"  [dim]{fig_type:<16}[/] [red]FAIL[/]")
```

## How to verify your work

After harmonizing each script, test it through the shell:
1. `chaos` → `t` → `n` (track next) — the tracking output should feel cohesive inside the shell
2. `chaos` → `a` → `c` (chaos card) — the analysis card should render cleanly
3. `chaos` → `f` → `fa` (all figures) — batch progress should be readable
4. `chaos` → `s` (status) — the stacked panels should render correctly

Also test standalone invocations to ensure backward compatibility:
- `chaos track 3.2V_0.9Hz` should still work and look good
- `chaos status` should show the Rich table
- `chaos analyze 3.2V_0.9Hz` should show the Rich panel

## Files to read first (for context)

Before making changes, read these to understand the established patterns:
- `scripts/utils/shell.py` — the hub, picker, and rendering functions
- `scripts/utils/render.py` — the existing Rich rendering module (verdict card, verification summary, bulk summary)
- `scripts/utils/thresholds.py` — constants referenced by render.py
- `scripts/utils/track_one.py` — the `run()` function shows the subprocess banner pattern
- `scripts/utils/paths.py` — understand PHASE, clip_dir, MEAS_DIR etc.

## Ground rules

1. Only change print/output code. Never change computation, file I/O, data structures, or return values.
2. Use lazy imports (`from rich.console import Console` inside the function) for scripts that are imported as modules elsewhere.
3. Test that the script still works standalone (`python scripts/analysis/lyapunov.py --stem 3.2V_0.9Hz`) after your changes.
4. If a script already delegates to render.py for its output, don't duplicate — just ensure the remaining raw prints in main() are converted.
5. Keep output concise. The goal is higher signal-to-noise, not more output. If a script currently prints 3 lines of noise, replacing them with 1 Rich-formatted line is better than 3 Rich-formatted lines.
