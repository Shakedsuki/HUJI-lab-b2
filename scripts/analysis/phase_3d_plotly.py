#!/usr/bin/env python3
"""
phase_3d_plotly.py
------------------
Interactive 3D phase-portrait viewer for a single driven-pendulum clip.

Two side-by-side 3D subplots, time on the vertical axis so the trajectory
spirals upward as it evolves:
    Left:  Arm 1  (x = θ₁, y = ω₁, z = t)
    Right: Arm 2  (x = θ₂, y = ω₂, z = t)

A time slider + play button animate a growing trace, so the attractor
fills in progressively; Plotly gives rotate / zoom / pan for free. This
complements the static phase_3d.py (PNG of cross-arm (θ₁,θ₂,ω₁) + rotation
MP4) — here each arm gets its own (θ, ω, t) view and it's interactive.

The HTML is an interactive, regenerable artifact (like the animations), so
it is written under animations/ and is git-ignored — regenerate on demand.

Usage
~~~~~
  python scripts/analysis/phase_3d_plotly.py --stem 3.2V_1.20Hz
  python scripts/analysis/phase_3d_plotly.py --stem 3.2V_0.91Hz --transient 3

Output
~~~~~~
  animations/phase_3d_plotly/<stem>_phase_3d_plotly.html
"""

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import EXPERIMENTS, clip_dir              # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402
from driven_helpers import parse_stem, load_driven_csv   # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True,
                   help="Clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="Seconds to skip at start (default: 5).")
    p.add_argument("--subsample", type=int, default=3,
                   help="Take every Nth point (default: 3). Keeps HTML size "
                        "manageable for long recordings.")
    p.add_argument("--n-frames", type=int, default=60,
                   help="Number of animation slider frames (default: 60).")
    return p.parse_args()


def resolve_f_drive(stem, override=None):
    """Drive frequency from experiments.json, falling back to the stem name."""
    if override is not None:
        return override
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, encoding="utf-8") as f:
            exp = json.load(f)
        if stem in exp and "drive_freq_hz" in exp[stem]:
            return float(exp[stem]["drive_freq_hz"])
    try:
        return parse_stem(stem)["f_drive_hz"]
    except ValueError:
        return None


