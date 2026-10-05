"""
utils/asset_manager.py

Central helper for loading and caching everything in assets/:
    assets/icons/    -> small UI icons (CTkImage, for buttons/sidebar/toasts)
    assets/images/   -> larger images (student photos placeholder, logos, backgrounds)
    assets/fonts/    -> custom .ttf/.otf fonts registered with Tkinter
    assets/sounds/   -> .mp3/.wav for voice confirmation & notification chimes

Usage:
    from utils.asset_manager import assets

    icon = assets.get_icon("dashboard.png", size=(20, 20))
    photo = assets.get_image("logo.png", size=(120, 120))
    assets.play_sound("attendance_success.wav")
"""

import logging
from pathlib import Path
from functools import lru_cache

from PIL import Image
import customtkinter as ctk

import config

logger = logging.getLogger("SmartAttendAI.assets")


class AssetManager:
    """Loads assets from disk once and caches them for reuse across the UI."""

    def __init__(self):
        self.icons_dir = config.ASSETS_DIR / "icons"
        self.images_dir = config.ASSETS_DIR / "images"
        self.fonts_dir = config.ASSETS_DIR / "fonts"
        self.sounds_dir = config.ASSETS_DIR / "sounds"

        self._image_cache = {}
        self._sound_engine = None  # lazy-loaded pyttsx3 / playsound backend

    # ------------------------------------------------------------
    # Icons & Images (CTkImage-based, works in both light/dark mode)
    # ------------------------------------------------------------
    def get_icon(self, filename: str, size: tuple = (20, 20)):
        return self._load_ctk_image(self.icons_dir, filename, size)

    def get_image(self, filename: str, size: tuple = (200, 200)):
        return self._load_ctk_image(self.images_dir, filename, size)

    def _load_ctk_image(self, directory: Path, filename: str, size: tuple):
        cache_key = (str(directory / filename), size)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        path = directory / filename
        if not path.exists():
            logger.warning("Asset not found: %s - using blank placeholder.", path)
            placeholder = Image.new("RGBA", size, (128, 128, 128, 60))
            ctk_img = ctk.CTkImage(light_image=placeholder, dark_image=placeholder, size=size)
            self._image_cache[cache_key] = ctk_img
            return ctk_img

        try:
            pil_img = Image.open(path).convert("RGBA")
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
            self._image_cache[cache_key] = ctk_img
            return ctk_img
        except Exception as exc:
            logger.error("Failed to load asset %s: %s", path, exc)
            return None

    # ------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------
    @lru_cache(maxsize=None)
    def get_font(self, filename: str, size: int = 14, weight: str = "normal"):
        """
        Returns a CTkFont. Custom .ttf files are registered with Tkinter
        the first time they're requested (requires tkextrafont on some
        platforms; falls back to the family name if registration fails).
        """
        path = self.fonts_dir / filename
        family = path.stem

        if path.exists():
            try:
                from tkinter import font as tkfont
                loaded = tkfont.families()
                if family not in loaded:
                    self._register_font_file(path)
            except Exception as exc:
                logger.warning("Could not register font %s: %s", filename, exc)
        else:
            logger.warning("Font not found: %s - falling back to system default.", path)
            family = None  # let CTkFont use its default family

        return ctk.CTkFont(family=family, size=size, weight=weight)

    @staticmethod
    def _register_font_file(path: Path):
        """Best-effort custom font registration (platform-dependent)."""
        try:
            import ctypes
            if ctypes.windll:  # Windows only
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)
        except Exception:
            pass  # Non-Windows platforms typically need system-level install

    # ------------------------------------------------------------
    # Sounds (notification chimes, voice confirmation playback)
    # ------------------------------------------------------------
    def play_sound(self, filename: str):
        path = self.sounds_dir / filename
        if not path.exists():
            logger.warning("Sound not found: %s", path)
            return

        try:
            import threading
            threading.Thread(target=self._play_async, args=(path,), daemon=True).start()
        except Exception as exc:
            logger.error("Failed to play sound %s: %s", path, exc)

    @staticmethod
    def _play_async(path: Path):
        try:
            import playsound as ps
            ps.playsound(str(path))
        except ImportError:
            logger.warning("playsound not installed - add 'playsound' to requirements.txt")

    def speak(self, text: str):
        """Text-to-speech for voice attendance confirmation (uses pyttsx3)."""
        try:
            import pyttsx3
            if self._sound_engine is None:
                self._sound_engine = pyttsx3.init()
            self._sound_engine.say(text)
            self._sound_engine.runAndWait()
        except ImportError:
            logger.warning("pyttsx3 not installed - voice confirmation disabled.")
        except Exception as exc:
            logger.error("TTS playback failed: %s", exc)


# Singleton instance - import this everywhere instead of instantiating directly
assets = AssetManager()