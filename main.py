"""
main.py
Entry point for SmartAttend AI.

Flow:
    Splash Screen -> Login Page -> Main App Shell (Sidebar + Dashboard/Pages)

Run with:
    python main.py
"""

import sys
import logging
from turtle import width
from turtle import width
import customtkinter as ctk
from utils.asset_manager import assets
from auth.login import authenticate_user
from auth.rbac import require_role
from auth.rbac import can_access
from ui.components.toast_notification import toast_manager
from ui.components.charts import line_chart, bar_chart, heatmap_chart

import config

# ------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOGS_DIR / "app.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("SmartAttendAI")

# ------------------------------------------------------------
# CustomTkinter global appearance
# ------------------------------------------------------------
ctk.set_appearance_mode(config.UI_APPEARANCE_MODE)
ctk.set_default_color_theme(config.UI_COLOR_THEME)


# ------------------------------------------------------------
# Placeholder page loader
# Real pages live in ui/pages/*.py. This lets main.py run even
# before every page module has been built out yet.
# ------------------------------------------------------------
def _load_page_class(module_path: str, class_name: str, fallback_title: str):
    """
    Try to import a real page class from ui/pages.
    Falls back to a simple placeholder frame if not implemented yet,
    so the app shell always runs end-to-end.
    """
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


class SplashScreen(ctk.CTkToplevel):
    """Startup splash shown briefly while the app initializes."""

    def __init__(self, master, on_finish):
        super().__init__(master)
        self.title("")
        self.geometry("420x260")
        self.overrideredirect(True)
        self.update_idletasks()

        width = self.winfo_width()
        height = self.winfo_height()

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        self.geometry(f"{width}x{height}+{x}+{y}")
        self._center()

        frame = ctk.CTkFrame(self, corner_radius=16)
        frame.pack(expand=True, fill="both", padx=2, pady=2)

        ctk.CTkLabel(
            frame,
            text=config.APP_NAME,
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack(pady=(50, 10))

        ctk.CTkLabel(
            frame,
            text="Smart Face Recognition Attendance System",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        ).pack(pady=(0, 25))

        self.progress = ctk.CTkProgressBar(frame, width=260)
        self.progress.pack(pady=10)
        self.progress.set(0)

        self.on_finish = on_finish
        self._animate(0)

    def _center(self):
        self.update_idletasks()
        w, h = 420, 260
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _animate(self, step):
        if step <= 100:
            self.progress.set(step / 100)
            self.after(15, self._animate, step + 4)
        else:
            self.destroy()
            self.on_finish()


class LoginPage(ctk.CTkFrame):
    """Admin/Faculty login screen. Wire up to auth/login.py for real auth."""

    def __init__(self, master, on_login_success):
        super().__init__(master)
        self.on_login_success = on_login_success

        container = ctk.CTkFrame(self, corner_radius=16, width=380, height=420)
        container.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            container, text=config.APP_NAME,
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(40, 5), padx=40)

        ctk.CTkLabel(
            container, text="Sign in to continue",
            text_color="gray", font=ctk.CTkFont(size=13)
        ).pack(pady=(0, 25))

        self.username_entry = ctk.CTkEntry(
            container, placeholder_text="Username", width=280, height=40
        )
        self.username_entry.pack(pady=8, padx=40)

        self.password_entry = ctk.CTkEntry(
            container, placeholder_text="Password", show="*", width=280, height=40
        )
        self.password_entry.pack(pady=8, padx=40)

        self.error_label = ctk.CTkLabel(container, text="", text_color="#e74c3c")
        self.error_label.pack(pady=(4, 0))

        ctk.CTkButton(
            container, text="Login", width=280, height=40,
            command=self._handle_login
        ).pack(pady=(20, 8), padx=40)

        ctk.CTkButton(
            container, text="Forgot Password?", width=280, height=30,
            fg_color="transparent", text_color="gray", hover=False,
        ).pack(pady=(0, 30), padx=40)

    def _handle_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            self.error_label.configure(text="Please enter both username and password.")
            return

        # TODO: replace with real check against auth/login.py + admin_users table
        authenticated = self._authenticate(username, password)

        if authenticated:
            self.on_login_success(username)
        else:
            self.error_label.configure(text="Invalid username or password.")

    def _authenticate(self, username, password):
        try:
            from auth.login import authenticate_user
            return authenticate_user(username, password)
        except ImportError:
            logger.warning("auth.login module not found - using dev bypass.")
            return True  # DEV ONLY: remove once auth module exists


