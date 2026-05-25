"""
figure_style.py
---------------
Shared styling for palette (contact-sheet) tiles, so every figure type's
palette tile looks the same. Keeping this in one place means a tweak to the
tile look (tick count, label size) is a single edit, not one per type.
"""

from matplotlib.ticker import MaxNLocator, LogLocator


def compact_tile_ax(ax, xlabel, ylabel, *, logx=False, logy=False):
    """Dress a palette-tile axis: short symbol labels + a few sparse ticks so the
    scale stays legible without cluttering the contact sheet. logx/logy switch the
    matching axis to sparse decade ticks (for log-log tiles like the power spectrum)."""
    ax.set_xlabel(xlabel, fontsize=6, labelpad=1)
    ax.set_ylabel(ylabel, fontsize=6, labelpad=1)
    ax.tick_params(labelsize=5, length=2, pad=1)
    ax.xaxis.set_major_locator(LogLocator(numticks=4) if logx else MaxNLocator(3))
    ax.yaxis.set_major_locator(LogLocator(numticks=4) if logy else MaxNLocator(3))
    if logx or logy:
        ax.tick_params(which="minor", length=0)   # decade majors only, no minor clutter
    ax.grid(True, alpha=0.2, which="major")
    for sp in ax.spines.values():
        sp.set_linewidth(0.5)
