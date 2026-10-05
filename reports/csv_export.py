"""
reports/csv_export.py

Generic CSV export utility. Simplest of the three report generators -
no styling concerns, just clean column-mapped rows to disk (or to an
in-memory string, e.g. for emailing as an attachment body).

Usage:
    from reports.csv_export import CSVExporter

    CSVExporter.generate(
        columns=[("roll_number", "Roll No."), ("full_name", "Name"), ("attendance_status", "Status")],
        rows=[{"roll_number": "101", "full_name": "Jay Prajapati", "attendance_status": "Present"}],
        filepath="data/reports/daily_attendance.csv",
    )

    # Or get the CSV as a string without writing to disk:
    csv_text = CSVExporter.to_string(columns, rows)
"""

import csv
import io
import logging
from pathlib import Path

logger = logging.getLogger("SmartAttendAI.reports.csv_export")


class CSVExporter:
    """Static-method exporter - no instance state needed for CSV generation."""

    @staticmethod
    def generate(columns: list, rows: list, filepath: str, encoding: str = "utf-8") -> str:
        """
        columns: list of (key, header) tuples, e.g. [("roll_number", "Roll No."), ...]
        rows: list of dicts, each expected to have the column keys.
        Returns the filepath written to (as a string), for convenience chaining.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        keys = [c[0] for c in columns]
        headers = [c[1] for c in columns]

        with open(filepath, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow([CSVExporter._safe_value(row.get(k)) for k in keys])

        logger.info("CSV report written: %s (%d row(s)).", filepath, len(rows))
        return str(filepath)

    @staticmethod
    def to_string(columns: list, rows: list) -> str:
        """Returns the CSV content as a string, without touching the filesystem."""
        keys = [c[0] for c in columns]
        headers = [c[1] for c in columns]

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([CSVExporter._safe_value(row.get(k)) for k in keys])

        return buffer.getvalue()

    @staticmethod
    def _safe_value(value):
        return value if value is not None else "-"