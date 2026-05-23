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
    """Explain a chaos verdict card (from chaos_analyze.compute_*)."""
    K = stat.get("K_chaos", float("nan"))
    H = stat.get("spectral_entropy_th1_norm", float("nan"))
    frac = topo.get("frac_inverted", 0.0)

    out = []
    out.append("[bold]what the numbers mean[/]")
    out.append("[dim]K · 0–1 test for chaos[/] — drives a helper coordinate from the "
               "angle and asks whether it stays put or wanders off like a random walk. "
               "[bold]≈0 regular · ≈1 chaotic.[/]")
    out.append("[dim]spectral entropy[/] — how spread-out the motion's frequencies are. "
               "A clean swing puts its energy in a few sharp peaks (low); chaos smears "
               "it across the whole band (high). Normalised 0–1.")
    out.append("")
    out.append("[bold]this clip[/]")

    if K < 0.3:
        out.append(f"• K = {_fmt(K)} is [green]low[/] — the helper coordinate stays bounded, "
                   "so the motion is not diffusive.")
    elif K > 0.6:
        out.append(f"• K = {_fmt(K)} is [red]high[/] — the helper coordinate wanders, the "
                   "signature of chaotic, diffusive motion.")
    else:
        out.append(f"• K = {_fmt(K)} is [yellow]mid-range[/] — neither clearly bounded nor "
                   "clearly diffusive (borderline).")

    if H < 0.4:
        out.append(f"• spectral entropy = {_fmt(H)} is [green]low[/] — energy sits in a few "
                   "frequencies, i.e. a near-periodic response.")
    else:
        out.append(f"• spectral entropy = {_fmt(H)} is [red]high[/] — energy is smeared across "
                   "many frequencies, a hallmark of chaos.")

    out.append(f"• the lower arm spent {_fmt(frac * 100, '.0f')}% of the run inverted "
               "(above horizontal).")
    out.append("")

    tail = {"REGULAR":    "A clean, predictable oscillation — not chaos.",
            "CHAOTIC":    "The fingerprints of deterministic chaos.",
            "BORDERLINE": "Sits on the fence — read it with care."}.get(verdict, "")
    vc = {"REGULAR": "green", "CHAOTIC": "red", "BORDERLINE": "yellow"}.get(verdict, "white")
    out.append(f"[bold]bottom line:[/] both tests agree → [bold {vc}]{verdict}[/]. {tail}")
    return "\n".join(out)
