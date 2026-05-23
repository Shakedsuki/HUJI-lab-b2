"""
ftle_windows.py
---------------
Windowed finite-time Lyapunov exponents (FTLE) from omega2 for a single clip.

Splits the post-transient omega2 series into N equal disjoint windows and runs
the Rosenstein largest-Lyapunov estimator on each, reusing the embedding /
divergence / slope-fit machinery from lyapunov.py so a window's lambda_1 is
computed identically to the whole-clip value.

The per-window lambda_1 values are the data behind the shell's FTLE sparkline
column and the per-clip chaos classification glyph. lambda1_std across the
windows encodes stationarity: a steady attractor has low spread, a transient or
intermittent run has high spread.

Output
~~~~~~
  measurements/<stem>/ftle_windows.json

Usage
~~~~~
  python scripts/analysis/ftle_windows.py --stem 3.2V_1.17Hz
  python scripts/analysis/ftle_windows.py --stem 3.2V_1.17Hz --transient 3.0 --windows 8

References
~~~~~~~~~~
Rosenstein, Collins & De Luca (1993). A practical method for calculating
largest Lyapunov exponents from small data sets. Physica D, 65, 117-134.
"""

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                            # sibling analysis modules
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
from paths import clip_dir                                           # noqa: E402
from lyapunov import (autocorr_first_drop, estimate_period_frames,   # noqa: E402
                      embed, rosenstein, fit_divergence_slope)

# ▁▂▃▄▅▆▇█ — same ramp the shell uses, so the terminal preview matches the column.
BLOCKS = "▁▂▃▄▅▆▇█"
DOT = "·"
CLS_COLOR = {"chaotic": "red", "regular": "green", "edge": "yellow"}

