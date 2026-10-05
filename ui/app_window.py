"""
ui/app_window.py

Main window / navigation shell.

Flow:
    SplashScreen -> LoginPage -> MainAppShell (Sidebar + page container)

This is what main.py imports and runs. Login is wired to the real
auth.login.authenticate_user() + auth.session_manager, and page
navigation is filtered by role via ui/sidebar.py's RBAC check.
"""

import logging
import customtkinter as ctk

import config
from ui.design_system import BG, SURFACE
from ui.theme_manager import theme_manager  # noqa: F401 (applies theme on import)
from ui.splash_screen import SplashScreen
from ui.sidebar import Sidebar
from ui.pages.login_page import LoginPage
from auth.login import logout_user
from auth.session_manager import session_manager

logger = logging.getLogger("SmartAttendAI.ui.app_window")


# ------------------------------------------------------------
# Placeholder page loader
# Real pages live in ui/pages/*.py. This lets the shell run even
# before every page module has been built out yet.
# ------------------------------------------------------------
def _load_page_class(module_path: str, class_name: str, fallback_title: str):
    try:
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Page '%s' not found (%s) - using placeholder.", class_name, exc)

        class _PlaceholderPage(ctk.CTkFrame):
            def __init__(self, master, **kwargs):
                super().__init__(master, **kwargs)
                ctk.CTkLabel(
                    self,
                    text=f"{fallback_title}\n\n(Page not implemented yet)",
                    font=ctk.CTkFont(size=20, weight="bold"),
                    justify="center",
                ).pack(expand=True)

        return _PlaceholderPage


class MainAppShell(ctk.CTkFrame):
    """Sidebar + page container shown after successful login."""

    PAGE_MAP = {
        "dashboard": (
            "ui.pages.dashboard_page",
            "DashboardPage",
            "Dashboard",
        ),
        "students": (
            "ui.pages.student_registration_page",
            "StudentRegistrationPage",
            "Student Management",
        ),
        "faculty": (
            "ui.pages.faculty_management_page",
            "FacultyManagementPage",
            "Faculty Management",
        ),
        "dataset": (
            "ui.pages.dataset_generator_page",
            "DatasetGeneratorPage",
            "Dataset Generator",
        ),
        "recognition": (
            "ui.pages.face_recognition_page",
            "FaceRecognitionPage",
            "Face Recognition",
        ),
        "attendance": (
            "ui.pages.attendance_dashboard_page",
            "AttendanceDashboardPage",
            "Attendance",
        ),
        "reports": (
            "ui.pages.reports_page",
            "ReportsPage",
            "Reports",
        ),
        "analytics": (
            "ui.pages.analytics_page",
            "AnalyticsPage",
            "Analytics",
        ),
        "settings": (
            "ui.pages.settings_page",
            "SettingsPage",
            "Settings",
        ),
        "help": (
            "ui.pages.help_page",
            "HelpPage",
            "Help",
        ),
    }

    def __init__(self, master, on_logout):
        super().__init__(
            master,
            fg_color=BG,
            corner_radius=0,
        )

        self.on_logout_callback = on_logout

        # Main shell fills the entire application window
        self.pack(
            fill="both",
            expand=True,
            padx=0,
            pady=0,
        )

        # Sidebar column
        self.grid_columnconfigure(
            0,
            weight=0,
            minsize=190,
        )

        # Main page column
        self.grid_columnconfigure(
            1,
            weight=1,
        )

        # Main row
        self.grid_rowconfigure(
            0,
            weight=1,
        )

        default_page = "dashboard"

        # Sidebar
        self.sidebar = Sidebar(
            self,
            on_nav=self.show_page,
            on_logout=self._handle_logout,
            active_key=default_page,
        )

        self.sidebar.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=0,
            pady=0,
        )

        # Page container
        self.page_container = ctk.CTkFrame(
            self,
            fg_color=BG,
            corner_radius=0,
        )

        self.page_container.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=0,
            pady=0,
        )

        self.page_container.grid_rowconfigure(
            0,
            weight=1,
        )

        self.page_container.grid_columnconfigure(
            0,
            weight=1,
        )

        self._current_page = None

        self.show_page(default_page)

    def show_page(self, key: str):
        if key not in self.PAGE_MAP:
            logger.warning(
                "Unknown page key requested: %s",
                key,
            )
            return

        session_manager.touch()

        module_path, class_name, title = self.PAGE_MAP[key]

        page_class = _load_page_class(
            module_path,
            class_name,
            title,
        )

        # Remove previous page
        if self._current_page is not None:
            try:
                self._current_page.destroy()
            except Exception:
                pass

        # Create new page
        self._current_page = page_class(
            self.page_container
        )

        # IMPORTANT:
        # Page gets the complete available area.
        # No vertical padding that can create visual gaps.
        self._current_page.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=0,
            pady=0,
        )

        self.page_container.grid_rowconfigure(
            0,
            weight=1,
        )

        self.page_container.grid_columnconfigure(
            0,
            weight=1,
        )

    def _handle_logout(self):
        logout_user()
        self.on_logout_callback()


class SmartAttendApp(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__(fg_color=BG)
        self.title(config.APP_NAME)
        # Initial application size
        window_width = max(config.WINDOW_MIN_WIDTH, 1400)
        window_height = max(config.WINDOW_MIN_HEIGHT, 800)

        self.geometry(
            f"{window_width}x{window_height}"
                )

        self.minsize(
            config.WINDOW_MIN_WIDTH,
            config.WINDOW_MIN_HEIGHT,
                )
        self.withdraw()  # hide main window until splash finishes

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        from ui.components.toast_notification import toast_manager
        toast_manager.attach(self)

        startup_tasks = [self._warm_up_database]
        SplashScreen(self, on_finish=self._show_login, tasks=startup_tasks)

    @staticmethod
    def _warm_up_database():
        try:
            from database.db_connector import db
            db.is_connected()
        except Exception as exc:
            logger.warning("Database warm-up failed (will retry on demand): %s", exc)

    def _show_login(self):
        self.deiconify()
        self._clear()
        LoginPage(self, on_login_success=self._show_dashboard).pack(fill="both", expand=True)

    def _show_dashboard(self, user: dict):
        logger.info("User '%s' logged in (role=%s).", user.get("username"), user.get("role"))
        self._clear()
        MainAppShell(self, on_logout=self._show_login)
        self._start_session_watchdog()

    def _start_session_watchdog(self):
        """Polls every 30s for idle-timeout expiry and bounces back to login."""
        session_manager.on_timeout(self._show_login)

        def _tick():
            if session_manager.is_logged_in() or not isinstance(self.winfo_children()[0], MainAppShell):
                session_manager.check_and_handle_timeout()
                self.after(30_000, _tick)

        self.after(30_000, _tick)

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def _on_close(self):
        logger.info("Application closing.")
        self.destroy()


def run():
    app = SmartAttendApp()
    app.mainloop()