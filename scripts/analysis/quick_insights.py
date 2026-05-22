"""
quick_insights.py — interactive plot explorer for tracking data.

Loads a clip's tracking.csv once, then enters a REPL where single-word
commands render different plotext views instantly. 12 plot types across
4 categories: time series, phase space, physical, chaos diagnostics.

Usage:
    chaos -> a -> qi (from shell)
    python scripts/analysis/quick_insights.py --stem 3.2V_0.9Hz
"""

import argparse
import os
import sys
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "utils"))
from paths import clip_dir, REPO_ROOT
from thresholds import get_pivot_arm

_L = 0.35
_G = 9.8


def _resolve_fdrive(stem):
    """Drive frequency (Hz) parsed from the stem; None for non-driven stems."""
    try:
        from driven_helpers import parse_stem
        return float(parse_stem(stem)["f_drive_hz"])
    except (ValueError, ImportError, KeyError):
        return None


def load_clip(stem):
    """Load tracking.csv and precompute all derived quantities."""
    csv_path = os.path.join(clip_dir(stem), "tracking.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No tracking.csv for {stem}")

    df = pd.read_csv(csv_path)
    clean = df[df["dropout"] == 0].copy().reset_index(drop=True)
    if len(clean) < 10:
        raise ValueError(f"Only {len(clean)} non-dropout frames")

    t = clean["time_s"].values
    th1 = clean["theta1_deg"].values
    th2 = clean["theta2_deg"].values
    xg, yg = clean["x_green"].values, clean["y_green"].values
    xr, yr = clean["x_red"].values, clean["y_red"].values

    dt = np.diff(t)
    dt[dt == 0] = 1e-6
    om1 = np.concatenate([[0], np.diff(th1) / dt])
    om2 = np.concatenate([[0], np.diff(th2) / dt])

    th2_abs = th1 + th2
    om2_abs = om1 + om2

    pivot, arm_px = get_pivot_arm(stem)

    th1_r = np.radians(th1)
    th2_abs_r = np.radians(th2_abs)
    th2_rel_r = np.radians(th2)
    w1_r = np.radians(om1)
    w2_abs_r = np.radians(om2_abs)
    PE = (_G * (3 * _L / 2) * (1 - np.cos(th1_r))
        + _G * (_L / 2) * (1 - np.cos(th2_abs_r)))
    KE = _L**2 * ((2/3) * w1_r**2
        + 0.5 * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1/6) * w2_abs_r**2)
    energy = KE + PE

    return {
        "stem": stem, "n_frames": len(clean),
        "duration_s": float(t[-1] - t[0]),
        "t": t - t[0], "th1": th1, "th2": th2,
        "om1": om1, "om2": om2,
        "th2_abs": th2_abs, "om2_abs": om2_abs,
        "energy": energy,
        "xg": xg, "yg": yg, "xr": xr, "yr": yr,
        "pivot": pivot,
        "f_drive": _resolve_fdrive(stem),
    }


# ─────────────────────────────────────────────
# PLOT RENDERERS
# ─────────────────────────────────────────────

def _setup(plt, title, w=76, h=20):
    plt.clf()
    plt.plotsize(w, h)
    plt.theme("clear")
    plt.axes_color("default")
    plt.ticks_color("default")
    plt.title(title)