def parse_args():
    p = argparse.ArgumentParser(description="Windowed finite-time Lyapunov exponents from omega2.")
    p.add_argument("--stem", required=True, help="config_description, e.g. 3.2V_1.17Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="seconds to discard from the start (default 5.0)")
    p.add_argument("--windows", type=int, default=8,
                   help="number of disjoint windows (default 8)")
    p.add_argument("--emb-dim", type=int, default=5,
                   help="embedding dimension m (default 5)")
    p.add_argument("--tau", type=int, default=None,
                   help="embedding delay in frames; auto-pick if omitted")
    p.add_argument("--theiler", type=int, default=None,
                   help="Theiler window in frames; auto = ~1 period if omitted")
    return p.parse_args()

def _num(v, nd):
    """Round a float for JSON; non-finite -> None (JSON null)."""
    if isinstance(v, (int, float)) and np.isfinite(v):
        return round(float(v), nd)
    return None

def load_omega2(csv_path):
    """Read (t, omega2) for analysis phases, dropping dropout frames and
    non-finite values. Time is re-zeroed to the first analysis sample so the
    window bounds read as clip time. Returns two 1-D float arrays."""
    ts, w2 = [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("phase") not in ("free_swing", "driven"):
                continue
            try:
                if int(float(r.get("dropout", 0) or 0)) != 0:
                    continue
                t = float(r["time_s"]); w = float(r["omega2_deg_s"])
            except (ValueError, KeyError, TypeError):
                continue
            if not (np.isfinite(t) and np.isfinite(w)):
                continue
            ts.append(t); w2.append(w)
    t = np.asarray(ts, dtype=float)
    w = np.asarray(w2, dtype=float)
    if t.size:
        t = t - t[0]
    return t, w

def compute_windows(t, w, *, transient, n_windows, emb_dim, tau_override, theiler_override):
    """Split the post-transient series into n_windows disjoint windows and run
    Rosenstein on each. Returns the result dict (sans stem/observable)."""
    keep = t >= transient
    t, w = t[keep], w[keep]
    n_total = w.size
    if n_total < 2000:
        raise SystemExit(
            f"Too few post-transient frames ({n_total}); need >= 2000 "
            f"(~33 s at 60 fps). Try a smaller --transient or a longer clip.")
    dt = float(np.mean(np.diff(t)))

    # Global embedding parameters, shared by every window so they are comparable.
    if tau_override is not None:
        tau = int(tau_override)
    else:
        tau = int(max(3, min(autocorr_first_drop(w), 30)))
    if theiler_override is not None:
        theiler = int(theiler_override)
    else:
        theiler = int(max(30, min(estimate_period_frames(t, w), 200)))

    n_window = n_total // n_windows
    windows, lambdas = [], []
    for i in range(n_windows):
        seg = w[i * n_window:(i + 1) * n_window]
        t0 = float(t[i * n_window])
        t1 = float(t[(i + 1) * n_window - 1])
        lam = r2 = float("nan")
        if seg.size > (emb_dim - 1) * tau:
            Y = embed(seg, emb_dim, tau)
            if Y.shape[0] >= 2 * theiler:
                k_max = int(min(Y.shape[0] // 4, 300))
                if k_max >= 2:
                    S = rosenstein(Y, theiler=theiler, k_max=k_max)
                    lam, r2, _lo, _hi = fit_divergence_slope(S, dt)
        windows.append({"t_start": round(t0, 2), "t_end": round(t1, 2),
                        "lambda1": _num(lam, 4), "r2": _num(r2, 3)})
        lambdas.append(lam)

    lam_arr = np.asarray(lambdas, dtype=float)
    finite = lam_arr[np.isfinite(lam_arr)]
    g = float(np.mean(finite)) if finite.size else float("nan")
    s = float(np.std(finite)) if finite.size else float("nan")
    if np.isfinite(g) and np.isfinite(s):
        cls = "chaotic" if g > s else ("regular" if g < -s else "edge")
    else:
        cls = "edge"

    return {
        "n_windows": n_windows,
        "transient_s": float(transient),
        "window_duration_s": round(n_window * dt, 2),
        "embedding_dim": int(emb_dim),
        "tau_frames": tau,
        "theiler_frames": theiler,
        "dt_s": _num(dt, 5),
        "windows": windows,
        "lambda1_global": _num(g, 4),
        "lambda1_std": _num(s, 4),
        "classification": cls,
    }

def _sparkline(windows):
    """8-char block sparkline of the window lambda_1 values (lambda range
    clamped to [-0.2, +0.4], the typical pendulum band)."""
    out = []
    for win in windows:
        lam = win["lambda1"]
        if lam is None:
            out.append(DOT); continue
        idx = max(0, min(7, int((lam + 0.2) / 0.6 * 8)))
        out.append(BLOCKS[idx])
    return "".join(out)

def render_summary(result):
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.rule import Rule
    con = Console()

    cls = result["classification"]
    color = CLS_COLOR.get(cls, "white")
    g, s = result["lambda1_global"], result["lambda1_std"]
    g_str = f"{g:+.4f} /s" if g is not None else "n/a"
    band = f"± {s:.4f}" if s is not None else ""

    spark = _sparkline(result["windows"])

    t_res = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t_res.add_column(style="dim", min_width=24); t_res.add_column(justify="right")
    t_res.add_row("λ₁ global (mean of windows)", f"[bold {color}]{g_str}[/]")
    t_res.add_row("λ₁ std (stationarity)", band or "n/a")
    t_res.add_row("windows", str(result["n_windows"]))
    t_res.add_row("FTLE sparkline", f"[{color}]{spark}[/]")

    t_emb = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    t_emb.add_column(style="dim", min_width=24); t_emb.add_column(justify="right")
    t_emb.add_row("observable", result["observable"])
    t_emb.add_row("transient discarded", f"{result['transient_s']:.1f} s")
    t_emb.add_row("window duration", f"{result['window_duration_s']:.1f} s")
    t_emb.add_row("embedding dim  m", str(result["embedding_dim"]))
    t_emb.add_row("embedding delay  τ", f"{result['tau_frames']} frames")
    t_emb.add_row("Theiler window  W", f"{result['theiler_frames']} frames")

    t_win = Table(box=None, show_header=True, padding=(0, 1), expand=False)
    t_win.add_column("#", justify="right", style="dim")
    t_win.add_column("t range (s)", justify="right")
    t_win.add_column("λ₁", justify="right")
    t_win.add_column("R²", justify="right")
    for i, win in enumerate(result["windows"], 1):
        lam = win["lambda1"]; r2 = win["r2"]
        lam_s = f"{lam:+.3f}" if lam is not None else "[dim]n/a[/]"
        r2_s = f"{r2:.2f}" if r2 is not None else "[dim]n/a[/]"
        t_win.add_row(str(i), f"{win['t_start']:.1f}–{win['t_end']:.1f}", lam_s, r2_s)

    con.print(Panel(
        Group(Rule("result", style="dim"), t_res,
              Rule("parameters", style="dim"), t_emb,
              Rule("windows", style="dim"), t_win),
        title=f"[bold {color}]{cls.upper()}[/]  [bold white]{result['stem']}[/]  "
              f"[dim]windowed FTLE (ω₂)[/]",
        border_style=color, padding=(1, 2)))

def main():
    args = parse_args()
    stem = args.stem
    out_dir = clip_dir(stem)
    csv_path = os.path.join(out_dir, "verification.csv")
    if not os.path.isfile(csv_path):
        raise SystemExit(f"No verification.csv for stem {stem!r} ({csv_path}).")

    t, w = load_omega2(csv_path)
    res = compute_windows(t, w, transient=args.transient, n_windows=args.windows,
                          emb_dim=args.emb_dim, tau_override=args.tau,
                          theiler_override=args.theiler)
    result = {"stem": stem, "observable": "omega2", **res}

    json_path = os.path.join(out_dir, "ftle_windows.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    render_summary(result)
    from rich.console import Console
    Console().print(f"[dim]json → {json_path}[/]")

if __name__ == "__main__":
    main()
