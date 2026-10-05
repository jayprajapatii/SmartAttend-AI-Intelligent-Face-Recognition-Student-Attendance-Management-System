"""
ui/components/progress_bar.py

Reusable progress indicators:
    - LabeledProgressBar: horizontal bar + percentage/count label,
      with optional color thresholds (e.g. green/yellow/red by value)
    - StepProgressBar: multi-step wizard indicator (e.g. dataset
      generation stages, registration wizards)
    - CircularProgress: lightweight pure-CTk ring (no Matplotlib) for
      small inline gauges - use ui.components.charts.progress_ring
      instead when you need a bigger, richer gauge.

Used by dataset_generator_page.py (capture progress), settings_page.py
(nothing yet, but useful for backup progress), and anywhere else that
currently builds its own raw CTkProgressBar + label pair.
"""

import customtkinter as ctk


# ------------------------------------------------------------
# Labeled linear progress bar
# ------------------------------------------------------------
class LabeledProgressBar(ctk.CTkFrame):
    """
    A progress bar with a title, a live "current / target" or "%"
    label, and optional color thresholds.

    Usage:
        bar = LabeledProgressBar(parent, title="Dataset Capture", total=150)
        bar.pack(fill="x")
        bar.set_progress(42)              # shows "42 / 150" and 28% fill
        bar.set_progress(150)             # complete - bar turns green automatically
        bar.set_progress(80, total=100)   # update total on the fly

        # Percentage-only mode (no fixed total):
        bar2 = LabeledProgressBar(parent, title="Attendance", mode="percentage")
        bar2.set_percentage(92.5)
    """

    DEFAULT_THRESHOLDS = [  # (min_percentage, color)
        (0, "#e74c3c"),    # red below 40%
        (40, "#f39c12"),   # amber 40-74%
        (75, "#2ecc71"),   # green 75%+
    ]

    def __init__(
        self,
        master,
        title: str = "",
        total: int = 100,
        mode: str = "count",  # "count" or "percentage"
        thresholds: list = None,
        show_percentage_label: bool = True,
        **kwargs,
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.total = max(total, 1)
        self.mode = mode
        self.thresholds = thresholds or self.DEFAULT_THRESHOLDS
        self._current = 0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")

        self.title_label = ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=12, weight="bold"))
        self.title_label.pack(side="left")

        self.value_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=12), text_color="gray")
        self.value_label.pack(side="right")

        self.bar = ctk.CTkProgressBar(self)
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(4, 0))

        self._show_percentage_label = show_percentage_label
        self._update_label()

    def set_progress(self, current: int, total: int = None):
        """Count mode: set current count out of total."""
        if total is not None:
            self.total = max(total, 1)
        self._current = max(0, min(current, self.total))
        fraction = self._current / self.total
        self.bar.set(fraction)
        self._apply_color(fraction * 100)
        self._update_label()

    def set_percentage(self, percentage: float):
        """Percentage mode: set 0-100 directly."""
        percentage = max(0.0, min(100.0, percentage))
        self._current = percentage
        self.bar.set(percentage / 100)
        self._apply_color(percentage)
        self._update_label()

    def _apply_color(self, percentage: float):
        color = self.thresholds[0][1]
        for min_pct, c in self.thresholds:
            if percentage >= min_pct:
                color = c
        self.bar.configure(progress_color=color)

    def _update_label(self):
        if not self._show_percentage_label:
            return
        if self.mode == "percentage":
            self.value_label.configure(text=f"{self._current:.0f}%")
        else:
            self.value_label.configure(text=f"{int(self._current)} / {int(self.total)}")

    def reset(self):
        self._current = 0
        self.bar.set(0)
        self._update_label()


