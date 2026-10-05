"""
ui/splash_screen.py

Startup splash screen shown briefly while the app initializes
(loads config, warms up the DB pool, etc.) before handing off to login.
"""

import logging
import customtkinter as ctk

import config
from ui.design_system import SURFACE, BORDER, TEXT, MUTED, PRIMARY

logger = logging.getLogger("SmartAttendAI.ui.splash")


class SplashScreen(ctk.CTkToplevel):
    """Borderless splash window with a progress bar, auto-closes into on_finish()."""

    WIDTH = 420
    HEIGHT = 260

    def __init__(self, master, on_finish, tasks=None):
        """
        master: the (hidden) root CTk window
        on_finish: callback invoked once the splash finishes
        tasks: optional list of zero-arg callables to run during startup
               (e.g. warm up DB connection, preload face embeddings index)
        """
        super().__init__(master)
        self.on_finish = on_finish
        self.tasks = tasks or []

        self.title("")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self._center()

        frame = ctk.CTkFrame(self, corner_radius=18, fg_color=SURFACE, border_width=1, border_color=BORDER)
        frame.pack(expand=True, fill="both", padx=2, pady=2)

        ctk.CTkLabel(
            frame,
            text=config.APP_NAME,
            font=ctk.CTkFont(size=26, weight="bold"), text_color=TEXT,
        ).pack(pady=(50, 10))

        ctk.CTkLabel(
            frame,
            text="Smart Face Recognition Attendance System",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(pady=(0, 25))

        self.status_label = ctk.CTkLabel(
            frame, text="Starting up...", font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.status_label.pack(pady=(0, 8))

        self.progress = ctk.CTkProgressBar(frame, width=260)
        self.progress.pack(pady=4)
        self.progress.set(0)

        ctk.CTkLabel(
            frame, text=f"v{config.APP_VERSION}", font=ctk.CTkFont(size=10), text_color="gray"
        ).pack(side="bottom", pady=10)

        self._run_startup_sequence()

    def _center(self):
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w // 2) - (self.WIDTH // 2)
        y = (screen_h // 2) - (self.HEIGHT // 2)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _run_startup_sequence(self):
        """Runs registered startup tasks, then animates to 100% and finishes."""
        total_steps = max(len(self.tasks), 1)
        self._execute_task(0, total_steps)

    def _execute_task(self, index: int, total_steps: int):
        if index >= len(self.tasks):
            self._animate_to_complete()
            return

        task = self.tasks[index]
        label = getattr(task, "label", f"Loading ({index + 1}/{total_steps})...")
        self.status_label.configure(text=label)
        self.progress.set(index / total_steps)

        try:
            task()
        except Exception as exc:
            logger.error("Startup task failed: %s", exc)
            self.status_label.configure(text="Startup warning - continuing...")

        self.after(150, self._execute_task, index + 1, total_steps)

    def _animate_to_complete(self):
        self.status_label.configure(text="Ready.")
        self._animate_progress(int(self.progress.get() * 100))

    def _animate_progress(self, step: int):
        if step <= 100:
            self.progress.set(step / 100)
            self.after(12, self._animate_progress, step + 5)
        else:
            self.destroy()
            self.on_finish()