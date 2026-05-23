"""
sanity_check.py — quick visual + automated tracking validation.

Renders 4 diagnostic plots in a 2x2 grid directly in the terminal
via plotext, computes automated quality checks, and returns a verdict
without requiring the slow overlay video render.

Usage:
    chaos -> t -> x (sanity check)
    chaos -> t -> k (sanity sweep)
    python scripts/analysis/sanity_check.py --stem 3.2V_0.9Hz
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

ARM_DEV_WARN_PCT = 3.0
ARM_DEV_FAIL_PCT = 6.0
ENERGY_SPIKE_FACTOR = 3.0
THETA_JUMP_DEG = 30.0


def load_tracking(stem):
    csv_path = os.path.join(clip_dir(stem), "tracking.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No tracking.csv for {stem}")
    df = pd.read_csv(csv_path)
    clean = df[df["dropout"] == 0].copy().reset_index(drop=True)
    if len(clean) < 10:
        raise ValueError(f"Only {len(clean)} non-dropout frames")
    return clean, {"stem": stem, "n_total": len(df), "n_clean": len(clean),
                   "n_dropout": int((df["dropout"] == 1).sum()),
                   "duration_s": float(df["time_s"].iloc[-1] - df["time_s"].iloc[0])}


def compute_diagnostics(df, stem):
    t = df["time_s"].values
    th1 = df["theta1_deg"].values
    th2 = df["theta2_deg"].values
    xg, yg = df["x_green"].values, df["y_green"].values
    xr, yr = df["x_red"].values, df["y_red"].values

    dt = np.diff(t)
    dt[dt == 0] = 1e-6
    om1 = np.concatenate([[0], np.diff(th1) / dt])
    om2 = np.concatenate([[0], np.diff(th2) / dt])

    pivot, arm_px = get_pivot_arm(stem)
    arm1_len = np.sqrt((xg - pivot[0])**2 + (yg - pivot[1])**2)
    arm2_len = np.sqrt((xr - xg)**2 + (yr - yg)**2)
    arm1_median = np.median(arm1_len)
    arm2_median = np.median(arm2_len)
    arm1_dev_pct = np.abs(arm1_len - arm1_median) / arm1_median * 100
    arm2_dev_pct = np.abs(arm2_len - arm2_median) / arm2_median * 100
    arm_max_dev = max(float(np.percentile(arm1_dev_pct, 99)),
                      float(np.percentile(arm2_dev_pct, 99)))

    th1_r = np.radians(th1)
    th2_abs_r = np.radians(th1 + th2)
    th2_rel_r = np.radians(th2)
    w1_r = np.radians(om1)
    w2_abs_r = np.radians(om1 + om2)
    PE = (_G * (3 * _L / 2) * (1 - np.cos(th1_r))
        + _G * (_L / 2) * (1 - np.cos(th2_abs_r)))
    KE = _L**2 * ((2/3) * w1_r**2
        + 0.5 * w1_r * w2_abs_r * np.cos(th2_rel_r)
        + (1/6) * w2_abs_r**2)
    energy = KE + PE
    energy_median = float(np.median(energy))
    energy_spikes = int(np.sum(energy > energy_median * ENERGY_SPIKE_FACTOR))

    th1_jumps = int(np.sum(np.abs(np.diff(th1)) > THETA_JUMP_DEG))
    th2_jumps = int(np.sum(np.abs(np.diff(th2)) > THETA_JUMP_DEG))

    return {
        "t": t, "th1": th1, "th2": th2, "om1": om1, "om2": om2,
        "arm1_dev_pct": arm1_dev_pct, "arm2_dev_pct": arm2_dev_pct,
        "arm_max_dev": arm_max_dev,
        "energy": energy, "energy_median": energy_median,
        "energy_spikes": energy_spikes,
        "th1_jumps": th1_jumps, "th2_jumps": th2_jumps,
        "arm1_median": arm1_median, "arm2_median": arm2_median,
        "arm_px_expected": arm_px,
    }


def compute_verdict(diag):
    reasons = []
    worst = "CLEAN"
    amd = diag["arm_max_dev"]
    if amd > ARM_DEV_FAIL_PCT:
        reasons.append(f"arm deviation p99 = {amd:.1f}% > {ARM_DEV_FAIL_PCT}%")
        worst = "REVIEW"
    elif amd > ARM_DEV_WARN_PCT:
        reasons.append(f"arm deviation p99 = {amd:.1f}% > {ARM_DEV_WARN_PCT}%")
        if worst != "REVIEW": worst = "WARN"
    es = diag["energy_spikes"]
    if es > 10:
        reasons.append(f"{es} energy spikes > {ENERGY_SPIKE_FACTOR}x median")
        worst = "REVIEW"
    elif es > 0:
        reasons.append(f"{es} energy spike(s)")
        if worst != "REVIEW": worst = "WARN"
    tj = diag["th1_jumps"] + diag["th2_jumps"]
    if tj > 5:
        reasons.append(f"{tj} angle jumps > {THETA_JUMP_DEG} deg/frame")
        worst = "REVIEW"
    elif tj > 0:
        reasons.append(f"{tj} angle jump(s)")
        if worst != "REVIEW": worst = "WARN"
    if not reasons:
        reasons.append("all checks passed")
    return worst, reasons


def render_plots(stem, meta, diag, verdict, reasons, plot_width=80, plot_height=16, show=True):
    """Render structured metrics panel + 2x2 plot grid + per-plot verdicts.
    With show=False, skips console output and returns the plot grid as a string."""
    import plotext as plt
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    con = Console()
    t = diag["t"] - diag["t"][0]

    step = max(1, len(t) // 500)
    ts = t[::step]
    th1s = diag["th1"][::step]
    th2s = diag["th2"][::step]
    om1s = diag["om1"][::step]
    es = diag["energy"][::step]
    a1s = diag["arm1_dev_pct"][::step]
    a2s = diag["arm2_dev_pct"][::step]

    v_colors = {"CLEAN": "green", "WARN": "yellow", "REVIEW": "red"}
    vc = v_colors.get(verdict, "white")

    # ── Structured metrics panel ──
    mt = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    mt.add_column(style="dim")
    mt.add_column(style="white bold")
    mt.add_column(style="dim")
    mt.add_column(style="white bold")
    mt.add_column(style="dim")
    mt.add_column(style="white bold")

    arm_c = vc if diag["arm_max_dev"] > ARM_DEV_WARN_PCT else "green"
    esp_c = vc if diag["energy_spikes"] > 0 else "green"
    tj = diag["th1_jumps"] + diag["th2_jumps"]
    jmp_c = vc if tj > 0 else "green"

    mt.add_row(
        "frames", str(meta["n_clean"]),
        "arm p99", f"[{arm_c}]{diag['arm_max_dev']:.1f}%[/]",
        "E spikes", f"[{esp_c}]{diag['energy_spikes']}[/]",
    )
    mt.add_row(
        "duration", f"{meta['duration_s']:.1f}s",
        "arm1", f"{diag['arm1_median']:.0f}px",
        "\u03b8 jumps", f"[{jmp_c}]{tj}[/]",
    )
    mt.add_row(
        "dropout", str(meta["n_dropout"]),
        "arm2", f"{diag['arm2_median']:.0f}px",
        "expected", f"{diag['arm_px_expected']}px",
    )

    if show:
        con.print(Panel(
            mt,
            title=f"[bold {vc}]{verdict}[/]  [bold white]{stem}[/]",
            border_style=vc,
            padding=(0, 1),
        ))
        con.print()

    # ── 2x2 plotext grid ──
    plt.clf()
    plt.subplots(2, 2)
    plt.plotsize(plot_width, plot_height * 2 + 8)
    plt.theme("dark")

    plt.subplot(1, 1)
    plt.theme("dark")
    plt.ticks_color("yellow")
    plt.plot(ts, th1s, label="\u03b81", color="green")
    plt.plot(ts, th2s, label="\u03b82", color="orange")
    plt.title("\u03b8(t)")
    plt.xlabel("t (s)")
    plt.ylabel("deg")

    plt.subplot(1, 2)
    plt.theme("dark")
    plt.ticks_color("yellow")
    plt.plot(ts, a1s, label="arm1", color="cyan")
    plt.plot(ts, a2s, label="arm2", color="magenta")
    plt.hline(ARM_DEV_WARN_PCT, color="yellow")
    plt.hline(ARM_DEV_FAIL_PCT, color="red")
    plt.title("arm dev %")
    plt.xlabel("t (s)")
    plt.ylabel("%")

    plt.subplot(2, 1)
    plt.theme("dark")
    plt.ticks_color("yellow")
    plt.scatter(th1s, om1s, color="blue", marker="dot")
    plt.title("\u03b81 vs \u03c91")
    plt.xlabel("\u03b81 (deg)")
    plt.ylabel("\u03c91 (\u00b0/s)")

    plt.subplot(2, 2)
    plt.theme("dark")
    plt.ticks_color("yellow")
    plt.plot(ts, es, color="orange")
    plt.hline(diag["energy_median"] * ENERGY_SPIKE_FACTOR, color="red")
    plt.title("E(t)")
    plt.xlabel("t (s)")
    plt.ylabel("E")

    if not show:
        return plt.build()
    plt.show()
    con.print()

    # ── Per-plot verdicts (2 lines, matching 2x2 positions) ──
    amd = diag["arm_max_dev"]
    es_n = diag["energy_spikes"]

    def _chk(ok, label, good, bad):
        sym = "[green]\u2713[/]" if ok else "[red]\u2717[/]"
        msg = f"[dim]{good}[/]" if ok else f"[dim]{bad}[/]"
        return f"{sym} [bold]{label}[/] {msg}"

    l1 = _chk(tj == 0, "\u03b8(t)", "smooth oscillation", f"{tj} jumps detected")
    r1 = _chk(amd < ARM_DEV_WARN_PCT, "arm", f"stable {amd:.1f}%", f"deviates {amd:.1f}%")
    l2 = _chk(amd < ARM_DEV_WARN_PCT, "phase", "coherent attractor", "suspect \u2014 check arm")
    r2 = _chk(es_n == 0, "energy", "no spikes", f"{es_n} spikes above threshold")

    con.print(f"  {l1:<55} {r1}")
    con.print(f"  {l2:<55} {r2}")
    con.print()

    return con


def check_one(stem, plot_width=80, plot_height=16):
    clean, meta = load_tracking(stem)
    diag = compute_diagnostics(clean, stem)
    verdict, reasons = compute_verdict(diag)
    render_plots(stem, meta, diag, verdict, reasons,
                 plot_width=plot_width, plot_height=plot_height)
    return verdict, reasons


def build_one(stem, plot_width=80, plot_height=16):
    """Build the 2x2 plotext grid for one clip as a string (no console output).
    Returns (verdict, plot_str)."""
    clean, meta = load_tracking(stem)
    diag = compute_diagnostics(clean, stem)
    verdict, reasons = compute_verdict(diag)
    plot_str = render_plots(stem, meta, diag, verdict, reasons,
                            plot_width=plot_width, plot_height=plot_height, show=False)
    return verdict, plot_str


def check_sweep(clips, on_pause=None):
    from rich.console import Console
    con = Console()
    results = []
    for i, clip in enumerate(clips):
        stem = clip["stem"]
        try:
            clean, meta = load_tracking(stem)
            diag = compute_diagnostics(clean, stem)
            verdict, reasons = compute_verdict(diag)
        except (FileNotFoundError, ValueError) as e:
            con.print(f"  [red]\u2717[/] {stem}  [red]{e}[/]")
            results.append((stem, "ERROR"))
            continue
        if verdict == "CLEAN":
            con.print(
                f"  [green]\u2713[/] {stem:<22}"
                f"  [green]clean[/]"
                f"  arm {diag['arm_max_dev']:.1f}%"
                f"  E {diag['energy_spikes']} spikes"
            )
            results.append((stem, "CLEAN"))
        else:
            vc = "yellow" if verdict == "WARN" else "red"
            con.print(f"\n  [{vc}]\u26a0[/] {stem}  [{vc}]{verdict}[/]")
            render_plots(stem, meta, diag, verdict, reasons)
            results.append((stem, verdict))
            if on_pause:
                action = on_pause(stem, verdict, reasons)
                if action == "q":
                    break
    return results


def main():
    p = argparse.ArgumentParser(description="Quick tracking sanity check.")
    p.add_argument("--stem", required=True)
    p.add_argument("--width", type=int, default=80)
    p.add_argument("--height", type=int, default=16)
    args = p.parse_args()
    try:
        verdict, _ = check_one(args.stem, plot_width=args.width, plot_height=args.height)
    except (FileNotFoundError, ValueError) as e:
        from rich.console import Console
        Console().print(f"  [red]ERROR:[/] {e}")
        return 1
    return 0 if verdict == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
