"""
ui/pages/faculty_management_page.py

Faculty Management page: registration form (left) + searchable
faculty table (middle) + subject assignment panel (right, appears
once a faculty member is selected).

Uses FacultyModel, DepartmentModel, and a lightweight inline subject
lookup (SubjectModel hasn't been built yet - replace the two
`db.fetch_all()` calls below with SubjectModel once it exists).
"""

import logging
import customtkinter as ctk
from tkinter import ttk, messagebox

from database.db_connector import db
from database.models.faculty_model import FacultyModel
from database.models.department_model import DepartmentModel
from auth.rbac import can_access

logger = logging.getLogger("SmartAttendAI.ui.pages.faculty_management")


class FacultyManagementPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._selected_faculty_id = None
        self._departments = {}

        ctk.CTkLabel(
            self, text="Faculty Management", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0)
        body.grid_rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_table_panel(body)
        self._build_subjects_panel(body)

        self._load_departments()
        self._refresh_table()

    # ------------------------------------------------------------
    # Left: registration / edit form
    # ------------------------------------------------------------
    def _build_form(self, parent):
        form_frame = ctk.CTkScrollableFrame(parent, width=300, corner_radius=14)
        form_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 16))

        self.form_title = ctk.CTkLabel(
            form_frame, text="Add New Faculty", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.form_title.pack(anchor="w", pady=(4, 16), padx=4)

        self.entries = {}
        fields = [
            ("faculty_name", "Full Name *"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("designation", "Designation"),
        ]
        for key, label in fields:
            ctk.CTkLabel(form_frame, text=label, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
                anchor="w", padx=4, pady=(6, 2)
            )
            entry = ctk.CTkEntry(form_frame, width=260)
            entry.pack(padx=4)
            self.entries[key] = entry

        ctk.CTkLabel(form_frame, text="Department", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=4, pady=(6, 2)
        )
        self.department_var = ctk.StringVar(value="")
        self.department_menu = ctk.CTkOptionMenu(
            form_frame, values=["Loading..."], variable=self.department_var, width=260
        )
        self.department_menu.pack(padx=4)

        button_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(20, 4), padx=4)

        self.save_button = ctk.CTkButton(button_row, text="Save Faculty", command=self._handle_save)
        self.save_button.pack(fill="x", pady=(0, 6))

        self.clear_button = ctk.CTkButton(
            button_row, text="Clear / New", fg_color="transparent", border_width=1,
            command=self._clear_form,
        )
        self.clear_button.pack(fill="x")

        if can_access("faculty.delete"):
            self.deactivate_button = ctk.CTkButton(
                button_row, text="Deactivate Selected", fg_color="#e74c3c", hover_color="#c0392b",
                command=self._handle_deactivate,
            )
            self.deactivate_button.pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------
    # Middle: search bar + faculty table
    # ------------------------------------------------------------
    def _build_table_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=14)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 16))

        search_row = ctk.CTkFrame(panel, fg_color="transparent")
        search_row.pack(fill="x", padx=16, pady=16)

        self.search_entry = ctk.CTkEntry(search_row, placeholder_text="Search by name or email...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _e: self._refresh_table())

        ctk.CTkButton(search_row, text="Search", width=90, command=self._refresh_table).pack(side="left")
        ctk.CTkButton(
            search_row, text="Reset", width=90, fg_color="transparent", border_width=1,
            command=self._reset_search,
        ).pack(side="left", padx=(8, 0))

        table_container = ctk.CTkFrame(panel, fg_color="transparent")
        table_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        columns = ("id", "name", "dept", "email", "phone", "designation")
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.tree = ttk.Treeview(table_container, columns=columns, show="headings", selectmode="browse")
        headers = {
            "id": "ID", "name": "Name", "dept": "Department",
            "email": "Email", "phone": "Phone", "designation": "Designation",
        }
        widths = {"id": 45, "name": 150, "dept": 130, "email": 170, "phone": 110, "designation": 120}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="w")

        vsb = ttk.Scrollbar(table_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        self.count_label = ctk.CTkLabel(panel, text="", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"))
        self.count_label.pack(anchor="w", padx=16, pady=(0, 12))

    # ------------------------------------------------------------
    # Right: subject assignment panel
    # ------------------------------------------------------------
    def _build_subjects_panel(self, parent):
        panel = ctk.CTkFrame(parent, width=260, corner_radius=14)
        panel.grid(row=0, column=2, sticky="ns")
        panel.grid_propagate(False)

        self.subjects_title = ctk.CTkLabel(
            panel, text="Assigned Subjects", font=ctk.CTkFont(size=14, weight="bold")
        )
        self.subjects_title.pack(anchor="w", padx=16, pady=(16, 4))

        self.subjects_hint = ctk.CTkLabel(
            panel, text="Select a faculty member from the table to manage subjects.",
            font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"), wraplength=220, justify="left",
        )
        self.subjects_hint.pack(anchor="w", padx=16, pady=(0, 12))

        self.assigned_list_frame = ctk.CTkScrollableFrame(panel, width=230, height=200, fg_color="transparent")
        self.assigned_list_frame.pack(fill="x", padx=16)

        ctk.CTkLabel(
            panel, text="Assign a Subject", font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=16, pady=(16, 6))

        self.subject_to_assign_var = ctk.StringVar(value="")
        self.subject_menu = ctk.CTkOptionMenu(
            panel, values=["Select faculty first"], variable=self.subject_to_assign_var, width=220
        )
        self.subject_menu.pack(padx=16)

        ctk.CTkButton(panel, text="Assign", width=220, command=self._handle_assign_subject).pack(
            padx=16, pady=(8, 16)
        )

        self._all_subjects = {}  # subject_name -> subject_id

    def _refresh_subjects_panel(self):
        for widget in self.assigned_list_frame.winfo_children():
            widget.destroy()

        if not self._selected_faculty_id:
            self.subjects_hint.configure(text="Select a faculty member from the table to manage subjects.")
            self.subject_menu.configure(values=["Select faculty first"])
            return

        self.subjects_hint.configure(text="")

        try:
            assigned = FacultyModel.get_subjects(self._selected_faculty_id)
        except Exception as exc:
            logger.error("Failed to load assigned subjects: %s", exc)
            assigned = []

        if not assigned:
            ctk.CTkLabel(
                self.assigned_list_frame, text="No subjects assigned yet.",
                font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"),
            ).pack(anchor="w", pady=4)
        else:
            for subject in assigned:
                row = ctk.CTkFrame(self.assigned_list_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(
                    row, text=subject["subject_name"], font=ctk.CTkFont(size=12), anchor="w"
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    row, text="✕", width=24, height=24, fg_color="transparent",
                    text_color="#e74c3c", hover_color=("#f5f5f5", "#333333"),
                    command=lambda sid=subject["subject_id"]: self._handle_unassign_subject(sid),
                ).pack(side="right")

        self._load_assignable_subjects(exclude_ids={s["subject_id"] for s in assigned})

    def _load_assignable_subjects(self, exclude_ids: set):
        try:
            all_subjects = db.fetch_all("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name ASC")
        except Exception as exc:
            logger.error("Failed to load subjects list: %s", exc)
            all_subjects = []

        assignable = [s for s in all_subjects if s["subject_id"] not in exclude_ids]
        self._all_subjects = {s["subject_name"]: s["subject_id"] for s in assignable}
        names = list(self._all_subjects.keys()) or ["No subjects available"]
        self.subject_menu.configure(values=names)
        self.subject_to_assign_var.set(names[0])

    def _handle_assign_subject(self):
        if not self._selected_faculty_id:
            return
        subject_id = self._all_subjects.get(self.subject_to_assign_var.get())
        if not subject_id:
            return
        try:
            FacultyModel.assign_subject(self._selected_faculty_id, subject_id)
        except Exception as exc:
            logger.error("Failed to assign subject: %s", exc)
            messagebox.showerror("Error", f"Could not assign subject:\n{exc}")
            return
        self._refresh_subjects_panel()

    def _handle_unassign_subject(self, subject_id: int):
        if not self._selected_faculty_id:
            return
        try:
            FacultyModel.unassign_subject(self._selected_faculty_id, subject_id)
        except Exception as exc:
            logger.error("Failed to unassign subject: %s", exc)
            messagebox.showerror("Error", f"Could not unassign subject:\n{exc}")
            return
        self._refresh_subjects_panel()

    # ------------------------------------------------------------
    # Departments lookup
    # ------------------------------------------------------------
    def _load_departments(self):
        try:
            departments = DepartmentModel.get_all()
        except Exception as exc:
            logger.error("Failed to load departments: %s", exc)
            departments = []

        self._departments = {d["department_name"]: d["department_id"] for d in departments}
        names = list(self._departments.keys()) or ["No departments found"]
        self.department_menu.configure(values=names)
        if names:
            self.department_var.set(names[0])

    # ------------------------------------------------------------
    # Table refresh / search
    # ------------------------------------------------------------
    def _refresh_table(self):
        keyword = self.search_entry.get().strip()
        try:
            faculty_list = FacultyModel.search(keyword) if keyword else FacultyModel.get_all()
        except Exception as exc:
            logger.error("Failed to load faculty: %s", exc)
            faculty_list = []

        for row in self.tree.get_children():
            self.tree.delete(row)

        dept_lookup = {v: k for k, v in self._departments.items()} if self._departments else {}

        for f in faculty_list:
            self.tree.insert("", "end", iid=str(f["faculty_id"]), values=(
                f["faculty_id"],
                f["faculty_name"],
                dept_lookup.get(f.get("department_id"), "-"),
                f.get("email") or "-",
                f.get("phone") or "-",
                f.get("designation") or "-",
            ))

        self.count_label.configure(text=f"{len(faculty_list)} faculty member(s) found")

    def _reset_search(self):
        self.search_entry.delete(0, "end")
        self._refresh_table()

    # ------------------------------------------------------------
    # Row selection -> populate form + subjects panel
    # ------------------------------------------------------------
    def _on_row_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return

        faculty_id = int(selection[0])
        faculty = FacultyModel.get_by_id(faculty_id)
        if not faculty:
            return

        self._selected_faculty_id = faculty_id
        self.form_title.configure(text=f"Edit: {faculty['faculty_name']}")
        self.subjects_title.configure(text=f"Subjects - {faculty['faculty_name']}")

        self.entries["faculty_name"].delete(0, "end")
        self.entries["faculty_name"].insert(0, faculty.get("faculty_name") or "")
        self.entries["email"].delete(0, "end")
        self.entries["email"].insert(0, faculty.get("email") or "")
        self.entries["phone"].delete(0, "end")
        self.entries["phone"].insert(0, faculty.get("phone") or "")
        self.entries["designation"].delete(0, "end")
        self.entries["designation"].insert(0, faculty.get("designation") or "")

        dept_lookup = {v: k for k, v in self._departments.items()} if self._departments else {}
        dept_name = dept_lookup.get(faculty.get("department_id"))
        if dept_name:
            self.department_var.set(dept_name)

        self._refresh_subjects_panel()

    # ------------------------------------------------------------
    # Save (create or update)
    # ------------------------------------------------------------
    def _handle_save(self):
        faculty_name = self.entries["faculty_name"].get().strip()
        if not faculty_name:
            messagebox.showwarning("Missing Information", "Full Name is required.")
            return

        department_id = self._departments.get(self.department_var.get())
        payload = dict(
            faculty_name=faculty_name,
            department_id=department_id,
            email=self.entries["email"].get().strip() or None,
            phone=self.entries["phone"].get().strip() or None,
            designation=self.entries["designation"].get().strip() or None,
        )

        try:
            if self._selected_faculty_id:
                FacultyModel.update(self._selected_faculty_id, **payload)
                messagebox.showinfo("Success", "Faculty updated successfully.")
            else:
                FacultyModel.create(**payload)
                messagebox.showinfo("Success", "Faculty registered successfully.")
        except Exception as exc:
            logger.error("Failed to save faculty: %s", exc)
            messagebox.showerror("Error", f"Could not save faculty:\n{exc}")
            return

        self._clear_form()
        self._refresh_table()

    def _handle_deactivate(self):
        if not self._selected_faculty_id:
            messagebox.showwarning("No Selection", "Select a faculty member from the table first.")
            return

        confirm = messagebox.askyesno(
            "Confirm Deactivate", "Deactivate this faculty member? Their records will be preserved."
        )
        if not confirm:
            return

        try:
            FacultyModel.soft_delete(self._selected_faculty_id)
        except Exception as exc:
            logger.error("Failed to deactivate faculty: %s", exc)
            messagebox.showerror("Error", f"Could not deactivate faculty:\n{exc}")
            return

        self._clear_form()
        self._refresh_table()

    def _clear_form(self):
        self._selected_faculty_id = None
        self.form_title.configure(text="Add New Faculty")
        self.subjects_title.configure(text="Assigned Subjects")
        for entry in self.entries.values():
            entry.delete(0, "end")
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())
        self._refresh_subjects_panel()