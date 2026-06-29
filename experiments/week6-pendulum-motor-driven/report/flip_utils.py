"""
Flip detection + on-plot rotation icons for the theta2 time series.

A "flip" of the lower arm is when theta2 goes over the top/bottom, i.e. the
wrapped angle jumps across the +/-180 deg boundary. We mark each flip with a
circular rotation icon (Style B): the curl direction encodes which way it went.
"""
import numpy as np
import matplotlib.patheffects as pe

CW = "↻"   # over-the-top flip  (crossed +180)
CCW = "↺"  # over-the-bottom flip (crossed -180)


def detect_flips(t, y, thresh=180.0):
    """Return [(t_flip, boundary)] where boundary=+1 if it crossed +180, -1 if -180."""
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    d = np.diff(y)
    out = []
    for i in np.where(np.abs(d) > thresh)[0]:
        boundary = +1 if d[i] < 0 else -1   # big negative jump => went up over +180
        out.append((float(t[i]), boundary))
    return out


def add_flip_icons(ax, flips, y_icon=150, fontsize=28, dashed=True, animated=False):
    """
    Draw rotation icons (+ optional dashed marker line) for each flip on `ax`.

    Returns a list of (t_flip, text_artist, line_artist) so callers can reveal
    them over time. If animated=True the artists start hidden (alpha 0).
    """
    a0 = 0.0 if animated else 1.0
    items = []
    for tf, b in flips:
        sym = CW if b > 0 else CCW
        txt = ax.text(
            tf, y_icon, sym, fontsize=fontsize, ha="center", va="center",
            color="black", fontweight="bold", zorder=6, alpha=a0,
            path_effects=[pe.withStroke(linewidth=max(2.0, fontsize * 0.14), foreground="white")],
        )
        ln = None
        if dashed:
            ln = ax.axvline(tf, color="0.45", lw=1.1, ls="--", zorder=5,
                            alpha=0.0 if animated else 0.55)
        items.append((tf, txt, ln))
    return items


def reveal_flips(items, t_now):
    """For animations: show every icon whose flip time has been reached."""
    for tf, txt, ln in items:
        on = t_now >= tf
        txt.set_alpha(1.0 if on else 0.0)
        if ln is not None:
            ln.set_alpha(0.55 if on else 0.0)