def _sub(d, n=800):
    """Subsample factor for plotting."""
    return max(1, len(d["t"]) // n)


def plot_both(d):
    import plotext as plt
    s = _sub(d)
    plt.clf()
    plt.subplots(2, 1)
    plt.plotsize(76, 24)
    plt.theme("clear")

    plt.subplot(1, 1)
    plt.axes_color("default")
    plt.ticks_color("default")
    plt.plot(d["t"][::s], d["th1"][::s], color="green")
    plt.title("\u03b8\u2081(t)")
    plt.ylabel("deg")

    plt.subplot(2, 1)
    plt.axes_color("default")
    plt.ticks_color("default")
    plt.plot(d["t"][::s], d["th2"][::s], color="orange")
    plt.title("\u03b8\u2082(t)")
    plt.xlabel("t (s)")
    plt.ylabel("deg")

    plt.show()


def plot_omega(d):
    import plotext as plt
    s = _sub(d)
    plt.clf()
    plt.subplots(2, 1)
    plt.plotsize(76, 24)
    plt.theme("clear")

    plt.subplot(1, 1)
    plt.axes_color("default")
    plt.ticks_color("default")
    plt.plot(d["t"][::s], d["om1"][::s], color="cyan")
    plt.title("\u03c9\u2081(t)")
    plt.ylabel("\u00b0/s")

    plt.subplot(2, 1)
    plt.axes_color("default")
    plt.ticks_color("default")
    plt.plot(d["t"][::s], d["om2"][::s], color="magenta")
    plt.title("\u03c9\u2082(t)")
    plt.xlabel("t (s)")
    plt.ylabel("\u00b0/s")

    plt.show()


def plot_tip(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "\u03b8\u2082_abs(t) = \u03b8\u2081 + \u03b8\u2082")
    plt.plot(d["t"][::s], d["th2_abs"][::s], color="orange")
    plt.hline(180, color="red")
    plt.hline(-180, color="red")
    plt.hline(90, color="yellow")
    plt.hline(-90, color="yellow")
    plt.xlabel("t (s)")
    plt.ylabel("deg")
    plt.show()


def plot_energy(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "E(t) = KE + PE")
    plt.plot(d["t"][::s], d["energy"][::s], color="orange")
    med = float(np.median(d["energy"]))
    plt.hline(med * 3, color="red")
    plt.xlabel("t (s)")
    plt.ylabel("E (J/kg)")
    plt.show()


def plot_phase1(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "\u03b8\u2081 vs \u03c9\u2081  (arm 1 phase portrait)")
    plt.scatter(d["th1"][::s], d["om1"][::s], color="blue", marker="dot")
    plt.xlabel("\u03b81 (deg)")
    plt.ylabel("\u03c91 (\u00b0/s)")
    plt.show()


def plot_phase2(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "\u03b8\u2082 vs \u03c9\u2082  (arm 2 phase portrait)")
    plt.scatter(d["th2"][::s], d["om2"][::s], color="blue", marker="dot")
    plt.xlabel("\u03b82 (deg)")
    plt.ylabel("\u03c92 (\u00b0/s)")
    plt.show()


def plot_config(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "\u03b8\u2081 vs \u03b8\u2082  (configuration space)")
    plt.scatter(d["th1"][::s], d["th2"][::s], color="blue", marker="dot")
    plt.xlabel("\u03b81 (deg)")
    plt.ylabel("\u03b82 (deg)")
    plt.show()


def plot_full(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "\u03b8\u2082_abs vs \u03c9\u2082_abs  (tip phase portrait)")
    plt.scatter(d["th2_abs"][::s], d["om2_abs"][::s], color="blue", marker="dot")
    plt.xlabel("\u03b82_abs (deg)")
    plt.ylabel("\u03c92_abs (\u00b0/s)")
    plt.show()


def plot_xy(d):
    import plotext as plt
    s = _sub(d)
    _setup(plt, "marker pixel positions")
    plt.scatter(d["xg"][::s], d["yg"][::s], label="green", color="green", marker="dot")
    plt.scatter(d["xr"][::s], d["yr"][::s], label="red", color="red", marker="dot")
    px, py = d["pivot"]
    plt.scatter([px], [py], label="pivot", color="white", marker="x")
    plt.xlabel("x (px)")
    plt.ylabel("y (px)")
    plt.show()


def plot_trace(d):
    import plotext as plt
    s = _sub(d, n=1200)
    _setup(plt, "tip trajectory (red marker path)")
    plt.plot(d["xr"][::s], d["yr"][::s], color="red")
    plt.xlabel("x (px)")
    plt.ylabel("y (px)")
    plt.show()


def plot_spectrum(d):
    import plotext as plt
    th2 = d["th2"]
    N = len(th2)
    if N < 4:
        print("  too few points for FFT")
        return
    dt = float(np.median(np.diff(d["t"])))
    freq = np.fft.rfftfreq(N, d=max(dt, 1e-6))
    spec = np.abs(np.fft.rfft(th2 - th2.mean())) ** 2
    mask = (freq > 0) & (spec > 0)
    if not mask.any():
        print("  empty spectrum")
        return
    _setup(plt, "power spectrum of \u03b8\u2082  (log-log)")
    plt.plot(freq[mask], spec[mask], color="magenta")
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("freq (Hz)")
    plt.ylabel("power")
    plt.show()


def plot_return(d):
    import plotext as plt
    th2 = d["th2"]
    if len(th2) < 20:
        print("  too few points")
        return
    _setup(plt, "\u03b8\u2082(n) vs \u03b8\u2082(n+1)  (return map)")
    plt.scatter(th2[:-1], th2[1:], color="orange", marker="dot")
    plt.xlabel("\u03b82(n)")
    plt.ylabel("\u03b82(n+1)")
    plt.show()


def plot_seismograph(d, mode="v1"):
    """Terminal preview of the seismograph. theta_tip = theta2 (absolute
    lower-arm angle from the green pivot). v1 spiral: r grows with time;
    v2 ripple: r grows with (t_end − t). Colour = time third (legend:
    blue early → orange mid → red late). Full colour figure:
    `chaos figures --types seismograph_v1` (or _v2)."""
    import plotext as plt
    s = _sub(d, n=1500)
    t = d["t"]
    th_tip = np.radians(d["th2"])        # theta2 is already lab-frame absolute
    if mode == "v2":
        r = 1.0 + 1.5 * (t[-1] - t)      # ripple: oldest farthest
        title = "seismograph v2 ripple  (θ_tip = θ₂,  r = t_end−t)"
    else:
        r = 1.0 + 1.5 * (t - t[0])       # spiral: newest farthest
        title = "seismograph v1 spiral  (θ_tip = θ₂,  r = time)"
    x = (r * np.sin(th_tip))[::s]
    y = (-r * np.cos(th_tip))[::s]
    n = len(x)
    a, b = n // 3, 2 * n // 3
    _setup(plt, title, w=58, h=26)
    plt.scatter(x[:a],  y[:a],  color="blue",   marker="dot", label="early (t₀)")
    plt.scatter(x[a:b], y[a:b], color="orange", marker="dot", label="mid")
    plt.scatter(x[b:],  y[b:],  color="red",    marker="dot", label="late (t_end)")
    plt.xlabel("x")
    plt.ylabel("y")
    plt.show()
    # Plain-text colour key in case the plotext legend is clipped.
    print("    ● early (t₀)   ● mid   ● late (t_end)   "
          "[blue → orange → red by time]")


def plot_cyclic_phase(d):
    """#2 cyclic (oscillator) phase ψ(t) per arm — advances 2π per cycle
    even when the arm only swings. Hilbert protophase of the de-trended
    unwrapped angle (shared with phase_analysis.py)."""
    import plotext as plt
    from phase_analysis import cyclic_phase
    t = d["t"]
    s = _sub(d)
    psi1, _ = cyclic_phase(d["th1"])
    psi2, _ = cyclic_phase(d["th2"])
    _setup(plt, "cyclic phase  ψ / 2π  (cycles)")
    plt.plot(t[::s], (psi1 / (2 * np.pi))[::s], color="blue", label="θ₁ upper")
    plt.plot(t[::s], (psi2 / (2 * np.pi))[::s], color="red",  label="θ₂ lower")
    plt.xlabel("t (s)")
    plt.ylabel("ψ / 2π")
    plt.show()
    print("    ● θ₁ upper   ● θ₂ lower")


def plot_drive_phase(d):
    """#3 drive-relative phase Δφ(t) = ψ_arm − 2π·f_drive·t per arm.
    Flat = phase-locked to the motor; sloped = slipping. Needs a driven
    clip (f_drive parsed from the stem)."""
    import plotext as plt
    from phase_analysis import cyclic_phase, drive_relative
    fd = d.get("f_drive")
    if not fd:
        print("  drive-relative phase needs a driven clip (no f_drive in the stem)")
        return
    t = d["t"]
    s = _sub(d)
    psi1, _ = cyclic_phase(d["th1"])
    psi2, _ = cyclic_phase(d["th2"])
    dphi1, _ = drive_relative(t, psi1, fd)
    dphi2, _ = drive_relative(t, psi2, fd)
    _setup(plt, f"drive-relative phase  Δφ / 2π   (f_drive = {fd:g} Hz)")
    plt.plot(t[::s], (dphi1 / (2 * np.pi))[::s], color="blue", label="θ₁ upper")
    plt.plot(t[::s], (dphi2 / (2 * np.pi))[::s], color="red",  label="θ₂ lower")
    plt.xlabel("t (s)")
    plt.ylabel("Δφ / 2π (cycles)")
    plt.show()
    print("    ● θ₁ upper   ● θ₂ lower   [flat = locked, sloped = slipping]")


PLOTS = {
    "both":     ("green",   "\u03b8\u2081(t) + \u03b8\u2082(t) overlay",         plot_both),
    "omega":    ("green",   "\u03c9\u2081(t) + \u03c9\u2082(t)",                  plot_omega),
    "tip":      ("green",   "\u03b8\u2082_abs(t) = \u03b8\u2081+\u03b8\u2082",    plot_tip),
    "energy":   ("green",   "E(t) = KE + PE",                                      plot_energy),
    "phase1":   ("yellow",  "\u03b8\u2081 vs \u03c9\u2081 phase portrait",        plot_phase1),
    "phase2":   ("yellow",  "\u03b8\u2082 vs \u03c9\u2082 phase portrait",        plot_phase2),
    "config":   ("yellow",  "\u03b8\u2081 vs \u03b8\u2082 configuration",         plot_config),
    "full":     ("yellow",  "\u03b8\u2082_abs vs \u03c9\u2082_abs tip phase",     plot_full),
    "xy":       ("blue",    "marker pixel positions",                               plot_xy),
    "trace":    ("blue",    "tip trajectory in pixel space",                        plot_trace),
    "spectrum": ("red",     "power spectrum of \u03b8\u2082",                      plot_spectrum),
    "return":   ("red",     "\u03b8\u2082(n) vs \u03b8\u2082(n+1) return map",    plot_return),
    "seis1":    ("yellow",  "seismograph v1 spiral (θ_tip=θ₂)",  lambda d: plot_seismograph(d, "v1")),
    "seis2":    ("yellow",  "seismograph v2 ripple (θ_tip=θ₂)",  lambda d: plot_seismograph(d, "v2")),
    "cyc":      ("magenta", "cyclic phase ψ(t) per arm",            plot_cyclic_phase),
    "lock":     ("magenta", "drive-relative phase Δφ(t) (locking)", plot_drive_phase),
}


# ─────────────────────────────────────────────
# REPL
# ─────────────────────────────────────────────

def _print_menu(con):
    """Print the available plot commands in compact inline frames."""
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text

    cats = [
        ("green",   "time series", ["both", "omega", "tip", "energy"]),
        ("yellow",  "phase space", ["phase1", "phase2", "config", "full", "seis1", "seis2"]),
        ("blue",    "physical",    ["xy", "trace"]),
        ("red",     "chaos",       ["spectrum", "return"]),
        ("magenta", "phase",       ["cyc", "lock"]),
    ]
    panels = []
    for color, label, keys in cats:
        content = " ".join(f"[{color} bold]{k}[/]" for k in keys)
        panels.append(Panel(
            Text.from_markup(content),
            title=f"[{color}]{label}[/]",
            border_style=color,
            padding=(0, 1),
            expand=False,
        ))
    con.print(Columns(panels, padding=(0, 1)))
    con.print()
    con.print("  [dim]examples:[/]")
    con.print("    [dim]\u25b8[/] [green bold]both[/]          [dim]\u2192 see \u03b8\u2081 and \u03b8\u2082 over time[/]")
    con.print("    [dim]\u25b8[/] [yellow bold]phase1[/]        [dim]\u2192 then switch to arm 1 phase portrait[/]")
    con.print("    [dim]\u25b8[/] [red bold]spectrum[/]       [dim]\u2192 check frequency content[/]")
    con.print("    [dim]\u25b8[/] [bold]back[/]           [dim]\u2192 done, return to menu[/]")
    con.print()
    con.print("  [dim]type a command, or[/] [bold]back[/] [dim]to return[/]  [dim italic]h = show menu again[/]")


def explore(stem):
    """Load a clip and enter the interactive plot explorer."""
    from rich.console import Console
    con = Console()

    try:
        d = load_clip(stem)
    except (FileNotFoundError, ValueError) as e:
        con.print(f"  [red]ERROR:[/] {e}")
        return

    con.print()
    con.print(
        f"  [green bold]explore[/]  [bold white]{stem}[/]  "
        f"[dim]{d['n_frames']} frames  {d['duration_s']:.1f}s[/]"
    )
    con.print(
        f"  [dim]type a plot name to view it instantly. data stays loaded between plots.[/]"
    )
    con.print()
    _print_menu(con)
    con.print()

    while True:
        try:
            cmd = input("  \u25b8 ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue
        if cmd in ("back", "b", "q", "quit"):
            break
        if cmd in ("help", "?", "h"):
            _print_menu(con)
            continue

        entry = PLOTS.get(cmd)
        if entry is None:
            con.print(f"  [dim]Unknown: {cmd}. Type 'h' for options.[/]")
            continue

        color, desc, plot_fn = entry
        con.print(f"  [{color}]{desc}[/]")
        try:
            plot_fn(d)
        except Exception as e:
            con.print(f"  [red]Plot error:[/] {e}")
        con.print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Interactive tracking data explorer.")
    p.add_argument("--stem", required=True)
    args = p.parse_args()
    explore(args.stem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
