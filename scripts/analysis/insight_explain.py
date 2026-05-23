"""
insight_explain.py — plain-English explanations for the shell's insight cards.

Each ``explain_*`` takes the already-computed metrics for one clip and returns
a Rich-markup string: what each number means, then an intuitive bottom line for
the actual values. The shell only renders what these return, so tune the voice
here without touching the TUI. Keep it short, concrete, and human.
"""

import math


def _fmt(v, f=".2f"):
    if isinstance(v, float) and math.isnan(v):
        return "n/a"
    try:
        return format(v, f)
    except (TypeError, ValueError):
        return str(v)


def explain_chaos(topo, stat, verdict, reasons):
    """Explain a chaos verdict card (from chaos_analyze.compute_*).

    Concise on purpose — it renders as a caption *below* the card, so keep it to
    a few sentences (definition + an intuitive read of the actual value)."""
    K = stat.get("K_chaos", float("nan"))
    H = stat.get("spectral_entropy_th1_norm", float("nan"))
    kread = ("[green]bounded[/] — not diffusive" if K < 0.3 else
             "[red]wandering[/] — diffusive, chaotic" if K > 0.6 else
             "[yellow]ambiguous[/] (mid-range)")
    hread = ("energy in a few sharp peaks → [green]near-periodic[/]" if H < 0.4 else
             "energy smeared across the band → [red]chaotic[/]")
    tail = {"REGULAR":    "a clean, predictable oscillation.",
            "CHAOTIC":    "the fingerprints of deterministic chaos.",
            "BORDERLINE": "on the fence — read with care."}.get(verdict, "")
    vc = {"REGULAR": "green", "CHAOTIC": "red", "BORDERLINE": "yellow"}.get(verdict, "white")
    return "\n".join([
        f"[dim]K[/] — 0–1 test for chaos (≈0 regular · ≈1 chaotic). "
        f"Here [bold]K = {_fmt(K)}[/]: {kread}.",
        f"[dim]spectral entropy[/] — how spread the frequencies are "
        f"(low = periodic · high = chaotic). Here [bold]≈ {_fmt(H)}[/]: {hread}.",
        f"[bold]bottom line →[/] [bold {vc}]{verdict}[/] — {tail}",
    ])


# Plot captions — static "what it shows + how to read it" (tune the voice freely).

def explain_poincare(*_a):
    return ("[dim]Poincaré section[/] — the state sampled once every drive period (a strobe of "
            "the motion).\n[green]A single dot or a few[/] = a periodic, phase-locked response; "
            "[red]a scattered cloud or fractal curve[/] = chaos.")


def explain_spectrum(*_a):
    return ("[dim]Power spectrum[/] — how the motion's energy is split across frequencies.\n"
            "[green]Sharp, isolated peaks[/] = periodic; [red]broadband “grass”[/] = chaotic. "
            "The tallest peak is the dominant response.")


def explain_phase(*_a):
    return ("[dim]Phase portrait[/] — θ vs ω for one arm (position vs velocity).\n"
            "[green]A closed loop[/] = a clean periodic orbit; [red]a filled, tangled band[/] = "
            "chaotic wandering that never repeats.")


def explain_return(*_a):
    return ("[dim]Return map[/] — successive crossings, θ(n) vs θ(n+1).\n"
            "[green]Points on a clean curve[/] = deterministic low-dimensional structure; "
            "[red]a formless scatter[/] = noise or high-dimensional chaos.")
