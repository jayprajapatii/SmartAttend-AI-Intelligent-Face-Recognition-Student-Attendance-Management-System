"""
utils/date_helper.py

Date/time utilities shared across pages and models that work with
attendance date ranges, report periods, and display formatting -
centralizes the "week starts Monday", "current academic period", and
"format a DB date for display" logic instead of each page reinventing
it (attendance_dashboard_page.py, reports_page.py, analytics_page.py
all need slightly different date-range math today).

Usage:
    from utils.date_helper import date_helper

    start, end = date_helper.week_range()               # this week (Mon-Sun)
    start, end = date_helper.month_range()               # this month
    start, end = date_helper.last_n_days(30)             # rolling window

    display = date_helper.format_display(some_date)       # "09 Aug 2026"
    relative = date_helper.relative_label(some_date)       # "Today" / "Yesterday" / "3 days ago"
"""

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger("SmartAttendAI.utils.date_helper")

ISO_FORMAT = "%Y-%m-%d"
DISPLAY_FORMAT = "%d %b %Y"
DISPLAY_FORMAT_SHORT = "%d %b"


class DateHelper:
    """Stateless date-range and formatting helpers."""

    # ------------------------------------------------------------
    # Common ranges (all return (start_date, end_date) as ISO strings)
    # ------------------------------------------------------------
    @staticmethod
    def today() -> str:
        return date.today().isoformat()

    @staticmethod
    def week_range(reference: date = None) -> tuple:
        """Monday-to-Sunday range containing `reference` (defaults to today)."""
        reference = reference or date.today()
        start = reference - timedelta(days=reference.weekday())
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()

    @staticmethod
    def month_range(reference: date = None) -> tuple:
        """First-to-last day of the month containing `reference` (defaults to today)."""
        reference = reference or date.today()
        start = reference.replace(day=1)
        if reference.month == 12:
            next_month = reference.replace(year=reference.year + 1, month=1, day=1)
        else:
            next_month = reference.replace(month=reference.month + 1, day=1)
        end = next_month - timedelta(days=1)
        return start.isoformat(), end.isoformat()

    @staticmethod
    def last_n_days(n: int, include_today: bool = True) -> tuple:
        """Rolling window ending today (or yesterday if include_today=False)."""
        end = date.today() if include_today else date.today() - timedelta(days=1)
        start = end - timedelta(days=n - 1)
        return start.isoformat(), end.isoformat()

    @staticmethod
    def previous_period(start_iso: str, end_iso: str) -> tuple:
        """
        Given a date range, returns the immediately preceding range of
        the same length - e.g. for week-over-week comparisons in
        core/analytics/trend_analysis.py's compare_periods().
        """
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
        length = (end - start).days + 1

        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=length - 1)
        return previous_start.isoformat(), previous_end.isoformat()

    # ------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------
    @staticmethod
    def format_display(value, fmt: str = DISPLAY_FORMAT) -> str:
        """Formats a date/datetime/ISO-string for display, e.g. '09 Aug 2026'."""
        parsed = DateHelper._coerce_date(value)
        if parsed is None:
            return str(value)
        return parsed.strftime(fmt)

    @staticmethod
    def format_short(value) -> str:
        return DateHelper.format_display(value, DISPLAY_FORMAT_SHORT)

    @staticmethod
    def relative_label(value) -> str:
        """Returns 'Today', 'Yesterday', 'N days ago', or a formatted date for anything older."""
        parsed = DateHelper._coerce_date(value)
        if parsed is None:
            return str(value)

        delta_days = (date.today() - parsed).days

        if delta_days == 0:
            return "Today"
        if delta_days == 1:
            return "Yesterday"
        if 0 < delta_days <= 7:
            return f"{delta_days} days ago"
        if delta_days < 0:
            return DateHelper.format_display(parsed)  # future date - just show it plainly
        return DateHelper.format_display(parsed)

    @staticmethod
    def _coerce_date(value):
        """Accepts a date, datetime, or ISO-format string and returns a date object, or None if unparseable."""
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                logger.debug("Could not parse date string: %s", value)
                return None
        return None

    # ------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------
    @staticmethod
    def is_weekend(value=None) -> bool:
        target = DateHelper._coerce_date(value) or date.today()
        return target.weekday() >= 5  # 5=Saturday, 6=Sunday

    @staticmethod
    def days_between(start_iso: str, end_iso: str) -> int:
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
        return (end - start).days + 1

    @staticmethod
    def date_list(start_iso: str, end_iso: str) -> list:
        """Every date (as ISO strings) between start and end, inclusive - useful for building a full calendar grid."""
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


# Singleton instance - import this everywhere instead of instantiating directly
date_helper = DateHelper()