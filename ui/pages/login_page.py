"""
ui/pages/login_page.py

Standalone login page, backed by auth.login.authenticate_user().
Includes a lightweight "Forgot Password" flow wired to
auth.otp_verification + auth.password_reset.
"""

import logging
import customtkinter as ctk

import config
from ui.design_system import BG, SURFACE, BORDER, TEXT, MUTED, PRIMARY, PRIMARY_HOVER, DANGER
from auth.login import authenticate_user
from auth.otp_verification import request_otp
from auth.password_reset import reset_password_with_otp

logger = logging.getLogger("SmartAttendAI.ui.pages.login")


class LoginPage(ctk.CTkFrame):
    """Admin/Faculty login screen with inline forgot-password flow."""

    def __init__(self, master, on_login_success):
        super().__init__(master, fg_color=BG)
        self.on_login_success = on_login_success
        self._mode = "login"  # "login" | "forgot_request" | "forgot_verify"
        self._reset_username = None

        self.container = ctk.CTkFrame(self, corner_radius=18, width=420, fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.container.place(relx=0.5, rely=0.5, anchor="center")

        self._render_login_form()

    # ------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------
    def _clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def _title(self, text: str, subtitle: str):
        ctk.CTkLabel(
            self.container, text=text, font=ctk.CTkFont(size=26, weight="bold"), text_color=TEXT
        ).pack(pady=(40, 5), padx=40)
        ctk.CTkLabel(
            self.container, text=subtitle, text_color=("#64748B", "#94A3B8"), font=ctk.CTkFont(size=13)
        ).pack(pady=(0, 25))

    # ------------------------------------------------------------
    # Screen 1: Login
    # ------------------------------------------------------------
    def _render_login_form(self):
        self._mode = "login"
        self._clear_container()
        self._title(config.APP_NAME, "Sign in to continue")

        self.username_entry = ctk.CTkEntry(
            self.container, placeholder_text="Username", width=320, height=44
        )
        self.username_entry.pack(pady=8, padx=40)
        self.username_entry.bind("<Return>", lambda _e: self.password_entry.focus())

        self.password_entry = ctk.CTkEntry(
            self.container, placeholder_text="Password", show="*", width=320, height=44
        )
        self.password_entry.pack(pady=8, padx=40)
        self.password_entry.bind("<Return>", lambda _e: self._handle_login())

        self.remember_me_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.container, text="Remember me", variable=self.remember_me_var,
            font=ctk.CTkFont(size=12),
        ).pack(pady=(6, 0), padx=40, anchor="w")

        self.error_label = ctk.CTkLabel(self.container, text="", text_color=DANGER, wraplength=280)
        self.error_label.pack(pady=(6, 0))

        self.login_button = ctk.CTkButton(
            self.container, text="Login", width=320, height=44, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=self._handle_login
        )
        self.login_button.pack(pady=(20, 8), padx=40)

        ctk.CTkButton(
            self.container, text="Forgot Password?", width=320, height=34,
            fg_color="transparent", text_color=("#64748B", "#94A3B8"), hover=False,
            command=self._render_forgot_password_request,
        ).pack(pady=(0, 30), padx=40)

        self.username_entry.focus()

    def _handle_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            self.error_label.configure(text="Please enter both username and password.")
            return

        self.login_button.configure(state="disabled", text="Signing in...")
        self.update_idletasks()

        result = authenticate_user(username, password)

        if result["success"]:
            self.on_login_success(result["user"])
        else:
            self.login_button.configure(state="normal", text="Login")
            self.error_label.configure(text=result["message"])
            self.password_entry.delete(0, "end")

    # ------------------------------------------------------------
    # Screen 2: Forgot password - request OTP
    # ------------------------------------------------------------
    def _render_forgot_password_request(self):
        self._mode = "forgot_request"
        self._clear_container()
        self._title("Reset Password", "Enter your username to receive a code")

        self.reset_username_entry = ctk.CTkEntry(
            self.container, placeholder_text="Username", width=320, height=44
        )
        self.reset_username_entry.pack(pady=8, padx=40)

        self.forgot_status_label = ctk.CTkLabel(
            self.container, text="", text_color=DANGER, wraplength=280
        )
        self.forgot_status_label.pack(pady=(6, 0))

        ctk.CTkButton(
            self.container, text="Send Code", width=320, height=44,
            command=self._handle_request_otp,
        ).pack(pady=(20, 8), padx=40)

        ctk.CTkButton(
            self.container, text="Back to Login", width=320, height=34,
            fg_color="transparent", text_color=("#64748B", "#94A3B8"), hover=False,
            command=self._render_login_form,
        ).pack(pady=(0, 30), padx=40)

    def _handle_request_otp(self):
        username = self.reset_username_entry.get().strip()
        if not username:
            self.forgot_status_label.configure(text="Please enter your username.")
            return

        result = request_otp(username)
        self._reset_username = username

        if result["success"]:
            self._render_forgot_password_verify()
        else:
            self.forgot_status_label.configure(text=result["message"])

    # ------------------------------------------------------------
    # Screen 3: Forgot password - verify OTP + set new password
    # ------------------------------------------------------------
    def _render_forgot_password_verify(self):
        self._mode = "forgot_verify"
        self._clear_container()
        self._title("Enter Code", f"We sent a 6-digit code for '{self._reset_username}'")

        self.otp_entry = ctk.CTkEntry(
            self.container, placeholder_text="6-digit code", width=320, height=44
        )
        self.otp_entry.pack(pady=8, padx=40)

        self.new_password_entry = ctk.CTkEntry(
            self.container, placeholder_text="New password", show="*", width=320, height=44
        )
        self.new_password_entry.pack(pady=8, padx=40)

        self.confirm_password_entry = ctk.CTkEntry(
            self.container, placeholder_text="Confirm new password", show="*", width=320, height=44
        )
        self.confirm_password_entry.pack(pady=8, padx=40)

        self.reset_status_label = ctk.CTkLabel(
            self.container, text="", text_color=DANGER, wraplength=280
        )
        self.reset_status_label.pack(pady=(6, 0))

        ctk.CTkButton(
            self.container, text="Reset Password", width=320, height=44,
            command=self._handle_reset_password,
        ).pack(pady=(20, 8), padx=40)

        ctk.CTkButton(
            self.container, text="Resend Code", width=320, height=34,
            fg_color="transparent", text_color=("#64748B", "#94A3B8"), hover=False,
            command=self._handle_request_otp,
        ).pack(pady=(0, 8), padx=40)

        ctk.CTkButton(
            self.container, text="Back to Login", width=320, height=34,
            fg_color="transparent", text_color=("#64748B", "#94A3B8"), hover=False,
            command=self._render_login_form,
        ).pack(pady=(0, 30), padx=40)

    def _handle_reset_password(self):
        otp_code = self.otp_entry.get().strip()
        new_password = self.new_password_entry.get().strip()
        confirm_password = self.confirm_password_entry.get().strip()

        result = reset_password_with_otp(
            self._reset_username, otp_code, new_password, confirm_password
        )

        if result["success"]:
            self._render_login_form()
            self.error_label.configure(text="", text_color="#2ecc71")
        else:
            self.reset_status_label.configure(text=result["message"])