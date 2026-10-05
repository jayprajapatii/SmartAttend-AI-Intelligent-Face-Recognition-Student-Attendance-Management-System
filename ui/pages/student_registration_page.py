"""
ui/pages/student_registration_page.py

Student Management page: registration form (left) + searchable
student table (right). Uses StudentModel, DepartmentModel, CourseModel.

Note: Excel import/export and "Add Student -> Dataset Generator" hand-off
are left as TODO hooks - wire them to xlsx utilities / dataset_generator_page
once those are built.
"""

import logging
import customtkinter as ctk
from tkinter import ttk, messagebox

from database.models.student_model import StudentModel
from database.models.department_model import DepartmentModel
from database.models.course_model import CourseModel
from auth.rbac import can_access
from core.attendance_engine.qr_backup import qr_backup
from PIL import Image
import io

logger = logging.getLogger("SmartAttendAI.ui.pages.student_registration")


class StudentRegistrationPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._selected_student_id = None
        self._departments = {}
        self._courses = {}

        ctk.CTkLabel(
            self, text="Student Management", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_table_panel(body)

        self._load_lookup_data()
        self._refresh_table()

    # ------------------------------------------------------------
    # Left: registration / edit form
    # ------------------------------------------------------------
    def _build_form(self, parent):
        form_frame = ctk.CTkScrollableFrame(parent, width=340, corner_radius=14)
        form_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 16))

        self.form_title = ctk.CTkLabel(
            form_frame, text="Add New Student", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.form_title.pack(anchor="w", pady=(4, 16), padx=4)

        self.entries = {}
        fields = [
            ("enrollment_number", "Enrollment Number *"),
            ("full_name", "Full Name *"),
            ("roll_number", "Roll Number"),
            ("email", "Email"),
            ("phone_number", "Phone Number"),
            ("parent_contact", "Parent Contact"),
            ("date_of_birth", "Date of Birth (YYYY-MM-DD)"),
            ("semester", "Semester"),
            ("section", "Section"),
        ]
        for key, label in fields:
            ctk.CTkLabel(form_frame, text=label, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
                anchor="w", padx=4, pady=(6, 2)
            )
            entry = ctk.CTkEntry(form_frame, width=300)
            entry.pack(padx=4)
            self.entries[key] = entry

        ctk.CTkLabel(form_frame, text="Gender", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=4, pady=(6, 2)
        )
        self.gender_var = ctk.StringVar(value="Male")
        ctk.CTkOptionMenu(
            form_frame, values=["Male", "Female", "Other"], variable=self.gender_var, width=300
        ).pack(padx=4)

        ctk.CTkLabel(form_frame, text="Department", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=4, pady=(6, 2)
        )
        self.department_var = ctk.StringVar(value="")
        self.department_menu = ctk.CTkOptionMenu(
            form_frame, values=["Loading..."], variable=self.department_var, width=300,
            command=self._on_department_change,
        )
        self.department_menu.pack(padx=4)

        ctk.CTkLabel(form_frame, text="Course", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=4, pady=(6, 2)
        )
        self.course_var = ctk.StringVar(value="")
        self.course_menu = ctk.CTkOptionMenu(
            form_frame, values=["Select department first"], variable=self.course_var, width=300
        )
        self.course_menu.pack(padx=4)

        ctk.CTkLabel(form_frame, text="Address", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=4, pady=(6, 2)
        )
        self.address_text = ctk.CTkTextbox(form_frame, width=300, height=60)
        self.address_text.pack(padx=4)

        button_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        button_row.pack(fill="x", pady=(20, 4), padx=4)

        self.save_button = ctk.CTkButton(button_row, text="Save Student", command=self._handle_save)
        self.save_button.pack(fill="x", pady=(0, 6))

        self.clear_button = ctk.CTkButton(
            button_row, text="Clear / New", fg_color="transparent", border_width=1,
            command=self._clear_form,
        )
        self.clear_button.pack(fill="x")

        if can_access("students.delete"):
            self.delete_button = ctk.CTkButton(
                button_row, text="Delete Selected", fg_color="#e74c3c", hover_color="#c0392b",
                command=self._handle_delete,
            )
            self.delete_button.pack(fill="x", pady=(6, 0))

        self.generate_qr_button = ctk.CTkButton(
            button_row, text="Generate QR Code", fg_color="transparent", border_width=1,
            command=self._handle_generate_qr,
        )
        self.generate_qr_button.pack(fill="x", pady=(6, 0))


    # ------------------------------------------------------------
    # Right: search bar + student table
    # ------------------------------------------------------------
    def _build_table_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=14)
        panel.grid(row=0, column=1, sticky="nsew")

        search_row = ctk.CTkFrame(panel, fg_color="transparent")
        search_row.pack(fill="x", padx=16, pady=16)

        self.search_entry = ctk.CTkEntry(
            search_row, placeholder_text="Search by name, roll number, or enrollment number..."
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _e: self._refresh_table())

        ctk.CTkButton(search_row, text="Search", width=90, command=self._refresh_table).pack(side="left")
        ctk.CTkButton(
            search_row, text="Reset", width=90, fg_color="transparent", border_width=1,
            command=self._reset_search,
        ).pack(side="left", padx=(8, 0))

        table_container = ctk.CTkFrame(panel, fg_color="transparent")
        table_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        columns = ("id", "enrollment", "name", "roll", "dept", "course", "sem", "phone")
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.tree = ttk.Treeview(table_container, columns=columns, show="headings", selectmode="browse")
        headers = {
            "id": "ID", "enrollment": "Enrollment No.", "name": "Full Name", "roll": "Roll No.",
            "dept": "Department", "course": "Course", "sem": "Sem", "phone": "Phone",
        }
        widths = {"id": 50, "enrollment": 120, "name": 160, "roll": 90, "dept": 130, "course": 130, "sem": 50, "phone": 110}
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
    # Lookup data (departments / courses)
    # ------------------------------------------------------------
    def _load_lookup_data(self):
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
            self._on_department_change(names[0])

    def _on_department_change(self, department_name: str):
        department_id = self._departments.get(department_name)
        if not department_id:
            self.course_menu.configure(values=["No courses found"])
            return
        try:
            courses = CourseModel.get_by_department(department_id)
        except Exception as exc:
            logger.error("Failed to load courses: %s", exc)
            courses = []

        self._courses = {c["course_name"]: c["course_id"] for c in courses}
        names = list(self._courses.keys()) or ["No courses found"]
        self.course_menu.configure(values=names)
        self.course_var.set(names[0])

    # ------------------------------------------------------------
    # Table refresh / search
    # ------------------------------------------------------------
    def _refresh_table(self):
        keyword = self.search_entry.get().strip()
        try:
            students = StudentModel.search(keyword) if keyword else StudentModel.get_all()
        except Exception as exc:
            logger.error("Failed to load students: %s", exc)
            students = []

        for row in self.tree.get_children():
            self.tree.delete(row)

        dept_lookup = {v: k for k, v in self._departments.items()} if self._departments else {}

        for s in students:
            self.tree.insert("", "end", iid=str(s["student_id"]), values=(
                s["student_id"],
                s["enrollment_number"],
                s["full_name"],
                s.get("roll_number") or "-",
                dept_lookup.get(s.get("department_id"), "-"),
                s.get("course_id") or "-",
                s.get("semester") or "-",
                s.get("phone_number") or "-",
            ))

        self.count_label.configure(text=f"{len(students)} student(s) found")

    def _reset_search(self):
        self.search_entry.delete(0, "end")
        self._refresh_table()

    # ------------------------------------------------------------
    # Row selection -> populate form for editing
    # ------------------------------------------------------------
    def _on_row_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return

        student_id = int(selection[0])
        student = StudentModel.get_by_id(student_id)
        if not student:
            return

        self._selected_student_id = student_id
        self.form_title.configure(text=f"Edit: {student['full_name']}")

        self.entries["enrollment_number"].delete(0, "end")
        self.entries["enrollment_number"].insert(0, student.get("enrollment_number") or "")
        self.entries["full_name"].delete(0, "end")
        self.entries["full_name"].insert(0, student.get("full_name") or "")
        self.entries["roll_number"].delete(0, "end")
        self.entries["roll_number"].insert(0, student.get("roll_number") or "")
        self.entries["email"].delete(0, "end")
        self.entries["email"].insert(0, student.get("email") or "")
        self.entries["phone_number"].delete(0, "end")
        self.entries["phone_number"].insert(0, student.get("phone_number") or "")
        self.entries["parent_contact"].delete(0, "end")
        self.entries["parent_contact"].insert(0, student.get("parent_contact") or "")
        self.entries["date_of_birth"].delete(0, "end")
        dob = student.get("date_of_birth")
        self.entries["date_of_birth"].insert(0, str(dob) if dob else "")
        self.entries["semester"].delete(0, "end")
        self.entries["semester"].insert(0, str(student.get("semester") or ""))
        self.entries["section"].delete(0, "end")
        self.entries["section"].insert(0, student.get("section") or "")

        self.gender_var.set(student.get("gender") or "Male")

        self.address_text.delete("1.0", "end")
        self.address_text.insert("1.0", student.get("address") or "")

    # ------------------------------------------------------------
    # Save (create or update)
    # ------------------------------------------------------------
    def _handle_save(self):
        enrollment_number = self.entries["enrollment_number"].get().strip()
        full_name = self.entries["full_name"].get().strip()

        if not enrollment_number or not full_name:
            messagebox.showwarning("Missing Information", "Enrollment Number and Full Name are required.")
            return

        department_id = self._departments.get(self.department_var.get())
        course_id = self._courses.get(self.course_var.get())
        semester_raw = self.entries["semester"].get().strip()
        semester = int(semester_raw) if semester_raw.isdigit() else None

        payload = dict(
            full_name=full_name,
            gender=self.gender_var.get(),
            date_of_birth=self.entries["date_of_birth"].get().strip() or None,
            email=self.entries["email"].get().strip() or None,
            phone_number=self.entries["phone_number"].get().strip() or None,
            parent_contact=self.entries["parent_contact"].get().strip() or None,
            department_id=department_id,
            course_id=course_id,
            semester=semester,
            section=self.entries["section"].get().strip() or None,
            roll_number=self.entries["roll_number"].get().strip() or None,
            address=self.address_text.get("1.0", "end").strip() or None,
        )

        try:
            if self._selected_student_id:
                StudentModel.update(self._selected_student_id, **payload)
                messagebox.showinfo("Success", "Student updated successfully.")
            else:
                StudentModel.create(enrollment_number=enrollment_number, **payload)
                messagebox.showinfo("Success", "Student registered successfully.")
        except Exception as exc:
            logger.error("Failed to save student: %s", exc)
            messagebox.showerror("Error", f"Could not save student:\n{exc}")
            return

        self._clear_form()
        self._refresh_table()

    def _handle_delete(self):
        if not self._selected_student_id:
            messagebox.showwarning("No Selection", "Select a student from the table first.")
            return

        confirm = messagebox.askyesno(
            "Confirm Delete",
            "Deactivate this student? Their attendance history will be preserved.",
        )
        if not confirm:
            return

        try:
            StudentModel.soft_delete(self._selected_student_id)
        except Exception as exc:
            logger.error("Failed to delete student: %s", exc)
            messagebox.showerror("Error", f"Could not delete student:\n{exc}")
            return

        self._clear_form()
        self._refresh_table()
        
    def _handle_generate_qr(self):
        if not self._selected_student_id:
            messagebox.showwarning("No Selection", "Select a student from the table first.")
            return

        student = StudentModel.get_by_id(self._selected_student_id)
        if not student:
            messagebox.showerror("Error", "Could not load the selected student.")
            return

        try:
            token, png_bytes = qr_backup.generate_token(self._selected_student_id, valid_minutes=5)
        except Exception as exc:
            logger.error("Failed to generate QR token: %s", exc)
            messagebox.showerror("Error", f"Could not generate QR code:\n{exc}")
            return

        if png_bytes is None:
            messagebox.showerror(
                "Missing Dependency",
                "The 'qrcode' package is not installed.\nRun: pip install qrcode",
            )
            return

        popup = ctk.CTkToplevel(self)
        popup.title(f"QR Code - {student['full_name']}")
        popup.geometry("320x400")
        popup.resizable(False, False)

        pil_img = Image.open(io.BytesIO(png_bytes))
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(280, 280))

        image_label = ctk.CTkLabel(popup, image=ctk_img, text="")
        image_label.image = ctk_img  # keep a reference so it isn't garbage-collected
        image_label.pack(pady=16)

        ctk.CTkLabel(
            popup, text=f"{student['full_name']}\nValid for 5 minutes",
            font=ctk.CTkFont(size=13), justify="center",
        ).pack()

        logger.info("QR code generated for student_id=%s.", self._selected_student_id)


    def _clear_form(self):
        self._selected_student_id = None
        self.form_title.configure(text="Add New Student")
        for entry in self.entries.values():
            entry.delete(0, "end")
        self.address_text.delete("1.0", "end")
        self.gender_var.set("Male")
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())
        

    