def build_figure(t, th1, th2, om1, om2, stem, f_drive, n_frames):
    """Build and return a plotly Figure with two 3D subplots + animation."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        from plotly.colors import sample_colorscale
    except ImportError:
        raise SystemExit("plotly is required:  pip install plotly")

    n = len(t)
    frame_indices = np.linspace(0, n - 1, n_frames + 1, dtype=int)[1:]

    # Per-point time colour (viridis) as rgb strings, via plotly's own scale.
    t_norm = (t - t.min()) / (t.max() - t.min() + 1e-12)
    colors = sample_colorscale("Viridis", list(t_norm))

    fig = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "scene"}, {"type": "scene"}]],
        subplot_titles=["Arm 1 — (θ₁, ω₁, t)", "Arm 2 — (θ₂, ω₂, t)"],
        horizontal_spacing=0.04,
    )

    # Traces 0,1 — the static "ghost" of the full trajectory (never animated).
    fig.add_trace(go.Scatter3d(
        x=th1, y=om1, z=t, mode="markers",
        marker=dict(size=1.5, color="rgba(120,120,120,0.10)"),
        showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter3d(
        x=th2, y=om2, z=t, mode="markers",
        marker=dict(size=1.5, color="rgba(120,120,120,0.10)"),
        showlegend=False, hoverinfo="skip"), row=1, col=2)

    # Traces 2,3 — the growing trajectory (animated).
    k0 = frame_indices[0]
    fig.add_trace(go.Scatter3d(
        x=th1[:k0], y=om1[:k0], z=t[:k0], mode="lines+markers",
        line=dict(width=2, color="mediumseagreen"),
        marker=dict(size=2, color=colors[:k0]), showlegend=False,
        hovertemplate="θ₁=%{x:.1f}°<br>ω₁=%{y:.0f}°/s<br>t=%{z:.1f}s"),
        row=1, col=1)
    fig.add_trace(go.Scatter3d(
        x=th2[:k0], y=om2[:k0], z=t[:k0], mode="lines+markers",
        line=dict(width=2, color="indianred"),
        marker=dict(size=2, color=colors[:k0]), showlegend=False,
        hovertemplate="θ₂=%{x:.1f}°<br>ω₂=%{y:.0f}°/s<br>t=%{z:.1f}s"),
        row=1, col=2)

    # Traces 4,5 — the "now" markers at the current endpoint (animated).
    fig.add_trace(go.Scatter3d(
        x=[th1[k0-1]], y=[om1[k0-1]], z=[t[k0-1]], mode="markers",
        marker=dict(size=7, color="lime", symbol="diamond",
                    line=dict(width=1, color="black")),
        showlegend=False, hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter3d(
        x=[th2[k0-1]], y=[om2[k0-1]], z=[t[k0-1]], mode="markers",
        marker=dict(size=7, color="red", symbol="diamond",
                    line=dict(width=1, color="black")),
        showlegend=False, hoverinfo="skip"), row=1, col=2)

    # Animation frames update ONLY the growing trace + now markers (traces
    # 2–5). The ghost traces (0,1) are static, so they are never repeated in
    # frames — keeping the embedded HTML small.
    frames = []
    for k in frame_indices:
        frames.append(go.Frame(
            data=[
                go.Scatter3d(x=th1[:k], y=om1[:k], z=t[:k], mode="lines+markers",
                             line=dict(width=2, color="mediumseagreen"),
                             marker=dict(size=2, color=colors[:k])),
                go.Scatter3d(x=th2[:k], y=om2[:k], z=t[:k], mode="lines+markers",
                             line=dict(width=2, color="indianred"),
                             marker=dict(size=2, color=colors[:k])),
                go.Scatter3d(x=[th1[k-1]], y=[om1[k-1]], z=[t[k-1]], mode="markers",
                             marker=dict(size=7, color="lime", symbol="diamond",
                                         line=dict(width=1, color="black"))),
                go.Scatter3d(x=[th2[k-1]], y=[om2[k-1]], z=[t[k-1]], mode="markers",
                             marker=dict(size=7, color="red", symbol="diamond",
                                         line=dict(width=1, color="black"))),
            ],
            traces=[2, 3, 4, 5],
            name=f"{t[k]:.1f}s",
        ))
    fig.frames = frames

    sliders = [dict(
        active=0,
        currentvalue=dict(prefix="t = ", suffix=" s", font=dict(size=13)),
        pad=dict(t=40),
        steps=[dict(args=[[fr.name], dict(frame=dict(duration=80, redraw=True),
                                          mode="immediate",
                                          transition=dict(duration=0))],
                    method="animate", label=fr.name)
               for fr in frames],
    )]
    updatemenus = [dict(
        type="buttons", showactive=False,
        x=0.05, y=0.0, xanchor="left", yanchor="top",
        buttons=[
            dict(label="▶ Play", method="animate",
                 args=[None, dict(frame=dict(duration=80, redraw=True),
                                  fromcurrent=True, transition=dict(duration=0))]),
            dict(label="⏸ Pause", method="animate",
                 args=[[None], dict(frame=dict(duration=0, redraw=False),
                                    mode="immediate", transition=dict(duration=0))]),
        ],
    )]

    f_label = f"f = {f_drive:.2f} Hz" if f_drive else ""
    scene_common = dict(
        xaxis=dict(title="θ (deg)", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        yaxis=dict(title="ω (deg/s)", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        zaxis=dict(title="t (s)", showgrid=True, gridcolor="rgba(200,200,200,0.3)"),
        bgcolor="rgba(250,250,250,1)",
        camera=dict(eye=dict(x=1.6, y=-1.2, z=0.8)),
    )
    fig.update_layout(
        title=dict(text=(f"3D Phase Portrait — {stem}   "
                         f"({f_label},  {n} pts,  {t[-1]:.0f} s)"),
                   font=dict(size=15)),
        scene=scene_common,
        scene2={**scene_common},
        sliders=sliders,
        updatemenus=updatemenus,
        height=650,
        margin=dict(l=0, r=0, t=60, b=10),
    )
    return fig


def main():
    args = parse_args()
    stem = args.stem

    # Load via the shared driven loader (phase-filtered, dropout-clean,
    # zero-based time) so this matches every other driven analysis script.
    t, th1, th2, om1, om2 = load_driven_csv(
        os.path.join(clip_dir(stem), "verification.csv"))
    f_drive = resolve_f_drive(stem)

    # Trim transient, then subsample to keep the HTML manageable.
    mask = t >= args.transient
    t, th1, th2, om1, om2 = t[mask], th1[mask], th2[mask], om1[mask], om2[mask]
    s = max(1, args.subsample)
    t, th1, th2 = t[::s], th1[::s], th2[::s]
    om1, om2 = om1[::s], om2[::s]
    if len(t) < 10:
        raise SystemExit(f"only {len(t)} points after transient+subsample.")

    info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    info.add_column(style="dim", min_width=18)
    info.add_column(style="white", justify="right")
    info.add_row("stem",     f"[cyan]{stem}[/]")
    info.add_row("f_drive",  f"{f_drive:.3f} Hz" if f_drive else "[dim]unknown[/]")
    info.add_row("points",   f"{len(t)}  [dim](subsample {s})[/]")
    info.add_row("t range",  f"{t[0]:.1f} – {t[-1]:.1f} s  [dim](transient {args.transient:.0f} s cut)[/]")
    info.add_row("θ₁ range", f"{th1.min():.1f} .. {th1.max():.1f}°")
    info.add_row("ω₁ range", f"{om1.min():.0f} .. {om1.max():.0f} °/s")
    info.add_row("θ₂ range", f"{th2.min():.1f} .. {th2.max():.1f}°")
    info.add_row("ω₂ range", f"{om2.min():.0f} .. {om2.max():.0f} °/s")
    info.add_row("frames",   str(args.n_frames))
    console.print(info)

    fig = build_figure(t, th1, th2, om1, om2, stem, f_drive, args.n_frames)

    # animations/phase_3d_plotly/<stem>_phase_3d_plotly.html (figure_path
    # routes phase_3d_plotly to animations/ — see figures_paths).
    out_path = figure_path("phase_3d_plotly", stem, ext="html")
    fig.write_html(out_path, include_plotlyjs="cdn", full_html=True)
    mirror_to_ready(out_path)
    console.print(f"\n  [green]Saved →[/] {out_path}")
    console.print("  [dim]Open in browser to interact (rotate / zoom / play).[/]")


if __name__ == "__main__":
    main()
