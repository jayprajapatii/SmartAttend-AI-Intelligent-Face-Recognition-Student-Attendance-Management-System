"""
ui/pages/analytics_page.py

Smart Attendance Analytics: daily trend chart, department-wise
comparison, attendance heatmap (day x hour), and an at-risk /
low-attendance student list (feeds the "Attendance Prediction"
feature described in the spec - this page surfaces the data;
a real ML model can later replace the simple threshold rule in
AttendanceModel.get_low_attendance_students()).
"""

import logging
from datetime import date, timedelta

import customtkinter as ctk
from tkinter import ttk
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database.models.attendance_model import AttendanceModel

logger = logging.getLogger("SmartAttendAI.ui.pages.analytics")

LOW_ATTENDANCE_THRESHOLD = 75.0  # percent
DEFAULT_RANGE_DAYS = 30


class AnalyticsPage(ctk.CTkScrollableFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(
            self, text="Analytics", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            self, text=f"Last {DEFAULT_RANGE_DAYS} days", font=ctk.CTkFont(size=13), text_color=("#64748B", "#94A3B8")
        ).pack(anchor="w", pady=(0, 20))

        self.end_date = date.today()
        self.start_date = self.end_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)

        self._build_trend_chart()
        self._build_department_chart()
        self._build_heatmap()
        self._build_at_risk_table()

    # ------------------------------------------------------------
    # Daily attendance trend (line chart)
    # ------------------------------------------------------------
    def _build_trend_chart(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            section, text="Daily Attendance Trend", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 8))

        try:
            trend = AttendanceModel.get_daily_trend(self.start_date.isoformat(), self.end_date.isoformat())
        except Exception as exc:
            logger.error("Failed to load trend data: %s", exc)
            trend = []

        dates = [self._fmt_date(r["attendance_date"]) for r in trend]
        present = [r["present_count"] for r in trend]

        fig = Figure(figsize=(9, 3), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        ax.patch.set_alpha(0)

        if dates:
            ax.plot(dates, present, marker="o", linewidth=2, color="#3b82f6")
            ax.fill_between(range(len(dates)), present, alpha=0.1, color="#3b82f6")
            step = max(len(dates) // 12, 1)
            ax.set_xticks(range(0, len(dates), step))
            ax.set_xticklabels(dates[::step], rotation=45, ha="right", fontsize=8)
        else:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)

        ax.set_ylabel("Students Present", fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()

        self._embed_chart(fig, section)

    # ------------------------------------------------------------
    # Department-wise comparison (bar chart)
    # ------------------------------------------------------------
    def _build_department_chart(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            section, text="Department-wise Attendance", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 8))

        try:
            dept_stats = AttendanceModel.get_department_wise_stats(
                self.start_date.isoformat(), self.end_date.isoformat()
            )
        except Exception as exc:
            logger.error("Failed to load department stats: %s", exc)
            dept_stats = []

        names = [d["department_name"] for d in dept_stats]
        percentages = [
            round((d["present_count"] / d["total_students"]) * 100, 1) if d["total_students"] else 0
            for d in dept_stats
        ]

        fig = Figure(figsize=(9, 3), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        ax.patch.set_alpha(0)

        if names:
            bars = ax.bar(names, percentages, color="#3b82f6")
            ax.bar_label(bars, fmt="%.0f%%", fontsize=8, padding=2)
            ax.set_ylim(0, 110)
            plt_labels = ax.get_xticklabels()
            ax.set_xticklabels(plt_labels, rotation=20, ha="right", fontsize=8)
        else:
            ax.text(0.5, 0.5, "No department data available", ha="center", va="center", transform=ax.transAxes)

        ax.set_ylabel("Attendance %", fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()

        self._embed_chart(fig, section)

    # ------------------------------------------------------------
    # Heatmap (date x hour)
    # ------------------------------------------------------------
    def _build_heatmap(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            section, text="Attendance Heatmap (Date x Hour)", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 8))

        try:
            heatmap_rows = AttendanceModel.get_heatmap_data(self.start_date.isoformat(), self.end_date.isoformat())
        except Exception as exc:
            logger.error("Failed to load heatmap data: %s", exc)
            heatmap_rows = []

        fig = Figure(figsize=(9, 3.5), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)

        if heatmap_rows:
            unique_dates = sorted({self._fmt_date(r["attendance_date"]) for r in heatmap_rows})
            hours = list(range(7, 19))  # typical class hours 7am-6pm
            matrix = np.zeros((len(hours), len(unique_dates)))

            date_index = {d: i for i, d in enumerate(unique_dates)}
            hour_index = {h: i for i, h in enumerate(hours)}

            for row in heatmap_rows:
                d = self._fmt_date(row["attendance_date"])
                h = row["hour_of_day"]
                if d in date_index and h in hour_index:
                    matrix[hour_index[h], date_index[d]] = row["count"]

            im = ax.imshow(matrix, aspect="auto", cmap="Blues")
            step = max(len(unique_dates) // 12, 1)
            ax.set_xticks(range(0, len(unique_dates), step))
            ax.set_xticklabels(unique_dates[::step], rotation=45, ha="right", fontsize=7)
            ax.set_yticks(range(len(hours)))
            ax.set_yticklabels([f"{h}:00" for h in hours], fontsize=7)
            fig.colorbar(im, ax=ax, shrink=0.8, label="Check-ins")
        else:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)

        fig.tight_layout()
        self._embed_chart(fig, section)

    # ------------------------------------------------------------
    # At-risk / low attendance students
    # ------------------------------------------------------------
    def _build_at_risk_table(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            section, text=f"At-Risk Students (below {LOW_ATTENDANCE_THRESHOLD:.0f}% attendance)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        try:
            at_risk = AttendanceModel.get_low_attendance_students(
                LOW_ATTENDANCE_THRESHOLD, self.start_date.isoformat(), self.end_date.isoformat()
            )
        except Exception as exc:
            logger.error("Failed to load at-risk students: %s", exc)
            at_risk = []

        table_frame = ctk.CTkFrame(section, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        columns = ("roll", "name", "attended", "total", "percentage")
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=8)
        headers = {
            "roll": "Roll No.", "name": "Name", "attended": "Attended",
            "total": "Total Sessions", "percentage": "Attendance %",
        }
        for col in columns:
            tree.heading(col, text=headers[col])
            tree.column(col, width=140, anchor="w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        if not at_risk:
            tree.insert("", "end", values=("-", "No students below threshold", "-", "-", "-"))
        else:
            for s in at_risk:
                tree.insert("", "end", values=(
                    s.get("roll_number") or "-",
                    s.get("full_name") or "-",
                    s.get("attended", 0),
                    s.get("total_sessions", 0),
                    f"{s.get('attendance_percentage', 0)}%",
                ))

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _fmt_date(value) -> str:
        return value.strftime("%d %b") if hasattr(value, "strftime") else str(value)

    @staticmethod
    def _embed_chart(fig, parent):
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=16, pady=(0, 16))