class Sidebar(ctk.CTkFrame):
    """Left navigation sidebar."""

    NAV_ITEMS = [
        ("Dashboard", "dashboard"),
        ("Students", "students"),
        ("Faculty", "faculty"),
        ("Dataset Generator", "dataset"),
        ("Face Recognition", "recognition"),
        ("Attendance", "attendance"),
        ("Reports", "reports"),
        ("Analytics", "analytics"),
        ("Settings", "settings"),
        ("Help", "help"),
    ]

    def __init__(self, master, on_nav):
        super().__init__(master, width=220, corner_radius=0)
        self.grid_propagate(False)
        self.on_nav = on_nav

        ctk.CTkLabel(
            self, text=config.APP_NAME,
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(24, 20), padx=20)

        for label, key in self.NAV_ITEMS:
            ctk.CTkButton(
                self, text=label, anchor="w", fg_color="transparent",
                command=lambda k=key: self.on_nav(k)
            ).pack(fill="x", padx=12, pady=3)

        ctk.CTkButton(
            self, text="Light / Dark Mode", fg_color="transparent",
            command=self._toggle_theme
        ).pack(side="bottom", fill="x", padx=12, pady=(3, 20))

    @staticmethod
    def _toggle_theme():
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Dark" if current == "Light" else "Light")


class MainAppShell(ctk.CTkFrame):
    """Sidebar + page container shown after successful login."""

    PAGE_MAP = {
        "dashboard": ("ui.pages.dashboard_page", "DashboardPage", "Dashboard"),
        "students": ("ui.pages.student_registration_page", "StudentRegistrationPage", "Student Management"),
        "faculty": ("ui.pages.faculty_management_page", "FacultyManagementPage", "Faculty Management"),
        "dataset": ("ui.pages.dataset_generator_page", "DatasetGeneratorPage", "Dataset Generator"),
        "recognition": ("ui.pages.face_recognition_page", "FaceRecognitionPage", "Face Recognition"),
        "attendance": ("ui.pages.attendance_dashboard_page", "AttendanceDashboardPage", "Attendance"),
        "reports": ("ui.pages.reports_page", "ReportsPage", "Reports"),
        "analytics": ("ui.pages.analytics_page", "AnalyticsPage", "Analytics"),
        "settings": ("ui.pages.settings_page", "SettingsPage", "Settings"),
        "help": ("ui.pages.help_page", "HelpPage", "Help"),
    }

    def __init__(self, master, username):
        super().__init__(master)
        self.username = username
        self.pack(fill="both", expand=True)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(self, on_nav=self.show_page)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        self.page_container = ctk.CTkFrame(self, fg_color="transparent")
        self.page_container.grid(row=0, column=1, sticky="nsew")

        self._current_page = None
        self.show_page("dashboard")

    def show_page(self, key: str):
        module_path, class_name, title = self.PAGE_MAP[key]
        page_class = _load_page_class(module_path, class_name, title)

        if self._current_page is not None:
            self._current_page.destroy()

        self._current_page = page_class(self.page_container)
        self._current_page.pack(fill="both", expand=True, padx=20, pady=20)


class SmartAttendApp(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()
        self.title(config.APP_NAME)
        self.geometry(f"{config.WINDOW_MIN_WIDTH}x{config.WINDOW_MIN_HEIGHT}")
        self.minsize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)
        self.withdraw()  # hide main window until splash finishes

        SplashScreen(self, on_finish=self._show_login)

    def _show_login(self):
        self.deiconify()
        self._clear()
        LoginPage(self, on_login_success=self._show_dashboard).pack(fill="both", expand=True)

    def _show_dashboard(self, username: str):
        logger.info("User '%s' logged in.", username)
        self._clear()
        MainAppShell(self, username=username)

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()


def main():
    logger.info("Starting %s v%s (%s)", config.APP_NAME, config.APP_VERSION, config.APP_ENV)
    app = SmartAttendApp()
    app.mainloop()
    
from ui.app_window import run

if __name__ == "__main__":
    run()