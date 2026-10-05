"""
core/voice/voice_confirmation.py

Text-to-speech voice confirmation for attendance events, e.g.:
    "Welcome Jay Prajapati. Your attendance has been recorded successfully."

Runs on a single dedicated background worker thread with a queue, so
speech requests are always played one at a time in order - pyttsx3's
engine is not safe to call concurrently from multiple threads (calling
runAndWait() from two threads at once can crash or hang), which is
what utils/asset_manager.py's speak() does today if called from
multiple places in quick succession (e.g. two students recognized in
the same frame). This module is the fix: ui/pages/face_recognition_page.py
and core/attendance_engine/attendance_marker.py should call
voice_confirmation.confirm_attendance(name) instead of spinning up
their own ad-hoc threading.Thread(target=assets.speak, ...) calls.

Usage:
    from core.voice.voice_confirmation import voice_confirmation

    voice_confirmation.confirm_attendance("Jay Prajapati")
    voice_confirmation.already_marked("Jay Prajapati")
    voice_confirmation.mask_warning("Jay Prajapati")
    voice_confirmation.unknown_face()

    # Mute/unmute (e.g. a toggle button on the recognition page):
    voice_confirmation.set_enabled(False)

    # Custom message:
    voice_confirmation.speak_async("Please move closer to the camera.")
"""

import logging
import queue
import threading

logger = logging.getLogger("SmartAttendAI.core.voice.voice_confirmation")

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    logger.warning("pyttsx3 not installed - voice confirmation will be silently disabled.")

DEFAULT_RATE = 175        # words per minute
DEFAULT_VOLUME = 1.0       # 0.0 - 1.0
MAX_QUEUE_SIZE = 20        # drop oldest if the queue backs up (e.g. many students in one frame)


# ------------------------------------------------------------
# Message templates
# ------------------------------------------------------------
def _welcome_message(name: str) -> str:
    return f"Welcome {name}. Your attendance has been recorded successfully."


def _already_marked_message(name: str) -> str:
    return f"{name}, your attendance was already recorded today."


def _mask_warning_message(name: str) -> str:
    return f"{name}, please remove your mask for attendance verification."


def _liveness_retry_message() -> str:
    return "Please blink or move slightly to confirm you are present."


def _unknown_face_message() -> str:
    return "Face not recognized. Please try again or contact your administrator."


def _qr_backup_message(name: str) -> str:
    return f"QR code verified. Welcome {name}. Attendance recorded."


class VoiceConfirmation:
    """
    Queued TTS speaker: one background worker thread pulls messages
    off a queue and speaks them one at a time via pyttsx3, so callers
    never block on speech and concurrent requests never collide.
    """

    def __init__(self, rate: int = DEFAULT_RATE, volume: float = DEFAULT_VOLUME):
        self.rate = rate
        self.volume = volume
        self._enabled = PYTTSX3_AVAILABLE

        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._engine = None
        self._worker_thread = None
        self._stop_event = threading.Event()

        if PYTTSX3_AVAILABLE:
            self._start_worker()

    def _start_worker(self):
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        try:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            self._engine.setProperty("volume", self.volume)
        except Exception as exc:
            logger.error("Failed to initialize TTS engine - voice confirmation disabled: %s", exc)
            self._enabled = False
            return

        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if text is None:  # sentinel for shutdown
                break

            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                logger.error("TTS playback failed for message '%s': %s", text, exc)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------
    # Enable / disable / configuration
    # ------------------------------------------------------------
    def is_available(self) -> bool:
        return PYTTSX3_AVAILABLE

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled and PYTTSX3_AVAILABLE
        if not enabled:
            self.clear_queue()

    def set_rate(self, rate: int):
        self.rate = rate
        if self._engine:
            try:
                self._engine.setProperty("rate", rate)
            except Exception as exc:
                logger.warning("Could not update TTS rate: %s", exc)

    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.0, volume))
        if self._engine:
            try:
                self._engine.setProperty("volume", self.volume)
            except Exception as exc:
                logger.warning("Could not update TTS volume: %s", exc)

    def list_voices(self) -> list:
        """Returns available system TTS voices (id, name) for a voice-selection dropdown, if desired."""
        if not self._engine:
            return []
        try:
            return [(v.id, v.name) for v in self._engine.getProperty("voices")]
        except Exception as exc:
            logger.warning("Could not list TTS voices: %s", exc)
            return []

    def set_voice(self, voice_id: str):
        if self._engine:
            try:
                self._engine.setProperty("voice", voice_id)
            except Exception as exc:
                logger.warning("Could not set TTS voice: %s", exc)

    # ------------------------------------------------------------
    # Core speak methods
    # ------------------------------------------------------------
    def speak_async(self, text: str):
        """Queues a message for playback without blocking the caller."""
        if not self._enabled or not text:
            return

        try:
            self._queue.put_nowait(text)
        except queue.Full:
            # Drop the oldest queued message to make room, rather than
            # blocking the caller (e.g. the camera loop) or losing the
            # newest, most relevant confirmation.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(text)
            except queue.Full:
                logger.warning("Voice queue full - dropping message: %s", text)

    def clear_queue(self):
        """Discards any pending (not-yet-spoken) messages, e.g. when a session ends."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def shutdown(self):
        """Stops the background worker thread cleanly (e.g. on app exit)."""
        self.clear_queue()
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)  # sentinel to unblock the worker's queue.get()
        except queue.Full:
            pass
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

    # ------------------------------------------------------------
    # Attendance-specific message shortcuts
    # ------------------------------------------------------------
    def confirm_attendance(self, name: str):
        self.speak_async(_welcome_message(name))

    def already_marked(self, name: str):
        self.speak_async(_already_marked_message(name))

    def mask_warning(self, name: str):
        self.speak_async(_mask_warning_message(name))

    def liveness_retry(self):
        self.speak_async(_liveness_retry_message())

    def unknown_face(self):
        self.speak_async(_unknown_face_message())

    def qr_backup_confirmed(self, name: str):
        self.speak_async(_qr_backup_message(name))


# Singleton instance - import this everywhere instead of instantiating directly
voice_confirmation = VoiceConfirmation()