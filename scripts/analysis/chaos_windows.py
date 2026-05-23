"""
chaos_windows.py
----------------
Per-clip chaos classification + time-resolved intensity — the SINGLE source of
truth behind the shell's chaos glyph and sparkline.

Both derive from chaos_analyze (the exact verdict the i-insights chaos card
shows), so the card, the glyph and the sparkline can never disagree:

  verdict        : REGULAR / BORDERLINE / CHAOTIC  (chaos_analyze.compute_verdict)
  window_entropy : spectral entropy of theta2 in N equal windows, each in [0, 1]
                   (0 = sharp peaks / periodic, 1 = broadband / chaotic) — the
                   same noise-robust diagnostic the verdict uses (H_th2), just
                   resolved over time. Unlike a windowed Lyapunov exponent it is
                   bounded and stable on short windows, so it reflects the
                   whole-clip verdict instead of contradicting it.

Output: measurements/<stem>/chaos_windows.json

Usage:
  python scripts/analysis/chaos_windows.py --stem 3.2V_1.17Hz
  python scripts/analysis/chaos_windows.py --stem 3.2V_1.17Hz --windows 8
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                            # sibling analysis modules
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
from paths import clip_dir            # noqa: E402
import chaos_analyze as ca            # noqa: E402

VERDICT_COLOR = {"REGULAR": "green", "BORDERLINE": "yellow", "CHAOTIC": "red"}


def _round(v, nd=4):
    if isinstance(v, (int, float)) and np.isfinite(v):
        return round(float(v), nd)
    return None


def compute(stem, n_windows=8):
    """Return the chaos_windows result dict for one clip (verdict + per-window
    theta2 spectral entropy), computed identically to the i-insights card."""
    csv_path = os.path.join(clip_dir(stem), "verification.csv")
    if not os.path.isfile(csv_path):
        raise SystemExit(f"No verification.csv for stem {stem!r} ({csv_path}).")

    data = ca.load_free_swing(csv_path)
    topo = ca.compute_topological(data)
    stat = ca.compute_statistical(topo)
    verdict, reasons = ca.compute_verdict(topo, stat)

    # Per-window spectral entropy of theta2 — the windowed form of the verdict's
    # own H_th2 driver. Same series the verdict sees, split into equal windows.
    th2 = topo["th2"]
    n = len(th2)
    w = max(1, n // n_windows)
    window_entropy = []
    for i in range(n_windows):
        seg = th2[i * w:] if i == n_windows - 1 else th2[i * w:(i + 1) * w]
        window_entropy.append(_round(ca.spectral_entropy_norm(seg)))

    return {
        "stem": stem,
        "verdict": verdict,
        "reasons": reasons,
        "K_chaos": _round(stat["K_chaos"]),
        "K_chaos_iqr": _round(stat.get("K_chaos_iqr", float("nan"))),
        "spectral_entropy_th2": _round(stat["spectral_entropy_th2_norm"]),
        "n_windows": n_windows,
        "window_entropy": window_entropy,
    }


def render_summary(res):
    from rich.console import Console
    con = Console()
    vc = VERDICT_COLOR.get(res["verdict"], "white")
    con.print(f"[bold {vc}]{res['verdict']}[/]  [bold white]{res['stem']}[/]  "
              f"[dim]K={res['K_chaos']}  H_th2={res['spectral_entropy_th2']}[/]")
    con.print(f"  [dim]window entropy:[/] {res['window_entropy']}")


def main():
    p = argparse.ArgumentParser(
        description="Per-clip chaos verdict + windowed theta2 spectral entropy "
                    "(the glyph + sparkline source of truth).")
    p.add_argument("--stem", required=True, help="config_description, e.g. 3.2V_1.17Hz")
    p.add_argument("--windows", type=int, default=8, help="number of equal windows (default 8)")
    args = p.parse_args()

    res = compute(args.stem, args.windows)
    out_path = os.path.join(clip_dir(args.stem), "chaos_windows.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)

    render_summary(res)
    from rich.console import Console
    Console().print(f"[dim]json → {out_path}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
