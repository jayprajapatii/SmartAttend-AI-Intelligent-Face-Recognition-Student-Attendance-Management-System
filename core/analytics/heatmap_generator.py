"""
core/analytics/heatmap_generator.py

Builds the date x hour matrix used for the attendance heatmap
visualization, centralizing logic currently duplicated inline in
ui/pages/analytics_page.py's _build_heatmap(). Swap that page to call
generate() here instead of rebuilding the matrix by hand.

Usage:
    from core.analytics.heatmap_generator import heatmap_generator

    result = heatmap_generator.generate(start_date, end_date)
    # result.matrix: np.ndarray shaped (len(hours), len(dates))
    # result.date_labels, result.hour_labels: axis labels for plotting

    from ui.components.charts import heatmap_chart
    heatmap_chart(parent, result.matrix, result.date_labels, result.hour_labels)
"""

import logging
from dataclasses import dataclass

import numpy as np

from database.models.attendance_model import AttendanceModel

logger = logging.getLogger("SmartAttendAI.core.analytics.heatmap_generator")

DEFAULT_HOUR_RANGE = range(7, 19)  # typical class hours, 7am-6pm


@dataclass
class HeatmapResult:
    matrix: np.ndarray
    date_labels: list
    hour_labels: list
    peak_hour: int = None
    peak_date: str = None
    total_checkins: int = 0


class HeatmapGenerator:
    """Builds a (hour x date) check-in count matrix for heatmap visualization."""

    def generate(self, start_date: str, end_date: str, hour_range=DEFAULT_HOUR_RANGE) -> HeatmapResult:
        try:
            rows = AttendanceModel.get_heatmap_data(start_date, end_date)
        except Exception as exc:
            logger.error("Failed to load heatmap data: %s", exc)
            rows = []

        if not rows:
            return HeatmapResult(matrix=np.zeros((0, 0)), date_labels=[], hour_labels=[])

        date_labels = sorted({self._fmt_date(r["attendance_date"]) for r in rows})
        hour_labels = list(hour_range)

        date_index = {d: i for i, d in enumerate(date_labels)}
        hour_index = {h: i for i, h in enumerate(hour_labels)}

        matrix = np.zeros((len(hour_labels), len(date_labels)))
        total_checkins = 0

        for row in rows:
            date_key = self._fmt_date(row["attendance_date"])
            hour_key = row["hour_of_day"]
            count = row["count"]
            total_checkins += count

            if date_key in date_index and hour_key in hour_index:
                matrix[hour_index[hour_key], date_index[date_key]] += count

        peak_hour, peak_date = self._find_peak(matrix, hour_labels, date_labels)

        return HeatmapResult(
            matrix=matrix,
            date_labels=[self._display_date(d) for d in date_labels],
            hour_labels=[f"{h}:00" for h in hour_labels],
            peak_hour=peak_hour,
            peak_date=peak_date,
            total_checkins=total_checkins,
        )

    @staticmethod
    def _find_peak(matrix: np.ndarray, hour_labels: list, date_labels: list) -> tuple:
        if matrix.size == 0 or matrix.max() == 0:
            return None, None
        hour_idx, date_idx = np.unravel_index(np.argmax(matrix), matrix.shape)
        return hour_labels[hour_idx], date_labels[date_idx]

    @staticmethod
    def _fmt_date(value) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _display_date(iso_date: str) -> str:
        """Converts an ISO date string to a short display label, e.g. '08 Aug'."""
        try:
            from datetime import date
            d = date.fromisoformat(iso_date)
            return d.strftime("%d %b")
        except (ValueError, TypeError):
            return iso_date


# Singleton instance - import this everywhere instead of instantiating directly
heatmap_generator = HeatmapGenerator()