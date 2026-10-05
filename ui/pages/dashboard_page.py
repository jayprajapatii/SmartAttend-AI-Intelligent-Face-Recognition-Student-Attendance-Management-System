"""
ui/pages/dashboard_page.py

Main dashboard: summary cards, monthly attendance trend chart,
recent activity feed, camera/database status.

Pulls data from AttendanceModel, StudentModel, DepartmentModel,
CourseModel, and RecognitionLogModel - all built in database/models/.
"""

import logging
from datetime import date, timedelta

import customtkinter as ctk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from database.models.attendance_model import AttendanceModel
from database.models.student_model import StudentModel
from database.models.department_model import DepartmentModel
from database.models.course_model import CourseModel
from database.models.recognition_log_model import RecognitionLogModel
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.ui.pages.dashboard")


class StatCard(ctk.CTkFrame):
    """Small reusable metric card: title, big value, optional subtitle."""

    def __init__(self, master, title: str, value: str, subtitle: str = "", accent: str = None, **kwargs):
        super().__init__(master, corner_radius=14, **kwargs)

        ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8")
        ).pack(anchor="w", padx=18, pady=(16, 2))

        ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=28, weight="bold"),
            text_color=accent,
        ).pack(anchor="w", padx=18)

        if subtitle:
            ctk.CTkLabel(
                self, text=subtitle, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")
            ).pack(anchor="w", padx=18, pady=(2, 16))
        else:
            ctk.CTkLabel(self, text="").pack(pady=(0, 8))


class DashboardPage(ctk.CTkScrollableFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(
            self, text="Dashboard", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            self, text=date.today().strftime("%A, %B %d, %Y"),
            font=ctk.CTkFont(size=13), text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", pady=(0, 20))

        self._build_stat_cards()
        self._build_secondary_row()
        self._build_chart()
        self._build_recent_activity()

    # ------------------------------------------------------------
    # Row 1: primary attendance stats
    # ------------------------------------------------------------
    def _build_stat_cards(self):
        try:
            summary = AttendanceModel.get_today_summary()
        except Exception as exc:
            logger.error("Failed to load today's summary: %s", exc)
            summary = {
                "total_students": 0, "present_today": 0, "late_today": 0,
                "absent_today": 0, "attendance_percentage": 0.0,
            }

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(0, 16))
        for i in range(5):
            row.grid_columnconfigure(i, weight=1, uniform="stats")

        cards = [
            ("Total Students", str(summary["total_students"]), "Registered"),
            ("Present Today", str(summary["present_today"]), "Marked present", "#2ecc71"),
            ("Absent Today", str(summary["absent_today"]), "Not yet marked", "#e74c3c"),
            ("Late Students", str(summary["late_today"]), "Marked late", "#f39c12"),
            ("Attendance %", f"{summary['attendance_percentage']}%", "Today"),
        ]
        for i, card_args in enumerate(cards):
            title, value, subtitle = card_args[0], card_args[1], card_args[2]
            accent = card_args[3] if len(card_args) > 3 else None
            card = StatCard(row, title, value, subtitle, accent=accent)
            card.grid(row=0, column=i, sticky="nsew", padx=6)

    # ------------------------------------------------------------
    # Row 2: departments / courses / recognition accuracy / system status
    # ------------------------------------------------------------
    def _build_secondary_row(self):
        try:
            dept_count = len(DepartmentModel.get_all())
        except Exception:
            dept_count = 0

        try:
            course_count = len(CourseModel.get_all())
        except Exception:
            course_count = 0

        try:
            accuracy = RecognitionLogModel.get_accuracy_stats()
            accuracy_text = f"{accuracy['accuracy_percentage']}%"
        except Exception:
            accuracy_text = "N/A"

        db_status = "Connected" if self._check_db() else "Disconnected"
        db_color = "#2ecc71" if db_status == "Connected" else "#e74c3c"

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(0, 24))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="stats2")

        StatCard(row, "Departments", str(dept_count), "Registered").grid(row=0, column=0, sticky="nsew", padx=6)
        StatCard(row, "Courses", str(course_count), "Registered").grid(row=0, column=1, sticky="nsew", padx=6)
        StatCard(row, "Recognition Accuracy", accuracy_text, "Face recognition").grid(row=0, column=2, sticky="nsew", padx=6)
        StatCard(row, "Database Status", db_status, "MySQL connection", accent=db_color).grid(row=0, column=3, sticky="nsew", padx=6)

    @staticmethod
    def _check_db() -> bool:
        try:
            return db.is_connected()
        except Exception:
            return False

    # ------------------------------------------------------------
    # Monthly attendance trend chart (Matplotlib embedded in CTk)
    # ------------------------------------------------------------
    def _build_chart(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 24))

        ctk.CTkLabel(
            section, text="Attendance Trend (Last 30 Days)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        end_date = date.today()
        start_date = end_date - timedelta(days=29)

        try:
            trend = AttendanceModel.get_daily_trend(start_date.isoformat(), end_date.isoformat())
        except Exception as exc:
            logger.error("Failed to load attendance trend: %s", exc)
            trend = []

        dates = [row["attendance_date"].strftime("%d %b") if hasattr(row["attendance_date"], "strftime")
                 else str(row["attendance_date"]) for row in trend]
        present_counts = [row["present_count"] for row in trend]

        fig = Figure(figsize=(8, 3), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        ax.patch.set_alpha(0)

        if dates:
            ax.plot(dates, present_counts, marker="o", linewidth=2, color="#3b82f6")
            ax.fill_between(range(len(dates)), present_counts, alpha=0.1, color="#3b82f6")
            step = max(len(dates) // 10, 1)
            ax.set_xticks(range(0, len(dates), step))
            ax.set_xticklabels(dates[::step], rotation=45, ha="right", fontsize=8)
        else:
            ax.text(0.5, 0.5, "No attendance data yet", ha="center", va="center", transform=ax.transAxes)

        ax.set_ylabel("Present", fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=section)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # ------------------------------------------------------------
    # Recent activity feed
    # ------------------------------------------------------------
    def _build_recent_activity(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            section, text="Recent Attendance Activity",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(16, 8))

        try:
            recent = AttendanceModel.get_recent_activity(limit=8)
        except Exception as exc:
            logger.error("Failed to load recent activity: %s", exc)
            recent = []

        if not recent:
            ctk.CTkLabel(
                section, text="No recent activity.", text_color=("#64748B", "#94A3B8")
            ).pack(anchor="w", padx=20, pady=(0, 16))
            return

        for entry in recent:
            row = ctk.CTkFrame(section, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=4)

            status = entry.get("attendance_status", "Present")
            status_color = {
                "Present": "#2ecc71", "Late": "#f39c12", "Absent": "#e74c3c"
            }.get(status, "gray")

            ctk.CTkLabel(
                row, text="●", text_color=status_color, font=ctk.CTkFont(size=14)
            ).pack(side="left", padx=(0, 8))

            ctk.CTkLabel(
                row, text=f"{entry.get('full_name', 'Unknown')} ({entry.get('roll_number', '-')})",
                font=ctk.CTkFont(size=13), anchor="w",
            ).pack(side="left", fill="x", expand=True)

            confidence = entry.get("recognition_confidence")
            confidence_text = f"{confidence:.0%}" if confidence is not None else ""
            ctk.CTkLabel(
                row, text=confidence_text, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")
            ).pack(side="right", padx=(0, 10))

            time_str = str(entry.get("time_in", ""))
            ctk.CTkLabel(
                row, text=time_str, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")
            ).pack(side="right", padx=(0, 10))

        ctk.CTkLabel(section, text="").pack(pady=(0, 8))