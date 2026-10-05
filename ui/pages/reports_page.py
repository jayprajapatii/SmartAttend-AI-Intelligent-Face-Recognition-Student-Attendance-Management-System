"""
ui/pages/reports_page.py

Report generation: daily, weekly, monthly, and subject-wise attendance
reports, previewed in a table and exportable as PDF, Excel, or CSV.

Export destinations: data/backups/../reports/ (created on demand).
"""

import csv
import logging
from datetime import date, timedelta
from pathlib import Path

import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

import config
from database.db_connector import db
from database.models.attendance_model import AttendanceModel

logger = logging.getLogger("SmartAttendAI.ui.pages.reports")

REPORT_TYPES = ("Daily", "Weekly", "Monthly", "Subject-wise")


class ReportsPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._current_rows = []       # last-generated report rows, for export
        self._current_columns = []    # (key, header) pairs matching self._current_rows

        ctk.CTkLabel(
            self, text="Reports", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        self._build_filter_bar()
        self._build_table()
        self._build_export_bar()

        self._load_subjects()

    # ------------------------------------------------------------
    # Filter bar
    # ------------------------------------------------------------
    def _build_filter_bar(self):
        row = ctk.CTkFrame(self, corner_radius=14)
        row.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(row, text="Report Type", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            side="left", padx=(16, 6), pady=14
        )
        self.report_type_var = ctk.StringVar(value="Daily")
        ctk.CTkOptionMenu(
            row, values=list(REPORT_TYPES), variable=self.report_type_var, width=140,
            command=self._on_report_type_change,
        ).pack(side="left", pady=14)

        ctk.CTkLabel(row, text="Date", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            side="left", padx=(20, 6), pady=14
        )
        self.date_entry = ctk.CTkEntry(row, width=120, placeholder_text="YYYY-MM-DD")
        self.date_entry.insert(0, date.today().isoformat())
        self.date_entry.pack(side="left", pady=14)

        self.subject_label = ctk.CTkLabel(row, text="Subject", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"))
        self.subject_var = ctk.StringVar(value="")
        self.subject_menu = ctk.CTkOptionMenu(row, values=["Loading..."], variable=self.subject_var, width=160)
        # subject controls are shown/hidden based on report type (see _on_report_type_change)

        ctk.CTkButton(row, text="Generate", width=110, command=self._generate).pack(
            side="left", padx=16, pady=14
        )

    def _on_report_type_change(self, report_type: str):
        if report_type == "Subject-wise":
            self.subject_label.pack(side="left", padx=(20, 6), pady=14)
            self.subject_menu.pack(side="left", pady=14)
        else:
            self.subject_label.pack_forget()
            self.subject_menu.pack_forget()

    def _load_subjects(self):
        try:
            subjects = db.fetch_all("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name ASC")
        except Exception as exc:
            logger.error("Failed to load subjects: %s", exc)
            subjects = []
        self._subject_lookup = {s["subject_name"]: s["subject_id"] for s in subjects}
        names = list(self._subject_lookup.keys()) or ["No subjects found"]
        self.subject_menu.configure(values=names)
        self.subject_var.set(names[0])

    # ------------------------------------------------------------
    # Table
    # ------------------------------------------------------------
    def _build_table(self):
        container = ctk.CTkFrame(self, corner_radius=14)
        container.pack(fill="both", expand=True, pady=(0, 16))

        self.table_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.table_frame.pack(fill="both", expand=True, padx=16, pady=16)

        self.tree = None  # built dynamically per report type in _render_table()

        self.summary_label = ctk.CTkLabel(container, text="", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"))
        self.summary_label.pack(anchor="w", padx=16, pady=(0, 12))

    def _render_table(self, columns: list):
        """columns: list of (key, header) tuples."""
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        self._current_columns = columns
        col_keys = [c[0] for c in columns]

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.tree = ttk.Treeview(self.table_frame, columns=col_keys, show="headings", selectmode="browse")
        for key, header in columns:
            self.tree.heading(key, text=header)
            self.tree.column(key, width=130, anchor="w")

        vsb = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ------------------------------------------------------------
    # Export bar
    # ------------------------------------------------------------
    def _build_export_bar(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkButton(row, text="Export PDF", width=130, command=lambda: self._export("pdf")).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(row, text="Export Excel", width=130, command=lambda: self._export("xlsx")).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(row, text="Export CSV", width=130, command=lambda: self._export("csv")).pack(
            side="left"
        )

    # ------------------------------------------------------------
    # Generate report
    # ------------------------------------------------------------
    def _generate(self):
        report_type = self.report_type_var.get()
        target_date_str = self.date_entry.get().strip() or date.today().isoformat()

        try:
            target_date = date.fromisoformat(target_date_str)
        except ValueError:
            messagebox.showwarning("Invalid Date", "Please enter a date in YYYY-MM-DD format.")
            return

        try:
            if report_type == "Daily":
                rows = AttendanceModel.get_daily_report(target_date.isoformat())
                columns = [
                    ("roll_number", "Roll No."), ("full_name", "Name"),
                    ("attendance_status", "Status"), ("time_in", "Time"),
                ]
                self._current_rows = rows
                title = f"Daily Attendance Report - {target_date.isoformat()}"

            elif report_type == "Weekly":
                start = target_date - timedelta(days=target_date.weekday())
                end = start + timedelta(days=6)
                rows = AttendanceModel.get_weekly_report(start.isoformat(), end.isoformat())
                columns = [
                    ("roll_number", "Roll No."), ("full_name", "Name"), ("days_present", "Days Present"),
                ]
                self._current_rows = rows
                title = f"Weekly Attendance Report - {start.isoformat()} to {end.isoformat()}"

            elif report_type == "Monthly":
                rows = AttendanceModel.get_monthly_report(target_date.year, target_date.month)
                columns = [
                    ("roll_number", "Roll No."), ("full_name", "Name"), ("days_present", "Days Present"),
                ]
                self._current_rows = rows
                title = f"Monthly Attendance Report - {target_date.strftime('%B %Y')}"

            else:  # Subject-wise
                subject_id = self._subject_lookup.get(self.subject_var.get())
                if not subject_id:
                    messagebox.showwarning("No Subject", "Select a subject first.")
                    return
                start = target_date - timedelta(days=30)
                rows = AttendanceModel.get_subject_wise_report(subject_id, start.isoformat(), target_date.isoformat())
                columns = [
                    ("roll_number", "Roll No."), ("full_name", "Name"), ("classes_attended", "Classes Attended"),
                ]
                self._current_rows = rows
                title = f"Subject-wise Report - {self.subject_var.get()} (last 30 days)"

        except Exception as exc:
            logger.error("Report generation failed: %s", exc)
            messagebox.showerror("Error", f"Could not generate report:\n{exc}")
            return

        self._current_title = title
        self._render_table(columns)
        self._populate_table(self._current_rows, columns)
        self.summary_label.configure(text=f"{title} - {len(self._current_rows)} row(s)")

    def _populate_table(self, rows, columns):
        keys = [c[0] for c in columns]
        for row in rows:
            values = [row.get(k, "-") if row.get(k) is not None else "-" for k in keys]
            self.tree.insert("", "end", values=values)

    # ------------------------------------------------------------
    # Export
    # ------------------------------------------------------------
    def _export(self, fmt: str):
        if not self._current_rows:
            messagebox.showwarning("Nothing to Export", "Generate a report first.")
            return

        reports_dir = config.BASE_DIR / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        default_name = self._current_title.replace(" ", "_").replace(":", "") + f".{fmt}"

        filetypes = {
            "pdf": [("PDF files", "*.pdf")],
            "xlsx": [("Excel files", "*.xlsx")],
            "csv": [("CSV files", "*.csv")],
        }[fmt]

        filepath = filedialog.asksaveasfilename(
            initialdir=str(reports_dir), initialfile=default_name,
            defaultextension=f".{fmt}", filetypes=filetypes,
        )
        if not filepath:
            return

        try:
            if fmt == "csv":
                self._export_csv(filepath)
            elif fmt == "xlsx":
                self._export_xlsx(filepath)
            elif fmt == "pdf":
                self._export_pdf(filepath)
        except Exception as exc:
            logger.error("Export to %s failed: %s", fmt, exc)
            messagebox.showerror("Export Error", f"Could not export report:\n{exc}")
            return

        messagebox.showinfo("Export Complete", f"Report saved to:\n{filepath}")

    def _export_csv(self, filepath: str):
        keys = [c[0] for c in self._current_columns]
        headers = [c[1] for c in self._current_columns]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in self._current_rows:
                writer.writerow([row.get(k, "-") for k in keys])

    def _export_xlsx(self, filepath: str):
        keys = [c[0] for c in self._current_columns]
        headers = [c[1] for c in self._current_columns]

        wb = Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(headers)
        for row in self._current_rows:
            ws.append([row.get(k, "-") for k in keys])

        for col_cells in ws.columns:
            max_length = max(len(str(cell.value)) for cell in col_cells if cell.value is not None) if col_cells else 10
            ws.column_dimensions[col_cells[0].column_letter].width = max(12, max_length + 2)

        wb.save(filepath)

    def _export_pdf(self, filepath: str):
        keys = [c[0] for c in self._current_columns]
        headers = [c[1] for c in self._current_columns]

        doc = SimpleDocTemplate(filepath, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = [Paragraph(self._current_title, styles["Title"]), Spacer(1, 12)]

        table_data = [headers] + [
            [str(row.get(k, "-")) for k in keys] for row in self._current_rows
        ]
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        doc.build(elements)