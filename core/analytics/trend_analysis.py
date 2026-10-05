"""
core/analytics/trend_analysis.py

Time-series trend analysis on top of AttendanceModel.get_daily_trend():
moving averages, trend direction (rising/falling/stable) via simple
linear regression slope, and period-over-period comparisons
(e.g. this week vs. last week).

Usage:
    from core.analytics.trend_analysis import trend_analysis

    trend = trend_analysis.analyze(start_date, end_date)
    print(trend.direction, trend.slope_per_day, trend.moving_average)

    comparison = trend_analysis.compare_periods(
        current_start, current_end, previous_start, previous_end
    )
    print(comparison.change_percentage, comparison.direction)
"""

import logging
from dataclasses import dataclass

import numpy as np

from database.models.attendance_model import AttendanceModel

logger = logging.getLogger("SmartAttendAI.core.analytics.trend_analysis")

STABLE_SLOPE_THRESHOLD = 0.15   # students/day - slopes smaller than this count as "Stable"
DEFAULT_MOVING_AVERAGE_WINDOW = 7


@dataclass
class TrendResult:
    direction: str            # "Rising" | "Falling" | "Stable" | "Insufficient Data"
    slope_per_day: float
    moving_average: list       # smoothed series, same length as input (edges use a shorter window)
    raw_dates: list
    raw_values: list
    r_squared: float = 0.0     # how well the linear trend fits (0-1)


@dataclass
class PeriodComparison:
    current_total: int
    previous_total: int
    change_absolute: int
    change_percentage: float
    direction: str   # "Improved" | "Declined" | "Unchanged"


class TrendAnalysis:
    """Computes trend direction and moving averages over a date range of daily present-counts."""

    # ------------------------------------------------------------
    # Trend direction + moving average
    # ------------------------------------------------------------
    def analyze(self, start_date: str, end_date: str, moving_average_window: int = DEFAULT_MOVING_AVERAGE_WINDOW) -> TrendResult:
        try:
            rows = AttendanceModel.get_daily_trend(start_date, end_date)
        except Exception as exc:
            logger.error("Failed to load daily trend data: %s", exc)
            rows = []

        if len(rows) < 2:
            return TrendResult(
                direction="Insufficient Data", slope_per_day=0.0,
                moving_average=[], raw_dates=[], raw_values=[],
            )

        dates = [self._fmt_date(r["attendance_date"]) for r in rows]
        values = [r["present_count"] for r in rows]

        slope, r_squared = self._linear_fit(values)
        direction = self._classify_direction(slope)
        moving_avg = self._moving_average(values, moving_average_window)

        return TrendResult(
            direction=direction,
            slope_per_day=round(slope, 3),
            moving_average=moving_avg,
            raw_dates=dates,
            raw_values=values,
            r_squared=round(r_squared, 3),
        )

    @staticmethod
    def _linear_fit(values: list) -> tuple:
        """Returns (slope, r_squared) of a simple linear regression over the sequence index."""
        x = np.arange(len(values))
        y = np.array(values, dtype=float)

        if np.std(y) == 0:
            return 0.0, 0.0  # perfectly flat - no meaningful slope/fit

        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept
        ss_res = np.sum((y - predicted) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return float(slope), float(max(0.0, r_squared))

    @staticmethod
    def _classify_direction(slope: float) -> str:
        if slope > STABLE_SLOPE_THRESHOLD:
            return "Rising"
        if slope < -STABLE_SLOPE_THRESHOLD:
            return "Falling"
        return "Stable"

    @staticmethod
    def _moving_average(values: list, window: int) -> list:
        if window <= 1 or len(values) < 2:
            return list(values)

        result = []
        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_slice = values[start:i + 1]
            result.append(round(sum(window_slice) / len(window_slice), 2))
        return result

    # ------------------------------------------------------------
    # Period-over-period comparison (e.g. this week vs last week)
    # ------------------------------------------------------------
    def compare_periods(
        self, current_start: str, current_end: str, previous_start: str, previous_end: str
    ) -> PeriodComparison:
        try:
            current_rows = AttendanceModel.get_daily_trend(current_start, current_end)
            previous_rows = AttendanceModel.get_daily_trend(previous_start, previous_end)
        except Exception as exc:
            logger.error("Failed to load period comparison data: %s", exc)
            current_rows, previous_rows = [], []

        current_total = sum(r["present_count"] for r in current_rows)
        previous_total = sum(r["present_count"] for r in previous_rows)

        change_absolute = current_total - previous_total
        change_percentage = (
            round((change_absolute / previous_total) * 100, 1) if previous_total else 0.0
        )

        if change_absolute > 0:
            direction = "Improved"
        elif change_absolute < 0:
            direction = "Declined"
        else:
            direction = "Unchanged"

        return PeriodComparison(
            current_total=current_total,
            previous_total=previous_total,
            change_absolute=change_absolute,
            change_percentage=change_percentage,
            direction=direction,
        )

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _fmt_date(value) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)


# Singleton instance - import this everywhere instead of instantiating directly
trend_analysis = TrendAnalysis()