"""
ui/components/charts.py

Reusable Matplotlib chart builders, pre-styled to match the app's
transparent-background CTk aesthetic. Each function builds a Figure
and embeds it in `parent` via FigureCanvasTkAgg, returning the
canvas widget so callers can pack/grid it or destroy+rebuild on
refresh.

Used by dashboard_page.py and analytics_page.py instead of each page
hand-rolling its own Matplotlib setup.

Usage:
    from ui.components.charts import line_chart, bar_chart, heatmap_chart

    canvas = line_chart(parent, x_labels=dates, y_values=counts,
                         y_label="Present")
    canvas.get_tk_widget().pack(fill="both", expand=True)
"""

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

DEFAULT_ACCENT = "#3b82f6"
DEFAULT_FIGSIZE = (8, 3)
DEFAULT_DPI = 100


def _new_figure(figsize=DEFAULT_FIGSIZE, dpi=DEFAULT_DPI):
    fig = Figure(figsize=figsize, dpi=dpi)
    fig.patch.set_alpha(0)  # transparent, so it blends with CTk frame background
    ax = fig.add_subplot(111)
    ax.patch.set_alpha(0)
    ax.spines[["top", "right"]].set_visible(False)
    return fig, ax


def _embed(fig, parent):
    canvas = FigureCanvasTkAgg(fig, master=parent)
    canvas.draw()
    return canvas


def _empty_state(ax, message: str = "No data available"):
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xticks([])
    ax.set_yticks([])


# ------------------------------------------------------------
# Line chart (trends over time)
# ------------------------------------------------------------
def line_chart(
    parent,
    x_labels: list,
    y_values: list,
    y_label: str = "",
    accent: str = DEFAULT_ACCENT,
    fill: bool = True,
    max_xticks: int = 12,
    figsize=DEFAULT_FIGSIZE,
):
    fig, ax = _new_figure(figsize)

    if x_labels and y_values:
        ax.plot(x_labels, y_values, marker="o", linewidth=2, color=accent, markersize=4)
        if fill:
            ax.fill_between(range(len(x_labels)), y_values, alpha=0.1, color=accent)
        step = max(len(x_labels) // max_xticks, 1)
        ax.set_xticks(range(0, len(x_labels), step))
        ax.set_xticklabels(x_labels[::step], rotation=45, ha="right", fontsize=8)
    else:
        _empty_state(ax)

    if y_label:
        ax.set_ylabel(y_label, fontsize=9)
    fig.tight_layout()
    return _embed(fig, parent)


# ------------------------------------------------------------
# Bar chart (category comparisons)
# ------------------------------------------------------------
def bar_chart(
    parent,
    categories: list,
    values: list,
    y_label: str = "",
    accent: str = DEFAULT_ACCENT,
    value_fmt: str = "%.0f",
    y_max: float = None,
    figsize=DEFAULT_FIGSIZE,
):
    fig, ax = _new_figure(figsize)

    if categories and values:
        bars = ax.bar(categories, values, color=accent)
        ax.bar_label(bars, fmt=value_fmt, fontsize=8, padding=2)
        if y_max:
            ax.set_ylim(0, y_max)
        ax.set_xticklabels(categories, rotation=20, ha="right", fontsize=8)
    else:
        _empty_state(ax)

    if y_label:
        ax.set_ylabel(y_label, fontsize=9)
    fig.tight_layout()
    return _embed(fig, parent)


# ------------------------------------------------------------
# Donut / pie chart (composition, e.g. Present/Absent/Late split)
# ------------------------------------------------------------
def donut_chart(
    parent,
    labels: list,
    values: list,
    colors: list = None,
    center_text: str = "",
    figsize=(4, 4),
):
    fig, ax = _new_figure(figsize)
    ax.axis("equal")

    if values and sum(values) > 0:
        colors = colors or ["#3b82f6", "#2ecc71", "#f39c12", "#e74c3c", "#9b59b6"]
        wedges, _texts = ax.pie(
            values, colors=colors[: len(values)], startangle=90,
            wedgeprops=dict(width=0.35, edgecolor="white"),
        )
        ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8, frameon=False)
        if center_text:
            ax.text(0, 0, center_text, ha="center", va="center", fontsize=14, fontweight="bold")
    else:
        _empty_state(ax)

    fig.tight_layout()
    return _embed(fig, parent)


# ------------------------------------------------------------
# Heatmap (e.g. attendance by date x hour)
# ------------------------------------------------------------
def heatmap_chart(
    parent,
    matrix: np.ndarray,
    x_labels: list,
    y_labels: list,
    cmap: str = "Blues",
    max_xticks: int = 12,
    colorbar_label: str = "",
    figsize=(9, 3.5),
):
    fig, ax = _new_figure(figsize)

    if matrix is not None and matrix.size > 0:
        im = ax.imshow(matrix, aspect="auto", cmap=cmap)
        step = max(len(x_labels) // max_xticks, 1)
        ax.set_xticks(range(0, len(x_labels), step))
        ax.set_xticklabels(x_labels[::step], rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(y_labels)))
        ax.set_yticklabels(y_labels, fontsize=7)
        fig.colorbar(im, ax=ax, shrink=0.8, label=colorbar_label)
    else:
        _empty_state(ax)

    fig.tight_layout()
    return _embed(fig, parent)


# ------------------------------------------------------------
# Progress ring (single-value gauge, e.g. attendance percentage)
# ------------------------------------------------------------
def progress_ring(
    parent,
    percentage: float,
    label: str = "",
    accent: str = DEFAULT_ACCENT,
    track_color: str = "#e5e5e5",
    figsize=(2.4, 2.4),
):
    fig, ax = _new_figure(figsize)
    ax.axis("equal")

    percentage = max(0.0, min(100.0, percentage))
    ax.pie(
        [percentage, 100 - percentage],
        colors=[accent, track_color],
        startangle=90, counterclock=False,
        wedgeprops=dict(width=0.22, edgecolor="none"),
    )
    ax.text(0, 0.05, f"{percentage:.0f}%", ha="center", va="center",
            fontsize=16, fontweight="bold")
    if label:
        ax.text(0, -0.25, label, ha="center", va="center", fontsize=9, color="gray")

    fig.tight_layout()
    return _embed(fig, parent)