# ------------------------------------------------------------
# Multi-step wizard indicator
# ------------------------------------------------------------
class StepProgressBar(ctk.CTkFrame):
    """
    Horizontal step indicator: circles connected by lines, each
    labeled below. Completed steps are filled/accented, the current
    step is outlined, future steps are muted.

    Usage:
        steps = StepProgressBar(parent, steps=[
            "Select Student", "Capture Images", "Generate Embeddings", "Done"
        ])
        steps.pack(fill="x", pady=20)
        steps.set_active_step(1)   # 0-indexed; marks step 0 complete, step 1 active
    """

    ACCENT = "#3b82f6"
    COMPLETE = "#2ecc71"
    MUTED = "#9ca3af"

    def __init__(self, master, steps: list, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.steps = steps
        self._circles = []
        self._labels = []
        self._connectors = []
        self._active_index = 0

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")
        for i in range(len(steps)):
            row.grid_columnconfigure(i, weight=1)

        for i, step_name in enumerate(steps):
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="nsew")

            circle_row = ctk.CTkFrame(cell, fg_color="transparent")
            circle_row.pack(fill="x")

            if i > 0:
                connector = ctk.CTkFrame(circle_row, height=2, fg_color=self.MUTED)
                connector.pack(side="left", fill="x", expand=True, pady=13)
                self._connectors.append(connector)

            circle = ctk.CTkLabel(
                circle_row, text=str(i + 1), width=28, height=28, corner_radius=14,
                fg_color=self.MUTED, text_color="white", font=ctk.CTkFont(size=12, weight="bold"),
            )
            circle.pack(side="left")
            self._circles.append(circle)

            label = ctk.CTkLabel(cell, text=step_name, font=ctk.CTkFont(size=10), text_color="gray")
            label.pack(pady=(6, 0))
            self._labels.append(label)

        self.set_active_step(0)

    def set_active_step(self, index: int):
        self._active_index = max(0, min(index, len(self.steps) - 1))

        for i, circle in enumerate(self._circles):
            if i < self._active_index:
                circle.configure(fg_color=self.COMPLETE, text="✓")
                self._labels[i].configure(text_color=self.COMPLETE)
            elif i == self._active_index:
                circle.configure(fg_color=self.ACCENT, text=str(i + 1))
                self._labels[i].configure(text_color=self.ACCENT)
            else:
                circle.configure(fg_color=self.MUTED, text=str(i + 1))
                self._labels[i].configure(text_color="gray")

        for i, connector in enumerate(self._connectors):
            # connector i sits between circle i and circle i+1
            connector.configure(fg_color=self.COMPLETE if i < self._active_index else self.MUTED)

    def next_step(self):
        self.set_active_step(self._active_index + 1)

    def previous_step(self):
        self.set_active_step(self._active_index - 1)


# ------------------------------------------------------------
# Lightweight circular progress (pure CTk, no Matplotlib)
# ------------------------------------------------------------
class CircularProgress(ctk.CTkFrame):
    """
    Small circular progress indicator built from a CTkProgressBar in
    'ring' orientation-adjacent style is not natively supported by
    CTk, so this uses a compact horizontal bar dressed as a badge -
    a true ring requires Canvas drawing. For a real ring/donut gauge,
    prefer ui.components.charts.progress_ring (Matplotlib-based).

    Usage:
        badge = CircularProgress(parent, percentage=82, label="Accuracy")
        badge.pack()
    """

    def __init__(self, master, percentage: float = 0, label: str = "", accent: str = "#3b82f6", size: int = 90, **kwargs):
        super().__init__(master, fg_color="transparent", width=size, height=size, **kwargs)
        self.canvas = ctk.CTkCanvas(self, width=size, height=size, highlightthickness=0, bg=self._bg_hex())
        self.canvas.pack()
        self.size = size
        self.accent = accent
        self.label = label
        self.set_percentage(percentage)

    def _bg_hex(self) -> str:
        # Best-effort match to the current CTk frame background so the
        # canvas doesn't show a mismatched square behind the circle.
        try:
            return self.master.cget("fg_color")[1] if ctk.get_appearance_mode() == "Dark" else self.master.cget("fg_color")[0]
        except Exception:
            return "#1a1a1a" if ctk.get_appearance_mode() == "Dark" else "#f5f5f5"

    def set_percentage(self, percentage: float):
        percentage = max(0.0, min(100.0, percentage))
        self.canvas.delete("all")

        pad = 6
        extent = -percentage / 100 * 360

        self.canvas.create_oval(pad, pad, self.size - pad, self.size - pad, outline="#e5e5e5", width=8)
        self.canvas.create_arc(
            pad, pad, self.size - pad, self.size - pad,
            start=90, extent=extent, style="arc", outline=self.accent, width=8,
        )
        self.canvas.create_text(
            self.size / 2, self.size / 2 - (6 if self.label else 0),
            text=f"{percentage:.0f}%", font=("Segoe UI", 13, "bold"), fill=self.accent,
        )
        if self.label:
            self.canvas.create_text(
                self.size / 2, self.size / 2 + 14,
                text=self.label, font=("Segoe UI", 8), fill="gray",
            )