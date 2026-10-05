"""
ui/sidebar.py

Left navigation sidebar. Nav items are filtered by the logged-in
user's role via auth.rbac.can_access(), so a 'faculty' user never
even sees buttons for pages like Settings or Analytics.
"""

import logging
import customtkinter as ctk

from auth.rbac import can_access
from auth.session_manager import session_manager
from ui.theme_manager import theme_manager
from ui.design_system import BG, SURFACE, SURFACE_2, BORDER, TEXT, MUTED, PRIMARY, PRIMARY_HOVER, DANGER, DANGER_HOVER

logger = logging.getLogger("SmartAttendAI.ui.sidebar")


class Sidebar(ctk.CTkFrame):
    """
    NAV_ITEMS: (display label, page key, rbac feature key)
    The rbac feature key must match an entry in auth.rbac.FEATURE_PERMISSIONS.
    """

    NAV_ITEMS = [
        ("Dashboard", "dashboard", "dashboard"),
        ("Students", "students", "students"),
        ("Faculty", "faculty", "faculty"),
        ("Dataset Generator", "dataset", "dataset_generator"),
        ("Face Recognition", "recognition", "face_recognition"),
        ("Attendance", "attendance", "attendance"),
        ("Reports", "reports", "reports"),
        ("Analytics", "analytics", "analytics"),
        ("Settings", "settings", "settings"),
        ("Help", "help", "help"),
    ]

    WIDTH = 248

    def __init__(self, master, on_nav, on_logout, active_key: str = "dashboard"):
        super().__init__(master, width=self.WIDTH, corner_radius=0, fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.grid_propagate(False)
        self.on_nav = on_nav
        self.on_logout = on_logout
        self.active_key = active_key
        self._nav_buttons = {}

        self._build_header()
        self._build_nav_items()
        self._build_footer()

    # ------------------------------------------------------------
    # Header: app name + logged-in user
    # ------------------------------------------------------------
    def _build_header(self):
        ctk.CTkLabel(
            self, text="SmartAttend AI",
            font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT,
        ).pack(pady=(24, 4), padx=20, anchor="w")

        user = session_manager.get_current_user()
        display_name = user.get("username", "Guest") if user else "Guest"
        role = user.get("role", "") if user else ""

        ctk.CTkLabel(
            self, text=f"{display_name}  ·  {role}",
            font=ctk.CTkFont(size=11), text_color=PRIMARY,
        ).pack(pady=(0, 20), padx=20, anchor="w")

    # ------------------------------------------------------------
    # Nav items (RBAC-filtered)
    # ------------------------------------------------------------
    def _build_nav_items(self):
        nav_container = ctk.CTkFrame(self, fg_color="transparent")
        nav_container.pack(fill="both", expand=True)

        for label, key, feature_key in self.NAV_ITEMS:
            if not can_access(feature_key):
                continue

            is_active = key == self.active_key
            btn = ctk.CTkButton(
                nav_container,
                text=label,
                anchor="w",
                fg_color=("#DBEAFE", "#1E3A5F") if is_active else "transparent",
                hover_color=("#EFF6FF", "#1E293B"),
                text_color=TEXT,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=42,
                corner_radius=10,
                command=lambda k=key: self._handle_nav(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_buttons[key] = btn

    def _handle_nav(self, key: str):
        self.set_active(key)
        self.on_nav(key)

    def set_active(self, key: str):
        """Update button highlighting to reflect the current page."""
        self.active_key = key
        for btn_key, btn in self._nav_buttons.items():
            is_active = btn_key == key
            btn.configure(fg_color=("#DBEAFE", "#1E3A5F") if is_active else "transparent")

    # ------------------------------------------------------------
    # Footer: theme toggle + logout
    # ------------------------------------------------------------
    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=12, pady=20)

        ctk.CTkButton(
            footer, text="☾  Toggle Theme", fg_color=SURFACE_2, hover_color=("#E2E8F0", "#334155"),
            border_width=1, border_color=BORDER, text_color=TEXT, command=theme_manager.toggle,
        ).pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            footer, text="⇥  Logout", fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self.on_logout,
        ).pack(fill="x")