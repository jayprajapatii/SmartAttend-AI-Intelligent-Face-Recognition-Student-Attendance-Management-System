"""
ui/pages/help_page.py

Help & documentation page: quick-start guide, collapsible FAQ
sections, and support contact info. Fully static content - no DB
calls - so it's safe to view for every role.
"""

import webbrowser
import customtkinter as ctk

import config

QUICK_START_STEPS = [
    ("1. Register Students", "Go to Student Management and add each student's details, "
                              "or bulk-import from an Excel sheet."),
    ("2. Generate Face Dataset", "Open Dataset Generator, select a student, and capture "
                                  "100-300 face images across different angles and lighting."),
    ("3. Assign Faculty & Subjects", "In Faculty Management, register faculty members and "
                                      "assign the subjects they teach."),
    ("4. Start Recognition", "Open Face Recognition, choose the subject/classroom, and start "
                              "the camera. Attendance is marked automatically as students are recognized."),
    ("5. Review & Export", "Use Attendance and Reports to review daily activity and export "
                            "PDF/Excel/CSV reports for any date range."),
]

FAQ_ITEMS = [
    ("A student isn't being recognized. What should I check?",
     "Make sure their face dataset has at least 100 images captured under varied lighting "
     "and angles. If recognition is still weak, lower the Recognition Threshold slightly in "
     "Settings (Admin only) - lower values match more leniently."),
    ("Why does the system say 'Unknown Face'?",
     "This means no stored face matched closely enough. It could be an unregistered person, "
     "a student without a completed dataset, or poor lighting/camera angle. Unknown faces are "
     "logged with a snapshot for admin review."),
    ("Can a student be marked present twice for the same class?",
     "No. The system enforces one attendance record per student, per subject, per day at the "
     "database level - duplicate/proxy attempts are automatically blocked."),
    ("How do I reset a forgotten admin password?",
     "On the login screen, click 'Forgot Password?', enter your username, and a verification "
     "code will be sent to your registered email. Enter the code to set a new password."),
    ("Where are exported reports saved?",
     "Reports are saved wherever you choose in the save dialog when exporting from the Reports "
     "page. A 'data/reports' folder is suggested by default."),
    ("Who can access Settings and Analytics?",
     "By default, Settings requires the super_admin role, and Analytics requires admin or "
     "higher. Faculty accounts see Dashboard, Face Recognition, Attendance, and Reports."),
    ("Does the system work without internet access?",
     "Yes - face recognition and attendance marking run entirely on the local machine and "
     "database. Internet is only needed for email/SMS notifications and optional cloud backups."),
]

SUPPORT_EMAIL = "support@smartattend.ai"
DOCS_URL = "https://example.com/smartattend-docs"  # replace with real docs URL when available


class HelpPage(ctk.CTkScrollableFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(
            self, text="Help & Documentation", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            self, text=f"{config.APP_NAME} v{config.APP_VERSION}",
            font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", pady=(0, 20))

        self._build_quick_start()
        self._build_faq()
        self._build_support()

    # ------------------------------------------------------------
    # Quick start guide
    # ------------------------------------------------------------
    def _build_quick_start(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            section, text="Quick Start Guide", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 12))

        for title, description in QUICK_START_STEPS:
            row = ctk.CTkFrame(section, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=6)

            ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(
                row, text=description, font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"),
                wraplength=800, justify="left",
            ).pack(anchor="w", pady=(2, 0))

        ctk.CTkLabel(section, text="").pack(pady=8)  # bottom spacer

    # ------------------------------------------------------------
    # FAQ (collapsible)
    # ------------------------------------------------------------
    def _build_faq(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 20))

        ctk.CTkLabel(
            section, text="Frequently Asked Questions", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 12))

        for question, answer in FAQ_ITEMS:
            self._build_faq_item(section, question, answer)

        ctk.CTkLabel(section, text="").pack(pady=8)  # bottom spacer

    def _build_faq_item(self, parent, question: str, answer: str):
        item_frame = ctk.CTkFrame(parent, fg_color="transparent")
        item_frame.pack(fill="x", padx=20, pady=2)

        answer_label = ctk.CTkLabel(
            item_frame, text=answer, font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"),
            wraplength=800, justify="left",
        )

        is_open = ctk.BooleanVar(value=False)

        def toggle():
            if is_open.get():
                answer_label.pack_forget()
                toggle_button.configure(text=f"▸  {question}")
                is_open.set(False)
            else:
                answer_label.pack(anchor="w", padx=24, pady=(2, 10), fill="x")
                toggle_button.configure(text=f"▾  {question}")
                is_open.set(True)

        toggle_button = ctk.CTkButton(
            item_frame, text=f"▸  {question}", anchor="w", fg_color="transparent",
            font=ctk.CTkFont(size=13), command=toggle,
        )
        toggle_button.pack(fill="x")

    # ------------------------------------------------------------
    # Support / contact
    # ------------------------------------------------------------
    def _build_support(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            section, text="Need More Help?", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            section,
            text=f"Contact your system administrator, or reach the SmartAttend AI support team at {SUPPORT_EMAIL}.",
            font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"), wraplength=800, justify="left",
        ).pack(anchor="w", padx=20)

        button_row = ctk.CTkFrame(section, fg_color="transparent")
        button_row.pack(anchor="w", padx=20, pady=(12, 20))

        ctk.CTkButton(
            button_row, text="Open Documentation", width=200,
            command=lambda: webbrowser.open(DOCS_URL),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            button_row, text="Email Support", width=200, fg_color="transparent", border_width=1,
            command=lambda: webbrowser.open(f"mailto:{SUPPORT_EMAIL}"),
        ).pack(side="left")