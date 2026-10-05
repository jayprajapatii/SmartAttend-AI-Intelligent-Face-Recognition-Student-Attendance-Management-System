"""
auth/session_manager.py

Tracks the currently logged-in user for this desktop app instance,
including idle-timeout enforcement ("Session Management" feature).

Since this is a single-user desktop app (one Tkinter process per
logged-in operator), a simple in-memory singleton is sufficient -
no server-side session store needed.
"""

import logging
import threading
from datetime import datetime, timedelta

import config

logger = logging.getLogger("SmartAttendAI.auth.session")


class SessionManager:

    def __init__(self, timeout_minutes: int = None):
        self.timeout_minutes = timeout_minutes or config.SESSION_TIMEOUT_MINUTES
        self._current_user = None
        self._login_time = None
        self._last_activity = None
        self._lock = threading.Lock()
        self._on_timeout_callback = None

    # ------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------
    def start_session(self, user: dict):
        with self._lock:
            self._current_user = user
            self._login_time = datetime.now()
            self._last_activity = datetime.now()
        logger.info("Session started for '%s' (role=%s)", user.get("username"), user.get("role"))

    def end_session(self):
        with self._lock:
            username = self._current_user.get("username") if self._current_user else None
            self._current_user = None
            self._login_time = None
            self._last_activity = None
        if username:
            logger.info("Session ended for '%s'.", username)

    def touch(self):
        """Call this on any user interaction to reset the idle timer."""
        with self._lock:
            if self._current_user:
                self._last_activity = datetime.now()

    # ------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------
    def is_logged_in(self) -> bool:
        return self._current_user is not None and not self.is_expired()

    def is_expired(self) -> bool:
        if not self._last_activity:
            return False
        idle_for = datetime.now() - self._last_activity
        return idle_for > timedelta(minutes=self.timeout_minutes)

    def get_current_user(self) -> dict | None:
        if self.is_expired():
            logger.info("Session expired due to inactivity.")
            self.end_session()
            return None
        return self._current_user

    def get_current_admin_id(self) -> int | None:
        user = self.get_current_user()
        return user["admin_id"] if user else None

    def get_current_role(self) -> str | None:
        user = self.get_current_user()
        return user["role"] if user else None

    def time_until_expiry(self) -> timedelta | None:
        if not self._last_activity:
            return None
        elapsed = datetime.now() - self._last_activity
        remaining = timedelta(minutes=self.timeout_minutes) - elapsed
        return remaining if remaining.total_seconds() > 0 else timedelta(0)

    # ------------------------------------------------------------
    # Timeout callback (UI hooks in to auto-redirect to login page)
    # ------------------------------------------------------------
    def on_timeout(self, callback):
        """Register a function to call when the session expires."""
        self._on_timeout_callback = callback

    def check_and_handle_timeout(self):
        """Call periodically (e.g. via a Tkinter `.after()` loop) from the UI."""
        if self._current_user and self.is_expired():
            self.end_session()
            if self._on_timeout_callback:
                self._on_timeout_callback()


# Singleton instance - import this everywhere instead of instantiating directly
session_manager = SessionManager()