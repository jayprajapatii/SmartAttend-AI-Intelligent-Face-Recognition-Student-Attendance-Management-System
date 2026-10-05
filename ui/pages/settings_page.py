"""
ui/pages/settings_page.py

Admin Panel -> System Settings: recognition/liveness/blur thresholds,
mask policy, session timeout (all stored in the `system_settings`
table), plus "Change Password" and a "Backup & Restore" section.

Gated to super_admin via auth.rbac (matches FEATURE_PERMISSIONS in
auth/rbac.py). The sidebar already hides this page for lower roles;
this page re-checks on load as defense-in-depth in case it's reached
directly.

Note: no SystemSettingsModel exists yet, so this page reads/writes
the `system_settings` table directly via db - swap for a real model
later following the same pattern used elsewhere (e.g. course_model.py).
"""

import logging
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

import config
from database.db_connector import db
from auth.session_manager import session_manager
from auth.rbac import can_access
from auth.password_reset import change_password

logger = logging.getLogger("SmartAttendAI.ui.pages.settings")


class SettingsPage(ctk.CTkScrollableFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        ctk.CTkLabel(
            self, text="Settings", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        if not can_access("settings"):
            ctk.CTkLabel(
                self, text="You do not have permission to view this page.",
                text_color="#e74c3c",
            ).pack(anchor="w", pady=40)
            return

        self._build_ai_thresholds_section()
        self._build_change_password_section()
        self._build_backup_section()

        self._load_system_settings()

    # ------------------------------------------------------------
    # AI / Recognition thresholds (system_settings table)
    # ------------------------------------------------------------
    def _build_ai_thresholds_section(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            section, text="AI Recognition Settings", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 12))

        grid = ctk.CTkFrame(section, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(0, 8))

        self.recognition_threshold_var = ctk.DoubleVar(value=config.RECOGNITION_THRESHOLD)
        self._build_slider_row(
            grid, "Recognition Threshold", self.recognition_threshold_var,
            0.3, 0.9, "Lower = more lenient matching, higher = stricter (fewer false positives).",
        )

        self.liveness_threshold_var = ctk.DoubleVar(value=config.LIVENESS_THRESHOLD)
        self._build_slider_row(
            grid, "Liveness Threshold", self.liveness_threshold_var,
            0.1, 0.9, "Minimum liveness confidence required before marking attendance.",
        )

        self.blur_threshold_var = ctk.DoubleVar(value=config.BLUR_THRESHOLD)
        self._build_slider_row(
            grid, "Blur Threshold", self.blur_threshold_var,
            20.0, 300.0, "Laplacian variance floor; frames below this are rejected as blurry.",
        )

        ctk.CTkLabel(grid, text="Mask Policy", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", pady=(12, 4)
        )
        self.mask_policy_var = ctk.StringVar(value="Warn")
        ctk.CTkSegmentedButton(
            grid, values=["Allow", "Deny", "Warn"], variable=self.mask_policy_var
        ).pack(anchor="w")

        ctk.CTkLabel(grid, text="Session Timeout (minutes)", font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", pady=(16, 4)
        )
        self.session_timeout_entry = ctk.CTkEntry(grid, width=100)
        self.session_timeout_entry.insert(0, str(config.SESSION_TIMEOUT_MINUTES))
        self.session_timeout_entry.pack(anchor="w")

        ctk.CTkButton(
            section, text="Save Settings", width=200, command=self._handle_save_settings
        ).pack(anchor="w", padx=20, pady=(20, 20))

    def _build_slider_row(self, parent, label, var, from_, to, hint):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))

        header = ctk.CTkFrame(row, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=label, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        value_label = ctk.CTkLabel(header, text=f"{var.get():.2f}", font=ctk.CTkFont(size=12))
        value_label.pack(side="right")

        def _on_change(value):
            value_label.configure(text=f"{float(value):.2f}")

        ctk.CTkSlider(row, from_=from_, to=to, variable=var, command=_on_change).pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(row, text=hint, font=ctk.CTkFont(size=10), text_color=("#64748B", "#94A3B8")).pack(anchor="w")

    def _load_system_settings(self):
        try:
            row = db.fetch_one("SELECT * FROM system_settings ORDER BY setting_id DESC LIMIT 1")
        except Exception as exc:
            logger.error("Failed to load system settings: %s", exc)
            row = None

        if not row:
            return

        self.recognition_threshold_var.set(row.get("recognition_threshold", config.RECOGNITION_THRESHOLD))
        self.liveness_threshold_var.set(row.get("liveness_threshold", config.LIVENESS_THRESHOLD))
        self.blur_threshold_var.set(row.get("blur_threshold", config.BLUR_THRESHOLD))
        self.mask_policy_var.set(row.get("mask_policy", "Warn"))
        self.session_timeout_entry.delete(0, "end")
        self.session_timeout_entry.insert(0, str(row.get("session_timeout_minutes", config.SESSION_TIMEOUT_MINUTES)))

    def _handle_save_settings(self):
        timeout_raw = self.session_timeout_entry.get().strip()
        if not timeout_raw.isdigit():
            messagebox.showwarning("Invalid Value", "Session timeout must be a whole number of minutes.")
            return

        admin_id = session_manager.get_current_admin_id()

        try:
            existing = db.fetch_one("SELECT setting_id FROM system_settings ORDER BY setting_id DESC LIMIT 1")
            if existing:
                db.execute(
                    """
                    UPDATE system_settings SET
                        recognition_threshold = %s, liveness_threshold = %s, blur_threshold = %s,
                        mask_policy = %s, session_timeout_minutes = %s, updated_by = %s
                    WHERE setting_id = %s
                    """,
                    (
                        round(self.recognition_threshold_var.get(), 2),
                        round(self.liveness_threshold_var.get(), 2),
                        round(self.blur_threshold_var.get(), 1),
                        self.mask_policy_var.get(),
                        int(timeout_raw),
                        admin_id,
                        existing["setting_id"],
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO system_settings (
                        recognition_threshold, liveness_threshold, blur_threshold,
                        mask_policy, session_timeout_minutes, updated_by
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        round(self.recognition_threshold_var.get(), 2),
                        round(self.liveness_threshold_var.get(), 2),
                        round(self.blur_threshold_var.get(), 1),
                        self.mask_policy_var.get(),
                        int(timeout_raw),
                        admin_id,
                    ),
                )
        except Exception as exc:
            logger.error("Failed to save system settings: %s", exc)
            messagebox.showerror("Error", f"Could not save settings:\n{exc}")
            return

        messagebox.showinfo(
            "Settings Saved",
            "System settings updated. Some changes may require restarting the recognition session.",
        )
        logger.info("System settings updated by admin_id=%s", admin_id)

    # ------------------------------------------------------------
    # Change Password
    # ------------------------------------------------------------
    def _build_change_password_section(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            section, text="Change Password", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 12))

        form = ctk.CTkFrame(section, fg_color="transparent")
        form.pack(fill="x", padx=20, pady=(0, 8))

        self.current_password_entry = ctk.CTkEntry(form, placeholder_text="Current password", show="*", width=280)
        self.current_password_entry.pack(anchor="w", pady=4)

        self.new_password_entry = ctk.CTkEntry(form, placeholder_text="New password", show="*", width=280)
        self.new_password_entry.pack(anchor="w", pady=4)

        self.confirm_password_entry = ctk.CTkEntry(form, placeholder_text="Confirm new password", show="*", width=280)
        self.confirm_password_entry.pack(anchor="w", pady=4)

        self.password_status_label = ctk.CTkLabel(form, text="", font=ctk.CTkFont(size=11))
        self.password_status_label.pack(anchor="w", pady=(4, 0))

        ctk.CTkButton(
            section, text="Update Password", width=200, command=self._handle_change_password
        ).pack(anchor="w", padx=20, pady=(12, 20))

    def _handle_change_password(self):
        admin_id = session_manager.get_current_admin_id()
        if not admin_id:
            messagebox.showerror("Session Expired", "Please log in again.")
            return

        result = change_password(
            admin_id,
            self.current_password_entry.get().strip(),
            self.new_password_entry.get().strip(),
            self.confirm_password_entry.get().strip(),
        )

        color = "#2ecc71" if result["success"] else "#e74c3c"
        self.password_status_label.configure(text=result["message"], text_color=color)

        if result["success"]:
            self.current_password_entry.delete(0, "end")
            self.new_password_entry.delete(0, "end")
            self.confirm_password_entry.delete(0, "end")

    # ------------------------------------------------------------
    # Backup & Restore
    # ------------------------------------------------------------
    def _build_backup_section(self):
        section = ctk.CTkFrame(self, corner_radius=14)
        section.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            section, text="Backup & Restore", font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 12))

        ctk.CTkLabel(
            section,
            text="Create a manual backup of the database, or view the automatic backup history.",
            font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"),
        ).pack(anchor="w", padx=20)

        button_row = ctk.CTkFrame(section, fg_color="transparent")
        button_row.pack(anchor="w", padx=20, pady=(12, 20))

        ctk.CTkButton(button_row, text="Create Backup Now", width=200, command=self._handle_backup_now).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            button_row, text="View Backup History", width=200, fg_color="transparent", border_width=1,
            command=self._handle_view_backups,
        ).pack(side="left")

    def _handle_backup_now(self):
        try:
            from utils.backup_restore import create_backup
            filepath = create_backup()
            messagebox.showinfo("Backup Complete", f"Backup saved to:\n{filepath}")
        except ImportError:
            logger.warning("utils.backup_restore not implemented yet.")
            messagebox.showinfo(
                "Not Implemented Yet",
                "The backup utility (utils/backup_restore.py) hasn't been built yet.",
            )
        except Exception as exc:
            logger.error("Backup failed: %s", exc)
            messagebox.showerror("Backup Failed", str(exc))

    def _handle_view_backups(self):
        try:
            rows = db.fetch_all("SELECT * FROM backups ORDER BY created_at DESC LIMIT 20")
        except Exception as exc:
            logger.error("Failed to load backup history: %s", exc)
            rows = []

        if not rows:
            messagebox.showinfo("Backup History", "No backups found yet.")
            return

        lines = [
            f"{r['created_at']} - {r['backup_type']} - {r.get('backup_size_mb', 0):.1f} MB"
            for r in rows
        ]
        messagebox.showinfo("Backup History", "\n".join(lines))