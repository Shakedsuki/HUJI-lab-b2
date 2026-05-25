"""
figure_style.py
---------------
Shared styling for palette (contact-sheet) tiles, so every figure type's
palette tile looks the same. Keeping this in one place means a tweak to the
tile look (tick count, label size) is a single edit, not one per type.
"""

from matplotlib.ticker import MaxNLocator


def compact_tile_ax(ax, xlabel, ylabel):
    """Dress a palette-tile axis: short symbol labels + 3 sparse numeric ticks
    so the scale stays legible without cluttering the contact sheet."""
    ax.set_xlabel(xlabel, fontsize=6, labelpad=1)
    ax.set_ylabel(ylabel, fontsize=6, labelpad=1)
    ax.tick_params(labelsize=5, length=2, pad=1)
    ax.xaxis.set_major_locator(MaxNLocator(3))
    ax.yaxis.set_major_locator(MaxNLocator(3))
    ax.grid(True, alpha=0.2)
    for sp in ax.spines.values():
        sp.set_linewidth(0.5)
