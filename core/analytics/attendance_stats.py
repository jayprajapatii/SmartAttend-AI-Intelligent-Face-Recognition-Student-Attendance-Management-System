"""
core/analytics/attendance_stats.py

Descriptive statistics layer on top of AttendanceModel's raw queries:
summary numbers (mean/median attendance %, distribution buckets),
department/course comparisons, and per-student stat cards - the kind
of aggregation ui/pages/analytics_page.py and reports_page.py need
but shouldn't have to compute by hand from raw rows.

Usage:
    from core.analytics.attendance_stats import attendance_stats

    summary = attendance_stats.overall_summary(start_date, end_date)
    print(summary.mean_percentage, summary.median_percentage)

    buckets = attendance_stats.distribution_buckets(start_date, end_date)
    # {"90-100%": 42, "75-89%": 30, "50-74%": 12, "Below 50%": 5}
"""

import logging
import statistics
from dataclasses import dataclass

from database.models.attendance_model import AttendanceModel

logger = logging.getLogger("SmartAttendAI.core.analytics.attendance_stats")

DEFAULT_BUCKET_EDGES = [
    ("90-100%", 90, 100),
    ("75-89%", 75, 90),
    ("50-74%", 50, 75),
    ("Below 50%", 0, 50),
]


@dataclass
class AttendanceSummary:
    student_count: int
    mean_percentage: float
    median_percentage: float
    min_percentage: float
    max_percentage: float
    std_dev: float
    total_sessions_observed: int = 0


@dataclass
class DepartmentComparison:
    department_name: str
    student_count: int
    average_percentage: float


class AttendanceStats:
    """Computes summary statistics over a date range, backed by AttendanceModel queries."""

    # ------------------------------------------------------------
    # Overall summary (mean/median/std dev of per-student percentages)
    # ------------------------------------------------------------
    def overall_summary(self, start_date: str, end_date: str) -> AttendanceSummary:
        percentages = self._per_student_percentages(start_date, end_date)

        if not percentages:
            return AttendanceSummary(
                student_count=0, mean_percentage=0.0, median_percentage=0.0,
                min_percentage=0.0, max_percentage=0.0, std_dev=0.0,
            )

        return AttendanceSummary(
            student_count=len(percentages),
            mean_percentage=round(statistics.mean(percentages), 1),
            median_percentage=round(statistics.median(percentages), 1),
            min_percentage=round(min(percentages), 1),
            max_percentage=round(max(percentages), 1),
            std_dev=round(statistics.pstdev(percentages), 1) if len(percentages) > 1 else 0.0,
        )

    def _per_student_percentages(self, start_date: str, end_date: str) -> list:
        """
        Reuses AttendanceModel.get_weekly_report-style per-student
        session counts, converted to percentages. Percentage needs a
        denominator, so this estimates total sessions as the max
        days_present observed across all students in range (a
        reasonable proxy when no fixed session-calendar table exists
        yet to know the "true" number of classes held).
        """
        try:
            rows = AttendanceModel.get_weekly_report(start_date, end_date)
        except Exception as exc:
            logger.error("Failed to load attendance rows for stats: %s", exc)
            return []

        if not rows:
            return []

        max_sessions = max((r.get("days_present", 0) for r in rows), default=0) or 1
        return [
            round((r.get("days_present", 0) / max_sessions) * 100, 1)
            for r in rows
        ]

    # ------------------------------------------------------------
    # Distribution buckets (for a histogram / bar chart)
    # ------------------------------------------------------------
    def distribution_buckets(self, start_date: str, end_date: str, edges: list = None) -> dict:
        edges = edges or DEFAULT_BUCKET_EDGES
        percentages = self._per_student_percentages(start_date, end_date)

        buckets = {label: 0 for label, _, _ in edges}
        for pct in percentages:
            for label, low, high in edges:
                if low <= pct <= high:
                    buckets[label] += 1
                    break

        return buckets

    # ------------------------------------------------------------
    # Department-wise comparison
    # ------------------------------------------------------------
    def department_comparison(self, start_date: str, end_date: str) -> list:
        try:
            dept_stats = AttendanceModel.get_department_wise_stats(start_date, end_date)
        except Exception as exc:
            logger.error("Failed to load department stats: %s", exc)
            dept_stats = []

        results = []
        for d in dept_stats:
            total = d.get("total_students", 0)
            present = d.get("present_count", 0)
            avg_pct = round((present / total) * 100, 1) if total else 0.0
            results.append(DepartmentComparison(
                department_name=d.get("department_name", "Unknown"),
                student_count=total,
                average_percentage=avg_pct,
            ))

        return sorted(results, key=lambda r: r.average_percentage, reverse=True)

    # ------------------------------------------------------------
    # Single student stat card
    # ------------------------------------------------------------
    def student_summary(self, student_id: int, start_date: str, end_date: str) -> dict:
        try:
            percentage = AttendanceModel.get_student_attendance_percentage(student_id, start_date, end_date)
            records = AttendanceModel.get_by_student(student_id, start_date, end_date)
        except Exception as exc:
            logger.error("Failed to load student summary for student_id=%s: %s", student_id, exc)
            return {"percentage": 0.0, "present": 0, "absent": 0, "late": 0, "total": 0}

        present = sum(1 for r in records if r["attendance_status"] == "Present")
        late = sum(1 for r in records if r["attendance_status"] == "Late")
        absent = sum(1 for r in records if r["attendance_status"] == "Absent")

        return {
            "percentage": percentage,
            "present": present,
            "late": late,
            "absent": absent,
            "total": len(records),
        }


# Singleton instance - import this everywhere instead of instantiating directly
attendance_stats = AttendanceStats()