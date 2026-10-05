"""
ui/pages/attendance_dashboard_page.py

Attendance overview for a selected date (+ optional subject filter):
present/absent/late counts, classroom occupancy percentage, and a
searchable table of every attendance record for that day.
"""

import logging
from datetime import date

import customtkinter as ctk
from tkinter import ttk

from database.db_connector import db
from database.models.attendance_model import AttendanceModel
from database.models.student_model import StudentModel

logger = logging.getLogger("SmartAttendAI.ui.pages.attendance_dashboard")


class AttendanceDashboardPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._selected_subject_id = None

        ctk.CTkLabel(
            self, text="Attendance", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        self._build_filter_bar()
        self._build_stat_cards()
        self._build_table()

        self._load_subjects()
        self.refresh()

    # ------------------------------------------------------------
    # Filter bar: date + subject + refresh
    # ------------------------------------------------------------
    def _build_filter_bar(self):
        row = ctk.CTkFrame(self, corner_radius=14)
        row.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(row, text="Date (YYYY-MM-DD)", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            side="left", padx=(16, 6), pady=14
        )
        self.date_entry = ctk.CTkEntry(row, width=130)
        self.date_entry.insert(0, date.today().isoformat())
        self.date_entry.pack(side="left", pady=14)

        ctk.CTkLabel(row, text="Subject", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            side="left", padx=(20, 6), pady=14
        )
        self.subject_var = ctk.StringVar(value="")
        self.subject_menu = ctk.CTkOptionMenu(
            row, values=["All Subjects"], variable=self.subject_var, width=180,
            command=lambda _v: self.refresh(),
        )
        self.subject_menu.pack(side="left", pady=14)

        ctk.CTkButton(row, text="Refresh", width=100, command=self.refresh).pack(
            side="left", padx=16, pady=14
        )

    # ------------------------------------------------------------
    # Summary cards
    # ------------------------------------------------------------
    def _build_stat_cards(self):
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.pack(fill="x", pady=(0, 16))
        for i in range(4):
            cards_row.grid_columnconfigure(i, weight=1, uniform="attcards")

        self.present_card = self._make_card(cards_row, "Present", "0", "#2ecc71")
        self.present_card.grid(row=0, column=0, sticky="nsew", padx=6)

        self.absent_card = self._make_card(cards_row, "Absent", "0", "#e74c3c")
        self.absent_card.grid(row=0, column=1, sticky="nsew", padx=6)

        self.late_card = self._make_card(cards_row, "Late", "0", "#f39c12")
        self.late_card.grid(row=0, column=2, sticky="nsew", padx=6)

        self.occupancy_card = self._make_card(cards_row, "Occupancy", "0%", None)
        self.occupancy_card.grid(row=0, column=3, sticky="nsew", padx=6)

    @staticmethod
    def _make_card(parent, title, value, accent):
        card = ctk.CTkFrame(parent, corner_radius=14)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=18, pady=(16, 2)
        )
        value_label = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=26, weight="bold"), text_color=accent)
        value_label.pack(anchor="w", padx=18, pady=(0, 16))
        card.value_label = value_label  # stash reference for updates
        return card

    # ------------------------------------------------------------
    # Table: present students + absentee list, tabbed
    # ------------------------------------------------------------
    def _build_table(self):
        container = ctk.CTkFrame(self, corner_radius=14)
        container.pack(fill="both", expand=True)

        self.tabs = ctk.CTkTabview(container)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=16)
        self.tabs.add("Present / Late")
        self.tabs.add("Absent")

        self.present_tree = self._make_tree(
            self.tabs.tab("Present / Late"),
            columns=("roll", "name", "status", "time", "confidence", "method"),
            headers={"roll": "Roll No.", "name": "Name", "status": "Status", "time": "Time",
                     "confidence": "Confidence", "method": "Method"},
        )
        self.absent_tree = self._make_tree(
            self.tabs.tab("Absent"),
            columns=("roll", "name", "dept"),
            headers={"roll": "Roll No.", "name": "Name", "dept": "Department"},
        )

    @staticmethod
    def _make_tree(parent, columns, headers):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            tree.heading(col, text=headers[col])
            tree.column(col, width=120, anchor="w")

        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        return tree

    # ------------------------------------------------------------
    # Subjects lookup (inline until SubjectModel exists)
    # ------------------------------------------------------------
    def _load_subjects(self):
        try:
            subjects = db.fetch_all("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name ASC")
        except Exception as exc:
            logger.error("Failed to load subjects: %s", exc)
            subjects = []

        self._subject_lookup = {s["subject_name"]: s["subject_id"] for s in subjects}
        names = ["All Subjects"] + list(self._subject_lookup.keys())
        self.subject_menu.configure(values=names)
        self.subject_var.set(names[0])

    # ------------------------------------------------------------
    # Refresh: pull data for the selected date/subject
    # ------------------------------------------------------------
    def refresh(self):
        target_date = self.date_entry.get().strip() or date.today().isoformat()
        subject_id = self._subject_lookup.get(self.subject_var.get())  # None = All Subjects

        try:
            records = AttendanceModel.get_by_date(target_date, subject_id=subject_id)
        except Exception as exc:
            logger.error("Failed to load attendance for %s: %s", target_date, exc)
            records = []

        try:
            all_students = StudentModel.get_all()
        except Exception as exc:
            logger.error("Failed to load students: %s", exc)
            all_students = []

        present_ids = {r["student_id"] for r in records if r["attendance_status"] in ("Present", "Late")}
        absentees = [s for s in all_students if s["student_id"] not in present_ids]

        present_count = sum(1 for r in records if r["attendance_status"] == "Present")
        late_count = sum(1 for r in records if r["attendance_status"] == "Late")
        total_students = len(all_students) or 1
        occupancy = round((len(present_ids) / total_students) * 100, 1)

        self.present_card.value_label.configure(text=str(present_count))
        self.late_card.value_label.configure(text=str(late_count))
        self.absent_card.value_label.configure(text=str(len(absentees)))
        self.occupancy_card.value_label.configure(text=f"{occupancy}%")

        self._populate_present_tree(records)
        self._populate_absent_tree(absentees)

    def _populate_present_tree(self, records):
        for row in self.present_tree.get_children():
            self.present_tree.delete(row)

        for r in records:
            confidence = r.get("recognition_confidence")
            confidence_text = f"{confidence:.0%}" if confidence is not None else "-"
            self.present_tree.insert("", "end", values=(
                r.get("roll_number") or "-",
                r.get("full_name") or "-",
                r.get("attendance_status"),
                str(r.get("time_in") or "-"),
                confidence_text,
                r.get("verification_method") or "-",
            ))

    def _populate_absent_tree(self, absentees):
        for row in self.absent_tree.get_children():
            self.absent_tree.delete(row)

        for s in absentees:
            self.absent_tree.insert("", "end", values=(
                s.get("roll_number") or "-",
                s.get("full_name") or "-",
                s.get("department_id") or "-",
            ))