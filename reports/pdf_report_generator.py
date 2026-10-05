"""
reports/pdf_report_generator.py

Generates styled .pdf reports via ReportLab: title, generation
timestamp, optional summary block, a styled data table with
alternating row colors, and page numbers in the footer. This is the
reusable version of the export logic currently inline in
ui/pages/reports_page.py's _export_pdf() - swap that page to call
PDFReportGenerator.generate() instead.

Usage:
    from reports.pdf_report_generator import PDFReportGenerator

    PDFReportGenerator.generate(
        title="Daily Attendance Report - 2026-08-09",
        columns=[("roll_number", "Roll No."), ("full_name", "Name"), ("attendance_status", "Status")],
        rows=[{"roll_number": "101", "full_name": "Jay Prajapati", "attendance_status": "Present"}],
        filepath="data/reports/daily_attendance.pdf",
    )

    # With a summary section (e.g. counts by status):
    PDFReportGenerator.generate(
        title="...", columns=[...], rows=[...], filepath="...",
        summary={"Present": 28, "Absent": 4, "Late": 2},
    )
"""

import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

logger = logging.getLogger("SmartAttendAI.reports.pdf_report_generator")

HEADER_BG_COLOR = colors.HexColor("#3B82F6")
STRIPE_COLOR = colors.HexColor("#F5F5F5")
BORDER_COLOR = colors.HexColor("#E0E0E0")


class PDFReportGenerator:
    """Static-method generator - no instance state needed for PDF report creation."""

    @staticmethod
    def generate(
        title: str,
        columns: list,
        rows: list,
        filepath: str,
        summary: dict = None,
        orientation: str = "landscape",
        subtitle: str = None,
    ) -> str:
        """
        columns: list of (key, header) tuples.
        rows: list of dicts, each expected to have the column keys.
        summary: optional dict of label -> value, rendered as a small
                 bullet-style block above the table.
        orientation: "landscape" (default, better for wide tables) or "portrait".
        Returns the filepath written to.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        page_size = landscape(A4) if orientation == "landscape" else A4
        doc = SimpleDocTemplate(
            str(filepath), pagesize=page_size,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(title, styles["Title"]))

        if subtitle:
            elements.append(Paragraph(subtitle, styles["Normal"]))

        timestamp_style = ParagraphStyle(
            "Timestamp", parent=styles["Normal"], fontSize=8, textColor=colors.grey,
        )
        elements.append(Paragraph(
            f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", timestamp_style
        ))
        elements.append(Spacer(1, 12))

        if summary:
            elements.extend(PDFReportGenerator._build_summary_block(summary, styles))
            elements.append(Spacer(1, 12))

        elements.append(PDFReportGenerator._build_table(columns, rows))

        doc.build(
            elements,
            onFirstPage=PDFReportGenerator._add_page_number,
            onLaterPages=PDFReportGenerator._add_page_number,
        )

        logger.info("PDF report written: %s (%d row(s)).", filepath, len(rows))
        return str(filepath)

    # ------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------
    @staticmethod
    def _build_summary_block(summary: dict, styles) -> list:
        summary_style = ParagraphStyle(
            "Summary", parent=styles["Normal"], fontSize=10, leading=16,
        )
        parts = [f"<b>{label}:</b> {value}" for label, value in summary.items()]
        return [Paragraph("&nbsp;&nbsp;&nbsp;&nbsp;".join(parts), summary_style)]

    @staticmethod
    def _build_table(columns: list, rows: list) -> Table:
        keys = [c[0] for c in columns]
        headers = [c[1] for c in columns]

        table_data = [headers]
        for row in rows:
            table_data.append([
                str(row.get(k)) if row.get(k) is not None else "-" for k in keys
            ])

        table = Table(table_data, repeatRows=1)

        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, STRIPE_COLOR]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
        table.setStyle(TableStyle(style_commands))
        return table

    @staticmethod
    def _add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        page_text = f"Page {doc.page}"
        canvas.drawRightString(doc.pagesize[0] - 1.5 * cm, 1 * cm, page_text)
        canvas.restoreState()