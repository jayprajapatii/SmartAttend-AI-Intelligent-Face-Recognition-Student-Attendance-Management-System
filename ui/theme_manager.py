"""
ui/theme_manager.py

Centralized light/dark mode + color theme control.
Persists the user's preference to disk so it survives app restarts,
and lets any widget register a callback to react when the theme changes
(e.g. to swap an icon's light/dark variant).
"""

import json
import logging
import customtkinter as ctk

import config

logger = logging.getLogger("SmartAttendAI.ui.theme")

_PREF_FILE = config.BASE_DIR / "data" / "ui_theme.json"
VALID_MODES = ("Light", "Dark", "System")


class ThemeManager:

    def __init__(self):
        self._mode = config.UI_APPEARANCE_MODE
        self._color_theme = config.UI_COLOR_THEME
        self._listeners = []
        self._load_preference()
        self._apply()

    # ------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------
    def _load_preference(self):
        if _PREF_FILE.exists():
            try:
                data = json.loads(_PREF_FILE.read_text())
                self._mode = data.get("mode", self._mode)
                self._color_theme = data.get("color_theme", self._color_theme)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read theme preference: %s", exc)

    def _save_preference(self):
        try:
            _PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PREF_FILE.write_text(json.dumps({
                "mode": self._mode,
                "color_theme": self._color_theme,
            }))
        except OSError as exc:
            logger.warning("Could not save theme preference: %s", exc)

    # ------------------------------------------------------------
    # Apply to customtkinter
    # ------------------------------------------------------------
    def _apply(self):
        ctk.set_appearance_mode(self._mode)
        ctk.set_default_color_theme(self._color_theme)
        logger.info("Theme applied: mode=%s color_theme=%s", self._mode, self._color_theme)

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------
    def get_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str):
        if mode not in VALID_MODES:
            logger.warning("Ignoring invalid theme mode: %s", mode)
            return
        self._mode = mode
        self._apply()
        self._save_preference()
        self._notify_listeners()

    def toggle(self):
        """Flip between Light and Dark (skips System for a simple one-click toggle)."""
        effective = ctk.get_appearance_mode()  # resolves 'System' to 'Light'/'Dark'
        new_mode = "Dark" if effective == "Light" else "Light"
        self.set_mode(new_mode)

    def is_dark(self) -> bool:
        return ctk.get_appearance_mode() == "Dark"

    def set_color_theme(self, color_theme: str):
        """
        NOTE: customtkinter color themes ('blue', 'green', 'dark-blue', or a
        path to a custom .json theme) require an app restart to fully apply.
        """
        self._color_theme = color_theme
        self._save_preference()
        logger.info("Color theme set to '%s' - restart the app to apply.", color_theme)

    # ------------------------------------------------------------
    # Change listeners (e.g. swap icon variants, redraw charts)
    # ------------------------------------------------------------
    def on_change(self, callback):
        """Register a no-arg callback fired whenever the mode changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        for callback in list(self._listeners):
            try:
                callback()
            except Exception as exc:
                logger.error("Theme change listener failed: %s", exc)


# Singleton instance - import this everywhere instead of instantiating directly
theme_manager = ThemeManager()